import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { AlertTriangle, Info, ShieldAlert } from "lucide-react";

type CalloutVariant = "info" | "notice" | "warning";

const ICONS: Record<CalloutVariant, LucideIcon> = {
  info: Info,
  notice: ShieldAlert,
  warning: AlertTriangle,
};

export function LegalCallout({
  variant = "notice",
  children,
}: {
  variant?: CalloutVariant;
  children: ReactNode;
}) {
  const Icon = ICONS[variant];
  return (
    <div className={`legal-callout legal-callout--${variant}`} role="note">
      <Icon className="legal-callout__icon" size={18} aria-hidden="true" />
      <div>{children}</div>
    </div>
  );
}
