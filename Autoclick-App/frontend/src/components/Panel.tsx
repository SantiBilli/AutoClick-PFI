import type { HTMLAttributes } from 'react';

export function Panel({ className = '', ...props }: HTMLAttributes<HTMLDivElement>) {
  return <section className={`rounded-panel border border-border bg-surface shadow-card ${className}`} {...props} />;
}
