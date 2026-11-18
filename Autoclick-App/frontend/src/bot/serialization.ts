import { actionsById } from '@/bot/registry';
import { canonicalBotSchema, deriveLinearNodeOrder, type CanonicalBot, type CanonicalBotNode } from '@/bot/schema';
import type { BotEditorNode, BotEditorState } from '@/bot/model';

export { deriveLinearNodeOrder };
export type EditorLoadState = { editor: BotEditorState; saved: CanonicalBot };

export function createEditorLoadState(botInput: unknown): EditorLoadState {
  const bot = canonicalBotSchema.parse(botInput);
  const nodes: BotEditorNode[] = bot.flow.nodes.map((node) => ({
    id: node.id,
    data: { actionType: node.type, params: structuredClone(node.params), readOnly: !actionsById.has(node.type) },
    slots: structuredClone((node as typeof node & { slots?: Record<string, string[]> }).slots ?? {}),
  }));
  const legacy = bot.schemaVersion === 1;
  const editor: BotEditorState = {
    metadata: { schemaVersion: bot.schemaVersion, id: bot.id, name: bot.name, description: bot.description, ...(bot.icon === undefined ? {} : { icon: bot.icon }) },
    nodes,
    root: legacy ? nodes.map((node) => node.id) : [...bot.flow.root],
    selectedNodeId: null,
    collapsedNodeIds: [],
    representation: legacy ? 'readOnlyGraph' : 'tree',
    legacyEdges: legacy ? structuredClone(bot.flow.edges) : [],
  };
  return { editor, saved: structuredClone(bot) };
}

export function createEditorState(botInput: unknown): BotEditorState { return createEditorLoadState(botInput).editor; }
export function serializeEditorState(state: BotEditorState): CanonicalBot {
  if (state.representation === 'readOnlyGraph') throw new Error('Legacy non-linear graphs are read-only');
  return canonicalBotSchema.parse({
    ...state.metadata,
    flow: { root: [...state.root], nodes: state.nodes.map((node): CanonicalBotNode => ({ id: node.id, type: node.data.actionType, params: structuredClone(node.data.params), ...(Object.keys(node.slots).length ? { slots: structuredClone(node.slots) } : {}) })) },
  });
}
function stableValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stableValue);
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, child]) => [key, stableValue(child)]));
  return value;
}
export function canonicalString(bot: CanonicalBot): string { return JSON.stringify(stableValue(canonicalBotSchema.parse(bot))); }
export type EditorStateAssessment = { serializable: true; dirty: boolean; draft: CanonicalBot } | { serializable: false; dirty: boolean; draft: null };
export function assessEditorState(state: BotEditorState, saved: CanonicalBot): EditorStateAssessment {
  try { const draft = serializeEditorState(state); return { serializable: true, dirty: canonicalString(draft) !== canonicalString(saved), draft }; }
  catch { return { serializable: false, dirty: state.representation !== 'readOnlyGraph', draft: null }; }
}
export function canSerializeEditorState(state: BotEditorState): boolean { try { serializeEditorState(state); return true; } catch { return false; } }
export function isEditorDirty(state: BotEditorState, saved: CanonicalBot): boolean { return assessEditorState(state, saved).dirty; }
