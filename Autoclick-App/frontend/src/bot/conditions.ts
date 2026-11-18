import { z } from 'zod';
import { jsonNumberSchema, type JsonValue } from '@/bot/schema';

export const CONDITION_OPERATORS = [
  'eq', 'ne', 'lt', 'lte', 'gt', 'gte', 'contains', 'startsWith', 'endsWith',
  'in', 'empty', 'notEmpty',
] as const;
export type ConditionOperator = (typeof CONDITION_OPERATORS)[number];
export type ConditionClause = { left: JsonValue; operator: ConditionOperator; right?: JsonValue };
export type Condition = { combinator: 'all' | 'any'; clauses: ConditionClause[] };

const jsonValue: z.ZodType<JsonValue> = z.lazy(() => z.union([
  z.string(), jsonNumberSchema, z.boolean(), z.null(), z.array(jsonValue), z.record(z.string(), jsonValue),
]));
const unary = new Set<ConditionOperator>(['empty', 'notEmpty']);
export const conditionSchema: z.ZodType<Condition> = z.object({
  combinator: z.enum(['all', 'any']),
  clauses: z.array(z.object({
    left: jsonValue,
    operator: z.enum(CONDITION_OPERATORS),
    right: jsonValue.optional(),
  }).strict().superRefine((clause, context) => {
    if (!unary.has(clause.operator) && clause.right === undefined) {
      context.addIssue({ code: 'custom', path: ['right'], message: 'Binary operators require a right operand' });
    }
  })).min(1),
}).strict();

export function evaluateCondition(condition: Condition): boolean {
  const values = condition.clauses.map(evaluateClause);
  return condition.combinator === 'all' ? values.every(Boolean) : values.some(Boolean);
}

export function evaluateClause({ left, operator, right }: ConditionClause): boolean {
  if (operator === 'empty') return isEmptiable(left) && !collectionSize(left);
  if (operator === 'notEmpty') return isEmptiable(left) && collectionSize(left) > 0;
  if (operator === 'eq') return jsonEqual(left, right);
  if (operator === 'ne') return !jsonEqual(left, right);
  if (['lt', 'lte', 'gt', 'gte'].includes(operator)) {
    if (!sameOrderedType(left, right)) return false;
    const comparison = typeof left === 'string'
      ? compareCodePoints(left, right as string)
      : (left as number) < (right as number) ? -1 : (left as number) > (right as number) ? 1 : 0;
    return operator === 'lt' ? comparison < 0 : operator === 'lte' ? comparison <= 0 : operator === 'gt' ? comparison > 0 : comparison >= 0;
  }
  if (operator === 'contains') {
    if (typeof left === 'string' && typeof right === 'string') return left.includes(right);
    return Array.isArray(left) && left.some((item) => jsonEqual(item, right));
  }
  if (operator === 'startsWith') return typeof left === 'string' && typeof right === 'string' && left.startsWith(right);
  if (operator === 'endsWith') return typeof left === 'string' && typeof right === 'string' && left.endsWith(right);
  return operator === 'in' && Array.isArray(right) && right.some((item) => jsonEqual(left, item));
}

function sameOrderedType(left: JsonValue, right: JsonValue | undefined) {
  return typeof left === 'number' && typeof right === 'number' || typeof left === 'string' && typeof right === 'string';
}

function compareCodePoints(left: string, right: string) {
  const a = Array.from(left, (character) => character.codePointAt(0)!);
  const b = Array.from(right, (character) => character.codePointAt(0)!);
  for (let index = 0; index < Math.min(a.length, b.length); index += 1) {
    if (a[index] !== b[index]) return a[index] < b[index] ? -1 : 1;
  }
  return a.length < b.length ? -1 : a.length > b.length ? 1 : 0;
}

function jsonEqual(left: JsonValue, right: JsonValue | undefined): boolean {
  if (right === undefined || Array.isArray(left) !== Array.isArray(right)) return false;
  if (typeof left === 'number' && typeof right === 'number') return left === right;
  if (left === null || right === null || typeof left !== typeof right) return left === right;
  if (Array.isArray(left) && Array.isArray(right)) return left.length === right.length && left.every((item, index) => jsonEqual(item, right[index]));
  if (typeof left === 'object' && typeof right === 'object') {
    const leftRecord = left as Record<string, JsonValue>; const rightRecord = right as Record<string, JsonValue>;
    const leftKeys = Object.keys(leftRecord); const rightKeys = Object.keys(rightRecord);
    return leftKeys.length === rightKeys.length && leftKeys.every((key) => key in rightRecord && jsonEqual(leftRecord[key], rightRecord[key]));
  }
  return left === right;
}

function isEmptiable(value: JsonValue): value is null | string | JsonValue[] | Record<string, JsonValue> {
  return value === null || typeof value === 'string' || Array.isArray(value) || typeof value === 'object';
}
function collectionSize(value: null | string | JsonValue[] | Record<string, JsonValue>) {
  if (value === null) return 0;
  return typeof value === 'object' && !Array.isArray(value) ? Object.keys(value).length : value.length;
}
