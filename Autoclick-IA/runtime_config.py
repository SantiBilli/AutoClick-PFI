"""Read the same worker profile used at startup, without exposing credentials."""
import json
from pathlib import Path

from app.config import Settings


if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    for name in (".env", ".env.cloud"):
        if not (root / name).is_file():
            raise RuntimeError(f"Missing worker configuration: {root / name}")
    settings = Settings(_env_file=(root / ".env", root / ".env.cloud"))
    print(json.dumps({
        "model": settings.ollama_model,
        "fallbackModel": settings.ollama_fallback_model,
        "ollamaBaseUrl": settings.ollama_base_url,
        "backendHost": settings.host,
        "backendPort": settings.port,
        "cloudEnabled": bool(settings.autoclick_cloud_api_url),
    }))
