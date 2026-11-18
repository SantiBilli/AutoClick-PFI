import { z } from 'zod';
import { botAiSchema } from '@/ai/schema';
import rawRegistry from '@action-registry';

const NON_EMPTY_ID = z.string().trim().min(1);
const NODE_TYPE = z.string().trim().regex(/^[A-Za-z][A-Za-z0-9_-]*(?:\.[A-Za-z][A-Za-z0-9_-]*)+$/);
const ICON = z.string().trim().min(1).max(64).regex(/^[A-Za-z0-9][A-Za-z0-9_-]*$/);
const UUID = z.string().transform((value, context) => {
  let hex = value;
  if (hex.startsWith('urn:uuid:')) hex = hex.slice(9);
  if (hex.startsWith('{') && hex.endsWith('}')) hex = hex.slice(1, -1);
  hex = hex.replaceAll('-', '');
  if (!/^[0-9A-Fa-f]{32}$/.test(hex)) {
    context.addIssue({ code: 'custom', message: 'Invalid UUID' });
    return z.NEVER;
  }
  const canonical = hex.toLowerCase();
  return `${canonical.slice(0, 8)}-${canonical.slice(8, 12)}-${canonical.slice(12, 16)}-${canonical.slice(16, 20)}-${canonical.slice(20)}`;
});

export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };
export function containsIsolatedUtf16Surrogate(value: string): boolean {
  for (let index = 0; index < value.length; index += 1) {
    const unit = value.charCodeAt(index);
    if (unit >= 0xd800 && unit <= 0xdbff) {
      const next = value.charCodeAt(index + 1);
      if (!(next >= 0xdc00 && next <= 0xdfff)) return true;
      index += 1;
    } else if (unit >= 0xdc00 && unit <= 0xdfff) {
      return true;
    }
  }
  return false;
}

export function addUnicodeScalarIssues(value: unknown, context: z.RefinementCtx, path: PropertyKey[] = []): void {
  if (typeof value === 'string') {
    if (containsIsolatedUtf16Surrogate(value)) {
      context.addIssue({ code: 'custom', path, message: 'Strings must contain only Unicode scalar values' });
    }
    return;
  }
  if (Array.isArray(value)) {
    value.forEach((child, index) => addUnicodeScalarIssues(child, context, [...path, index]));
    return;
  }
  if (value && typeof value === 'object') {
    Object.entries(value).forEach(([key, child]) => {
      if (containsIsolatedUtf16Surrogate(key)) {
        context.addIssue({ code: 'custom', path: [...path, key], message: 'Object keys must contain only Unicode scalar values' });
      }
      addUnicodeScalarIssues(child, context, [...path, key]);
    });
  }
}
export const jsonNumberSchema = z.number().finite().refine((value) => !Number.isInteger(value) || Number.isSafeInteger(value), 'JSON integers must be safe integers');
const jsonValueSchema: z.ZodType<JsonValue> = z.lazy(() => z.union([
  z.string(), jsonNumberSchema, z.boolean(), z.null(), z.array(jsonValueSchema), z.record(z.string(), jsonValueSchema),
]));

const DECLARED_SLOTS: Readonly<Record<string, readonly string[]>> = Object.fromEntries(
  rawRegistry.actions.filter((action) => 'slots' in action).map((action) => [action.id, action.slots ?? []]),
);

export const canonicalBotNodeSchema = z.object({
  id: NON_EMPTY_ID,
  type: NODE_TYPE,
  params: z.record(z.string(), jsonValueSchema),
  slots: z.record(NON_EMPTY_ID, z.array(NON_EMPTY_ID)).optional(),
}).strict();

export const canonicalBotEdgeSchema = z.object({ id: NON_EMPTY_ID, source: NON_EMPTY_ID, target: NON_EMPTY_ID }).strict();

const flowV2Schema = z.object({
  root: z.array(NON_EMPTY_ID),
  nodes: z.array(canonicalBotNodeSchema).max(1_000),
}).strict().superRefine(({ root, nodes }, context) => {
  const ids = new Set<string>();
  nodes.forEach((node, index) => {
    if (ids.has(node.id)) context.addIssue({ code: 'custom', path: ['nodes', index, 'id'], message: 'Node IDs must be unique' });
    ids.add(node.id);
  });
  const placements = [...root];
  nodes.forEach((node, index) => {
    const declared = DECLARED_SLOTS[node.type] ?? [];
    const actual = Object.keys(node.slots ?? {});
    if (actual.length !== declared.length || actual.some((slot) => !declared.includes(slot))) {
      context.addIssue({ code: 'custom', path: ['nodes', index, 'slots'], message: 'Slots must match the action declaration' });
    }
    for (const children of Object.values(node.slots ?? {})) placements.push(...children);
  });
  if (placements.some((id) => !ids.has(id))) context.addIssue({ code: 'custom', message: 'Tree references must exist' });
  if (new Set(placements).size !== placements.length) context.addIssue({ code: 'custom', message: 'Every node must be placed once' });
  if (placements.length !== ids.size || placements.some((id) => !ids.has(id))) context.addIssue({ code: 'custom', message: 'Tree cannot contain orphans' });
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const visiting = new Set<string>();
  const visited = new Set<string>();
  function visit(id: string) {
    if (visiting.has(id)) {
      context.addIssue({ code: 'custom', message: 'Tree cannot contain cycles' });
      return;
    }
    if (visited.has(id) || !byId.has(id)) return;
    visiting.add(id);
    for (const children of Object.values(byId.get(id)?.slots ?? {})) children.forEach(visit);
    visiting.delete(id);
    visited.add(id);
  }
  root.forEach(visit);
  // A component made exclusively of child links has no root. Traverse every
  // node so that it cannot hide a cycle while still placing every ID once.
  nodes.forEach((node) => visit(node.id));
});

const flowV1Schema = z.object({ nodes: z.array(z.object({ id: NON_EMPTY_ID, type: NODE_TYPE, params: z.record(z.string(), jsonValueSchema) }).strict()).max(1_000), edges: z.array(canonicalBotEdgeSchema).max(2_000) }).strict().superRefine(({ nodes, edges }, context) => {
  const nodeIds = nodes.map((node) => node.id);
  const edgeIds = edges.map((edge) => edge.id);
  const known = new Set(nodeIds);
  if (known.size !== nodeIds.length) context.addIssue({ code: 'custom', message: 'Node IDs must be unique' });
  if (new Set(edgeIds).size !== edgeIds.length) context.addIssue({ code: 'custom', message: 'Edge IDs must be unique' });
  edges.forEach((edge, index) => {
    if (edge.source === edge.target) context.addIssue({ code: 'custom', path: ['edges', index], message: 'Edges cannot be self-links' });
    if (!known.has(edge.source) || !known.has(edge.target)) context.addIssue({ code: 'custom', path: ['edges', index], message: 'Edges must reference existing nodes' });
  });
});
const metadata = { id: UUID, name: z.string().trim().min(1).max(120), description: z.string().max(500).optional().default(''), icon: ICON.nullish().transform((icon) => icon ?? undefined), ai: botAiSchema.optional() };
const v1Schema = z.object({ schemaVersion: z.literal(1), ...metadata, flow: flowV1Schema }).strict();
const v2Schema = z.object({ schemaVersion: z.literal(2), ...metadata, flow: flowV2Schema }).strict();

export type CanonicalBotEdge = z.output<typeof canonicalBotEdgeSchema>;
export type LinearPathResult = { ok: true; nodeIds: string[] } | { ok: false; reason: 'branch' | 'cycle' | 'disconnected' | 'ambiguous' };
export function deriveLinearNodeOrder(nodes: Array<{ id: string }>, edges: CanonicalBotEdge[]): LinearPathResult {
  if (new Set(nodes.map((node) => node.id)).size !== nodes.length || new Set(edges.map((edge) => edge.id)).size !== edges.length) return { ok: false, reason: 'ambiguous' };
  if (nodes.length <= 1) return edges.length === 0 ? { ok: true, nodeIds: nodes.map((node) => node.id) } : { ok: false, reason: 'ambiguous' };
  if (edges.length !== nodes.length - 1) return { ok: false, reason: 'disconnected' };
  const incoming = new Map(nodes.map((node) => [node.id, 0]));
  const outgoing = new Map(nodes.map((node) => [node.id, [] as string[]]));
  for (const edge of edges) {
    if (!incoming.has(edge.source) || !incoming.has(edge.target) || edge.source === edge.target) return { ok: false, reason: 'ambiguous' };
    incoming.set(edge.target, incoming.get(edge.target)! + 1);
    outgoing.get(edge.source)!.push(edge.target);
  }
  if ([...incoming.values()].some((count) => count > 1) || [...outgoing.values()].some((targets) => targets.length > 1)) return { ok: false, reason: 'branch' };
  const starts = nodes.filter((node) => incoming.get(node.id) === 0);
  if (starts.length !== 1) return { ok: false, reason: starts.length === 0 ? 'cycle' : 'ambiguous' };
  const ordered: string[] = [];
  const seen = new Set<string>();
  let current: string | undefined = starts[0].id;
  while (current) {
    if (seen.has(current)) return { ok: false, reason: 'cycle' };
    seen.add(current); ordered.push(current); current = outgoing.get(current)?.[0];
  }
  return ordered.length === nodes.length ? { ok: true, nodeIds: ordered } : { ok: false, reason: 'disconnected' };
}

export const canonicalBotSchema = z.union([v2Schema, v1Schema]).superRefine((bot, context) => {
  addUnicodeScalarIssues(bot, context);
}).transform((bot, context) => {
  if (bot.schemaVersion === 2) return bot;
  const path = deriveLinearNodeOrder(bot.flow.nodes, bot.flow.edges);
  if (!path.ok) return bot;
  return { ...bot, schemaVersion: 2 as const, flow: { root: path.nodeIds, nodes: bot.flow.nodes } };
});

export type CanonicalBot = z.output<typeof canonicalBotSchema>;
export type CanonicalBotInput = z.input<typeof canonicalBotSchema>;
export type CanonicalBotNode = z.output<typeof canonicalBotNodeSchema>;
export type CanonicalTreeBot = Omit<Extract<CanonicalBot, { schemaVersion: 2 }>, 'flow'> & {
  schemaVersion: 2;
  flow: { root: string[]; nodes: CanonicalBotNode[] };
};
export function parseCanonicalBot(input: unknown): CanonicalBot { return canonicalBotSchema.parse(input); }
