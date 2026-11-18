import { AlertTriangle, Check, HelpCircle, Play, X } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { createEditorState } from '@/bot/serialization';
import type { BotEditorState } from '@/bot/model';
import { actionsById } from '@/bot/registry';
import { actionIcons } from '@/features/editor/actionIcons';
import type { CanonicalBot } from '@/bot/schema';
import type { ValidationIssue } from '@/bot/validation';
import { diffBots, type BotDiffStatus } from '@/ai/proposalDiff';
import { ConfigurationPanel } from '@/features/editor/ConfigurationPanel';
import { OverlayDialog } from '@/features/editor/OverlayDialog';
import { SequenceStack } from '@/features/editor/SequenceStack';
import type { BlockExecutionStatus } from '@/execution/state';

const noop = () => {};
const comparisonLegend: Array<{ status: BotDiffStatus; label: string; className: string }> = [
  { status: 'added', label: 'Agregado', className: 'bg-emerald-500' },
  { status: 'removed', label: 'Eliminado', className: 'bg-red-500' },
  { status: 'modified', label: 'Modificado', className: 'bg-amber-500' },
  { status: 'unchanged', label: 'Sin cambios', className: 'bg-blue-500' },
];

function ancestorNodeIds(editor: BotEditorState, nodeId: string): string[] {
  const parentByChild = new Map<string, string>();
  for (const node of editor.nodes) {
    for (const childId of Object.values(node.slots).flat()) parentByChild.set(childId, node.id);
  }
  const ancestors: string[] = [];
  const visited = new Set<string>();
  let parentId = parentByChild.get(nodeId);
  while (parentId && !visited.has(parentId)) {
    visited.add(parentId);
    ancestors.unshift(parentId);
    parentId = parentByChild.get(parentId);
  }
  return ancestors;
}

export function ProposalComparison({
  original,
  proposed,
  proposalEditor,
  goToTargets,
  version,
  summary,
  validationIssues,
  executionStatuses,
  canExecute,
  canAccept,
  canReject,
  accepting,
  editingDisabled,
  editingDisabledReason,
  onExecute,
  onAccept,
  onReject,
  onProposalSelect,
  onProposalToggle,
  onProposalChange,
}: {
  original: CanonicalBot;
  proposed: CanonicalBot;
  proposalEditor: BotEditorState;
  goToTargets: Array<{ id: string; label: string }>;
  version: number;
  summary: string;
  validationIssues: ValidationIssue[];
  executionStatuses: Record<string, BlockExecutionStatus>;
  canExecute: boolean;
  canAccept: boolean;
  canReject: boolean;
  accepting: boolean;
  editingDisabled: boolean;
  editingDisabledReason: string | null;
  onExecute(): void;
  onAccept(): void;
  onReject(): void;
  onProposalSelect(nodeId: string): void;
  onProposalToggle(nodeId: string): void;
  onProposalChange(nodeId: string, fieldName: string, value: unknown): void;
}) {
  const proposalPaneRef = useRef<HTMLElement>(null);
  const [pendingIssueFocus, setPendingIssueFocus] = useState<{
    nodeId: string;
    fieldName?: string;
  } | null>(null);
  const [selectedOriginalNodeId, setSelectedOriginalNodeId] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const originalEditor = useMemo(() => createEditorState(original), [original]);
  const diff = useMemo(() => diffBots(original, proposed), [original, proposed]);
  const hasChanges = useMemo(() => {
    return (
      diff.counts.added > 0 ||
      diff.counts.removed > 0 ||
      diff.counts.modified > 0 ||
      diff.metadata.name ||
      diff.metadata.description ||
      diff.metadata.icon
    );
  }, [diff]);
  const selectedProposalNode = proposalEditor.nodes.find(
    (node) => node.id === proposalEditor.selectedNodeId
  ) ?? null;
  const selectedOriginalNode = originalEditor.nodes.find(
    (node) => node.id === selectedOriginalNodeId
  ) ?? null;
  const activeModalNode = selectedOriginalNode ?? selectedProposalNode;
  const isOriginalModal = Boolean(selectedOriginalNode);
  const activeAction = activeModalNode ? actionsById.get(activeModalNode.data.actionType) : undefined;
  const ActiveActionIcon = activeAction ? actionIcons[activeAction.icon] : HelpCircle;

  useEffect(() => {
    if (proposalEditor.selectedNodeId || selectedOriginalNodeId) {
      setModalOpen(true);
    }
  }, [proposalEditor.selectedNodeId, selectedOriginalNodeId]);

  function handleCloseModal() {
    setModalOpen(false);
    setSelectedOriginalNodeId(null);
    onProposalSelect('');
  }

  const errorCount = validationIssues.filter((issue) => issue.severity === 'error').length;
  const warningCount = validationIssues.length - errorCount;
  const issueDetails = validationIssues.map((issue) => {
    const node = issue.nodeId
      ? proposalEditor.nodes.find((candidate) => candidate.id === issue.nodeId)
      : undefined;
    const action = node ? actionsById.get(node.data.actionType) : undefined;
    const field = action?.fields.find((candidate) => candidate.name === issue.fieldName);

    return {
      ...issue,
      context: [
        action?.title ?? (node ? node.data.actionType : 'Propuesta general'),
        field?.label ?? issue.fieldName,
      ].filter(Boolean).join(' · '),
    };
  });

  useEffect(() => {
    if (!pendingIssueFocus || proposalEditor.selectedNodeId !== pendingIssueFocus.nodeId) return;
    const ancestors = ancestorNodeIds(proposalEditor, pendingIssueFocus.nodeId);
    if (ancestors.some((nodeId) => proposalEditor.collapsedNodeIds.includes(nodeId))) return;

    setPendingIssueFocus(null);
    const blockId = `sequence-block-${pendingIssueFocus.nodeId}`;
    const proposalBlock = proposalPaneRef.current
      ? Array.from(proposalPaneRef.current.querySelectorAll<HTMLElement>('[id]'))
          .find((element) => element.id === blockId)
      : null;
    proposalBlock?.scrollIntoView?.({ block: 'nearest' });
    if (pendingIssueFocus.fieldName) {
      document.getElementById(`field-${pendingIssueFocus.fieldName}`)?.focus();
    }
  }, [pendingIssueFocus, proposalEditor]);

  return (
    <section aria-label="Comparación de propuesta IA" className="flex h-full min-h-0 flex-col bg-slate-100">
      <header className="shrink-0 border-b border-slate-300 bg-white px-4 py-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0 max-w-3xl">
            <div className="flex flex-wrap gap-1.5 text-[11px] font-bold text-text-muted">
              {hasChanges ? (
                <span>{diff.counts.added} agregados · {diff.counts.removed} eliminados · {diff.counts.modified} modificados</span>
              ) : (
                <span>La propuesta no presenta cambios respecto al original</span>
              )}
            </div>
          </div>
          <div className="flex flex-wrap justify-end gap-2">
            <button className="inline-flex h-9 items-center gap-1.5 rounded-control border border-border bg-white px-3 text-[12px] font-bold text-text transition-colors duration-150 hover:border-red-200 hover:bg-red-50 hover:text-danger focus-visible:outline-none focus-visible:shadow-focus disabled:opacity-50" disabled={!canReject || accepting} onClick={onReject} type="button"><X aria-hidden="true" size={15} />Rechazar</button>
            <button className="inline-flex h-9 items-center gap-1.5 rounded-control border border-primary px-3 text-[12px] font-bold text-primary transition-colors duration-150 hover:bg-blue-50 focus-visible:outline-none focus-visible:shadow-focus disabled:opacity-50" disabled={!canExecute || accepting} onClick={onExecute} type="button"><Play aria-hidden="true" size={15} />Ejecutar propuesta</button>
            <button className="inline-flex h-9 items-center gap-1.5 rounded-control bg-primary px-3 text-[12px] font-bold text-white transition-colors duration-150 hover:bg-primary-hover hover:shadow-glow-primary focus-visible:outline-none focus-visible:shadow-focus disabled:opacity-50 disabled:shadow-none" disabled={!canAccept || accepting} onClick={onAccept} type="button"><Check aria-hidden="true" size={15} />{accepting ? 'Aceptando…' : 'Aceptar cambios'}</button>
          </div>
        </div>
        {hasChanges && (
          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-slate-200 pt-2 text-[10px] font-bold text-text-muted" aria-label="Leyenda de comparación">
            {comparisonLegend.map(({ status, label, className }) => <span className="inline-flex items-center gap-1.5" data-status={status} key={status}><span aria-hidden="true" className={`size-2 rounded-full ${className}`} />{label}</span>)}
          </div>
        )}
        {validationIssues.length ? (
          <div className="relative mt-2 overflow-hidden rounded-control border border-amber-200 bg-gradient-to-br from-amber-50 to-orange-50/50 px-3 py-2.5 text-amber-950" role="alert">
            <span aria-hidden="true" className="absolute inset-y-0 left-0 w-[3px] bg-amber-500" />
            <div className="flex items-start gap-2.5 pl-1">
              <span aria-hidden="true" className="mt-0.5 grid size-6 shrink-0 place-items-center rounded-full bg-amber-100 text-amber-700">
                <AlertTriangle aria-hidden="true" size={13} />
              </span>
              <div className="min-w-0 flex-1">
                <p className="m-0 text-[11px] font-bold">
                  {errorCount > 0
                    ? `${errorCount} ${errorCount === 1 ? 'error impide' : 'errores impiden'} aceptar o ejecutar esta propuesta`
                    : `${warningCount} ${warningCount === 1 ? 'advertencia impide' : 'advertencias impiden'} ejecutar esta propuesta`}
                </p>
                <ul className="mt-2 mb-0 max-h-36 space-y-1.5 overflow-y-auto p-0 pr-1">
                  {issueDetails.map((issue, index) => {
                    const key = `${issue.code}-${issue.nodeId ?? 'proposal'}-${issue.fieldName ?? 'general'}-${index}`;
                    const content = <>
                      <p className="m-0 text-[11px] font-bold">{issue.context}</p>
                      <p className="mt-0.5 mb-0 text-[11px] leading-4 text-amber-900">{issue.message}</p>
                    </>;
                    if (!issue.nodeId) {
                      return <li className="list-none rounded-md border border-amber-200 bg-white/65 px-2.5 py-2" key={key}>{content}</li>;
                    }
                    const nodeId = issue.nodeId;
                    return (
                      <li className="list-none" key={key}>
                        <button
                          className="w-full rounded-md border border-amber-200 bg-white/65 px-2.5 py-2 text-left transition-colors duration-150 hover:border-amber-400 focus-visible:outline-none focus-visible:shadow-focus"
                          onClick={() => {
                            setPendingIssueFocus({
                              nodeId,
                              ...(issue.fieldName ? { fieldName: issue.fieldName } : {}),
                            });
                            for (const ancestorId of ancestorNodeIds(proposalEditor, nodeId)) {
                              if (proposalEditor.collapsedNodeIds.includes(ancestorId)) {
                                onProposalToggle(ancestorId);
                              }
                            }
                            setSelectedOriginalNodeId(null);
                            onProposalSelect(nodeId);
                            setModalOpen(true);
                          }}
                          type="button">
                          {content}
                        </button>
                      </li>
                    );
                  })}
                </ul>
                <p className="mt-2 mb-0 text-[11px] leading-4 text-amber-800">
                  Seleccioná un problema o un bloque de la propuesta para corregir sus parámetros.
                </p>
              </div>
            </div>
          </div>
        ) : null}
        {editingDisabledReason ? (
          <p className="mt-2 mb-0 rounded-control border border-amber-300 bg-amber-50 px-3 py-2 text-[11px] font-bold text-amber-900" role="status">
            {editingDisabledReason}
          </p>
        ) : null}
      </header>
      <div className={`grid min-h-0 flex-1 ${hasChanges ? 'grid-cols-1 gap-px overflow-y-auto bg-slate-300 xl:grid-cols-2 xl:overflow-hidden' : 'grid-cols-1 overflow-y-auto bg-slate-50'}`}>
        <section aria-label="Bot original" className="flex min-h-[24rem] min-w-0 flex-col bg-slate-50 xl:min-h-0">
          <h2 className="m-0 shrink-0 border-b border-slate-200 bg-white px-4 py-2 text-sm font-extrabold">Original</h2>
          <div className="min-h-0 flex-1">
            <SequenceStack
              comparisonStatuses={diff.originalStatuses}
              executionStatuses={{}}
              issues={[]}
              onMove={noop}
              onSelect={(nodeId) => {
                setSelectedOriginalNodeId(nodeId);
                setModalOpen(true);
              }}
              onToggle={noop}
              readOnly
              showReadOnlyNotice={false}
              state={originalEditor}
            />
          </div>
        </section>
        {hasChanges && (
          <section aria-label="Propuesta Autoclick AI" className="flex min-h-[24rem] min-w-0 flex-col bg-slate-50 xl:min-h-0" ref={proposalPaneRef}>
            <h2 className="m-0 shrink-0 border-b border-slate-200 bg-white px-4 py-2 text-sm font-extrabold">Propuesta Autoclick AI</h2>
            <div className="min-h-0 flex-1">
              <SequenceStack
                comparisonStatuses={diff.proposedStatuses}
                executionStatuses={executionStatuses}
                issues={validationIssues}
                onMove={noop}
                onSelect={(nodeId) => {
                  setSelectedOriginalNodeId(null);
                  onProposalSelect(nodeId);
                  setModalOpen(true);
                }}
                onToggle={onProposalToggle}
                readOnly
                showReadOnlyNotice={false}
                state={proposalEditor}
              />
            </div>
          </section>
        )}
      </div>

      <OverlayDialog
        ariaLabel="Configuración del bloque"
        className="hidden inset-0 h-screen w-screen p-4 open:grid open:place-items-center"
        focusKey={activeModalNode?.id}
        onDismiss={handleCloseModal}
        open={modalOpen && Boolean(activeModalNode)}>
        <div className="@container max-h-[85vh] w-full max-w-2xl overflow-hidden rounded-panel border border-border bg-surface shadow-overlay">
          <div className="flex items-center gap-3 border-b border-border px-5 pt-4 pb-3.5">
            <span className="grid size-10 shrink-0 place-items-center rounded-control bg-blue-50 text-primary shadow-sm">
              <ActiveActionIcon aria-hidden="true" size={19} />
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <h2 className="m-0 truncate text-lg font-extrabold">
                  {activeAction?.title ?? activeModalNode?.data.actionType}
                </h2>
                <span className={`rounded-full px-2.5 py-0.5 text-[11px] font-bold ${isOriginalModal ? 'bg-slate-100 text-text-muted border border-slate-200' : 'bg-blue-50 text-primary border border-blue-200'}`}>
                  {isOriginalModal ? 'Original · Solo lectura' : 'Propuesta AutoClick AI'}
                </span>
              </div>
            </div>
            <button
              aria-label="Cerrar configuración del bloque"
              className="shrink-0 rounded-control p-1.5 text-text-muted transition-colors hover:bg-black/5 hover:text-text focus-visible:outline-none focus-visible:shadow-focus"
              data-dialog-initial-focus
              onClick={handleCloseModal}
              type="button">
              <X aria-hidden="true" size={18} />
            </button>
          </div>
          <div className="max-h-[calc(85vh-4.5rem)] overflow-y-auto">
            <ConfigurationPanel
              disabled={isOriginalModal || editingDisabled}
              goToTargets={goToTargets}
              hideHeader
              issues={isOriginalModal ? [] : validationIssues}
              node={activeModalNode}
              onChange={(fieldName, value) => {
                if (!isOriginalModal && selectedProposalNode) {
                  onProposalChange(selectedProposalNode.id, fieldName, value);
                }
              }}
            />
          </div>
        </div>
      </OverlayDialog>
    </section>
  );
}
