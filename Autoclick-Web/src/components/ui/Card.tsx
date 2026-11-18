import type { HTMLAttributes } from "react";

export interface CardProps extends HTMLAttributes<HTMLElement> {
  as?: "article" | "div" | "section";
  hover?: boolean;
}

export function Card({ as: Element = "section", hover = false, className = "", ...props }: CardProps) {
  return <Element className={`ui-card ${hover ? "ui-card--hover" : ""} ${className}`.trim()} {...props} />;
}
