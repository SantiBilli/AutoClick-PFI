ERROR_MESSAGES = {
    "INVALID_REQUEST": "La solicitud no es valida.",
    "OLLAMA_UNAVAILABLE": "No se pudo conectar con Ollama.",
    "MODEL_NOT_FOUND": "El modelo configurado no esta instalado.",
    "GENERATION_TIMEOUT": "La generacion excedio el tiempo permitido.",
    "GENERATION_CANCELLED": "La generacion fue cancelada.",
    "CONTEXT_TOO_LARGE": "El contexto del bot supera el limite disponible del modelo.",
    "INVALID_PROPOSAL": "La propuesta generada no es valida.",
    "CATALOG_MISMATCH": "El catalogo de acciones no coincide. Actualiza AutoClick e intenta nuevamente.",
    "INTERNAL_ERROR": "Ocurrio un error interno.",
    "EDITOR_CONTEXT_REQUIRED": "La solicitud mutacional requiere editorContext cuando hay un editor abierto.",
}

SAFE_LOCATION_PARTS = frozenset({
    "kind",
    "name",
    "description",
    "summary",
    "message",
    "flow",
    "type",
    "params",
    "slots",
    "root",
    "nodes",
    "edges",
})
