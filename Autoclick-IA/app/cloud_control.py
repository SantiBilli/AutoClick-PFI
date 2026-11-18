"""Cloud admission, actual token metering and durable usage reporting.

No prompts, responses, JWTs or authorization tickets are written to the outbox.
Only the trusted worker (SigV4, short-lived IAM credentials) can settle usage.
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import httpx

from app.ollama_client import OllamaUsage

LOG = logging.getLogger(__name__)


@dataclass
class Meter:
    request_id: str
    checkpoint: Callable[[], None] | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    known: bool = True
    calls: int = 0


active_meter: contextvars.ContextVar[Meter | None] = contextvars.ContextVar('cloud_meter', default=None)


class MeteredOllama:
    def __init__(self, client, settings):
        self.client, self.settings = client, settings

    def __getattr__(self, name):
        return getattr(self.client, name)

    async def stream_chat(self, messages, **kwargs):
        meter = active_meter.get()
        if meter is None:
            async for event in self.client.stream_chat(messages, **kwargs):
                yield event
            return
        meter.calls += 1
        complete = False
        stream = self.client.stream_chat(messages, **kwargs)
        try:
            async for event in stream:
                if isinstance(event, OllamaUsage):
                    complete = True
                    if event.input_tokens is None or event.output_tokens is None:
                        meter.known = False
                    meter.input_tokens += event.input_tokens or 0
                    meter.output_tokens += event.output_tokens or 0
                    if meter.checkpoint:
                        meter.checkpoint()
                yield event
        finally:
            await stream.aclose()
            if not getattr(self.client, "usage_known", True):
                meter.known = False
                if meter.checkpoint:
                    meter.checkpoint()
            if not complete:
                meter.known = False
                if meter.checkpoint:
                    meter.checkpoint()


def usage_payload(meter, *, known=None):
    return {'requestId': meter.request_id, 'inputTokens': meter.input_tokens,
            'outputTokens': meter.output_tokens, 'usageKnown': meter.known if known is None else known}


class UsageOutbox:
    def __init__(self, path: str):
        target = Path(path).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        self.path = str(target)
        with self.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS reports (request_id TEXT PRIMARY KEY, path TEXT NOT NULL, payload TEXT NOT NULL, created REAL NOT NULL)')

    def connection(self):
        return sqlite3.connect(self.path, timeout=5)

    def put(self, request_id, path, payload):
        with self.connection() as db:
            # The final payload replaces the recovery marker. One row per request.
            db.execute('INSERT INTO reports VALUES (?,?,?,?) ON CONFLICT(request_id) DO UPDATE SET path=excluded.path,payload=excluded.payload',
                       (request_id, path, json.dumps(payload), time.time()))

    def pending(self):
        with self.connection() as db:
            return db.execute('SELECT request_id,path,payload FROM reports ORDER BY created LIMIT 100').fetchall()

    def remove(self, request_id):
        with self.connection() as db:
            db.execute('DELETE FROM reports WHERE request_id=?', (request_id,))


class ControlClient:
    def __init__(self, settings):
        import botocore.session
        self.url = settings.autoclick_cloud_api_url.rstrip('/')
        self.region = settings.autoclick_cloud_region
        self.session = botocore.session.Session(profile=settings.autoclick_cloud_aws_profile or None)
        self.http = httpx.AsyncClient(timeout=25)

    def sign(self, path, body):
        from botocore.auth import SigV4Auth
        from botocore.awsrequest import AWSRequest
        credentials = self.session.get_credentials()
        if credentials is None:
            raise RuntimeError('Worker credentials are not configured')
        req = AWSRequest(method='POST', url=self.url + path, data=body, headers={'Content-Type': 'application/json'})
        SigV4Auth(credentials.get_frozen_credentials(), 'execute-api', self.region).add_auth(req)
        return dict(req.headers)

    async def post(self, path, payload):
        body = json.dumps(payload).encode()
        headers = await asyncio.to_thread(self.sign, path, body)
        response = await self.http.post(self.url + path, content=body, headers=headers)
        response.raise_for_status()
        return response.json()


class CloudControl:
    def __init__(self, settings):
        self.settings = settings
        self.client = ControlClient(settings)
        self.outbox = UsageOutbox(settings.autoclick_cloud_outbox)
        self.running: set[str] = set()
        self.report_lock = asyncio.Lock()
        self.capacity = asyncio.Semaphore(settings.autoclick_cloud_concurrency)
        self.task: asyncio.Task | None = None

    async def start(self):
        self.task = asyncio.create_task(self.report_loop())

    async def close(self):
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        await self.flush()
        await self.client.http.aclose()

    async def report_loop(self):
        while True:
            await self.flush()
            await asyncio.sleep(15)

    async def flush(self):
        async with self.report_lock:
            for rid, path, payload in self.outbox.pending():
                if rid in self.running:
                    continue
                try:
                    await self.client.post(path, json.loads(payload))
                    self.outbox.remove(rid)
                except Exception:
                    LOG.warning('cloud_usage_report_pending request_id=%s', rid)


class CloudAuthorizationMiddleware:
    def __init__(self, app, control: CloudControl):
        self.app, self.control = app, control

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope.get('path') != '/v1/chat/stream' or scope.get('method') == 'OPTIONS':
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get('headers', []))
        try:
            rid = str(uuid.UUID(headers.get(b'x-autoclick-request-id', b'').decode()))
            ticket = headers.get(b'authorization', b'').decode().removeprefix('Bearer ')
            if not 32 <= len(ticket) <= 128:
                raise ValueError('Invalid authorization')
        except (ValueError, UnicodeError):
            await self.reject(send, 401, 'AUTHORIZATION_REQUIRED', 'Se requiere autorización de AutoClick para usar IA.')
            return
        if self.control.capacity.locked():
            await self.reject(send, 503, 'AI_BUSY', 'El servidor de IA está ocupado. Volvé a intentar.')
            return
        async with self.control.capacity:
            try:
                claim = {'requestId': rid, 'authorization': ticket, 'claimId': str(uuid.uuid4())}
                for attempt in range(3):
                    try:
                        await self.control.client.post('/v1/ai/validate', claim)
                        break
                    except httpx.TransportError:
                        if attempt == 2:
                            raise
                        await asyncio.sleep(0.2 * (attempt + 1))
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    await self.reject(send, 429, 'QUOTA_EXCEEDED', 'No quedan tokens disponibles en la organización o el área.')
                    return
                status = 403 if e.response.status_code < 500 else 503
                await self.reject(send, status, 'AUTHORIZATION_REJECTED', 'No se pudo validar la autorización de IA. Iniciá una nueva solicitud.')
                return
            except Exception:
                await self.reject(send, 503, 'CONTROL_UNAVAILABLE', 'No se pudo conectar con el servicio de autorización.')
                return
            meter = Meter(rid)
            # Persist measured subtotals; a crash never creates an estimated charge.
            meter.checkpoint = lambda: self.control.outbox.put(rid, '/v1/ai/fail', usage_payload(meter, known=False))
            self.control.running.add(rid)
            try:
                meter.checkpoint()
            except Exception:
                self.control.running.discard(rid)
                await self.reject(send, 503, 'REPORT_STORAGE_UNAVAILABLE', 'No se pudo iniciar el registro de consumo.')
                return
            context_token = active_meter.set(meter)
            scope.setdefault('state', {})['cloud_request_id'] = rid
            terminal = False
            pending = b''
            finalized = False

            async def finalize():
                nonlocal finalized
                if finalized:
                    return
                path = '/v1/ai/complete' if terminal and meter.known else '/v1/ai/fail'
                payload = usage_payload(meter)
                self.control.outbox.put(rid, path, payload)
                finalized = True
                # Settle before Desktop sees done and can start the next query.
                # Keep the durable report for background retry on network failure.
                try:
                    await self.control.client.post(path, payload)
                    self.control.outbox.remove(rid)
                except Exception:
                    LOG.warning('cloud_usage_report_pending request_id=%s', rid)

            async def observe(message):
                nonlocal terminal, pending
                if message['type'] == 'http.response.body':
                    pending += message.get('body', b'')
                    while b'\n\n' in pending:
                        frame, pending = pending.split(b'\n\n', 1)
                        if b'event: done\n' in frame:
                            terminal = True
                            await finalize()
                        elif b'event: error\n' in frame:
                            await finalize()
                    # Never retain a whole response in the middleware.
                    if len(pending) > 131072:
                        pending = b''
                await send(message)

            try:
                await self.app(scope, receive, observe)
            finally:
                active_meter.reset(context_token)
                try:
                    if not finalized:
                        # On disconnect/cancellation, let the background task retry.
                        self.control.outbox.put(rid, '/v1/ai/fail', usage_payload(meter))
                finally:
                    self.control.running.discard(rid)

    @staticmethod
    async def reject(send, status, code, message):
        body = json.dumps({'code': code, 'message': message}).encode()
        await send({'type': 'http.response.start', 'status': status, 'headers': [(b'content-type', b'application/json')]})
        await send({'type': 'http.response.body', 'body': body})
