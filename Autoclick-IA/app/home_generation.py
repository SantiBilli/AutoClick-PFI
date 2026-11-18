"""Choose an action before its parameters in constrained Home output.

The transport schema places the action and location before its parameters.
This adapter changes representation only; every choice remains model output.
"""
import copy
import json

from app.agent import ProposalValidationError, _reject_duplicate_json_keys, extract_json_payload
from app.config import DEFAULT_MAX_JSON_DEPTH, MAX_GENERATION_BYTES, MAX_GENERATION_CODE_POINTS
from app.schemas import validate_json_tree


def linear_home_schema(schema, request):
    """Keep the allowed actions/parameters; serialize placement before params."""
    from app.creation_plan import creation_plan_schema
    if schema is None or 'UpdatedFlowNode' not in schema.get('$defs', {}):
        return schema
    result = copy.deepcopy(schema)
    plan = creation_plan_schema(request)
    by_id = {v['properties']['action']['const']: v for v in plan['$defs']['PlannedNode']['oneOf']}
    variants = []
    for node in schema['$defs']['UpdatedFlowNode']['oneOf']:
        variant = by_id[node['properties']['type']['const']]
        variant['properties']['params'] = copy.deepcopy(node['properties']['params'])
        variants.append(variant)
    result['$defs'].update({'PlannedNode': {'oneOf': variants}, 'PlanLocation': plan['$defs']['PlanLocation']})
    del result['$defs']['UpdatedFlowNode']
    for branch in result['oneOf']:
        if branch.get('properties', {}).get('kind', {}).get('const') == 'updatedFlow':
            branch['properties']['flow']['items'] = {'$ref': '#/$defs/PlannedNode'}
    return result


def canonical_home_content(content, request=None):
    cleaned = extract_json_payload(content)
    if len(cleaned) > MAX_GENERATION_CODE_POINTS or len(cleaned.encode('utf-8')) > MAX_GENERATION_BYTES:
        raise ProposalValidationError('home draft exceeds generation limits')
    try:
        raw = json.loads(cleaned, object_pairs_hook=_reject_duplicate_json_keys,
                         parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        validate_json_tree(raw, DEFAULT_MAX_JSON_DEPTH)
        if isinstance(raw, dict) and raw.get('kind') == 'updatedFlow':
            if raw.get('flow') and any(isinstance(node, dict) and 'location' in node for node in raw['flow']):
                from app.creation_plan import compile_creation_plan
                if request is None:
                    raise ValueError('linear Home output requires the verified catalog')
                raw = compile_creation_plan(raw, request)
            def convert(node):
                if not isinstance(node, dict):
                    raise ValueError('flow node must be an object')
                if 'action' in node:
                    if 'type' in node:
                        raise ValueError('conflicting action and type')
                    node['type'] = node.pop('action')
                for children in node.get('slots', {}).values():
                    for child in children:
                        convert(child)
            for node in raw['flow']:
                convert(node)
            return json.dumps(raw, ensure_ascii=False, separators=(',', ':'))
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError) as error:
        raise ProposalValidationError('home output is not valid bounded JSON') from error
    return cleaned
