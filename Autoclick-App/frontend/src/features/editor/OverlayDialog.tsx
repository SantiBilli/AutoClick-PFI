import { useEffect, useRef, type KeyboardEvent, type ReactNode } from 'react';

const FOCUSABLE = 'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

type Props = {
  open: boolean;
  onDismiss: () => void;
  children: ReactNode;
  ariaLabel?: string;
  labelledBy?: string;
  className?: string;
  dismissible?: boolean;
  focusKey?: string | number;
  restoreFocus?: boolean;
};

function focusInitialControl(dialog: HTMLDialogElement) {
  const initial = dialog.querySelector<HTMLElement>('[data-dialog-initial-focus]') ?? dialog.querySelector<HTMLElement>(FOCUSABLE);
  initial?.focus();
}

export function OverlayDialog({ open, onDismiss, children, ariaLabel, labelledBy, className = '', dismissible = true, focusKey, restoreFocus = true }: Props) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const openerRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog || !open) return;
    openerRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    if (!dialog.open) dialog.showModal();
    focusInitialControl(dialog);

    return () => {
      if (dialog.open) dialog.close();
      if (restoreFocus) openerRef.current?.focus();
      openerRef.current = null;
    };
  }, [open, restoreFocus]);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog || !open || focusKey === undefined) return;
    focusInitialControl(dialog);
  }, [focusKey]);

  function handleKeyDown(event: KeyboardEvent<HTMLDialogElement>) {
    if (event.key === 'Escape') {
      event.preventDefault();
      if (dismissible) onDismiss();
      return;
    }
    if (event.key !== 'Tab') return;
    const focusable = [...event.currentTarget.querySelectorAll<HTMLElement>(FOCUSABLE)];
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable.at(-1)!;
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  return (
    <dialog
      aria-label={ariaLabel}
      aria-labelledby={labelledBy}
      className={`m-0 max-h-none max-w-none border-0 bg-transparent p-0 text-text backdrop:bg-slate-950/45 ${className}`}
      onCancel={(event) => {
        event.preventDefault();
        if (dismissible) onDismiss();
      }}
      onClick={(event) => {
        if (dismissible && event.target === event.currentTarget) onDismiss();
      }}
      onKeyDown={handleKeyDown}
      ref={dialogRef}>
      {open ? children : null}
    </dialog>
  );
}
