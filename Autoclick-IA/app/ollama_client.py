import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from app.config import (
    MAX_GENERATION_BYTES,
    MAX_GENERATION_CODE_POINTS,
    RUNTIME_CONTEXT_TOKENS,
    RUNTIME_OUTPUT_TOKENS,
    RUNTIME_CONVERSATIONAL_OUTPUT_TOKENS,
    Settings,
)
from app.token_budget import Qwen35TokenCounter, TokenMetadataError

MAX_SAFE_INTEGER = 9_007_199_254_740_991
MAX_FINISH_REASON_CHARS = 16
KNOWN_FINISH_REASONS = frozenset({"stop", "length", "load"})
MAX_TOOL_ARGUMENT_BYTES = MAX_GENERATION_BYTES
MAX_NDJSON_LINE_BYTES = 2 * MAX_GENERATION_BYTES


class OllamaError(Exception):
    pass


class OllamaUnavailableError(OllamaError):
    pass


class ModelNotFoundError(OllamaError):
    pass


class GenerationTimeoutError(OllamaError):
    pass


class MalformedOllamaResponseError(OllamaError):
    pass


@dataclass(frozen=True)
class OllamaHealth:
    reachable: bool
    model_installed: bool
    active_model: str | None = None
    fallback_installed: bool = False


@dataclass(frozen=True)
class OllamaFragment:
    kind: Literal["thinking", "content"]
    content: str


@dataclass(frozen=True)
class OllamaToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class OllamaUsage:
    input_tokens: int | None
    output_tokens: int | None
    finish_reason: str


OllamaStreamEvent = OllamaFragment | OllamaToolCall | OllamaUsage


class _ThinkingFilter:
    """Prefer Ollama's native channel and quarantine legacy tagged reasoning."""

    def __init__(self) -> None:
        self.native_thinking_seen = False
        self.answer_started = False
        self.pending_content = ""
        self.pending_bytes = 0
        self.tagged_reasoning = False

    def feed_thinking(self, content: str) -> list[OllamaFragment]:
        self.native_thinking_seen = True
        if not content or self.answer_started:
            return []
        return [OllamaFragment("thinking", content)]

    def feed_content(self, content: str) -> list[OllamaFragment]:
        if not content:
            return []
        if self.answer_started or self.native_thinking_seen:
            self.answer_started = True
            return [OllamaFragment("content", content)]

        try:
            content_bytes = len(content.encode("utf-8"))
        except UnicodeEncodeError as exc:
            self._clear_pending()
            raise MalformedOllamaResponseError(
                "invalid legacy thinking content"
            ) from exc
        if (
            len(self.pending_content) + len(content) > MAX_GENERATION_CODE_POINTS
            or self.pending_bytes + content_bytes > MAX_GENERATION_BYTES
        ):
            self._clear_pending()
            raise MalformedOllamaResponseError(
                "legacy thinking buffer exceeded bounds"
            )
        self.pending_content += content
        self.pending_bytes += content_bytes
        if "<think>" in self.pending_content:
            self.tagged_reasoning = True
        closing_index = self.pending_content.find("</think>")
        if closing_index < 0:
            return []

        reasoning = self.pending_content[:closing_index].replace("<think>", "")
        answer = self.pending_content[closing_index + len("</think>") :]
        self._clear_pending()
        fragments: list[OllamaFragment] = []
        if reasoning:
            fragments.append(OllamaFragment("thinking", reasoning))
        if answer:
            self.answer_started = True
            fragments.append(OllamaFragment("content", answer))
        return fragments

    def finish(self) -> list[OllamaFragment]:
        if not self.pending_content:
            return []
        pending = self.pending_content
        tagged_reasoning = self.tagged_reasoning
        self._clear_pending()
        if tagged_reasoning:
            return [OllamaFragment("thinking", pending.replace("<think>", ""))]
        self.answer_started = True
        return [OllamaFragment("content", pending)]

    def _clear_pending(self) -> None:
        self.pending_content = ""
        self.pending_bytes = 0
        self.tagged_reasoning = False


class OllamaClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        timeout = httpx.Timeout(
            connect=settings.autoclick_ai_connect_timeout_seconds,
            read=max(
                settings.autoclick_ai_home_timeout_seconds,
                settings.autoclick_ai_editor_timeout_seconds,
            ),
            write=settings.autoclick_ai_connect_timeout_seconds,
            pool=settings.autoclick_ai_connect_timeout_seconds,
        )
        self._client = client or httpx.AsyncClient(base_url=settings.ollama_base_url, timeout=timeout)
        self._owns_client = client is None
        self._token_counter: Qwen35TokenCounter | None = None
        self._token_counter_lock = asyncio.Lock()

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def get_token_counter(self) -> Qwen35TokenCounter:
        if self._token_counter is not None:
            return self._token_counter
        async with self._token_counter_lock:
            if self._token_counter is not None:
                return self._token_counter
            response = await self._client.post(
                "/api/show",
                json={"model": self.settings.ollama_model, "verbose": True},
            )
            if response.status_code == 404:
                raise ModelNotFoundError
            response.raise_for_status()
            try:
                payload = response.json()
            except ValueError as exc:
                raise MalformedOllamaResponseError(
                    "model tokenizer metadata is missing"
                ) from exc
            if not isinstance(payload, dict):
                raise MalformedOllamaResponseError("model tokenizer metadata is missing")
            model_info = payload.get("model_info")
            if not isinstance(model_info, dict):
                raise MalformedOllamaResponseError("model tokenizer metadata is missing")
            self._token_counter = Qwen35TokenCounter.from_model_info(model_info)
            return self._token_counter

    async def health(self) -> OllamaHealth:
        try:
            response = await self._client.get("/api/tags")
            response.raise_for_status()
            payload = response.json()
            models = payload.get("models")
            if not isinstance(models, list):
                raise MalformedOllamaResponseError("invalid tags response")
            names = {
                model.get("name")
                for model in models
                if isinstance(model, dict) and isinstance(model.get("name"), str)
            }
            if self.settings.ollama_model not in names:
                return OllamaHealth(True, False)
            try:
                await self.get_token_counter()
            except (
                ModelNotFoundError,
                MalformedOllamaResponseError,
                TokenMetadataError,
            ):
                return OllamaHealth(True, False)
            return OllamaHealth(True, True)
        except (httpx.ConnectError, httpx.NetworkError, httpx.TimeoutException):
            return OllamaHealth(False, False)
        except (httpx.HTTPStatusError, ValueError, MalformedOllamaResponseError):
            return OllamaHealth(False, False)

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        *,
        format_schema: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        think: bool = False,
        timeout_seconds: float,
        num_predict: int | None = None,
        first_response_timeout_seconds: float | None = None,
    ) -> AsyncIterator[OllamaStreamEvent]:
        stream = self._stream_chat(
            messages,
            format_schema=format_schema,
            tools=tools,
            think=think,
            timeout_seconds=timeout_seconds,
            num_predict=num_predict,
            first_response_timeout_seconds=first_response_timeout_seconds,
        )
        try:
            async for event in stream:
                yield event
        finally:
            await stream.aclose()

    async def _stream_chat(
        self,
        messages: list[dict[str, Any]],
        *,
        format_schema: dict[str, Any] | None,
        tools: list[dict[str, Any]] | None = None,
        think: bool,
        timeout_seconds: float,
        num_predict: int | None = None,
        first_response_timeout_seconds: float | None = None,
    ) -> AsyncIterator[OllamaStreamEvent]:
        allowed_tool_names = {
            function["function"]["name"]
            for function in tools or []
            if isinstance(function, dict)
            and isinstance(function.get("function"), dict)
            and isinstance(function["function"].get("name"), str)
        }
        predict_tokens = num_predict if num_predict is not None else self.settings.ollama_max_output_tokens
        payload: dict[str, Any] = {
            "model": self.settings.ollama_model,
            "messages": messages,
            "stream": True,
            "think": think,
            "options": {
                "num_ctx": self.settings.ollama_context_length,
                "num_predict": predict_tokens,
                # Qwen's thinking mode must not use greedy decoding, which
                # can get stuck in repeated reasoning. Structured non-thinking
                # recipes keep their established deterministic sampling.
                "temperature": 0.6 if think else self.settings.ollama_temperature,
                # Structured bots must repeat exact IDs, field names and literals.
                # Do not inherit creative repetition penalties from a model alias.
                "presence_penalty": 0,
                "frequency_penalty": 0,
                "repeat_penalty": 1,
            },
        }
        if format_schema is not None:
            payload["format"] = format_schema
        if think:
            payload['options'].update(top_p=0.95, top_k=20, min_p=0)
        if self.settings.ollama_seed is not None:
            payload['options']['seed'] = self.settings.ollama_seed
        if tools:
            payload["tools"] = tools
        try:
            deadline = asyncio.get_running_loop().time() + timeout_seconds
            first_response_deadline = (
                min(deadline, asyncio.get_running_loop().time() + first_response_timeout_seconds)
                if first_response_timeout_seconds is not None else deadline
            )
            stack = AsyncExitStack()
            try:
                async with asyncio.timeout_at(first_response_deadline):
                    response = await stack.enter_async_context(
                        self._client.stream("POST", "/api/chat", json=payload)
                    )
                if response.status_code == 404:
                    raise ModelNotFoundError
                if response.status_code == 400 and payload.get("think"):
                    payload.pop("think", None)
                    async with asyncio.timeout_at(first_response_deadline):
                        response = await stack.enter_async_context(
                            self._client.stream("POST", "/api/chat", json=payload)
                        )
                if response.status_code == 404:
                    raise ModelNotFoundError
                response.raise_for_status()
                content_filter = _ThinkingFilter()
                usage: OllamaUsage | None = None
                async for line in _iter_ndjson_lines(response, deadline, first_response_deadline):
                    if line.endswith(b"\r"):
                        line = line[:-1]
                    if not line:
                        continue
                    try:
                        item: Any = json.loads(line)
                    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                        raise MalformedOllamaResponseError(
                            "invalid stream JSON"
                        ) from exc
                    if not isinstance(item, dict):
                        raise MalformedOllamaResponseError("invalid stream item")
                    if item.get("error"):
                        error = str(item["error"]).lower()
                        if "model" in error and (
                            "not found" in error or "pull" in error
                        ):
                            raise ModelNotFoundError
                        if any(term in error for term in (
                            "out of memory", "not enough memory", "insufficient memory",
                            "unable to allocate", "runner process has terminated",
                        )):
                            raise OllamaUnavailableError("model runner unavailable")
                        raise OllamaError("upstream generation error")
                    message = item.get("message", {})
                    if not isinstance(message, dict):
                        raise MalformedOllamaResponseError(
                            "invalid message fragment"
                        )
                    thinking = message.get("thinking")
                    content = message.get("content")
                    if thinking is not None and not isinstance(thinking, str):
                        raise MalformedOllamaResponseError(
                            "invalid thinking fragment"
                        )
                    if content is not None and not isinstance(content, str):
                        raise MalformedOllamaResponseError(
                            "invalid content fragment"
                        )
                    if thinking:
                        for fragment in content_filter.feed_thinking(thinking):
                            yield fragment
                    if content:
                        for fragment in content_filter.feed_content(content):
                            yield fragment
                    tool_calls = message.get("tool_calls")
                    if tool_calls and isinstance(tool_calls, list):
                        for tc in tool_calls:
                            if isinstance(tc, dict):
                                fn = tc.get("function", {})
                                name = fn.get("name", "")
                                args = fn.get("arguments", {})
                                if name not in allowed_tool_names:
                                    raise MalformedOllamaResponseError(
                                        "unexpected tool call"
                                    )
                                yield OllamaToolCall(
                                    name=name,
                                    arguments=_parse_tool_arguments(args),
                                )
                    if tool_calls is not None and not isinstance(tool_calls, list):
                        raise MalformedOllamaResponseError("invalid tool calls")
                    if item.get("done") is True:
                        input_tokens = _optional_token_count(
                            item, "prompt_eval_count"
                        )
                        output_tokens = _optional_token_count(item, "eval_count")
                        finish_reason = item.get("done_reason", "stop")
                        if (
                            not isinstance(finish_reason, str)
                            or not finish_reason.strip()
                            or len(finish_reason) > MAX_FINISH_REASON_CHARS
                            or finish_reason not in KNOWN_FINISH_REASONS
                        ):
                            raise MalformedOllamaResponseError(
                                "invalid finish reason"
                            )
                        usage = OllamaUsage(
                            input_tokens=input_tokens,
                            output_tokens=output_tokens,
                            finish_reason=finish_reason,
                        )
                        break
                for fragment in content_filter.finish():
                    yield fragment
                if usage is None:
                    raise MalformedOllamaResponseError(
                        "stream ended without terminal usage"
                    )
                yield usage
            finally:
                await stack.aclose()
        except TimeoutError as exc:
            raise GenerationTimeoutError from exc
        except (httpx.ConnectError, httpx.NetworkError, httpx.TimeoutException) as exc:
            raise OllamaUnavailableError from exc
        except httpx.HTTPStatusError as exc:
            raise OllamaUnavailableError from exc


async def _iter_ndjson_lines(
    response: httpx.Response, deadline: float, first_response_deadline: float | None = None
) -> AsyncIterator[bytes]:
    chunks = response.aiter_bytes()
    pending = bytearray()
    first_chunk = True
    while True:
        try:
            read_deadline = min(deadline, first_response_deadline) if first_chunk and first_response_deadline is not None else deadline
            async with asyncio.timeout_at(read_deadline):
                chunk = await anext(chunks)
            if chunk:
                first_chunk = False
        except StopAsyncIteration:
            break

        start = 0
        while True:
            newline = chunk.find(b"\n", start)
            if newline < 0:
                remainder_size = len(chunk) - start
                if len(pending) + remainder_size > MAX_NDJSON_LINE_BYTES:
                    raise MalformedOllamaResponseError(
                        "stream line exceeded bounds"
                    )
                pending.extend(chunk[start:])
                break

            segment_size = newline - start
            if len(pending) + segment_size > MAX_NDJSON_LINE_BYTES:
                raise MalformedOllamaResponseError("stream line exceeded bounds")
            pending.extend(chunk[start:newline])
            yield bytes(pending)
            pending.clear()
            start = newline + 1

    if pending:
        yield bytes(pending)


def _parse_tool_arguments(arguments: Any) -> dict[str, Any]:
    if isinstance(arguments, str):
        try:
            encoded = arguments.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise MalformedOllamaResponseError("invalid tool arguments") from exc
        if len(encoded) > MAX_TOOL_ARGUMENT_BYTES:
            raise MalformedOllamaResponseError("tool arguments exceeded bounds")
        try:
            arguments = json.loads(arguments)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}
    if not isinstance(arguments, dict):
        return {}
    try:
        encoded = json.dumps(
            arguments, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise MalformedOllamaResponseError("invalid tool arguments") from exc
    if len(encoded) > MAX_TOOL_ARGUMENT_BYTES:
        raise MalformedOllamaResponseError("tool arguments exceeded bounds")
    return arguments


def _optional_token_count(item: dict[str, Any], key: str) -> int | None:
    value = item.get(key)
    if value is None:
        return None
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
        or value > MAX_SAFE_INTEGER
    ):
        raise MalformedOllamaResponseError(f"invalid {key}")
    return value
