import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { RevealItem } from "../ui/Reveal";

export function LegalSummaryCard({
  icon: Icon,
  title,
  children,
}: {
  icon: LucideIcon;
  title: string;
  children: ReactNode;
}) {
  return (
    <RevealItem as="article" className="ui-card legal-summary-card">
      <span className="legal-summary-card__icon">
        <Icon size={20} aria-hidden="true" />
      </span>
      <h3>{title}</h3>
      {typeof children === "string" ? <p>{children}</p> : children}
    </RevealItem>
  );
}
