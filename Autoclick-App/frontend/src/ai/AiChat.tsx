import {
  Blocks,
  Check,
  CircleStop,
  Edit3,
  FileSpreadsheet,
  Loader2,
  MessageSquarePlus,
  MousePointerClick,
  RefreshCw,
  Search,
  Send,
  Sparkles,
  Trash2,
  Wifi,
  WifiOff,
} from 'lucide-react';
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import {
  lazy,
  Suspense,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from 'react';
import { useAi } from '@/ai/AiProvider';
import { aiBotDraftSchema } from '@/ai/botDraft';
import { DashboardConversationMenu } from '@/ai/DashboardConversationMenu';
import { ConversationOptionsMenu } from '@/ai/EditorConversationMenu';
import {
  AI_MAX_MESSAGE_CODE_POINTS,
  type AiConversation,
  type AiEditorContext,
  type AiHealth,
  type AiMessageMetrics,
  type AiMessage,
} from '@/ai/types';
import { Alert } from '@/components/Alert';
import { Mascot } from '@/components/Mascot';
import { ToastViewport, useToast } from '@/components/Toast';
import { easeOutExpo } from '@/lib/motion';
import starterPrompts from '@/ai/starterPrompts.json';

const AssistantMarkdown = lazy(() =>
  import('@/ai/AssistantMarkdown').then((module) => ({ default: module.AssistantMarkdown }))
);

type ChatProps = {
  compact?: boolean;
  getEditorContext?: () => AiEditorContext;
};

const STARTER_ICONS: Record<string, typeof Sparkles> = {
  automation: Sparkles,
  catalog: Blocks,
  excel: FileSpreadsheet,
  mouseKeyboard: MousePointerClick,
};
const SUGGESTED_PROMPTS = starterPrompts.map((prompt) => ({
  ...prompt,
  icon: STARTER_ICONS[prompt.id] ?? Sparkles,
}));

export function ConversationList({
  compact = false,
  editor = false,
  onAfterSelect,
}: {
  compact?: boolean;
  editor?: boolean;
  onAfterSelect?: () => void;
}) {
  const ai = useAi();
  const [query, setQuery] = useState('');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [title, setTitle] = useState('');
  const [renameError, setRenameError] = useState(false);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const titleInputRef = useRef<HTMLInputElement>(null);
  const { toast, show: showToast, dismiss: dismissToast } = useToast();
  const conversations = ai.state.conversations.filter((conversation) =>
    conversation.title.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())
  );
  const activeConversation = ai.activeConversation;
  const atLimit = ai.state.conversations.length >= ai.maximumConversations;

  useEffect(() => {
    if (!editingId) return;
    titleInputRef.current?.focus();
    titleInputRef.current?.select();
  }, [editingId]);

  function startRename(conversation: AiConversation) {
    setEditingId(conversation.id);
    setTitle(conversation.title);
    setRenameError(false);
  }

  function cancelRename() {
    setEditingId(null);
    setRenameError(false);
  }

  function submitRename(conversation: AiConversation) {
    const trimmedTitle = title.trim();
    if (!trimmedTitle) {
      setRenameError(true);
      titleInputRef.current?.focus();
      return;
    }
    ai.renameConversation(conversation.id, trimmedTitle);
    setEditingId(null);
    setRenameError(false);
  }

  if (editor) {
    return (
      <section
        aria-label="Historial de conversaciones"
        className="relative flex min-h-0 flex-1 flex-col bg-blue-50/20 p-3">
        <label className="relative block">
          <Search
            aria-hidden="true"
            className="absolute top-2.5 left-2.5 text-text-muted"
            size={16}
          />
          <span className="sr-only">Buscar conversaciones</span>
          <input
            aria-label="Buscar conversaciones"
            className="field-control h-9 w-full rounded-control bg-bg pr-3 pl-8 transition-colors"
            onChange={(event) => setQuery(event.target.value)}
            ref={searchInputRef}
            type="search"
            value={query}
          />
        </label>
        <div className="mt-2 min-h-0 flex-1 space-y-1 overflow-y-auto">
          {conversations.length ? (
            conversations.map((conversation) => (
              <div
                className={`group relative rounded-control border p-2 transition-colors ${conversation.id === ai.state.activeConversationId ? 'border-blue-200 bg-blue-50' : 'border-transparent hover:bg-bg'}`}
                key={conversation.id}>
                {editingId === conversation.id ? (
                  <form
                    className="flex flex-col gap-1.5"
                    onSubmit={(event) => {
                      event.preventDefault();
                      submitRename(conversation);
                    }}>
                    <input
                      aria-invalid={renameError}
                      aria-label="Nombre de la conversación"
                      className="field-control min-w-0 flex-1 rounded-control px-2 py-1 text-[12px]"
                      maxLength={80}
                      onChange={(event) => {
                        setTitle(event.target.value);
                        if (renameError) setRenameError(false);
                      }}
                      onKeyDown={(event) => {
                        if (event.key !== 'Escape') return;
                        event.preventDefault();
                        event.stopPropagation();
                        cancelRename();
                      }}
                      ref={titleInputRef}
                      value={title}
                    />
                    {renameError ? (
                      <span className="text-[10px] font-bold text-danger">
                        El nombre no puede estar vacío.
                      </span>
                    ) : null}
                    <div className="flex justify-end gap-1">
                      <button
                        className="rounded-control px-2 py-1 text-[11px] font-bold text-text-muted hover:bg-bg focus-visible:outline-none focus-visible:shadow-focus"
                        onClick={cancelRename}
                        type="button">
                        Cancelar
                      </button>
                      <button
                        aria-label="Guardar nombre"
                        className="flex items-center gap-1 rounded-control bg-primary px-2 py-1 text-[11px] font-bold text-white hover:bg-primary-hover focus-visible:outline-none focus-visible:shadow-focus"
                        type="submit">
                        <Check aria-hidden="true" size={13} />
                        Guardar
                      </button>
                    </div>
                  </form>
                ) : (
                  <div className="flex items-center gap-1">
                    <button
                      className="min-w-0 flex-1 truncate text-left text-[12px] font-bold focus-visible:outline-none focus-visible:shadow-focus disabled:opacity-50"
                      disabled={ai.mutationsDisabled}
                      onClick={() => {
                        ai.selectConversation(conversation.id);
                        onAfterSelect?.();
                      }}
                      title={conversation.title}
                      type="button">
                      {conversation.title}
                    </button>
                    <ConversationOptionsMenu
                      canDelete={ai.canDeleteConversation}
                      conversation={conversation}
                      disabled={ai.mutationsDisabled}
                      onDelete={() => {
                        ai.deleteConversation(conversation.id);
                        window.requestAnimationFrame(() => searchInputRef.current?.focus());
                      }}
                      onRenameStart={() => startRename(conversation)}
                    />
                  </div>
                )}
              </div>
            ))
          ) : query.trim() ? (
            <p className="px-2 text-[12px] text-text-muted">No hay conversaciones que coincidan.</p>
          ) : (
            <div className="grid place-items-center gap-2 px-2 py-6 text-center">
              <Mascot size={48} state="idle" />
              <p className="m-0 text-[12px] font-bold text-text-muted">
                Todavía no tenés conversaciones.
              </p>
            </div>
          )}
        </div>
      </section>
    );
  }

  if (!compact) {
    return (
      <section
        aria-label="Historial de conversaciones"
        className="relative flex min-h-0 flex-1 flex-col bg-blue-50/20 p-3">
        <label className="relative block">
          <Search
            aria-hidden="true"
            className="absolute top-2.5 left-2.5 text-text-muted"
            size={16}
          />
          <span className="sr-only">Buscar conversaciones</span>
          <input
            aria-label="Buscar conversaciones"
            className="field-control h-9 w-full rounded-control bg-bg pr-3 pl-8 transition-colors"
            onChange={(event) => setQuery(event.target.value)}
            ref={searchInputRef}
            type="search"
            value={query}
          />
        </label>
        <div className="mt-2 min-h-0 flex-1 space-y-1 overflow-y-auto">
          {conversations.length ? (
            conversations.map((conversation) => (
              <div
                className={`group relative rounded-control border p-2 transition-colors ${conversation.id === ai.state.activeConversationId ? 'border-blue-200 bg-blue-50' : 'border-transparent hover:bg-bg'}`}
                key={conversation.id}>
                {editingId === conversation.id ? (
                  <form
                    className="flex flex-col gap-1.5"
                    onSubmit={(event) => {
                      event.preventDefault();
                      submitRename(conversation);
                    }}>
                    <input
                      aria-invalid={renameError}
                      aria-label="Nombre de la conversación"
                      className="field-control min-w-0 flex-1 rounded-control px-2 py-1 text-[12px]"
                      maxLength={80}
                      onChange={(event) => {
                        setTitle(event.target.value);
                        if (renameError) setRenameError(false);
                      }}
                      onKeyDown={(event) => {
                        if (event.key !== 'Escape') return;
                        event.preventDefault();
                        event.stopPropagation();
                        cancelRename();
                      }}
                      ref={titleInputRef}
                      value={title}
                    />
                    {renameError ? (
                      <span className="text-[10px] font-bold text-danger">
                        El nombre no puede estar vacío.
                      </span>
                    ) : null}
                    <div className="flex justify-end gap-1">
                      <button
                        className="rounded-control px-2 py-1 text-[11px] font-bold text-text-muted hover:bg-bg focus-visible:outline-none focus-visible:shadow-focus"
                        onClick={cancelRename}
                        type="button">
                        Cancelar
                      </button>
                      <button
                        aria-label="Guardar nombre"
                        className="flex items-center gap-1 rounded-control bg-primary px-2 py-1 text-[11px] font-bold text-white hover:bg-primary-hover focus-visible:outline-none focus-visible:shadow-focus"
                        type="submit">
                        <Check aria-hidden="true" size={13} />
                        Guardar
                      </button>
                    </div>
                  </form>
                ) : (
                  <div className="flex items-center gap-1">
                    <button
                      className="min-w-0 flex-1 truncate text-left text-[12px] font-bold focus-visible:outline-none focus-visible:shadow-focus disabled:opacity-50"
                      disabled={ai.mutationsDisabled}
                      onClick={() => {
                        ai.selectConversation(conversation.id);
                        onAfterSelect?.();
                      }}
                      title={conversation.title}
                      type="button">
                      {conversation.title}
                    </button>
                    <DashboardConversationMenu
                      canDelete={ai.canDeleteConversation}
                      conversation={conversation}
                      disabled={ai.mutationsDisabled}
                      onDelete={() => {
                        ai.deleteConversation(conversation.id);
                        window.requestAnimationFrame(() => searchInputRef.current?.focus());
                      }}
                      onRenameStart={() => startRename(conversation)}
                      onToast={(message, tone) => showToast(message, { tone })}
                    />
                  </div>
                )}
              </div>
            ))
          ) : query.trim() ? (
            <p className="px-2 text-[12px] text-text-muted">No hay conversaciones que coincidan.</p>
          ) : (
            <div className="grid place-items-center gap-2 px-2 py-6 text-center">
              <Mascot float={false} interactive={false} size={48} state="idle" />
              <p className="m-0 text-[12px] font-bold text-text-muted">
                Todavía no tenés conversaciones.
              </p>
            </div>
          )}
        </div>
        <ToastViewport onDismiss={dismissToast} toast={toast} />
      </section>
    );
  }

  return (
    <section
      aria-label="Conversaciones"
      className={`flex min-h-0 flex-col ${compact ? 'border-b border-border p-3' : 'max-h-64 border-b border-border bg-surface p-3 lg:h-full lg:max-h-none lg:border-r lg:border-b-0'}`}>
      <button
        className="flex h-10 items-center justify-center gap-2 rounded-control bg-primary px-3 font-bold text-white hover:bg-primary-hover focus-visible:outline-none focus-visible:shadow-focus disabled:cursor-not-allowed disabled:opacity-50"
        disabled={atLimit || ai.mutationsDisabled}
        onClick={() => ai.createConversation()}
        title={atLimit ? `Máximo de ${ai.maximumConversations} conversaciones` : undefined}
        type="button">
        <MessageSquarePlus aria-hidden="true" size={17} />
        Nueva conversación
      </button>
      {compact ? (
        <div className="mt-2 text-[11px] font-bold text-text-muted">
          <label className="block" htmlFor="ai-conversation-select">
            Conversación
          </label>
          <select
            className="field-control mt-1 h-9 w-full rounded-control bg-white px-2 text-text disabled:bg-bg"
            disabled={ai.mutationsDisabled}
            id="ai-conversation-select"
            onChange={(event) => ai.selectConversation(event.target.value)}
            value={ai.state.activeConversationId ?? ''}>
            <option disabled value="">
              Sin conversaciones
            </option>
            {ai.state.conversations.map((conversation) => (
              <option key={conversation.id} value={conversation.id}>
                {conversation.title}
              </option>
            ))}
          </select>
          {activeConversation ? (
            editingId === activeConversation.id ? (
              <form
                className="mt-2 flex gap-1"
                onSubmit={(event) => {
                  event.preventDefault();
                  ai.renameConversation(activeConversation.id, title);
                  setEditingId(null);
                }}>
                <input
                  aria-label="Nombre de la conversación"
                  autoFocus
                  className="field-control h-8 min-w-0 flex-1 rounded px-2"
                  maxLength={80}
                  onChange={(event) => setTitle(event.target.value)}
                  value={title}
                />
                <button
                  aria-label="Guardar nombre"
                  className="rounded p-1 focus-visible:shadow-focus"
                  type="submit">
                  <Check aria-hidden="true" size={15} />
                </button>
              </form>
            ) : (
              <span className="mt-2 flex justify-end gap-1">
                <button
                  aria-label={`Renombrar ${activeConversation.title}`}
                  className="rounded p-1 text-text-muted hover:text-primary focus-visible:shadow-focus disabled:opacity-50"
                  disabled={ai.mutationsDisabled}
                  onClick={() => {
                    setEditingId(activeConversation.id);
                    setTitle(activeConversation.title);
                  }}
                  type="button">
                  <Edit3 aria-hidden="true" size={14} />
                </button>
                <button
                  aria-label={`Eliminar ${activeConversation.title}`}
                  className="rounded p-1 text-text-muted hover:text-danger focus-visible:shadow-focus disabled:opacity-50"
                  disabled={!ai.canDeleteConversation}
                  onClick={() => ai.deleteConversation(activeConversation.id)}
                  type="button">
                  <Trash2 aria-hidden="true" size={14} />
                </button>
              </span>
            )
          ) : null}
          {atLimit ? (
            <span className="mt-1 block text-[10px] font-normal text-text-muted">
              Máximo de {ai.maximumConversations} conversaciones.
            </span>
          ) : null}
        </div>
      ) : (
        <>
          <label className="relative mt-3 block">
            <Search
              aria-hidden="true"
              className="absolute top-2.5 left-2.5 text-text-muted"
              size={16}
            />
            <span className="sr-only">Buscar conversaciones</span>
            <input
              aria-label="Buscar conversaciones"
              className="field-control h-9 w-full rounded-control bg-bg pr-3 pl-8"
              onChange={(event) => setQuery(event.target.value)}
              type="search"
              value={query}
            />
          </label>
          <div className="mt-2 min-h-0 flex-1 space-y-1 overflow-y-auto">
            {conversations.length ? (
              conversations.map((conversation) => (
                <div
                  className={`group relative rounded-control border p-2 transition-colors ${conversation.id === ai.state.activeConversationId ? 'border-blue-200 bg-blue-50' : 'border-transparent hover:bg-bg'}`}
                  key={conversation.id}>
                  {editingId === conversation.id ? (
                    <form
                      className="flex flex-col gap-1.5"
                      onSubmit={(event) => {
                        event.preventDefault();
                        submitRename(conversation);
                      }}>
                      <input
                        aria-invalid={renameError}
                        aria-label="Nombre de la conversación"
                        className="field-control min-w-0 flex-1 rounded-control px-2 py-1 text-[12px]"
                        maxLength={80}
                        onChange={(event) => {
                          setTitle(event.target.value);
                          if (renameError) setRenameError(false);
                        }}
                        onKeyDown={(event) => {
                          if (event.key !== 'Escape') return;
                          event.preventDefault();
                          event.stopPropagation();
                          cancelRename();
                        }}
                        ref={titleInputRef}
                        value={title}
                      />
                      {renameError ? (
                        <span className="text-[10px] font-bold text-danger">
                          El nombre no puede estar vacío.
                        </span>
                      ) : null}
                      <div className="flex justify-end gap-1">
                        <button
                          className="rounded-control px-2 py-1 text-[11px] font-bold text-text-muted hover:bg-bg focus-visible:outline-none focus-visible:shadow-focus"
                          onClick={cancelRename}
                          type="button">
                          Cancelar
                        </button>
                        <button
                          aria-label="Guardar nombre"
                          className="flex items-center gap-1 rounded-control bg-primary px-2 py-1 text-[11px] font-bold text-white hover:bg-primary-hover focus-visible:outline-none focus-visible:shadow-focus"
                          type="submit">
                          <Check aria-hidden="true" size={13} />
                          Guardar
                        </button>
                      </div>
                    </form>
                  ) : (
                    <div className="flex items-center gap-1">
                      <button
                        className="min-w-0 flex-1 truncate text-left text-[12px] font-bold focus-visible:outline-none focus-visible:shadow-focus disabled:opacity-50"
                        disabled={ai.mutationsDisabled}
                        onClick={() => {
                          ai.selectConversation(conversation.id);
                          onAfterSelect?.();
                        }}
                        title={conversation.title}
                        type="button">
                        {conversation.title}
                      </button>
                      <DashboardConversationMenu
                        canDelete={ai.canDeleteConversation}
                        conversation={conversation}
                        disabled={ai.mutationsDisabled}
                        onDelete={() => {
                          ai.deleteConversation(conversation.id);
                          window.requestAnimationFrame(() => searchInputRef.current?.focus());
                        }}
                        onRenameStart={() => startRename(conversation)}
                        onToast={(message, tone) => showToast(message, { tone })}
                      />
                    </div>
                  )}
                </div>
              ))
            ) : query.trim() ? (
              <p className="px-2 text-[12px] text-text-muted">
                No hay conversaciones que coincidan.
              </p>
            ) : (
              <div className="grid place-items-center gap-2 px-2 py-6 text-center">
                <Mascot float={false} interactive={false} size={48} state="idle" />
                <p className="m-0 text-[12px] font-bold text-text-muted">
                  Todavía no tenés conversaciones.
                </p>
              </div>
            )}
          </div>
        </>
      )}
    </section>
  );
}

export function AiChat({ compact = false, getEditorContext }: ChatProps) {
  const ai = useAi();
  const [draft, setDraft] = useState('');
  const [justSent, setJustSent] = useState(false);
  const sentTimerRef = useRef<number | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const reduceMotion = Boolean(useReducedMotion());
  const generation =
    ai.state.generation?.conversationId === ai.activeConversation?.id ? ai.state.generation : null;
  const visibleMessages = ai.activeConversation?.messages ?? [];

  useEffect(() => () => {
    if (sentTimerRef.current !== null) window.clearTimeout(sentTimerRef.current);
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView?.({ block: 'end' });
  }, [generation?.assistantContent, visibleMessages.length]);

  useEffect(() => {
    const element = textareaRef.current;
    if (!element) return;
    element.style.height = 'auto';
    element.style.height = `${element.scrollHeight}px`;
  }, [draft]);

  async function submit(text = draft) {
    if (!text.trim() || ai.state.generation) return;
    setJustSent(true);
    if (sentTimerRef.current !== null) window.clearTimeout(sentTimerRef.current);
    sentTimerRef.current = window.setTimeout(() => setJustSent(false), 350);
    const accepted = await ai.sendMessage(text, getEditorContext);
    if (accepted) setDraft('');
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      void submit();
    }
  }

  return (
    <section aria-label="Chat de AutoClick AI" className="flex min-h-0 flex-1 flex-col bg-surface">
      {getEditorContext && !compact ? (
        <div className="border-b border-blue-100 bg-blue-50 px-3 py-2 text-[11px] font-bold text-primary">
          Usando el bot actual como contexto
        </div>
      ) : null}
      {!compact ? <AiHealthStatus health={ai.health} onRetry={ai.retryHealth} /> : null}
      <div
        aria-live="polite"
        aria-relevant="additions text"
        className={`min-h-0 flex-1 overflow-y-auto ${compact ? 'p-3' : 'p-4 sm:p-6'}`}
        role="log">
        {!visibleMessages.length && !generation ? (
          compact ? (
            <motion.div
              animate={{ opacity: 1 }}
              className="grid h-full min-h-0 place-items-center text-center"
              initial={reduceMotion ? { opacity: 1 } : { opacity: 0 }}
              transition={reduceMotion ? { duration: 0 } : { duration: 0.3 }}>
              <div className="max-w-sm">
                <div className="relative mx-auto mb-1.5 grid size-[72px] place-items-center">
                  <span
                    aria-hidden="true"
                    className="absolute -inset-2 rounded-full bg-gradient-to-br from-blue-200/80 to-cyan-200/60 blur-lg"
                  />
                  {reduceMotion ? (
                    <img
                      alt=""
                      className="relative pointer-events-none block w-[72px] select-none"
                      decoding="async"
                      src="/mascot/wave.png"
                    />
                  ) : (
                    <Mascot
                      className="relative"
                      entrance="soft"
                      interactive={false}
                      size={72}
                      state="wave"
                    />
                  )}
                </div>
                <h2 className="m-0 text-base font-extrabold sm:text-lg">
                  ¡Hola! Soy ClickIA, ¿en qué te ayudo?
                </h2>
                <p className="mt-1 text-[12.5px] leading-4 text-text-muted">
                  Consultá sobre bloques, validaciones y cómo armar tu automatización.
                </p>
              </div>
            </motion.div>
          ) : (
            <motion.div
              animate={{ opacity: 1 }}
              className="grid h-full min-h-48 place-items-center text-center"
              initial={reduceMotion ? { opacity: 1 } : { opacity: 0 }}
              transition={reduceMotion ? { duration: 0 } : { duration: 0.3 }}>
              <div className="max-w-xl">
                <div className="relative mx-auto mb-1.5 grid size-[72px] place-items-center">
                  <span
                    aria-hidden="true"
                    className="absolute -inset-2 rounded-full bg-gradient-to-br from-blue-200/80 to-cyan-200/60 blur-lg"
                  />
                  {reduceMotion ? (
                    <img
                      alt=""
                      className="relative pointer-events-none block w-[72px] select-none"
                      decoding="async"
                      src="/mascot/wave.png"
                    />
                  ) : (
                    <Mascot
                      className="relative"
                      entrance="soft"
                      interactive={false}
                      size={72}
                      state="wave"
                    />
                  )}
                </div>
                <h2 className="m-0 text-base font-extrabold sm:text-lg">
                  ¡Hola! Soy ClickIA, ¿en qué te ayudo?
                </h2>
                <p className="mt-1 text-[12.5px] leading-4 text-text-muted">
                  Consultá sobre bloques, validaciones y cómo armar tu automatización.
                </p>
                <div className="mt-4 grid grid-cols-1 gap-2 text-left sm:grid-cols-2">
                  {SUGGESTED_PROMPTS.map((prompt, index) => (
                    <motion.button
                      animate={{ opacity: 1, y: 0 }}
                      className="flex items-center gap-2 rounded-control border border-border bg-white px-3 py-2.5 text-[12px] font-bold text-text shadow-sm transition-colors hover:border-blue-200 hover:bg-blue-50/60 hover:text-primary focus-visible:outline-none focus-visible:shadow-focus"
                      disabled={Boolean(ai.state.generation) || ai.mutationsDisabled}
                      initial={reduceMotion ? { opacity: 1, y: 0 } : { opacity: 0, y: 6 }}
                      key={prompt.label}
                      onClick={() => void submit(prompt.message)}
                      transition={
                        reduceMotion ? { duration: 0 } : { duration: 0.25, delay: 0.05 * index }
                      }
                      type="button"
                      whileHover={reduceMotion ? undefined : { y: -2 }}
                      whileTap={reduceMotion ? undefined : { scale: 0.98 }}>
                      <prompt.icon aria-hidden="true" className="shrink-0 text-primary" size={15} />
                      {prompt.label}
                    </motion.button>
                  ))}
                </div>
              </div>
            </motion.div>
          )
        ) : null}
        <div className="mx-auto flex w-full max-w-3xl flex-col gap-3">
          <AnimatePresence initial={false}>
            {visibleMessages.map((message) => (
              <MessageBubble
                compact={compact}
                content={message.content}
                draft={message.draft}
                interrupted={message.status === 'interrupted'}
                key={message.id}
                metrics={message.metrics}
                reduceMotion={reduceMotion}
                role={message.role}
              />
            ))}
          </AnimatePresence>
          {generation?.phase === 'streaming' && !generation.assistantContent ? (
            <>
              {/* {generation.statusStage ? (
                <p className="m-0 text-[12px] text-text-muted" role="status">
                  Etapa: {generation.statusStage}
                </p>
              ) : null} */}
              <ThinkingStatus
                compact={compact}
                content={generation.thinkingContent}
                reduceMotion={reduceMotion}
              />
            </>
          ) : null}
          {generation?.phase === 'streaming' && generation.assistantContent ? (
            <MessageBubble
              compact={compact}
              content={generation.assistantContent}
              draft={generation.botDraft}
              reduceMotion={reduceMotion}
              role="assistant"
              streaming
            />
          ) : null}
          {generation?.phase === 'connecting' ? (
            compact ? (
              <p className="m-0 flex items-center gap-2 text-[12px] text-text-muted" role="status">
                <motion.span
                  animate={
                    justSent && !reduceMotion
                      ? { rotate: [0, -6, 4, 0], y: [0, -3, 0] }
                      : { rotate: 0, y: 0 }
                  }
                  transition={reduceMotion ? { duration: 0 } : { duration: 0.35, ease: 'easeOut' }}>
                  <Mascot float={false} interactive={false} size={28} state="thinking" />
                </motion.span>
                Conectando con ClickIA…
              </p>
            ) : (
              <p className="m-0 flex items-center gap-2 text-[12px] text-text-muted" role="status">
                {reduceMotion ? (
                  <img
                    alt=""
                    className="pointer-events-none block w-7 select-none"
                    decoding="async"
                    src="/mascot/AutoClick_Robot_Pensando.png"
                  />
                ) : (
                  <motion.span
                    animate={
                      justSent ? { rotate: [0, -6, 4, 0], y: [0, -3, 0] } : { rotate: 0, y: 0 }
                    }
                    transition={{ duration: 0.35, ease: 'easeOut' }}>
                    <Mascot float={false} interactive={false} size={28} state="thinking" />
                  </motion.span>
                )}
                Conectando con ClickIA…
              </p>
            )
          ) : null}
          <div ref={messagesEndRef} />
        </div>
      </div>
      <AnimatePresence initial={false}>
        {ai.state.error ? (
          compact ? (
            <div className="px-3 pt-2">
              <Alert className="mb-0" shake={false}>
                <span>{ai.state.error}</span>
                {ai.syncStatus === 'unsynced' ? (
                  <span className="mt-1 flex flex-wrap gap-x-3 gap-y-1">
                    <button
                      className="font-bold underline"
                      onClick={ai.retryPersistence}
                      type="button">
                      Reintentar
                    </button>
                    <button
                      className="font-bold underline"
                      onClick={ai.pruneUnsyncedChanges}
                      type="button">
                      Reducir historial
                    </button>
                    <button
                      className="font-bold underline"
                      onClick={ai.discardUnsyncedChanges}
                      type="button">
                      Descartar cambios
                    </button>
                  </span>
                ) : null}
              </Alert>
            </div>
          ) : (
            <div className="px-4 pt-3">
              <Alert className="mb-0">
                <span>{ai.state.error}</span>
                {ai.syncStatus === 'unsynced' ? (
                  <span className="mt-1 flex flex-wrap gap-x-3 gap-y-1">
                    <button
                      className="font-bold underline"
                      onClick={ai.retryPersistence}
                      type="button">
                      Reintentar
                    </button>
                    <button
                      className="font-bold underline"
                      onClick={ai.pruneUnsyncedChanges}
                      type="button">
                      Reducir historial
                    </button>
                    <button
                      className="font-bold underline"
                      onClick={ai.discardUnsyncedChanges}
                      type="button">
                      Descartar cambios
                    </button>
                  </span>
                ) : null}
              </Alert>
            </div>
          )
        ) : null}
      </AnimatePresence>
      <form
        className={
          compact ? 'shrink-0 bg-surface px-3 pt-1.5 pb-3' : 'shrink-0 bg-surface px-4 pt-2 pb-4'
        }
        onSubmit={(event: FormEvent) => {
          event.preventDefault();
          void submit();
        }}>
        <label className="sr-only" htmlFor={compact ? 'ai-editor-message' : 'ai-page-message'}>
          Mensaje para AutoClick AI
        </label>
        {compact ? (
          <div className="field-shell relative rounded-panel bg-white transition-colors duration-200 ease-out">
            <textarea
              className="field-inner max-h-36 min-h-[46px] w-full resize-none overflow-y-auto rounded-panel bg-transparent py-3 pr-12 pl-3.5 leading-5 text-[13px] text-text placeholder:text-text-soft disabled:cursor-not-allowed disabled:text-text-muted"
              disabled={Boolean(ai.state.generation) || ai.mutationsDisabled}
              id="ai-editor-message"
              maxLength={AI_MAX_MESSAGE_CODE_POINTS * 2}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Escribí tu consulta…"
              ref={textareaRef}
              rows={1}
              value={draft}
            />
            <div className="absolute right-2 bottom-2">
              <AnimatePresence initial={false} mode="wait">
                {ai.state.generation ? (
                  <motion.button
                    animate={{ opacity: 1, scale: 1, rotate: 0 }}
                    aria-label="Detener"
                    className="relative grid size-8 shrink-0 place-items-center rounded-full bg-danger text-white focus-visible:outline-none focus-visible:shadow-focus"
                    exit={
                      reduceMotion
                        ? { opacity: 1, scale: 1, rotate: 0 }
                        : { opacity: 0, scale: 0.6, rotate: 12 }
                    }
                    initial={
                      reduceMotion
                        ? { opacity: 1, scale: 1, rotate: 0 }
                        : { opacity: 0, scale: 0.6, rotate: -12 }
                    }
                    key="stop"
                    onClick={ai.stopGeneration}
                    title="Detener"
                    transition={
                      reduceMotion ? { duration: 0 } : { duration: 0.18, ease: easeOutExpo }
                    }
                    type="button"
                    whileHover={reduceMotion ? undefined : { scale: 1.08 }}
                    whileTap={reduceMotion ? undefined : { scale: 0.92 }}>
                    {!reduceMotion ? (
                      <motion.span
                        animate={{ scale: 1.9, opacity: 0 }}
                        aria-hidden="true"
                        className="absolute inset-0 rounded-full bg-danger/60"
                        initial={{ scale: 1, opacity: 0.55 }}
                        transition={{ duration: 1.4, repeat: Infinity, ease: 'easeOut' }}
                      />
                    ) : null}
                    <CircleStop aria-hidden="true" className="relative" size={15} />
                  </motion.button>
                ) : (
                  <motion.button
                    animate={{ opacity: 1, scale: 1, rotate: 0 }}
                    aria-label="Enviar mensaje"
                    className={`grid size-8 shrink-0 place-items-center rounded-full bg-primary text-white transition-[opacity,box-shadow] duration-150 focus-visible:outline-none focus-visible:shadow-focus ${draft.trim() && !ai.mutationsDisabled ? 'hover:bg-primary-hover hover:shadow-glow-primary' : 'opacity-35'}`}
                    disabled={!draft.trim() || ai.mutationsDisabled}
                    exit={
                      reduceMotion
                        ? { opacity: 1, scale: 1, rotate: 0 }
                        : { opacity: 0, scale: 0.6, rotate: -12 }
                    }
                    initial={
                      reduceMotion
                        ? { opacity: 1, scale: 1, rotate: 0 }
                        : { opacity: 0, scale: 0.6, rotate: 12 }
                    }
                    key="send"
                    transition={
                      reduceMotion ? { duration: 0 } : { duration: 0.18, ease: easeOutExpo }
                    }
                    type="submit"
                    whileHover={
                      reduceMotion || !draft.trim() || ai.mutationsDisabled
                        ? undefined
                        : { scale: 1.08 }
                    }
                    whileTap={
                      reduceMotion || !draft.trim() || ai.mutationsDisabled
                        ? undefined
                        : { scale: 0.92 }
                    }>
                    <Send aria-hidden="true" size={14} />
                  </motion.button>
                )}
              </AnimatePresence>
            </div>
          </div>
        ) : (
          <div className="field-shell relative rounded-panel bg-white transition-colors duration-200 ease-out">
            <textarea
              className="field-inner max-h-36 min-h-[46px] w-full resize-none overflow-y-auto rounded-panel bg-transparent py-3 pr-12 pl-3.5 leading-5 text-[13px] text-text placeholder:text-text-soft disabled:cursor-not-allowed disabled:text-text-muted"
              disabled={Boolean(ai.state.generation) || ai.mutationsDisabled}
              id="ai-page-message"
              maxLength={AI_MAX_MESSAGE_CODE_POINTS * 2}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Escribí tu consulta…"
              ref={textareaRef}
              rows={1}
              value={draft}
            />
            <div className="absolute right-2 bottom-2">
              <AnimatePresence initial={false} mode="wait">
                {ai.state.generation ? (
                  <motion.button
                    animate={{ opacity: 1, scale: 1, rotate: 0 }}
                    aria-label="Detener"
                    className="relative grid size-8 shrink-0 place-items-center rounded-full bg-danger text-white focus-visible:outline-none focus-visible:shadow-focus"
                    exit={
                      reduceMotion
                        ? { opacity: 1, scale: 1, rotate: 0 }
                        : { opacity: 0, scale: 0.6, rotate: 12 }
                    }
                    initial={
                      reduceMotion
                        ? { opacity: 1, scale: 1, rotate: 0 }
                        : { opacity: 0, scale: 0.6, rotate: -12 }
                    }
                    key="stop"
                    onClick={ai.stopGeneration}
                    title="Detener"
                    transition={
                      reduceMotion ? { duration: 0 } : { duration: 0.18, ease: easeOutExpo }
                    }
                    type="button"
                    whileHover={reduceMotion ? undefined : { scale: 1.08 }}
                    whileTap={reduceMotion ? undefined : { scale: 0.92 }}>
                    {!reduceMotion ? (
                      <motion.span
                        animate={{ scale: 1.9, opacity: 0 }}
                        aria-hidden="true"
                        className="absolute inset-0 rounded-full bg-danger/60"
                        initial={{ scale: 1, opacity: 0.55 }}
                        transition={{ duration: 1.4, repeat: Infinity, ease: 'easeOut' }}
                      />
                    ) : null}
                    <CircleStop aria-hidden="true" className="relative" size={15} />
                  </motion.button>
                ) : (
                  <motion.button
                    animate={{ opacity: 1, scale: 1, rotate: 0 }}
                    aria-label="Enviar mensaje"
                    className={`grid size-8 shrink-0 place-items-center rounded-full bg-primary text-white transition-[opacity,box-shadow] duration-150 focus-visible:outline-none focus-visible:shadow-focus ${draft.trim() && !ai.mutationsDisabled ? 'hover:bg-primary-hover hover:shadow-glow-primary' : 'opacity-35'}`}
                    disabled={!draft.trim() || ai.mutationsDisabled}
                    exit={
                      reduceMotion
                        ? { opacity: 1, scale: 1, rotate: 0 }
                        : { opacity: 0, scale: 0.6, rotate: -12 }
                    }
                    initial={
                      reduceMotion
                        ? { opacity: 1, scale: 1, rotate: 0 }
                        : { opacity: 0, scale: 0.6, rotate: 12 }
                    }
                    key="send"
                    transition={
                      reduceMotion ? { duration: 0 } : { duration: 0.18, ease: easeOutExpo }
                    }
                    type="submit"
                    whileHover={
                      reduceMotion || !draft.trim() || ai.mutationsDisabled
                        ? undefined
                        : { scale: 1.08 }
                    }
                    whileTap={
                      reduceMotion || !draft.trim() || ai.mutationsDisabled
                        ? undefined
                        : { scale: 0.92 }
                    }>
                    <Send aria-hidden="true" size={14} />
                  </motion.button>
                )}
              </AnimatePresence>
            </div>
          </div>
        )}
      </form>
      {ai.creationError ? (
        compact ? (
          <div className="px-3 pt-2 pb-1">
            <Alert className="mb-0" shake={false}>
              {ai.creationError}
            </Alert>
          </div>
        ) : (
          <div className="px-4 pt-3 pb-1">
            <Alert className="mb-0">{ai.creationError}</Alert>
          </div>
        )
      ) : null}
    </section>
  );
}

function AiHealthStatus({ health, onRetry }: { health: AiHealth; onRetry(): void }) {
  const reduceMotion = Boolean(useReducedMotion());
  const unavailable =
    health.status === 'api-unavailable' ||
    health.status === 'ollama-unavailable' ||
    health.status === 'model-unavailable';
  let message;
  if (health.status === 'checking') {
    message = 'Comprobando el servicio local…';
  } else if (health.status === 'ready') {
    message = 'ClickIA listo para responder.';
  } else if (health.status === 'api-unavailable') {
    message = (
      <>
        AutoClick AI no responde en <code className="break-all font-mono">{health.url}</code>.
        Iniciá Autoclick-IA y volvé a intentar.
      </>
    );
  } else if (health.status === 'ollama-unavailable') {
    message = (
      <>
        Ollama no responde. Ejecutá <code className="font-mono">ollama serve</code> y volvé a
        intentar.
      </>
    );
  } else {
    message =
      'El modelo de AI no está instalado. Revisá la instalación de Autoclick-IA y volvé a intentar.';
  }

  const StatusIcon = health.status === 'ready' ? Wifi : unavailable ? WifiOff : Loader2;

  return (
    <motion.div
      animate={{ opacity: 1 }}
      aria-label="Estado de AutoClick AI"
      className={`relative flex shrink-0 flex-wrap items-center gap-x-2.5 gap-y-1 overflow-hidden border-b px-4 py-2 text-[11px] ${
        health.status === 'ready'
          ? 'border-green-100 bg-gradient-to-r from-green-50 to-emerald-50/40 text-success'
          : unavailable
            ? 'border-amber-200 bg-gradient-to-r from-amber-50 to-orange-50/40 text-amber-900'
            : 'border-border bg-bg text-text-muted'
      }`}
      initial={reduceMotion ? { opacity: 1 } : { opacity: 0 }}
      transition={reduceMotion ? { duration: 0 } : { duration: 0.25 }}
      role="status">
      <span
        aria-hidden="true"
        className={`relative grid size-6 shrink-0 place-items-center rounded-full ${
          health.status === 'ready'
            ? 'bg-success/15 text-success'
            : unavailable
              ? 'bg-amber-500/15 text-amber-700'
              : 'bg-text-muted/15 text-text-muted'
        }`}>
        {health.status === 'ready' ? (
          reduceMotion ? (
            <img
              alt=""
              className="pointer-events-none block w-[22px] select-none"
              decoding="async"
              src="/mascot/face.png"
            />
          ) : (
            <>
              <motion.span
                animate={{ scale: 1.9, opacity: 0 }}
                className="absolute inset-0 rounded-full bg-success/50"
                initial={{ scale: 1, opacity: 0.6 }}
                transition={{ duration: 1.6, repeat: Infinity, ease: 'easeOut' }}
              />
              <Mascot float={false} interactive={false} size={22} state="face" />
            </>
          )
        ) : (
          <StatusIcon
            aria-hidden="true"
            className={health.status === 'checking' && !reduceMotion ? 'animate-spin' : ''}
            size={12}
          />
        )}
      </span>
      <span className="min-w-0 flex-1 leading-4">{message}</span>
      {unavailable ? (
        <motion.button
          aria-label="Reintentar conexión con AutoClick AI"
          className="inline-flex shrink-0 items-center gap-1 rounded-full bg-white/70 px-2 py-1 font-bold text-primary hover:bg-white focus-visible:outline-none focus-visible:shadow-focus"
          onClick={onRetry}
          type="button"
          whileHover={reduceMotion ? undefined : { scale: 1.05 }}
          whileTap={reduceMotion ? undefined : { scale: 0.95 }}>
          <RefreshCw aria-hidden="true" size={13} />
          Reintentar
        </motion.button>
      ) : null}
    </motion.div>
  );
}

function MessageBubble({
  compact,
  reduceMotion,
  role,
  content,
  interrupted = false,
  streaming = false,
  metrics,
  draft,
}: {
  compact: boolean;
  reduceMotion: boolean;
  role: 'user' | 'assistant';
  content: string;
  interrupted?: boolean;
  streaming?: boolean;
  metrics?: AiMessageMetrics;
  draft?: AiMessage['draft'];
}) {
  const ai = useAi();
  const parsedDraft = draft ? aiBotDraftSchema.safeParse(draft) : undefined;
  const validDraft = parsedDraft?.success ? parsedDraft.data : undefined;
  const contentNode = (
    <>
      {role === 'assistant' ? (
        <Suspense fallback={<span className="whitespace-pre-wrap">{content}</span>}>
          <AssistantMarkdown content={content} />
        </Suspense>
      ) : (
        content
      )}
      {streaming ? (
        <span
          className={`ml-1 inline-block h-3 w-1 bg-primary ${reduceMotion ? '' : 'animate-pulse'}`}
          aria-hidden="true"
        />
      ) : null}
      {interrupted ? (
        <span className="mt-1 block text-[10px] opacity-70">Respuesta detenida</span>
      ) : null}
      {role === 'assistant' && metrics ? (
        <span
          className="mt-1.5 block border-t border-slate-200 pt-1 text-[10px] font-medium text-text-muted"
          data-testid="assistant-metrics">
          {formatMetrics(metrics)}
        </span>
      ) : null}
      {role === 'assistant' && validDraft ? (
        <div className="mt-2 border-t border-slate-200 pt-2">
          <p className="m-0 text-[11px] font-bold text-text-muted">
            Borrador de bot: {validDraft.name}
          </p>
          <p className="mt-1 mb-2 text-[11px] text-text-muted">{validDraft.summary}</p>
          {compact ? (
            <button
              className="rounded-control bg-primary px-3 py-1.5 text-[12px] font-bold text-white hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-50"
              disabled={Boolean(ai.creatingDraft)}
              onClick={() => void ai.createBotFromDraft(validDraft)}
              type="button">
              {ai.creatingDraft === draft ? 'Creando…' : 'Crear Bot'}
            </button>
          ) : (
            <motion.button
              className="rounded-control bg-primary px-3 py-1.5 text-[12px] font-bold text-white hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-50"
              disabled={Boolean(ai.creatingDraft)}
              onClick={() => void ai.createBotFromDraft(validDraft)}
              type="button"
              whileHover={reduceMotion || ai.creatingDraft ? undefined : { scale: 1.03 }}
              whileTap={reduceMotion || ai.creatingDraft ? undefined : { scale: 0.96 }}>
              {ai.creatingDraft === draft ? 'Creando…' : 'Crear Bot'}
            </motion.button>
          )}
        </div>
      ) : null}
    </>
  );
  const props = {
    'aria-label': role === 'user' ? 'Tu mensaje' : 'Respuesta de AutoClick AI',
    className: `max-w-[88%] rounded-panel px-3 py-2.5 text-[13px] leading-5 ${role === 'user' ? 'self-end whitespace-pre-wrap bg-primary text-white' : 'self-start border border-border bg-bg text-text'}`,
  };
  return compact ? (
    <motion.article
      {...props}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      initial={reduceMotion ? { opacity: 1, y: 0, scale: 1 } : { opacity: 0, y: 10, scale: 0.98 }}
      transition={reduceMotion ? { duration: 0 } : { duration: 0.25, ease: easeOutExpo }}>
      {contentNode}
    </motion.article>
  ) : (
    <motion.article
      {...props}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      initial={reduceMotion ? { opacity: 1, y: 0, scale: 1 } : { opacity: 0, y: 10, scale: 0.98 }}
      transition={reduceMotion ? { duration: 0 } : { duration: 0.25, ease: easeOutExpo }}>
      {contentNode}
    </motion.article>
  );
}

function formatMetrics(metrics: AiMessageMetrics): string {
  const seconds = (metrics.totalTimeMs / 1_000).toFixed(2).replace('.', ',');
  const input =
    metrics.inputTokens === null
      ? '— tokens de entrada'
      : `${metrics.inputTokens.toLocaleString('es-AR')} tokens de entrada`;
  const output =
    metrics.outputTokens === null
      ? '— tokens de salida'
      : `${metrics.outputTokens.toLocaleString('es-AR')} tokens de salida`;
  return `${seconds} s · ${input} · ${output}`;
}

function ThinkingStatus({
  compact,
  content,
  reduceMotion,
}: {
  compact: boolean;
  content: string;
  reduceMotion: boolean;
}) {
  const latestLine = content
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .at(-1);
  return compact ? (
    <div className="flex max-w-full items-center gap-2" role="status">
      <Mascot float={false} interactive={false} size={46} state="thinking" />
      <p className="m-0 flex min-w-0 flex-1 items-center gap-1.5 truncate text-[12px] text-text-muted">
        <span className="truncate">Pensando{latestLine ? `: ${latestLine}` : ''}</span>
        <span aria-hidden="true" className="flex shrink-0 gap-0.5">
          {[0, 1, 2].map((index) =>
            reduceMotion ? (
              <span className="size-1 rounded-full bg-text-muted" key={index} />
            ) : (
              <motion.span
                animate={{ opacity: [0.25, 1, 0.25] }}
                className="size-1 rounded-full bg-text-muted"
                key={index}
                transition={{ duration: 1.1, repeat: Infinity, delay: index * 0.15 }}
              />
            )
          )}
        </span>
      </p>
    </div>
  ) : (
    <div className="flex max-w-full items-center gap-2" role="status">
      {reduceMotion ? (
        <img
          alt=""
          className="pointer-events-none block w-[46px] select-none"
          decoding="async"
          src="/mascot/AutoClick_Robot_Pensando.png"
        />
      ) : (
        <Mascot float={false} interactive={false} size={46} state="thinking" />
      )}
      <p className="m-0 flex min-w-0 flex-1 items-center gap-1.5 truncate text-[12px] text-text-muted">
        <span className="truncate">Pensando{latestLine ? `: ${latestLine}` : ''}</span>
        <span aria-hidden="true" className="flex shrink-0 gap-0.5">
          {[0, 1, 2].map((index) =>
            reduceMotion ? (
              <span className="size-1 rounded-full bg-text-muted" key={index} />
            ) : (
              <motion.span
                animate={{ opacity: [0.25, 1, 0.25] }}
                className="size-1 rounded-full bg-text-muted"
                key={index}
                transition={{ duration: 1.1, repeat: Infinity, delay: index * 0.15 }}
              />
            )
          )}
        </span>
      </p>
    </div>
  );
}
