import { CheckCircle2, ChevronDown, GripVertical, Play, Save, Search, Square, X } from 'lucide-react';
import { AnimatePresence, motion } from 'framer-motion';
import { useDeferredValue, useState } from 'react';
import { useDraggable, useDroppable } from '@dnd-kit/core';
import { useCombinedRefs } from '@dnd-kit/utilities';
import { actionRegistry } from '@/bot/registry';
import { actionIcons } from '@/features/editor/actionIcons';
import { OverlayDialog } from '@/features/editor/OverlayDialog';
import { catalogDndId } from '@/features/editor/sequenceDrop';

type Props = {
  open: boolean;
  onAdd: (actionType: string) => void;
  onClose: () => void;
  disabled?: boolean;
  dirty: boolean;
  canSave: boolean;
  saving: boolean;
  canExecute: boolean;
  canCancel: boolean;
  cancelling: boolean;
  onSave: () => void;
  onValidate: () => void;
  onExecute: () => void;
  onCancel: () => void;
};

const categoryColors: Record<string, { dot: string; tile: string; hoverTile: string }> = {
  execution: { dot: 'bg-blue-500', tile: 'bg-blue-50 text-blue-600', hoverTile: 'group-hover/item:bg-blue-100' },
  variables: { dot: 'bg-amber-500', tile: 'bg-amber-50 text-amber-600', hoverTile: 'group-hover/item:bg-amber-100' },
  mouse: { dot: 'bg-violet-500', tile: 'bg-violet-50 text-violet-600', hoverTile: 'group-hover/item:bg-violet-100' },
  keyboard: { dot: 'bg-violet-500', tile: 'bg-violet-50 text-violet-600', hoverTile: 'group-hover/item:bg-violet-100' },
  excel: { dot: 'bg-emerald-500', tile: 'bg-emerald-50 text-emerald-600', hoverTile: 'group-hover/item:bg-emerald-100' },
  browser: { dot: 'bg-sky-500', tile: 'bg-sky-50 text-sky-600', hoverTile: 'group-hover/item:bg-sky-100' },
  window: { dot: 'bg-indigo-500', tile: 'bg-indigo-50 text-indigo-600', hoverTile: 'group-hover/item:bg-indigo-100' },
  file: { dot: 'bg-cyan-500', tile: 'bg-cyan-50 text-cyan-600', hoverTile: 'group-hover/item:bg-cyan-100' },
  folder: { dot: 'bg-cyan-500', tile: 'bg-cyan-50 text-cyan-600', hoverTile: 'group-hover/item:bg-cyan-100' },
  clipboard: { dot: 'bg-teal-500', tile: 'bg-teal-50 text-teal-600', hoverTile: 'group-hover/item:bg-teal-100' },
  system: { dot: 'bg-slate-500', tile: 'bg-slate-100 text-slate-600', hoverTile: 'group-hover/item:bg-slate-200' },
  flow: { dot: 'bg-fuchsia-500', tile: 'bg-fuchsia-50 text-fuchsia-600', hoverTile: 'group-hover/item:bg-fuchsia-100' },
  http: { dot: 'bg-rose-500', tile: 'bg-rose-50 text-rose-600', hoverTile: 'group-hover/item:bg-rose-100' },
  workflow: { dot: 'bg-purple-500', tile: 'bg-purple-50 text-purple-600', hoverTile: 'group-hover/item:bg-purple-100' },
  vision: { dot: 'bg-pink-500', tile: 'bg-pink-50 text-pink-600', hoverTile: 'group-hover/item:bg-pink-100' },
};
const defaultCategoryColor = { dot: 'bg-primary', tile: 'bg-blue-50 text-primary', hoverTile: 'group-hover/item:bg-blue-100' };

type ToolbarIconButtonProps = {
  label: string;
  icon: typeof Save;
  onClick: () => void;
  disabled?: boolean;
  tone?: 'default' | 'primary' | 'danger';
  busy?: boolean;
  keyShortcuts?: string;
};

function ToolbarIconButton({ label, icon: Icon, onClick, disabled, tone = 'default', busy, keyShortcuts }: ToolbarIconButtonProps) {
  const [hovered, setHovered] = useState(false);
  const toneClass = tone === 'primary'
    ? 'border-transparent bg-primary text-white hover:bg-primary-hover hover:shadow-glow-primary'
    : tone === 'danger'
      ? 'border-border bg-white text-text-muted hover:border-red-200 hover:bg-red-50 hover:text-danger'
      : 'border-border bg-white text-text-muted hover:border-blue-200 hover:bg-blue-50 hover:text-primary';
  return (
    <span className="relative inline-flex">
      <motion.button
        aria-keyshortcuts={keyShortcuts}
        aria-label={label}
        className={`grid size-8 shrink-0 place-items-center rounded-control border transition-colors focus-visible:outline-none focus-visible:shadow-focus disabled:cursor-not-allowed disabled:opacity-40 disabled:shadow-none ${toneClass}`}
        disabled={disabled}
        onBlur={() => setHovered(false)}
        onClick={onClick}
        onFocus={() => setHovered(true)}
        onHoverEnd={() => setHovered(false)}
        onHoverStart={() => setHovered(true)}
        type="button"
        whileHover={disabled ? undefined : { scale: 1.08 }}
        whileTap={disabled ? undefined : { scale: 0.92 }}>
        <Icon aria-hidden="true" className={busy ? 'motion-safe:animate-spin' : ''} size={15} />
      </motion.button>
      <AnimatePresence>
        {hovered && !disabled ? (
          <motion.span
            animate={{ opacity: 1, y: 0, scale: 1 }}
            className="pointer-events-none absolute top-full left-1/2 z-30 mt-2 -translate-x-1/2 rounded-control bg-sidebar px-2.5 py-1.5 text-[11px] font-bold whitespace-nowrap text-white shadow-overlay"
            exit={{ opacity: 0, y: 4, scale: 0.95 }}
            initial={{ opacity: 0, y: 4, scale: 0.95 }}
            transition={{ duration: 0.12 }}>
            {label}
            <span aria-hidden="true" className="absolute -top-1 left-1/2 size-2 -translate-x-1/2 rotate-45 bg-sidebar" />
          </motion.span>
        ) : null}
      </AnimatePresence>
    </span>
  );
}

function CatalogAction({ action, disabled, onAdd }: { action: (typeof actionRegistry.actions)[number]; disabled: boolean; onAdd: (actionType: string) => void }) {
  const Icon = actionIcons[action.icon];
  const id = catalogDndId(action.id);
  const color = categoryColors[action.category] ?? defaultCategoryColor;
  const { attributes, listeners, setNodeRef: setDraggableNodeRef, isDragging } = useDraggable({ id, disabled });
  const { setNodeRef: setDroppableNodeRef } = useDroppable({ id, disabled });
  const setNodeRef = useCombinedRefs(setDraggableNodeRef, setDroppableNodeRef);
  return (
    <button
      className={`group/item flex cursor-grab items-start gap-2.5 rounded-control border border-transparent px-2.5 py-2.5 text-left transition-[background-color,border-color,transform] duration-150 ease-out hover:border-blue-100 hover:bg-blue-50/70 focus-visible:outline-none focus-visible:shadow-focus active:scale-[0.98] active:cursor-grabbing disabled:cursor-not-allowed disabled:opacity-50 disabled:active:scale-100 ${isDragging ? 'opacity-45' : ''}`}
      data-catalog-action={action.id}
      disabled={disabled}
      key={action.id}
      onClick={() => onAdd(action.id)}
      ref={setNodeRef}
      title="Arrastrá a la secuencia o presioná para agregar al final"
      type="button"
      {...attributes}
      {...listeners}>
      <span className={`mt-0.5 grid size-7 shrink-0 place-items-center rounded-md shadow-sm transition-colors ${color.tile} ${color.hoverTile}`}><Icon aria-hidden="true" size={15} /></span>
      <span className="min-w-0 flex-1"><span className="block text-[13px] font-extrabold">{action.title}</span><span className="mt-0.5 block text-[11px] leading-4 text-text-muted">{action.description}</span></span>
      <GripVertical aria-hidden="true" className="mt-1 shrink-0 text-border group-hover/item:text-text-muted" size={14} />
    </button>
  );
}

export function ActionCatalog({ open, onAdd, onClose, disabled = false, dirty, canSave, saving, canExecute, canCancel, cancelling, onSave, onValidate, onExecute, onCancel }: Props) {
  const [query, setQuery] = useState('');
  const deferredQuery = useDeferredValue(query.trim().toLocaleLowerCase('es'));
  const categories = new Map<string, { name: string; actions: typeof actionRegistry.actions }>();

  for (const action of actionRegistry.actions) {
    if (deferredQuery && !`${action.title} ${action.description} ${action.categoryName}`.toLocaleLowerCase('es').includes(deferredQuery)) continue;
    const category = categories.get(action.category) ?? { name: action.categoryName, actions: [] };
    category.actions.push(action);
    categories.set(action.category, category);
  }

  const contents = (mobile: boolean) => (
    <>
      <div className="border-b border-border bg-gradient-to-br from-blue-50/80 via-blue-50/25 to-transparent px-4 pt-3.5 pb-3.5">
        <div className="flex items-center justify-between gap-2">
          <h2 className="m-0 text-2xl font-extrabold tracking-tight">Bloques</h2>
          <div className="flex shrink-0 items-center gap-1">
            <ToolbarIconButton busy={saving} disabled={!canSave || saving} icon={Save} keyShortcuts="Control+S Meta+S" label={saving ? 'Guardando…' : 'Guardar'} onClick={onSave} tone="primary" />
            <ToolbarIconButton icon={CheckCircle2} label="Validar" onClick={onValidate} />
            {canCancel ? (
              <ToolbarIconButton icon={Square} label={cancelling ? 'Cancelando...' : 'Cancelar'} onClick={onCancel} tone="danger" />
            ) : (
              <ToolbarIconButton disabled={!canExecute} icon={Play} label="Ejecutar" onClick={onExecute} />
            )}
            <button aria-label="Cerrar catálogo" className={`rounded-control p-1.5 hover:bg-bg focus-visible:outline-none focus-visible:shadow-focus ${mobile ? '' : 'hidden'}`} onClick={onClose} type="button">
              <X aria-hidden="true" size={17} />
            </button>
          </div>
        </div>
        <span className={`mt-2 flex items-center gap-1.5 text-[10px] font-bold whitespace-nowrap transition-colors duration-300 ${dirty ? 'text-red-900' : 'text-success'}`} role="status">
          <span className="relative flex size-1.5 shrink-0">
            {dirty ? <motion.span animate={{ scale: [1, 1.8], opacity: [0.7, 0] }} className="absolute inset-0 rounded-full bg-red-800" transition={{ duration: 1.4, repeat: Infinity, ease: 'easeOut' }} /> : null}
            <span className={`relative size-1.5 rounded-full ${dirty ? 'bg-red-800' : 'bg-success'}`} />
          </span>
          {dirty ? 'Cambios sin guardar' : 'Guardado'}
        </span>
      </div>
      <label className="group relative m-3 block">
        <span className="sr-only">Buscar bloques</span>
        <Search aria-hidden="true" className="pointer-events-none absolute top-1/2 left-3.5 -translate-y-1/2 text-text-muted transition-colors duration-150 group-focus-within:text-primary" size={16} />
        <input
          data-dialog-initial-focus={mobile ? true : undefined}
          className="field-control h-10 w-full rounded-control bg-white pr-8 pl-10 text-[13px] font-medium text-text transition-[border-color,box-shadow] duration-150 ease-out placeholder:font-normal placeholder:text-text-muted [&::-webkit-search-cancel-button]:appearance-none"
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Buscar bloques…"
          type="search"
          value={query}
        />
        {query ? (
          <button aria-label="Limpiar búsqueda" className="absolute top-1/2 right-2 grid size-6 -translate-y-1/2 place-items-center rounded-full text-text-muted transition-colors hover:bg-bg hover:text-text focus-visible:outline-none focus-visible:shadow-focus" onClick={() => setQuery('')} type="button">
            <X aria-hidden="true" size={13} />
          </button>
        ) : null}
      </label>
      <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-4">
        {[...categories.entries()].map(([id, category]) => (
          <details className="group border-b border-border py-2" key={id} open>
            <summary className="flex cursor-pointer list-none items-center justify-between rounded-control px-2 py-2 text-[12px] font-extrabold tracking-[0.05em] uppercase hover:bg-bg focus-visible:outline-none focus-visible:shadow-focus">
              <span className="flex items-center gap-2">
                <span aria-hidden="true" className={`size-2 shrink-0 rounded-full ${(categoryColors[id] ?? defaultCategoryColor).dot}`} />
                {category.name}
              </span>
              <ChevronDown aria-hidden="true" className="transition-transform group-open:rotate-180" size={15} />
            </summary>
            <div className="grid gap-1.5 pt-1">
              {category.actions.map((action) => {
                return <CatalogAction action={action} disabled={disabled} key={action.id} onAdd={onAdd} />;
              })}
            </div>
          </details>
        ))}
        {categories.size === 0 ? <p className="px-2 py-6 text-center text-[12px] text-text-muted">No hay bloques que coincidan.</p> : null}
      </div>
    </>
  );

  return (
    <>
      <aside aria-label="Catálogo de bloques" className="hidden min-h-0 flex-1 flex-col bg-gradient-to-b from-white to-blue-50/30 lg:flex">
        {contents(false)}
      </aside>
      <OverlayDialog ariaLabel="Catálogo de bloques móvil" className="inset-y-0 left-0 h-screen w-[min(88vw,300px)] lg:hidden" onDismiss={onClose} open={open}>
        <div className="flex h-full flex-col border-r border-border bg-gradient-to-b from-white to-blue-50/30 shadow-overlay">{contents(true)}</div>
      </OverlayDialog>
    </>
  );
}
