import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import { History, MessageSquarePlus, Trash2, X } from 'lucide-react';
import { useRef, useState } from 'react';
import { AiChat, ConversationList } from '@/ai/AiChat';
import { DashboardAiProvider, useAi } from '@/ai/AiProvider';
import { Mascot } from '@/components/Mascot';
import { OverlayDialog } from '@/features/editor/OverlayDialog';

function AutoClickAiPageContent() {
  const ai = useAi();
  const [historyOpen, setHistoryOpen] = useState(false);
  const [clearDialogOpen, setClearDialogOpen] = useState(false);
  const toggleRef = useRef<HTMLButtonElement>(null);
  const reduceMotion = Boolean(useReducedMotion());
  const atLimit = ai.state.conversations.length >= ai.maximumConversations;

  function closeHistory(restoreToggle = true) {
    setHistoryOpen(false);
    if (restoreToggle) window.requestAnimationFrame(() => toggleRef.current?.focus());
  }

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      <motion.div
        animate={{ opacity: 1, y: 0 }}
        className="mb-4 flex shrink-0 flex-wrap items-center gap-2 sm:gap-3"
        initial={reduceMotion ? { opacity: 1, y: 0 } : { opacity: 0, y: -8 }}
        transition={reduceMotion ? { duration: 0 } : { duration: 0.35, ease: [0.16, 1, 0.3, 1] }}>
        <Mascot decorative={false} float={false} interactive={false} size={34} state="face" />
        <div className="min-w-0 flex-1">
          <h1 className="m-0 text-2xl font-extrabold">Asistente IA</h1>
          <p className="m-0 text-[13px] text-text-muted">
            Asistente local especializado en tus automatizaciones.
          </p>
        </div>
        <button
          aria-label={
            historyOpen ? 'Ocultar historial de conversaciones' : 'Ver historial de conversaciones'
          }
          aria-pressed={historyOpen}
          className={`inline-flex shrink-0 items-center gap-2 rounded-control border px-3.5 py-2 text-[12.5px] font-bold shadow-sm transition-colors focus-visible:outline-none focus-visible:shadow-focus ${historyOpen ? 'border-primary bg-blue-50 text-primary' : 'border-border bg-white text-text hover:border-blue-200 hover:bg-blue-50/60 hover:text-primary'}`}
          onClick={() => (historyOpen ? closeHistory(false) : setHistoryOpen(true))}
          ref={toggleRef}
          type="button">
          <History aria-hidden="true" size={16} />
          Historial
        </button>
        <button
          aria-label="Nueva conversación"
          className="inline-flex shrink-0 items-center gap-2 rounded-control border border-border bg-white px-3.5 py-2 text-[12.5px] font-bold text-text shadow-sm transition-colors hover:border-blue-200 hover:bg-blue-50/60 hover:text-primary focus-visible:outline-none focus-visible:shadow-focus disabled:cursor-not-allowed disabled:opacity-50"
          disabled={atLimit || ai.mutationsDisabled}
          onClick={() => ai.createConversation()}
          title={
            atLimit
              ? `Alcanzaste el máximo de ${ai.maximumConversations} conversaciones`
              : undefined
          }
          type="button">
          <MessageSquarePlus aria-hidden="true" size={16} />
          Nueva conversación
        </button>
        <button
          aria-label="Limpiar todos los chats"
          className="inline-flex shrink-0 items-center gap-2 rounded-control border border-border bg-white px-3.5 py-2 text-[12.5px] font-bold text-text shadow-sm transition-colors hover:border-red-200 hover:bg-red-50 hover:text-danger focus-visible:outline-none focus-visible:shadow-focus disabled:cursor-not-allowed disabled:opacity-50"
          disabled={ai.state.conversations.length === 0 || ai.mutationsDisabled}
          onClick={() => setClearDialogOpen(true)}
          title={
            ai.state.conversations.length === 0
              ? 'No hay conversaciones para limpiar'
              : 'Eliminar todas las conversaciones'
          }
          type="button">
          <Trash2 aria-hidden="true" size={16} />
          Limpiar chats
        </button>
      </motion.div>
      <motion.div
        animate={{ opacity: 1, scale: 1 }}
        className="relative flex min-h-0 flex-1 overflow-hidden rounded-panel border border-border bg-surface shadow-card"
        initial={reduceMotion ? { opacity: 1, scale: 1 } : { opacity: 0, scale: 0.99 }}
        transition={
          reduceMotion ? { duration: 0 } : { duration: 0.35, delay: 0.05, ease: [0.16, 1, 0.3, 1] }
        }>
        <AnimatePresence initial={false}>
          {historyOpen ? (
            <motion.aside
              animate={{ opacity: 1, x: 0 }}
              className="absolute inset-0 z-30 flex min-h-0 w-full shrink-0 overflow-hidden bg-surface sm:relative sm:inset-auto sm:z-auto sm:w-[304px] sm:border-r sm:border-border"
              data-testid="dashboard-history-panel"
              exit={reduceMotion ? { opacity: 1, x: 0 } : { opacity: 0, x: -16 }}
              initial={reduceMotion ? { opacity: 1, x: 0 } : { opacity: 0, x: -16 }}
              transition={
                reduceMotion ? { duration: 0 } : { duration: 0.25, ease: [0.16, 1, 0.3, 1] }
              }>
              <div className="flex min-h-0 w-full flex-col sm:w-[304px]">
                <div className="flex shrink-0 items-center justify-between gap-2 border-b border-border px-3 py-2.5">
                  <span className="flex min-w-0 items-center gap-1.5 text-[11px] font-extrabold tracking-[0.04em] text-text-muted uppercase">
                    <History aria-hidden="true" size={14} />
                    Historial de conversaciones
                  </span>
                  <div className="flex items-center gap-1">
                    {ai.state.conversations.length > 0 ? (
                      <button
                        aria-label="Limpiar todas las conversaciones"
                        className="rounded-control p-1.5 text-text-muted hover:bg-red-50 hover:text-danger focus-visible:outline-none focus-visible:shadow-focus disabled:cursor-not-allowed disabled:opacity-50"
                        disabled={ai.mutationsDisabled}
                        onClick={() => setClearDialogOpen(true)}
                        title="Limpiar todas las conversaciones"
                        type="button">
                        <Trash2 aria-hidden="true" size={14} />
                      </button>
                    ) : null}
                    <button
                      aria-label="Cerrar historial"
                      className="shrink-0 rounded-control p-1.5 text-text-muted hover:bg-black/5 hover:text-text focus-visible:outline-none focus-visible:shadow-focus"
                      onClick={() => closeHistory()}
                      type="button">
                      <X aria-hidden="true" size={15} />
                    </button>
                  </div>
                </div>
                <ConversationList
                  onAfterSelect={() => {
                    closeHistory(false);
                    window.requestAnimationFrame(() =>
                      document.getElementById('ai-page-message')?.focus()
                    );
                  }}
                />
              </div>
            </motion.aside>
          ) : null}
        </AnimatePresence>
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
          <AiChat />
        </div>
      </motion.div>

      <OverlayDialog
        ariaLabel="¿Limpiar todos los chats?"
        className="hidden inset-0 h-screen w-screen p-4 open:grid open:place-items-center"
        onDismiss={() => setClearDialogOpen(false)}
        open={clearDialogOpen}>
        <div className="relative w-full max-w-sm rounded-panel border border-border bg-surface shadow-overlay">
          <Mascot
            className="absolute -top-4 -left-3 z-10"
            decorative={false}
            entrance="bounce"
            float={false}
            interactive={false}
            size={40}
            state="thinking"
          />
          <div className="flex items-center gap-3 border-b border-border px-5 pt-4 pb-3.5">
            <span className="grid size-10 shrink-0 place-items-center rounded-control bg-red-50 text-danger shadow-sm">
              <Trash2 aria-hidden="true" size={18} />
            </span>
            <div className="min-w-0 flex-1">
              <h2 className="m-0 text-lg font-extrabold text-text">¿Limpiar todos los chats?</h2>
            </div>
            <button
              aria-label="Cerrar"
              className="rounded-control p-1.5 text-text-muted hover:bg-black/5 focus-visible:outline-none focus-visible:shadow-focus"
              onClick={() => setClearDialogOpen(false)}
              type="button">
              <X aria-hidden="true" size={18} />
            </button>
          </div>
          <div className="p-5">
            <div className="rounded-control border border-red-200 bg-red-50 p-3 text-[12px] text-danger">
              <p className="m-0 font-extrabold">Esta acción no se puede deshacer.</p>
              <p className="mt-1 mb-0 leading-5">
                Se eliminarán permanentemente todas las conversaciones guardadas ({ai.state.conversations.length}{' '}
                {ai.state.conversations.length === 1 ? 'conversación' : 'conversaciones'}) y todo su historial de mensajes.
              </p>
            </div>
            <p className="mt-3 mb-5 text-[12.5px] leading-5 text-text-muted">
              Una vez limpio el historial, comenzarás con una pantalla en blanco lista para nuevas consultas.
            </p>
            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <button
                className="inline-flex h-10 items-center justify-center rounded-control border border-border bg-white px-4 text-[13px] font-bold text-text hover:bg-bg focus-visible:outline-none focus-visible:shadow-focus"
                data-dialog-initial-focus
                onClick={() => setClearDialogOpen(false)}
                type="button">
                Cancelar
              </button>
              <button
                className="inline-flex h-10 items-center justify-center gap-2 rounded-control bg-danger px-4 text-[13px] font-bold text-white hover:bg-danger/90 focus-visible:outline-none focus-visible:shadow-focus disabled:opacity-60"
                disabled={ai.mutationsDisabled}
                onClick={() => {
                  ai.clearConversations();
                  setClearDialogOpen(false);
                }}
                type="button">
                <Trash2 aria-hidden="true" size={15} />
                Sí, limpiar todo
              </button>
            </div>
          </div>
        </div>
      </OverlayDialog>
    </div>
  );
}

export function AutoClickAiPage() {
  return (
    <DashboardAiProvider>
      <AutoClickAiPageContent />
    </DashboardAiProvider>
  );
}
