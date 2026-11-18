import { z } from 'zod';
import { getAiCapabilities } from '@/ai/capabilities';
import { canonicalBotSchema } from '@/bot/schema';
import type { CanonicalBot } from '@/bot/schema';

const draftMetadataSchema = z.object({
  name: z.string().trim().min(1).max(120),
  summary: z.string().trim().min(1).max(1000),
  catalogVersion: z.number().int().nonnegative(),
  catalogHash: z.string().regex(/^[0-9a-f]{64}$/),
}).strict();

export type AiBotDraft = {
  bot: CanonicalBot;
  name: string;
  summary: string;
  catalogVersion: number;
  catalogHash: string;
};

export const aiBotDraftSchema: z.ZodType<AiBotDraft> = z.object({
  bot: z.unknown(),
  ...draftMetadataSchema.shape,
}).strict().superRefine((draft, context) => {
  const bot = canonicalBotSchema.safeParse(draft.bot);
  if (!bot.success) {
    context.addIssue({ code: 'custom', path: ['bot'], message: 'Invalid canonical bot' });
  } else if (bot.data.name !== draft.name) {
    context.addIssue({ code: 'custom', path: ['name'], message: 'Draft name must match canonical bot name' });
  }
  const capabilities = getAiCapabilities();
  if (draft.catalogVersion !== capabilities.catalogVersion) {
    context.addIssue({ code: 'custom', path: ['catalogVersion'], message: 'Catalog version mismatch' });
  }
  if (draft.catalogHash !== capabilities.catalogHash) {
    context.addIssue({ code: 'custom', path: ['catalogHash'], message: 'Catalog hash mismatch' });
  }
}) as z.ZodType<AiBotDraft>;
