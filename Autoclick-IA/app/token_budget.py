from collections.abc import Mapping, Sequence
from functools import lru_cache

import regex


MAX_TOKENIZER_ENTRIES = 300_000
CHAT_SPECIAL_TOKENS = (
    "<|endoftext|>",
    "<|im_start|>",
    "<|im_end|>",
    "<think>",
    "</think>",
)
REQUIRED_CHAT_TOKENS = frozenset(("<|im_start|>", "<|im_end|>"))
PRETOKENIZE_PATTERN = regex.compile(
    r"(?i:'s|'t|'re|'ve|'m|'ll|'d)|[^\r\n\p{L}\p{N}]?[\p{L}\p{M}]+|"
    r"\p{N}| ?[^\s\p{L}\p{M}\p{N}]+[\r\n]*|\s*[\r\n]+|\s+(?!\S)|\s+"
)


class TokenMetadataError(ValueError):
    pass


@lru_cache(maxsize=1)
def bytes_to_unicode() -> dict[int, str]:
    visible_bytes = (
        list(range(ord("!"), ord("~") + 1))
        + list(range(ord("¡"), ord("¬") + 1))
        + list(range(ord("®"), ord("ÿ") + 1))
    )
    code_points = visible_bytes.copy()
    extra = 0
    for value in range(256):
        if value not in visible_bytes:
            visible_bytes.append(value)
            code_points.append(256 + extra)
            extra += 1
    return dict(zip(visible_bytes, map(chr, code_points), strict=True))


def render_qwen35_chat(
    messages: Sequence[Mapping[str, str]], *, think: bool
) -> str:
    rendered = "".join(
        f'<|im_start|>{message["role"]}\n{message["content"].strip()}<|im_end|>\n'
        for message in messages
    )
    generation_prefix = "<|im_start|>assistant\n<think>\n"
    if not think:
        generation_prefix += "\n</think>\n\n"
    return rendered + generation_prefix


class Qwen35TokenCounter:
    def __init__(
        self,
        *,
        encoder: dict[str, int],
        merge_ranks: dict[tuple[str, str], int],
        byte_encoder: Mapping[int, str],
    ) -> None:
        self._encoder = encoder
        self._merge_ranks = merge_ranks
        self._byte_encoder = byte_encoder
        specials = [token for token in CHAT_SPECIAL_TOKENS if token in encoder]
        self._special_pattern = regex.compile(
            "|".join(regex.escape(token) for token in specials)
        )

    @classmethod
    def from_model_info(
        cls, model_info: Mapping[str, object]
    ) -> "Qwen35TokenCounter":
        tokens = require_string_list(model_info, "tokenizer.ggml.tokens")
        merges = require_string_list(model_info, "tokenizer.ggml.merges")
        token_types = require_int_list(model_info, "tokenizer.ggml.token_type")
        validate_qwen35_metadata(model_info, tokens, merges, token_types)
        return cls(
            encoder={token: index for index, token in enumerate(tokens)},
            merge_ranks={
                tuple(merge.split(" ", 1)): rank
                for rank, merge in enumerate(merges)
            },
            byte_encoder=bytes_to_unicode(),
        )

    def encode(self, text: str) -> list[int]:
        encoded: list[int] = []
        ordinary_start = 0
        for match in self._special_pattern.finditer(text):
            encoded.extend(self._encode_ordinary(text[ordinary_start : match.start()]))
            encoded.append(self._encoder[match.group()])
            ordinary_start = match.end()
        encoded.extend(self._encode_ordinary(text[ordinary_start:]))
        return encoded

    def count_text(self, text: str) -> int:
        return len(self.encode(text))

    def count_chat(
        self, messages: Sequence[Mapping[str, str]], *, think: bool
    ) -> int:
        return self.count_text(render_qwen35_chat(messages, think=think))

    def _encode_ordinary(self, text: str) -> list[int]:
        encoded: list[int] = []
        for piece in PRETOKENIZE_PATTERN.findall(text):
            byte_piece = "".join(
                self._byte_encoder[value] for value in piece.encode("utf-8")
            )
            encoded.extend(self._encode_bpe_piece(byte_piece))
        return encoded

    @lru_cache(maxsize=65_536)
    def _encode_bpe_piece(self, piece: str) -> tuple[int, ...]:
        parts = list(piece)
        while len(parts) > 1:
            ranked_pairs = (
                (self._merge_ranks[(left, right)], (left, right))
                for left, right in zip(parts, parts[1:])
                if (left, right) in self._merge_ranks
            )
            best = min(ranked_pairs, default=None)
            if best is None:
                break
            _, (left, right) = best
            merged: list[str] = []
            index = 0
            while index < len(parts):
                if (
                    index + 1 < len(parts)
                    and parts[index] == left
                    and parts[index + 1] == right
                ):
                    merged.append(left + right)
                    index += 2
                else:
                    merged.append(parts[index])
                    index += 1
            parts = merged
        try:
            return tuple(self._encoder[part] for part in parts)
        except KeyError:
            raise TokenMetadataError("tokenizer vocabulary is incomplete") from None


def require_string_list(
    model_info: Mapping[str, object], key: str
) -> list[str]:
    value = model_info.get(key)
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise TokenMetadataError("tokenizer string metadata is invalid")
    return value


def require_int_list(model_info: Mapping[str, object], key: str) -> list[int]:
    value = model_info.get(key)
    if not isinstance(value, list) or any(type(item) is not int for item in value):
        raise TokenMetadataError("tokenizer integer metadata is invalid")
    return value


def validate_qwen35_metadata(
    model_info: Mapping[str, object],
    tokens: Sequence[str],
    merges: Sequence[str],
    token_types: Sequence[int],
) -> None:
    arch = str(model_info.get("general.architecture", "")).lower()
    tok_pre = str(model_info.get("tokenizer.ggml.pre", "")).lower()
    tok_model = str(model_info.get("tokenizer.ggml.model", "")).lower()
    if (
        not any(k in arch for k in ("qwen35", "qwen2", "qwen"))
        or tok_model not in ("gpt2", "llama")
        or not any(k in tok_pre for k in ("qwen35", "qwen2", "default", "qwen"))
    ):
        raise TokenMetadataError("tokenizer architecture is incompatible")
    if any(
        len(entries) > MAX_TOKENIZER_ENTRIES
        for entries in (tokens, merges, token_types)
    ):
        raise TokenMetadataError("tokenizer metadata exceeds the supported size")
    if len(tokens) != len(token_types):
        raise TokenMetadataError("tokenizer vocabulary metadata length mismatch")
    vocabulary = set(tokens)
    if len(vocabulary) != len(tokens):
        raise TokenMetadataError("tokenizer vocabulary contains duplicate entries")
    if not REQUIRED_CHAT_TOKENS.issubset(vocabulary):
        raise TokenMetadataError("required chat tokens are missing")
    if not set(bytes_to_unicode().values()).issubset(vocabulary):
        raise TokenMetadataError("tokenizer byte vocabulary is incomplete")
    if not merges:
        raise TokenMetadataError("tokenizer merge metadata is invalid")
    merge_pairs: set[tuple[str, str]] = set()
    for merge in merges:
        if merge.count(" ") != 1:
            raise TokenMetadataError("tokenizer merge metadata is invalid")
        left, right = merge.split(" ", 1)
        pair = (left, right)
        if (
            not left
            or not right
            or pair in merge_pairs
            or left not in vocabulary
            or right not in vocabulary
            or left + right not in vocabulary
        ):
            raise TokenMetadataError("tokenizer merge metadata is invalid")
        merge_pairs.add(pair)
