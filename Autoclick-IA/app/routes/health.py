from fastapi import APIRouter, Request

from app.schemas import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse, response_model_by_alias=True)
async def health(request: Request) -> HealthResponse:
    settings = request.app.state.settings
    result = await request.app.state.ollama.health()
    model_status = dict(
        activeModel=result.active_model or (settings.ollama_model if result.model_installed else None),
        fallbackEnabled=bool(settings.ollama_fallback_model),
        fallbackInstalled=result.fallback_installed,
    )
    if not result.reachable:
        return HealthResponse(
            status="ollama_unavailable",
            **model_status,
            serviceReachable=True,
            ollamaReachable=False,
            modelInstalled=False,
            model=settings.ollama_model,
            remediation="Ejecuta `ollama serve` y vuelve a intentarlo.",
        )
    if not result.model_installed:
        return HealthResponse(
            status="model_not_found",
            **model_status,
            serviceReachable=True,
            ollamaReachable=True,
            modelInstalled=False,
            model=settings.ollama_model,
            remediation=(
                f"Restaura el modelo entrenado con `ollama create {settings.ollama_model} -f Modelfile`."
                if settings.ollama_model.casefold().startswith('autoclick')
                else f"Ejecuta `ollama pull {settings.ollama_model}`."
            ),
        )
    return HealthResponse(
        status="ready",
        **model_status,
        serviceReachable=True,
        ollamaReachable=True,
        modelInstalled=True,
        model=settings.ollama_model,
        remediation=None,
    )
