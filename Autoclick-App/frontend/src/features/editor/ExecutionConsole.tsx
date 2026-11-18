import {
  AlertCircle,
  Check,
  ChevronDown,
  ChevronUp,
  Clipboard,
  Info,
  Trash2,
  TriangleAlert,
} from 'lucide-react';
import { useEffect, useEffectEvent, useId, useRef, useState } from 'react';
import type { ExecutionEvent } from '@/app/DesktopBridge';
import { Mascot } from '@/components/Mascot';
import type { ExecutionState } from '@/execution/state';

type Filter = 'all' | ExecutionEvent['level'];

const filters: { value: Filter; label: string }[] = [
  { value: 'all', label: 'Todos' },
  { value: 'info', label: 'Información' },
  { value: 'warning', label: 'Advertencias' },
  { value: 'error', label: 'Errores' },
];
const statusLabels: Record<ExecutionState['status'], string> = {
  idle: 'Sin ejecutar',
  starting: 'Iniciando',
  running: 'Ejecutando',
  cancel_requested: 'Cancelando',
  succeeded: 'Completado',
  failed: 'Falló',
  cancelled: 'Cancelado',
};
const TRUNCATED_OUTPUT_NOTICE =
  'Aviso: el historial está incompleto porque se omitieron eventos anteriores.';

function eventTime(event: ExecutionEvent): string {
  return new Date(event.timestamp).toLocaleTimeString('es-AR', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
}

function eventStep(event: ExecutionEvent): string | null {
  if (!event.blockName) return null;
  return event.blockIndex === undefined ? event.blockName : `Paso ${event.blockIndex + 1}: ${event.blockName}`;
}

function eventLine(event: ExecutionEvent): string {
  const time = eventTime(event);
  const block = event.blockName
    ? ` · ${event.blockIndex === undefined ? '' : `${event.blockIndex + 1}. `}${event.blockName}`
    : '';
  const path = event.blockPath?.length ? ` · ${event.blockPath.join(' / ')}` : '';
  const detail = event.details ? ` · ${event.details}` : '';
  const code = event.code ? ` · ${event.code}` : '';
  return `${time} · ${event.level.toUpperCase()}${block}${path} · ${event.message}${detail}${code}`;
}

const MIN_CONSOLE_HEIGHT = 160;
const MAX_CONSOLE_HEIGHT = 520;
const MIN_EDITOR_WORKSPACE_HEIGHT = 240;

function reachableMaximum() {
  return Math.max(
    MIN_CONSOLE_HEIGHT,
    Math.min(MAX_CONSOLE_HEIGHT, window.innerHeight - MIN_EDITOR_WORKSPACE_HEIGHT)
  );
}

function clampHeight(value: number, maximum: number) {
  return Math.min(maximum, Math.max(MIN_CONSOLE_HEIGHT, value));
}

function lastErrorEvent(events: ExecutionEvent[]) {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    if (events[index].level === 'error') return events[index];
  }
  return null;
}

const EVENT_TONE = {
  error: { Icon: AlertCircle, chip: 'bg-red-500/15 text-red-300', label: 'Error' },
  warning: { Icon: TriangleAlert, chip: 'bg-amber-500/15 text-amber-300', label: 'Advertencia' },
  success: { Icon: Check, chip: 'bg-emerald-500/15 text-emerald-300', label: 'Información' },
  info: { Icon: Info, chip: 'bg-blue-500/15 text-blue-300', label: 'Información' },
} as const;

function eventTone(event: ExecutionEvent) {
  if (event.level === 'error') return EVENT_TONE.error;
  if (event.level === 'warning') return EVENT_TONE.warning;
  if (event.type.endsWith('succeeded')) return EVENT_TONE.success;
  return EVENT_TONE.info;
}

export function ExecutionConsole({
  execution,
  currentBlockName = null,
}: {
  execution: ExecutionState;
  currentBlockName?: string | null;
}) {
  const panelId = useId();
  const [open, setOpen] = useState(false);
  const [maximumHeight, setMaximumHeight] = useState(reachableMaximum);
  const [height, setHeight] = useState(() => clampHeight(240, reachableMaximum()));
  const [filter, setFilter] = useState<Filter>('all');
  const [displayFloor, setDisplayFloor] = useState(0);
  const [copyFeedback, setCopyFeedback] = useState('');
  const initialErrorKey = execution.error
    ? `${execution.error.code}:${execution.error.message}`
    : null;
  const previousErrorKeyRef = useRef(initialErrorKey);
  const previousStatusRef = useRef(execution.status);
  const initialErrorEvent = lastErrorEvent(execution.events);
  const latestErrorEventRef = useRef(
    initialErrorEvent ? `${initialErrorEvent.runId}:${initialErrorEvent.sequence}` : null
  );
  const dragRef = useRef<{ startY: number; startHeight: number } | null>(null);

  useEffect(() => {
    if (execution.status === 'starting') {
      setOpen(true);
      setDisplayFloor(0);
      setCopyFeedback('');
    }
  }, [execution.status]);

  const errorKey = execution.error ? `${execution.error.code}:${execution.error.message}` : null;
  useEffect(() => {
    if (errorKey && errorKey !== previousErrorKeyRef.current) setOpen(true);
    previousErrorKeyRef.current = errorKey;
  }, [errorKey]);

  const latestErrorEvent = lastErrorEvent(execution.events);
  const latestErrorEventKey = latestErrorEvent
    ? `${latestErrorEvent.runId}:${latestErrorEvent.sequence}`
    : null;
  useEffect(() => {
    if (latestErrorEventKey && latestErrorEventKey !== latestErrorEventRef.current) setOpen(true);
    latestErrorEventRef.current = latestErrorEventKey;
  }, [latestErrorEventKey]);

  useEffect(() => {
    if (execution.status === 'failed' && previousStatusRef.current !== 'failed') setOpen(true);
    previousStatusRef.current = execution.status;
  }, [execution.status]);

  const resizeToViewport = useEffectEvent(() => {
    const nextMaximum = reachableMaximum();
    setMaximumHeight(nextMaximum);
    setHeight((current) => clampHeight(current, nextMaximum));
  });
  useEffect(() => {
    window.addEventListener('resize', resizeToViewport);
    return () => window.removeEventListener('resize', resizeToViewport);
  }, []);

  const locallyVisible = execution.events.filter((event) => event.sequence > displayFloor);
  const visibleEvents =
    filter === 'all' ? locallyVisible : locallyVisible.filter((event) => event.level === filter);
  const errorCount = locallyVisible.filter((event) => event.level === 'error').length;
  const progress =
    execution.currentBlockIndex === null
      ? `0 de ${execution.totalBlocks}`
      : `${Math.min(execution.currentBlockIndex + 1, execution.totalBlocks)} de ${execution.totalBlocks}`;
  const progressLabel = currentBlockName ? `${progress} · ${currentBlockName}` : progress;

  function clearVisibleView() {
    setDisplayFloor(
      Math.max(execution.cursor, ...execution.events.map((event) => event.sequence), 0)
    );
    setCopyFeedback('Vista local limpiada.');
  }

  async function copyVisible() {
    if (visibleEvents.length === 0 && !execution.eventsTruncated) return;
    try {
      const lines = visibleEvents.map(eventLine);
      if (execution.eventsTruncated) lines.unshift(TRUNCATED_OUTPUT_NOTICE);
      await navigator.clipboard.writeText(lines.join('\n'));
      setCopyFeedback('Eventos visibles copiados.');
    } catch {
      setCopyFeedback('No se pudieron copiar los eventos.');
    }
  }

  function beginResize(event: React.PointerEvent<HTMLDivElement>) {
    dragRef.current = { startY: event.clientY, startHeight: height };
    try {
      event.currentTarget.setPointerCapture(event.pointerId);
    } catch {
      // Pointer capture may be unavailable in embedded or synthetic environments.
    }
  }

  function resize(event: React.PointerEvent<HTMLDivElement>) {
    if (!dragRef.current) return;
    setHeight(
      clampHeight(
        dragRef.current.startHeight + dragRef.current.startY - event.clientY,
        maximumHeight
      )
    );
  }

  function finishResize() {
    dragRef.current = null;
  }

  function resizeWithKeyboard(event: React.KeyboardEvent<HTMLDivElement>) {
    const change = event.shiftKey ? 40 : 10;
    let next: number | null = null;
    if (event.key === 'ArrowUp') next = height + change;
    if (event.key === 'ArrowDown') next = height - change;
    if (event.key === 'Home') next = MIN_CONSOLE_HEIGHT;
    if (event.key === 'End') next = maximumHeight;
    if (next === null) return;
    event.preventDefault();
    setHeight(clampHeight(next, maximumHeight));
  }

  return (
    <footer
      className="flex shrink-0 flex-col border-t border-slate-700 bg-sidebar text-slate-200"
      aria-label="Actividad de ejecución"
      style={open ? { height } : undefined}>
      {open ? (
        <div
          aria-label="Redimensionar actividad"
          aria-orientation="horizontal"
          aria-valuemax={maximumHeight}
          aria-valuemin={MIN_CONSOLE_HEIGHT}
          aria-valuenow={height}
          className="h-2 cursor-row-resize touch-none bg-slate-800 hover:bg-primary focus-visible:outline-none focus-visible:shadow-focus"
          onKeyDown={resizeWithKeyboard}
          onPointerDown={beginResize}
          onLostPointerCapture={finishResize}
          onPointerMove={resize}
          onPointerCancel={finishResize}
          onPointerUp={finishResize}
          role="separator"
          tabIndex={0}
        />
      ) : null}
      <div className="flex min-h-10 flex-wrap items-center gap-x-3 gap-y-1 px-3 py-1.5 text-[11px] sm:px-4">
        <button
          aria-controls={panelId}
          aria-expanded={open}
          className="flex items-center gap-2 rounded-md font-extrabold text-white transition-colors duration-150 hover:text-sky-300"
          onClick={() => setOpen((value) => !value)}
          type="button">
          {open ? (
            <ChevronDown aria-hidden="true" size={15} />
          ) : (
            <ChevronUp aria-hidden="true" size={15} />
          )}
          Actividad
        </button>
        <span aria-live="polite" className="font-bold text-slate-300">
          {statusLabels[execution.status]} · {progressLabel}
        </span>
        <span className={errorCount ? 'font-bold text-red-300' : 'text-slate-400'}>
          {errorCount} {errorCount === 1 ? 'error' : 'errores'}
        </span>
        {execution.eventsTruncated && !open ? (
          <span
            className="flex items-center gap-1 font-bold text-amber-300"
            title={TRUNCATED_OUTPUT_NOTICE}>
            <TriangleAlert aria-hidden="true" size={13} /> Historial incompleto
          </span>
        ) : null}
        {open ? (
          <div className="ml-auto flex flex-wrap items-center gap-1.5">
            <button
              aria-label="Limpiar vista de actividad"
              className="rounded-md p-1.5 transition-colors duration-150 hover:bg-slate-700 focus-visible:outline-none focus-visible:shadow-focus disabled:opacity-40"
              disabled={locallyVisible.length === 0}
              onClick={clearVisibleView}
              title="Limpiar vista"
              type="button">
              <Trash2 aria-hidden="true" size={14} />
            </button>
            <button
              aria-label="Copiar eventos visibles"
              className="rounded-md p-1.5 transition-colors duration-150 hover:bg-slate-700 focus-visible:outline-none focus-visible:shadow-focus disabled:opacity-40"
              disabled={visibleEvents.length === 0 && !execution.eventsTruncated}
              onClick={() => void copyVisible()}
              title="Copiar visibles"
              type="button">
              <Clipboard aria-hidden="true" size={14} />
            </button>
            <button
              aria-label="Contraer actividad"
              className="rounded-md p-1.5 transition-colors duration-150 hover:bg-slate-700 focus-visible:outline-none focus-visible:shadow-focus"
              onClick={() => setOpen(false)}
              type="button">
              <ChevronDown aria-hidden="true" size={15} />
            </button>
          </div>
        ) : null}
      </div>
      {open ? (
        <div className="flex min-h-0 flex-1 flex-col border-t border-slate-700" id={panelId}>
          <div className="flex flex-wrap items-center gap-1 border-b border-slate-700 px-3 py-2 sm:px-4">
            {filters.map((item) => (
              <button
                aria-pressed={filter === item.value}
                className={`rounded-full px-2.5 py-1 text-[10px] font-bold transition-colors duration-150 focus-visible:outline-none focus-visible:shadow-focus ${filter === item.value ? 'bg-blue-500 text-white' : 'bg-slate-700 text-slate-200 hover:bg-slate-600'}`}
                key={item.value}
                onClick={() => setFilter(item.value)}
                type="button">
                {item.label}
              </button>
            ))}
            <span aria-live="polite" className="ml-auto text-[10px] text-slate-300" role="status">
              {copyFeedback}
            </span>
          </div>
          {execution.error ? (
            <div
              className="flex items-start gap-2 border-b border-red-900 bg-red-950/50 px-4 py-2 text-[11px] text-red-200"
              role="alert">
              <AlertCircle aria-hidden="true" className="mt-0.5 shrink-0" size={14} />
              <span>
                {execution.error.message}{' '}
                <span className="font-mono text-[10.5px] text-red-300/70">({execution.error.code})</span>
              </span>
            </div>
          ) : null}
          {execution.eventsTruncated ? (
            <div
              aria-label="Historial de eventos incompleto"
              className="flex items-start gap-2 border-b border-amber-800 bg-amber-950/40 px-4 py-2 text-[11px] text-amber-200"
              role="status">
              <TriangleAlert aria-hidden="true" className="mt-0.5 shrink-0" size={14} />
              <span>{TRUNCATED_OUTPUT_NOTICE}</span>
            </div>
          ) : null}
          <div
            className="min-h-0 flex-1 overflow-y-auto px-3 py-2 sm:px-4"
            role="log"
            aria-label="Eventos de ejecución">
            {visibleEvents.length === 0 ? (
              locallyVisible.length ? (
                <p className="m-0 py-6 text-center text-[12.5px] text-slate-400">No hay eventos para este filtro.</p>
              ) : execution.runId ? (
                <p className="m-0 py-6 text-center text-[12.5px] text-slate-400">No hay eventos visibles.</p>
              ) : (
                <div className="grid place-items-center gap-1.5 py-8 text-center">
                  <Mascot float={false} size={40} state="idle" />
                  <p className="m-0 text-[12.5px] font-bold text-slate-100">Todavía no ejecutaste este bot.</p>
                  <p className="m-0 max-w-[240px] text-[11.5px] leading-4 text-slate-400">
                    Presioná Ejecutar y vas a ver acá, paso a paso, qué hace tu bot.
                  </p>
                </div>
              )
            ) : (
              visibleEvents.map((event) => {
                const tone = eventTone(event);
                const step = eventStep(event);
                const path = event.blockPath?.length ? event.blockPath.join(' / ') : null;
                return (
                  <div
                    className="flex items-start gap-2.5 border-b border-slate-800 py-2.5 last:border-0"
                    key={`${event.runId}-${event.sequence}`}>
                    <span className={`grid size-6 shrink-0 place-items-center rounded-full ${tone.chip}`}>
                      <tone.Icon aria-label={tone.label} size={13} />
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="m-0 text-[12.5px] leading-5 break-words text-slate-100">
                        {event.message}
                        {event.details ? <span className="text-slate-400"> — {event.details}</span> : null}
                      </p>
                      <p className="m-0 mt-0.5 flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-[10.5px] text-slate-500">
                        <span>{eventTime(event)}</span>
                        {step ? <span>· {step}</span> : null}
                        {path ? <span className="font-mono">· {path}</span> : null}
                        {event.code ? <span className="rounded bg-slate-800 px-1 py-px font-mono text-[9.5px]">{event.code}</span> : null}
                      </p>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>
      ) : null}
    </footer>
  );
}
