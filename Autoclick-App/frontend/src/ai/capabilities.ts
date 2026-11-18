import { actionRegistry } from '@/bot/registry';
import type { AiActionCapability, AiCapabilities } from '@/ai/types';

export function getActionCapabilities(): AiActionCapability[] {
  return actionRegistry.actions.map(({ id, category, categoryName, title, description, fields, defaults, output, outputs, slots, platform }) => ({
    id,
    category,
    categoryName,
    title,
    description,
    fields: fields.map((field) => ({
      name: field.name,
      label: field.label,
      type: field.type,
      required: field.required,
      ...(field.min === undefined ? {} : { min: field.min }),
      ...(field.max === undefined ? {} : { max: field.max }),
      ...(field.minLength === undefined ? {} : { minLength: field.minLength }),
      ...(field.maxLength === undefined ? {} : { maxLength: field.maxLength }),
      ...(field.pattern === undefined ? {} : { pattern: field.pattern }),
      ...(field.options === undefined ? {} : { options: [...field.options] }),
    })),
    defaults: structuredClone(defaults),
    output: output ? { ...output } : null,
    outputs: outputs.map((item) => ({ ...item })),
    slots: [...slots],
    ...(platform === undefined ? {} : { platform }),
  }));
}

export function getAiCapabilities(): AiCapabilities {
  return {
    catalogVersion: actionRegistry.catalogVersion,
    catalogHash: actionRegistry.catalogHash,
    actions: getActionCapabilities(),
  };
}
