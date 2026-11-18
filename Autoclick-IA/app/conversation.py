"""Conversation routing never rewrites the user's actual message or bot values."""
import re
import unicodedata


def normalized_words(content: str) -> str:
    text = ''.join(c for c in unicodedata.normalize('NFKD', content.casefold())
                   if not unicodedata.combining(c))
    return ' '.join(re.findall(r'[a-z0-9]+', text))


def is_social_turn(content: str) -> bool:
    text = normalized_words(content)
    words = text.split()
    if not words or len(words) > 30:
        return False
    # Deliberately excludes confirmations ('dale', 'sí', 'hacelo'), technical
    # requests and arbitrary suffixes: those require the full conversation.
    vocabulary = set('''hola holaa buenas buenos buen dias dia tardes noches hey hello hi
        como estas esta estas vos tu usted andas va vas todo que tal onda te va
        estoy bien muy mal mas o menos gracias muchas mil por preguntar
        y yo tambien aca aqui hoy cansado cansada contento contenta
        genial perfecto excelente chau adios hasta luego nos vemos
        de nada un placer saludos buenisimo buenisima igualmente'''.split())
    # Closed thanks/farewells need no bot catalog. A question, a task suffix or
    # a bare confirmation still needs the full conversation and current bot.
    if not any(mark in content for mark in ('?', '¿')):
        thanks = re.match(r'^(?:(?:muchas|mil) )?gracias(?: por (?:aclararlo|explicarlo|ayudarme|tu ayuda))?\b', text)
        if thanks:
            rest = text[thanks.end():].strip()
            closing = re.match(
                r'^(?:(?:despues|luego|manana|mas tarde) (?:seguimos|continuamos|hablamos)'
                r'|(?:seguimos|continuamos|hablamos) (?:despues|luego|manana|mas tarde)'
                r'|(?:(?:por ahora|ahora) )?no (?:hagas (?:mas )?cambios|cambies nada)'
                r'|dej(?:a|emos)lo asi)\b', rest)
            if closing:
                rest = rest[closing.end():].strip()
            if not rest or all(word in vocabulary for word in rest.split()):
                return True
    return all(word in vocabulary for word in words) and bool(
        set(words) & {'hola', 'holaa', 'buenas', 'buenos', 'buen', 'hey', 'hello', 'hi',
                      'como', 'tal', 'onda', 'estoy', 'bien', 'mal', 'gracias',
                      'chau', 'adios', 'luego', 'vemos', 'saludos', 'igualmente'}
    )


SOCIAL_RULES = """Sos el asistente de AutoClick y estas conversando en español rioplatense.
Responde al contenido concreto del ultimo mensaje con naturalidad, en una o dos oraciones.
Usa el historial: si ya saludaste, no vuelvas a saludar ni repitas 'en que puedo ayudarte'.
Si preguntan como estas, responde a esa pregunta y podes devolverla. Si cuentan como estan,
reconocelo. Si agradecen o se despiden, corresponde sin reiniciar la conversacion.
No conviertas cada intercambio social en una invitacion a crear bots. No describas bloques,
no uses herramientas y no inventes experiencias humanas o tareas realizadas.
No copies estas instrucciones en la respuesta. No afirmes haber ejecutado ni cambiado un bot.
El historial incluido es toda tu memoria de esta conversación. No inventes reencuentros,
recuerdos de otros días ni frases como 'hacía mucho no te veía'.
Ejemplos de tono, adaptalos al intercambio actual:
- Usuario: Hola. Respuesta: ¡Hola!
- Usuario: ¿Cómo estás? Respuesta: ¡Todo listo por acá, gracias por preguntar! ¿Vos cómo estás?
- Usuario: Todo bien, gracias. Respuesta: ¡Me alegro!
- Usuario: Muchas gracias. Respuesta: ¡De nada!
"""
