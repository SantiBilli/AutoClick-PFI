import { useEffect, useEffectEvent } from 'react';
import type {
  ApiError,
  ApiErrorCode,
  ApiResponse,
  ExecutionStatusErrorCode,
  ExecutionStatusResult,
} from '@/app/DesktopBridge';

export const EXECUTION_POLL_INTERVAL_MS = 150;

type StatusResponse = ApiResponse<
  ExecutionStatusResult,
  ExecutionStatusErrorCode | 'DESKTOP_BRIDGE_UNAVAILABLE'
>;
type PollTimer = ReturnType<typeof setTimeout>;
type ExecutionPollerOptions = {
  runId: string;
  initialCursor: number;
  poll: (runId: string, afterSequence: number) => Promise<StatusResponse>;
  onStatus: (result: ExecutionStatusResult) => void;
  onError: (error: ApiError<ApiErrorCode>) => void;
  intervalMs?: number;
};

const terminalStatuses = new Set(['succeeded', 'failed', 'cancelled']);

export function createExecutionPoller(options: ExecutionPollerOptions): () => void {
  let cursor = options.initialCursor;
  let timer: PollTimer | null = null;
  let stopped = false;
  let draining = false;
  const interval = options.intervalMs ?? EXECUTION_POLL_INTERVAL_MS;

  const schedule = (delay: number) => {
    if (!stopped) timer = setTimeout(request, delay);
  };

  const request = async () => {
    timer = null;
    try {
      const response = await options.poll(options.runId, cursor);
      if (stopped) return;
      if (!response.ok) {
        options.onError(response.error);
        if (response.error.code === 'EXECUTION_NOT_FOUND') {
          stopped = true;
          return;
        }
        schedule(interval);
        return;
      }

      if (response.data.runId !== options.runId || response.data.nextSequence < cursor) {
        schedule(interval);
        return;
      }

      cursor = Math.max(cursor, response.data.nextSequence);
      options.onStatus(response.data);
      const terminal = terminalStatuses.has(response.data.status);
      if (terminal && !draining) {
        draining = true;
        schedule(0);
      } else if (terminal && draining) {
        stopped = true;
      } else {
        schedule(interval);
      }
    } catch {
      if (stopped) return;
      options.onError({
        code: 'EXECUTION_STATUS_FAILED',
        message: 'No se pudo consultar la ejecución.',
      });
      schedule(interval);
    }
  };

  schedule(interval);
  return () => {
    stopped = true;
    if (timer !== null) clearTimeout(timer);
  };
}

export type UseExecutionPollingOptions = ExecutionPollerOptions;

export function useExecutionPolling(options: UseExecutionPollingOptions): void {
  const poll = useEffectEvent(options.poll);
  const onStatus = useEffectEvent(options.onStatus);
  const onError = useEffectEvent(options.onError);

  useEffect(() => {
    return createExecutionPoller({
      runId: options.runId,
      initialCursor: options.initialCursor,
      poll,
      onStatus,
      onError,
      intervalMs: options.intervalMs,
    });
  }, [options.runId]);
}
