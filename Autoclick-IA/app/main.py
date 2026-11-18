from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings, get_settings
from app.ollama_client import OllamaClient
from app.model_fallback import FallbackOllama, ModelFallbackMiddleware
from app.mcp_client import McpRuntime
from app.routes.chat import router as chat_router
from app.routes.health import router as health_router
from app.cloud_control import CloudControl, CloudAuthorizationMiddleware, MeteredOllama


def create_app(
    settings: Settings | None = None,
    ollama_client: Any | None = None,
    mcp_runtime: McpRuntime | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    resolved_client = ollama_client or (
        FallbackOllama(resolved_settings) if resolved_settings.ollama_fallback_model
        else OllamaClient(resolved_settings)
    )
    fallback_client = resolved_client if isinstance(resolved_client, FallbackOllama) else None
    control = CloudControl(resolved_settings) if resolved_settings.autoclick_cloud_api_url else None
    if control:
        resolved_client = MeteredOllama(resolved_client, resolved_settings)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        try:
            if control:
                await control.start()
            async with (mcp_runtime or McpRuntime()) as runtime:
                application.state.mcp = runtime
                yield
        finally:
            if control:
                await control.close()
            close = getattr(resolved_client, "close", None)
            if close is not None:
                await close()

    application = FastAPI(title="Autoclick-IA", version="0.1.0", lifespan=lifespan)
    application.state.settings = resolved_settings
    application.state.ollama = resolved_client
    if fallback_client:
        application.add_middleware(ModelFallbackMiddleware, client=fallback_client)
    if control:
        application.add_middleware(CloudAuthorizationMiddleware, control=control)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-AutoClick-Request-Id"],
    )
    application.include_router(health_router)
    application.include_router(chat_router)
    return application


app = create_app()
