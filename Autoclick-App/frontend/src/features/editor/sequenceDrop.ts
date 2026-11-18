import type { BotEditorState, TreeLocation } from '@/bot/model';
import { nodeLocation, sequenceAt } from '@/bot/state';

export type SequenceDrop =
  | { kind: 'add'; actionType: string; toIndex: number; location: TreeLocation }
  | { kind: 'reorder'; nodeId: string; toIndex: number; location: TreeLocation };
export type EditorDndItem = { kind: 'catalog'; actionType: string } | { kind: 'sequence'; nodeId: string };
export function catalogDndId(actionType: string): string { return `catalog:${actionType}`; }
export function sequenceDndId(nodeId: string): string { return `sequence:${nodeId}`; }
export function insertDndId(location: TreeLocation, index: number): string {
  return location.parentId === null ? `insert-${index}` : `insert:${encodeURIComponent(location.parentId)}:${encodeURIComponent(location.slot)}:${index}`;
}
export function parseEditorDndId(id: string): EditorDndItem | null {
  if (id.startsWith('catalog:')) return { kind: 'catalog', actionType: id.slice(8) };
  if (id.startsWith('sequence:')) return { kind: 'sequence', nodeId: id.slice(9) };
  return null;
}
function insertion(id: string): { location: TreeLocation; index: number } | null {
  if (id.startsWith('insert-')) return { location: { parentId: null, slot: 'root' }, index: Number(id.slice(7)) };
  const match = /^insert:([^:]+):([^:]+):(\d+)$/.exec(id);
  return match ? { location: { parentId: decodeURIComponent(match[1]), slot: decodeURIComponent(match[2]) }, index: Number(match[3]) } : null;
}
export function resolveSequenceDrop(state: BotEditorState, activeId: string, overId: string): SequenceDrop | null {
  const zone = insertion(overId);
  const overItem = zone ? null : parseEditorDndId(overId);
  const location = zone?.location ?? (overItem?.kind === 'sequence' ? nodeLocation(state, overItem.nodeId) : null);
  const target = location && sequenceAt(state, location);
  const rawIndex = zone?.index ?? (overItem?.kind === 'sequence' && target ? target.indexOf(overItem.nodeId) : -1);
  if (!location || !target || !Number.isInteger(rawIndex) || rawIndex < 0 || rawIndex > target.length) return null;
  const active = parseEditorDndId(activeId);
  if (!active) return null;
  if (active.kind === 'catalog') return { kind: 'add', actionType: active.actionType, location, toIndex: Math.min(rawIndex, target.length) };
  const from = nodeLocation(state, active.nodeId);
  const source = from && sequenceAt(state, from);
  if (!from || !source) return null;
  const fromIndex = source.indexOf(active.nodeId);
  const same = from.parentId === location.parentId && from.slot === location.slot;
  const adjusted = zone && same && rawIndex > fromIndex ? rawIndex - 1 : rawIndex;
  return { kind: 'reorder', nodeId: active.nodeId, location, toIndex: Math.max(0, Math.min(adjusted, same ? target.length - 1 : target.length)) };
}
