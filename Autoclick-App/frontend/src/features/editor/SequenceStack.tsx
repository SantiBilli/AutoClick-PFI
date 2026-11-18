import { CSS } from '@dnd-kit/utilities';
import { SortableContext, verticalListSortingStrategy, useSortable } from '@dnd-kit/sortable';
import { useDroppable } from '@dnd-kit/core';
import { motion } from 'framer-motion';
import { ArrowDown, ArrowUp, Check, ChevronDown, ChevronRight, CircleAlert, CircleStop, GripVertical, HelpCircle, LoaderCircle, Plus, Trash2, TriangleAlert } from 'lucide-react';
import { actionsById } from '@/bot/registry';
import { isPendingParameter } from '@/bot/pending';
import type { BotEditorNode, BotEditorState, TreeLocation } from '@/bot/model';
import type { ValidationIssue } from '@/bot/validation';
import { actionIcons } from '@/features/editor/actionIcons';
import { insertDndId, sequenceDndId } from '@/features/editor/sequenceDrop';
import type { BlockExecutionStatus } from '@/execution/state';
import type { BotDiffStatus } from '@/ai/proposalDiff';

const executionStatusPresentation = {
  running: { label: 'En ejecución', className: 'border-blue-500 ring-2 ring-blue-400/40', icon: LoaderCircle },
  succeeded: { label: 'Completado', className: 'border-emerald-500', icon: Check },
  warning: { label: 'Completado con advertencia', className: 'border-amber-500', icon: TriangleAlert },
  stopped: { label: 'Detenido', className: 'border-slate-500', icon: CircleStop },
  failed: { label: 'Falló', className: 'border-red-500 ring-2 ring-red-400/30', icon: CircleAlert },
  cancelled: { label: 'Cancelado', className: 'border-slate-500', icon: CircleStop },
} satisfies Record<BlockExecutionStatus, { label: string; className: string; icon: typeof Check }>;

const standardBlockStyle = 'border-blue-100 bg-white text-text';
const comparisonPresentation = {
  added: { label: 'Agregado', className: 'border-emerald-500 bg-emerald-50 text-emerald-950', dot: 'bg-emerald-500' },
  removed: { label: 'Eliminado', className: 'border-red-500 bg-red-50 text-red-950', dot: 'bg-red-500' },
  modified: { label: 'Modificado', className: 'border-amber-500 bg-amber-50 text-amber-950', dot: 'bg-amber-500' },
  unchanged: { label: 'Sin cambios', className: 'border-blue-100 bg-white text-text', dot: 'bg-blue-500' },
} satisfies Record<BotDiffStatus, { label: string; className: string; dot: string }>;

const SLOT_LABELS: Record<string, string> = {
  body: 'Cuerpo', then: 'Entonces', else: 'Si no', try: 'Intentar', catch: 'Recuperar',
};

export function DragBlockPreview({ actionType }: { actionType: string }) {
  const action = actionsById.get(actionType);
  const Icon = action ? actionIcons[action.icon] : HelpCircle;
  return (
    <div
      aria-hidden="true"
      className={`pointer-events-none flex min-w-64 items-center gap-3 rounded-panel border-2 px-3 py-2.5 opacity-[0.85] shadow-overlay ${action ? standardBlockStyle : 'border-slate-300 bg-slate-100 text-slate-800'}`}
      data-testid="drag-block-preview">
      <span className="grid size-8 shrink-0 place-items-center rounded-control bg-white/80">
        <Icon aria-hidden="true" size={17} />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-[13px] font-extrabold break-words">
          {action?.title ?? actionType}
        </span>
        <span className="mt-0.5 block text-[10px] font-bold tracking-[0.06em] uppercase opacity-65">
          {action?.categoryName ?? 'Tipo no compatible · solo lectura'}
        </span>
      </span>
    </div>
  );
}

function InsertZone({
  index,
  location,
  disabled,
  empty = false,
}: {
  index: number;
  location: TreeLocation;
  disabled: boolean;
  empty?: boolean;
}) {
  const { isOver, setNodeRef } = useDroppable({ id: insertDndId(location, index), disabled });
  return (
    <div
      aria-label={`Insertar en posición ${index + 1}`}
      className={`relative z-10 ${empty ? 'min-h-60' : 'h-5'}`}
      data-insertion-index={index}
      ref={setNodeRef}>
      {empty ? (
        <div className="grid min-h-60 place-items-center rounded-panel border-2 border-dashed border-border bg-white/70 p-6 text-center text-text-muted transition-colors duration-200 hover:border-blue-200">
          <div>
            <span className="mx-auto mb-3 grid size-11 place-items-center rounded-full bg-blue-50 text-primary">
              <Plus aria-hidden="true" size={22} />
            </span>
            <p className="m-0 font-extrabold text-text">La secuencia está vacía</p>
            <p className="mt-1 mb-0 text-[12px]">
              Agregá un bloque desde el catálogo para comenzar.
            </p>
          </div>
        </div>
      ) : null}
      <div
        className={`pointer-events-none absolute top-1/2 right-5 left-5 flex -translate-y-1/2 items-center gap-2 transition-opacity duration-150 ${isOver ? 'opacity-100' : 'opacity-0'}`}>
        <span className="h-0.5 flex-1 bg-primary" />
        <Plus aria-hidden="true" className="text-primary" size={16} />
        <span className="h-0.5 flex-1 bg-primary" />
      </div>
    </div>
  );
}

function SortableBlock({
  node,
  index,
  count,
  selected,
  invalid,
  executionStatus,
  disabled,
  onSelect,
  onMove,
  onDelete,
  collapsed,
  onToggle,
  comparisonStatus,
}: {
  node: BotEditorNode;
  index: number;
  count: number;
  selected: boolean;
  invalid: boolean;
  executionStatus?: BlockExecutionStatus;
  disabled: boolean;
  onSelect: () => void;
  onMove: (toIndex: number) => void;
  onDelete?: () => void;
  collapsed: boolean;
  onToggle: () => void;
  comparisonStatus?: BotDiffStatus;
}) {
  const action = actionsById.get(node.data.actionType);
  const Icon = action ? actionIcons[action.icon] : HelpCircle;
  const execution = executionStatus ? executionStatusPresentation[executionStatus] : null;
  const comparison = comparisonStatus ? comparisonPresentation[comparisonStatus] : null;
  const hasPendingParameters = Object.values(node.data.params).some(isPendingParameter);
  const hasSemanticBorder = Boolean((comparison && comparisonStatus !== 'unchanged') || selected || execution || invalid || hasPendingParameters);
  const ExecutionIcon = execution?.icon;
  const {
    attributes,
    listeners,
    setActivatorNodeRef,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: sequenceDndId(node.id), disabled });
  function moveAndFocus(toIndex: number) {
    onMove(toIndex);
    window.requestAnimationFrame(() => {
      document
        .getElementById(`sequence-block-${node.id}`)
        ?.querySelector<HTMLElement>('[data-block-select]')
        ?.focus();
    });
  }
  return (
    <motion.article
      aria-current={selected ? 'step' : undefined}
      className={`group relative z-10 flex min-w-0 items-center gap-3 rounded-panel border-2 px-3 py-2.5 shadow-sm transition-[border-color,box-shadow,opacity] duration-200 hover:shadow-card-hover ${hasSemanticBorder ? '' : 'hover:border-blue-300'} ${comparison?.className ?? (action ? standardBlockStyle : 'border-slate-300 bg-slate-100 text-slate-800')} ${selected ? 'ring-2 ring-primary/30 border-primary' : ''} ${execution?.className ?? ''} ${invalid ? '!border-danger' : hasPendingParameters ? '!border-red-300' : ''} ${isDragging ? 'opacity-45' : ''}`}
      data-diff-status={comparisonStatus}
      id={`sequence-block-${node.id}`}
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}>
      <span
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 -z-10 rounded-panel bg-gradient-to-br from-blue-50 via-transparent to-cyan-50/70 opacity-0 transition-opacity duration-300 ease-out group-hover:opacity-100"
      />
      <span
        className="grid size-8 shrink-0 place-items-center rounded-full bg-white/80 text-[12px] font-extrabold shadow-sm"
        aria-label={`Posición ${index + 1} de ${count}`}>
        {index + 1}
      </span>
      <button
        aria-label={`Reordenar ${action?.title ?? node.data.actionType}`}
        className="touch-none cursor-grab border-none rounded-md p-1.5 text-current/60 hover:bg-white/70 disabled:cursor-not-allowed"
        disabled={disabled}
        ref={setActivatorNodeRef}
        type="button"
        {...attributes}
        {...listeners}>
        <GripVertical aria-hidden="true" size={18} />
      </button>
      {Object.keys(node.slots).length ? (
        <button aria-expanded={!collapsed} aria-label={`${collapsed ? 'Expandir' : 'Contraer'} ${action?.title ?? node.data.actionType}`} className="rounded-md border-none p-1.5 hover:bg-white/70" onClick={onToggle} type="button">
          {collapsed ? <ChevronRight aria-hidden="true" size={17} /> : <ChevronDown aria-hidden="true" size={17} />}
        </button>
      ) : null}
      <button
        className="flex min-w-0 flex-1 py-2 border-none items-center gap-3 rounded-md text-left focus-visible:outline-none focus-visible:shadow-focus"
        data-block-select
        onClick={onSelect}
        type="button">
        <span className="grid size-8 shrink-0 place-items-center rounded-control bg-white/80">
          <Icon aria-hidden="true" size={17} />
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-2 text-[13px] font-extrabold break-words">
            {action?.title ?? node.data.actionType}
            {invalid ? (
              <CircleAlert aria-label="Bloque con errores" className="text-danger" size={15} />
            ) : null}
          </span>
          <span className="mt-0.5 block text-[10px] font-bold tracking-[0.06em] uppercase opacity-65">
            {action?.categoryName ?? 'Tipo no compatible · solo lectura'}
          </span>
        </span>
      </button>
      {execution && ExecutionIcon ? (
        <span aria-label={`Estado de ejecución: ${execution.label}`} className="flex shrink-0 items-center gap-1 rounded-full bg-white/80 px-2 py-1 text-[10px] font-extrabold" role="status">
          <ExecutionIcon aria-hidden="true" className={executionStatus === 'running' ? 'motion-safe:animate-spin' : ''} size={13} />
          <span className="hidden sm:inline">{execution.label}</span>
        </span>
      ) : null}
      {comparison ? (
        <span aria-label={`Estado de comparación: ${comparison.label}`} className={`size-2.5 shrink-0 rounded-full ${comparison.dot}`} />
      ) : null}
      {onDelete ? (
        <motion.button
          aria-label={`Eliminar ${action?.title ?? node.data.actionType}`}
          className="shrink-0 rounded-md border-none p-1.5 text-danger/70 opacity-100 transition-[opacity,background-color,color] duration-150 [@media(hover:hover)]:opacity-0 [@media(hover:hover)]:group-hover:opacity-100 hover:bg-red-50 hover:text-danger focus-visible:opacity-100 focus-visible:outline-none focus-visible:shadow-focus disabled:cursor-not-allowed disabled:opacity-0"
          disabled={disabled || node.data.readOnly}
          onClick={onDelete}
          type="button"
          whileHover={disabled || node.data.readOnly ? undefined : { scale: 1.18, rotate: -8 }}
          whileTap={disabled || node.data.readOnly ? undefined : { scale: 0.88, rotate: 0 }}>
          <Trash2 aria-hidden="true" size={15} />
        </motion.button>
      ) : null}
      <span className="flex shrink-0 flex-col gap-1">
        <button
          aria-label={`Subir ${action?.title ?? node.data.actionType}`}
          className="rounded-md border-none p-1 transition-colors duration-150 hover:bg-white/70 disabled:opacity-30"
          disabled={disabled || index === 0}
          onClick={() => moveAndFocus(index - 1)}
          type="button">
          <ArrowUp aria-hidden="true" size={15} />
        </button>
        <button
          aria-label={`Bajar ${action?.title ?? node.data.actionType}`}
          className="rounded-md border-none p-1 transition-colors duration-150 hover:bg-white/70 disabled:opacity-30"
          disabled={disabled || index === count - 1}
          onClick={() => moveAndFocus(index + 1)}
          type="button">
          <ArrowDown aria-hidden="true" size={15} />
        </button>
      </span>
    </motion.article>
  );
}

function SequenceList({ state, ids, location, depth, invalid, executionStatuses, comparisonStatuses, readOnly, onSelect, onMove, onDelete, onToggle }: {
  state: BotEditorState; ids: string[]; location: TreeLocation; depth: number; invalid: Set<string>;
  executionStatuses: Record<string, BlockExecutionStatus>; readOnly: boolean;
  comparisonStatuses?: Record<string, BotDiffStatus>;
  onSelect: (nodeId: string) => void; onMove: (nodeId: string, location: TreeLocation, toIndex: number) => void; onDelete?: (nodeId: string) => void; onToggle: (nodeId: string) => void;
}) {
  const byId = new Map(state.nodes.map((node) => [node.id, node]));
  if (!ids.length) return <InsertZone disabled={readOnly} empty={depth === 0} index={0} location={location} />;
  return <SortableContext items={ids.map(sequenceDndId)} strategy={verticalListSortingStrategy}>
    <div className={`relative ${depth === 0 ? 'before:absolute before:top-5 before:bottom-5 before:left-7 before:w-0.5 before:bg-gradient-to-b before:from-primary/40 before:via-bright-blue/30 before:to-secondary/30 sm:before:left-10' : ''}`}>
      <InsertZone disabled={readOnly} index={0} location={location} />
      {ids.map((id, index) => {
        const node = byId.get(id);
        if (!node) return null;
        const collapsed = state.collapsedNodeIds.includes(node.id);
        return <div key={node.id}>
          <SortableBlock collapsed={collapsed} comparisonStatus={comparisonStatuses?.[node.id]} count={ids.length} disabled={readOnly} executionStatus={executionStatuses[node.id]} index={index} invalid={invalid.has(node.id)} node={node} onDelete={onDelete ? () => onDelete(node.id) : undefined} onMove={(toIndex) => onMove(node.id, location, toIndex)} onSelect={() => onSelect(node.id)} onToggle={() => onToggle(node.id)} selected={node.id === state.selectedNodeId} />
          {!collapsed ? Object.entries(node.slots).map(([slot, children]) => <section aria-label={`${actionsById.get(node.data.actionType)?.title ?? node.data.actionType}: ${slot}`} className="ml-5 mt-2 rounded-panel border border-slate-300 bg-white/55 px-3 sm:ml-10" key={slot}>
            <div className="pt-2 text-[10px] font-extrabold tracking-wider text-text-muted uppercase">{SLOT_LABELS[slot] ?? slot}</div>
            <SequenceList comparisonStatuses={comparisonStatuses} depth={depth + 1} executionStatuses={executionStatuses} ids={children} invalid={invalid} location={{ parentId: node.id, slot }} onDelete={onDelete} onMove={onMove} onSelect={onSelect} onToggle={onToggle} readOnly={readOnly} state={state} />
          </section>) : null}
          <InsertZone disabled={readOnly} index={index + 1} location={location} />
        </div>;
      })}
    </div>
  </SortableContext>;
}

export function SequenceStack({
  state,
  issues,
  executionStatuses = {},
  comparisonStatuses,
  showReadOnlyNotice = true,
  readOnly,
  onSelect,
  onMove,
  onDelete,
  onToggle,
}: {
  state: BotEditorState;
  issues: ValidationIssue[];
  executionStatuses?: Record<string, BlockExecutionStatus>;
  comparisonStatuses?: Record<string, BotDiffStatus>;
  showReadOnlyNotice?: boolean;
  readOnly: boolean;
  onSelect: (nodeId: string) => void;
  onMove: (nodeId: string, location: TreeLocation, toIndex: number) => void;
  onDelete?: (nodeId: string) => void;
  onToggle: (nodeId: string) => void;
}) {
  const invalid = new Set(
    issues
      .filter((issue) => issue.severity === 'error' && issue.nodeId)
      .map((issue) => issue.nodeId!)
  );
  return (
    <section
      aria-label="Secuencia del bot"
      className="bg-editor-canvas h-full overflow-y-auto px-3 py-5 sm:px-6">
      <div className="mx-auto w-full max-w-2xl">
        {readOnly && showReadOnlyNotice ? (
          <div
            className="mb-4 rounded-panel border border-amber-300 bg-amber-50 p-4 text-[12px] leading-5 text-amber-900"
            role="alert">
            <strong>Modo seguro de solo lectura.</strong> Este bot contiene ramas, ciclos o
            componentes desconectados y no puede representarse como una secuencia sin perder
            información.
          </div>
        ) : null}
        <SequenceList comparisonStatuses={comparisonStatuses} depth={0} executionStatuses={executionStatuses} ids={state.root} invalid={invalid} location={{ parentId: null, slot: 'root' }} onDelete={onDelete} onMove={onMove} onSelect={onSelect} onToggle={onToggle} readOnly={readOnly} state={state} />
      </div>
    </section>
  );
}
