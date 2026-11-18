"""Small model edits, expanded to the existing fully validated public protocol.

Only this model-facing contract merges partial params. The public
updateNodeParams operation still replaces a complete parameter object.
"""
import copy
import json

from app.agent import (
    AgentProposal, AgentProposalArguments, ProposalValidationError,
    _field_json_schema, _ollama_compatible_schema, _reject_duplicate_json_keys,
    parse_editor_turn,
)
from app.config import MAX_GENERATION_BYTES, MAX_GENERATION_CODE_POINTS, DEFAULT_MAX_JSON_DEPTH
from app.editor_safety import classify_editor_intent, ambiguous_initial_wait_edit
from app.schemas import ChatRequest, validate_json_tree
from app.mcp_client import mcp_preview_bot_patch
from app.tree_diff import dump_tree_operations


class NoEffectEdit(ProposalValidationError):
    """A fully previewed patch produced the unchanged current bot."""


def command_first_schema(schema):
    """Select an operation before spelling its data in Ollama's key order."""
    result = copy.deepcopy(schema)
    def visit(value):
        if isinstance(value, dict):
            fields = value.get('properties', {})
            if isinstance(fields.get('op'), dict) and 'const' in fields['op']:
                command = fields.pop('op')
                value['properties'] = {'command': command, **fields}
                value['required'] = ['command' if field == 'op' else field for field in value.get('required', [])]
            if value.get('discriminator', {}).get('propertyName') == 'op':
                value['discriminator']['propertyName'] = 'command'
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(result)
    return result


def editor_patch_schema(request: ChatRequest) -> dict:
    answers = [{
        'type': 'object', 'properties': {
            'kind': {'const': kind}, 'message': {'type': 'string', 'minLength': 1},
        }, 'required': ['kind', 'message'], 'additionalProperties': False,
    } for kind in ('answer', 'clarification')]
    if ambiguous_initial_wait_edit(request):
        return {'oneOf': answers[1:]}
    intent = classify_editor_intent(request.messages[-1].content)
    if intent == 'informational':
        return {'oneOf': answers[:1]}
    if intent == 'mutation':
        # A request to edit must produce a reviewable proposal or ask for a
        # missing target. A verified no-op may enable answers during repair.
        answers = answers[1:]
    schema = AgentProposalArguments.model_json_schema(by_alias=True)
    defs = schema['$defs']
    # Dynamic field schemas prevent exchanging parameters between block types.
    context = request.editor_context
    baseline = context.working_bot if context.working_bot is not None else context.bot
    actions = {action.id: action for action in request.capabilities.actions}
    groups = {}
    for node in baseline['flow']['nodes']:
        groups.setdefault(node['type'], []).append(node['id'])
    updates = []
    for action_id, ids in groups.items():
        action = actions.get(action_id)
        if action is None or not action.fields:
            continue
        updates.append({
            'type': 'object', 'properties': {
                'op': {'const': 'updateNodeParams'}, 'nodeId': {'type': 'string', 'enum': ids},
                'params': {'type': 'object', 'properties': {field.name: _field_json_schema(field) for field in action.fields},
                           'minProperties': 1, 'additionalProperties': False},
            }, 'required': ['op', 'nodeId', 'params'], 'additionalProperties': False,
        })
    # Parameters for new nodes belong in addNode. Existing nodes have exact IDs
    # and per-action partial schemas; runtime validation proves the final tree.
    if updates:
        defs['UpdateNodeParamsOperation'] = {'oneOf': updates}
    # Root insertion is not "after this node": it has a null parent and an
    # index among siblings. Leaf IDs can never be parent IDs. Reserve a fresh
    # namespace so new containers can still receive children in the same patch.
    existing_ids = {node['id'] for node in baseline['flow']['nodes']}
    suffix = 0
    prefix = 'new_'
    while any(identity.startswith(prefix) for identity in existing_ids):
        suffix += 1
        prefix = f'new{suffix}_'
    new_id = {'type': 'string', 'pattern': '^' + prefix + '[A-Za-z0-9_]+$', 'description': 'ID nuevo unico para este parche, comenzando con ' + prefix}
    defs['ProposalNode']['properties']['id'] = new_id
    defs['ProposalNode']['properties']['type'] = {'type': 'string', 'enum': list(actions)}
    index = defs['ProposalLocation']['properties']['index']
    def location(parent, slots):
        return {'type':'object', 'properties':{'parentId':parent,'slot':{'type':'string','enum':slots},'index':index},
                'required':['parentId','slot','index'], 'additionalProperties':False}
    locations = [location({'type':'null'}, ['root'])]
    for node in baseline['flow']['nodes']:
        slots = actions[node['type']].slots if node['type'] in actions else []
        if slots:
            locations.append(location({'const':node['id']}, slots))
    new_slots = sorted({slot for action in actions.values() for slot in action.slots})
    if new_slots:
        locations.append(location(new_id, new_slots))
    defs['ProposalLocation'] = {'oneOf':locations}
    defs['SetMetadataOperation']['properties']['name']['description'] = 'Nuevo nombre visible solicitado para el bot, no el nombre de un campo. Omitelo si el usuario no pidio renombrar.'
    defs['SetMetadataOperation']['properties']['description']['description'] = 'Nueva descripcion visible; omitela si no se pidio cambiar la descripcion.'
    patch = {
        'type': 'object', 'properties': {
            'kind': {'const': 'patch'}, 'summary': {'type': 'string', 'minLength': 1},
            'operations': schema['properties']['operations'],
        }, 'required': ['kind', 'summary', 'operations'], 'additionalProperties': False,
    }
    return _ollama_compatible_schema({'$defs': defs, 'oneOf': [*answers, patch]})


def parse_editor_response(content: str, request: ChatRequest, *, max_depth=DEFAULT_MAX_JSON_DEPTH):
    if len(content) > MAX_GENERATION_CODE_POINTS or len(content.encode('utf-8')) > MAX_GENERATION_BYTES:
        raise ProposalValidationError('editor response exceeds generation limits')
    try:
        raw = json.loads(content, object_pairs_hook=_reject_duplicate_json_keys,
                         parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        validate_json_tree(raw, max_depth)
    except (ValueError, RecursionError) as error:
        raise ProposalValidationError('editor response must be complete bounded JSON') from error
    if not isinstance(raw, dict) or raw.get('kind') != 'patch':
        # Preserve validation of existing full-flow responses during migration.
        return parse_editor_turn(content, request, max_depth=max_depth)
    for operation in raw.get('operations', []) if isinstance(raw.get('operations'), list) else []:
        if isinstance(operation, dict) and 'command' in operation:
            if 'op' in operation:
                raise ProposalValidationError('patch has conflicting command and op')
            operation['op'] = operation.pop('command')
    if isinstance(raw.get('operations'), list):
        signatures = [json.dumps(operation, sort_keys=True, separators=(',', ':')) for operation in raw['operations']]
        if len(signatures) != len(set(signatures)):
            raise ProposalValidationError('patch repeats identical operations', repair_details=[
                'No repitas operaciones idénticas. Emite una sola operación por cambio solicitado y conserva el resto del bot.',
            ])
    if set(raw) != {'kind', 'summary', 'operations'}:
        raise ProposalValidationError('patch requires only kind, summary and operations')
    context = request.editor_context
    if context is None:
        raise ProposalValidationError('patch requires editor context')
    arguments = AgentProposalArguments.model_validate({key: raw[key] for key in ('summary', 'operations')})
    baseline = context.working_bot if context.working_bot is not None else context.bot
    params_by_id = {node['id']: copy.deepcopy(node['params']) for node in baseline['flow']['nodes']}
    operations = dump_tree_operations(arguments.operations)
    for operation_index, operation in enumerate(operations):
        if operation['op'] == 'updateNodeParams':
            node_id = operation['nodeId']
            if node_id not in params_by_id:
                raise ProposalValidationError('patch references an unknown node', repair_details=['Usa el id exacto del bloque presente en BOT_ACTUAL_EN_EDITOR.'])
            if not operation['params']:
                raise ProposalValidationError('parameter edit must change at least one field')
            operation['params'] = {**params_by_id[node_id], **operation['params']}
            params_by_id[node_id] = copy.deepcopy(operation['params'])
        elif operation['op'] == 'addNode':
            params_by_id[operation['node']['id']] = copy.deepcopy(operation['node']['params'])
        elif operation['op'] == 'replaceNode':
            params_by_id[operation['nodeId']] = copy.deepcopy(operation['params'])
        elif operation['op'] == 'removeNode':
            params_by_id.pop(operation['nodeId'], None)
        elif operation['op'] == 'moveNode':
            # Model-only append convention: len(siblings) before removing the
            # source means the end, just as it does for addNode. Public moves
            # keep their original contract (index after removing the source).
            prefix = mcp_preview_bot_patch(baseline, operations[:operation_index]) if operation_index else None
            current = prefix['data']['previewBot'] if prefix and prefix.get('ok') else baseline if not operation_index else None
            if current is not None:
                location = operation['location']
                parent = next((node for node in current['flow']['nodes'] if node['id'] == location['parentId']), None)
                siblings = current['flow']['root'] if location['parentId'] is None and location['slot'] == 'root' else parent['slots'].get(location['slot'], []) if parent else []
                if operation['nodeId'] in siblings and location['index'] == len(siblings):
                    location['index'] -= 1
    return AgentProposal(kind='proposal', proposal=AgentProposalArguments.model_validate({
        'summary': arguments.summary, 'operations': operations,
    }))
