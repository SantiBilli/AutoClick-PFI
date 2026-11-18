"""Reuse validated editor operations for follow-ups to a Home draft."""
import json

from app.agent import (
    _home_bot_draft_schema, _reject_duplicate_json_keys, parse_home_bot_draft,
    validate_home_bot_draft, validate_proposal_semantics, ProposalValidationError,
)
from app.editor_patch import editor_patch_schema, parse_editor_response, NoEffectEdit
from app.editor_safety import classify_editor_intent
from app.external_facts import ExternalFactRequirement, assign_evidence, extract_evidence_spans
from app.home_intent import explicit_new_bot_request
from app.home_generation import canonical_home_content
from app.mcp_client import mcp_preview_bot_patch
from app.runtime_context import current_home_draft
from app.schemas import EditorContext
from app.tree_diff import canonical_bot_hash, dump_tree_operations


def home_edit_request(request, bot=None):
    bot = bot if bot is not None else current_home_draft(request)
    if bot is None:
        return None
    return request.model_copy(update={'editor_context': EditorContext(bot=bot, validation_issues=[])})


def home_response_schema(request, bot=None):
    schema = _home_bot_draft_schema(request)
    if classify_editor_intent(request.messages[-1].content) == 'informational':
        schema['oneOf'] = [branch for branch in schema['oneOf'] if branch['properties']['kind'].get('const') == 'answer']
        return schema
    edit_request = home_edit_request(request, bot)
    if edit_request is None:
        return schema
    patch = editor_patch_schema(edit_request)
    branches = [branch for branch in patch['oneOf'] if branch['properties']['kind'].get('const') == 'patch']
    schema.setdefault('$defs', {}).update(patch.get('$defs', {}))
    if (not explicit_new_bot_request(request.messages[-1].content)
            and (classify_editor_intent(request.messages[-1].content) == 'mutation'
                 or supplied_pending_parameters(request, edit_request.editor_context.bot))):
        schema['oneOf'] = branches
    else:
        schema['oneOf'].extend(branches)
    return schema


def supplied_pending_parameters(request, bot):
    """Detect a value reply against pending catalog fields, without applying it.

    This only selects the editing contract. The model must still choose the
    block, write the operation and pass the normal patch/provenance validation.
    """
    return bool(_pending_evidence(request, bot))


def _pending_evidence(request, bot):
    latest = request.messages[-1].content
    if '?' in latest or '¿' in latest or classify_editor_intent(latest) == 'informational':
        return ()
    actions = {action.id: action for action in request.capabilities.actions}
    requirements = {}
    for node in bot['flow']['nodes']:
        action = actions.get(node['type'])
        if action is None:
            continue
        for field in action.fields:
            if node['params'].get(field.name) == {'$pending': True}:
                requirement = ExternalFactRequirement.from_field(action.id, field, action_title=action.title)
                requirements[requirement.ref] = requirement
    return assign_evidence(tuple(requirements.values()), extract_evidence_spans(latest))


def parse_home_response(content, request):
    content = canonical_home_content(content, request)
    try:
        raw = json.loads(content, object_pairs_hook=_reject_duplicate_json_keys)
    except (ValueError, RecursionError):
        return parse_home_bot_draft(content, request)
    if not isinstance(raw, dict) or raw.get('kind') != 'patch':
        return parse_home_bot_draft(content, request)
    edit_request = home_edit_request(request)
    if edit_request is None:
        raise ProposalValidationError('Home patch requires a valid prior draft')
    outcome = parse_editor_response(content, edit_request)
    validate_proposal_semantics(outcome.proposal, edit_request)
    baseline = edit_request.editor_context.bot
    preview = mcp_preview_bot_patch(baseline, dump_tree_operations(outcome.proposal.operations))
    if not preview.get('ok'):
        raise ProposalValidationError('MCP rejected the Home patch', repair_details=[str(issue.get('message','Invalid patch')) for issue in preview.get('issues',[])])
    bot = preview['data']['previewBot']
    for assignment in _pending_evidence(request, baseline):
        ref = assignment.field_ref
        candidates = [node for node in baseline['flow']['nodes'] if node['type'] == ref.action_id
                      and node['params'].get(ref.field_name) == {'$pending': True}]
        # Several identical pending fields need model disambiguation; do not
        # choose a target from the text or silently write an extracted value.
        if len(candidates) == 1:
            after = next((node for node in bot['flow']['nodes'] if node['id'] == candidates[0]['id']), None)
            if after is not None and after['params'].get(ref.field_name) == {'$pending': True}:
                raise ProposalValidationError('supplied parameter was left pending', repair_details=[
                    f'El usuario aportó un valor para {ref.field_name} del bloque {candidates[0]["id"]}. '
                    'Propón updateNodeParams sobre ese bloque: cambiar solo el nombre o la descripción no configura el parámetro.',
                ])
    # MCP may omit slots on newly added leaves; the Home model boundary uses
    # an explicit empty object. Do not fill missing slots on containers.
    actions = {action.id: action for action in request.capabilities.actions}
    for node in bot['flow']['nodes']:
        action = actions.get(node['type'])
        if action is not None and not action.slots and 'slots' not in node:
            node['slots'] = {}
    if canonical_bot_hash(bot) == canonical_bot_hash(baseline):
        raise NoEffectEdit('patch does not change the draft', repair_details=['Compara el pedido con el estado actual. Si ya tiene el valor pedido, responde con kind=answer describiendo lo que contiene el borrador; si elegiste un valor equivocado, corrige el parche. No propongas operaciones sin efecto ni afirmes cambios realizados. Usa una descripción del valor actual, sin frases de finalización como actualizado, cambiado o configurado.'])
    return validate_home_bot_draft({'bot':bot, 'name':bot['name'], 'summary':outcome.proposal.summary}, request)


HOME_EDIT_RULES = '''[EDICION_BORRADOR_HOME]
BOT_ACTUAL_HOME muestra el borrador actual validado con sus IDs exactos. Para modificar ese borrador usa kind=patch con summary y operations; conserva sus IDs y el resto del flujo. El historial es contexto, pero el estado actual prevalece sobre versiones anteriores.
Para cambiar parametros emite {"command":"updateNodeParams","nodeId":"id exacto existente","params":{"campo":"nuevo valor"}}. Incluye solo los campos que cambian: la aplicacion conserva los demas. El valor del parametro se cambia dentro de params; describirlo en name o description no lo configura.
Para agregar usa addNode con node (id nuevo, type, params) y location (parentId, slot, index). Usa null/root para la raiz y el ID del contenedor con su slot para hijos. Para quitar usa removeNode; para mover moveNode; para nombre/descripcion setMetadata.
Las operaciones usan el mismo formato del editor pero el resultado se muestra como borrador de Inicio para revisar; no ejecuta ni guarda nada.
Si pide crear OTRO bot diferente, usa kind=updatedFlow completo. Para consultas usa kind=answer y responde sobre el borrador actual.
[/EDICION_BORRADOR_HOME]'''
