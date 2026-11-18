import { actionsById, getActionDefaults, normalizeParameterValue } from '@/bot/registry';
import type { BotEditorState, TreeLocation } from '@/bot/model';

export type BotEditorAction =
  | { type: 'metadataChanged'; name?: string; description?: string }
  | { type: 'nodeAdded'; actionType: string; index?: number; nodeId?: string; location?: TreeLocation }
  | { type: 'nodeReordered'; nodeId: string; toIndex: number }
  | { type: 'nodeMoved'; nodeId: string; to: TreeLocation; toIndex: number }
  | { type: 'nodeSelected'; nodeId: string | null }
  | { type: 'nodeCollapsed'; nodeId: string }
  | { type: 'parameterChanged'; nodeId: string; fieldName: string; value: unknown }
  | { type: 'coordinatesChanged'; nodeId: string; x: number; y: number }
  | { type: 'nodeDeleted'; nodeId: string };

function uniqueId(): string { return `node-${crypto.randomUUID()}`; }
export function sequenceAt(state: BotEditorState, location: TreeLocation): string[] | null {
  if (location.parentId === null) return location.slot === 'root' ? state.root : null;
  return state.nodes.find((node) => node.id === location.parentId)?.slots[location.slot] ?? null;
}
export function nodeLocation(state: BotEditorState, nodeId: string): TreeLocation | null {
  if (state.root.includes(nodeId)) return { parentId: null, slot: 'root' };
  for (const node of state.nodes) for (const [slot, ids] of Object.entries(node.slots)) if (ids.includes(nodeId)) return { parentId: node.id, slot };
  return null;
}
export function descendantIds(state: BotEditorState, nodeId: string): Set<string> {
  const found = new Set<string>();
  function visit(id: string) {
    if (found.has(id)) return;
    found.add(id);
    const node = state.nodes.find((candidate) => candidate.id === id);
    if (node) Object.values(node.slots).flat().forEach(visit);
  }
  visit(nodeId); return found;
}
function replaceSequence(state: BotEditorState, location: TreeLocation, ids: string[]): BotEditorState {
  if (location.parentId === null) return { ...state, root: ids };
  return { ...state, nodes: state.nodes.map((node) => node.id === location.parentId ? { ...node, slots: { ...node.slots, [location.slot]: ids } } : node) };
}

export function botEditorReducer(state: BotEditorState, action: BotEditorAction): BotEditorState {
  if (state.representation === 'readOnlyGraph' && action.type !== 'nodeSelected') return state;
  switch (action.type) {
    case 'metadataChanged': {
      if ((action.name === undefined || action.name === state.metadata.name) && (action.description === undefined || action.description === state.metadata.description)) return state;
      return { ...state, metadata: { ...state.metadata, ...(action.name === undefined ? {} : { name: action.name }), ...(action.description === undefined ? {} : { description: action.description }) } };
    }
    case 'nodeAdded': {
      const definition = actionsById.get(action.actionType);
      if (!definition) return state;
      const id = action.nodeId ?? uniqueId();
      if (state.nodes.some((node) => node.id === id)) return state;
      const location = action.location ?? { parentId: null, slot: 'root' };
      const target = sequenceAt(state, location);
      if (!target) return state;
      const index = Math.max(0, Math.min(action.index ?? target.length, target.length));
      const next = replaceSequence(state, location, [...target.slice(0, index), id, ...target.slice(index)]);
      return { ...next, nodes: [...next.nodes, { id, data: { actionType: action.actionType, params: getActionDefaults(action.actionType), readOnly: false }, slots: Object.fromEntries(definition.slots.map((slot) => [slot, []])) }], selectedNodeId: id };
    }
    case 'nodeReordered':
      return botEditorReducer(state, { type: 'nodeMoved', nodeId: action.nodeId, to: nodeLocation(state, action.nodeId) ?? { parentId: null, slot: 'root' }, toIndex: action.toIndex });
    case 'nodeMoved': {
      const from = nodeLocation(state, action.nodeId);
      const source = from && sequenceAt(state, from);
      const target = sequenceAt(state, action.to);
      if (!from || !source || !target || action.to.parentId && descendantIds(state, action.nodeId).has(action.to.parentId)) return state;
      const fromIndex = source.indexOf(action.nodeId);
      if (fromIndex < 0) return state;
      let next = replaceSequence(state, from, source.filter((id) => id !== action.nodeId));
      const freshTarget = sequenceAt(next, action.to);
      if (!freshTarget) return state;
      const index = Math.max(0, Math.min(action.toIndex, freshTarget.length));
      if (from.parentId === action.to.parentId && from.slot === action.to.slot && fromIndex === index) return state;
      next = replaceSequence(next, action.to, [...freshTarget.slice(0, index), action.nodeId, ...freshTarget.slice(index)]);
      return next;
    }
    case 'nodeSelected':
      if (action.nodeId === state.selectedNodeId) return state;
      return !action.nodeId || state.nodes.some((node) => node.id === action.nodeId) ? { ...state, selectedNodeId: action.nodeId || null } : state;
    case 'nodeCollapsed':
      if (!state.nodes.some((node) => node.id === action.nodeId && Object.keys(node.slots).length)) return state;
      return { ...state, collapsedNodeIds: state.collapsedNodeIds.includes(action.nodeId) ? state.collapsedNodeIds.filter((id) => id !== action.nodeId) : [...state.collapsedNodeIds, action.nodeId] };
    case 'parameterChanged': {
      const node = state.nodes.find((candidate) => candidate.id === action.nodeId);
      const field = node && actionsById.get(node.data.actionType)?.fields.find((item) => item.name === action.fieldName);
      if (!node || node.data.readOnly || !field) return state;
      const value = normalizeParameterValue(field, action.value);
      if (value === node.data.params[action.fieldName] || (value === undefined && !(action.fieldName in node.data.params))) return state;
      const params = { ...node.data.params }; if (value === undefined) delete params[action.fieldName]; else params[action.fieldName] = value;
      return { ...state, nodes: state.nodes.map((candidate) => candidate.id === node.id ? { ...candidate, data: { ...candidate.data, params } } : candidate) };
    }
    case 'coordinatesChanged': {
      const node = state.nodes.find((candidate) => candidate.id === action.nodeId);
      const definition = node && actionsById.get(node.data.actionType);
      if (!node || node.data.readOnly || !definition || !['mouse.move', 'mouse.click', 'mouse.rightClick', 'mouse.doubleClick'].includes(definition.id)) return state;
      if (node.data.params.x === action.x && node.data.params.y === action.y) return state;
      return { ...state, nodes: state.nodes.map((candidate) => candidate.id === node.id ? { ...candidate, data: { ...candidate.data, params: { ...candidate.data.params, x: action.x, y: action.y } } } : candidate) };
    }
    case 'nodeDeleted': {
      const node = state.nodes.find((candidate) => candidate.id === action.nodeId);
      if (!node || node.data.readOnly) return state;
      const removed = descendantIds(state, node.id);
      const location = nodeLocation(state, node.id);
      if (!location) return state;
      const next = replaceSequence(state, location, sequenceAt(state, location)!.filter((id) => id !== node.id));
      return { ...next, nodes: next.nodes.filter((candidate) => !removed.has(candidate.id)), selectedNodeId: state.selectedNodeId && removed.has(state.selectedNodeId) ? null : state.selectedNodeId, collapsedNodeIds: state.collapsedNodeIds.filter((id) => !removed.has(id)) };
    }
  }
}
