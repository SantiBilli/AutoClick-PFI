import { actionsById, isValidFieldValue } from '@/bot/registry';
import { isPendingParameter, allowsPendingParameter } from '@/bot/pending';
import type { ActionField } from '@/bot/registry';
import type { BotEditorState } from '@/bot/model';
import type { JsonValue } from '@/bot/schema';

export type ValidationIssueCode =
  | 'empty-graph'
  | 'unknown-action'
  | 'missing-parameter'
  | 'pending-parameter'
  | 'invalid-parameter'
  | 'malformed-variable-token'
  | 'variable-token-limit'
  | 'missing-variable'
  | 'ambiguous-variable'
  | 'duplicate-output'
  | 'variable-cycle'
  | 'variable-depth'
  | 'variable-size'
  | 'coordinate-pair'
  | 'invalid-key'
  | 'invalid-cell'
  | 'invalid-excel-path'
  | 'missing-workbook'
  | 'duplicate-workbook'
  | 'closed-workbook'
  | 'duplicate-workbook-path'
  | 'invalid-sequence';

export type ValidationIssue = {
  code: ValidationIssueCode;
  severity: 'error' | 'warning';
  message: string;
  nodeId?: string;
  fieldName?: string;
};

const TOKEN_COMPATIBLE_TYPES = new Set<ActionField['type']>(['text', 'multiline', 'file', 'key', 'json', 'condition', 'integer', 'number']);
const TOKEN_NAME = /^[A-Za-z_][A-Za-z0-9_]*$/;
const TOKEN = /{{([A-Za-z_][A-Za-z0-9_]*)}}/g;
const MAX_TOKEN_COUNT = 10_000;
const VISION_DERIVED_SUFFIXES = [
  '_centroX',
  '_centrox',
  '_centroY',
  '_centroy',
  '_x',
  '_y',
  '_ancho',
  '_alto',
  '_confianza',
  '_textoDetectado',
  '_textodetectado',
  '_encontrado',
] as const;
const MAX_RESOLUTION_DEPTH = 10;
const MAX_EXPANDED_LENGTH = 100_000;
const UNKNOWN_VALUE = Symbol('runtime-value');
type ResolvableValue = JsonValue | typeof UNKNOWN_VALUE;

const MODIFIER_KEYS = new Set(['ctrl', 'shift', 'alt', 'win']);
const NAMED_KEYS = new Set([
  'backspace', 'tab', 'enter', 'esc', 'space', 'delete', 'insert', 'home', 'end', 'pageup', 'pagedown',
  'left', 'right', 'up', 'down', 'capslock', 'numlock', 'scrolllock', 'pause', 'printscreen', 'decimal',
  'add', 'subtract', 'multiply', 'divide', 'separator', 'volumeup', 'volumedown', 'volumemute', 'accept',
  'apps', 'browserback', 'browserfavorites', 'browserforward', 'browserhome', 'browserrefresh', 'browsersearch',
  'browserstop', 'clear', 'convert', 'del', 'escape', 'execute', 'final', 'fn', 'hanguel', 'hangul', 'hanja',
  'help', 'junja', 'kana', 'kanji', 'launchapp1', 'launchapp2', 'launchmail', 'launchmediaselect',
  'modechange', 'nexttrack', 'nonconvert', 'pgdn', 'pgup', 'playpause', 'prevtrack', 'print', 'prntscrn',
  'prtsc', 'prtscr', 'return', 'select', 'sleep', 'stop', 'yen', 'command', 'option', 'optionleft',
  'optionright', 'altleft', 'altright', 'ctrlleft', 'ctrlright', 'shiftleft', 'shiftright', 'winleft', 'winright',
]);
const KEY_ALLOWLIST = new Set([
  ...MODIFIER_KEYS,
  ...NAMED_KEYS,
  ...'abcdefghijklmnopqrstuvwxyz0123456789',
  ...Array.from({ length: 10 }, (_, index) => `num${index}`),
  ...Array.from({ length: 24 }, (_, index) => `f${index + 1}`),
]);
const EXCEL_EXTENSIONS = new Set(['.xls', '.xlsx', '.xlsm', '.xlsb']);
const WINDOWS_DEVICE_NAMES = new Set([
  'con', 'prn', 'aux', 'nul',
  ...Array.from({ length: 9 }, (_, index) => `com${index + 1}`),
  ...Array.from({ length: 9 }, (_, index) => `lpt${index + 1}`),
  'com\u00b9', 'com\u00b2', 'com\u00b3', 'lpt\u00b9', 'lpt\u00b2', 'lpt\u00b3',
]);

export function hasMalformedVariableToken(value: string): boolean {
  let cursor = 0;
  while (cursor < value.length) {
    const opening = value.indexOf('{{', cursor);
    const orphanClosing = value.indexOf('}}', cursor);
    if (orphanClosing !== -1 && (opening === -1 || orphanClosing < opening)) return true;
    if (opening === -1) return false;
    const closing = value.indexOf('}}', opening + 2);
    if (closing === -1 || !TOKEN_NAME.test(value.slice(opening + 2, closing))) return true;
    cursor = closing + 2;
  }
  return false;
}

export function validateEditorState(state: BotEditorState): ValidationIssue[] {
  const issues: ValidationIssue[] = [];
  if (state.representation === 'readOnlyGraph') return [{ code: 'invalid-sequence', severity: 'error', message: 'El grafo no puede representarse como un árbol ordenado.' }];
  if (state.root.length === 0) {
    issues.push({ code: 'empty-graph', severity: 'warning', message: 'El flujo no contiene bloques.' });
    return issues;
  }

  for (const node of orderedNodes(state)) {
    const action = actionsById.get(node.data.actionType);
    if (!action) {
      issues.push({ code: 'unknown-action', severity: 'error', nodeId: node.id, message: 'El tipo de bloque no es compatible.' });
    } else {
      for (const field of action.fields) {
        const value = node.data.params[field.name];
        if (isPendingParameter(value) && allowsPendingParameter(field)) {
          issues.push({ code: 'pending-parameter', severity: 'warning', nodeId: node.id, fieldName: field.name,
            message: `Pendiente: completá ${field.label} antes de ejecutar.` });
          continue;
        }
        if (value === undefined || (value === null && field.type !== 'json') || (field.required && value === '')) {
          if (field.required) issues.push(parameterIssue('missing-parameter', node.id, field.name, 'Falta un parámetro obligatorio.'));
          continue;
        }
        if (!isValidFieldValue(field, value)) {
          issues.push(parameterIssue('invalid-parameter', node.id, field.name, 'El parámetro no tiene un valor válido.'));
        }
        if (TOKEN_COMPATIBLE_TYPES.has(field.type) && typeof value === 'string' && hasMalformedVariableToken(value)) {
          issues.push(parameterIssue('malformed-variable-token', node.id, field.name, 'La referencia de variable no tiene un formato válido.'));
        }
      }
    }
  }
  return issues;
}

export function validateExecutionReadiness(state: BotEditorState, botDirectoryPath: string): ValidationIssue[] {
  const issues = validateEditorState(state).filter((issue) => {
    if (issue.code !== 'invalid-parameter' || !issue.nodeId || !issue.fieldName) return true;
    const node = state.nodes.find((candidate) => candidate.id === issue.nodeId);
    const field = actionsById.get(node?.data.actionType ?? '')?.fields.find((candidate) => candidate.name === issue.fieldName);
    const value = node?.data.params[issue.fieldName];
    if (issue.fieldName === 'value' && ['variable.create', 'excel.writeCell'].includes(node?.data.actionType ?? '')) return false;
    return field?.type === 'variable' || typeof value !== 'string' || !value.includes('{{');
  });
  if (state.root.length === 0) return issues;

  let values = new Map<string, ResolvableValue>();
  let liveWorkbooks = new Set<string>();
  let maybeLiveWorkbooks = new Set<string>();
  let closedWorkbooks = new Set<string>();
  let openedPaths = new Set<string>();
  let logicalResolution: { width: number; height: number } | null = null;
  validateVariableGraph(state, issues);
  validateLoopSafety(state, issues);
  validateGotoSafety(state, issues);
  const { before: variableStates, ambiguousBefore, reachable } = preflightVariableStates(state);
  const variableOwners = preflightVariableOwners(state);
  const resourceStates = preflightResourceStates(state, botDirectoryPath);
  const resourceOwners = preflightResourceOwners(state, botDirectoryPath);

  for (const node of orderedNodes(state)) {
    const invalidNodes = new Set(issues.filter((issue) => issue.severity === 'error').map((issue) => issue.nodeId).filter(Boolean));
    values = new Map(
      [...(variableStates.get(node.id) ?? new Map())].filter(([name]) => !invalidNodes.has(variableOwners.get(name))),
    );
    const ambiguousVariables = ambiguousBefore.get(node.id) ?? new Set<string>();
    const resources = resourceStates.get(node.id)!;
    liveWorkbooks = new Set([...resources.live].filter((name) => !invalidNodes.has(resourceOwners.names.get(name))));
    maybeLiveWorkbooks = new Set([...resources.maybeLive].filter((name) => !invalidNodes.has(resourceOwners.names.get(name))));
    closedWorkbooks = new Set(resources.closed);
    openedPaths = new Set([...resources.opened].filter((path) => !invalidNodes.has(resourceOwners.paths.get(path))));
    logicalResolution = resources.resolution;
    const action = actionsById.get(node.data.actionType);
    if (!action) continue;
    if (!reachable.has(node.id)) continue;
    const resolved = new Map<string, ResolvableValue>();

    for (const field of action.fields) {
      let configured = node.data.params[field.name];
      if (configured === undefined && field.name in action.defaults) configured = action.defaults[field.name] as JsonValue;
      if (configured === null && field.type !== 'json' && field.name in action.defaults) configured = action.defaults[field.name] as JsonValue;
      if (configured === undefined || (configured === null && field.type !== 'json') || (field.required && configured === '')) continue;
      if (isPendingParameter(configured) && allowsPendingParameter(field)) {
        resolved.set(field.name, UNKNOWN_VALUE);
        continue;
      }
      if (field.type === 'variable') {
        const outputs = new Set([...(action.outputs.map((output) => output.field)), ...(action.output ? [action.output.field] : [])]);
        if (typeof configured === 'string' && ambiguousVariables.has(configured) && (!outputs.has(field.name) || ['variable.create', 'variable.update', 'variable.delete'].includes(node.data.actionType))) {
          addIssue(issues, parameterIssue('ambiguous-variable', node.id, field.name, 'La variable puede no existir en todas las continuaciones.'));
          continue;
        }
        resolved.set(field.name, configured as JsonValue);
        continue;
      }
      try {
        if ([...templateNames(configured)].some((name) => ambiguousVariables.has(name))) {
          addIssue(issues, parameterIssue('ambiguous-variable', node.id, field.name, 'La variable puede no existir en todas las continuaciones.'));
          continue;
        }
        let value = resolveValue(configured as JsonValue, values);
        if (field.type === 'condition' && hasRuntimeUnknown(value)) value = UNKNOWN_VALUE;
        resolved.set(field.name, value);
        const jsonValueField = field.type === 'json' || field.type === 'condition' || field.name === 'value' && ['variable.create', 'excel.writeCell'].includes(node.data.actionType);
        if (value !== UNKNOWN_VALUE && !jsonValueField && !isValidFieldValue(field, value)) {
          addIssue(issues, parameterIssue('invalid-parameter', node.id, field.name, 'El parámetro no tiene un valor válido.'));
        }
        if (node.data.actionType === 'excel.writeCell' && field.name === 'value' && value !== UNKNOWN_VALUE && !isExcelScalar(value)) {
          addIssue(issues, parameterIssue('invalid-parameter', node.id, field.name, 'El valor de Excel debe ser un dato simple.'));
        }
      } catch (error) {
        addResolutionIssue(issues, node.id, field.name, error);
      }
    }

    if (['mouse.move', 'mouse.click', 'mouse.rightClick', 'mouse.doubleClick'].includes(node.data.actionType)) {
      const x = resolved.get('x');
      const y = resolved.get('y');
      if (x !== UNKNOWN_VALUE && y !== UNKNOWN_VALUE && (x === undefined) !== (y === undefined)) {
        addIssue(issues, parameterIssue('coordinate-pair', node.id, x === undefined ? 'x' : 'y', 'Las coordenadas X e Y deben configurarse juntas.'));
      } else if (logicalResolution && typeof x === 'number' && typeof y === 'number' && (
        x < 0 || y < 0 || x >= logicalResolution.width || y >= logicalResolution.height
      )) {
        addIssue(issues, parameterIssue('invalid-parameter', node.id, 'x', 'Las coordenadas están fuera de la resolución base.'));
      }
    }
    if (node.data.actionType === 'system.setBaseResolution') {
      const width = resolved.get('width');
      const height = resolved.get('height');
      if (typeof width === 'number' && typeof height === 'number') logicalResolution = { width, height };
    }
    if (node.data.actionType === 'keyboard.press') {
      const key = resolved.get('key');
      if (key !== UNKNOWN_VALUE && (typeof key !== 'string' || !isValidKeyboardKey(key))) {
        addIssue(issues, parameterIssue('invalid-key', node.id, 'key', 'La tecla o combinación no es compatible.'));
      }
    }
    if (node.data.actionType.startsWith('excel.')) {
      const cell = resolved.get('cell');
      if (cell !== undefined && cell !== UNKNOWN_VALUE && (typeof cell !== 'string' || !isValidA1Cell(cell))) {
        addIssue(issues, parameterIssue('invalid-cell', node.id, 'cell', 'La celda debe ser una referencia A1 válida dentro de Excel.'));
      }
      const range = resolved.get('range');
      if (range !== undefined && range !== UNKNOWN_VALUE && (typeof range !== 'string' || !isValidA1Range(range))) {
        addIssue(issues, parameterIssue('invalid-cell', node.id, 'range', 'El rango debe usar referencias A1 válidas dentro de Excel.'));
      }
      if (node.data.actionType === 'excel.writeRange' && typeof range === 'string') {
        const value = resolved.get('value');
        if (value !== UNKNOWN_VALUE && !excelMatrixMatchesRange(value, range)) {
          addIssue(issues, parameterIssue('invalid-parameter', node.id, 'value', 'La matriz debe ser rectangular y coincidir con el tamaño del rango.'));
        }
      }
      const path = resolved.get('path');
      if (path !== undefined && path !== '' && path !== UNKNOWN_VALUE && (typeof path !== 'string' || !isSafeExcelPath(path))) {
        addIssue(issues, parameterIssue('invalid-excel-path', node.id, 'path', 'La ruta debe ser local y usar una extensión de Excel compatible.'));
      }
    }
    if (node.data.actionType === 'flow.forRange') {
      const start = resolved.get('start'); const end = resolved.get('end'); const step = resolved.get('step');
      if (step !== UNKNOWN_VALUE && (typeof step !== 'number' || !Number.isInteger(step) || step === 0)) {
        addIssue(issues, parameterIssue('invalid-parameter', node.id, 'step', 'El paso debe ser un entero distinto de cero.'));
      } else if ([start, end, step].every((value) => typeof value === 'number') && ((end as number) - (start as number)) * (step as number) < 0) {
        addIssue(issues, parameterIssue('invalid-parameter', node.id, 'step', 'El paso debe avanzar hacia el final del rango.'));
      }
    }
    if (node.data.actionType === 'flow.forEach') {
      const items = resolved.get('items');
      if (items !== UNKNOWN_VALUE && !Array.isArray(items)) addIssue(issues, parameterIssue('invalid-parameter', node.id, 'items', 'Los elementos deben formar un arreglo JSON.'));
    }
    if (node.data.actionType === 'http.request') {
      for (const fieldName of ['headers', 'query']) {
        const value = resolved.get(fieldName);
        if (value !== undefined && value !== UNKNOWN_VALUE && (!value || Array.isArray(value) || typeof value !== 'object')) addIssue(issues, parameterIssue('invalid-parameter', node.id, fieldName, 'El valor debe ser un objeto JSON.'));
      }
    }
    if (node.data.actionType === 'workflow.run') {
      const path = resolved.get('path');
      if (path !== UNKNOWN_VALUE && (typeof path !== 'string' || !/^(?:[A-Za-z]:[\\/]|\\\\)/.test(path))) addIssue(issues, parameterIssue('invalid-parameter', node.id, 'path', 'La ruta del bot debe ser completa.'));
    }
    const workbookName = resolved.get('workbookVariable');
    if (typeof workbookName === 'string' && maybeLiveWorkbooks.has(workbookName)) {
      addIssue(issues, parameterIssue('missing-workbook', node.id, 'workbookVariable', 'El libro puede no estar abierto en todas las continuaciones.'));
    }
    const outputName = resolved.get('outputVariable');
    if (['excel.open', 'excel.create'].includes(node.data.actionType) && typeof outputName === 'string' && maybeLiveWorkbooks.has(outputName)) {
      addIssue(issues, parameterIssue('duplicate-workbook', node.id, 'outputVariable', 'El libro puede estar abierto en alguna continuación.'));
    }
    if (node.data.actionType.startsWith('file.') || node.data.actionType.startsWith('folder.')) {
      for (const fieldName of ['path', 'source', 'destination']) {
        const path = resolved.get(fieldName);
        if (path !== undefined && path !== UNKNOWN_VALUE && (typeof path !== 'string' || !/^(?:[A-Za-z]:[\\/]|\\\\)/.test(path))) {
          addIssue(issues, parameterIssue('invalid-parameter', node.id, fieldName, 'La ruta debe ser completa.'));
        }
      }
    }

    if (issues.some((issue) => issue.nodeId === node.id)) continue;
    if (node.data.actionType === 'variable.create') {
      const name = resolved.get('name');
      if (typeof name === 'string') {
        if (values.has(name)) addIssue(issues, parameterIssue('duplicate-output', node.id, 'name', 'Ya existe una variable con ese nombre.'));
        else values.set(name, resolved.get('value') ?? '');
      }
      continue;
    }
    if (['variable.update', 'variable.delete'].includes(node.data.actionType)) {
      const name = resolved.get('name');
      if (typeof name === 'string' && !values.has(name)) addIssue(issues, parameterIssue('missing-variable', node.id, 'name', 'La variable debe existir antes de usarla.'));
      else if (typeof name === 'string' && node.data.actionType === 'variable.update') values.set(name, resolved.get('value') ?? null);
      else if (typeof name === 'string') values.delete(name);
      continue;
    }
    if (['excel.open', 'excel.create'].includes(node.data.actionType)) {
      const name = resolved.get('outputVariable');
      const path = resolved.get('path');
      let valid = true;
      if (typeof name === 'string' && liveWorkbooks.has(name)) {
        addIssue(issues, parameterIssue('duplicate-workbook', node.id, 'outputVariable', 'Ya existe un libro abierto con ese nombre.'));
        valid = false;
      }
      const normalizedPath = typeof path === 'string' ? canonicalizeWindowsPath(path, botDirectoryPath) : null;
      if (normalizedPath && openedPaths.has(normalizedPath)) {
        addIssue(issues, parameterIssue('duplicate-workbook-path', node.id, 'path', 'Ese archivo ya fue abierto en esta ejecución.'));
        valid = false;
      }
      if (valid && typeof name === 'string') {
        liveWorkbooks.add(name);
        closedWorkbooks.delete(name);
        if (normalizedPath) openedPaths.add(normalizedPath);
      }
      continue;
    }

    const workbook = resolved.get('workbookVariable');
    let workbookValid = true;
    if (node.data.actionType.startsWith('excel.') && typeof workbook === 'string') {
      if (closedWorkbooks.has(workbook)) {
        addIssue(issues, parameterIssue('closed-workbook', node.id, 'workbookVariable', 'El libro ya fue cerrado.'));
        workbookValid = false;
      } else if (!liveWorkbooks.has(workbook)) {
        addIssue(issues, parameterIssue('missing-workbook', node.id, 'workbookVariable', 'El libro debe abrirse antes de usarlo.'));
        workbookValid = false;
      }
    }
    if (node.data.actionType === 'excel.close' && workbookValid && typeof workbook === 'string') {
      liveWorkbooks.delete(workbook);
      closedWorkbooks.add(workbook);
      continue;
    }
    if (node.data.actionType.startsWith('excel.') && !workbookValid) continue;
    for (const outputDefinition of action.outputs.length ? action.outputs : action.output ? [action.output] : []) {
      if (outputDefinition.type === 'workbook') continue;
      const output = resolved.get(outputDefinition.field);
      if (typeof output === 'string') {
        if (values.has(output)) addIssue(issues, parameterIssue('duplicate-output', node.id, outputDefinition.field, 'Ya existe una variable con ese nombre.'));
        else values.set(output, UNKNOWN_VALUE);
      }
    }
  }
  return issues;
}

type ResolutionErrorCode = 'malformed' | 'limit' | 'missing' | 'cycle' | 'depth' | 'size';

class ResolutionError extends Error {
  constructor(readonly code: ResolutionErrorCode) { super(code); }
}

function tokenMatches(value: string, budget: { remaining: number }) {
  if (value.includes('{{{') || value.includes('}}}')) throw new ResolutionError('malformed');
  const matches = [...value.matchAll(TOKEN)];
  budget.remaining -= matches.length;
  if (budget.remaining < 0) throw new ResolutionError('limit');
  if (value.replace(TOKEN, '').includes('{{') || value.replace(TOKEN, '').includes('}}')) throw new ResolutionError('malformed');
  return matches;
}

function resolveValue(
  value: JsonValue,
  variables: ReadonlyMap<string, ResolvableValue>,
  stack: string[] = [],
  depth = 0,
  budget = { remaining: MAX_TOKEN_COUNT },
): ResolvableValue {
  if (isPendingParameter(value)) return UNKNOWN_VALUE;
  if (Array.isArray(value)) {
    if (depth >= MAX_RESOLUTION_DEPTH) throw new ResolutionError('depth');
    const resolved = value.map((item) => resolveValue(item, variables, stack, depth + 1, budget)) as ResolvableValue;
    if (jsonStringLength(resolved) > MAX_EXPANDED_LENGTH) throw new ResolutionError('size');
    return resolved;
  }
  if (value && typeof value === 'object') {
    if (depth >= MAX_RESOLUTION_DEPTH) throw new ResolutionError('depth');
    const resolved = Object.fromEntries(
      Object.entries(value).map(([key, item]) => [key, resolveValue(item, variables, stack, depth + 1, budget)]),
    ) as ResolvableValue;
    if (jsonStringLength(resolved) > MAX_EXPANDED_LENGTH) throw new ResolutionError('size');
    return resolved;
  }
  if (typeof value !== 'string') return structuredClone(value);
  const matches = tokenMatches(value, budget);
  if (!matches.length) {
    if (codePointLengthExceeds(value, MAX_EXPANDED_LENGTH)) throw new ResolutionError('size');
    return value;
  }
  const whole = value.match(/^{{([A-Za-z_][A-Za-z0-9_]*)}}$/);
  if (whole) return resolveName(whole[1], variables, stack, depth, budget);
  let result = '';
  let resultLength = 0;
  let cursor = 0;
  let deferred = false;
  for (const match of matches) {
    const literal = value.slice(cursor, match.index);
    resultLength = addCodePointLength(resultLength, literal);
    result += literal;
    const resolved = resolveName(match[1], variables, stack, depth, budget);
    if (resolved === UNKNOWN_VALUE) {
      deferred = true;
    } else {
      const rendered = typeof resolved === 'string' ? resolved : JSON.stringify(resolved);
      resultLength = addCodePointLength(resultLength, rendered);
      result += rendered;
    }
    cursor = (match.index ?? 0) + match[0].length;
  }
  const tail = value.slice(cursor);
  addCodePointLength(resultLength, tail);
  if (deferred) return UNKNOWN_VALUE;
  result += tail;
  if (codePointLengthExceeds(result, MAX_EXPANDED_LENGTH)) throw new ResolutionError('size');
  return result;
}

function resolveName(name: string, variables: ReadonlyMap<string, ResolvableValue>, stack: string[], depth: number, budget: { remaining: number }): ResolvableValue {
  if (stack.includes(name)) throw new ResolutionError('cycle');
  if (!variables.has(name)) throw new ResolutionError('missing');
  if (depth >= MAX_RESOLUTION_DEPTH) throw new ResolutionError('depth');
  const value = variables.get(name)!;
  return value === UNKNOWN_VALUE ? value : resolveValue(value, variables, [...stack, name], depth + 1, budget);
}

function validateVariableGraph(state: BotEditorState, issues: ValidationIssue[]) {
  const definitions = new Map<string, ResolvableValue>();
  const owners = new Map<string, string>();
  const states = preflightVariableStates(state).before;
  for (const node of orderedNodes(state)) {
    if (node.data.actionType !== 'variable.create') continue;
    const name = node.data.params.name;
    if (typeof name !== 'string' || !TOKEN_NAME.test(name)) continue;
    if (states.get(node.id)?.has(name)) {
      addIssue(issues, parameterIssue('duplicate-output', node.id, 'name', 'Ya existe una variable con ese nombre.'));
      continue;
    }
    if (definitions.has(name)) continue;
    definitions.set(name, node.data.params.value ?? '');
    owners.set(name, node.id);
  }
  for (const [name, nodeId] of owners) {
    try {
      resolveValue(`{{${name}}}`, definitions);
    } catch (error) {
      if (error instanceof ResolutionError && ['cycle', 'depth', 'size', 'limit'].includes(error.code)) {
        addResolutionIssue(issues, nodeId, 'value', error);
      }
    }
  }
}

function addResolutionIssue(issues: ValidationIssue[], nodeId: string, fieldName: string, error: unknown) {
  if (!(error instanceof ResolutionError)) throw error;
  const details: Record<ResolutionErrorCode, [ValidationIssueCode, string]> = {
    malformed: ['malformed-variable-token', 'La referencia de variable no tiene un formato válido.'],
    limit: ['variable-token-limit', 'El campo contiene demasiadas referencias de variable.'],
    missing: ['missing-variable', 'La variable debe definirse antes de usarla.'],
    cycle: ['variable-cycle', 'Las variables contienen una referencia circular.'],
    depth: ['variable-depth', 'Las referencias de variable superan la profundidad permitida.'],
    size: ['variable-size', 'El valor expandido de la variable es demasiado grande.'],
  };
  const [code, message] = details[error.code];
  addIssue(issues, parameterIssue(code, nodeId, fieldName, message));
}

function addIssue(issues: ValidationIssue[], issue: ValidationIssue) {
  if (!issues.some((current) => current.code === issue.code && current.nodeId === issue.nodeId && current.fieldName === issue.fieldName)) issues.push(issue);
}

function isValidKeyboardKey(value: string) {
  if (!value || value !== value.trim() || value.includes(',')) return false;
  const parts = value.toLowerCase().split('+');
  if (parts.some((part) => !part || !KEY_ALLOWLIST.has(part))) return false;
  if (parts.length === 1) return true;
  const modifiers = parts.slice(0, -1);
  const key = parts.at(-1)!;
  return !MODIFIER_KEYS.has(key) && modifiers.every((part) => MODIFIER_KEYS.has(part)) && new Set(modifiers).size === modifiers.length;
}

function isValidA1Cell(value: string) {
  const match = /^([A-Za-z]{1,3})([1-9][0-9]{0,6})$/.exec(value);
  if (!match) return false;
  let column = 0;
  for (const character of match[1].toUpperCase()) column = column * 26 + character.charCodeAt(0) - 64;
  return column <= 16_384 && Number(match[2]) <= 1_048_576;
}

export function orderedNodes(state: BotEditorState) {
  const byId = new Map(state.nodes.map((node) => [node.id, node]));
  const result = [] as BotEditorState['nodes'];
  function visit(ids: string[]) {
    for (const id of ids) {
      const node = byId.get(id);
      if (!node) continue;
      result.push(node);
      Object.values(node.slots).forEach(visit);
    }
  }
  visit(state.root);
  return result;
}

function staticLoopIterationCount(node: BotEditorState['nodes'][number]): number | null {
  if (node.data.actionType === 'flow.forRange') {
    const { start, end, step } = node.data.params;
    if ([start, end, step].every(Number.isSafeInteger) && typeof start === 'number' && typeof end === 'number' && typeof step === 'number' && step !== 0 && (end - start) * step >= 0) {
      if (start === 0 && end === 0) return 0;
      return Math.floor(Math.abs(end - start) / Math.abs(step)) + 1;
    }
  }
  if (node.data.actionType === 'flow.forEach' && Array.isArray(node.data.params.items)) return node.data.params.items.length;
  return null;
}

function preflightVariableStates(state: BotEditorState) {
  const byId = new Map(state.nodes.map((node) => [node.id, node]));
  const before = new Map<string, Map<string, ResolvableValue>>();
  const ambiguousBefore = new Map<string, Set<string>>();
  const reachable = new Set<string>();
  type VariableState = readonly [Map<string, ResolvableValue>, Set<string>];
  const merge = (left: Map<string, ResolvableValue>, leftMaybe: Set<string>, right: Map<string, ResolvableValue>, rightMaybe: Set<string>) => {
    const definite = new Map<string, ResolvableValue>([...left].filter(([name]) => right.has(name)).map(([name, value]) => [name, value === right.get(name) ? value : UNKNOWN_VALUE]));
    return [definite, new Set([...left.keys(), ...right.keys(), ...leftMaybe, ...rightMaybe].filter((name) => !definite.has(name)))] as const;
  };
  function applyLeaf(node: BotEditorState['nodes'][number], current: Map<string, ResolvableValue>, maybe: Set<string>) {
    const name = node.data.params.name;
    if (node.data.actionType === 'variable.create' && typeof name === 'string' && !current.has(name) && !maybe.has(name)) current.set(name, node.data.params.value ?? '');
    else if (node.data.actionType === 'variable.update' && typeof name === 'string' && current.has(name)) current.set(name, UNKNOWN_VALUE);
    else if (node.data.actionType === 'variable.delete' && typeof name === 'string') { current.delete(name); maybe.delete(name); }
    else for (const output of actionsById.get(node.data.actionType)?.outputs ?? []) {
      const outputName = node.data.params[output.field];
      if (output.type !== 'workbook' && typeof outputName === 'string') {
        const namesToRegister = [outputName];
        if (node.data.actionType === 'vision.detectElement') {
          for (const suffix of VISION_DERIVED_SUFFIXES) namesToRegister.push(`${outputName}${suffix}`);
        }
        for (const outName of namesToRegister) {
          if (!current.has(outName) && !maybe.has(outName)) current.set(outName, UNKNOWN_VALUE);
        }
      }
    }
  }
  function definedNames(ids: string[]): Set<string> {
    const names = new Set<string>();
    for (const id of ids) {
      const node = byId.get(id); if (!node) continue;
      if (node.data.actionType === 'variable.create' && typeof node.data.params.name === 'string') names.add(node.data.params.name);
      for (const output of actionsById.get(node.data.actionType)?.outputs ?? []) {
        const name = node.data.params[output.field];
        if (output.type !== 'workbook' && typeof name === 'string') {
          names.add(name);
          if (node.data.actionType === 'vision.detectElement') {
            for (const suffix of VISION_DERIVED_SUFFIXES) names.add(`${name}${suffix}`);
          }
        }
      }
      Object.values(node.slots).forEach((children) => definedNames(children).forEach((name) => names.add(name)));
    }
    return names;
  }
  function catchEntry(ids: string[], incoming: Map<string, ResolvableValue>, incomingMaybe: Set<string>) {
    const current = new Map(incoming); const maybe = new Set(incomingMaybe);
    for (let index = 0; index < ids.length; index += 1) {
      const node = byId.get(ids[index]); if (!node) continue;
      if (['variable.create', 'variable.update', 'variable.delete', 'flow.comment'].includes(node.data.actionType)) applyLeaf(node, current, maybe);
      else { definedNames(ids.slice(index)).forEach((name) => { if (!current.has(name)) maybe.add(name); }); break; }
    }
    return [current, maybe] as const;
  }
  function sequence(ids: string[], incoming: Map<string, ResolvableValue>, incomingMaybe = new Set<string>()): VariableState {
    if (!ids.length) return [new Map(incoming), new Set(incomingMaybe)];
    const mergeOptional = (...states: Array<VariableState | null>): VariableState | null => {
      const present = states.filter((value): value is VariableState => value !== null);
      if (!present.length) return null;
      return present.slice(1).reduce((result, value) => merge(...result, ...value), present[0]);
    };
    const same = (left: VariableState | null, right: VariableState | null) => {
      if (!left || !right) return left === right;
      return left[0].size === right[0].size && left[1].size === right[1].size
        && [...left[0]].every(([name, value]) => right[0].get(name) === value)
        && [...left[1]].every((name) => right[1].has(name));
    };
    function transfer(node: BotEditorState['nodes'][number], input: VariableState): VariableState | null {
      let current = new Map(input[0]); let maybe = new Set(input[1]);
      if (node.data.actionType === 'flow.if') {
        return mergeOptional(sequence(node.slots.then ?? [], current, maybe), sequence(node.slots.else ?? [], current, maybe));
      }
      if (node.data.actionType === 'flow.tryCatch') {
        const base = new Map(current); const baseMaybe = new Set(maybe); const errorName = node.data.params.errorVariable;
        if (typeof errorName === 'string' && errorName) base.set(errorName, null);
        const tried = sequence(node.slots.try ?? [], base, baseMaybe);
        const catchBase = catchEntry(node.slots.try ?? [], base, baseMaybe);
        const caught = sequence(node.slots.catch ?? [], ...catchBase);
        const combined = mergeOptional(tried, caught); if (!combined) return null;
        [current, maybe] = combined;
        if (typeof errorName === 'string' && errorName) { current.set(errorName, UNKNOWN_VALUE); maybe.delete(errorName); }
        return [current, maybe];
      }
      if (node.data.actionType === 'flow.group') {
        return sequence(node.slots.body ?? [], current, maybe);
      }
      if (['flow.forRange', 'flow.forEach', 'flow.while'].includes(node.data.actionType)) {
        const incomingNames = new Set(current.keys()); const body = new Map(current); const bodyMaybe = new Set(maybe);
        const names = node.data.actionType === 'flow.forRange' ? [node.data.params.currentVariable]
          : node.data.actionType === 'flow.forEach' ? [node.data.params.itemVariable, node.data.params.indexVariable] : [];
        names.forEach((name) => { if (typeof name === 'string' && name) { body.set(name, UNKNOWN_VALUE); bodyMaybe.delete(name); } });
        const bodyOutput = sequence(node.slots.body ?? [], body, bodyMaybe);
        if (!bodyOutput) return staticLoopIterationCount(node) ? null : [current, maybe];
        const [bodyResult, bodyResultMaybe] = bodyOutput;
        const count = staticLoopIterationCount(node);
        if (count === 1) return [bodyResult, bodyResultMaybe];
        for (const name of current.keys()) if (!bodyResult.has(name) || bodyResult.get(name) !== current.get(name)) current.set(name, UNKNOWN_VALUE);
        const guaranteed = count !== null && count > 0;
        for (const name of [...bodyResult.keys()].filter((name) => !incomingNames.has(name))) {
          if (guaranteed) { current.set(name, UNKNOWN_VALUE); maybe.delete(name); } else maybe.add(name);
        }
        bodyResultMaybe.forEach((name) => { if (!current.has(name)) maybe.add(name); });
        names.forEach((name) => {
          if (typeof name !== 'string' || !name) return;
          if (guaranteed) { current.set(name, UNKNOWN_VALUE); maybe.delete(name); }
          else maybe.add(name);
        });
        return [current, maybe];
      }
      applyLeaf(node, current, maybe);
      return [current, maybe];
    }
    const positions = new Map(ids.map((id, index) => [id, index]));
    const inputs: Array<VariableState | null> = Array(ids.length).fill(null);
    inputs[0] = [new Map(incoming), new Set(incomingMaybe)];
    const queue = [0];
    const exits = new Map<number, VariableState>();
    while (queue.length) {
      const index = queue.shift()!; const current = inputs[index]; if (!current) continue;
      const node = byId.get(ids[index]); if (!node) continue;
      reachable.add(node.id);
      const recorded = mergeOptional(before.has(node.id) ? [before.get(node.id)!, ambiguousBefore.get(node.id)!] : null, current)!;
      before.set(node.id, recorded[0]); ambiguousBefore.set(node.id, recorded[1]);
      const output = transfer(node, current); if (!output) continue;
      let successor: number | undefined;
      if (node.data.actionType === 'flow.goTo') {
        const target = node.data.params.targetNodeId;
        if (typeof target === 'string') successor = positions.get(target);
      } else if (index + 1 < ids.length) successor = index + 1;
      else { exits.set(index, output); continue; }
      if (successor === undefined) continue;
      const joined = mergeOptional(inputs[successor], output);
      if (!same(joined, inputs[successor])) { inputs[successor] = joined; if (!queue.includes(successor)) queue.push(successor); }
    }
    return mergeOptional(...exits.values()) ?? [new Map(), new Set()];
  }
  sequence(state.root, new Map());
  state.nodes.forEach((node) => { if (!before.has(node.id)) before.set(node.id, new Map()); if (!ambiguousBefore.has(node.id)) ambiguousBefore.set(node.id, new Set()); });
  return { before, ambiguousBefore, reachable };
}

function preflightVariableOwners(state: BotEditorState) {
  const owners = new Map<string, string>();
  for (const node of state.nodes) {
    const names: unknown[] = node.data.actionType === 'variable.create' ? [node.data.params.name] : [];
    for (const output of actionsById.get(node.data.actionType)?.outputs ?? []) {
      if (output.type !== 'workbook') {
        const outName = node.data.params[output.field];
        names.push(outName);
        if (node.data.actionType === 'vision.detectElement' && typeof outName === 'string') {
          for (const suffix of VISION_DERIVED_SUFFIXES) names.push(`${outName}${suffix}`);
        }
      }
    }
    names.forEach((name) => { if (typeof name === 'string' && !owners.has(name)) owners.set(name, node.id); });
  }
  return owners;
}

function templateNames(value: unknown): Set<string> {
  if (typeof value === 'string') return new Set(tokenMatches(value, { remaining: MAX_TOKEN_COUNT }).map((match) => match[1]));
  if (Array.isArray(value)) return new Set(value.flatMap((item) => [...templateNames(item)]));
  if (value && typeof value === 'object') return new Set(Object.values(value).flatMap((item) => [...templateNames(item)]));
  return new Set();
}

function validateLoopSafety(state: BotEditorState, issues: ValidationIssue[]) {
  const byId = new Map(state.nodes.map((node) => [node.id, node]));
  function body(ids: string[], iterations: number | null, incoming: Set<string>) {
    for (const id of ids) {
      const node = byId.get(id); if (!node) continue;
      if (node.data.actionType === 'variable.create' && (iterations === null || iterations > 1)) {
        addIssue(issues, parameterIssue('ambiguous-variable', node.id, 'name', 'La variable no puede crearse de forma segura en múltiples iteraciones.'));
      }
      if (node.data.actionType === 'variable.delete' && typeof node.data.params.name === 'string' && incoming.has(node.data.params.name)) addIssue(issues, parameterIssue('ambiguous-variable', node.id, 'name', 'No se puede eliminar una variable previa desde un bucle opcional o repetido.'));
      if (['excel.open', 'excel.create'].includes(node.data.actionType) && (iterations === null || iterations > 1)) addIssue(issues, parameterIssue('duplicate-workbook', node.id, 'outputVariable', 'No se pueden abrir libros dentro de un bucle opcional o repetido.'));
      if (node.data.actionType === 'excel.close' && (iterations === null || iterations > 1)) addIssue(issues, parameterIssue('closed-workbook', node.id, 'workbookVariable', 'No se puede cerrar el mismo libro en múltiples iteraciones.'));
      Object.values(node.slots).forEach((children) => body(children, iterations, incoming));
    }
  }
  function walk(ids: string[], known: Set<string>) {
    for (const id of ids) {
      const node = byId.get(id); if (!node) continue;
      if (['flow.forRange', 'flow.forEach', 'flow.while'].includes(node.data.actionType)) body(node.slots.body ?? [], staticLoopIterationCount(node), new Set(known));
      Object.values(node.slots).forEach((children) => walk(children, new Set(known)));
      if (node.data.actionType === 'variable.create' && typeof node.data.params.name === 'string') known.add(node.data.params.name);
    }
  }
  walk(state.root, new Set());
}

function validateGotoSafety(state: BotEditorState, issues: ValidationIssue[]) {
  const byId = new Map(state.nodes.map((node) => [node.id, node]));
  function container(ids: string[]) {
    const positions = new Map(ids.map((id, index) => [id, index]));
    ids.forEach((id, index) => {
      const node = byId.get(id); if (!node) return;
      if (node.data.actionType === 'flow.goTo') {
        const target = node.data.params.targetNodeId;
        const targetIndex = typeof target === 'string' ? positions.get(target) : undefined;
        if (targetIndex === undefined) addIssue(issues, parameterIssue('invalid-sequence', id, 'targetNodeId', 'El destino debe estar en la misma secuencia ordenada.'));
      }
      Object.values(node.slots).forEach(container);
    });
  }
  container(state.root);
}

type ResourceSnapshot = {
  live: Set<string>; maybeLive: Set<string>; closed: Set<string>; opened: Set<string>;
  resolution: { width: number; height: number } | null;
};

function preflightResourceStates(state: BotEditorState, botDirectoryPath: string) {
  const byId = new Map(state.nodes.map((node) => [node.id, node]));
  const before = new Map<string, ResourceSnapshot>();
  const copy = (value: ResourceSnapshot): ResourceSnapshot => ({ live: new Set(value.live), maybeLive: new Set(value.maybeLive), closed: new Set(value.closed), opened: new Set(value.opened), resolution: value.resolution });
  function merge(values: ResourceSnapshot[]): ResourceSnapshot {
    const live = new Set([...values[0].live].filter((name) => values.slice(1).every((value) => value.live.has(name))));
    const possible = new Set(values.flatMap((value) => [...value.live, ...value.maybeLive]));
    const closed = new Set([...values[0].closed].filter((name) => values.slice(1).every((value) => value.closed.has(name))));
    const firstResolution = values[0].resolution;
    return {
      live,
      maybeLive: new Set([...possible].filter((name) => !live.has(name))),
      closed,
      opened: new Set(values.flatMap((value) => [...value.opened])),
      resolution: values.slice(1).every((value) => value.resolution?.width === firstResolution?.width && value.resolution?.height === firstResolution?.height) ? firstResolution : null,
    };
  }
  const canFail = (node: BotEditorState['nodes'][number]) => {
    if (node.data.actionType === 'flow.if') return templateNames(node.data.params.condition).size > 0;
    if (['flow.forRange', 'flow.forEach', 'flow.while'].includes(node.data.actionType)) return templateNames(node.data.params).size > 0;
    return !['flow.group', 'flow.tryCatch', 'flow.comment', 'variable.create', 'variable.update', 'variable.delete', 'system.setBaseResolution'].includes(node.data.actionType);
  };
  function sequence(ids: string[], input: ResourceSnapshot, failures?: ResourceSnapshot[]): ResourceSnapshot {
    if (!ids.length) return copy(input);
    const mergeOptional = (...states: Array<ResourceSnapshot | null>) => {
      const present = states.filter((value): value is ResourceSnapshot => value !== null);
      return present.length ? merge(present) : null;
    };
    const same = (left: ResourceSnapshot | null, right: ResourceSnapshot | null) => Boolean(left && right
      && left.live.size === right.live.size && [...left.live].every((name) => right.live.has(name))
      && left.maybeLive.size === right.maybeLive.size && [...left.maybeLive].every((name) => right.maybeLive.has(name))
      && left.closed.size === right.closed.size && [...left.closed].every((name) => right.closed.has(name))
      && left.opened.size === right.opened.size && [...left.opened].every((name) => right.opened.has(name))
      && left.resolution?.width === right.resolution?.width && left.resolution?.height === right.resolution?.height);
    function transfer(node: BotEditorState['nodes'][number], inputState: ResourceSnapshot): ResourceSnapshot | null {
      let current = copy(inputState);
      if (failures && canFail(node)) failures.push(copy(current));
      if (node.data.actionType === 'flow.if') {
        return mergeOptional(
          sequence(node.slots.then ?? [], current, failures),
          sequence(node.slots.else ?? [], current, failures),
        );
      }
      if (node.data.actionType === 'flow.tryCatch') {
        const caughtFailures: ResourceSnapshot[] = [];
        const tried = sequence(node.slots.try ?? [], current, caughtFailures);
        const catchInput = caughtFailures.length ? merge(caughtFailures) : copy(current);
        const caught = sequence(node.slots.catch ?? [], catchInput, failures);
        return mergeOptional(tried, caught);
      }
      if (node.data.actionType === 'flow.group') return sequence(node.slots.body ?? [], current, failures);
      if (['flow.forRange', 'flow.forEach', 'flow.while'].includes(node.data.actionType)) {
        const loopInput = copy(current); const result = sequence(node.slots.body ?? [], current, failures);
        return staticLoopIterationCount(node) === 1 ? result : merge([loopInput, result]);
      }
      if (['excel.open', 'excel.create'].includes(node.data.actionType)) {
        const name = node.data.params.outputVariable; if (typeof name === 'string') { current.live.add(name); current.maybeLive.delete(name); current.closed.delete(name); }
        const path = node.data.params.path; if (typeof path === 'string' && !path.includes('{{')) { const normalized = canonicalizeWindowsPath(path, botDirectoryPath); if (normalized) current.opened.add(normalized); }
      } else if (node.data.actionType === 'excel.close') {
        const name = node.data.params.workbookVariable; if (typeof name === 'string') { current.live.delete(name); current.maybeLive.delete(name); current.closed.add(name); }
      } else if (node.data.actionType === 'system.setBaseResolution') {
        const { width, height } = node.data.params; current.resolution = Number.isSafeInteger(width) && Number.isSafeInteger(height) ? { width: width as number, height: height as number } : null;
      }
      return current;
    }
    const positions = new Map(ids.map((id, index) => [id, index]));
    const inputs: Array<ResourceSnapshot | null> = Array(ids.length).fill(null); inputs[0] = copy(input);
    const queue = [0]; const exits = new Map<number, ResourceSnapshot>();
    while (queue.length) {
      const index = queue.shift()!; const current = inputs[index]; if (!current) continue;
      const node = byId.get(ids[index]); if (!node) continue;
      before.set(node.id, mergeOptional(before.get(node.id) ?? null, current)!);
      const output = transfer(node, current); if (!output) continue;
      let successor: number | undefined;
      if (node.data.actionType === 'flow.goTo') {
        const target = node.data.params.targetNodeId; if (typeof target === 'string') successor = positions.get(target);
      } else if (index + 1 < ids.length) successor = index + 1;
      else { exits.set(index, output); continue; }
      if (successor === undefined) continue;
      const joined = mergeOptional(inputs[successor], output);
      if (!same(joined, inputs[successor])) { inputs[successor] = joined; if (!queue.includes(successor)) queue.push(successor); }
    }
    return mergeOptional(...exits.values()) ?? copy(input);
  }
  sequence(state.root, { live: new Set(), maybeLive: new Set(), closed: new Set(), opened: new Set(), resolution: null });
  state.nodes.forEach((node) => { if (!before.has(node.id)) before.set(node.id, { live: new Set(), maybeLive: new Set(), closed: new Set(), opened: new Set(), resolution: null }); });
  return before;
}

function preflightResourceOwners(state: BotEditorState, botDirectoryPath: string) {
  const names = new Map<string, string>(); const paths = new Map<string, string>();
  for (const node of state.nodes) if (['excel.open', 'excel.create'].includes(node.data.actionType)) {
    const name = node.data.params.outputVariable; if (typeof name === 'string' && !names.has(name)) names.set(name, node.id);
    const path = node.data.params.path; const normalized = typeof path === 'string' && !path.includes('{{') ? canonicalizeWindowsPath(path, botDirectoryPath) : null;
    if (normalized && !paths.has(normalized)) paths.set(normalized, node.id);
  }
  return { names, paths };
}

function jsonStringLength(value: ResolvableValue): number {
  if (value === UNKNOWN_VALUE) return 0;
  if (typeof value === 'string') return [...value].length;
  if (Array.isArray(value)) return value.reduce<number>((total, item) => total + jsonStringLength(item), 0);
  if (value && typeof value === 'object') return Object.values(value).reduce<number>((total, item) => total + jsonStringLength(item), 0);
  return 0;
}

function hasRuntimeUnknown(value: ResolvableValue): boolean {
  if (value === UNKNOWN_VALUE) return true;
  if (Array.isArray(value)) return value.some((item) => hasRuntimeUnknown(item as ResolvableValue));
  return Boolean(value && typeof value === 'object' && Object.values(value).some((item) => hasRuntimeUnknown(item as ResolvableValue)));
}

function isValidA1Range(value: string) {
  const parts = value.split(':');
  return (parts.length === 1 || parts.length === 2) && parts.every(isValidA1Cell);
}

function excelMatrixMatchesRange(value: ResolvableValue | undefined, range: string) {
  if (!Array.isArray(value) || !value.length || value.some((row) => !Array.isArray(row) || !row.length)) return false;
  const width = (value[0] as JsonValue[]).length;
  if (value.some((row) => (row as JsonValue[]).length !== width)) return false;
  if (value.some((row) => (row as JsonValue[]).some((cell) => !isExcelScalar(cell)))) return false;
  const [start, end = start] = range.split(':');
  if (!isValidA1Cell(start) || !isValidA1Cell(end)) return false;
  const [startColumn, startRow] = a1Parts(start);
  const [endColumn, endRow] = a1Parts(end);
  return value.length === Math.abs(endRow - startRow) + 1 && width === Math.abs(endColumn - startColumn) + 1;
}

function a1Parts(value: string): [number, number] {
  const [, letters, row] = /^([A-Za-z]+)([0-9]+)$/.exec(value)!;
  let column = 0;
  for (const character of letters.toUpperCase()) column = column * 26 + character.charCodeAt(0) - 64;
  return [column, Number(row)];
}

function addCodePointLength(current: number, value: string) {
  let length = current;
  for (const _character of value) {
    length += 1;
    if (length > MAX_EXPANDED_LENGTH) throw new ResolutionError('size');
  }
  return length;
}

function codePointLengthExceeds(value: string, maximum: number) {
  let length = 0;
  for (const _character of value) {
    length += 1;
    if (length > maximum) return true;
  }
  return false;
}

function isSafeExcelPath(value: string) {
  if (!value || /[\u0000-\u001f*?"<>|]/.test(value) || value.includes('://')) return false;
  if (/^(?:\\\\|\/\/|\\\?\\|\\\.\\|\\)/.test(value)) return false;
  const drive = /^[A-Za-z]:/.exec(value)?.[0] ?? '';
  if (drive && !/^[A-Za-z]:[\\/]/.test(value)) return false;
  if (value.slice(drive.length).includes(':')) return false;
  const segments = value.slice(drive.length).split(/[\\/]/).filter(Boolean);
  if (!segments.length || segments.some((segment) => {
    if (segment === '.' || segment === '..' || /[. ]$/.test(segment)) return true;
    return WINDOWS_DEVICE_NAMES.has(segment.trimEnd().split('.', 1)[0].toLowerCase());
  })) return false;
  const filename = segments.at(-1)!;
  const dot = filename.lastIndexOf('.');
  return dot >= 0 && EXCEL_EXTENSIONS.has(filename.slice(dot).toLowerCase());
}

function canonicalizeWindowsPath(value: string, botDirectoryPath: string) {
  const absolute = /^([A-Za-z]):[\\/]+(.*)$/.exec(value);
  const base = /^([A-Za-z]):[\\/]+(.*)$/.exec(botDirectoryPath);
  if (!base) return null;
  const drive = absolute?.[1] ?? base[1];
  const segments = [
    ...(absolute ? [] : base[2].split(/[\\/]+/)),
    ...(absolute?.[2] ?? value).split(/[\\/]+/),
  ].filter(Boolean);
  return `${drive}:\\${segments.join('\\')}`.normalize('NFC').toLowerCase();
}

function isExcelScalar(value: JsonValue): value is string | number | boolean | null {
  return value === null || ['string', 'number', 'boolean'].includes(typeof value);
}

function parameterIssue(code: ValidationIssueCode, nodeId: string, fieldName: string, message: string): ValidationIssue {
  return { code, severity: 'error', nodeId, fieldName, message };
}
