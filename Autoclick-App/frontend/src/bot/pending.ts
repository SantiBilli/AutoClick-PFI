import type { ActionField } from '@/bot/registry';

export function isPendingParameter(value: unknown): boolean {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    && Object.keys(value).length === 1 && (value as Record<string, unknown>).$pending === true;
}

export function allowsPendingParameter(field: Pick<ActionField, 'type' | 'name'>): boolean {
  return field.type !== 'variable' && field.name !== 'targetNodeId';
}
