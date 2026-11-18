import type { AiPersistedState } from '@/ai/types';
import type { PendingAiProposal } from '@/ai/proposalSchema';

export type ApiErrorCode =
  | 'DIRECTORY_SELECTION_CANCELLED'
  | 'DIRECTORY_UNAVAILABLE'
  | 'CATALOG_READ_FAILED'
  | 'BOT_ENTRY_NOT_FOUND'
  | 'BOT_LOAD_FAILED'
  | 'BOT_INVALID'
  | 'BOT_CHANGED_EXTERNALLY'
  | 'BOT_SAVE_FAILED'
  | 'BOT_AI_INVALID'
  | 'BOT_AI_TOO_LARGE'
  | 'BOT_AI_SAVE_FAILED'
  | 'BOT_PENDING_AI_INVALID'
  | 'BOT_PENDING_AI_STALE'
  | 'BOT_PENDING_AI_TOO_LARGE'
  | 'BOT_PENDING_AI_SAVE_FAILED'
  | 'EXECUTION_ALREADY_ACTIVE'
  | 'EXECUTION_CAPTURE_ACTIVE'
  | 'EXECUTION_BOT_INVALID'
  | 'EXECUTION_UNSUPPORTED_ACTION'
  | 'EXECUTION_VARIABLE_INVALID'
  | 'EXECUTION_ENVIRONMENT_UNAVAILABLE'
  | 'EXECUTION_START_FAILED'
  | 'EXECUTION_SHUTTING_DOWN'
  | 'EXECUTION_NOT_FOUND'
  | 'EXECUTION_NOT_ACTIVE'
  | 'EXECUTION_STATUS_FAILED'
  | 'WORKFLOW_LOAD_FAILED'
  | 'WORKFLOW_CYCLE'
  | 'WORKFLOW_DEPTH_EXCEEDED'
  | 'WORKFLOW_UNIQUE_FILE_LIMIT_EXCEEDED'
  | 'WORKFLOW_INVOCATION_LIMIT_EXCEEDED'
  | 'WORKFLOW_EXPANDED_NODE_LIMIT_EXCEEDED'
  | 'WORKFLOW_CUMULATIVE_BYTE_LIMIT_EXCEEDED'
  | 'CAPTURE_CANCELLED'
  | 'CAPTURE_TIMEOUT'
  | 'CAPTURE_ALREADY_ACTIVE'
  | 'CAPTURE_ENVIRONMENT_UNAVAILABLE'
  | 'CAPTURE_SHUTTING_DOWN'
  | 'DESKTOP_BRIDGE_UNAVAILABLE';
export type SelectDirectoryErrorCode =
  | 'DIRECTORY_SELECTION_CANCELLED'
  | 'DIRECTORY_UNAVAILABLE'
  | 'CATALOG_READ_FAILED'
  | 'DESKTOP_BRIDGE_UNAVAILABLE';
export type CatalogErrorCode = 'DIRECTORY_UNAVAILABLE' | 'CATALOG_READ_FAILED';
export type LoadBotErrorCode =
  | 'BOT_ENTRY_NOT_FOUND'
  | 'BOT_LOAD_FAILED'
  | 'BOT_INVALID'
  | 'DIRECTORY_UNAVAILABLE';
export type CreateBotErrorCode =
  | 'BOT_INVALID'
  | 'BOT_SAVE_FAILED'
  | 'DIRECTORY_UNAVAILABLE';
export type DeleteBotErrorCode =
  | 'BOT_ENTRY_NOT_FOUND'
  | 'BOT_SAVE_FAILED'
  | 'DIRECTORY_UNAVAILABLE'
  | 'DESKTOP_BRIDGE_UNAVAILABLE';
export type SaveBotErrorCode =
  | 'BOT_ENTRY_NOT_FOUND'
  | 'BOT_INVALID'
  | 'BOT_CHANGED_EXTERNALLY'
  | 'BOT_SAVE_FAILED'
  | 'DIRECTORY_UNAVAILABLE';
export type SaveBotAiErrorCode =
  | 'BOT_ENTRY_NOT_FOUND'
  | 'BOT_AI_INVALID'
  | 'BOT_AI_TOO_LARGE'
  | 'BOT_CHANGED_EXTERNALLY'
  | 'BOT_AI_SAVE_FAILED';
export type SavePendingAiProposalErrorCode =
  | 'BOT_ENTRY_NOT_FOUND'
  | 'BOT_PENDING_AI_INVALID'
  | 'BOT_PENDING_AI_STALE'
  | 'BOT_PENDING_AI_TOO_LARGE'
  | 'BOT_CHANGED_EXTERNALLY'
  | 'BOT_PENDING_AI_SAVE_FAILED';
export type ExecuteBotErrorCode =
  | 'EXECUTION_ALREADY_ACTIVE'
  | 'EXECUTION_CAPTURE_ACTIVE'
  | 'EXECUTION_BOT_INVALID'
  | 'EXECUTION_UNSUPPORTED_ACTION'
  | 'EXECUTION_VARIABLE_INVALID'
  | 'EXECUTION_ENVIRONMENT_UNAVAILABLE'
  | 'EXECUTION_START_FAILED'
  | 'EXECUTION_SHUTTING_DOWN'
  | 'WORKFLOW_LOAD_FAILED'
  | 'WORKFLOW_CYCLE'
  | 'WORKFLOW_DEPTH_EXCEEDED'
  | 'WORKFLOW_UNIQUE_FILE_LIMIT_EXCEEDED'
  | 'WORKFLOW_INVOCATION_LIMIT_EXCEEDED'
  | 'WORKFLOW_EXPANDED_NODE_LIMIT_EXCEEDED'
  | 'WORKFLOW_CUMULATIVE_BYTE_LIMIT_EXCEEDED';
export type CancelExecutionErrorCode =
  | 'EXECUTION_NOT_FOUND'
  | 'EXECUTION_NOT_ACTIVE'
  | 'EXECUTION_STATUS_FAILED';
export type ExecutionStatusErrorCode = 'EXECUTION_NOT_FOUND' | 'EXECUTION_STATUS_FAILED';
export type CaptureMouseErrorCode =
  | 'CAPTURE_CANCELLED'
  | 'CAPTURE_TIMEOUT'
  | 'CAPTURE_ALREADY_ACTIVE'
  | 'CAPTURE_ENVIRONMENT_UNAVAILABLE'
  | 'CAPTURE_SHUTTING_DOWN';
export type ApiError<Code extends ApiErrorCode = ApiErrorCode> = { code: Code; message: string };
export type ApiResponse<T, Code extends ApiErrorCode = ApiErrorCode> =
  | { ok: true; data: T; error: null }
  | { ok: false; data: null; error: ApiError<Code> };

export type HealthData = { status: string; version: string };
export type BotDescriptor = {
  entryId: string;
  filename: string;
  botId: string;
  name: string;
  description: string;
  icon: string | null;
  blockCount: number;
  modifiedAt: string;
  fileSize: number;
};
export type BotCatalog = {
  directoryName: string;
  directoryPath: string;
  bots: BotDescriptor[];
  invalidCount: number;
};
export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };
export type CanonicalBotNode = {
  id: string;
  type: string;
  params: Record<string, JsonValue>;
  slots?: Record<string, string[]>;
};
export type CanonicalBotNodeInput = CanonicalBotNode;
export type CanonicalBotEdge = { id: string; source: string; target: string };
export type CanonicalBot = {
  schemaVersion: 1 | 2;
  id: string;
  name: string;
  description: string;
  icon?: string;
  flow: {
    root?: string[];
    nodes: CanonicalBotNode[];
    edges?: CanonicalBotEdge[];
  };
  ai?: AiPersistedState;
  pendingAiProposal?: PendingAiProposal;
};
export type CanonicalBotInput = Omit<CanonicalBot, 'description' | 'icon' | 'flow'> & {
  description?: string;
  icon?: string | null;
  flow: {
    nodes: CanonicalBotNodeInput[];
    root?: string[];
    edges?: CanonicalBotEdge[];
  };
};
export type EditorLoadResult = {
  bot: CanonicalBot;
  editorToken: string;
  botDirectoryPath: string;
  revision: string;
  botRevision?: string;
  warning?:
    | 'PENDING_AI_PROPOSAL_DISCARDED'
    | 'PENDING_AI_PROPOSAL_DISCARD_FAILED'
    | 'PENDING_AI_PROPOSAL_STALE_DISCARDED'
    | 'PENDING_AI_PROPOSAL_STALE_DISCARD_FAILED';
  descriptor: BotDescriptor;
};
export type EditorSaveResult = {
  revision: string;
  botRevision?: string;
  descriptor: BotDescriptor;
};
export type EditorAiSaveResult = EditorSaveResult & { ai: AiPersistedState };
export type { PendingAiProposal } from '@/ai/proposalSchema';
export type EditorPendingAiProposalSaveResult = EditorSaveResult & {
  pendingAiProposal: PendingAiProposal | null;
};
export type NativeExecutionStatus =
  | 'validating'
  | 'running'
  | 'cancel_requested'
  | 'succeeded'
  | 'failed'
  | 'cancelled';
export type ExecutionEventType =
  | 'run.validating'
  | 'run.started'
  | 'block.started'
  | 'block.succeeded'
  | 'block.warning'
  | 'block.failed'
  | 'block.stopped'
  | 'block.cancelled'
  | 'run.cancel_requested'
  | 'run.cleanup_pending'
  | 'run.cancelled'
  | 'run.succeeded'
  | 'run.failed';
export type ExecutionEventCode =
  | ExecuteBotErrorCode
  | CancelExecutionErrorCode
  | ExecutionStatusErrorCode
  | 'VARIABLE_TOKEN_INVALID'
  | 'VARIABLE_MISSING'
  | 'VARIABLE_CYCLE'
  | 'VARIABLE_DEPTH_EXCEEDED'
  | 'VARIABLE_EXPANDED_SIZE_EXCEEDED'
  | 'RESOURCE_NOT_FOUND'
  | 'RESOURCE_ALREADY_DEFINED'
  | 'RESOURCE_CLOSED'
  | 'RESOURCE_CLEANUP_FAILED'
  | 'ACTION_PARAMETER_INVALID'
  | 'EVENT_CURSOR_AHEAD'
  | 'VARIABLE_TOKEN_COUNT_EXCEEDED'
  | 'EXECUTION_CANCELLED'
  | 'DESKTOP_INPUT_FAILED'
  | 'CLIPBOARD_UNAVAILABLE'
  | 'EXCEL_UNAVAILABLE'
  | 'EXCEL_OPEN_FAILED'
  | 'EXCEL_WORKSHEET_NOT_FOUND'
  | 'EXCEL_READ_FAILED'
  | 'EXCEL_WRITE_FAILED'
  | 'EXCEL_SAVE_FAILED'
  | 'EXCEL_DESTINATION_EXISTS'
  | 'EXCEL_CLOSE_FAILED'
  | 'EXCEL_VALUE_UNSUPPORTED'
  | 'FILESYSTEM_OPERATION_FAILED'
  | 'PROCESS_START_FAILED'
  | 'WINDOW_NOT_FOUND'
  | 'WINDOW_OPERATION_FAILED'
  | 'HTTP_REQUEST_FAILED'
  | 'HTTP_RESPONSE_TOO_LARGE'
  | 'WORKFLOW_LOAD_FAILED'
  | 'WORKFLOW_CYCLE'
  | 'WORKFLOW_DEPTH_EXCEEDED'
  | 'WORKFLOW_UNIQUE_FILE_LIMIT_EXCEEDED'
  | 'WORKFLOW_INVOCATION_LIMIT_EXCEEDED'
  | 'WORKFLOW_EXPANDED_NODE_LIMIT_EXCEEDED'
  | 'WORKFLOW_CUMULATIVE_BYTE_LIMIT_EXCEEDED'
  | 'STEP_BUDGET_EXCEEDED'
  | 'VISION_OCR_UNAVAILABLE'
  | 'VISION_ELEMENT_NOT_FOUND'
  | 'VISION_CAPTURE_FAILED';
export type ExecutionEvent = {
  schemaVersion: 1;
  runId: string;
  sequence: number;
  timestamp: string;
  type: ExecutionEventType;
  level: 'info' | 'warning' | 'error';
  message: string;
  details?: string;
  blockId?: string;
  editorBlockId?: string;
  blockName?: string;
  blockIndex?: number;
  blockPath?: string[];
  code?: ExecutionEventCode;
};
export type ExecutionStartResult = {
  runId: string;
  status: 'validating';
  startedAt: string;
};
export type ExecutionCancelResult = {
  runId: string;
  status: NativeExecutionStatus;
};
export type ExecutionStatusResult = {
  runId: string;
  status: NativeExecutionStatus;
  currentBlockId: string | null;
  currentEditorBlockId: string | null;
  currentBlockIndex: number | null;
  totalBlocks: number;
  cancelRequested: boolean;
  events: ExecutionEvent[];
  nextSequence: number;
  eventsTruncated: boolean;
};
export type MousePosition = { x: number; y: number };
export type DesktopApi = {
  health(): Promise<ApiResponse<HealthData, never>>;
  pick_file_path?(
    dialogType: 'file' | 'folder' | 'save',
  ): Promise<ApiResponse<string | null, 'DESKTOP_BRIDGE_UNAVAILABLE'>>;
  select_bot_directory(): Promise<ApiResponse<BotCatalog, SelectDirectoryErrorCode>>;
  get_bot_catalog(): Promise<ApiResponse<BotCatalog | null, CatalogErrorCode>>;
  load_bot(entryId: string): Promise<ApiResponse<EditorLoadResult, LoadBotErrorCode>>;
  create_bot(name: string): Promise<ApiResponse<EditorLoadResult, CreateBotErrorCode>>;
  delete_bot(entryId: string): Promise<ApiResponse<boolean, DeleteBotErrorCode>>;
  save_bot(
    editorToken: string,
    expectedRevision: string,
    bot: CanonicalBotInput,
    clearPendingAiProposal?: boolean,
  ): Promise<ApiResponse<EditorSaveResult, SaveBotErrorCode>>;
  save_bot_ai(
    editorToken: string,
    expectedRevision: string,
    ai: AiPersistedState,
  ): Promise<ApiResponse<EditorAiSaveResult, SaveBotAiErrorCode>>;
  save_pending_ai_proposal(
    editorToken: string,
    expectedRevision: string,
    pending: PendingAiProposal | null,
  ): Promise<ApiResponse<EditorPendingAiProposalSaveResult, SavePendingAiProposalErrorCode>>;
  execute_bot(
    editorToken: string,
    bot: CanonicalBotInput,
  ): Promise<ApiResponse<ExecutionStartResult, ExecuteBotErrorCode>>;
  cancel_execution(runId: string): Promise<ApiResponse<ExecutionCancelResult, CancelExecutionErrorCode>>;
  get_execution_status(
    runId: string,
    afterSequence: number,
  ): Promise<ApiResponse<ExecutionStatusResult, ExecutionStatusErrorCode>>;
  capture_mouse_position(): Promise<ApiResponse<MousePosition, CaptureMouseErrorCode>>;
};

function bridgeUnavailable<T>(): ApiResponse<T, 'DESKTOP_BRIDGE_UNAVAILABLE'> {
  return {
    ok: false,
    data: null,
    error: {
      code: 'DESKTOP_BRIDGE_UNAVAILABLE',
      message: 'La integración de escritorio no está disponible',
    },
  };
}

function safeFailure<
  T,
  Code extends
    | 'CATALOG_READ_FAILED'
    | 'BOT_LOAD_FAILED'
    | 'BOT_SAVE_FAILED'
    | 'BOT_AI_SAVE_FAILED'
    | 'BOT_PENDING_AI_SAVE_FAILED'
    | 'EXECUTION_START_FAILED'
    | 'EXECUTION_STATUS_FAILED'
    | 'CAPTURE_ENVIRONMENT_UNAVAILABLE',
>(code: Code): ApiResponse<T, Code> {
  const messages = {
    CATALOG_READ_FAILED: 'No se pudo leer el catálogo de bots.',
    BOT_LOAD_FAILED: 'No se pudo cargar el bot.',
    BOT_SAVE_FAILED: 'No se pudo guardar el bot.',
    BOT_AI_SAVE_FAILED: 'No se pudo guardar el historial del bot.',
    BOT_PENDING_AI_SAVE_FAILED: 'No se pudo guardar la propuesta pendiente.',
    EXECUTION_START_FAILED: 'No se pudo iniciar la ejecución.',
    EXECUTION_STATUS_FAILED: 'No se pudo consultar la ejecución.',
    CAPTURE_ENVIRONMENT_UNAVAILABLE: 'La selección en pantalla no está disponible.',
  } as const;
  return { ok: false, data: null, error: { code, message: messages[code] } };
}

export const desktopBridge = {
  async health(): Promise<ApiResponse<HealthData, 'DESKTOP_BRIDGE_UNAVAILABLE'>> {
    if (!window.pywebview?.api) {
      return bridgeUnavailable();
    }
    try {
      return await window.pywebview.api.health();
    } catch {
      return bridgeUnavailable();
    }
  },
  async pickFilePath(
    dialogType: 'file' | 'folder' | 'save' = 'file',
  ): Promise<ApiResponse<string | null, 'DESKTOP_BRIDGE_UNAVAILABLE'>> {
    if (!window.pywebview?.api?.pick_file_path) {
      return bridgeUnavailable();
    }
    try {
      return await window.pywebview.api.pick_file_path(dialogType);
    } catch {
      return bridgeUnavailable();
    }
  },
  async selectBotDirectory(): Promise<ApiResponse<BotCatalog, SelectDirectoryErrorCode>> {
    if (!window.pywebview?.api) {
      return bridgeUnavailable();
    }
    try {
      return await window.pywebview.api.select_bot_directory();
    } catch {
      return bridgeUnavailable();
    }
  },
  async getBotCatalog(): Promise<
    ApiResponse<BotCatalog | null, CatalogErrorCode | 'DESKTOP_BRIDGE_UNAVAILABLE'>
  > {
    if (!window.pywebview?.api) {
      return bridgeUnavailable();
    }
    try {
      return await window.pywebview.api.get_bot_catalog();
    } catch {
      return safeFailure('CATALOG_READ_FAILED');
    }
  },
  async loadBot(
    entryId: string,
  ): Promise<ApiResponse<EditorLoadResult, LoadBotErrorCode | 'DESKTOP_BRIDGE_UNAVAILABLE'>> {
    if (!window.pywebview?.api) {
      return bridgeUnavailable();
    }
    try {
      return await window.pywebview.api.load_bot(entryId);
    } catch {
      return safeFailure('BOT_LOAD_FAILED');
    }
  },
  async createBot(
    name: string,
  ): Promise<ApiResponse<EditorLoadResult, CreateBotErrorCode | 'DESKTOP_BRIDGE_UNAVAILABLE'>> {
    if (!window.pywebview?.api) {
      return bridgeUnavailable();
    }
    try {
      return await window.pywebview.api.create_bot(name);
    } catch {
      return safeFailure('BOT_SAVE_FAILED');
    }
  },
  async deleteBot(
    entryId: string,
  ): Promise<ApiResponse<boolean, DeleteBotErrorCode | 'DESKTOP_BRIDGE_UNAVAILABLE'>> {
    if (!window.pywebview?.api?.delete_bot) {
      return bridgeUnavailable();
    }
    try {
      return await window.pywebview.api.delete_bot(entryId);
    } catch {
      return safeFailure('BOT_SAVE_FAILED');
    }
  },
  async saveBot(
    editorToken: string,
    expectedRevision: string,
    bot: CanonicalBotInput,
    clearPendingAiProposal = false,
  ): Promise<ApiResponse<EditorSaveResult, SaveBotErrorCode | 'DESKTOP_BRIDGE_UNAVAILABLE'>> {
    if (!window.pywebview?.api) {
      return bridgeUnavailable();
    }
    try {
      return clearPendingAiProposal
        ? await window.pywebview.api.save_bot(editorToken, expectedRevision, bot, true)
        : await window.pywebview.api.save_bot(editorToken, expectedRevision, bot);
    } catch {
      return safeFailure('BOT_SAVE_FAILED');
    }
  },
  async saveBotAi(
    editorToken: string,
    expectedRevision: string,
    ai: AiPersistedState,
  ): Promise<ApiResponse<EditorAiSaveResult, SaveBotAiErrorCode | 'DESKTOP_BRIDGE_UNAVAILABLE'>> {
    if (!window.pywebview?.api) {
      return bridgeUnavailable();
    }
    try {
      return await window.pywebview.api.save_bot_ai(editorToken, expectedRevision, ai);
    } catch {
      return safeFailure('BOT_AI_SAVE_FAILED');
    }
  },
  async savePendingAiProposal(
    editorToken: string,
    expectedRevision: string,
    pending: PendingAiProposal | null,
  ): Promise<
    ApiResponse<
      EditorPendingAiProposalSaveResult,
      SavePendingAiProposalErrorCode | 'DESKTOP_BRIDGE_UNAVAILABLE'
    >
  > {
    if (!window.pywebview?.api) {
      return bridgeUnavailable();
    }
    try {
      return await window.pywebview.api.save_pending_ai_proposal(
        editorToken,
        expectedRevision,
        pending,
      );
    } catch {
      return safeFailure('BOT_PENDING_AI_SAVE_FAILED');
    }
  },
  async executeBot(
    editorToken: string,
    bot: CanonicalBotInput,
  ): Promise<
    ApiResponse<ExecutionStartResult, ExecuteBotErrorCode | 'DESKTOP_BRIDGE_UNAVAILABLE'>
  > {
    if (!window.pywebview?.api) {
      return bridgeUnavailable();
    }
    try {
      return await window.pywebview.api.execute_bot(editorToken, bot);
    } catch {
      return safeFailure('EXECUTION_START_FAILED');
    }
  },
  async cancelExecution(
    runId: string,
  ): Promise<
    ApiResponse<ExecutionCancelResult, CancelExecutionErrorCode | 'DESKTOP_BRIDGE_UNAVAILABLE'>
  > {
    if (!window.pywebview?.api) {
      return bridgeUnavailable();
    }
    try {
      return await window.pywebview.api.cancel_execution(runId);
    } catch {
      return safeFailure('EXECUTION_STATUS_FAILED');
    }
  },
  async getExecutionStatus(
    runId: string,
    afterSequence: number,
  ): Promise<
    ApiResponse<ExecutionStatusResult, ExecutionStatusErrorCode | 'DESKTOP_BRIDGE_UNAVAILABLE'>
  > {
    if (!window.pywebview?.api) {
      return bridgeUnavailable();
    }
    try {
      return await window.pywebview.api.get_execution_status(runId, afterSequence);
    } catch {
      return safeFailure('EXECUTION_STATUS_FAILED');
    }
  },
  async captureMousePosition(): Promise<
    ApiResponse<MousePosition, CaptureMouseErrorCode | 'DESKTOP_BRIDGE_UNAVAILABLE'>
  > {
    if (!window.pywebview?.api) {
      return bridgeUnavailable();
    }
    try {
      return await window.pywebview.api.capture_mouse_position();
    } catch {
      return safeFailure('CAPTURE_ENVIRONMENT_UNAVAILABLE');
    }
  },
};
