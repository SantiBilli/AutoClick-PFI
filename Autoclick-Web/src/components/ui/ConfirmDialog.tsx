"use client";
import type { ReactNode } from "react";
import { Modal } from "./Modal";
import { Button } from "./Button";

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = "Confirmar",
  cancelLabel = "Cancelar",
  tone = "default",
  loading = false,
  onConfirm,
  onClose,
}: {
  open: boolean;
  title: string;
  description?: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: "default" | "danger";
  loading?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}) {
  return (
    <Modal open={open} title={title} onClose={onClose}>
      <div className="confirm-dialog">
        {description && <p className="portal-muted">{description}</p>}
        <div className="dialog-actions">
          <Button type="button" variant="ghost" onClick={onClose} disabled={loading}>{cancelLabel}</Button>
          <Button type="button" variant={tone === "danger" ? "danger" : "primary"} onClick={onConfirm} disabled={loading}>{confirmLabel}</Button>
        </div>
      </div>
    </Modal>
  );
}
