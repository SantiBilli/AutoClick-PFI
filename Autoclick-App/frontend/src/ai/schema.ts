import { z } from 'zod';
import {
  AI_MAX_AI_STATE_BYTES,
  AI_MAX_MESSAGE_CODE_POINTS,
  AI_STORAGE_VERSION,
  countCodePoints,
} from '@/ai/types';
import type { AiBotDraft } from '@/ai/botDraft';

export const BOT_AI_MAX_CONVERSATIONS = 10;
export const AI_MAX_MESSAGES = 60;
export const BOT_AI_BUDGET_BYTES = AI_MAX_AI_STATE_BYTES;

const uuidSchema = z.string().uuid().transform((value) => value.toLowerCase());
const utcTimestampSchema = z.iso.datetime({ offset: false });
const metricCountSchema = z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER);
export const aiMessageMetricsSchema = z.object({
  totalTimeMs: metricCountSchema,
  inputTokens: metricCountSchema.nullable(),
  outputTokens: metricCountSchema.nullable(),
}).strict();
const persistedBotDraftSchema: z.ZodType<AiBotDraft> = z.object({
  bot: z.unknown(),
  name: z.string().trim().min(1).max(120),
  summary: z.string().trim().min(1).max(500),
  catalogVersion: z.number().int().nonnegative(),
  catalogHash: z.string().regex(/^[0-9a-f]{64}$/),
}).strict() as z.ZodType<AiBotDraft>;

export const aiMessageSchema = z.object({
  id: uuidSchema,
  role: z.enum(['user', 'assistant']),
  content: z.string().min(1).refine(
    (value) => countCodePoints(value) <= AI_MAX_MESSAGE_CODE_POINTS,
    'Message exceeds the code point limit'
  ),
  createdAt: utcTimestampSchema,
  status: z.enum(['complete', 'interrupted']),
  metrics: aiMessageMetricsSchema.optional(),
  draft: persistedBotDraftSchema.optional(),
}).strict().superRefine((message, context) => {
  if (message.role === 'user' && message.status !== 'complete') {
    context.addIssue({ code: 'custom', path: ['status'], message: 'User messages must be complete' });
  }
  if (message.role === 'user' && message.metrics !== undefined) {
    context.addIssue({ code: 'custom', path: ['metrics'], message: 'User messages cannot contain model metrics' });
  }
  if (message.role === 'user' && message.draft !== undefined) {
    context.addIssue({ code: 'custom', path: ['draft'], message: 'User messages cannot contain bot drafts' });
  }
});

export const aiConversationSchema = z.object({
  id: uuidSchema,
  title: z.string().trim().min(1).max(80),
  createdAt: utcTimestampSchema,
  updatedAt: utcTimestampSchema,
  messages: z.array(aiMessageSchema).max(AI_MAX_MESSAGES),
}).strict();

export const botAiSchema = z.object({
  schemaVersion: z.literal(AI_STORAGE_VERSION),
  activeConversationId: uuidSchema.nullable(),
  conversations: z.array(aiConversationSchema).max(BOT_AI_MAX_CONVERSATIONS),
}).strict().superRefine((state, context) => {
  const conversationIds = new Set<string>();
  const messageIds = new Set<string>();
  state.conversations.forEach((conversation, conversationIndex) => {
    if (conversationIds.has(conversation.id)) {
      context.addIssue({ code: 'custom', path: ['conversations', conversationIndex, 'id'], message: 'Conversation IDs must be unique' });
    }
    conversationIds.add(conversation.id);
    conversation.messages.forEach((message, messageIndex) => {
      if (messageIds.has(message.id)) {
        context.addIssue({ code: 'custom', path: ['conversations', conversationIndex, 'messages', messageIndex, 'id'], message: 'Message IDs must be unique' });
      }
      messageIds.add(message.id);
    });
  });
  if (state.activeConversationId !== null && !conversationIds.has(state.activeConversationId)) {
    context.addIssue({ code: 'custom', path: ['activeConversationId'], message: 'Active conversation must exist' });
  }
  if (new TextEncoder().encode(JSON.stringify(state)).byteLength > BOT_AI_BUDGET_BYTES) {
    context.addIssue({ code: 'custom', message: 'AI state exceeds its byte budget' });
  }
});

export type BotAiState = z.output<typeof botAiSchema>;

export function parseBotAi(input: unknown): BotAiState {
  return botAiSchema.parse(input);
}
