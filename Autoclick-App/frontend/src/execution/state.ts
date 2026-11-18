import type {
  ApiError,
  ApiErrorCode,
  ExecutionEvent,
  ExecutionStartResult,
  ExecutionStatusResult,
  NativeExecutionStatus,
} from '@/app/DesktopBridge';

export const MAX_EXECUTION_EVENTS = 1_000;

export type ExecutionStatus =
  | 'idle'
  | 'starting'
  | 'running'
  | 'cancel_requested'
  | 'succeeded'
  | 'failed'
  | 'cancelled';
export type BlockExecutionStatus =
  | 'running'
  | 'succeeded'
  | 'failed'
  | 'warning'
  | 'stopped'
  | 'cancelled';
export type ExecutionState = {
  status: ExecutionStatus;
  runId: string | null;
  startedAt: string | null;
  currentBlockId: string | null;
  currentBlockIndex: number | null;
  totalBlocks: number;
  events: ExecutionEvent[];
  eventsTruncated: boolean;
  cursor: number;
  orderedBlockIds: string[];
  blocks: Record<string, BlockExecutionStatus>;
  blockEventStatuses: Record<string, BlockExecutionStatus>;
  error: ApiError | null;
  finalStatus: 'succeeded' | 'failed' | 'cancelled' | null;
};

export const initialExecutionState: ExecutionState = {
  status: 'idle',
  runId: null,
  startedAt: null,
  currentBlockId: null,
  currentBlockIndex: null,
  totalBlocks: 0,
  events: [],
  eventsTruncated: false,
  cursor: 0,
  orderedBlockIds: [],
  blocks: {},
  blockEventStatuses: {},
  error: null,
  finalStatus: null,
};

export type ExecutionAction =
  | { type: 'resetForNewRun'; orderedBlockIds: string[] }
  | { type: 'runStarted'; result: ExecutionStartResult }
  | { type: 'startFailed'; error: ApiError<ApiErrorCode> }
  | { type: 'cancelRequested'; runId: string }
  | { type: 'statusReceived'; result: ExecutionStatusResult }
  | { type: 'requestFailed'; runId: string | null; error: ApiError<ApiErrorCode> }
  | { type: 'reset' };

function frontendStatus(status: NativeExecutionStatus): Exclude<ExecutionStatus, 'idle'> {
  return status === 'validating' ? 'starting' : status;
}

function applyBlockEvents(
  blocks: ExecutionState['blockEventStatuses'],
  events: ExecutionEvent[],
  orderedBlockIds: string[],
): ExecutionState['blockEventStatuses'] {
  let next = blocks;
  for (const event of events) {
    const blockId = event.editorBlockId;
    if (!blockId || !orderedBlockIds.includes(blockId)) continue;
    const status =
      event.type === 'block.started'
        ? 'running'
        : event.type === 'block.succeeded'
          ? 'succeeded'
          : event.type === 'block.warning'
            ? 'warning'
            : event.type === 'block.failed'
              ? 'failed'
              : event.type === 'block.stopped'
                ? 'stopped'
                : event.type === 'block.cancelled'
                  ? 'cancelled'
              : null;
    if (status && higherBlockStatus(next[blockId], status) !== next[blockId]) {
      if (next === blocks) next = { ...blocks };
      next[blockId] = higherBlockStatus(next[blockId], status);
    }
  }
  return next;
}

const blockStatusPriority: Record<BlockExecutionStatus, number> = {
  running: 1,
  succeeded: 2,
  warning: 3,
  stopped: 4,
  cancelled: 5,
  failed: 6,
};

function higherBlockStatus<T extends BlockExecutionStatus>(
  current: T | undefined,
  candidate: T,
): T {
  return current && blockStatusPriority[current] >= blockStatusPriority[candidate]
    ? current
    : candidate;
}

function currentBlock(
  orderedBlockIds: string[],
  result: ExecutionStatusResult,
): { id: string | null; index: number | null } {
  const editorBlockId = result.currentEditorBlockId;
  if (editorBlockId !== null) {
    const knownIndex = orderedBlockIds.indexOf(editorBlockId);
    if (knownIndex >= 0) return { id: editorBlockId, index: knownIndex };
  }
  return { id: null, index: null };
}

function reconcileBlocks(
  orderedBlockIds: string[],
  status: ExecutionStatus,
  currentIndex: number | null,
  eventStatuses: ExecutionState['blockEventStatuses'],
): Record<string, BlockExecutionStatus> {
  const blocks: Record<string, BlockExecutionStatus> = { ...eventStatuses };
  if (currentIndex !== null) {
    const current = orderedBlockIds[currentIndex];
    if (current && !blocks[current] && (status === 'running' || status === 'cancel_requested')) blocks[current] = 'running';
  }
  return blocks;
}

export function executionReducer(state: ExecutionState, action: ExecutionAction): ExecutionState {
  switch (action.type) {
    case 'resetForNewRun':
      return {
        ...initialExecutionState,
        status: 'starting',
        orderedBlockIds: [...action.orderedBlockIds],
        totalBlocks: action.orderedBlockIds.length,
      };
    case 'runStarted':
      return {
        ...state,
        status: frontendStatus(action.result.status),
        runId: action.result.runId,
        startedAt: action.result.startedAt,
        error: null,
        finalStatus: null,
      };
    case 'startFailed':
      return {
        ...state,
        status: 'failed',
        error: action.error,
        finalStatus: 'failed',
      };
    case 'cancelRequested':
      return state.runId === action.runId && !state.finalStatus
        ? { ...state, status: 'cancel_requested' }
        : state;
    case 'requestFailed':
      if (action.runId !== state.runId || state.finalStatus) return state;
      if (
        state.error?.code === action.error.code &&
        state.error.message === action.error.message
      ) return state;
      return action.error.code === 'EXECUTION_NOT_FOUND'
        ? { ...state, status: 'failed', error: action.error, finalStatus: 'failed' }
        : { ...state, error: action.error };
    case 'statusReceived': {
      const result = action.result;
      if (state.runId !== result.runId || result.nextSequence < state.cursor) return state;
      const freshEvents = result.events
        .filter((event) => event.runId === state.runId && event.sequence > state.cursor)
        .sort((left, right) => left.sequence - right.sequence)
        .filter((event, index, events) => index === 0 || event.sequence !== events[index - 1].sequence);
      const events = [...state.events, ...freshEvents].slice(-MAX_EXECUTION_EVENTS);
      const blockEventStatuses = applyBlockEvents(
        state.blockEventStatuses,
        freshEvents,
        state.orderedBlockIds,
      );
      const receivedStatus = frontendStatus(result.status);
      const receivedFinalStatus =
        receivedStatus === 'succeeded' ||
        receivedStatus === 'failed' ||
        receivedStatus === 'cancelled'
          ? receivedStatus
          : null;
      const finalStatus = state.finalStatus ?? receivedFinalStatus;
      const status = finalStatus
        ? finalStatus
        : state.status === 'cancel_requested' &&
            (receivedStatus === 'starting' || receivedStatus === 'running')
          ? 'cancel_requested'
          : receivedStatus;
      const normalizedCurrentBlock = currentBlock(state.orderedBlockIds, result);
      return {
        ...state,
        status,
        currentBlockId: normalizedCurrentBlock.id,
        currentBlockIndex: normalizedCurrentBlock.index,
        totalBlocks: result.totalBlocks,
        events,
        eventsTruncated: state.eventsTruncated || result.eventsTruncated,
        cursor: Math.max(
          state.cursor,
          result.nextSequence,
          freshEvents.at(-1)?.sequence ?? 0,
        ),
        blocks: reconcileBlocks(
          state.orderedBlockIds,
          status,
          normalizedCurrentBlock.index,
          blockEventStatuses,
        ),
        blockEventStatuses,
        error: null,
        finalStatus,
      };
    }
    case 'reset':
      return initialExecutionState;
  }
}
