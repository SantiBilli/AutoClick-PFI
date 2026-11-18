import type { CanonicalBotInput } from '@/bot/schema';
import type { ValidationIssue } from '@/bot/validation';
import type { AiBotProposal } from '@/ai/proposalSchema';
import type { AiBotDraft } from '@/ai/botDraft';
import aiContract from '@ai-contract';

export const AI_STORAGE_VERSION = 1 as const;
export const AI_REQUEST_VERSION = 1 as const;
export const AI_MAX_MESSAGE_CODE_POINTS = aiContract.maxMessageCodePoints;
export const AI_MAX_AI_STATE_BYTES = aiContract.maxAiStateBytes;

export const countCodePoints = (value: string): number => Array.from(value).length;
export const truncateCodePoints = (
  value: string,
  maximum = AI_MAX_MESSAGE_CODE_POINTS
): string => Array.from(value).slice(0, maximum).join('');

export type AiMessageMetrics = {
  totalTimeMs: number;
  inputTokens: number | null;
  outputTokens: number | null;
};

export type AiMessage = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  createdAt: string;
  status: 'complete' | 'interrupted';
  metrics?: AiMessageMetrics;
  draft?: AiBotDraft;
};

export type AiConversation = {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  messages: AiMessage[];
};

export type AiPersistedState = {
  schemaVersion: typeof AI_STORAGE_VERSION;
  activeConversationId: string | null;
  conversations: AiConversation[];
};

export type AiActionCapability = {
  id: string;
  category: string;
  categoryName: string;
  title: string;
  description: string;
  fields: Array<{
    name: string;
    label: string;
    type: string;
    required: boolean;
    min?: number;
    max?: number;
    minLength?: number;
    maxLength?: number;
    pattern?: string;
    options?: string[];
  }>;
  defaults: Record<string, unknown>;
  output: { field: string; type: 'value' | 'workbook' } | null;
  outputs: Array<{ field: string; type: 'value' | 'workbook' }>;
  slots: string[];
  platform?: 'windows';
};

export type AiCapabilities = {
  catalogVersion: number;
  catalogHash: string;
  actions: AiActionCapability[];
};

export type AiEditorContext = {
  bot: CanonicalBotInput;
  validationIssues: ValidationIssue[];
  selectedBlockId: string | null;
  workingBot?: CanonicalBotInput;
  workingValidationIssues?: ValidationIssue[];
  proposalVersion?: number;
};

export type AiChatRequest = {
  schemaVersion: typeof AI_REQUEST_VERSION;
  messages: Array<{ role: 'user' | 'assistant'; content: string }>;
  capabilities: AiCapabilities;
  editorContext: AiEditorContext | null;
};

export type AiStreamEvent =
  | { type: 'start'; requestId: string; model: string }
  | { type: 'thinking'; content: string }
  | { type: 'status'; content: string; stage?: string }
  | { type: 'delta'; content: string }
  | { type: 'proposal'; proposal: AiBotProposal }
  | { type: 'botDraft'; draft: AiBotDraft }
  | { type: 'done'; finishReason: string; metrics: AiMessageMetrics }
  | { type: 'error'; code: string; message: string; requestId: string };

export type AiHealth =
  | { status: 'checking' }
  | { status: 'ready'; model: string }
  | { status: 'api-unavailable'; url: string }
  | { status: 'ollama-unavailable'; model: string }
  | { status: 'model-unavailable'; model: string };

export type AiGeneration = {
  conversationId: string;
  userMessage: AiMessage;
  assistantMessageId: string;
  thinkingContent: string;
  statusStage?: string;
  assistantContent: string;
  botDraft?: AiBotDraft;
  phase: 'connecting' | 'streaming';
};

export type AiState = AiPersistedState & {
  generation: AiGeneration | null;
  error: string | null;
};
