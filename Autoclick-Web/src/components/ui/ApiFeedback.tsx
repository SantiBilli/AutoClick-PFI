"use client";
import type { ReactNode } from 'react';
import { useEffect } from 'react';
import { CheckCircle2, LoaderCircle, AlertCircle } from 'lucide-react';
import { isApiPending, showSuccess, useApiActivity } from '../../lib/api-activity';
export function ApiFeedback({ children }: { children: ReactNode }) {
  const { pending, message, error } = useApiActivity();
  useEffect(() => {
    if (sessionStorage.getItem('autoclick-logged-out')) {
      sessionStorage.removeItem('autoclick-logged-out');
      showSuccess('Sesión cerrada correctamente.');
    }
  }, []);
  return <>
    {/* FormData omits disabled fields, even after the activity store has settled. */}
    <fieldset className="api-boundary" disabled={pending > 0} aria-busy={pending > 0}
      onSubmitCapture={event => { if (isApiPending() || event.currentTarget.disabled) { event.preventDefault(); event.stopPropagation(); } }}>
      {children}
    </fieldset>
    <div className={`api-feedback ${error ? 'api-feedback--error' : ''}`} role={error ? 'alert' : 'status'} aria-live={error ? 'assertive' : 'polite'}>
      {pending ? <><LoaderCircle className="api-spinner" size={18} /> Procesando…</> : message ? <>{error ? <AlertCircle size={18} /> : <CheckCircle2 size={18} />}{message}</> : null}
    </div>
  </>;
}
