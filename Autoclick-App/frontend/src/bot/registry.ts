import { z } from 'zod';
import rawRegistry from '@action-registry';
import type { JsonValue } from '@/bot/schema';
import { conditionSchema } from '@/bot/conditions';

export const VARIABLE_IDENTIFIER_PATTERN = '^[A-Za-z_][A-Za-z0-9_]*$';
const ALLOWED_ICONS = new Set([
  'Clock3',
  'Variable',
  'MousePointer2',
  'Mouse',
  'Keyboard',
  'FileSpreadsheet',
  'Sheet',
  'Save',
  'X',
  'Play',
  'Globe',
  'AppWindow',
  'Folder',
  'File',
  'Clipboard',
  'Calendar',
  'User',
  'MessageSquare',
  'Trash2',
  'Network',
  'Workflow',
  'CornerDownRight',
  'ScanText',
]);
const IDENTIFIER = /^[A-Za-z][A-Za-z0-9]*(?:[._-][A-Za-z0-9]+)*$/;
const STRING_FIELD_TYPES = new Set(['text', 'multiline', 'file', 'key', 'variable']);
const NUMERIC_FIELD_TYPES = new Set(['integer', 'number']);

export const actionFieldSchema = z
  .object({
    name: z.string().regex(IDENTIFIER),
    label: z.string().min(1).max(80),
    type: z.enum(['text', 'multiline', 'integer', 'number', 'boolean', 'select', 'file', 'key', 'variable', 'json', 'condition']),
    required: z.boolean(),
    min: z.number().finite().nullish().transform((value) => value ?? undefined),
    max: z.number().finite().nullish().transform((value) => value ?? undefined),
    minLength: z.number().int().min(0).nullish().transform((value) => value ?? undefined),
    maxLength: z.number().int().min(0).nullish().transform((value) => value ?? undefined),
    pattern: z.string().nullish().transform((value) => value ?? undefined),
    options: z.array(z.string()).nullish().transform((value) => value ?? undefined),
  })
  .strict()
  .superRefine((field, context) => {
    const numeric = NUMERIC_FIELD_TYPES.has(field.type);
    const string = STRING_FIELD_TYPES.has(field.type);
    if (!numeric && (field.min !== undefined || field.max !== undefined)) {
      context.addIssue({ code: 'custom', message: 'Only numeric fields may have numeric bounds' });
    }
    if (field.type === 'integer' && [field.min, field.max].some((value) => value !== undefined && !Number.isInteger(value))) {
      context.addIssue({ code: 'custom', message: 'Integer bounds must be integers' });
    }
    if (field.min !== undefined && field.max !== undefined && field.min > field.max) {
      context.addIssue({ code: 'custom', message: 'Minimum cannot exceed maximum' });
    }
    if (!string && (field.minLength !== undefined || field.maxLength !== undefined || field.pattern !== undefined)) {
      context.addIssue({ code: 'custom', message: 'Only string fields may have string constraints' });
    }
    if (field.minLength !== undefined && field.maxLength !== undefined && field.minLength > field.maxLength) {
      context.addIssue({ code: 'custom', message: 'Minimum length cannot exceed maximum length' });
    }
    if (field.type === 'select') {
      if (!field.options?.length || new Set(field.options).size !== field.options.length || field.options.some((option) => !option)) {
        context.addIssue({ code: 'custom', message: 'Select fields require unique non-empty options' });
      }
    } else if (field.options !== undefined) {
      context.addIssue({ code: 'custom', message: 'Only select fields may define options' });
    }
    if (field.pattern !== undefined) {
      try {
        new RegExp(field.pattern);
      } catch {
        context.addIssue({ code: 'custom', message: 'Field pattern must be valid' });
      }
    }
    if (field.type === 'variable' && field.pattern !== VARIABLE_IDENTIFIER_PATTERN) {
      context.addIssue({ code: 'custom', message: 'Variable fields require the canonical pattern' });
    }
  });

const actionOutputSchema = z
  .object({ field: z.string().regex(IDENTIFIER), type: z.enum(['value', 'workbook']) })
  .strict();

export const actionDefinitionSchema = z
  .object({
    id: z.string().regex(IDENTIFIER),
    category: z.string().regex(IDENTIFIER),
    categoryName: z.string().min(1).max(80),
    title: z.string().min(1).max(80),
    description: z.string().min(1).max(240),
    icon: z.string(),
    fields: z.array(actionFieldSchema),
    defaults: z.record(z.string(), z.unknown()),
    output: actionOutputSchema.nullable(),
    outputs: z.array(actionOutputSchema).default([]),
    handlerKey: z.string().regex(IDENTIFIER),
    platform: z.literal('windows').nullable().optional().transform((value) => value ?? undefined),
    slots: z.array(z.string().regex(IDENTIFIER)).default([]),
  })
  .strict()
  .superRefine((action, context) => {
    const fields = new Map(action.fields.map((field) => [field.name, field]));
    if (fields.size !== action.fields.length) context.addIssue({ code: 'custom', message: 'Field names must be unique' });
    if (new Set(action.slots).size !== action.slots.length) context.addIssue({ code: 'custom', message: 'Slot names must be unique' });
    if (!ALLOWED_ICONS.has(action.icon)) context.addIssue({ code: 'custom', message: 'Icon is not allowed' });

    for (const [name, value] of Object.entries(action.defaults)) {
      const field = fields.get(name);
      if (!field || value === null || !isValidFieldValue(field, value, false)) {
        context.addIssue({ code: 'custom', path: ['defaults', name], message: 'Default does not satisfy its field' });
      }
    }
    if (action.output && (fields.get(action.output.field)?.type !== 'variable')) {
      context.addIssue({ code: 'custom', path: ['output'], message: 'Output must reference a variable field' });
    }
    if (new Set(action.outputs.map((output) => output.field)).size !== action.outputs.length) {
      context.addIssue({ code: 'custom', path: ['outputs'], message: 'Output fields must be unique' });
    }
    for (const output of action.outputs) {
      if (fields.get(output.field)?.type !== 'variable') context.addIssue({ code: 'custom', path: ['outputs'], message: 'Outputs must reference variable fields' });
    }
    if (action.output && action.outputs.length && JSON.stringify(action.output) !== JSON.stringify(action.outputs[0])) {
      context.addIssue({ code: 'custom', path: ['outputs'], message: 'Legacy output must match the first output' });
    }
  });

export const actionRegistrySchema = z
  .object({
    catalogVersion: z.number().int().min(1),
    catalogHash: z.string().regex(/^[0-9a-f]{64}$/),
    actions: z.array(actionDefinitionSchema),
  })
  .strict()
  .superRefine(({ actions }, context) => {
    if (new Set(actions.map((action) => action.id)).size !== actions.length) {
      context.addIssue({ code: 'custom', message: 'Action IDs must be unique' });
    }
    if (new Set(actions.map((action) => action.handlerKey)).size !== actions.length) {
      context.addIssue({ code: 'custom', message: 'Handler keys must be unique' });
    }
  });

export type ActionField = z.output<typeof actionFieldSchema>;
export type ActionDefinition = z.output<typeof actionDefinitionSchema>;
export type ActionRegistry = z.output<typeof actionRegistrySchema>;

export function isValidFieldValue(field: ActionField, value: unknown, required = field.required): value is JsonValue {
  if (value === undefined || value === null) return !required;
  if (value === '' && required) return false;
  if (typeof value === 'string' && value.includes('{{')) return true;
  if (field.type === 'integer' && (!Number.isSafeInteger(value) || !Number.isFinite(value))) return false;
  if (field.type === 'number' && (typeof value !== 'number' || !Number.isFinite(value))) return false;
  if (field.type === 'boolean') return typeof value === 'boolean';
  if (field.type === 'json') return isJsonValue(value);
  if (field.type === 'condition') return conditionSchema.safeParse(value).success;
  if (field.type === 'select') return typeof value === 'string' && Boolean(field.options?.includes(value));
  if (STRING_FIELD_TYPES.has(field.type)) {
    if (typeof value !== 'string') return false;
    if (field.minLength !== undefined && value.length < field.minLength) return false;
    if (field.maxLength !== undefined && value.length > field.maxLength) return false;
    if (field.pattern !== undefined) {
      const match = value.match(new RegExp(field.pattern));
      if (!match || match.index !== 0 || match[0].length !== value.length) return false;
    }
  }
  if (typeof value === 'number') {
    if (field.min !== undefined && value < field.min) return false;
    if (field.max !== undefined && value > field.max) return false;
  }
  return true;
}

export function parseActionRegistry(input: unknown): ActionRegistry {
  return actionRegistrySchema.parse(input);
}

export const actionRegistry = parseActionRegistry(rawRegistry);
export const actionsById: ReadonlyMap<string, ActionDefinition> = new Map(
  actionRegistry.actions.map((action) => [action.id, action]),
);

export function getActionDefaults(actionType: string): Record<string, JsonValue> {
  const action = actionsById.get(actionType);
  if (!action) return {};
  return structuredClone(action.defaults) as Record<string, JsonValue>;
}

export function normalizeParameterValue(field: ActionField, value: unknown): JsonValue | undefined {
  if (value === undefined || value === null || value === '') return undefined;
  if (field.type === 'integer' || field.type === 'number') {
    const parsed = typeof value === 'number' ? value : Number(value);
    return Number.isFinite(parsed) && (field.type !== 'integer' || Number.isInteger(parsed))
      ? parsed
      : String(value);
  }
  if (field.type === 'boolean') {
    if (value === true || value === 'true') return true;
    if (value === false || value === 'false') return false;
    return String(value);
  }
  if (field.type === 'json' || field.type === 'condition') {
    if (typeof value !== 'string') return isJsonValue(value) ? value : String(value);
    try { return JSON.parse(value) as JsonValue; } catch { return value; }
  }
  return typeof value === 'string' ? value : String(value);
}

function isJsonValue(value: unknown): value is JsonValue {
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return true;
  if (typeof value === 'number') return Number.isFinite(value) && (!Number.isInteger(value) || Number.isSafeInteger(value));
  if (Array.isArray(value)) return value.every(isJsonValue);
  return typeof value === 'object' && Object.values(value as Record<string, unknown>).every(isJsonValue);
}
