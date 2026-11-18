from functools import lru_cache
from urllib.parse import urlparse

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

CANONICAL_MAX_BOT_NODES = 1_000
CANONICAL_MAX_BOT_EDGES = 2_000
DEFAULT_MAX_MESSAGES = 100
DEFAULT_MAX_ACTIONS = 200
DEFAULT_MAX_JSON_DEPTH = 32
DEFAULT_RUNTIME_MODEL = "autoclick-8b:entrega33"
DEFAULT_FALLBACK_MODEL = "qwen3.6:27b"
RUNTIME_MODEL = DEFAULT_RUNTIME_MODEL
RUNTIME_CONTEXT_TOKENS = 32_768
RUNTIME_OUTPUT_TOKENS = 4_096
RUNTIME_CONVERSATIONAL_OUTPUT_TOKENS = 1_024
MAX_MESSAGE_CODE_POINTS = 64_000
MAX_GENERATION_BYTES = 65_536
MAX_GENERATION_CODE_POINTS = 64_000
MAX_REQUEST_BYTES = 1_048_576
REQUEST_DEADLINE_SECONDS = 300
HOME_REQUEST_DEADLINE_SECONDS = 600
REPAIR_RESERVE_SECONDS = 60
DEFAULT_MAX_MESSAGE_CHARS = MAX_MESSAGE_CODE_POINTS


class Settings(BaseSettings):
    autoclick_ai_review_drafts: bool = True
    autoclick_ai_plan_natural_drafts: bool = True
    autoclick_ai_structured_tools: bool = True
    autoclick_ai_grounded_edit_summaries: bool = False
    autoclick_ai_grounded_creation_summaries: bool = False
    autoclick_ai_recipe_attempts: int = Field(default=2, ge=1, le=3)
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = Field(default=DEFAULT_RUNTIME_MODEL)
    ollama_fallback_model: str | None = DEFAULT_FALLBACK_MODEL
    ollama_fallback_start_timeout_seconds: float = Field(default=120, gt=0, le=300)
    ollama_context_length: int = Field(
        default=RUNTIME_CONTEXT_TOKENS, ge=2_048, le=131_072
    )
    autoclick_ai_host: str = "127.0.0.1"
    autoclick_ai_port: int = Field(default=8_000, ge=1, le=65_535)
    autoclick_cloud_api_url: str = ""
    autoclick_cloud_region: str = "us-east-1"
    autoclick_cloud_aws_profile: str = ""
    autoclick_cloud_outbox: str = "~/.autoclick/usage-outbox.sqlite3"
    autoclick_cloud_concurrency: int = Field(default=1, ge=1, le=8)
    autoclick_ai_allowed_origins: str = (
        "http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:5180,null"
    )
    autoclick_ai_connect_timeout_seconds: float = Field(default=5, gt=0, le=60)
    autoclick_ai_generation_timeout_seconds: float = Field(default=REQUEST_DEADLINE_SECONDS, gt=0, le=1_800)
    autoclick_ai_home_timeout_seconds: float = Field(default=HOME_REQUEST_DEADLINE_SECONDS, gt=0, le=1_800)
    autoclick_ai_editor_timeout_seconds: float = Field(default=REQUEST_DEADLINE_SECONDS, gt=0, le=1_800)
    autoclick_ai_repair_reserve_seconds: float = Field(default=REPAIR_RESERVE_SECONDS, ge=0, le=300)
    autoclick_ai_max_request_bytes: int = Field(
        default=MAX_REQUEST_BYTES, ge=1_024, le=MAX_REQUEST_BYTES
    )
    autoclick_ai_max_messages: int = Field(default=DEFAULT_MAX_MESSAGES, ge=1, le=DEFAULT_MAX_MESSAGES)
    autoclick_ai_max_message_chars: int = Field(
        default=MAX_MESSAGE_CODE_POINTS, ge=1, le=MAX_MESSAGE_CODE_POINTS
    )
    autoclick_ai_max_actions: int = Field(default=DEFAULT_MAX_ACTIONS, ge=1, le=DEFAULT_MAX_ACTIONS)
    autoclick_ai_max_bot_nodes: int = Field(
        default=CANONICAL_MAX_BOT_NODES, ge=1, le=CANONICAL_MAX_BOT_NODES
    )
    autoclick_ai_max_bot_edges: int = Field(
        default=CANONICAL_MAX_BOT_EDGES, ge=1, le=CANONICAL_MAX_BOT_EDGES
    )
    autoclick_ai_max_json_depth: int = Field(
        default=DEFAULT_MAX_JSON_DEPTH, ge=4, le=DEFAULT_MAX_JSON_DEPTH
    )
    generation_reserve_tokens: int = Field(
        default=RUNTIME_OUTPUT_TOKENS, ge=256
    )
    ollama_max_output_tokens: int = Field(default=RUNTIME_OUTPUT_TOKENS, ge=256)
    ollama_think: bool = False
    ollama_temperature: float = Field(default=0, ge=0, le=2)
    ollama_seed: int | None = None
    @field_validator("ollama_base_url")
    @classmethod
    def validate_ollama_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("OLLAMA_BASE_URL must be an HTTP(S) URL")
        return value.rstrip("/")

    @field_validator("ollama_model", "autoclick_ai_host")
    @classmethod
    def reject_blank_values(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be blank")
        return value.strip()

    @field_validator("ollama_fallback_model")
    @classmethod
    def normalize_fallback_model(cls, value: str | None) -> str | None:
        return (value.strip() or None) if value is not None else None

    @field_validator("autoclick_ai_allowed_origins")
    @classmethod
    def validate_origins(cls, value: str) -> str:
        origins = [item.strip() for item in value.split(",") if item.strip()]
        if not origins or "*" in origins:
            raise ValueError("explicit CORS origins are required")
        for origin in origins:
            parsed = urlparse(origin)
            if origin != "null" and (parsed.scheme not in {"http", "https"} or not parsed.netloc):
                raise ValueError(f"invalid CORS origin: {origin}")
        return ",".join(dict.fromkeys(origins))

    @model_validator(mode="after")
    def validate_runtime_profile(self) -> "Settings":
        if self.ollama_fallback_model == self.ollama_model:
            raise ValueError("primary and fallback models must be different")
        if self.autoclick_cloud_api_url:
            parsed = urlparse(self.autoclick_cloud_api_url)
            if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
                raise ValueError("AUTOCLICK_CLOUD_API_URL must be an HTTPS URL")
        if self.autoclick_ai_host not in ("127.0.0.1", "localhost", "::1") and not self.autoclick_cloud_api_url:
            raise ValueError("Public AI binding requires cloud authorization")
        if not self.ollama_max_output_tokens <= self.generation_reserve_tokens < self.ollama_context_length:
            raise ValueError("output tokens must fit the generation reserve and leave room for input")
        if not self.ollama_model.strip():
            raise ValueError("ollama_model must not be empty")
        if self.autoclick_ai_generation_timeout_seconds != self.autoclick_ai_editor_timeout_seconds:
            raise ValueError("legacy generation timeout must match editor timeout")
        if self.autoclick_ai_repair_reserve_seconds >= min(
            self.autoclick_ai_home_timeout_seconds,
            self.autoclick_ai_editor_timeout_seconds,
        ):
            raise ValueError("repair reserve must be shorter than both mode timeouts")
        if self.autoclick_ai_max_request_bytes != MAX_REQUEST_BYTES:
            raise ValueError("request byte limit must be 1048576")
        if self.autoclick_ai_max_message_chars != MAX_MESSAGE_CODE_POINTS:
            raise ValueError("message limit must be 64000 code points")
        return self

    @property
    def host(self) -> str:
        return self.autoclick_ai_host

    @property
    def port(self) -> int:
        return self.autoclick_ai_port

    @property
    def allowed_origins(self) -> list[str]:
        return self.autoclick_ai_allowed_origins.split(",")


@lru_cache
def get_settings() -> Settings:
    return Settings()
