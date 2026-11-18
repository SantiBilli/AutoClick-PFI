import { CheckCircle2, CircleAlert, TriangleAlert } from 'lucide-react';
import type { ValidationIssue } from '@/bot/validation';

export function ValidationPanel({
  issues,
  visible,
  onFocus,
}: {
  issues: ValidationIssue[];
  visible: boolean;
  onFocus: (nodeId: string) => void;
}) {
  if (!visible) return null;
  return (
    <section
      aria-label="Resultado de validación"
      className="max-h-36 overflow-y-auto border-t border-border bg-surface px-4 py-3"
      role="status">
      {issues.length === 0 ? (
        <p className="m-0 flex items-center gap-2 text-[12px] font-bold text-success">
          <CheckCircle2 aria-hidden="true" size={16} />
          El flujo está listo para ejecutar.
        </p>
      ) : (
        <>
          <p className="mt-0 mb-2 text-[11px] font-extrabold tracking-[0.07em] uppercase">
            Validación · {issues.length} {issues.length === 1 ? 'hallazgo' : 'hallazgos'}
          </p>
          <ul className="m-0 grid list-none gap-1 p-0 sm:grid-cols-2">
            {issues.map((issue, index) => {
              const Icon = issue.severity === 'error' ? CircleAlert : TriangleAlert;
              const content = (
                <>
                  <Icon aria-hidden="true" className="mt-0.5 shrink-0" size={14} />
                  <span>
                    {issue.message}
                    {issue.fieldName ? ` Campo: ${issue.fieldName}.` : ''}
                  </span>
                </>
              );
              return (
                <li key={`${issue.code}-${issue.nodeId ?? 'flow'}-${issue.fieldName ?? index}`}>
                  {issue.nodeId ? (
                    <button
                      className="flex w-full items-start gap-2 rounded-md px-2 py-1 text-left text-[11px] text-danger transition-colors duration-150 hover:bg-red-50 focus-visible:outline-none focus-visible:shadow-focus"
                      onClick={() => onFocus(issue.nodeId!)}
                      type="button">
                      {content}
                    </button>
                  ) : (
                    <span className="flex items-start gap-2 px-2 py-1 text-[11px] text-danger">
                      {content}
                    </span>
                  )}
                </li>
              );
            })}
          </ul>
        </>
      )}
    </section>
  );
}
