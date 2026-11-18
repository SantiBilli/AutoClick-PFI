import {
  createContext,
  useContext,
  useEffect,
  useReducer,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { getAiCapabilities } from '@/ai/capabilities';
import { AiClientError, fetchAiHealth, streamAiChat } from '@/ai/client';
import { normalizeBotAiState } from '@/ai/botPersistence';
import type { AiBotProposal } from '@/ai/proposalSchema';
import type { AiBotDraft } from '@/ai/botDraft';
import type { CanonicalBot } from '@/bot/schema';
import { desktopBridge } from '@/app/DesktopBridge';
import {
  aiReducer,
  createAiState,
  modelConversationHistory,
  newConversation,
  persistedAiState,
} from '@/ai/state';
import { emptyAiPersistedState, loadAiState, pruneAiState, saveAiState } from '@/ai/storage';
import {
  AI_MAX_MESSAGE_CODE_POINTS,
  AI_REQUEST_VERSION,
  countCodePoints,
  type AiConversation,
  type AiEditorContext,
  type AiHealth,
  type AiMessage,
  type AiMessageMetrics,
  type AiPersistedState,
  type AiState,
} from '@/ai/types';

const AI_URL = (import.meta.env.VITE_AUTOCLICK_AI_URL || 'http://127.0.0.1:8000').replace(
  /\/+$/,
  ''
);
export const AI_HEALTH_TIMEOUT_MS = 5_000;

export type AiSyncStatus = 'saved' | 'saving' | 'unsynced';

export type AiRepository = {
  initialState: AiPersistedState;
  maximumConversations: number;
  save(state: AiPersistedState): Promise<AiPersistedState>;
};

type AiContextValue = {
  state: AiState;
  health: AiHealth;
  activeConversation: AiConversation | null;
  syncStatus: AiSyncStatus;
  mutationsDisabled: boolean;
  canDeleteConversation: boolean;
  maximumConversations: number;
  createConversation(): string;
  selectConversation(conversationId: string): void;
  renameConversation(conversationId: string, title: string): void;
  deleteConversation(conversationId: string): void;
  clearConversations(): void;
  sendMessage(content: string, getEditorContext?: () => AiEditorContext): Promise<boolean>;
  stopGeneration(): void;
  retryPersistence(): void;
  discardUnsyncedChanges(): void;
  pruneUnsyncedChanges(): void;
  retryHealth(): void;
  creatingDraft: AiBotDraft | null;
  creationError: string | null;
  createBotFromDraft(draft: AiBotDraft): Promise<boolean>;
};

const AiContext = createContext<AiContextValue | null>(null);

function id(): string {
  return crypto.randomUUID();
}
function now(): string {
  return new Date().toISOString();
}

function publicError(error: unknown): string {
  if (error instanceof AiClientError || error instanceof Error) return error.message;
  return 'No se pudo comunicar con el servicio de AutoClick AI.';
}

function safeCreationError(code: string): string {
  if (code === 'DESKTOP_BRIDGE_UNAVAILABLE') return 'La integración de escritorio no está disponible. Abrí AutoClick desde la aplicación de escritorio.';
  if (code === 'BOT_INVALID') return 'El borrador no es válido para crear un bot.';
  if (code === 'BOT_CHANGED_EXTERNALLY') return 'El bot cambió antes de guardarse. Intentá nuevamente.';
  return 'No se pudo crear o guardar el bot. Intentá nuevamente.';
}

function dashboardRepository(): AiRepository {
  return {
    initialState: loadAiState(),
    maximumConversations: 20,
    async save(state) {
      const normalized = pruneAiState(state);
      if (!saveAiState(normalized)) throw new Error('No se pudo guardar el historial local.');
      return normalized;
    },
  };
}

export function DashboardAiProvider({ children }: { children: ReactNode }) {
  const repositoryRef = useRef<AiRepository | null>(null);
  repositoryRef.current ??= dashboardRepository();
  return <ScopedAiProvider repository={repositoryRef.current}>{children}</ScopedAiProvider>;
}

export function BotAiProvider({
  children,
  initialState,
  blocked = false,
  save,
  onUnsyncedChange,
  onProposal,
}: {
  children: ReactNode;
  initialState?: AiPersistedState;
  blocked?: boolean;
  save: (state: AiPersistedState) => Promise<AiPersistedState>;
  onUnsyncedChange?: (unsynced: boolean) => void;
  onProposal?: (proposal: AiBotProposal, requestContext: AiEditorContext, signal: AbortSignal) => void | Promise<void>;
}) {
  const repositoryRef = useRef<AiRepository>({
    initialState: normalizeBotAiState(initialState ?? emptyAiPersistedState()),
    maximumConversations: 10,
    save: async (state) => save(normalizeBotAiState(state)),
  });
  repositoryRef.current.save = async (state) => save(normalizeBotAiState(state));
  return (
    <ScopedAiProvider
      blocked={blocked}
      checkHealth={false}
      onUnsyncedChange={onUnsyncedChange}
      onProposal={onProposal}
      repository={repositoryRef.current}>
      {children}
    </ScopedAiProvider>
  );
}

// Kept as the dashboard provider name for existing consumers.
export const AiProvider = DashboardAiProvider;

function ScopedAiProvider({
  children,
  repository,
  blocked = false,
  checkHealth = true,
  onUnsyncedChange,
  onProposal,
}: {
  children: ReactNode;
  repository: AiRepository;
  blocked?: boolean;
  checkHealth?: boolean;
  onUnsyncedChange?: (unsynced: boolean) => void;
  onProposal?: (proposal: AiBotProposal, requestContext: AiEditorContext, signal: AbortSignal) => void | Promise<void>;
}) {
  const [state, dispatch] = useReducer(aiReducer, repository.initialState, createAiState);
  const [health, setHealth] = useState<AiHealth>({ status: 'checking' });
  const [healthAttempt, setHealthAttempt] = useState(0);
  const [syncStatus, setSyncStatus] = useState<AiSyncStatus>('saved');
  const [persistenceActive, setPersistenceActive] = useState(false);
  const [persistenceError, setPersistenceError] = useState<string | null>(null);
  const [creatingDraft, setCreatingDraft] = useState<AiBotDraft | null>(null);
  const [creationError, setCreationError] = useState<string | null>(null);
  const creationActiveRef = useRef(false);
  const controllerRef = useRef<AbortController | null>(null);
  const stateRef = useRef(state);
  const persistenceActiveRef = useRef(false);
  const retryStateRef = useRef<AiPersistedState | null>(null);
  const lastSavedStateRef = useRef<AiPersistedState>(structuredClone(repository.initialState));
  const generationStartedAtRef = useRef(new Map<string, number>());
  const proposalHandlerRef = useRef(onProposal);
  stateRef.current = state;
  proposalHandlerRef.current = onProposal;

  useEffect(() => {
    if (!checkHealth) return;
    let active = true;
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), AI_HEALTH_TIMEOUT_MS);
    setHealth({ status: 'checking' });
    fetchAiHealth(AI_URL, controller.signal).then(
      (response) => {
        if (active) setHealth(normalizeHealth(response));
      },
      () => {
        if (active) setHealth({ status: 'api-unavailable', url: AI_URL });
      }
    ).finally(() => window.clearTimeout(timeout));
    return () => {
      active = false;
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [checkHealth, healthAttempt]);

  useEffect(() => () => controllerRef.current?.abort(), []);

  function apply(action: Parameters<typeof aiReducer>[1]): AiState {
    const next = aiReducer(stateRef.current, action);
    stateRef.current = next;
    dispatch(action);
    return next;
  }

  async function persist(next: AiState): Promise<boolean> {
    const attempted = persistedAiState(next);
    retryStateRef.current = attempted;
    persistenceActiveRef.current = true;
    setPersistenceActive(true);
    setSyncStatus('saving');
    setPersistenceError(null);
    try {
      const normalized = await repository.save(attempted);
      lastSavedStateRef.current = structuredClone(normalized);
      apply({ type: 'persistedStateAdopted', persisted: normalized });
      retryStateRef.current = null;
      setSyncStatus('saved');
      onUnsyncedChange?.(false);
      return true;
    } catch (error) {
      setPersistenceError(publicError(error));
      setSyncStatus('unsynced');
      onUnsyncedChange?.(true);
      return false;
    } finally {
      persistenceActiveRef.current = false;
      setPersistenceActive(false);
    }
  }

  function canMutate(): boolean {
    return !blocked && syncStatus !== 'unsynced' && !persistenceActiveRef.current && !stateRef.current.generation;
  }

  function createConversation(): string {
    if (!canMutate() || stateRef.current.conversations.length >= repository.maximumConversations)
      return '';
    const conversationId = id();
    const next = apply({
      type: 'conversationCreated',
      conversation: newConversation(conversationId, now()),
    });
    void persist(next);
    return conversationId;
  }

  function selectConversation(conversationId: string) {
    if (!canMutate() || stateRef.current.activeConversationId === conversationId) return;
    const next = apply({ type: 'conversationSelected', conversationId });
    void persist(next);
  }

  function renameConversation(conversationId: string, title: string) {
    if (!canMutate()) return;
    const before = stateRef.current;
    const next = apply({ type: 'conversationRenamed', conversationId, title, updatedAt: now() });
    if (next !== before) void persist(next);
  }

  function deleteConversation(conversationId: string) {
    const recoverable = !blocked
      && !persistenceActiveRef.current
      && !stateRef.current.generation;
    if (!canMutate() && !(syncStatus === 'unsynced' && recoverable)) return;
    if (stateRef.current.generation?.conversationId === conversationId) stopGeneration();
    const action = { type: 'conversationDeleted', conversationId } as const;
    const next = syncStatus === 'unsynced'
      ? aiReducer(createAiState(structuredClone(lastSavedStateRef.current)), action)
      : apply(action);
    if (syncStatus === 'unsynced') {
      stateRef.current = next;
      dispatch({ type: 'persistedStateAdopted', persisted: persistedAiState(next) });
    }
    void persist(next);
  }

  function clearConversations() {
    const recoverable = !blocked
      && !persistenceActiveRef.current
      && !stateRef.current.generation;
    if (!canMutate() && !(syncStatus === 'unsynced' && recoverable)) return;
    if (stateRef.current.generation) stopGeneration();
    const action = { type: 'conversationsCleared' } as const;
    const next = syncStatus === 'unsynced'
      ? aiReducer(createAiState(structuredClone(lastSavedStateRef.current)), action)
      : apply(action);
    if (syncStatus === 'unsynced') {
      stateRef.current = next;
      dispatch({ type: 'persistedStateAdopted', persisted: persistedAiState(next) });
    }
    void persist(next);
  }

  async function sendMessage(
    content: string,
    getEditorContext?: () => AiEditorContext
  ): Promise<boolean> {
    const text = content.trim();
    const current = stateRef.current;
    if (
      !text ||
      countCodePoints(text) > AI_MAX_MESSAGE_CODE_POINTS ||
      current.generation ||
      controllerRef.current ||
      !canMutate()
    )
      return false;

    let conversation =
      current.conversations.find(
        ({ id: conversationId }) => conversationId === current.activeConversationId
      ) ?? null;
    if (!conversation) {
      if (current.conversations.length >= repository.maximumConversations) return false;
      conversation = newConversation(id(), now());
      apply({ type: 'conversationCreated', conversation });
    }
    const userMessage: AiMessage = {
      id: id(),
      role: 'user',
      content: text,
      createdAt: now(),
      status: 'complete',
    };
    const assistantMessageId = id();
    const history = modelConversationHistory(conversation.messages, 58, !getEditorContext);
    const next = apply({
      type: 'generationConnecting',
      conversationId: conversation.id,
      userMessage,
      assistantMessageId,
    });
    if (!(await persist(next))) {
      apply({
        type: 'generationFailed',
        assistantMessageId,
        createdAt: now(),
        error: 'El mensaje no se pudo guardar.',
      });
      return false;
    }

    generationStartedAtRef.current.set(assistantMessageId, performance.now());
    const controller = new AbortController();
    controllerRef.current = controller;
    void (async () => {
      try {
        const editorContext = getEditorContext ? getEditorContext() : null;
        await streamAiChat(
          AI_URL,
          {
            schemaVersion: AI_REQUEST_VERSION,
            messages: [...history, userMessage].map(({ role, content: messageContent }) => ({
              role,
              content: messageContent,
            })),
            capabilities: getAiCapabilities(),
            editorContext,
          },
          controller.signal,
          {
            onStart() {
              apply({ type: 'generationStarted', assistantMessageId });
            },
            onThinking(thinking) {
              apply({ type: 'generationThinking', assistantMessageId, content: thinking });
            },
            onStatus(status) {
              apply({ type: 'generationStatus', assistantMessageId, stage: status.stage });
            },
            onDelta(delta) {
              apply({ type: 'generationDelta', assistantMessageId, content: delta });
            },
            onProposal(proposal, signal) {
              if (
                signal !== controller.signal
                || signal.aborted
                || controllerRef.current !== controller
                || stateRef.current.generation?.assistantMessageId !== assistantMessageId
              ) return;
              apply({ type: 'generationProposalSummary', assistantMessageId, content: proposal.summary });
              if (editorContext) return proposalHandlerRef.current?.(proposal, editorContext, signal);
            },
            onBotDraft(draft, signal) {
              if (signal.aborted || controllerRef.current !== controller || stateRef.current.generation?.assistantMessageId !== assistantMessageId) return;
              apply({ type: 'generationBotDraft', assistantMessageId, draft });
            },
            onDone(_finishReason, metrics) {
              return finishGeneration(assistantMessageId, 'complete', metrics);
            },
          }
        );
      } catch (error) {
        if (controller.signal.aborted) await finishGeneration(assistantMessageId, 'interrupted', elapsedMetrics(assistantMessageId));
        else {
          const before = stateRef.current;
          const failed = apply({
            type: 'generationFailed',
            assistantMessageId,
            createdAt: now(),
            error: publicError(error),
            metrics: elapsedMetrics(assistantMessageId),
          });
          if (before.generation?.assistantContent && failed !== before) await persist(failed);
        }
      } finally {
        generationStartedAtRef.current.delete(assistantMessageId);
        if (controllerRef.current === controller) controllerRef.current = null;
      }
    })();
    return true;
  }

  async function finishGeneration(assistantMessageId: string, status: 'complete' | 'interrupted', metrics?: AiMessageMetrics) {
    const before = stateRef.current;
    const generation = before.generation;
    if (!generation || generation.assistantMessageId !== assistantMessageId) return;
    const next = apply({
      type: status === 'complete' ? 'generationFinished' : 'generationInterrupted',
      assistantMessageId,
      createdAt: now(),
      metrics,
    });
    if (generation.assistantContent && next !== before) await persist(next);
  }

  function stopGeneration() {
    const generation = stateRef.current.generation;
    if (!generation) return;
    controllerRef.current?.abort();
    void finishGeneration(generation.assistantMessageId, 'interrupted', elapsedMetrics(generation.assistantMessageId));
  }

  function elapsedMetrics(assistantMessageId: string): AiMessageMetrics {
    const startedAt = generationStartedAtRef.current.get(assistantMessageId) ?? performance.now();
    return {
      totalTimeMs: Math.max(0, Math.round(performance.now() - startedAt)),
      inputTokens: null,
      outputTokens: null,
    };
  }

  function retryPersistence() {
    if (blocked || persistenceActiveRef.current || !retryStateRef.current) return;
    const retryState = createAiState(retryStateRef.current);
    stateRef.current = retryState;
    dispatch({ type: 'persistedStateAdopted', persisted: retryStateRef.current });
    void persist(retryState);
  }

  async function createBotFromDraft(draft: AiBotDraft): Promise<boolean> {
    if (creationActiveRef.current) return false;
    creationActiveRef.current = true;
    setCreatingDraft(draft);
    setCreationError(null);
    try {
      const created = await desktopBridge.createBot(draft.name);
      if (!created.ok) throw new Error(safeCreationError(created.error.code));
      const botToSave: CanonicalBot = {
        ...draft.bot,
        id: created.data.bot?.id ?? draft.bot.id,
        name: draft.name,
      };
      const saved = await desktopBridge.saveBot(created.data.editorToken, created.data.revision, botToSave, true);
      if (!saved.ok) throw new Error(safeCreationError(saved.error.code));
      window.location.hash = `/bots/${encodeURIComponent(saved.data.descriptor.entryId)}`;
      return true;
    } catch (error) {
      setCreationError(error instanceof Error ? error.message : 'No se pudo crear el bot. Intentá nuevamente.');
      return false;
    } finally {
      creationActiveRef.current = false;
      setCreatingDraft(null);
    }
  }

  function discardUnsyncedChanges() {
    if (blocked || persistenceActiveRef.current || syncStatus !== 'unsynced') return;
    const saved = structuredClone(lastSavedStateRef.current);
    retryStateRef.current = saved;
    void persist(createAiState(saved));
  }

  function pruneUnsyncedChanges() {
    if (blocked || persistenceActiveRef.current || syncStatus !== 'unsynced') return;
    const current = structuredClone(lastSavedStateRef.current);
    const candidates = [...current.conversations].sort((left, right) =>
      left.updatedAt.localeCompare(right.updatedAt)
    );
    const withMessages = candidates.find((conversation) => conversation.messages.length > 0);
    let nextPersisted: AiPersistedState;
    if (withMessages) {
      nextPersisted = {
        ...current,
        conversations: current.conversations.map((conversation) =>
          conversation.id === withMessages.id
            ? { ...conversation, messages: conversation.messages.slice(1) }
            : conversation
        ),
      };
    } else if (candidates.length) {
      const removedId = candidates[0].id;
      const conversations = current.conversations.filter(({ id: conversationId }) => conversationId !== removedId);
      nextPersisted = {
        ...current,
        activeConversationId: current.activeConversationId === removedId
          ? conversations[0]?.id ?? null
          : current.activeConversationId,
        conversations,
      };
    } else {
      nextPersisted = current;
    }
    const next = createAiState(pruneAiState(nextPersisted));
    stateRef.current = next;
    dispatch({ type: 'persistedStateAdopted', persisted: persistedAiState(next) });
    void persist(next);
  }

  const activeConversation =
    state.conversations.find(
      ({ id: conversationId }) => conversationId === state.activeConversationId
    ) ?? null;
  return (
    <AiContext.Provider
      value={{
        state: persistenceError ? { ...state, error: persistenceError } : state,
        health,
        activeConversation,
        syncStatus,
        mutationsDisabled: blocked || syncStatus === 'unsynced' || persistenceActive || Boolean(state.generation),
        canDeleteConversation: !blocked && !persistenceActive && !state.generation,
        maximumConversations: repository.maximumConversations,
        createConversation,
        selectConversation,
        renameConversation,
        deleteConversation,
        clearConversations,
        sendMessage,
        stopGeneration,
        retryPersistence,
        discardUnsyncedChanges,
        pruneUnsyncedChanges,
         retryHealth: () => setHealthAttempt((attempt) => attempt + 1),
         creatingDraft,
         creationError,
         createBotFromDraft,
      }}>
      {children}
    </AiContext.Provider>
  );
}

export function useAi(): AiContextValue {
  const value = useContext(AiContext);
  if (!value) throw new Error('useAi debe utilizarse dentro de AiProvider');
  return value;
}

function normalizeHealth(input: unknown): AiHealth {
  const value = input && typeof input === 'object' ? (input as Record<string, unknown>) : {};
  const model =
    typeof value.model === 'string' && value.model.trim() && value.model.length <= 120
      ? value.model.trim()
      : null;
  const status =
    typeof value.status === 'string' ? value.status.toLowerCase().replaceAll('-', '_') : '';
  const ollama =
    value.ollama && typeof value.ollama === 'object'
      ? (value.ollama as Record<string, unknown>)
      : {};
  const modelInfo =
    value.modelStatus && typeof value.modelStatus === 'object'
      ? (value.modelStatus as Record<string, unknown>)
      : {};
  if (!model) return { status: 'api-unavailable', url: AI_URL };
  if (status === 'ollama_unavailable' || ollama.reachable === false)
    return { status: 'ollama-unavailable', model };
  if (
    status === 'model_not_found' ||
    status === 'model_unavailable' ||
    value.modelAvailable === false ||
    modelInfo.installed === false
  )
    return { status: 'model-unavailable', model };
  if (status === 'ready') return { status: 'ready', model };
  return { status: 'api-unavailable', url: AI_URL };
}
