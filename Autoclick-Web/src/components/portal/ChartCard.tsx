import type { ReactNode } from "react";
import { Panel } from "../ui/Panel";

export function ChartCard({
  eyebrow,
  title,
  description,
  action,
  children,
  className = "",
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <Panel hover spotlight className={`chart-card ${className}`.trim()}>
      <div className="dash-panel__head">
        <div>
          {eyebrow && <p className="dash-eyebrow">{eyebrow}</p>}
          <h2>{title}</h2>
          {description && <p>{description}</p>}
        </div>
        {action}
      </div>
      <div className="chart-card__body">{children}</div>
    </Panel>
  );
}
