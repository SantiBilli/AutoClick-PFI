"use client";

import { useEffect, useId, useRef } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { isApiPending } from "../../lib/api-activity";
import { X } from "lucide-react";
import type { ReactNode } from "react";
import { easeOutExpo } from "../../lib/motion";

interface ModalProps {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
}

export function Modal({ open, title, onClose, children }: ModalProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);
  const titleId = useId();
  const reduceMotion = useReducedMotion();
  onCloseRef.current = () => { if (!isApiPending()) onClose(); };

  useEffect(() => {
    if (!open) return;

    previousFocusRef.current = document.activeElement as HTMLElement | null;
    const focusable = dialogRef.current?.querySelector<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
    );
    (focusable ?? dialogRef.current)?.focus();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !(event.target as HTMLElement).closest("[data-select-popup]")) {
        onCloseRef.current();
        return;
      }

      if (event.key !== "Tab" || !dialogRef.current || (event.target as HTMLElement).closest("[data-select-popup]")) return;
      const elements = Array.from(
        dialogRef.current.querySelectorAll<HTMLElement>(
          'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
        ),
      ).filter((element) => !element.hasAttribute("disabled"));
      if (elements.length === 0) return;
      const first = elements[0];
      const last = elements[elements.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    const handleFocusIn = (event: FocusEvent) => {
      if (dialogRef.current && !dialogRef.current.contains(event.target as Node) && !(event.target as HTMLElement).closest("[data-select-popup]")) {
        dialogRef.current.focus();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    document.addEventListener("focusin", handleFocusIn);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.removeEventListener("focusin", handleFocusIn);
      previousFocusRef.current?.focus();
    };
  }, [open]);

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="ui-modal-backdrop"
          role="presentation"
          onMouseDown={() => onCloseRef.current()}
          initial={reduceMotion ? false : { opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={reduceMotion ? undefined : { opacity: 0 }}
          transition={{ duration: 0.2, ease: easeOutExpo }}
        >
          <motion.div
            ref={dialogRef}
            tabIndex={-1}
            className="ui-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
            onMouseDown={(event) => event.stopPropagation()}
            initial={reduceMotion ? false : { opacity: 0, y: 20, scale: 0.95, filter: "blur(6px)" }}
            animate={{ opacity: 1, y: 0, scale: 1, filter: "blur(0px)" }}
            exit={reduceMotion ? undefined : { opacity: 0, y: 10, scale: 0.97, filter: "blur(3px)" }}
            transition={reduceMotion ? { duration: 0.15 } : { type: "spring", stiffness: 340, damping: 30 }}
          >
            <div className="ui-modal__header">
              <h2 id={titleId}>{title}</h2>
              <button className="ui-icon-button" type="button" aria-label="Cerrar" onClick={() => onCloseRef.current()}>
                <X size={18} aria-hidden="true" />
              </button>
            </div>
            <div className="ui-modal__body">{children}</div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
