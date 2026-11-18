import asyncio
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

from fastapi import Request

from app.config import MAX_GENERATION_BYTES, MAX_GENERATION_CODE_POINTS
from app.ollama_client import (
    GenerationTimeoutError,
    OllamaFragment,
    OllamaStreamEvent,
    OllamaToolCall,
    OllamaUsage,
)

ANSWER_CHUNK_CODE_POINTS = 4_096
MAX_PROPOSAL_EVENT_BYTES = 60 * 1_024
MAX_TOOL_CALLS_PER_ROUND = 4


class RecoverableGenerationError(Exception):
    def __init__(
        self,
        message: str,
        *,
        candidate: str = "",
        usage: OllamaUsage | None = None,
    ) -> None:
        super().__init__(message)
        self.candidate = candidate
        self.usage = usage


class _ClosableStream(Protocol):
    def __aiter__(self) -> AsyncIterator[OllamaStreamEvent]: ...

    async def __anext__(self) -> OllamaStreamEvent: ...

    async def aclose(self) -> None: ...


@dataclass(frozen=True)
class GenerationAttempt:
    content: str
    usage: OllamaUsage
    tool_calls: tuple[OllamaToolCall, ...] = ()


def remaining_seconds(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise GenerationTimeoutError
    return remaining


async def collect_attempt(
    stream: _ClosableStream, request: Request
) -> GenerationAttempt:
    chunks: list[str] = []
    tool_calls: list[OllamaToolCall] = []
    byte_count = 0
    code_point_count = 0
    active_error: BaseException | None = None
    tails = {"content": "", "thinking": ""}
    unchecked = {"content": 0, "thinking": 0}
    structured_content = False
    content_prefix = ""

    try:
        while True:
            try:
                event = await _next_event(stream, request)
            except StopAsyncIteration as exc:
                raise RecoverableGenerationError(
                    "attempt ended without usage",
                    candidate=_bounded_candidate(chunks),
                ) from exc

            if isinstance(event, OllamaUsage):
                content = "".join(chunks)
                if event.finish_reason != "stop":
                    raise RecoverableGenerationError(
                        "attempt did not finish completely",
                        candidate=content,
                        usage=event,
                    )
                if not content.strip() and not tool_calls:
                    raise RecoverableGenerationError(
                        "attempt returned no answer",
                        candidate=content,
                        usage=event,
                    )
                return GenerationAttempt(
                    content=content,
                    usage=event,
                    tool_calls=tuple(tool_calls),
                )

            if isinstance(event, OllamaToolCall):
                if len(tool_calls) >= MAX_TOOL_CALLS_PER_ROUND:
                    raise RecoverableGenerationError(
                        "attempt exceeded tool call bounds",
                        candidate=_bounded_candidate(chunks),
                    )
                tool_calls.append(event)
                continue

            if not isinstance(event, OllamaFragment):
                raise RecoverableGenerationError(
                    "attempt returned an unknown event",
                    candidate=_bounded_candidate(chunks),
                )
            kind = event.kind
            if kind == "content" and len(content_prefix) < 64:
                content_prefix = (content_prefix + event.content)[:64]
                structured_content = content_prefix.lstrip().startswith(("{", "[", "```"))
            tails[kind] = (tails[kind] + event.content)[-4096:]
            unchecked[kind] += len(event.content)
            if unchecked[kind] >= 256:
                unchecked[kind] = 0
                if (kind == "thinking" or not structured_content) and _repeats_without_progress(tails[kind]):
                    raise RecoverableGenerationError(
                        "attempt repeated without progress", candidate=_bounded_candidate(chunks)
                    )
            if kind == "thinking":
                continue

            fragment = event.content
            try:
                fragment_bytes = len(fragment.encode("utf-8"))
            except UnicodeEncodeError as exc:
                raise RecoverableGenerationError(
                    "attempt returned invalid Unicode",
                    candidate=_bounded_candidate(chunks),
                ) from exc
            byte_count += fragment_bytes
            code_point_count += len(fragment)
            if (
                byte_count > MAX_GENERATION_BYTES
                or code_point_count > MAX_GENERATION_CODE_POINTS
            ):
                raise RecoverableGenerationError(
                    "attempt exceeded generation bounds",
                    candidate=_bounded_candidate(chunks, fragment),
                )
            chunks.append(fragment)
    except BaseException as exc:
        active_error = exc
        raise
    finally:
        try:
            await stream.aclose()
        except BaseException:
            if active_error is None:
                raise


def _repeats_without_progress(tail: str) -> bool:
    """Bounded check for eight consecutive copies of a natural-language phrase.

    Structured bot data may legitimately repeat nodes and is checked separately.
    This aborts degeneration early enough to leave time for the repair attempt.
    """
    for size in range(32, min(256, len(tail) // 8) + 1):
        phrase = tail[-size:]
        if len(phrase.split()) >= 4 and tail[-size * 8:] == phrase * 8:
            return True
    for size in range(128, min(1024, len(tail) // 4) + 1):
        phrase = tail[-size:]
        if len(phrase.split()) >= 30 and tail[-size * 4:] == phrase * 4:
            return True
    return False


def chunk_answer(content: str) -> list[str]:
    return [
        content[index : index + ANSWER_CHUNK_CODE_POINTS]
        for index in range(0, len(content), ANSWER_CHUNK_CODE_POINTS)
    ]


def _bounded_candidate(chunks: list[str], fragment: str = "") -> str:
    content = "".join(chunks)
    remaining_code_points = MAX_GENERATION_CODE_POINTS - len(content)
    if remaining_code_points > 0:
        content += fragment[:remaining_code_points]
    encoded = content.encode("utf-8")
    if len(encoded) <= MAX_GENERATION_BYTES:
        return content
    return encoded[:MAX_GENERATION_BYTES].decode("utf-8", errors="ignore")


async def _next_event(
    stream: AsyncIterator[OllamaStreamEvent], request: Request
) -> OllamaStreamEvent:
    task = asyncio.create_task(anext(stream))
    try:
        while True:
            done, _ = await asyncio.wait({task}, timeout=0.1)
            if task in done:
                return task.result()
            if await request.is_disconnected():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                raise asyncio.CancelledError
    except BaseException:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        raise
