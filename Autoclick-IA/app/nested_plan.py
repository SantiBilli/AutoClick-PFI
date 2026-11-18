"""Bounded representation adapter for model-authored nested creation plans.

Placement is supplied by the model's tree; no actions or values are inferred.
"""
import copy
from app.agent import ProposalValidationError, DEFAULT_MAX_JSON_DEPTH

MAX_PLAN_NODES = 40


def nested_plan_schema(flat_schema, actions):
    schema = copy.deepcopy(flat_schema)
    variants = schema['$defs']['PlannedNode']['oneOf']
    for variant in variants:
        action = actions[variant['properties']['action']['const']]
        # Optional variable declarations still need an explicit decision. Their
        # generation schema allows null when no optional binding is wanted.
        # The adapter translates that explicit absence into an omitted field
        # because the canonical runtime does not accept a present null value.
        params = variant['properties']['params']
        required = params.setdefault('required', [])
        for field in action.fields:
            if field.type == 'variable' and field.name not in required:
                required.append(field.name)
        variant['properties'].pop('location')
        variant['required'].remove('location')
        variant['properties']['slots'] = {
            'type': 'object', 'properties': {
                slot: {'type': 'array', 'items': {'$ref': '#/$defs/NestedNode'}, 'maxItems': MAX_PLAN_NODES}
                for slot in action.slots},
            'required': list(action.slots), 'additionalProperties': False,
        }
        variant['required'].append('slots')
    schema['$defs'] = {'NestedNode': {'oneOf': variants}}
    flow = schema['oneOf'][0]['properties']['flow']
    flow['items'] = {'$ref': '#/$defs/NestedNode'}
    flow['minItems'] = 1  # Selected types may occur inside a root container.
    return schema


def flatten_nested_plan(payload, actions, selected):
    if not isinstance(payload, dict) or not isinstance(payload.get('flow'), list):
        raise ProposalValidationError('nested plan requires a root list')
    rows = []
    allowed = set(selected)

    def visit(items, depth, slot):
        if depth >= DEFAULT_MAX_JSON_DEPTH or not isinstance(items, list):
            raise ProposalValidationError('nested plan exceeds placement bounds')
        for item in items:
            if len(rows) >= MAX_PLAN_NODES:
                raise ProposalValidationError('nested plan exceeds node bound')
            if not isinstance(item, dict) or set(item) != {'action', 'params', 'slots'}:
                raise ProposalValidationError('nested plan node requires action, params and slots')
            action_id = item['action']
            if not isinstance(action_id, str) or action_id not in allowed:
                raise ProposalValidationError('nested plan uses an unselected action')
            action = actions[action_id]
            if (not isinstance(item['params'], dict) or not isinstance(item['slots'], dict)
                    or set(item['slots']) != set(action.slots)):
                raise ProposalValidationError('nested plan slots must match their container')
            params = copy.deepcopy(item['params'])
            for field in action.fields:
                if field.type == 'variable' and not field.required and params.get(field.name) is None:
                    params.pop(field.name, None)
            rows.append({'action': action_id, 'location': {'depth': depth, 'slot': slot},
                         'params': params})
            for child_slot in action.slots:
                visit(item['slots'][child_slot], depth + 1, child_slot)
    visit(payload['flow'], 0, 'root')
    return {**payload, 'flow': rows}
