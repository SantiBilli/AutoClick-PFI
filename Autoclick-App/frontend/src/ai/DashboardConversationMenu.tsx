import { motion, useReducedMotion } from 'framer-motion';
import { MoreVertical, Pencil, Trash2, X, type LucideIcon } from 'lucide-react';
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { AiConversation } from '@/ai/types';
import { Mascot } from '@/components/Mascot';
import { OverlayDialog } from '@/features/editor/OverlayDialog';

type MenuItem = {
  key: string;
  label: string;
  icon: LucideIcon;
  onSelect(): void;
  disabled?: boolean;
  danger?: boolean;
};

function DropdownMenu({ triggerLabel, items }: { triggerLabel: string; items: MenuItem[] }) {
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null);
  const reduceMotion = Boolean(useReducedMotion());
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const itemRefs = useRef<Array<HTMLButtonElement | null>>([]);

  useEffect(() => {
    if (!open) return;
    function closeOnOutsidePointer(event: PointerEvent) {
      const target = event.target as Node;
      if (menuRef.current?.contains(target) || triggerRef.current?.contains(target)) return;
      setOpen(false);
    }
    function handleKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key === 'Escape') {
        event.preventDefault();
        event.stopPropagation();
        setOpen(false);
        triggerRef.current?.focus();
        return;
      }
      if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
      event.preventDefault();
      const enabled = itemRefs.current.filter(
        (item): item is HTMLButtonElement => Boolean(item && !item.disabled),
      );
      if (!enabled.length) return;
      const currentIndex = enabled.indexOf(document.activeElement as HTMLButtonElement);
      const nextIndex = event.key === 'ArrowDown'
        ? (currentIndex + 1) % enabled.length
        : (currentIndex - 1 + enabled.length) % enabled.length;
      enabled[nextIndex]?.focus();
    }
    function closeOnScroll(event: Event) {
      if (!menuRef.current?.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener('pointerdown', closeOnOutsidePointer);
    document.addEventListener('keydown', handleKeyDown);
    document.addEventListener('scroll', closeOnScroll, true);
    return () => {
      document.removeEventListener('pointerdown', closeOnOutsidePointer);
      document.removeEventListener('keydown', handleKeyDown);
      document.removeEventListener('scroll', closeOnScroll, true);
    };
  }, [open]);

  useLayoutEffect(() => {
    if (!open || !triggerRef.current) return;
    const menuWidth = 208;
    const rect = triggerRef.current.getBoundingClientRect();
    const estimatedHeight = items.length * 36 + 24;
    const flipUp = rect.bottom + estimatedHeight > window.innerHeight && rect.top > estimatedHeight;
    setPosition({
      top: flipUp ? rect.top - estimatedHeight - 6 : rect.bottom + 6,
      left: Math.max(8, Math.min(rect.right - menuWidth, window.innerWidth - menuWidth - 8)),
    });
  }, [items.length, open]);

  useLayoutEffect(() => {
    if (open && position) itemRefs.current.find((item) => item && !item.disabled)?.focus({ preventScroll: true });
  }, [open, position]);

  const orderedItems = [...items.filter((item) => !item.danger), ...items.filter((item) => item.danger)];
  return (
    <span className="relative inline-flex shrink-0">
      <button
        aria-expanded={open}
        aria-haspopup="menu"
        aria-label={triggerLabel}
        className="grid size-8 shrink-0 place-items-center rounded-control text-text-muted transition-colors hover:bg-black/5 hover:text-text focus-visible:outline-none focus-visible:shadow-focus"
        onClick={(event) => {
          event.stopPropagation();
          setOpen((value) => !value);
        }}
        ref={triggerRef}
        type="button">
        <MoreVertical aria-hidden="true" size={16} />
      </button>
      {open && position ? createPortal(
        <motion.div
          animate={{ opacity: 1, y: 0, scale: 1 }}
          aria-label={triggerLabel}
          className="fixed z-40 w-52 rounded-panel border border-border bg-surface p-1.5 shadow-overlay"
          initial={reduceMotion ? { opacity: 1, y: 0, scale: 1 } : { opacity: 0, y: -4, scale: 0.97 }}
          ref={menuRef}
          role="menu"
          style={{ left: position.left, top: position.top }}
          transition={reduceMotion ? { duration: 0 } : { duration: 0.14, ease: [0.16, 1, 0.3, 1] }}>
          {orderedItems.map((item, index) => {
            const Icon = item.icon;
            const divider = item.danger && index > 0;
            return (
              <span className="contents" key={item.key}>
                {divider ? <span aria-hidden="true" className="my-1.5 block h-px bg-border" /> : null}
                <button
                  className={`flex w-full items-center gap-2.5 rounded-control px-2.5 py-2 text-left text-[12px] font-bold transition-colors focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-40 ${item.danger ? 'text-danger hover:bg-red-50 focus-visible:bg-red-50' : 'text-text hover:bg-bg focus-visible:bg-bg'}`}
                  disabled={item.disabled}
                  onClick={() => {
                    setOpen(false);
                    triggerRef.current?.focus();
                    item.onSelect();
                  }}
                  ref={(element) => { itemRefs.current[index] = element; }}
                  role="menuitem"
                  tabIndex={-1}
                  type="button">
                  <Icon aria-hidden="true" size={14} />
                  {item.label}
                </button>
              </span>
            );
          })}
        </motion.div>,
        document.body,
      ) : null}
    </span>
  );
}

export function DashboardConversationMenu({
  conversation,
  disabled,
  canDelete,
  onRenameStart,
  onDelete,
  onToast,
}: {
  conversation: AiConversation;
  disabled: boolean;
  canDelete: boolean;
  onRenameStart(): void;
  onDelete(): void;
  onToast(message: string, tone: 'success' | 'error'): void;
}) {
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteError, setDeleteError] = useState(false);

  function closeDelete() {
    setDeleteOpen(false);
    setDeleteError(false);
  }

  return (
    <>
      <DropdownMenu
        items={[
          { key: 'rename', label: 'Renombrar', icon: Pencil, onSelect: onRenameStart, disabled },
          { key: 'delete', label: 'Eliminar', icon: Trash2, onSelect: () => {
            setDeleteError(false);
            setDeleteOpen(true);
          }, disabled: !canDelete, danger: true },
        ]}
        triggerLabel={`Opciones de la conversación ${conversation.title}`}
      />
      <OverlayDialog
        ariaLabel="¿Eliminar conversación?"
        className="hidden inset-0 h-screen w-screen p-4 open:grid open:place-items-center"
        onDismiss={closeDelete}
        open={deleteOpen}>
        <div className="relative w-full max-w-sm rounded-panel border border-border bg-surface shadow-overlay">
          <Mascot className="absolute -top-4 -left-3 z-10" decorative={false} entrance="bounce" float={false} interactive={false} size={40} state="thinking" />
          <div className="flex items-center gap-3 border-b border-border px-5 pt-4 pb-3.5">
            <span className="grid size-10 shrink-0 place-items-center rounded-control bg-red-50 text-danger shadow-sm">
              <Trash2 aria-hidden="true" size={18} />
            </span>
            <h2 className="m-0 min-w-0 flex-1 truncate text-lg font-extrabold">¿Eliminar conversación?</h2>
            <button aria-label="Cerrar" className="rounded-control p-1.5 text-text-muted hover:bg-black/5 focus-visible:outline-none focus-visible:shadow-focus" onClick={closeDelete} type="button">
              <X aria-hidden="true" size={18} />
            </button>
          </div>
          <div className="p-5">
            <p className="m-0 truncate text-[12px] font-bold text-text" title={conversation.title}>{conversation.title}</p>
            <p className="mt-2 mb-4 text-[13px] leading-5 text-text-muted">Esta acción no se puede deshacer. Se perderán todos los mensajes de esta conversación.</p>
            {deleteError ? (
              <p className="mb-4 rounded-control border border-red-200 bg-red-50 px-3 py-2 text-[12px] font-bold text-danger" role="alert">
                No se pudo eliminar la conversación localmente. Intentá nuevamente.
              </p>
            ) : null}
            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <button className="inline-flex h-10 items-center justify-center rounded-control border border-border bg-white px-4 text-[13px] font-bold focus-visible:outline-none focus-visible:shadow-focus" data-dialog-initial-focus onClick={closeDelete} type="button">Cancelar</button>
              <button
                className="inline-flex h-10 items-center justify-center gap-2 rounded-control bg-danger px-4 text-[13px] font-bold text-white focus-visible:outline-none focus-visible:shadow-focus disabled:opacity-60"
                onClick={() => {
                  try {
                    onDelete();
                  } catch {
                    setDeleteError(true);
                    return;
                  }
                  setDeleteOpen(false);
                  onToast('Conversación eliminada localmente.', 'success');
                }}
                type="button">
                <Trash2 aria-hidden="true" size={15} />
                Eliminar
              </button>
            </div>
          </div>
        </div>
      </OverlayDialog>
    </>
  );
}
