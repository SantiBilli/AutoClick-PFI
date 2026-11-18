import type { Announcements } from '@dnd-kit/core';
import { actionsById } from '@/bot/registry';
import type { BotEditorState } from '@/bot/model';
import { nodeLocation, sequenceAt } from '@/bot/state';
import { parseEditorDndId, resolveSequenceDrop } from '@/features/editor/sequenceDrop';

function blockName(id: string, state: BotEditorState): string {
  const item = parseEditorDndId(id);
  const actionType = item?.kind === 'catalog' ? item.actionType : item?.kind === 'sequence' ? state.nodes.find((node) => node.id === item.nodeId)?.data.actionType : undefined;
  return actionType ? actionsById.get(actionType)?.title ?? actionType : id;
}
function currentPosition(id: string, state: BotEditorState): number | null {
  const item = parseEditorDndId(id);
  if (item?.kind !== 'sequence') return null;
  const location = nodeLocation(state, item.nodeId);
  const index = location ? sequenceAt(state, location)?.indexOf(item.nodeId) ?? -1 : -1;
  return index < 0 ? null : index + 1;
}
function destination(activeId: string, overId: string, state: BotEditorState): number | null { const drop = resolveSequenceDrop(state, activeId, overId); return drop ? drop.toIndex + 1 : null; }
export function createSequenceAnnouncements(state: BotEditorState): Announcements {
  return {
    onDragStart: ({ active }) => { const id = active.id.toString(); const name = blockName(id, state); return parseEditorDndId(id)?.kind === 'catalog' ? `Bloque ${name} levantado del catálogo.` : `Bloque ${name} levantado desde la posición ${currentPosition(id, state)}.`; },
    onDragOver: ({ active, over }) => { if (!over) return `Bloque ${blockName(active.id.toString(), state)} fuera de la secuencia.`; const position = destination(active.id.toString(), over.id.toString(), state); return position === null ? `Bloque ${blockName(active.id.toString(), state)} fuera de la secuencia.` : `Bloque ${blockName(active.id.toString(), state)} sobre la posición ${position}.`; },
    onDragEnd: ({ active, over }) => { const name = blockName(active.id.toString(), state); if (!over) return `Movimiento de ${name} cancelado.`; const position = destination(active.id.toString(), over.id.toString(), state); return position === null ? `Movimiento de ${name} cancelado.` : `Bloque ${name} colocado en la posición ${position}.`; },
    onDragCancel: ({ active }) => `Movimiento de ${blockName(active.id.toString(), state)} cancelado.`,
  };
}
