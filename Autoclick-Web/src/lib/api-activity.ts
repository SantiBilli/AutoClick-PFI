"use client";
import { useSyncExternalStore } from 'react';
type Activity = { pending: number; message: string; error: boolean };
const initial: Activity = { pending: 0, message: '', error: false };
let state = initial;
let timer: ReturnType<typeof setTimeout> | undefined;
const listeners = new Set<() => void>();
function publish(next: Activity) { state = next; listeners.forEach(fn => fn()); }
function subscribe(fn: () => void) { listeners.add(fn); return () => { listeners.delete(fn); }; }
export function useApiActivity() { return useSyncExternalStore(subscribe, () => state, () => initial); }
export function isApiPending() { return state.pending > 0; }
export function showSuccess(message: string) {
  clearTimeout(timer);
  publish({ ...state, message, error: false });
  if (!state.pending) timer = setTimeout(() => publish({ ...state, message: '' }), 3000);
}
export async function trackActivity<T>(work: () => Promise<T>, success = ''): Promise<T> {
  clearTimeout(timer);
  publish({ pending: state.pending + 1, message: state.pending || (!success && !state.error) ? state.message : '', error: state.pending ? state.error : false });
  try {
    const result = await work();
    if (success && !state.error) publish({ ...state, message: success });
    return result;
  } catch (error) {
    publish({ ...state, error: true, message: error instanceof Error ? error.message : 'No se pudo completar la operación.' });
    throw error;
  } finally {
    publish({ ...state, pending: state.pending - 1 });
    if (!state.pending && state.message) timer = setTimeout(() => publish({ ...state, message: '', error: false }), state.error ? 6000 : 3000);
  }
}
