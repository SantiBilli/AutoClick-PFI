import { z } from 'zod';
import { addUnicodeScalarIssues, canonicalBotSchema, type JsonValue } from '@/bot/schema';

const boundedId = z.string().trim().min(1).max(200);
const jsonNumber = z.number().finite().refine(
  (value) => !Number.isInteger(value) || Number.isSafeInteger(value),
  'JSON integers must be safe integers',
);
const jsonValueSchema: z.ZodType<JsonValue> = z.lazy(() => z.union([
  z.string(),
  jsonNumber,
  z.boolean(),
  z.null(),
  z.array(jsonValueSchema),
  z.record(z.string(), jsonValueSchema),
]));

export const proposalLocationSchema = z.object({
  parentId: boundedId.nullish().default(null),
  slot: boundedId,
  index: z.number().int().min(0).max(1_000),
}).strict().superRefine((location, context) => {
  const parent = location.parentId ?? null;
  if ((parent === null) !== (location.slot === 'root')) {
    context.addIssue({ code: 'custom', message: 'root is valid only with a null parentId' });
  }
});

const proposalNodeSchema = z.object({
  id: boundedId,
  type: boundedId,
  params: z.record(z.string(), jsonValueSchema),
}).strict();

const proposalResultingBotSchema = z.unknown().superRefine((value, context) => {
  if (!value || typeof value !== 'object' || !('schemaVersion' in value) || value.schemaVersion !== 2) {
    context.addIssue({ code: 'custom', message: 'resultingBot must use schema v2' });
  }
}).pipe(canonicalBotSchema);

const setMetadataSchema = z.object({
  op: z.literal('setMetadata'),
  name: z.string().trim().min(1).max(120).nullish(),
  description: z.string().max(500).nullish(),
}).strict().refine(
  ({ name, description }) =>
    (name !== undefined && name !== null && name.length > 0) ||
    (description !== undefined && description !== null),
  {
    message: 'setMetadata requires name or description',
  },
);

export const proposalOperationSchema = z.discriminatedUnion('op', [
  setMetadataSchema,
  z.object({ op: z.literal('addNode'), node: proposalNodeSchema, location: proposalLocationSchema }).strict(),
  z.object({ op: z.literal('removeNode'), nodeId: boundedId }).strict(),
  z.object({ op: z.literal('moveNode'), nodeId: boundedId, location: proposalLocationSchema }).strict(),
  z.object({ op: z.literal('updateNodeParams'), nodeId: boundedId, params: z.record(z.string(), jsonValueSchema) }).strict(),
  z.object({ op: z.literal('replaceNode'), nodeId: boundedId, actionType: boundedId, params: z.record(z.string(), jsonValueSchema) }).strict(),
]);
export const aiBotProposalSchema = z.object({
  id: z.string().uuid(),
  version: z.number().int().min(1),
  baseBotId: z.string().uuid(),
  summary: z.string().trim().min(1).max(1_000),
  operations: z.array(proposalOperationSchema).min(1).max(200),
  resultingBot: proposalResultingBotSchema,
  baselineBotRevision: z.string().regex(/^[a-f0-9]{64}$/),
}).strict().superRefine((proposal, context) => {
  addUnicodeScalarIssues(proposal, context);
  if (proposal.resultingBot?.id.toLowerCase() !== proposal.baseBotId.toLowerCase()) {
    context.addIssue({
      code: 'custom',
      path: ['resultingBot', 'id'],
      message: 'resultingBot must match baseBotId',
    });
  }
});

const pendingBotSchema = z.unknown().superRefine((value, context) => {
  if (!value || typeof value !== 'object' || !('schemaVersion' in value) || value.schemaVersion !== 2) {
    context.addIssue({ code: 'custom', message: 'pending proposal bots must use schema v2' });
  }
}).pipe(canonicalBotSchema);

export const pendingAiProposalSchema = z.object({
  proposal: aiBotProposalSchema,
  operationBaseline: pendingBotSchema,
  original: pendingBotSchema,
  editorBotRevision: z.string().regex(/^[a-f0-9]{64}$/),
}).strict().superRefine((pending, context) => {
  if (
    pending.operationBaseline.id.toLowerCase() !== pending.proposal.baseBotId.toLowerCase()
    || pending.original.id.toLowerCase() !== pending.proposal.baseBotId.toLowerCase()
  ) {
    context.addIssue({ code: 'custom', message: 'pending proposal bot IDs must match' });
  }
});

export type ProposalLocation = z.output<typeof proposalLocationSchema>;
export type ProposalOperation = z.output<typeof proposalOperationSchema>;
export type AiBotProposal = z.output<typeof aiBotProposalSchema>;
export type PendingAiProposal = z.output<typeof pendingAiProposalSchema>;
