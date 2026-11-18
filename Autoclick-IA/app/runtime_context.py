"""Bounded catalog retrieval and facts calculated from the supplied bot, never execution."""
import json
import re
import unicodedata
from collections import Counter
from autoclick_mcp.pending import is_pending_parameter
from autoclick_mcp.validator import HTTP_DERIVED_SUFFIXES, VISION_DERIVED_SUFFIXES

from app.capability_context import build_capability_document
from app.mcp_client import mcp_validate_bot, mcp_canonical_capabilities


def _terms(text):
    plain = ''.join(c for c in unicodedata.normalize('NFKD', text.casefold()) if not unicodedata.combining(c))
    # Stems are retrieval hints only: they never decide whether to edit or answer.
    stop = {'para', 'como', 'pued', 'quie', 'hace', 'teng', 'todo', 'cada', 'bloq', 'acci', 'mism', 'otra', 'otro', 'solo', 'sola'}
    return {word[:4] for word in re.findall(r'[a-z0-9]+', plain) if len(word) >= 4 and word[:4] not in stop}


def current_home_draft(request):
    if request.editor_context is not None:
        return None
    for message in reversed(request.messages[:-1]):
        if message.role != 'assistant':
            continue
        match = re.search(r'\[BORRADOR_HOME_NO_CONFIABLE\]\s*(\{.*\})\s*\[/BORRADOR_HOME_NO_CONFIABLE\]', message.content, re.DOTALL)
        if match is None:
            continue
        try:
            bot = json.loads(match.group(1))
            if mcp_validate_bot(bot, mode='proposal').get('ok'):
                return bot
        except (ValueError, TypeError, RecursionError):
            pass
        return None
    return None


def focused_catalog(request, bot=None, *, detail_limit=12):
    """Keep every catalog title; preload schemas by relevance and current bot.

    Missing details remain available through MCP. This does not filter the
    model's allowed actions or change any user-provided values.
    """
    document = build_capability_document(request.capabilities, compact=True)
    query = ' '.join(m.content for m in request.messages[-5:] if m.role == 'user')
    terms = _terms(query)
    used = {node['type'] for node in bot['flow']['nodes']} if bot is not None else set()
    actions = [action for category in document['categories'] for action in category['actions']]
    scored = []
    for action in actions:
        field_labels = ' '.join(field['label'] for field in action['fields'])
        title_terms = _terms(action['id'] + ' ' + action['title'])
        body_terms = _terms(action['description'] + ' ' + field_labels)
        score = len(terms & title_terms) * 3 + len(terms & body_terms)
        if score:
            scored.append((score, action['id']))
    selected = used | {identity for _, identity in sorted(scored, reverse=True)[:detail_limit]}
    document['actionDetails'] = [action.copy() for action in actions if action['id'] in selected]
    for category in document['categories']:
        category['actions'] = [{'id': action['id'], 'title': action['title']} for action in category['actions']]
    product = document.get('productDocumentation')
    if product:
        product['documents'] = [doc for doc in product['documents'] if doc['id'] in {'proposal-review', 'required-values'}
                                or _terms(' '.join(doc['topics'])) & terms]
    document['detailPolicy'] = 'El indice contiene TODOS los bloques. actionDetails contiene esquemas relevantes; consulta get_action_schemas para ampliar y search_product_docs para el comportamiento documentado.'
    return document


def editor_selection_facts(bot, selected_block_id):
    """Describe selection and parameter ownership from the actual catalog/bot."""
    nodes = {node['id']: node for node in bot['flow']['nodes']}
    actions = {action.id: action for action in mcp_canonical_capabilities().actions}
    owners = {}
    for node in nodes.values():
        action = actions.get(node['type'])
        if action is not None:
            for field in action.fields:
                owners.setdefault(field.name, []).append(node['id'])
    selected = nodes.get(selected_block_id)
    if selected is None:
        selection = {'id': selected_block_id, 'exists': False}
    else:
        action = actions.get(selected['type'])
        selection = {'id': selected['id'], 'exists': True,
                     'actionId': selected['type'],
                     'title': action.title if action is not None else None,
                     'editableFields': [field.name for field in action.fields] if action is not None else []}
    return {'selectedBlock': selection, 'parameterOwners': owners}


def bot_facts(bot):
    nodes = {node['id']: node for node in bot['flow']['nodes']}
    actions = {action.id: action for action in mcp_canonical_capabilities().actions}
    bindings = []
    derived_bindings = []
    references = set()
    for node in nodes.values():
        action = actions.get(node['type'])
        if action is not None:
            fields = {output.field for output in action.outputs}
            if action.output:
                fields.add(action.output.field)
            if action.slots:
                fields.update(field.name for field in action.fields if field.type == 'variable')
            for field in sorted(fields):
                name = node.get('params', {}).get(field, action.defaults.get(field))
                if isinstance(name, str) and name:
                    bindings.append({'nodeId': node['id'], 'field': field, 'name': name})
                    if field == 'outputVariable':
                        suffixes = (HTTP_DERIVED_SUFFIXES if action.id == 'http.request' else
                                    VISION_DERIVED_SUFFIXES if action.id == 'vision.detectElement' else ())
                        derived_bindings.extend(
                            {'nodeId': node['id'], 'baseName': name, 'name': name + suffix}
                            for suffix in suffixes
                        )
        references.update(re.findall(r'\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}', json.dumps(node.get('params', {}), ensure_ascii=False)))
    loops = []
    pending_parameters = [
        {'nodeId': node['id'], 'actionId': node['type'], 'field': field}
        for node in nodes.values()
        for field, value in node.get('params', {}).items()
        if is_pending_parameter(value)
    ]
    for node in nodes.values():
        if node['type'] != 'flow.forRange':
            continue
        p = node['params']
        fact = {'nodeId': node['id'], 'start': p.get('start'), 'end': p.get('end'), 'step': p.get('step', 1), 'maxIterations': p.get('maxIterations', 1000)}
        start, end, step = (fact[key] for key in ('start', 'end', 'step'))
        if all(type(v) is int for v in (start, end, step)) and step != 0:
            if (end - start) * step < 0:
                fact['iterations'] = 'rango invalido: el paso no avanza hacia el fin'
            else:
                # The desktop executor treats 0..0 as an empty range.
                fact['iterations'] = 0 if start == end == 0 else abs(end - start) // abs(step) + 1
                if type(fact['maxIterations']) is int and fact['iterations'] > fact['maxIterations']:
                    fact['rangeIterations'] = fact['iterations']
                    fact['iterations'] = 'el limite de seguridad impide completar el rango'
        else:
            fact['iterations'] = 'depende de valores en ejecucion'
        loops.append(fact)

    counts = Counter()
    waits = 0
    deterministic = True

    def sequence(ids, multiplier=1):
        nonlocal waits, deterministic
        for identity in ids:
            node = nodes[identity]
            action = node['type']
            params = node['params']
            counts[action] += multiplier
            if action == 'execution.wait':
                delay = params.get('milliseconds', 1000)
                if type(delay) is int and delay >= 0:
                    waits += delay * multiplier
                else:
                    deterministic = False
            if action == 'flow.forRange':
                iterations = next(loop['iterations'] for loop in loops if loop['nodeId'] == identity)
                limit = params.get('maxIterations', 1000)
                if type(iterations) is int and type(limit) is int and 0 <= iterations <= limit:
                    sequence(node.get('slots', {}).get('body', []), multiplier * iterations)
                else:
                    deterministic = False
            elif action == 'flow.group':
                sequence(node.get('slots', {}).get('body', []), multiplier)
            elif node.get('slots') or action in {'flow.goTo', 'execution.stop'}:
                deterministic = False

    sequence(bot['flow']['root'])
    result = {'nodeCount': len(nodes), 'rangeLoops': loops,
              'declaredVariableBindings': bindings, 'parameterVariableReferences': sorted(references),
              'derivedVariableBindings': derived_bindings,
              'pendingParameterCount': len(pending_parameters),
              'pendingParameters': pending_parameters,
              'executionStatus': 'No hay evidencia de ejecucion en este contexto. Una propuesta o aceptacion no prueba que se ejecuto.'}
    families = {node['type'].partition('.')[0] for node in nodes.values()}
    result['availableActionsForCurrentFamilies'] = {
        family: [action.title for action in actions.values() if action.id.partition('.')[0] == family]
        for family in sorted(families)
    }
    # Make absence explicit for comparable object families. Derive both the
    # operation and object vocabulary from catalog titles, never a fixed list
    # of missing blocks. A counterpart with another ID/title remains supported.
    operations = {}
    for action in actions.values():
        family, _, operation = action.id.partition('.')
        operations.setdefault(family, set()).add(operation)
    catalog_titles = {action.title.casefold() for action in actions.values()}
    unavailable = set()
    for family in families:
        objects = Counter(action.title.split()[1] for action in actions.values()
                          if action.id.partition('.')[0] == family and len(action.title.split()) == 2)
        if not objects or objects.most_common(1)[0][1] < 2:
            continue
        object_name = objects.most_common(1)[0][0]
        for action in actions.values():
            other_family, _, operation = action.id.partition('.')
            if other_family == family or len(operations[family] & operations[other_family]) < 2:
                continue
            words = action.title.split()
            candidate = words[0] + ' ' + object_name
            if len(words) == 2 and operation not in operations[family] and candidate.casefold() not in catalog_titles:
                unavailable.add(candidate)
    result['unavailableCounterpartTitles'] = sorted(unavailable)
    if deterministic:
        result['programmedActionCountsIfActionsSucceed'] = dict(counts)
        result['programmedWaitMilliseconds'] = waits
    return result
