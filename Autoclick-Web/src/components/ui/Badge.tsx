import type { HTMLAttributes } from "react";

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: "blue" | "cyan" | "slate" | "green" | "red" | "amber";
}

export function Badge({ className = "", tone = "slate", ...props }: BadgeProps) {
  return <span className={`ui-badge ui-badge--${tone} ${className}`.trim()} {...props} />;
}
