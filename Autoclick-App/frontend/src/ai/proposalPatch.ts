import { aiBotProposalSchema, type AiBotProposal, type ProposalLocation, type ProposalOperation } from '@/ai/proposalSchema';
import { actionsById, isValidFieldValue } from '@/bot/registry';
import { isPendingParameter, allowsPendingParameter } from '@/bot/pending';
import { parseCanonicalBot, type CanonicalBot, type CanonicalBotNode, type CanonicalTreeBot, type JsonValue } from '@/bot/schema';

type MutableTree = { root: string[]; nodes: CanonicalBotNode[] };

export class ProposalPatchError extends Error {
  constructor(message = 'La propuesta no se puede aplicar al bot actual.') {
    super(message);
    this.name = 'ProposalPatchError';
  }
}

export function validateProposalResult(
  baseInput: CanonicalBot,
  proposalInput: AiBotProposal,
): CanonicalTreeBot {
  const proposal = aiBotProposalSchema.parse(proposalInput);
  const applied = applyBotProposal(baseInput, proposal);
  const supplied = parseCanonicalBot(proposal.resultingBot);
  if (supplied.schemaVersion !== 2) {
    throw new ProposalPatchError('La propuesta contiene un bot no soportado.');
  }
  if (canonicalProposalBotString(applied) !== canonicalProposalBotString(supplied)) {
    throw new ProposalPatchError('La propuesta no coincide con sus operaciones.');
  }
  return structuredClone(supplied) as CanonicalTreeBot;
}

export function canonicalProposalBotString(input: CanonicalBot): string {
  const bot = structuredClone(parseCanonicalBot(input));
  if (bot.schemaVersion !== 2) throw new ProposalPatchError('Solo los bots de secuencia se pueden comparar.');
  const treeBot = bot as CanonicalTreeBot;
  const normalized = {
    ...treeBot,
    icon: treeBot.icon ?? 'bot',
    flow: {
      ...treeBot.flow,
      nodes: treeBot.flow.nodes
        .map((node) => ({ ...node, slots: node.slots ?? {} }))
        .sort((left, right) => compareCodePoints(left.id, right.id)),
    },
  };
  return canonicalValue(normalized);
}

export function canonicalSemanticBotString(
  input: CanonicalBot & { pendingAiProposal?: unknown },
): string {
  const semantic = structuredClone(input) as Record<string, unknown>;
  delete semantic.ai;
  delete semantic.pendingAiProposal;
  return canonicalProposalBotString(semantic as CanonicalBot);
}

export async function canonicalBotRevision(
  input: CanonicalBot & { pendingAiProposal?: unknown },
): Promise<string> {
  const bytes = new TextEncoder().encode(canonicalSemanticBotString(input));
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  return Array.from(new Uint8Array(digest), (value) => value.toString(16).padStart(2, '0')).join('');
}

export function applyBotProposal(baseInput: CanonicalBot, proposalInput: AiBotProposal): CanonicalTreeBot {
  try {
    const base = parseCanonicalBot(baseInput);
    const proposal = aiBotProposalSchema.parse(proposalInput);
    if (base.schemaVersion !== 2) throw new ProposalPatchError('Solo los bots de secuencia se pueden modificar.');
    if (base.id.toLowerCase() !== proposal.baseBotId.toLowerCase()) throw new ProposalPatchError('La propuesta pertenece a otro bot.');

    const draft = structuredClone(base) as CanonicalTreeBot;
    const tree: MutableTree = draft.flow;
    for (const operation of proposal.operations) {
      if (operation.op === 'setMetadata') {
        if (operation.name !== undefined && operation.name !== null) draft.name = operation.name;
        if (operation.description !== undefined && operation.description !== null) draft.description = operation.description;
        continue;
      }
      if (operation.op === 'addNode') {
        if (tree.nodes.some(({ id }) => id === operation.node.id)) throw new ProposalPatchError('La propuesta repite un ID de bloque.');
        const action = actionsById.get(operation.node.type);
        if (!action) throw new ProposalPatchError('La propuesta usa una acción desconocida.');
        const target = targetSequence(tree, operation.location);
        if (operation.location.index > target.length) throw new ProposalPatchError('La posición de inserción no existe.');
        const node: CanonicalBotNode = {
          id: operation.node.id,
          type: operation.node.type,
          params: normalizeParams(operation.node.type, operation.node.params),
          ...(action.slots.length ? { slots: Object.fromEntries(action.slots.map((slot) => [slot, []])) } : {}),
        };
        tree.nodes.push(node);
        target.splice(operation.location.index, 0, node.id);
        continue;
      }
      if (operation.op === 'removeNode') {
        requireNode(tree, operation.nodeId);
        const source = sourceSequence(tree, operation.nodeId);
        source.splice(source.indexOf(operation.nodeId), 1);
        const removed = descendantIds(tree, operation.nodeId);
        tree.nodes = tree.nodes.filter(({ id }) => !removed.has(id));
        continue;
      }
      if (operation.op === 'moveNode') {
        requireNode(tree, operation.nodeId);
        if (operation.location.parentId !== null && descendantIds(tree, operation.nodeId).has(operation.location.parentId)) {
          throw new ProposalPatchError('Un bloque no puede moverse dentro de sí mismo.');
        }
        const source = sourceSequence(tree, operation.nodeId);
        source.splice(source.indexOf(operation.nodeId), 1);
        const target = targetSequence(tree, operation.location);
        if (operation.location.index > target.length) throw new ProposalPatchError('La posición de destino no existe.');
        target.splice(operation.location.index, 0, operation.nodeId);
        continue;
      }
      if (operation.op === 'updateNodeParams') {
        const node = requireNode(tree, operation.nodeId);
        node.params = normalizeParams(node.type, operation.params);
        continue;
      }
      const node = requireNode(tree, operation.nodeId);
      const replacement = actionsById.get(operation.actionType);
      if (!replacement) throw new ProposalPatchError('La propuesta usa una acción desconocida.');
      const currentSlots = Object.keys(node.slots ?? {}).sort();
      const replacementSlots = [...replacement.slots].sort();
      if (JSON.stringify(currentSlots) !== JSON.stringify(replacementSlots)) {
        throw new ProposalPatchError('El reemplazo no conserva la estructura anidada.');
      }
      node.type = operation.actionType;
      node.params = normalizeParams(operation.actionType, operation.params);
    }

    const parsed = parseCanonicalBot(draft);
    if (parsed.schemaVersion !== 2) throw new ProposalPatchError();
    return parsed as CanonicalTreeBot;
  } catch (error) {
    if (error instanceof ProposalPatchError) throw error;
    throw new ProposalPatchError();
  }
}

export function compactProposalParameterOperation(
  operations: ProposalOperation[],
  nodeId: string,
  params: Record<string, JsonValue>,
): ProposalOperation[] {
  const index = compactableParameterOperationIndex(operations, nodeId);
  const nextParams = structuredClone(params);
  if (index < 0) {
    if (operations.length >= 200) {
      throw new ProposalPatchError('La propuesta alcanzó el límite de 200 operaciones para editar este bloque.');
    }
    return [...operations, { op: 'updateNodeParams', nodeId, params: nextParams }];
  }
  return operations.map((operation, operationIndex) => {
    if (operationIndex !== index) return operation;
    if (operation.op === 'addNode') {
      return { ...operation, node: { ...operation.node, params: nextParams } };
    }
    return { ...operation, params: nextParams };
  });
}

export function canEditProposalNodeParameters(
  operations: ProposalOperation[],
  nodeId: string,
): boolean {
  return operations.length < 200 || compactableParameterOperationIndex(operations, nodeId) >= 0;
}

function compactableParameterOperationIndex(operations: ProposalOperation[], nodeId: string): number {
  for (let candidate = operations.length - 1; candidate >= 0; candidate -= 1) {
    const operation = operations[candidate];
    if (
      (operation.op === 'addNode' && operation.node.id === nodeId)
      || ((operation.op === 'replaceNode' || operation.op === 'updateNodeParams') && operation.nodeId === nodeId)
    ) {
      return candidate;
    }
  }
  return -1;
}

function canonicalValue(value: unknown): string {
  if (value === null) return 'n;';
  if (typeof value === 'boolean') return value ? 'b1;' : 'b0;';
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) throw new ProposalPatchError('El bot contiene un número no finito.');
    if (Number.isInteger(value) && !Number.isSafeInteger(value)) {
      throw new ProposalPatchError('El bot contiene un entero no seguro.');
    }
    const bytes = new Uint8Array(8);
    new DataView(bytes.buffer).setFloat64(0, Object.is(value, -0) ? 0 : value, false);
    return `d${Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')};`;
  }
  if (typeof value === 'string') {
    return `s${Array.from(new TextEncoder().encode(value), (byte) => byte.toString(16).padStart(2, '0')).join('')};`;
  }
  if (Array.isArray(value)) return `a${value.length}:${value.map(canonicalValue).join('')}`;
  if (value && typeof value === 'object') {
    const entries = Object.entries(value)
      .filter(([, child]) => child !== undefined)
      .sort(([left], [right]) => compareCodePoints(left, right));
    return `o${entries.length}:${entries.map(([key, child]) => canonicalValue(key) + canonicalValue(child)).join('')}`;
  }
  throw new ProposalPatchError('El bot contiene un valor no JSON.');
}

function compareCodePoints(left: string, right: string): number {
  const leftPoints = Array.from(left, (character) => character.codePointAt(0)!);
  const rightPoints = Array.from(right, (character) => character.codePointAt(0)!);
  const length = Math.min(leftPoints.length, rightPoints.length);
  for (let index = 0; index < length; index += 1) {
    if (leftPoints[index] !== rightPoints[index]) return leftPoints[index] - rightPoints[index];
  }
  return leftPoints.length - rightPoints.length;
}

function normalizeParams(actionType: string, input: Record<string, JsonValue>): Record<string, JsonValue> {
  const action = actionsById.get(actionType);
  if (!action) throw new ProposalPatchError('La propuesta usa una acción desconocida.');
  const fields = new Map(action.fields.map((field) => [field.name, field]));
  if (Object.keys(input).some((name) => !fields.has(name))) throw new ProposalPatchError('La propuesta contiene un parámetro desconocido.');
  const params = { ...structuredClone(action.defaults), ...structuredClone(input) } as Record<string, JsonValue>;
  for (const field of action.fields) {
    const value = params[field.name];
    if (isPendingParameter(value) && allowsPendingParameter(field)) continue;
    if (value === undefined) {
      if (field.required) throw new ProposalPatchError('La propuesta omite un parámetro obligatorio.');
      continue;
    }
    const containsVariableToken = typeof value === 'string' && value.includes('{{');
    if (!containsVariableToken && !isValidFieldValue(field, value)) {
      throw new ProposalPatchError('La propuesta contiene un parámetro inválido.');
    }
  }
  return params;
}

function requireNode(tree: MutableTree, nodeId: string): CanonicalBotNode {
  const node = tree.nodes.find(({ id }) => id === nodeId);
  if (!node) throw new ProposalPatchError('La propuesta referencia un bloque inexistente.');
  return node;
}

function targetSequence(tree: MutableTree, location: ProposalLocation): string[] {
  if (location.parentId === null) {
    if (location.slot !== 'root') throw new ProposalPatchError('La ubicación raíz es inválida.');
    return tree.root;
  }
  const parent = requireNode(tree, location.parentId);
  const action = actionsById.get(parent.type);
  if (!action?.slots.includes(location.slot) || !parent.slots?.[location.slot]) {
    throw new ProposalPatchError('La propuesta referencia un contenedor inválido.');
  }
  return parent.slots[location.slot];
}

function sourceSequence(tree: MutableTree, nodeId: string): string[] {
  const matches: string[][] = [];
  if (tree.root.includes(nodeId)) matches.push(tree.root);
  for (const node of tree.nodes) {
    for (const children of Object.values(node.slots ?? {})) if (children.includes(nodeId)) matches.push(children);
  }
  if (matches.length !== 1) throw new ProposalPatchError('La ubicación actual del bloque es inválida.');
  return matches[0];
}

function descendantIds(tree: MutableTree, nodeId: string): Set<string> {
  const nodes = new Map(tree.nodes.map((node) => [node.id, node]));
  const found = new Set<string>();
  function visit(id: string) {
    if (found.has(id)) return;
    found.add(id);
    Object.values(nodes.get(id)?.slots ?? {}).flat().forEach(visit);
  }
  visit(nodeId);
  return found;
}
