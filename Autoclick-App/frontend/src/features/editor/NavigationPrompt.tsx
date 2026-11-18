import { useCallback, useEffect, useEffectEvent, useImperativeHandle, useLayoutEffect, useRef, useState, type Ref, type RefObject } from 'react';
import { useBlocker, useNavigate } from 'react-router-dom';
import { Button } from '@/components/Button';
import { Mascot } from '@/components/Mascot';
import { OverlayDialog } from '@/features/editor/OverlayDialog';

export type NavigationPromptControl = { resetPendingNavigation: () => void };

export function NavigationPrompt({ protectedState, saving = false, conflict, executionActive = false, onExecutionLeaveAttempt, allowNextNavigationRef, controlRef }: { protectedState: boolean; saving?: boolean; conflict: boolean; executionActive?: boolean; onExecutionLeaveAttempt?: () => void; allowNextNavigationRef?: RefObject<boolean>; controlRef?: Ref<NavigationPromptControl> }) {
  const navigate = useNavigate();
  const acceptedHashRef = useRef(window.location.hash);
  const pendingHashRef = useRef<string | null>(null);
  const traversalHashExpectedRef = useRef(false);
  const guardTraversalRef = useRef<'restore' | 'discard' | null>(null);
  const [directHashBlocked, setDirectHashBlocked] = useState(false);
  const requestExecutionCancel = useEffectEvent(() => onExecutionLeaveAttempt?.());
  const navigationGuardRef = useRef({ protectedState, allowNextNavigationRef });
  // Router registration uses a passive effect. Its installed callback must
  // already reflect the committed draft while that registration catches up.
  useLayoutEffect(() => {
    navigationGuardRef.current = { protectedState, allowNextNavigationRef };
  }, [protectedState, allowNextNavigationRef]);
  const shouldBlockNavigation = useCallback(() => {
    const current = navigationGuardRef.current;
    return !current.allowNextNavigationRef?.current && current.protectedState;
  }, []);
  const blocker = useBlocker(shouldBlockNavigation);

  function resetPendingNavigation() {
    if (blocker.state === 'blocked') blocker.reset();
    pendingHashRef.current = null;
    traversalHashExpectedRef.current = false;
    guardTraversalRef.current = null;
    if (allowNextNavigationRef) allowNextNavigationRef.current = false;
    setDirectHashBlocked(false);
  }

  useImperativeHandle(controlRef, () => ({ resetPendingNavigation }));

  useEffect(() => {
    if (protectedState) return;
    resetPendingNavigation();
  }, [protectedState]);

  useEffect(() => {
    if (executionActive && blocker.state === 'blocked') requestExecutionCancel();
  }, [blocker.state, executionActive]);

  useEffect(() => {
    function guard(event: BeforeUnloadEvent) {
      if (!protectedState) return;
      if (executionActive) requestExecutionCancel();
      event.preventDefault();
      event.returnValue = '';
    }
    window.addEventListener('beforeunload', guard);
    return () => window.removeEventListener('beforeunload', guard);
  }, [executionActive, protectedState]);

  useEffect(() => {
    function guardHashChange(event: HashChangeEvent) {
      const currentHash = window.location.hash;
      if (guardTraversalRef.current === 'restore') {
        event.stopImmediatePropagation();
        guardTraversalRef.current = null;
        traversalHashExpectedRef.current = false;
        return;
      }
      if (guardTraversalRef.current === 'discard') {
        event.stopImmediatePropagation();
        guardTraversalRef.current = null;
        traversalHashExpectedRef.current = false;
        acceptedHashRef.current = currentHash;
        const navigation = navigate(currentHash.slice(1) || '/', { replace: true });
        void Promise.resolve(navigation).finally(() => {
          if (allowNextNavigationRef) allowNextNavigationRef.current = false;
        });
        return;
      }
      if (traversalHashExpectedRef.current) {
        traversalHashExpectedRef.current = false;
        return;
      }
      if (allowNextNavigationRef?.current) {
        acceptedHashRef.current = currentHash;
        return;
      }
      if (!protectedState) {
        acceptedHashRef.current = currentHash;
        return;
      }
      if (currentHash === acceptedHashRef.current) return;

      event.preventDefault();
      event.stopImmediatePropagation();
      pendingHashRef.current = currentHash;
      if (executionActive) requestExecutionCancel();
      if (!conflict) setDirectHashBlocked(true);
      guardTraversalRef.current = 'restore';
      window.history.back();
    }

    function markHistoryTraversal(event: PopStateEvent) {
      if (guardTraversalRef.current === 'restore') {
        event.stopImmediatePropagation();
        window.setTimeout(() => {
          if (guardTraversalRef.current === 'restore') guardTraversalRef.current = null;
        }, 0);
        return;
      }
      if (guardTraversalRef.current === 'discard') {
        event.stopImmediatePropagation();
        return;
      }
      if (typeof event.state?.idx !== 'number') {
        event.stopImmediatePropagation();
        return;
      }
      traversalHashExpectedRef.current = true;
      window.setTimeout(() => { traversalHashExpectedRef.current = false; }, 0);
    }

    window.addEventListener('hashchange', guardHashChange, true);
    window.addEventListener('popstate', markHistoryTraversal, true);
    return () => {
      window.removeEventListener('hashchange', guardHashChange, true);
      window.removeEventListener('popstate', markHistoryTraversal, true);
    };
  }, [allowNextNavigationRef, conflict, executionActive, navigate, protectedState]);

  function keepEditing() {
    if (blocker.state === 'blocked') blocker.reset();
    pendingHashRef.current = null;
    setDirectHashBlocked(false);
  }

  function discardChanges() {
    if (saving) {
      keepEditing();
      return;
    }
    if (blocker.state === 'blocked') {
      blocker.proceed();
      return;
    }
    const targetHash = pendingHashRef.current;
    if (!targetHash) return;
    acceptedHashRef.current = targetHash;
    if (allowNextNavigationRef) allowNextNavigationRef.current = true;
    guardTraversalRef.current = 'discard';
    pendingHashRef.current = null;
    setDirectHashBlocked(false);
    window.history.forward();
  }

  return (
    <OverlayDialog className="hidden inset-0 h-screen w-screen p-4 open:grid open:place-items-center" dismissible={!executionActive} focusKey={executionActive ? 'execution' : 'navigation'} labelledBy="discard-title" onDismiss={keepEditing} open={!conflict && (blocker.state === 'blocked' || directHashBlocked)}>
      <div className="relative w-full max-w-md rounded-panel border border-border bg-surface p-5 pt-10 shadow-overlay">
        <div className="absolute -top-10 -left-4 z-10 drop-shadow-xl">
          <Mascot decorative={false} entrance="bounce" float={false} size={72} state="thinking" />
        </div>
        <h2 className="m-0 text-lg font-extrabold" id="discard-title">{executionActive ? 'Cancelando ejecución' : saving ? 'Guardando cambios' : 'Hay cambios sin guardar'}</h2>
        <p className="mt-2 mb-5 leading-5 text-text-muted">{executionActive ? 'Esperá a que finalice la cancelación y la limpieza antes de salir. Si la solicitud falló o parece detenida, podés reintentarla de forma segura.' : saving ? 'Guardando en disco. Esperá a que termine antes de salir.' : 'Si salís ahora, se perderán los cambios de este bot.'}</p>
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          {executionActive ? <Button data-dialog-initial-focus onClick={onExecutionLeaveAttempt} variant="secondary">Reintentar cancelación</Button> : <Button data-dialog-initial-focus onClick={keepEditing} variant="secondary">Seguir editando</Button>}
          {saving || executionActive ? null : <Button onClick={discardChanges}>Descartar cambios</Button>}
        </div>
      </div>
    </OverlayDialog>
  );
}
