import { botAiSchema, BOT_AI_BUDGET_BYTES, BOT_AI_MAX_CONVERSATIONS, AI_MAX_MESSAGES, type BotAiState } from '@/ai/schema';
import { AI_STORAGE_VERSION, type AiConversation, type AiPersistedState } from '@/ai/types';

export class BotAiSizeError extends Error {
  constructor() {
    super('El historial de este bot es demasiado grande. Eliminá mensajes o conversaciones antes de continuar.');
  }
}

function byteLength(value: AiPersistedState): number {
  return new TextEncoder().encode(JSON.stringify(value)).byteLength;
}

export function normalizeBotAiState(state: AiPersistedState): BotAiState {
  let conversations: AiConversation[] = state.conversations
    .map((conversation) => ({ ...conversation, messages: conversation.messages.slice(-AI_MAX_MESSAGES) }))
    .sort((left, right) => right.updatedAt.localeCompare(left.updatedAt))
    .slice(0, BOT_AI_MAX_CONVERSATIONS);
  let activeConversationId = conversations.some(({ id }) => id === state.activeConversationId)
    ? state.activeConversationId
    : conversations[0]?.id ?? null;

  let candidate: AiPersistedState = { schemaVersion: AI_STORAGE_VERSION, activeConversationId, conversations };
  while (byteLength(candidate) > BOT_AI_BUDGET_BYTES) {
    const oldestWithHistory = [...conversations]
      .reverse()
      .find((conversation) => conversation.messages.length > 0 && conversation.id !== activeConversationId);
    if (oldestWithHistory) {
      conversations = conversations.map((conversation) => conversation.id === oldestWithHistory.id
        ? { ...conversation, messages: conversation.messages.slice(1) }
        : conversation);
    } else {
      const removableEmpty = [...conversations]
        .reverse()
        .find((conversation) => conversation.messages.length === 0 && conversation.id !== activeConversationId);
      if (!removableEmpty) throw new BotAiSizeError();
      conversations = conversations.filter(({ id }) => id !== removableEmpty.id);
    }
    activeConversationId = conversations.some(({ id }) => id === activeConversationId)
      ? activeConversationId
      : conversations[0]?.id ?? null;
    candidate = { schemaVersion: AI_STORAGE_VERSION, activeConversationId, conversations };
  }
  return botAiSchema.parse(candidate);
}
