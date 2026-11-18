import { CheckCircle2, Info, TriangleAlert, X } from "lucide-react";
import type { ReactNode } from "react";

interface ToastProps {
  variant?: "success" | "error" | "info";
  title?: string;
  message?: string;
  onDismiss?: () => void;
  children?: ReactNode;
}

export function Toast({ variant = "info", title, message, onDismiss, children }: ToastProps) {
  const Icon = variant === "success" ? CheckCircle2 : variant === "error" ? TriangleAlert : Info;
  return (
    <div className={`ui-toast ui-toast--${variant}`} role="status">
      <Icon className="ui-toast__icon" size={20} aria-hidden="true" />
      <div className="ui-toast__content">
        {title && <strong>{title}</strong>}
        <span>{message ?? children}</span>
      </div>
      {onDismiss && (
        <button className="ui-icon-button" type="button" aria-label="Cerrar aviso" onClick={onDismiss}>
          <X size={16} aria-hidden="true" />
        </button>
      )}
    </div>
  );
}
