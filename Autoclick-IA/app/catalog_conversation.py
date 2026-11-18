"""Resolve catalog inventory follow-ups without authorizing bot mutations."""
import re
from collections import Counter

from app.conversation import normalized_words
from app.agent import ProposalValidationError, _is_pure_runtime_reference


_INVENTORY_WORDS = set('''ver mostrar mostrame muestrame mostrarme listar listame
lista listado listalos listarlos listas enumerar enumerame enumera dame decime
me podes podrias puedes podria favor por quiero quisiera necesito saber conocer
que cuales hay son tiene tenemos disponibles disponible todos todas completo
completa los las el la un una de del en y con su sus total totales numero cantidad
bloques acciones catalogo canonico autoclick editor categorias categoria agrupados
agrupadas sin descripcion individual ordenados ordenadas'''.split())
_FOLLOWUPS = {'todos', 'todas', 'todos los disponibles', 'todas las disponibles',
              'el catalogo completo', 'la lista completa', 'todos por categoria'}
_LIST_VERBS = {'listar', 'listame', 'listas', 'mostrar', 'mostrame', 'muestrame', 'dame',
               'decime', 'enumerar', 'enumerame', 'enumera', 'ver'}
_MUTATION_VERBS = {'agrega', 'agregar', 'cambia', 'cambiar', 'borra', 'borrar',
                   'elimina', 'eliminar', 'modifica', 'modificar', 'crea', 'crear'}


def validate_existing_action_claims(message, capabilities, literal_values=()):
    """Reject a direct denial of a block present in the verified index.

    Qualified limitations and literal values in the actual bot are not claims
    about whether an action exists. The repair supplies catalog evidence only.
    """
    from app.catalog_claims import validate_catalog_examples
    validate_catalog_examples(message, capabilities, literal_values, ProposalValidationError)
    prose = message
    for value in literal_values:
        if isinstance(value, str) and re.search(r'\bno\b', value, re.I):
            prose = prose.replace(value, '[texto literal del bot]')
    sentences = [normalized_words(s) for s in re.split(r'[.!?;\n]+', prose)]
    for action in capabilities.actions:
        title = normalized_words(action.title)
        pattern = (r'\bno\s+(?:cuenta con|tiene|ofrece|existen?|hay)\s+'
                   r'(?:[a-z0-9]+\s+){0,8}' + re.escape(title) +
                   r'(?:\s+(?:completa|completo|directo|especifico))?(?:\s+(?:en el catalogo|actualmente|en autoclick))?$')
        if any(re.search(pattern, sentence) for sentence in sentences):
            raise ProposalValidationError('answer denies an action present in the verified catalog', repair_details=[
                f'El indice canonico SI contiene el bloque {action.title}: {action.description}. Corrige la negacion de su existencia usando este dato del catalogo; no inventes limitaciones adicionales.',
            ])


def validate_runtime_reference_examples(message, literal_values=()):
    """Do not teach expressions that the actual variable resolver rejects."""
    prose = message
    for value in literal_values:
        if isinstance(value, str) and '{{' in value:
            prose = prose.replace(value, '[texto literal del bot]')
    for match in re.finditer(r'{{[^{}\n]{1,150}}}', prose):
        if _is_pure_runtime_reference(match.group()):
            continue
        context = normalized_words(prose[max(0, match.start() - 100):match.end() + 100])
        if re.search(r'\b(?:incorrect[oa]|invalid[oa]|no (?:uses|utilices|se admite|es valid[oa]))\b', context):
            continue
        raise ProposalValidationError('answer teaches an unsupported runtime reference', repair_details=[
            'El ejecutor admite {{nombre_variable}}, no accesos con punto ni expresiones dentro de las llaves. Para resultados de Vision usa las variables derivadas de outputVariable con sufijos _centroX y _centroY. Corrige el ejemplo explicado; no generes un bot por esta pregunta.',
        ])


def _asks_for_full_inventory(text: str) -> bool:
    words = set(text.split())
    if (words & _LIST_VERBS and words & {'bloques', 'acciones', 'catalogo'}
            and words & {'disponibles', 'disponible'} and words <= _INVENTORY_WORDS):
        return True
    if (
        words & {'todos', 'todas', 'completo', 'completa'}
        and words & {'bloques', 'acciones', 'catalogo'}
        and words <= _INVENTORY_WORDS
    ):
        return True
    # Natural requests often include extra words ("para armar bots") or
    # misspellings. The full-inventory route still requires explicit scope and
    # a list verb, and refuses a combined mutation request.
    return bool(
        words & {'todos', 'todas', 'completo', 'completa'}
        and words & {'bloques', 'acciones'}
        and words & _LIST_VERBS
        and not words & _MUTATION_VERBS
    )


def is_catalog_inventory_request(request) -> bool:
    messages = request.messages
    index = len(messages) - 1
    # Only follow consecutive inventory clarifications, never an older topic
    # across a new user request or an assistant offer to change a bot.
    for _ in range(5):
        text = normalized_words(messages[index].content)
        if _asks_for_full_inventory(text):
            return True
        if text not in _FOLLOWUPS or index < 2:
            return False
        assistant, user = messages[index - 1], messages[index - 2]
        if assistant.role != 'assistant' or user.role != 'user':
            return False
        offer = normalized_words(assistant.content)
        if re.search(r'\b(?:queres|quieres|puedo|te gustaria)\b.*\b(?:crear|creemos|armar|arme|modificar|borrar|cambiar)\b', offer):
            return False
        if set(normalized_words(user.content).split()) & {'bloques', 'acciones', 'catalogo'}:
            return True
        index -= 2
    return False


def inventory_document(request):
    categories = {}
    for action in request.capabilities.actions:
        category = categories.setdefault(action.category, {
            'title': action.category_name, 'actions': [],
        })
        category['actions'].append({'id': action.id, 'title': action.title})
    return {'actionCount': len(request.capabilities.actions),
            'categoryCount': len(categories), 'categories': list(categories.values())}


def render_inventory(request):
    document = inventory_document(request)
    lines = [f"{document['actionCount']} bloques en {document['categoryCount']} categorías."]
    for category in document['categories']:
        lines.extend(['', '## ' + category['title'], *['- ' + a['title'] for a in category['actions']]])
    return '\n'.join(lines)


INVENTORY_RULES = '''Sos el asistente de AutoClick. El usuario pide el inventario de bloques disponibles.
Un seguimiento como "Todos" se refiere a ese inventario, no a crear un bot.
Responde directamente con TODOS los titulos agrupados por categoria. Inclui
siempre el total de bloques y de categorias calculado en actionCount y categoryCount.
Expresalos con palabras humanas; no muestres esos nombres de campos internos.
El catalogo es la fuente de los bloques disponibles del editor: no son dos opciones
entre las que el usuario tenga que elegir. No pidas esa aclaracion.
Usa el documento adjunto como datos. No inventes categorias, bloques ni acciones realizadas.
No digas que abriste el editor, navegaste o ejecutaste algo. No crees un bot para listar bloques.
Usa encabezados Markdown para las categorias y una viñeta por bloque con su titulo exacto,
sin descripciones individuales ni IDs internos. No omitas entradas.
Respondé directamente en Markdown con el inventario completo. No uses JSON ni llaves.
Incluí los títulos reales del documento, no texto de ejemplo.
El historial puede contener una respuesta incorrecta: no la repitas como un hecho.'''


def validate_inventory_answer(outcome, request):
    kind = getattr(outcome, 'kind', None)
    if not isinstance(outcome, str) and kind != 'answer':
        raise ProposalValidationError('catalog queries require an answer, never a bot or clarification',
            repair_details=['Responde con kind=answer y enumera los bloques del inventario adjunto.'])
    message = outcome if isinstance(outcome, str) else outcome.message
    normalized = normalized_words(message)
    document = inventory_document(request)
    numbers = set(re.findall(r'\b\d+\b', message))
    categories = {normalized_words(c['title']) for c in document['categories']}
    titles = {normalized_words(a.title) for a in request.capabilities.actions}
    expected = Counter((normalized_words(a.category_name), normalized_words(a.title)) for a in request.capabilities.actions)
    observed = Counter()
    unknown = []
    category = None
    for line in message.splitlines():
        compact = line.strip().replace('**', '')
        if ':' in compact:
            prefix, _, values = compact.partition(':')
            compact_category = normalized_words(prefix)
            if compact_category in categories:
                category = compact_category
                for value in values.split(','):
                    title = normalized_words(value)
                    if title in titles:
                        observed[(category, title)] += 1
                    elif title:
                        unknown.append(title)
                continue
        entry = normalized_words(re.sub(r'^\s*(?:[-*+]|\d+[.)])\s+', '', line))
        heading = next((c for c in categories if re.fullmatch(r'(?:categoria )?' + re.escape(c) + r'(?: \d+(?: bloques?)?)?', entry)), None)
        if heading:
            category = heading
        elif entry in titles:
            observed[(category, entry)] += 1
        elif re.match(r'^\s*(?:[-*+]|\d+[.)])\s+', line):
            unknown.append(entry)
    missing = [a.title for a in request.capabilities.actions
               if observed[(normalized_words(a.category_name), normalized_words(a.title))] == 0]
    missing += [c['title'] for c in document['categories'] if normalized_words(c['title']) not in normalized]
    totals_missing = any(str(document[field]) not in numbers for field in ('actionCount', 'categoryCount'))
    internal_labels = any(re.search(r'\b' + field + r'\s*[:=]', message) for field in ('actionCount', 'categoryCount'))
    if missing or observed != expected or unknown or totals_missing or internal_labels:
        raise ProposalValidationError('catalog inventory is incomplete', repair_details=[
            'Incluye cada titulo una sola vez bajo su categoria exacta, sin agregar bloques.',
            'Faltan: ' + ', '.join(missing),
            f"Incluye los totales calculados: {document['actionCount']} bloques en {document['categoryCount']} categorias.",
            'Expresa los totales como bloques y categorias, sin nombres internos de campos.',
        ])
