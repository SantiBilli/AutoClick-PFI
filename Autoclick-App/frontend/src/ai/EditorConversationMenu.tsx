import { motion, useReducedMotion } from 'framer-motion';
import { History, MessageSquarePlus, MoreVertical, Pencil, Trash2, type LucideIcon } from 'lucide-react';
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { AiConversation } from '@/ai/types';

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
  const reduceMotion = useReducedMotion();
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
      const enabledItems = itemRefs.current.filter(
        (item): item is HTMLButtonElement => Boolean(item && !item.disabled),
      );
      if (!enabledItems.length) return;
      const currentIndex = enabledItems.indexOf(document.activeElement as HTMLButtonElement);
      const nextIndex = event.key === 'ArrowDown'
        ? (currentIndex + 1) % enabledItems.length
        : (currentIndex - 1 + enabledItems.length) % enabledItems.length;
      enabledItems[nextIndex]?.focus();
    }

    function closeOnScroll(event: Event) {
      if (menuRef.current?.contains(event.target as Node)) return;
      setOpen(false);
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
    const estimatedHeight = items.length * 36 + 12;
    const flipUp = rect.bottom + estimatedHeight > window.innerHeight && rect.top > estimatedHeight;
    setPosition({
      top: flipUp ? rect.top - estimatedHeight - 6 : rect.bottom + 6,
      left: Math.max(8, Math.min(rect.right - menuWidth, window.innerWidth - menuWidth - 8)),
    });
  }, [items.length, open]);

  useLayoutEffect(() => {
    if (!open || !position) return;
    itemRefs.current.find((item) => item && !item.disabled)?.focus({ preventScroll: true });
  }, [open, position]);

  const normalItems = items.filter((item) => !item.danger);
  const dangerItems = items.filter((item) => item.danger);
  let itemIndex = -1;

  function renderItem(item: MenuItem) {
    itemIndex += 1;
    const index = itemIndex;
    const Icon = item.icon;
    return (
      <button
        className={`flex w-full items-center gap-2.5 rounded-control px-2.5 py-2 text-left text-[12px] font-bold transition-colors focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-40 ${
          item.danger
            ? 'text-danger hover:bg-red-50 focus-visible:bg-red-50 active:bg-red-100'
            : 'text-text hover:bg-bg focus-visible:bg-bg active:bg-blue-50'
        }`}
        disabled={item.disabled}
        key={item.key}
        onClick={() => {
          const trigger = triggerRef.current;
          trigger?.focus();
          setOpen(false);
          item.onSelect();
          window.requestAnimationFrame(() => {
            if (trigger?.isConnected) trigger.focus();
          });
        }}
        ref={(element) => { itemRefs.current[index] = element; }}
        role="menuitem"
        tabIndex={-1}
        type="button">
        <Icon aria-hidden="true" size={14} />
        {item.label}
      </button>
    );
  }

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
      {open && position
        ? createPortal(
            <motion.div
              animate={{ opacity: 1, y: 0, scale: 1 }}
              aria-label={triggerLabel}
              className="fixed z-40 w-52 rounded-panel border border-border bg-surface p-1.5 shadow-overlay"
              initial={reduceMotion ? { opacity: 1, y: 0, scale: 1 } : { opacity: 0, y: -4, scale: 0.97 }}
              ref={menuRef}
              role="menu"
              style={{ left: position.left, top: position.top }}
              transition={reduceMotion ? { duration: 0 } : { duration: 0.14, ease: [0.16, 1, 0.3, 1] }}>
              {normalItems.map(renderItem)}
              {dangerItems.length ? <div aria-hidden="true" className="my-1.5 h-px bg-border" role="separator" /> : null}
              {dangerItems.map(renderItem)}
            </motion.div>,
            document.body,
          )
        : null}
    </span>
  );
}

export function ChatHeaderMenu({
  atLimit,
  disabled,
  historyOpen,
  maximumConversations,
  onNewConversation,
  onToggleHistory,
}: {
  atLimit: boolean;
  disabled: boolean;
  historyOpen: boolean;
  maximumConversations: number;
  onNewConversation(): void;
  onToggleHistory(): void;
}) {
  return (
    <DropdownMenu
      items={[
        {
          key: 'new',
          label: 'Nueva conversación',
          icon: MessageSquarePlus,
          onSelect: onNewConversation,
          disabled: atLimit || disabled,
        },
        {
          key: 'history',
          label: historyOpen ? 'Ocultar historial' : 'Ver historial',
          icon: History,
          onSelect: onToggleHistory,
        },
      ]}
      triggerLabel={atLimit ? `Opciones de conversación (máximo de ${maximumConversations} conversaciones)` : 'Opciones de conversación'}
    />
  );
}

export function ConversationOptionsMenu({
  conversation,
  disabled,
  canDelete,
  onRenameStart,
  onDelete,
}: {
  conversation: AiConversation;
  disabled: boolean;
  canDelete: boolean;
  onRenameStart(): void;
  onDelete(): void;
}) {
  return (
    <DropdownMenu
      items={[
        { key: 'rename', label: 'Renombrar', icon: Pencil, onSelect: onRenameStart, disabled },
        { key: 'delete', label: 'Eliminar', icon: Trash2, onSelect: onDelete, disabled: !canDelete, danger: true },
      ]}
      triggerLabel={`Opciones de la conversación ${conversation.title}`}
    />
  );
}
