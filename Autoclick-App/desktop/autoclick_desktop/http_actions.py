import errno
import json
import math
import multiprocessing
import re
import select
import socket
import ssl
import time
import urllib.parse
from dataclasses import dataclass
from threading import Event
from typing import Callable, Mapping, Protocol, Sequence

from pydantic import JsonValue

from autoclick_desktop.bot_schema import validate_finite_json
from autoclick_desktop.execution_errors import ExecutionCancelled, ExecutionErrorCode, HandlerError
from autoclick_desktop.execution_models import ResolvedAction


HTTP_CANCEL_POLL_SECONDS = 0.05
MAX_HTTP_HEADER_BYTES = 256 * 1024
MAX_HTTP_RESPONSE_BODY_BYTES = 10 * 1024 * 1024
MAX_HTTP_CHUNK_LINE_BYTES = 8 * 1024
MAX_HTTP_TRAILER_LINE_BYTES = 8 * 1024
MAX_HTTP_TRAILER_BYTES = 64 * 1024
Address = tuple[int, int, int, str, tuple[object, ...]]
Resolver = Callable[[str, int], Sequence[Address]]
DnsWorkerTarget = Callable[[object, str, int], None]
_HTTP_TOKEN = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_MANAGED_REQUEST_HEADERS = frozenset({
    "connection",
    "content-length",
    "proxy-connection",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
})


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


class HttpResponseTooLargeError(OSError):
    pass


class HttpMalformedResponseError(OSError):
    pass


class HttpAdapter(Protocol):
    def request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
        cancel_event: Event,
    ) -> HttpResponse: ...


def _system_resolver(host: str, port: int) -> Sequence[Address]:
    """Synchronous resolver retained as the injectable resolver contract."""
    try:
        socket.inet_pton(socket.AF_INET, host)
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (host, port))]
    except OSError:
        try:
            socket.inet_pton(socket.AF_INET6, host)
            return [(socket.AF_INET6, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (host, port, 0, 0))]
        except OSError:
            return socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)


def _dns_worker(connection: object, host: str, port: int) -> None:
    """Spawn-safe DNS target; the parent owns its hard cancellation boundary."""
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        connection.send(("ok", addresses))  # type: ignore[attr-defined]
    except BaseException:
        try:
            connection.send(("error", None))  # type: ignore[attr-defined]
        except BaseException:
            pass
    finally:
        connection.close()  # type: ignore[attr-defined]


def _numeric_addresses(host: str, port: int) -> Sequence[Address] | None:
    try:
        socket.inet_pton(socket.AF_INET, host)
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (host, port))]
    except OSError:
        try:
            socket.inet_pton(socket.AF_INET6, host)
            return [(socket.AF_INET6, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (host, port, 0, 0))]
        except OSError:
            return None


def _stop_process(process: object) -> None:
    if process.is_alive():  # type: ignore[attr-defined]
        process.terminate()  # type: ignore[attr-defined]
    process.join(1)  # type: ignore[attr-defined]
    if process.is_alive():  # type: ignore[attr-defined]
        process.kill()  # type: ignore[attr-defined]
        process.join()  # type: ignore[attr-defined]


def _has_disallowed_control(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)


def _scalar_text(value: object, *, allow_none: bool = False) -> str:
    if value is None and allow_none:
        return ""
    if not isinstance(value, (str, int, float, bool)):
        raise ValueError("HTTP value must be scalar")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("HTTP value must be finite")
    text = str(value)
    if _has_disallowed_control(text):
        raise ValueError("HTTP value contains a control character")
    return text


def _validated_headers(
    headers: Mapping[object, object], *, allow_managed: bool = False
) -> dict[str, str]:
    result: dict[str, str] = {}
    normalized_names: set[str] = set()
    for raw_name, raw_value in headers.items():
        if not isinstance(raw_name, str) or _HTTP_TOKEN.fullmatch(raw_name) is None:
            raise ValueError("HTTP header name is invalid")
        normalized_name = raw_name.casefold()
        if normalized_name in normalized_names:
            raise ValueError("HTTP header names must be unique")
        if not allow_managed and normalized_name in _MANAGED_REQUEST_HEADERS:
            raise ValueError("HTTP framing header is managed by the transport")
        normalized_names.add(normalized_name)
        value = _scalar_text(raw_value)
        try:
            value.encode("iso-8859-1")
        except UnicodeEncodeError:
            raise ValueError("HTTP header value is not encodable") from None
        result[raw_name] = value
    return result


def _validated_query(query: Mapping[object, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for raw_name, raw_value in query.items():
        name = _scalar_text(raw_name)
        if isinstance(raw_value, list):
            result[name] = [
                None if item is None else _scalar_text(item)
                for item in raw_value
            ]
        else:
            result[name] = None if raw_value is None else _scalar_text(raw_value)
    return result


class CancellableHttpAdapter:
    def __init__(
        self,
        *,
        resolver: Resolver | None = None,
        _dns_worker_target: DnsWorkerTarget = _dns_worker,
        max_response_body_bytes: int = MAX_HTTP_RESPONSE_BODY_BYTES,
    ) -> None:
        if (
            not isinstance(max_response_body_bytes, int)
            or isinstance(max_response_body_bytes, bool)
            or max_response_body_bytes < 1
        ):
            raise ValueError("invalid HTTP response body limit")
        self._resolver = resolver
        self._dns_worker_target = _dns_worker_target
        self._max_response_body_bytes = max_response_body_bytes

    def _resolve(
        self,
        host: str,
        port: int,
        deadline: float,
        cancel_event: Event,
    ) -> Sequence[Address]:
        numeric = _numeric_addresses(host, port)
        if numeric is not None:
            return numeric
        if self._resolver is not None:
            addresses = self._resolver(host, port)
            if cancel_event.is_set():
                raise ExecutionCancelled()
            if time.monotonic() >= deadline:
                raise TimeoutError("HTTP request timed out")
            return addresses

        context = multiprocessing.get_context("spawn")
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(
            target=self._dns_worker_target,
            args=(sender, host, port),
            name="autoclick-dns-resolver",
            daemon=False,
        )
        started = False
        try:
            process.start()
            started = True
            sender.close()
            while True:
                if cancel_event.is_set():
                    raise ExecutionCancelled()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("HTTP request timed out")
                if receiver.poll(min(HTTP_CANCEL_POLL_SECONDS, remaining)):
                    status, payload = receiver.recv()
                    if status != "ok":
                        raise OSError("HTTP address resolution failed")
                    return payload
                if not process.is_alive():
                    raise OSError("HTTP address resolution failed")
        finally:
            receiver.close()
            sender.close()
            if started:
                _stop_process(process)

    def request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
        cancel_event: Event,
    ) -> HttpResponse:
        parts = urllib.parse.urlsplit(url)
        host = parts.hostname
        if host is None:
            raise ValueError("HTTP URL has no host")
        port = parts.port or (443 if parts.scheme == "https" else 80)
        deadline = time.monotonic() + timeout
        if _HTTP_TOKEN.fullmatch(method) is None or _has_disallowed_control(url):
            raise ValueError("HTTP request framing is invalid")
        headers = _validated_headers(headers)
        addresses = self._resolve(host, port, deadline, cancel_event)
        last_error: OSError | None = None
        for family, socktype, protocol, _canonical, address in addresses:
            connection: socket.socket | ssl.SSLSocket | None = None
            try:
                connection = socket.socket(family, socktype, protocol)
                connection.setblocking(False)
                result = connection.connect_ex(address)
                if result not in {0, errno.EINPROGRESS, errno.EWOULDBLOCK, errno.EALREADY}:
                    raise OSError(result, "HTTP connection failed")
                if result != 0:
                    self._wait(connection, deadline, cancel_event, write=True)
                    error = connection.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                    if error:
                        raise OSError(error, "HTTP connection failed")
                if parts.scheme == "https":
                    connection = ssl.create_default_context().wrap_socket(
                        connection, server_hostname=host, do_handshake_on_connect=False
                    )
                    connection.setblocking(False)
                    self._handshake(connection, deadline, cancel_event)
                target = urllib.parse.urlunsplit(("", "", parts.path or "/", parts.query, ""))
                request_headers = {**headers}
                if not any(name.casefold() == "host" for name in request_headers):
                    default_port = 443 if parts.scheme == "https" else 80
                    host_literal = f"[{host}]" if ":" in host else host
                    request_headers["Host"] = host_literal if port == default_port else f"{host_literal}:{port}"
                request_headers["Connection"] = "close"
                if body is not None:
                    request_headers["Content-Length"] = str(len(body))
                request_headers = _validated_headers(request_headers, allow_managed=True)
                encoded_headers = "".join(f"{name}: {value}\r\n" for name, value in request_headers.items())
                payload = f"{method} {target} HTTP/1.1\r\n{encoded_headers}\r\n".encode("iso-8859-1") + (body or b"")
                self._send_all(connection, payload, deadline, cancel_event)
                return self._read_response(connection, method, deadline, cancel_event)
            except ExecutionCancelled:
                raise
            except HttpResponseTooLargeError:
                raise
            except OSError as error:
                last_error = error
            finally:
                if connection is not None:
                    try:
                        connection.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                    connection.close()
        raise last_error or OSError("HTTP address resolution returned no addresses")

    @staticmethod
    def _wait(
        connection: socket.socket,
        deadline: float,
        cancel_event: Event,
        *,
        read: bool = False,
        write: bool = False,
    ) -> None:
        while True:
            if cancel_event.is_set():
                raise ExecutionCancelled()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("HTTP request timed out")
            readable, writable, exceptional = select.select(
                [connection] if read else [],
                [connection] if write else [],
                [connection],
                min(HTTP_CANCEL_POLL_SECONDS, remaining),
            )
            if exceptional:
                raise OSError("HTTP socket failed")
            if readable or writable:
                return

    def _handshake(self, connection: ssl.SSLSocket, deadline: float, cancel_event: Event) -> None:
        while True:
            try:
                connection.do_handshake()
                return
            except ssl.SSLWantReadError:
                self._wait(connection, deadline, cancel_event, read=True)
            except ssl.SSLWantWriteError:
                self._wait(connection, deadline, cancel_event, write=True)

    def _send_all(self, connection: socket.socket, payload: bytes, deadline: float, cancel_event: Event) -> None:
        view = memoryview(payload)
        while view:
            self._wait(connection, deadline, cancel_event, write=True)
            try:
                sent = connection.send(view)
            except ssl.SSLWantReadError:
                self._wait(connection, deadline, cancel_event, read=True)
                continue
            except (ssl.SSLWantWriteError, BlockingIOError):
                continue
            if sent == 0:
                raise OSError("HTTP socket closed while sending")
            view = view[sent:]

    def _receive(
        self,
        connection: socket.socket,
        deadline: float,
        cancel_event: Event,
        max_bytes: int = 64 * 1024,
    ) -> bytes:
        while True:
            self._wait(connection, deadline, cancel_event, read=True)
            try:
                return connection.recv(max_bytes)
            except ssl.SSLWantReadError:
                continue
            except ssl.SSLWantWriteError:
                self._wait(connection, deadline, cancel_event, write=True)
            except BlockingIOError:
                continue

    def _read_response(
        self, connection: socket.socket, method: str, deadline: float, cancel_event: Event
    ) -> HttpResponse:
        buffer = bytearray()
        while b"\r\n\r\n" not in buffer:
            chunk = self._receive(
                connection, deadline, cancel_event, MAX_HTTP_CHUNK_LINE_BYTES
            )
            if not chunk:
                raise OSError("HTTP response ended before headers")
            buffer.extend(chunk)
            if len(buffer) > MAX_HTTP_HEADER_BYTES:
                raise OSError("HTTP response headers are too large")
        raw_headers, initial_body = bytes(buffer).split(b"\r\n\r\n", 1)
        lines = raw_headers.decode("iso-8859-1").split("\r\n")
        status_parts = lines[0].split(" ", 2)
        if len(status_parts) < 2 or not status_parts[1].isdigit():
            raise OSError("HTTP response status is malformed")
        status = int(status_parts[1])
        headers: dict[str, str] = {}
        for line in lines[1:]:
            if ":" not in line:
                raise OSError("HTTP response header is malformed")
            name, value = line.split(":", 1)
            headers[name.strip()] = value.strip()
        lowered = {name.casefold(): value for name, value in headers.items()}
        if method == "HEAD" or status in {204, 304} or 100 <= status < 200:
            body = bytearray()
        elif "chunked" in lowered.get("transfer-encoding", "").casefold():
            body = self._read_chunked(connection, bytearray(initial_body), deadline, cancel_event)
        elif "content-length" in lowered:
            try:
                expected = int(lowered["content-length"])
            except ValueError:
                raise OSError("HTTP response content length is malformed") from None
            if expected < 0:
                raise OSError("HTTP response content length is malformed")
            if expected > self._max_response_body_bytes:
                raise HttpResponseTooLargeError("HTTP response body is too large")
            body = bytearray(initial_body[:expected])
            while len(body) < expected:
                chunk = self._receive(connection, deadline, cancel_event)
                if not chunk:
                    raise OSError("HTTP response body ended early")
                body.extend(chunk[:expected - len(body)])
        else:
            if len(initial_body) > self._max_response_body_bytes:
                raise HttpResponseTooLargeError("HTTP response body is too large")
            body = bytearray(initial_body)
            while True:
                chunk = self._receive(connection, deadline, cancel_event)
                if not chunk:
                    break
                if len(body) + len(chunk) > self._max_response_body_bytes:
                    raise HttpResponseTooLargeError("HTTP response body is too large")
                body.extend(chunk)
        return HttpResponse(status, headers, bytes(body))

    def _read_chunked(
        self, connection: socket.socket, initial: bytearray, deadline: float, cancel_event: Event
    ) -> bytearray:
        pending = initial
        decoded = bytearray()

        def read_line(limit: int) -> bytes:
            while True:
                marker = pending.find(b"\r\n")
                if marker >= 0:
                    if marker > limit:
                        raise HttpMalformedResponseError("chunked HTTP framing line is too large")
                    line = bytes(pending[:marker])
                    del pending[:marker + 2]
                    return line
                if len(pending) > limit:
                    raise HttpMalformedResponseError("chunked HTTP framing line is too large")
                chunk = self._receive(
                    connection,
                    deadline,
                    cancel_event,
                    limit + 2 - len(pending),
                )
                if not chunk:
                    raise HttpMalformedResponseError("chunked HTTP response ended early")
                pending.extend(chunk)

        while True:
            size_line = read_line(MAX_HTTP_CHUNK_LINE_BYTES)
            size_text = size_line.split(b";", 1)[0]
            extension = size_line[len(size_text):]
            if (
                not size_text
                or re.fullmatch(rb"[0-9A-Fa-f]+", size_text) is None
                or any(byte < 32 or byte == 127 for byte in extension)
            ):
                raise HttpMalformedResponseError("chunked HTTP response is malformed")
            size = int(size_text, 16)
            if size == 0:
                trailer_bytes = 0
                while True:
                    trailer = read_line(MAX_HTTP_TRAILER_LINE_BYTES)
                    trailer_bytes += len(trailer) + 2
                    if trailer_bytes > MAX_HTTP_TRAILER_BYTES:
                        raise HttpMalformedResponseError("chunked HTTP trailers are too large")
                    if not trailer:
                        break
                    if b":" not in trailer:
                        raise HttpMalformedResponseError("chunked HTTP trailer is malformed")
                    name, value = trailer.split(b":", 1)
                    if _HTTP_TOKEN.fullmatch(name.decode("iso-8859-1")) is None or any(
                        (byte < 32 and byte != 9) or byte == 127 for byte in value
                    ):
                        raise HttpMalformedResponseError("chunked HTTP trailer is malformed")
                return decoded
            if len(decoded) + size > self._max_response_body_bytes:
                raise HttpResponseTooLargeError("HTTP response body is too large")
            while len(pending) < size + 2:
                chunk = self._receive(
                    connection, deadline, cancel_event, size + 2 - len(pending)
                )
                if not chunk:
                    raise HttpMalformedResponseError("chunked HTTP response ended early")
                pending.extend(chunk)
            decoded.extend(pending[:size])
            if pending[size:size + 2] != b"\r\n":
                raise HttpMalformedResponseError("chunked HTTP response is malformed")
            del pending[:size + 2]


# Retain the public adapter name used by existing injection/tests without urllib.
UrllibHttpAdapter = CancellableHttpAdapter


def handle_http_request(
    action: ResolvedAction, adapter: HttpAdapter, cancel_event: Event | None = None
) -> JsonValue:
    method = action.params["method"]
    url = action.params["url"]
    headers_value = action.params.get("headers", {})
    query_value = action.params.get("query", {})
    timeout_ms = action.params["timeoutMs"]
    if (
        not isinstance(method, str)
        or not isinstance(url, str)
        or not isinstance(headers_value, dict)
        or not isinstance(query_value, dict)
        or not isinstance(timeout_ms, (int, float))
        or isinstance(timeout_ms, bool)
        or timeout_ms <= 0
    ):
        raise HandlerError(ExecutionErrorCode.HTTP_REQUEST_FAILED)
    cancellation = cancel_event or Event()
    try:
        if cancellation.is_set():
            raise ExecutionCancelled()
        if _HTTP_TOKEN.fullmatch(method) is None or _has_disallowed_control(url):
            raise ValueError("HTTP request framing is invalid")
        headers = _validated_headers(headers_value)
        query = urllib.parse.urlencode(_validated_query(query_value), doseq=True)
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            raise ValueError("invalid HTTP URL")
        url = urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, "&".join(filter(None, (parts.query, query))), ""))
        body_value = action.params.get("body")
        body: bytes | None = None
        if body_value is not None:
            if isinstance(body_value, str):
                body = body_value.encode("utf-8")
            else:
                body = json.dumps(body_value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
                if not any(key.casefold() == "content-type" for key in headers):
                    headers["Content-Type"] = "application/json"
        response = adapter.request(method, url, headers, body, timeout_ms / 1000, cancellation)
        if cancellation.is_set():
            raise ExecutionCancelled()
        text = response.body.decode("utf-8", errors="replace")
        decoded: JsonValue = text
        try:
            candidate = json.loads(
                text,
                parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
            )
            decoded = validate_finite_json(candidate)
        except (json.JSONDecodeError, TypeError, ValueError, RecursionError):
            decoded = text
        return {"status": response.status, "headers": dict(response.headers), "body": decoded}
    except HandlerError:
        raise
    except HttpResponseTooLargeError:
        raise HandlerError(ExecutionErrorCode.HTTP_RESPONSE_TOO_LARGE) from None
    except Exception:
        raise HandlerError(ExecutionErrorCode.HTTP_REQUEST_FAILED) from None
