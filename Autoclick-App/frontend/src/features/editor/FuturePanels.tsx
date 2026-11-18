import { Sparkles, TerminalSquare, X } from 'lucide-react';
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import { useEffect, useRef, useState, type Ref } from 'react';
import { AiChat, ConversationList } from '@/ai/AiChat';
import { useAi } from '@/ai/AiProvider';
import { ChatHeaderMenu } from '@/ai/EditorConversationMenu';
import type { AiEditorContext } from '@/ai/types';
import { Mascot } from '@/components/Mascot';

const BUBBLE_NUDGE_INTERVAL_MS = 16_000;
const BUBBLE_NUDGE_DURATION_MS = 2_200;
const BUBBLE_NUDGE_WIGGLE_MS = 600;
const ESCAPE_INTERACTION_OWNER =
  '[aria-roledescription="draggable"], [aria-roledescription="sortable"], [data-dnd-kit-dragging="true"]';
const OPEN_DIALOG =
  'dialog[open], [role="dialog"][aria-modal="true"], [role="dialog"][data-state="open"]';

export function EditorAiPanel({
  getEditorContext,
  onClose,
}: {
  getEditorContext: () => AiEditorContext;
  onClose: () => void;
}) {
  const ai = useAi();
  const reduceMotion = Boolean(useReducedMotion());
  const [historyOpen, setHistoryOpen] = useState(false);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const focusComposerAfterHistoryRef = useRef(false);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    closeButtonRef.current?.focus();
  }, []);

  useEffect(() => {
    if (historyOpen || !focusComposerAfterHistoryRef.current) return;
    focusComposerAfterHistoryRef.current = false;
    const frame = window.requestAnimationFrame(() => {
      document.querySelector<HTMLElement>('#ai-editor-message')?.focus();
    });
    return () => window.cancelAnimationFrame(frame);
  }, [historyOpen]);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key !== 'Escape' || event.defaultPrevented || document.querySelector(OPEN_DIALOG))
        return;
      const owner = event.target instanceof Element ? event.target : document.activeElement;
      if (owner?.closest(ESCAPE_INTERACTION_OWNER)) return;
      const panel = panelRef.current;
      if (!panel || !(owner instanceof Node) || !panel.contains(owner)) return;
      onClose();
    }
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  return (
    <motion.div
      animate={{ opacity: 1 }}
      aria-label="AutoClick AI"
      className="flex h-full min-h-0 w-full flex-1 flex-col overflow-hidden bg-surface"
      initial={reduceMotion ? { opacity: 1 } : { opacity: 0 }}
      ref={panelRef}
      role="region"
      transition={reduceMotion ? { duration: 0 } : { duration: 0.2 }}>
      <div className="flex shrink-0 items-center justify-between gap-2 border-b border-border bg-gradient-to-r from-cyan-50/70 to-white px-3 py-2.5">
        <span className="flex min-w-0 items-center gap-1.5 text-[13px] font-extrabold text-secondary">
          <Mascot float={false} size={22} state="face" />
          Asistente IA
        </span>
        <div className="flex shrink-0 items-center gap-0.5">
          <ChatHeaderMenu
            atLimit={ai.state.conversations.length >= ai.maximumConversations}
            disabled={ai.mutationsDisabled}
            historyOpen={historyOpen}
            maximumConversations={ai.maximumConversations}
            onNewConversation={() => {
              ai.createConversation();
              setHistoryOpen(false);
            }}
            onToggleHistory={() => setHistoryOpen((value) => !value)}
          />
          <button
            aria-label="Cerrar AutoClick AI"
            className="shrink-0 rounded-control p-2 text-text-muted transition-colors hover:bg-black/5 hover:text-text focus-visible:outline-none focus-visible:shadow-focus"
            onClick={onClose}
            ref={closeButtonRef}
            type="button">
            <X aria-hidden="true" size={18} />
          </button>
        </div>
      </div>
      <div className="flex min-h-0 flex-1 flex-col">
        {historyOpen ? (
          <ConversationList
            editor
            onAfterSelect={() => {
              focusComposerAfterHistoryRef.current = true;
              setHistoryOpen(false);
            }}
          />
        ) : (
          <AiChat compact getEditorContext={getEditorContext} />
        )}
      </div>
    </motion.div>
  );
}

export function AiChatBubble({
  open,
  onOpen,
  ref,
}: {
  open: boolean;
  onOpen: () => void;
  ref?: Ref<HTMLButtonElement>;
}) {
  const [nudging, setNudging] = useState(false);
  const [hovered, setHovered] = useState(false);
  const reduceMotion = useReducedMotion();

  useEffect(() => {
    if (open || reduceMotion) {
      setNudging(false);
      return;
    }
    let timeout: number | undefined;
    const interval = window.setInterval(() => {
      setNudging(true);
      timeout = window.setTimeout(() => setNudging(false), BUBBLE_NUDGE_DURATION_MS);
    }, BUBBLE_NUDGE_INTERVAL_MS);
    return () => {
      window.clearInterval(interval);
      if (timeout !== undefined) window.clearTimeout(timeout);
    };
  }, [open, reduceMotion]);

  return (
    <motion.button
      animate={
        open
          ? { opacity: 0, scale: 0.6 }
          : reduceMotion
            ? { opacity: 1, scale: 1, y: 0 }
            : { opacity: 1, scale: 1, y: [0, -5, 0] }
      }
      aria-hidden={open}
      aria-label="Abrir AutoClick AI"
      className={`absolute right-4 bottom-4 z-20 grid size-14 place-items-center rounded-full bg-gradient-to-br from-secondary to-cyan-400 shadow-glow-secondary focus-visible:outline-none focus-visible:shadow-focus ${open ? 'pointer-events-none' : 'pointer-events-auto'}`}
      onClick={onOpen}
      onHoverEnd={() => setHovered(false)}
      onHoverStart={() => setHovered(true)}
      ref={ref}
      tabIndex={open ? -1 : 0}
      transition={
        reduceMotion
          ? { duration: 0 }
          : {
              y: { duration: 2.6, repeat: Infinity, ease: 'easeInOut' },
              default: { duration: 0.2 },
            }
      }
      type="button"
      whileHover={open ? undefined : { scale: 1.08 }}
      whileTap={open ? undefined : { scale: 0.92 }}>
      {!open && !reduceMotion ? (
        <motion.span
          animate={{ scale: 1.7, opacity: 0 }}
          className="absolute inset-0 rounded-full bg-secondary/60"
          initial={{ scale: 1, opacity: 0.55 }}
          transition={{ duration: 1.8, repeat: Infinity, ease: 'easeOut' }}
        />
      ) : null}
      <AnimatePresence>
        {hovered && !open ? (
          <motion.span
            animate={{ opacity: 1, y: 0, scale: 1 }}
            aria-hidden="true"
            className="absolute right-0 bottom-full mb-3"
            exit={{ opacity: 0, y: 4, scale: 0.94 }}
            initial={{ opacity: 0, y: 4, scale: 0.94 }}
            transition={{ duration: 0.18, ease: [0.16, 1, 0.3, 1] }}>
            {!reduceMotion ? (
              <motion.span
                animate={{ scale: [1, 1.15, 1], opacity: [0.55, 0.2, 0.55] }}
                aria-hidden="true"
                className="absolute inset-0 -z-10 rounded-full bg-cyan-300/70 blur-md"
                transition={{ duration: 2.2, repeat: Infinity, ease: 'easeInOut' }}
              />
            ) : null}
            <span className="relative flex items-center gap-1.5 rounded-full border-2 border-cyan-200 bg-white px-3.5 py-2 text-[12px] font-extrabold whitespace-nowrap text-secondary shadow-glow-secondary">
              <Sparkles aria-hidden="true" size={13} />
              ¡Hola! Soy ClickIA
            </span>
            <span
              aria-hidden="true"
              className="absolute top-full right-6 size-2.5 -translate-y-1/2 rotate-45 border-r-2 border-b-2 border-cyan-200 bg-white"
            />
          </motion.span>
        ) : null}
      </AnimatePresence>
      <motion.span
        animate={
          !reduceMotion && nudging
            ? { rotate: [0, -12, 10, -6, 0], scale: [1, 1.14, 1] }
            : { rotate: 0, scale: 1 }
        }
        className="relative"
        transition={
          reduceMotion
            ? { duration: 0 }
            : { duration: BUBBLE_NUDGE_WIGGLE_MS / 1000, ease: 'easeInOut' }
        }>
        <motion.span
          animate={reduceMotion ? undefined : { rotate: [0, -6, 4, -3, 0] }}
          className="block"
          transition={
            reduceMotion
              ? { duration: 0 }
              : { duration: 5, ease: 'easeInOut', repeat: Infinity, repeatDelay: 1.4 }
          }>
          <Mascot blink={false} float={false} interactive={false} size={40} state="face" />
        </motion.span>
      </motion.span>
    </motion.button>
  );
}

export function ConsolePlaceholder() {
  return (
    <footer className="flex h-10 shrink-0 items-center gap-2 border-t border-border bg-sidebar px-4 text-[11px] text-slate-300">
      <TerminalSquare aria-hidden="true" size={15} />
      <strong className="text-white">Actividad</strong>
      <span className="h-3 w-px bg-slate-600" />
      Disponible al ejecutar bots
    </footer>
  );
}
