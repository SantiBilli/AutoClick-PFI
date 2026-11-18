import { motion, useReducedMotion } from 'framer-motion';
import { AlertCircle, CheckCircle2, X } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

export type ToastTone = 'success' | 'error';
export type ToastState = {
  id: string;
  message: string;
  tone: ToastTone;
  action?: { label: string; onClick(): void };
};

const TOAST_DURATION_MS = 6000;

export function useToast() {
  const [toast, setToast] = useState<ToastState | null>(null);
  const timerRef = useRef<number | null>(null);
  const dismiss = useCallback(() => {
    if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    timerRef.current = null;
    setToast(null);
  }, []);
  const show = useCallback((message: string, options: { tone?: ToastTone; action?: ToastState['action'] } = {}) => {
    if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    const next = { id: crypto.randomUUID(), message, tone: options.tone ?? 'success', action: options.action };
    setToast(next);
    timerRef.current = window.setTimeout(() => {
      setToast((current) => current?.id === next.id ? null : current);
      timerRef.current = null;
    }, TOAST_DURATION_MS);
  }, []);
  useEffect(() => () => {
    if (timerRef.current !== null) window.clearTimeout(timerRef.current);
  }, []);
  return { toast, show, dismiss };
}

export function ToastViewport({ toast, onDismiss }: { toast: ToastState | null; onDismiss(): void }) {
  const reduceMotion = Boolean(useReducedMotion());
  if (!toast) return null;
  const Icon = toast.tone === 'error' ? AlertCircle : CheckCircle2;
  return createPortal(
    <div aria-atomic="true" aria-live="polite" className="pointer-events-none fixed inset-x-0 bottom-4 z-50 flex justify-center px-3">
      <motion.div
        animate={{ opacity: 1, y: 0, scale: 1 }}
        className={`pointer-events-auto flex max-w-md items-center gap-2.5 rounded-control border px-3.5 py-2.5 text-[12px] font-bold shadow-overlay ${toast.tone === 'error' ? 'border-red-200 bg-white text-red-950' : 'border-border bg-sidebar text-white'}`}
        initial={reduceMotion ? { opacity: 1, y: 0, scale: 1 } : { opacity: 0, y: 6, scale: 0.96 }}
        role="status"
        transition={reduceMotion ? { duration: 0 } : { duration: 0.18, ease: [0.16, 1, 0.3, 1] }}>
        <Icon aria-hidden="true" className={toast.tone === 'error' ? 'text-danger' : 'text-emerald-400'} size={16} />
        <span className="min-w-0 truncate">{toast.message}</span>
        {toast.action ? <button className="shrink-0 rounded-control px-2 py-1 font-extrabold underline-offset-2 hover:underline focus-visible:outline-none focus-visible:shadow-focus" onClick={() => { toast.action?.onClick(); onDismiss(); }} type="button">{toast.action.label}</button> : null}
        <button aria-label="Cerrar notificación" className="shrink-0 text-current/60 hover:text-current focus-visible:outline-none focus-visible:shadow-focus" onClick={onDismiss} type="button">
          <X aria-hidden="true" size={14} />
        </button>
      </motion.div>
    </div>,
    document.body,
  );
}
