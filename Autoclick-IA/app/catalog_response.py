import re

from app.schemas import Capabilities


CATALOG_RESPONSE_FORMAT = """Cuando el usuario pida todos los bloques por categoria, devuelve unicamente Markdown con esta estructura exacta:
# Bloques disponibles

**<actionCount> bloques en <categoryCount> categorías**

## <categoryName>

- <actionTitle>
Repite cada categoria en su orden y, debajo, cada una de sus acciones en su orden. Incluye cada categoria y accion exactamente una vez. Usa solamente los nombres visibles de categorias y bloques; no incluyas IDs internos ni nombres de operaciones de parche. En modo editor, coloca este Markdown como el contenido de message de un resultado answer; fuera del editor, devuelvelo directamente."""
CANONICAL_ACTION_COUNT = 69
CANONICAL_CATEGORY_COUNT = 14
MARKDOWN_CONTROL_CHARACTERS = r"\\`*{}[]<>()#+-.!|>_~"
MARKDOWN_CONTROL_PATTERN = re.compile(
    f"([{re.escape(MARKDOWN_CONTROL_CHARACTERS)}])"
)


class CatalogResponseError(ValueError):
    def __init__(self, action_count: int, category_count: int) -> None:
        super().__init__("catalog response does not match the canonical projection")
        self.action_count = action_count
        self.category_count = category_count


def catalog_counts(capabilities: Capabilities) -> tuple[int, int]:
    return (
        len(capabilities.actions),
        len({action.category for action in capabilities.actions}),
    )


def validate_catalog_response(content: str, capabilities: Capabilities) -> None:
    action_count, category_count = catalog_counts(capabilities)
    expected = _expected_lines(capabilities)
    if content.splitlines() != expected:
        raise CatalogResponseError(
            action_count,
            category_count,
        )


def render_catalog_response(capabilities: Capabilities) -> str:
    return "\n".join(_expected_lines(capabilities))


def _render_label(label: str) -> str:
    single_line = " ".join(label.splitlines())
    return MARKDOWN_CONTROL_PATTERN.sub(r"\\\1", single_line)


def _expected_lines(capabilities: Capabilities) -> list[str]:
    categories: dict[tuple[str, str], list[str]] = {}
    for action in capabilities.actions:
        categories.setdefault(
            (action.category, action.category_name), []
        ).append(_render_label(action.title))

    lines = [
        "# Bloques disponibles",
        "",
        f"**{len(capabilities.actions)} bloques en {len(categories)} {'categoría' if len(categories) == 1 else 'categorías'}**",
    ]
    for (_, category_name), action_titles in categories.items():
        lines.extend(["", f"## {_render_label(category_name)}", ""])
        lines.extend(f"- {title}" for title in action_titles)
    return lines
