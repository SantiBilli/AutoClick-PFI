import { AI_MAX_MESSAGE_CODE_POINTS, AI_STORAGE_VERSION, countCodePoints, truncateCodePoints, type AiConversation, type AiMessage, type AiMessageMetrics, type AiPersistedState, type AiState } from '@/ai/types';

export type AiAction =
  | { type: 'conversationCreated'; conversation: AiConversation }
  | { type: 'conversationSelected'; conversationId: string }
  | { type: 'conversationRenamed'; conversationId: string; title: string; updatedAt: string }
  | { type: 'conversationDeleted'; conversationId: string }
  | { type: 'conversationsCleared' }
  | { type: 'generationConnecting'; conversationId: string; userMessage: AiMessage; assistantMessageId: string }
  | { type: 'generationStarted'; assistantMessageId: string }
  | { type: 'generationThinking'; assistantMessageId: string; content: string }
  | { type: 'generationStatus'; assistantMessageId: string; stage?: string }
  | { type: 'generationDelta'; assistantMessageId: string; content: string }
  | { type: 'generationProposalSummary'; assistantMessageId: string; content: string }
  | { type: 'generationBotDraft'; assistantMessageId: string; draft: NonNullable<AiMessage['draft']> }
  | { type: 'generationFinished'; assistantMessageId: string; createdAt: string; metrics?: AiMessageMetrics }
  | { type: 'generationInterrupted'; assistantMessageId: string; createdAt: string; error?: string; metrics?: AiMessageMetrics }
  | { type: 'generationFailed'; assistantMessageId: string; createdAt: string; error: string; metrics?: AiMessageMetrics }
  | { type: 'persistedStateAdopted'; persisted: AiPersistedState }
  | { type: 'errorCleared' };

export function createAiState(persisted: AiPersistedState): AiState {
  return { ...persisted, generation: null, error: null };
}

function updateConversation(state: AiState, conversationId: string, update: (conversation: AiConversation) => AiConversation): AiState {
  return { ...state, conversations: state.conversations.map((conversation) => conversation.id === conversationId ? update(conversation) : conversation) };
}

function completeGeneration(state: AiState, assistantMessageId: string, createdAt: string, status: 'complete' | 'interrupted', error: string | null, metrics?: AiMessageMetrics): AiState {
  const generation = state.generation;
  if (!generation || generation.assistantMessageId !== assistantMessageId) return state;
  const assistant: AiMessage | null = generation.assistantContent
    ? { id: assistantMessageId, role: 'assistant', content: generation.assistantContent, createdAt, status, ...(metrics ? { metrics } : {}), ...(generation.botDraft ? { draft: generation.botDraft } : {}) }
    : null;
  if (!assistant) return { ...state, generation: null, error };
  const next = updateConversation(state, generation.conversationId, (conversation) => ({
    ...conversation,
    updatedAt: createdAt,
    messages: [...conversation.messages, assistant].slice(-60),
  }));
  return { ...next, generation: null, error };
}

export function aiReducer(state: AiState, action: AiAction): AiState {
  switch (action.type) {
    case 'conversationCreated':
      return { ...state, activeConversationId: action.conversation.id, conversations: [action.conversation, ...state.conversations], error: null };
    case 'conversationSelected':
      return state.conversations.some(({ id }) => id === action.conversationId) ? { ...state, activeConversationId: action.conversationId, error: null } : state;
    case 'conversationRenamed': {
      const title = action.title.trim().slice(0, 80);
      return title ? updateConversation(state, action.conversationId, (conversation) => ({ ...conversation, title, updatedAt: action.updatedAt })) : state;
    }
    case 'conversationDeleted': {
      const conversations = state.conversations.filter(({ id }) => id !== action.conversationId);
      return {
        ...state,
        conversations,
        activeConversationId: state.activeConversationId === action.conversationId ? conversations[0]?.id ?? null : state.activeConversationId,
        error: null,
      };
    }
    case 'conversationsCleared': {
      return {
        ...state,
        conversations: [],
        activeConversationId: null,
        error: null,
      };
    }
    case 'generationConnecting':
      if (state.generation) return state;
      return {
        ...updateConversation(state, action.conversationId, (conversation) => ({
          ...conversation,
          updatedAt: action.userMessage.createdAt,
          messages: [...conversation.messages, action.userMessage].slice(-60),
          title: conversation.messages.length === 0 && conversation.title === 'Nueva conversación'
            ? titleFromMessage(action.userMessage.content)
            : conversation.title,
        })),
        activeConversationId: action.conversationId,
        generation: { ...action, phase: 'connecting', thinkingContent: '', assistantContent: '' },
        error: null,
      };
    case 'generationStarted': {
      const generation = state.generation;
      if (generation?.assistantMessageId !== action.assistantMessageId) return state;
      return { ...state, generation: { ...generation, phase: 'streaming' } };
    }
    case 'generationThinking': {
      const generation = state.generation;
      return generation?.assistantMessageId === action.assistantMessageId && !generation.assistantContent
        ? { ...state, generation: { ...generation, thinkingContent: (generation.thinkingContent + action.content).slice(-2_000) } }
        : state;
    }
    case 'generationDelta': {
      const generation = state.generation;
      return generation?.assistantMessageId === action.assistantMessageId
        ? { ...state, generation: { ...generation, thinkingContent: '', assistantContent: truncateCodePoints(generation.assistantContent + action.content) } }
        : state;
    }
    case 'generationStatus': {
      const generation = state.generation;
      return generation?.assistantMessageId === action.assistantMessageId
        ? { ...state, generation: { ...generation, statusStage: action.stage } }
        : state;
    }
    case 'generationProposalSummary': {
      const generation = state.generation;
      return generation?.assistantMessageId === action.assistantMessageId
        ? { ...state, generation: { ...generation, thinkingContent: '', assistantContent: truncateCodePoints(action.content) } }
        : state;
    }
    case 'generationBotDraft': {
      const generation = state.generation;
      return generation?.assistantMessageId === action.assistantMessageId && !generation.botDraft
        ? { ...state, generation: { ...generation, botDraft: action.draft } }
        : state;
    }
    case 'generationFinished':
      return completeGeneration(state, action.assistantMessageId, action.createdAt, 'complete', null, action.metrics);
    case 'generationInterrupted':
      return completeGeneration(state, action.assistantMessageId, action.createdAt, 'interrupted', action.error ?? null, action.metrics);
    case 'generationFailed': {
      const generation = state.generation;
      if (!generation || generation.assistantMessageId !== action.assistantMessageId) return state;
      if (generation.assistantContent) return completeGeneration(state, action.assistantMessageId, action.createdAt, 'interrupted', action.error, action.metrics);
      return { ...state, generation: null, error: action.error };
    }
    case 'persistedStateAdopted':
      return { ...state, ...action.persisted };
    case 'errorCleared':
      return { ...state, error: null };
  }
}

export function newConversation(id: string, now: string): AiConversation {
  return { id, title: 'Nueva conversación', createdAt: now, updatedAt: now, messages: [] };
}

export function persistedAiState(state: AiState): AiPersistedState {
  return { schemaVersion: AI_STORAGE_VERSION, activeConversationId: state.activeConversationId, conversations: state.conversations };
}

export function titleFromMessage(content: string): string {
  const title = content.trim().replace(/\s+/g, ' ');
  return title.length > 60 ? `${title.slice(0, 57)}...` : title || 'Nueva conversación';
}

export function modelConversationHistory(messages: AiMessage[], maximum = 58, includeDrafts = true): AiMessage[] {
  const completeTurns: AiMessage[] = [];
  let pendingUser: AiMessage | null = null;
  for (const message of messages) {
    if (message.role === 'user') {
      pendingUser = message;
    } else if (pendingUser) {
      completeTurns.push(pendingUser, message);
      pendingUser = null;
    }
  }
  const evenMaximum = Math.max(0, maximum - (maximum % 2));
  const history = evenMaximum === 0 ? [] : completeTurns.slice(-evenMaximum);
  if (!includeDrafts) return history;
  for (let index = history.length - 1; index >= 0; index -= 1) {
    const message = history[index];
    if (message.role !== 'assistant' || message.status !== 'complete' || !message.draft) continue;
    // The card is persisted separately from its summary. Send its actual data
    // on follow-ups, without adding internal JSON to the visible transcript.
    const context = `\n\n[BORRADOR_HOME_NO_CONFIABLE]\n${JSON.stringify(message.draft.bot)}\n[/BORRADOR_HOME_NO_CONFIABLE]`;
    const unavailable = '\n\nEl borrador anterior no cabe en este historial. Para revisarlo completo, abrilo en el editor; no supongas sus bloques ni parámetros.';
    const suffix = countCodePoints(context) <= AI_MAX_MESSAGE_CODE_POINTS ? context : unavailable;
    history[index] = { ...message, content: truncateCodePoints(message.content, AI_MAX_MESSAGE_CODE_POINTS - countCodePoints(suffix)) + suffix };
    break;
  }
  return history;
}
