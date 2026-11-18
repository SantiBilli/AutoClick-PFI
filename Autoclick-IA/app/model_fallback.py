"""Request-scoped model recovery without mixing streams or changing prompts."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import logging

import httpx

from app.config import Settings
from app.ollama_client import (
    GenerationTimeoutError, MalformedOllamaResponseError, ModelNotFoundError,
    OllamaClient, OllamaHealth, OllamaUnavailableError,
)
from app.prompt import PromptTooLargeError
from app.token_budget import TokenMetadataError

LOG = logging.getLogger(__name__)


@dataclass
class Selection:
    fallback: bool = False
    usage_known: bool = True


def _recoverable(error: Exception) -> bool:
    status_error = error if isinstance(error, httpx.HTTPStatusError) else error.__cause__
    if isinstance(status_error, httpx.HTTPStatusError):
        return status_error.response.status_code in {404, 408, 429} or status_error.response.status_code >= 500
    return isinstance(error, (
        ModelNotFoundError, OllamaUnavailableError, GenerationTimeoutError,
        httpx.ConnectError, httpx.NetworkError, httpx.TimeoutException,
    ))


class FallbackOllama:
    def __init__(self, settings: Settings, primary=None, fallback=None):
        if not settings.ollama_fallback_model:
            raise ValueError("fallback model is required")
        self.settings = settings
        self.primary = primary or OllamaClient(settings)
        self.fallback = fallback or OllamaClient(settings.model_copy(update={
            "ollama_model": settings.ollama_fallback_model,
            "ollama_fallback_model": None,
        }))
        self._selection: ContextVar[Selection | None] = ContextVar("model_selection", default=None)

    @contextmanager
    def request_scope(self):
        token = self._selection.set(Selection())
        try:
            yield
        finally:
            self._selection.reset(token)

    @property
    def active_model(self) -> str:
        selection = self._selection.get()
        return self.settings.ollama_fallback_model if selection and selection.fallback else self.settings.ollama_model

    @property
    def fallback_used(self) -> bool:
        selection = self._selection.get()
        return bool(selection and selection.fallback)

    @property
    def usage_known(self) -> bool:
        selection = self._selection.get()
        return selection.usage_known if selection else True

    async def close(self):
        try:
            await self.primary.close()
        finally:
            await self.fallback.close()

    async def health(self) -> OllamaHealth:
        primary = await self.primary.health()
        fallback = await self.fallback.health()
        active = (self.settings.ollama_model if primary.model_installed else
                  self.settings.ollama_fallback_model if fallback.model_installed else None)
        return OllamaHealth(
            primary.reachable or fallback.reachable,
            primary.model_installed or fallback.model_installed,
            active_model=active, fallback_installed=fallback.model_installed,
        )

    def _switch(self, selection: Selection, error: Exception):
        selection.fallback = True
        # Do not log prompts, credentials or provider error bodies.
        LOG.warning("model_fallback reason=%s", type(error).__name__)

    async def get_token_counter(self):
        selection = self._selection.get() or Selection()
        if selection.fallback:
            return await self.fallback.get_token_counter()
        try:
            async with asyncio.timeout(self.settings.ollama_fallback_start_timeout_seconds):
                return await self.primary.get_token_counter()
        except Exception as error:
            if not (_recoverable(error) or isinstance(error, (
                TimeoutError, MalformedOllamaResponseError, TokenMetadataError,
            ))):
                raise
            self._switch(selection, error)
            return await self.fallback.get_token_counter()

    async def stream_chat(self, messages, *, timeout_seconds: float, **kwargs):
        selection = self._selection.get() or Selection()
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        clients = [self.fallback] if selection.fallback else [self.primary, self.fallback]
        for client in clients:
            is_fallback = client is self.fallback
            emitted = False
            stream = None
            request_timeout = asyncio.timeout_at(deadline)
            try:
                async with request_timeout:
                    if is_fallback:
                        counter = await client.get_token_counter()
                        count = counter.count_chat(messages, think=kwargs.get("think", False))
                        if count > self.settings.ollama_context_length - self.settings.generation_reserve_tokens:
                            raise PromptTooLargeError("fallback input exceeds the model context")
                    remaining = deadline - asyncio.get_running_loop().time()
                    options = dict(kwargs)
                    if not is_fallback:
                        options["first_response_timeout_seconds"] = min(
                            self.settings.ollama_fallback_start_timeout_seconds, remaining / 2,
                        )
                    stream = client.stream_chat(messages, timeout_seconds=remaining, **options)
                    async for event in stream:
                        emitted = True
                        yield event
                return
            except Exception as error:
                if isinstance(error, TimeoutError):
                    error = GenerationTimeoutError()
                if request_timeout.expired() or is_fallback or emitted or not _recoverable(error) or asyncio.get_running_loop().time() >= deadline:
                    raise error
                if not isinstance(error, ModelNotFoundError):
                    # An aborted inference has no terminal token totals.
                    selection.usage_known = False
                self._switch(selection, error)
            finally:
                if stream is not None:
                    await stream.aclose()


class ModelFallbackMiddleware:
    def __init__(self, app, client: FallbackOllama):
        self.app, self.client = app, client

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        with self.client.request_scope():
            await self.app(scope, receive, send)
