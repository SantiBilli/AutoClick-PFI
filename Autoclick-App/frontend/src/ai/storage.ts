import { z } from 'zod';
import {
  AI_MAX_AI_STATE_BYTES,
  AI_MAX_MESSAGE_CODE_POINTS,
  AI_STORAGE_VERSION,
  countCodePoints,
  type AiConversation,
  type AiPersistedState,
} from '@/ai/types';
import { aiBotDraftSchema } from '@/ai/botDraft';

export const AI_STORAGE_KEY = 'autoclick.ai.conversations.v1';
export const AI_MAX_CONVERSATIONS = 20;
export const AI_MAX_MESSAGES = 60;
export const AI_STORAGE_BUDGET_BYTES = AI_MAX_AI_STATE_BYTES;

const metricCountSchema = z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER);
const messageMetricsSchema = z.object({
  totalTimeMs: metricCountSchema,
  inputTokens: metricCountSchema.nullable(),
  outputTokens: metricCountSchema.nullable(),
}).strict();
const messageSchema = z.object({
  id: z.string().min(1),
  role: z.enum(['user', 'assistant']),
  content: z.string().refine(
    (value) => countCodePoints(value) <= AI_MAX_MESSAGE_CODE_POINTS,
    'Message exceeds the code point limit'
  ),
  createdAt: z.string().min(1),
  status: z.enum(['complete', 'interrupted']),
  metrics: messageMetricsSchema.optional(),
  draft: aiBotDraftSchema.optional(),
}).strict();

const conversationSchema = z.object({
  id: z.string().min(1),
  title: z.string().min(1).max(80),
  createdAt: z.string().min(1),
  updatedAt: z.string().min(1),
  messages: z.array(messageSchema).max(AI_MAX_MESSAGES),
}).strict();

const persistedSchema = z.object({
  schemaVersion: z.literal(AI_STORAGE_VERSION),
  activeConversationId: z.string().min(1).nullable(),
  conversations: z.array(conversationSchema).max(AI_MAX_CONVERSATIONS),
}).strict().superRefine((state, context) => {
  const ids = new Set(state.conversations.map((conversation) => conversation.id));
  if (ids.size !== state.conversations.length) context.addIssue({ code: 'custom', message: 'Conversation IDs must be unique' });
  if (state.activeConversationId !== null && !ids.has(state.activeConversationId)) {
    context.addIssue({ code: 'custom', path: ['activeConversationId'], message: 'Active conversation must exist' });
  }
  if (new TextEncoder().encode(JSON.stringify(state)).byteLength > AI_STORAGE_BUDGET_BYTES) {
    context.addIssue({ code: 'custom', message: 'AI state exceeds its byte budget' });
  }
});

export function emptyAiPersistedState(): AiPersistedState {
  return { schemaVersion: AI_STORAGE_VERSION, activeConversationId: null, conversations: [] };
}

export function loadAiState(storage: Pick<Storage, 'getItem'> = localStorage): AiPersistedState {
  try {
    const value = storage.getItem(AI_STORAGE_KEY);
    if (!value) return emptyAiPersistedState();
    return persistedSchema.parse(JSON.parse(value));
  } catch {
    return emptyAiPersistedState();
  }
}

export function pruneAiState(state: AiPersistedState): AiPersistedState {
  let conversations: AiConversation[] = state.conversations
    .map((conversation) => ({ ...conversation, messages: conversation.messages.slice(-AI_MAX_MESSAGES) }))
    .sort((left, right) => right.updatedAt.localeCompare(left.updatedAt))
    .slice(0, AI_MAX_CONVERSATIONS);

  let activeConversationId = conversations.some(({ id }) => id === state.activeConversationId)
    ? state.activeConversationId
    : conversations[0]?.id ?? null;
  let candidate: AiPersistedState = { schemaVersion: AI_STORAGE_VERSION, activeConversationId, conversations };

  while (new Blob([JSON.stringify(candidate)]).size > AI_STORAGE_BUDGET_BYTES) {
    const oldestWithHistory = [...conversations].reverse().find((conversation) => conversation.messages.length > 1);
    if (oldestWithHistory) {
      conversations = conversations.map((conversation) => conversation.id === oldestWithHistory.id
        ? { ...conversation, messages: conversation.messages.slice(1) }
        : conversation);
    } else if (conversations.length > 1) {
      conversations = conversations.slice(0, -1);
    } else {
      conversations = [];
    }
    activeConversationId = conversations.some(({ id }) => id === activeConversationId)
      ? activeConversationId
      : conversations[0]?.id ?? null;
    candidate = { schemaVersion: AI_STORAGE_VERSION, activeConversationId, conversations };
    if (!conversations.length) break;
  }
  return candidate;
}

export function saveAiState(state: AiPersistedState, storage: Pick<Storage, 'setItem'> = localStorage): boolean {
  try {
    if (state.conversations.some((conversation) => conversation.messages.some(
      (message) => countCodePoints(message.content) > AI_MAX_MESSAGE_CODE_POINTS
    ))) return false;
    const result = persistedSchema.safeParse(pruneAiState(state));
    if (!result.success) return false;
    storage.setItem(AI_STORAGE_KEY, JSON.stringify(result.data));
    return true;
  } catch {
    return false;
  }
}
