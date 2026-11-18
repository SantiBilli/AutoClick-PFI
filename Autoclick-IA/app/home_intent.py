"""Small, evidence-based intent hints for Home flow generation."""
import re
import unicodedata
from dataclasses import dataclass


_WEB_ADDRESS = re.compile(
    r'(?<![@\w])((?:https?://)?(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}'
    r'(?::\d{1,5})?(?:/[^\s"\'<>]*)?)',
    re.IGNORECASE,
)


def explicit_web_url(message: str) -> str | None:
    """Use only an address written by the user; add HTTPS to a bare host."""
    match = _WEB_ADDRESS.search(message)
    if match is None:
        return None
    address = match.group(1).rstrip('.,;!?)')
    return address if address.lower().startswith(('https://', 'http://')) else f'https://{address}'


def _plain(text: str) -> str:
    return ''.join(
        char for char in unicodedata.normalize('NFKD', text.casefold())
        if not unicodedata.combining(char)
    )


def explicit_new_bot_request(message: str) -> bool:
    """Separate a fresh bot request from edits to the current Home draft."""
    text = _plain(message)
    return bool(re.search(
        r'\b(?:crea(?:me)?|arma(?:me)?|hace(?:me)?|genera(?:me)?|quiero|necesito)\s+'
        r'(?:(?:un|otro|nuevo|el)\s+)*(?:bot|flujo)\b'
        r'|\b(?:otro|nuevo)\s+bot\b', text,
    ))


@dataclass(frozen=True)
class WebVisionClickIntent:
    url: str
    target_text: str
    wait_milliseconds: int | None


def web_vision_click_intent(message: str) -> WebVisionClickIntent | None:
    """Identify a bounded web-open, text-detect, click request."""
    plain = _plain(message)
    if not (
        re.search(r'\b(?:bus[qc]\w*|detect\w*|encontr\w*|localiz\w*)\b', plain)
        and re.search(r'\b(?:clic\w*|click\w*)\b', plain)
        and not re.search(r'\b(?:sin\s+esperar|sin\s+pausa\w*)\b', plain)
        and not re.search(r'\b(?:escrib\w*|descarg\w*|copi\w*|guard\w*|elimin\w*|mover\w*)\b', plain)
    ):
        return None
    url = explicit_web_url(message)
    if url is None:
        return None
    quoted = re.search(
        r'(?:bot[oó]n|texto|elemento)\s+(?:que\s+)?(?:dice\s+)?["“«]([^"”»]{1,80})["”»]',
        message,
        re.IGNORECASE,
    )
    unquoted = re.search(
        r'(?:bot[oó]n|texto|elemento)\s+(?:que\s+)?(?:dice\s+)?([A-Za-zÁÉÍÓÚáéíóúÑñ][\wÁÉÍÓÚáéíóúÑñ]{1,60})'
        r'(?=\s+(?:y|para|despu[eé]s)|[.!?,]|$)',
        message,
        re.IGNORECASE,
    )
    target = (quoted or unquoted)
    if target is None:
        return None
    target_text = target.group(1).strip()
    if not target_text:
        return None
    duration = re.search(r'\b(\d+)\s*(milisegundos?|ms|segundos?|s)\b', plain)
    milliseconds = None
    if duration is not None:
        scale = 1 if duration.group(2).startswith(('mili', 'ms')) else 1000
        milliseconds = int(duration.group(1)) * scale
        if milliseconds > 3_600_000:
            return None
    return WebVisionClickIntent(url=url, target_text=target_text, wait_milliseconds=milliseconds)


@dataclass(frozen=True)
class SimpleWebOpenIntent:
    url: str | None


def simple_web_open_intent(message: str) -> SimpleWebOpenIntent | None:
    """Identify a one-step web opening task without guessing its address."""
    plain = _plain(message)
    if not (
        re.search(r'\b(?:abrir|abre|abri|entrar|entre)\b', plain)
        and (explicit_web_url(message) is not None or re.search(r'\b(?:pagina|web|sitio|navegador|facebook)\b', plain))
        and not re.search(r'\b(?:bus[qc]\w*|detect\w*|clic\w*|click\w*|esper\w*|presion\w*|escrib\w*|descarg\w*|copi\w*|guard\w*|leer|mover)\b', plain)
    ):
        return None
    return SimpleWebOpenIntent(url=explicit_web_url(message))
