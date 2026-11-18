import { AlertTriangle, ArrowLeft, HelpCircle, RefreshCw, X } from 'lucide-react';
import { motion, MotionConfig, useReducedMotion } from 'framer-motion';
import { useEffect, useEffectEvent, useReducer, useRef, useState, useTransition } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  DndContext,
  DragOverlay,
  KeyboardSensor,
  PointerSensor,
  rectIntersection,
  useSensor,
  useSensors,
  type CollisionDetection,
  type DragEndEvent,
  type DragStartEvent,
} from '@dnd-kit/core';
import { sortableKeyboardCoordinates } from '@dnd-kit/sortable';
import { desktopBridge, type ApiErrorCode, type PendingAiProposal } from '@/app/DesktopBridge';
import { BotAiProvider } from '@/ai/AiProvider';
import { parseBotAi } from '@/ai/schema';
import { emptyAiPersistedState } from '@/ai/storage';
import type { AiEditorContext, AiPersistedState } from '@/ai/types';
import { aiBotProposalSchema, pendingAiProposalSchema, type AiBotProposal } from '@/ai/proposalSchema';
import {
  canonicalBotRevision,
  canonicalProposalBotString,
  canEditProposalNodeParameters,
  compactProposalParameterOperation,
  validateProposalResult,
  ProposalPatchError,
} from '@/ai/proposalPatch';
import type { BotEditorNode, BotEditorState } from '@/bot/model';
import { botEditorReducer, type BotEditorAction } from '@/bot/state';
import {
  assessEditorState,
  canonicalString,
  createEditorLoadState,
  createEditorState,
  serializeEditorState,
} from '@/bot/serialization';
import { parseCanonicalBot, type CanonicalBot } from '@/bot/schema';
import { validateExecutionReadiness, type ValidationIssue } from '@/bot/validation';
import { orderedNodes } from '@/bot/validation';
import type { TreeLocation } from '@/bot/model';
import { actionsById } from '@/bot/registry';
import { actionIcons } from '@/features/editor/actionIcons';
import { Button } from '@/components/Button';
import { Alert } from '@/components/Alert';
import { Mascot } from '@/components/Mascot';
import { ActionCatalog } from '@/features/editor/ActionCatalog';
import { AiChatBubble, EditorAiPanel } from '@/features/editor/FuturePanels';
import { DragBlockPreview, SequenceStack } from '@/features/editor/SequenceStack';
import { ConfigurationPanel } from '@/features/editor/ConfigurationPanel';
import { EditorToolbar } from '@/features/editor/EditorToolbar';
import { NavigationPrompt, type NavigationPromptControl } from '@/features/editor/NavigationPrompt';
import { ValidationPanel } from '@/features/editor/ValidationPanel';
import { OverlayDialog } from '@/features/editor/OverlayDialog';
import { createSequenceAnnouncements } from '@/features/editor/dndAccessibility';
import { parseEditorDndId, resolveSequenceDrop } from '@/features/editor/sequenceDrop';
import { ExecutionConsole } from '@/features/editor/ExecutionConsole';
import { ProposalComparison } from '@/features/editor/ProposalComparison';
import {
  executionReducer,
  initialExecutionState,
  type ExecutionAction,
  type ExecutionState,
} from '@/execution/state';
import { useExecutionPolling } from '@/execution/useExecutionPolling';

type Session = {
  editorToken: string;
  botDirectoryPath: string;
  revision: string;
  editorBotRevision: string;
  saved: CanonicalBot;
  initialAi: AiPersistedState;
  initialPending: PendingAiProposal | null;
};
type SafeError = { code: ApiErrorCode; message: string };
type CaptureFeedback = { nodeId: string; kind: 'status' | 'error'; message: string };
type Assessment = {
  editor: BotEditorState;
  saved: CanonicalBot;
  dirty: boolean;
  serializable: boolean;
  draft: CanonicalBot | null;
};
type AgentProposalDraft = {
  proposal: AiBotProposal;
  operationBaseline: CanonicalBot;
  original: CanonicalBot;
  proposed: CanonicalBot;
  editor: BotEditorState;
  validationIssues: ValidationIssue[];
  editorToken: string;
};
type ProposalEditorAction = Extract<
  BotEditorAction,
  { type: 'nodeSelected' | 'nodeCollapsed' | 'parameterChanged' }
>;
type ProposalBusyState = {
  executionStarting: boolean;
  executionActive: boolean;
  accepting: boolean;
  saving: boolean;
  conflict: boolean;
  pendingWrites: number;
  captureActive: boolean;
  dragging: boolean;
  aiUnsynced: boolean;
};
type PendingRestoreRetry = {
  pending: PendingAiProposal;
  editorToken: string;
  loadGeneration: number;
};
const EDITOR_ASSESSMENT_DELAY_MS = 120;

export function isProposalBusy(state: ProposalBusyState): boolean {
  return state.executionStarting
    || state.executionActive
    || state.accepting
    || state.saving
    || state.conflict
    || state.pendingWrites > 0
    || state.captureActive
    || state.dragging
    || state.aiUnsynced;
}

const sequenceCollisionDetection: CollisionDetection = (args) =>
  rectIntersection({
    ...args,
    droppableContainers: args.droppableContainers.filter(
      ({ id }) => !id.toString().startsWith('catalog:')
    ),
  });

function isEditableDeleteTarget(target: EventTarget | null): boolean {
  if (!(target instanceof Element)) return false;
  return Boolean(
    target.closest('input, textarea, select, [contenteditable]:not([contenteditable="false"])') ||
    target.closest('dialog[open], [role="dialog"]')
  );
}

function errorMessage(code: ApiErrorCode, operation: 'load' | 'save') {
  if (code === 'DESKTOP_BRIDGE_UNAVAILABLE')
    return 'La integración de escritorio no está disponible. Abrí AutoClick desde la aplicación de escritorio.';
  if (code === 'BOT_ENTRY_NOT_FOUND')
    return 'Este bot ya no está disponible. Volvé al Explorador y actualizá la carpeta.';
  if (code === 'DIRECTORY_UNAVAILABLE') return 'La carpeta de bots ya no está disponible.';
  if (code === 'BOT_INVALID')
    return operation === 'load'
      ? 'El archivo ya no contiene un bot válido.'
      : 'El borrador no tiene una estructura válida.';
  return operation === 'load'
    ? 'No se pudo cargar el bot. Intentá nuevamente.'
    : 'No se pudo guardar el bot. El borrador se conserva.';
}

function aiSaveErrorMessage(code: ApiErrorCode) {
  if (code === 'BOT_AI_INVALID') return 'El historial del bot no es válido.';
  if (code === 'BOT_AI_TOO_LARGE')
    return 'El historial supera el límite permitido. Eliminá conversaciones antes de reintentar.';
  if (code === 'DESKTOP_BRIDGE_UNAVAILABLE')
    return 'La integración de escritorio no está disponible.';
  return 'No se pudo guardar el historial del bot.';
}

function executionErrorMessage(code: ApiErrorCode) {
  if (code === 'EXECUTION_ALREADY_ACTIVE')
    return 'Ya hay una ejecución activa. Esperá a que termine o cancelala.';
  if (code === 'EXECUTION_CAPTURE_ACTIVE')
    return 'Hay una selección de coordenadas activa. Esperá a que termine.';
  if (code === 'EXECUTION_BOT_INVALID') return 'El borrador no está listo para ejecutarse.';
  if (code === 'EXECUTION_UNSUPPORTED_ACTION')
    return 'El borrador contiene una acción que no se puede ejecutar.';
  if (code === 'EXECUTION_VARIABLE_INVALID')
    return 'Las variables del borrador no son válidas para la ejecución.';
  if (code === 'EXECUTION_ENVIRONMENT_UNAVAILABLE')
    return 'El entorno de escritorio necesario no está disponible.';
  if (code === 'EXECUTION_SHUTTING_DOWN')
    return 'AutoClick se está cerrando y no puede iniciar otra ejecución.';
  if (code === 'WORKFLOW_LOAD_FAILED')
    return 'No se pudo cargar uno de los flujos anidados.';
  if (code === 'WORKFLOW_CYCLE')
    return 'Los flujos anidados contienen una llamada circular.';
  if (code === 'WORKFLOW_DEPTH_EXCEEDED')
    return 'Los flujos anidados superan la profundidad permitida.';
  if (code === 'WORKFLOW_UNIQUE_FILE_LIMIT_EXCEEDED')
    return 'Los flujos anidados contienen demasiados archivos únicos.';
  if (code === 'WORKFLOW_INVOCATION_LIMIT_EXCEEDED')
    return 'Los flujos anidados contienen demasiadas invocaciones.';
  if (code === 'WORKFLOW_EXPANDED_NODE_LIMIT_EXCEEDED')
    return 'Los flujos anidados contienen demasiados bloques expandidos.';
  if (code === 'WORKFLOW_CUMULATIVE_BYTE_LIMIT_EXCEEDED')
    return 'Los flujos anidados exceden el tamaño acumulado permitido.';
  if (code === 'EXECUTION_NOT_FOUND') return 'La ejecución ya no está disponible.';
  if (code === 'EXECUTION_NOT_ACTIVE') return 'La ejecución ya finalizó.';
  if (code === 'DESKTOP_BRIDGE_UNAVAILABLE')
    return 'La integración de escritorio no está disponible.';
  if (code === 'EXECUTION_STATUS_FAILED') return 'No se pudo consultar o cancelar la ejecución.';
  return 'No se pudo iniciar la ejecución.';
}

function captureErrorMessage(code: ApiErrorCode) {
  if (code === 'CAPTURE_TIMEOUT')
    return 'La selección agotó el tiempo de espera. Intentá nuevamente.';
  if (code === 'CAPTURE_ALREADY_ACTIVE') return 'Ya hay una selección de coordenadas activa.';
  if (code === 'CAPTURE_SHUTTING_DOWN')
    return 'AutoClick se está cerrando y no puede seleccionar coordenadas.';
  if (code === 'DESKTOP_BRIDGE_UNAVAILABLE')
    return 'La integración de escritorio no está disponible.';
  return 'La selección en pantalla no está disponible.';
}

function ExecutionPolling({
  runId,
  dispatch,
}: {
  runId: string;
  dispatch: React.Dispatch<ExecutionAction>;
}) {
  useExecutionPolling({
    runId,
    initialCursor: 0,
    poll: desktopBridge.getExecutionStatus,
    onStatus: (result) => dispatch({ type: 'statusReceived', result }),
    onError: (error) =>
      dispatch({
        type: 'requestFailed',
        runId,
        error: { ...error, message: executionErrorMessage(error.code) },
      }),
  });
  return null;
}

function EditorPageContent() {
  const { entryId = '' } = useParams();
  const navigate = useNavigate();
  const prefersReducedMotion = useReducedMotion();
  const [editor, setEditor] = useState<BotEditorState | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [assessment, setAssessment] = useState<Assessment | null>(null);
  const [dragging, setDragging] = useState(false);
  const [activeDragId, setActiveDragId] = useState<string | null>(null);
  const [error, setError] = useState<SafeError | null>(null);
  const [conflict, setConflict] = useState(false);
  const [validationVisible, setValidationVisible] = useState(false);
  const [issues, setIssues] = useState<ValidationIssue[]>([]);
  const [catalogOpen, setCatalogOpen] = useState(false);
  const [propertiesOpen, setPropertiesOpen] = useState(false);
  const [aiChatOpen, setAiChatOpen] = useState(false);
  const [aiUnsynced, setAiUnsynced] = useState(false);
  const [agentProposal, setAgentProposal] = useState<AgentProposalDraft | null>(null);
  const [pendingRestoreRetry, setPendingRestoreRetry] = useState<PendingRestoreRetry | null>(null);
  const [acceptingProposal, setAcceptingProposal] = useState(false);
  const [activeWrite, setActiveWrite] = useState<'manual' | 'ai' | null>(null);
  const [pendingWrites, setPendingWrites] = useState(0);
  const [captureNodeId, setCaptureNodeId] = useState<string | null>(null);
  const [captureFeedback, setCaptureFeedback] = useState<CaptureFeedback | null>(null);
  const [captureInFlight, setCaptureInFlight] = useState(false);
  const [execution, dispatchExecution] = useReducer(executionReducer, initialExecutionState);
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  );
  const [, startValidationTransition] = useTransition();
  const allowNextNavigationRef = useRef(false);
  const navigationPromptControlRef = useRef<NavigationPromptControl>(null);
  const entryIdRef = useRef(entryId);
  const editorRef = useRef<BotEditorState | null>(null);
  const sessionRef = useRef<Session | null>(null);
  const savingRef = useRef(false);
  const mountedRef = useRef(false);
  const assessmentRef = useRef<Assessment | null>(null);
  const editorRegionRef = useRef<HTMLElement>(null);
  const aiBubbleRef = useRef<HTMLButtonElement>(null);
  const wasAiChatOpenRef = useRef(false);
  const focusEditorAfterLoadRef = useRef(false);
  const executionStartingRef = useRef(false);
  const executionRef = useRef<ExecutionState>(initialExecutionState);
  const cancelAfterStartRef = useRef(false);
  const executionDraftNodesRef = useRef<CanonicalBot['flow']['nodes']>([]);
  const captureActiveRef = useRef(false);
  const captureButtonRef = useRef<HTMLButtonElement>(null);
  const captureGenerationRef = useRef(0);
  const loadGenerationRef = useRef(0);
  const saveGenerationRef = useRef(0);
  const writeGenerationRef = useRef(0);
  const writeQueueRef = useRef<Promise<void>>(Promise.resolve());
  const activeWriteRef = useRef<'manual' | 'ai' | null>(null);
  const pendingWritesRef = useRef(0);
  const agentProposalRef = useRef<AgentProposalDraft | null>(null);
  const persistedProposalRef = useRef<AgentProposalDraft | null>(null);
  const acceptingProposalRef = useRef(false);
  const conflictRef = useRef(false);
  const draggingRef = useRef(false);
  const aiUnsyncedRef = useRef(false);
  entryIdRef.current = entryId;
  executionRef.current = execution;
  agentProposalRef.current = agentProposal;
  conflictRef.current = conflict;

  function proposalBusyNow(): boolean {
    const currentExecution = executionRef.current;
    return isProposalBusy({
      executionStarting: executionStartingRef.current,
      executionActive: ['starting', 'running', 'cancel_requested'].includes(currentExecution.status),
      accepting: acceptingProposalRef.current,
      saving: savingRef.current,
      conflict: conflictRef.current,
      pendingWrites: pendingWritesRef.current,
      captureActive: captureActiveRef.current,
      dragging: draggingRef.current,
      aiUnsynced: aiUnsyncedRef.current,
    });
  }

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      captureGenerationRef.current += 1;
      loadGenerationRef.current += 1;
      saveGenerationRef.current += 1;
      writeGenerationRef.current += 1;
      captureActiveRef.current = false;
      const current = executionRef.current;
      if (current.status === 'starting' && !current.runId) {
        cancelAfterStartRef.current = true;
      } else if (
        current.runId &&
        ['starting', 'running', 'cancel_requested'].includes(current.status)
      ) {
        void desktopBridge.cancelExecution(current.runId);
      }
    };
  }, []);

  function installSession(
    bot: CanonicalBot,
    editorToken: string,
    botDirectoryPath: string,
    revision: string,
    editorBotRevision: string,
    initialPending: PendingAiProposal | null,
  ) {
    const currentExecution = executionRef.current;
    if (
      executionStartingRef.current ||
      ['starting', 'running', 'cancel_requested'].includes(currentExecution.status)
    ) {
      if (executionStartingRef.current && !currentExecution.runId)
        cancelAfterStartRef.current = true;
      else void cancelExecution();
      setEditor(editorRef.current);
      setSession(sessionRef.current);
      setAssessment(assessmentRef.current);
      return false;
    }
    captureGenerationRef.current += 1;
    saveGenerationRef.current += 1;
    writeGenerationRef.current += 1;
    writeQueueRef.current = Promise.resolve();
    activeWriteRef.current = null;
    pendingWritesRef.current = 0;
    savingRef.current = false;
    captureActiveRef.current = false;
    draggingRef.current = false;
    aiUnsyncedRef.current = false;
    setSaving(false);
    setActiveWrite(null);
    setPendingWrites(0);
    setAiUnsynced(false);
    agentProposalRef.current = null;
    persistedProposalRef.current = null;
    setAgentProposal(null);
    acceptingProposalRef.current = false;
    setAcceptingProposal(false);
    setCaptureNodeId(null);
    setCaptureFeedback(null);
    executionStartingRef.current = false;
    cancelAfterStartRef.current = false;
    executionDraftNodesRef.current = [];
    executionRef.current = initialExecutionState;
    dispatchExecution({ type: 'reset' });
    const { editor: nextEditor, saved } = createEditorLoadState(bot);
    const nextSession = {
      editorToken,
      botDirectoryPath,
      revision,
      editorBotRevision,
      saved,
      initialAi: bot.ai ?? emptyAiPersistedState(),
      initialPending,
    };
    const assessment = assessEditorState(nextEditor, saved);
    editorRef.current = nextEditor;
    sessionRef.current = nextSession;
    const publication = { editor: nextEditor, saved, ...assessment };
    assessmentRef.current = publication;
    setEditor(nextEditor);
    setSession(nextSession);
    setAssessment(publication);
    setDragging(false);
    setActiveDragId(null);
    setValidationVisible(false);
    setIssues([]);
    return true;
  }

  function parseLoadedSessionBot(input: Parameters<typeof parseCanonicalBot>[0]) {
    const raw = structuredClone(input) as Record<string, unknown>;
    const pendingInput = raw.pendingAiProposal;
    delete raw.pendingAiProposal;
    const bot = parseCanonicalBot(raw);
    const pending = pendingInput === undefined
      ? null
      : pendingAiProposalSchema.parse(pendingInput);
    return { bot, pending };
  }

  async function restorePendingProposal(
    pending: PendingAiProposal,
    editorToken: string,
    loadGeneration: number,
  ) {
    let restoreFailure: 'BOT_PENDING_AI_INVALID' | 'BOT_PENDING_AI_STALE' = 'BOT_PENDING_AI_INVALID';
    try {
      const currentSession = sessionRef.current;
      if (!currentSession || currentSession.editorToken !== editorToken) return;
      const parsed = pendingAiProposalSchema.parse(pending);
      const [baselineRevision, originalRevision, diskRevision] = await Promise.all([
        canonicalBotRevision(parsed.operationBaseline),
        canonicalBotRevision(parsed.original),
        canonicalBotRevision(currentSession.saved),
      ]);
      if (
        loadGenerationRef.current !== loadGeneration
        || sessionRef.current?.editorToken !== editorToken
      ) return;
      if (
        baselineRevision !== parsed.proposal.baselineBotRevision
        || originalRevision !== parsed.editorBotRevision
      ) {
        throw new ProposalPatchError('La propuesta guardada no es válida.');
      }
      if (diskRevision !== parsed.editorBotRevision) {
        restoreFailure = 'BOT_PENDING_AI_STALE';
        throw new ProposalPatchError('La propuesta guardada pertenece a otra versión del bot.');
      }
      const proposed = parseCanonicalBot(validateProposalResult(parsed.operationBaseline, parsed.proposal));
      const proposedEditor = createEditorState(proposed);
      if (
        canonicalProposalBotString(serializeEditorState(proposedEditor))
        !== canonicalProposalBotString(proposed)
      ) {
        throw new ProposalPatchError('La propuesta guardada no se puede representar de forma segura.');
      }
      const next: AgentProposalDraft = {
        proposal: parsed.proposal,
        operationBaseline: parseCanonicalBot(parsed.operationBaseline),
        original: parseCanonicalBot(parsed.original),
        proposed,
        editor: proposedEditor,
        validationIssues: validateExecutionReadiness(proposedEditor, currentSession.botDirectoryPath),
        editorToken,
      };
      if (sessionRef.current?.editorToken !== editorToken) return;
      if (proposalBusyNow()) {
        setPendingRestoreRetry({ pending, editorToken, loadGeneration });
        setError({
          code: 'BOT_PENDING_AI_SAVE_FAILED',
          message: 'La propuesta pendiente no se pudo restaurar porque el editor está ocupado.',
        });
        return;
      }
      setPendingRestoreRetry(null);
      agentProposalRef.current = next;
      persistedProposalRef.current = next;
      setAgentProposal(next);
      setError(null);
    } catch {
      const currentSession = sessionRef.current;
      if (!currentSession || currentSession.editorToken !== editorToken) return;
      let cleared = false;
      try {
        const response = await enqueueWrite('ai', editorToken, async () => {
          const latestSession = sessionRef.current;
          if (!latestSession || latestSession.editorToken !== editorToken) {
            throw new Error('La sesión del editor cambió.');
          }
          const saved = await desktopBridge.savePendingAiProposal(
            editorToken,
            latestSession.revision,
            null,
          );
          if (saved.ok) {
            const nextSession = {
              ...latestSession,
              revision: saved.data.revision,
              editorBotRevision: saved.data.botRevision ?? latestSession.editorBotRevision,
            };
            sessionRef.current = nextSession;
            setSession(nextSession);
          } else if (saved.error.code === 'BOT_CHANGED_EXTERNALLY') {
            setConflict(true);
          }
          return saved;
        });
        cleared = response.ok;
      } catch {
        cleared = false;
      } finally {
        if (sessionRef.current?.editorToken === editorToken) {
          setPendingRestoreRetry(cleared ? null : { pending, editorToken, loadGeneration });
          setError({
            code: cleared ? restoreFailure : 'BOT_PENDING_AI_SAVE_FAILED',
            message: cleared
              ? restoreFailure === 'BOT_PENDING_AI_STALE'
                ? 'La propuesta pendiente pertenecía a otra versión del bot y se descartó.'
                : 'La propuesta pendiente ya no era válida y se descartó.'
              : restoreFailure === 'BOT_PENDING_AI_STALE'
                ? 'La propuesta pendiente pertenece a otra versión del bot, pero no se pudo eliminar.'
                : 'La propuesta pendiente ya no era válida, pero no se pudo eliminar.',
          });
        }
      }
    }
  }

  function applyLoadWarning(warning: string | undefined) {
    if (warning === 'PENDING_AI_PROPOSAL_STALE_DISCARDED') {
      setError({
        code: 'BOT_PENDING_AI_STALE',
        message: 'La propuesta pendiente pertenecía a otra versión del bot y se eliminó sin afectar el bot.',
      });
    } else if (warning === 'PENDING_AI_PROPOSAL_STALE_DISCARD_FAILED') {
      setError({
        code: 'BOT_PENDING_AI_SAVE_FAILED',
        message: 'La propuesta pendiente pertenece a otra versión del bot. El bot se abrió, pero no se pudo limpiar el archivo.',
      });
    } else if (warning === 'PENDING_AI_PROPOSAL_DISCARDED') {
      setError({
        code: 'BOT_PENDING_AI_INVALID',
        message: 'La propuesta pendiente no era válida y se eliminó sin afectar el bot.',
      });
    } else if (warning === 'PENDING_AI_PROPOSAL_DISCARD_FAILED') {
      setError({
        code: 'BOT_PENDING_AI_SAVE_FAILED',
        message: 'La propuesta pendiente no era válida. El bot se abrió, pero no se pudo limpiar el archivo.',
      });
    }
  }

  function reconcile(nextEditor: BotEditorState, saved = sessionRef.current?.saved) {
    if (!saved) return;
    const assessment = assessEditorState(nextEditor, saved);
    const publication = { editor: nextEditor, saved, ...assessment };
    assessmentRef.current = publication;
    setAssessment(publication);
  }

  async function loadFromDisk() {
    const requestedEntryId = entryIdRef.current;
    const generation = ++loadGenerationRef.current;
    captureGenerationRef.current += 1;
    setCaptureNodeId(null);
    setCaptureFeedback(null);
    if (conflict) focusEditorAfterLoadRef.current = true;
    navigationPromptControlRef.current?.resetPendingNavigation();
    setLoading(true);
    setError(null);
    const response = await desktopBridge.loadBot(requestedEntryId);
    if (
      !mountedRef.current ||
      loadGenerationRef.current !== generation ||
      entryIdRef.current !== requestedEntryId
    )
      return;
    if (response.ok) {
      try {
        const loaded = parseLoadedSessionBot(response.data.bot);
        installSession(
          loaded.bot,
          response.data.editorToken,
          response.data.botDirectoryPath,
          response.data.revision,
          response.data.botRevision ?? '',
          loaded.pending,
        );
        if (loaded.pending) void restorePendingProposal(loaded.pending, response.data.editorToken, generation);
        applyLoadWarning(response.data.warning);
        setConflict(false);
      } catch {
        setError({ code: 'BOT_INVALID', message: errorMessage('BOT_INVALID', 'load') });
      }
    } else {
      setError({ code: response.error.code, message: errorMessage(response.error.code, 'load') });
    }
    setLoading(false);
  }

  useEffect(() => {
    if (!loading && !conflict && editor && focusEditorAfterLoadRef.current) {
      focusEditorAfterLoadRef.current = false;
      editorRegionRef.current?.focus();
    }
  }, [conflict, editor, loading]);

  useEffect(() => {
    let active = true;
    async function load() {
      const requestedEntryId = entryId;
      const generation = ++loadGenerationRef.current;
      captureGenerationRef.current += 1;
      setCaptureNodeId(null);
      setCaptureFeedback(null);
      focusEditorAfterLoadRef.current = false;
      const currentExecution = executionRef.current;
      if (
        executionStartingRef.current ||
        ['starting', 'running', 'cancel_requested'].includes(currentExecution.status)
      ) {
        if (executionStartingRef.current && !currentExecution.runId)
          cancelAfterStartRef.current = true;
        else void cancelExecution();
        return;
      }
      setLoading(true);
      setError(null);
      setEditor(null);
      setSession(null);
      editorRef.current = null;
      sessionRef.current = null;
      assessmentRef.current = null;
      setAssessment(null);
      const response = await desktopBridge.loadBot(requestedEntryId);
      if (
        !active ||
        !mountedRef.current ||
        loadGenerationRef.current !== generation ||
        entryIdRef.current !== requestedEntryId
      )
        return;
      if (response.ok) {
        try {
          const loaded = parseLoadedSessionBot(response.data.bot);
          if (!active || loadGenerationRef.current !== generation) return;
          installSession(
            loaded.bot,
            response.data.editorToken,
            response.data.botDirectoryPath,
            response.data.revision,
            response.data.botRevision ?? '',
            loaded.pending,
          );
          if (loaded.pending) void restorePendingProposal(loaded.pending, response.data.editorToken, generation);
          if (response.data.warning) applyLoadWarning(response.data.warning);
          else setError(null);
        } catch {
          setError({ code: 'BOT_INVALID', message: errorMessage('BOT_INVALID', 'load') });
        }
      } else {
        setError({ code: response.error.code, message: errorMessage(response.error.code, 'load') });
      }
      setLoading(false);
    }
    void load();
    return () => {
      active = false;
    };
  }, [entryId]);

  function dispatch(action: BotEditorAction) {
    if (agentProposalRef.current) return;
    const current = editorRef.current;
    if (!current) return;
    const next = botEditorReducer(current, action);
    if (next === current) return;
    if (action.type !== 'nodeSelected' && action.type !== 'nodeCollapsed') {
      agentProposalRef.current = null;
      setAgentProposal(null);
    }
    if (next.selectedNodeId !== current.selectedNodeId) {
      captureGenerationRef.current += 1;
      setCaptureNodeId(null);
      setCaptureFeedback(null);
    }
    editorRef.current = next;
    setEditor(next);
    if (action.type === 'nodeSelected') {
      const currentAssessment = assessmentRef.current;
      if (currentAssessment?.editor === current) {
        const publication = { ...currentAssessment, editor: next };
        assessmentRef.current = publication;
        setAssessment(publication);
      }
    } else {
      assessmentRef.current = null;
      setAssessment(null);
      setValidationVisible(false);
      setIssues([]);
    }
  }

  function dispatchProposal(action: ProposalEditorAction) {
    const active = agentProposalRef.current;
    const currentSession = sessionRef.current;
    if (
      !active
      || !currentSession
      || active.editorToken !== currentSession.editorToken
    ) return;
    if (action.type === 'parameterChanged' && isProposalBusy({
      executionStarting: executionStartingRef.current,
      executionActive: ['starting', 'running', 'cancel_requested'].includes(executionRef.current.status),
      accepting: acceptingProposalRef.current,
      saving: savingRef.current,
      conflict: conflictRef.current,
      pendingWrites: 0,
      captureActive: captureActiveRef.current,
      dragging: draggingRef.current,
      aiUnsynced: aiUnsyncedRef.current,
    })) return;
    if (
      action.type === 'parameterChanged'
      && !canEditProposalNodeParameters(active.proposal.operations, action.nodeId)
    ) {
      setError({
        code: 'BOT_INVALID',
        message: 'La propuesta alcanzó el límite de 200 operaciones para editar este bloque.',
      });
      return;
    }
    const nextEditor = botEditorReducer(active.editor, action);
    if (nextEditor === active.editor) return;

    let next: AgentProposalDraft;
    if (action.type === 'parameterChanged') {
      try {
        const resultingBot = serializeEditorState(nextEditor);
        const node = nextEditor.nodes.find((candidate) => candidate.id === action.nodeId);
        if (!node) return;
        const proposal = aiBotProposalSchema.parse({
          ...active.proposal,
          version: active.proposal.version + 1,
          operations: compactProposalParameterOperation(
            active.proposal.operations,
            node.id,
            node.data.params,
          ),
          resultingBot,
        });
        const proposed = validateProposalResult(active.operationBaseline, proposal);
        const verifiedEditor = createEditorState(proposed);
        const roundTrip = serializeEditorState(verifiedEditor);
        if (canonicalProposalBotString(roundTrip) !== canonicalProposalBotString(proposed)) {
          throw new ProposalPatchError('La propuesta no se puede representar de forma segura en el editor.');
        }
        verifiedEditor.selectedNodeId = nextEditor.selectedNodeId;
        verifiedEditor.collapsedNodeIds = nextEditor.collapsedNodeIds;
        next = {
          ...active,
          proposal,
          proposed,
          editor: verifiedEditor,
          validationIssues: validateExecutionReadiness(verifiedEditor, currentSession.botDirectoryPath),
        };
      } catch {
        return;
      }
    } else {
      next = { ...active, editor: nextEditor };
    }

    if (action.type === 'parameterChanged') {
      agentProposalRef.current = next;
      setAgentProposal(next);
      void persistAgentProposal(next).then((saved) => {
        if (saved) {
          persistedProposalRef.current = next;
          return;
        }
        if (agentProposalRef.current !== next) return;
        const rollback = persistedProposalRef.current;
        agentProposalRef.current = rollback;
        setAgentProposal(rollback);
      });
    } else {
      agentProposalRef.current = next;
      if (persistedProposalRef.current?.proposal === active.proposal) {
        persistedProposalRef.current = next;
      }
      setAgentProposal(next);
    }
  }

  useEffect(() => {
    if (!editor || !session || dragging) return;
    const assessed = assessmentRef.current;
    if (assessed?.editor === editor && assessed.saved === session.saved) return;
    const timeout = window.setTimeout(
      () => reconcile(editor, session.saved),
      EDITOR_ASSESSMENT_DELAY_MS
    );
    return () => window.clearTimeout(timeout);
  }, [dragging, editor, session]);

  const currentAssessment =
    assessment?.editor === editor && assessment.saved === session?.saved ? assessment : null;
  const dirty = currentAssessment?.dirty ?? true;
  const structurallySerializable = currentAssessment?.serializable ?? false;
  const readinessIssues =
    currentAssessment && session
      ? validateExecutionReadiness(currentAssessment.editor, session.botDirectoryPath)
      : [];
  const executionActive =
    execution.status === 'starting' ||
    execution.status === 'running' ||
    execution.status === 'cancel_requested';
  const captureActive = captureNodeId !== null;
  const canSave = Boolean(
    editor &&
    session &&
    structurallySerializable &&
    !dragging &&
    !executionActive &&
    !conflict &&
    !aiUnsynced &&
    !agentProposal &&
    pendingWrites === 0
  );
  const canExecute = Boolean(
    editor &&
    session?.editorToken &&
    currentAssessment?.draft &&
    readinessIssues.length === 0 &&
    !dragging &&
    !saving &&
    !conflict &&
    !executionActive &&
    !captureInFlight &&
    !aiUnsynced &&
    !agentProposal
  );
  const canCancel = Boolean(
    execution.runId && (execution.status === 'running' || execution.status === 'cancel_requested')
  );
  const proposalCurrent = Boolean(
    agentProposal
    && session
    && agentProposal.editorToken === session.editorToken
  );
  const proposalHasErrors = Boolean(
    proposalCurrent
    && agentProposal!.validationIssues.some((issue) => issue.severity === 'error')
  );
  const proposalReady = proposalCurrent && agentProposal!.validationIssues.length === 0;
  const proposalBusy = isProposalBusy({
    executionStarting: executionStartingRef.current,
    executionActive,
    accepting: acceptingProposal,
    saving,
    conflict,
    pendingWrites,
    captureActive: captureActive || captureInFlight,
    dragging,
    aiUnsynced,
  });
  const canExecuteProposal = Boolean(
    proposalReady
    && session?.editorToken
    && !proposalBusy
  );
  const canAcceptProposal = Boolean(
    proposalCurrent
    && !proposalHasErrors
    && session?.editorToken
    && !proposalBusy
  );
  const canRejectProposal = Boolean(
    proposalCurrent
    && !proposalBusy
  );
  const selectedNode = editor?.nodes.find((node) => node.id === editor.selectedNodeId) ?? null;
  const selectedNodeId = selectedNode?.id ?? null;
  const selectedAction = selectedNode ? actionsById.get(selectedNode.data.actionType) : undefined;
  const SelectedActionIcon = selectedAction ? actionIcons[selectedAction.icon] : HelpCircle;
  useEffect(() => {
    if (selectedNodeId) setPropertiesOpen(true);
  }, [selectedNodeId]);
  useEffect(() => {
    if (proposalCurrent) setPropertiesOpen(false);
  }, [proposalCurrent]);
  useEffect(() => {
    if (!aiChatOpen && wasAiChatOpenRef.current) aiBubbleRef.current?.focus();
    wasAiChatOpenRef.current = aiChatOpen;
  }, [aiChatOpen]);
  const selectedProposalNode = agentProposal?.editor.nodes.find(
    (node) => node.id === agentProposal.editor.selectedNodeId
  ) ?? null;
  const proposalNodeHasCapacity = Boolean(
    !agentProposal
    || !selectedProposalNode
    || canEditProposalNodeParameters(agentProposal.proposal.operations, selectedProposalNode.id)
  );
  const proposalEditingDisabled = isProposalBusy({
    executionStarting: executionStartingRef.current,
    executionActive,
    accepting: acceptingProposal,
    saving,
    conflict,
    pendingWrites: 0,
    captureActive: captureActive || captureInFlight,
    dragging,
    aiUnsynced,
  }) || !proposalNodeHasCapacity;
  const proposalEditingDisabledReason = !proposalNodeHasCapacity
    ? 'Este bloque no se puede editar porque la propuesta ya alcanzó el límite de 200 operaciones.'
    : null;
  const currentExecutionNode = executionDraftNodesRef.current.find((node) => node.id === execution.currentBlockId) ?? null;
  const currentBlockEvent = [...execution.events].reverse().find((event) => event.editorBlockId === execution.currentBlockId && event.blockName);
  const currentBlockName = currentBlockEvent?.blockName ?? (currentExecutionNode
    ? (actionsById.get(currentExecutionNode.type)?.title ?? currentExecutionNode.type)
    : null);
  const activeDragItem = activeDragId ? parseEditorDndId(activeDragId) : null;
  const activeDragActionType =
    activeDragItem?.kind === 'catalog'
      ? activeDragItem.actionType
      : activeDragItem?.kind === 'sequence'
        ? (editor?.nodes.find((node) => node.id === activeDragItem.nodeId)?.data.actionType ?? null)
        : null;

  function enqueueWrite<T>(
    kind: 'manual' | 'ai',
    editorToken: string,
    operation: () => Promise<T>
  ): Promise<T> {
    const generation = writeGenerationRef.current;
    pendingWritesRef.current += 1;
    setPendingWrites(pendingWritesRef.current);
    let resolveResult!: (value: T | PromiseLike<T>) => void;
    let rejectResult!: (reason?: unknown) => void;
    const result = new Promise<T>((resolve, reject) => {
      resolveResult = resolve;
      rejectResult = reject;
    });
    const queued = writeQueueRef.current
      .then(async () => {
        if (
          writeGenerationRef.current !== generation ||
          sessionRef.current?.editorToken !== editorToken
        ) {
          throw new Error('La sesión del editor cambió.');
        }
        activeWriteRef.current = kind;
        setActiveWrite(kind);
        try {
          const value = await operation();
          resolveResult(value);
        } catch (error) {
          rejectResult(error);
        } finally {
          if (writeGenerationRef.current === generation) {
            activeWriteRef.current = null;
            setActiveWrite(null);
          }
        }
      })
      .catch(rejectResult)
      .finally(() => {
        if (writeGenerationRef.current !== generation) return;
        pendingWritesRef.current = Math.max(0, pendingWritesRef.current - 1);
        setPendingWrites(pendingWritesRef.current);
      });
    writeQueueRef.current = queued.then(
      () => undefined,
      () => undefined
    );
    return result;
  }

  async function persistBotAi(ai: AiPersistedState): Promise<AiPersistedState> {
    const requestedSession = sessionRef.current;
    if (!requestedSession || conflict)
      throw new Error('El historial no se puede guardar hasta recargar el bot.');
    return enqueueWrite('ai', requestedSession.editorToken, async () => {
      const currentSession = sessionRef.current;
      if (
        !currentSession ||
        currentSession.editorToken !== requestedSession.editorToken ||
        conflict
      ) {
        throw new Error('La sesión del editor cambió.');
      }
      const response = await desktopBridge.saveBotAi(
        currentSession.editorToken,
        currentSession.revision,
        ai
      );
      if (!response.ok) {
        if (response.error.code === 'BOT_CHANGED_EXTERNALLY') {
          setConflict(true);
          throw new Error('El bot cambió en disco. Recargalo antes de guardar el historial.');
        }
        throw new Error(aiSaveErrorMessage(response.error.code));
      }
      const normalized = parseBotAi(response.data.ai);
      const nextSession = { ...currentSession, revision: response.data.revision };
      sessionRef.current = nextSession;
      setSession(nextSession);
      return normalized;
    });
  }

  async function persistAgentProposal(next: AgentProposalDraft): Promise<boolean> {
    const requestedSession = sessionRef.current;
    if (!requestedSession || requestedSession.editorToken !== next.editorToken || conflict) return false;
    const editorBotRevision = requestedSession.editorBotRevision
      || await canonicalBotRevision(requestedSession.saved);
    const pending = pendingAiProposalSchema.parse({
      proposal: next.proposal,
      operationBaseline: next.operationBaseline,
      original: next.original,
      editorBotRevision,
    });
    try {
      const response = await enqueueWrite('ai', requestedSession.editorToken, async () => {
        const currentSession = sessionRef.current;
        if (!currentSession || currentSession.editorToken !== requestedSession.editorToken) {
          throw new Error('La sesión del editor cambió.');
        }
        const saved = await desktopBridge.savePendingAiProposal(
          currentSession.editorToken,
          currentSession.revision,
          pending,
        );
        if (saved.ok) {
          const nextSession = {
            ...currentSession,
            revision: saved.data.revision,
            editorBotRevision,
          };
          sessionRef.current = nextSession;
          setSession(nextSession);
        } else if (saved.error.code === 'BOT_CHANGED_EXTERNALLY') {
          setConflict(true);
        }
        return saved;
      });
      if (!response.ok) {
        setError({
          code: response.error.code,
          message: response.error.code === 'BOT_PENDING_AI_TOO_LARGE'
            ? 'La propuesta es demasiado grande para conservarla.'
            : response.error.code === 'BOT_PENDING_AI_STALE'
              ? 'La propuesta pertenece a otra versión del bot y no se pudo conservar.'
            : 'No se pudo guardar la propuesta pendiente.',
        });
        return false;
      }
      return true;
    } catch {
      setError({ code: 'BOT_PENDING_AI_SAVE_FAILED', message: 'No se pudo guardar la propuesta pendiente.' });
      return false;
    }
  }

  async function save() {
    const currentEditor = editorRef.current;
    const currentSession = sessionRef.current;
    const assessed = assessmentRef.current;
    if (
      !currentEditor ||
      !currentSession ||
      savingRef.current ||
      agentProposalRef.current ||
      pendingWritesRef.current > 0 ||
      aiUnsynced ||
      conflict ||
      dragging ||
      ['starting', 'running', 'cancel_requested'].includes(executionRef.current.status) ||
      assessed?.editor !== currentEditor ||
      assessed.saved !== currentSession.saved ||
      !assessed.serializable
    )
      return;
    const generation = ++saveGenerationRef.current;
    const editorToken = currentSession.editorToken;
    function finishSave() {
      if (saveGenerationRef.current !== generation) return;
      savingRef.current = false;
      setSaving(false);
    }
    savingRef.current = true;
    setSaving(true);
    setError(null);
    let draft: CanonicalBot;
    try {
      draft = serializeEditorState(currentEditor);
    } catch {
      setError({ code: 'BOT_INVALID', message: errorMessage('BOT_INVALID', 'save') });
      finishSave();
      return;
    }
    let response;
    try {
      response = await enqueueWrite('manual', editorToken, async () => {
        const latestSession = sessionRef.current;
        if (!latestSession || latestSession.editorToken !== editorToken)
          throw new Error('La sesión del editor cambió.');
        const saveResponse = await desktopBridge.saveBot(
          editorToken,
          latestSession.revision,
          draft
        );
        if (saveResponse.ok) {
          const botRevision = saveResponse.data.botRevision
            ?? await canonicalBotRevision(draft);
          const nextSession = {
            ...latestSession,
            revision: saveResponse.data.revision,
            editorBotRevision: botRevision,
            saved: draft,
          };
          sessionRef.current = nextSession;
          setSession(nextSession);
        } else if (saveResponse.error.code === 'BOT_CHANGED_EXTERNALLY') {
          setConflict(true);
        }
        return saveResponse;
      });
    } catch {
      finishSave();
      return;
    }
    if (!mountedRef.current) return;
    const liveSession = sessionRef.current;
    if (
      saveGenerationRef.current !== generation ||
      !liveSession ||
      liveSession.editorToken !== editorToken ||
      !editorRef.current
    ) {
      finishSave();
      return;
    }
    if (response.ok) {
      const latestEditor = editorRef.current;
      if (latestEditor) reconcile(latestEditor, draft);
      setConflict(false);
    } else if (response.error.code === 'BOT_CHANGED_EXTERNALLY') {
      setConflict(true);
    } else {
      setError({ code: response.error.code, message: errorMessage(response.error.code, 'save') });
    }
    finishSave();
  }

  const saveEvent = useEffectEvent(save);
  useEffect(() => {
    function keyboardSave(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLocaleLowerCase() === 's') {
        event.preventDefault();
        void saveEvent();
      }
    }
    window.addEventListener('keydown', keyboardSave);
    return () => window.removeEventListener('keydown', keyboardSave);
  }, []);

  const deleteSelectedNodeEvent = useEffectEvent(() => {
    const current = editorRef.current;
    if (
      !current
      || agentProposalRef.current
      || current.representation === 'readOnlyGraph'
      || dragging
    ) return false;
    const selectedNode = current.nodes.find((node) => node.id === current.selectedNodeId);
    if (!selectedNode || selectedNode.data.readOnly) return false;
    dispatch({ type: 'nodeDeleted', nodeId: selectedNode.id });
    return true;
  });
  useEffect(() => {
    function keyboardDelete(event: KeyboardEvent) {
      if (
        event.key !== 'Delete' ||
        event.defaultPrevented ||
        event.ctrlKey ||
        event.altKey ||
        event.metaKey ||
        event.shiftKey ||
        isEditableDeleteTarget(event.target)
      )
        return;
      if (!deleteSelectedNodeEvent()) return;
      event.preventDefault();
      event.stopPropagation();
    }
    window.addEventListener('keydown', keyboardDelete);
    return () => window.removeEventListener('keydown', keyboardDelete);
  }, []);

  function addAction(actionType: string, index?: number, location?: TreeLocation) {
    dispatch({ type: 'nodeAdded', actionType, index, location });
    setCatalogOpen(false);
  }

  function focusIssue(nodeId: string) {
    dispatch({ type: 'nodeSelected', nodeId });
    setPropertiesOpen(true);
    document
      .getElementById(`sequence-block-${nodeId}`)
      ?.scrollIntoView({ behavior: prefersReducedMotion ? 'auto' : 'smooth', block: 'center' });
  }

  function startDrag(event: DragStartEvent) {
    draggingRef.current = true;
    setActiveDragId(event.active.id.toString());
    setDragging(true);
    assessmentRef.current = null;
    setAssessment(null);
  }

  function stopDrag(event: DragEndEvent) {
    const current = editorRef.current;
    const overId = event.over?.id.toString();
    if (current && overId) {
      const drop = resolveSequenceDrop(current, event.active.id.toString(), overId);
      if (drop?.kind === 'add') addAction(drop.actionType, drop.toIndex, drop.location);
      if (drop?.kind === 'reorder')
        dispatch({ type: 'nodeMoved', nodeId: drop.nodeId, to: drop.location, toIndex: drop.toIndex });
    }
    setActiveDragId(null);
    draggingRef.current = false;
    setDragging(false);
  }

  function cancelDrag() {
    setActiveDragId(null);
    draggingRef.current = false;
    setDragging(false);
  }

  function validate() {
    const currentSession = sessionRef.current;
    if (!editor || !currentSession) return;
    startValidationTransition(() => {
      setIssues(validateExecutionReadiness(editor, currentSession.botDirectoryPath));
      setValidationVisible(true);
    });
  }

  function getAiEditorContext(): AiEditorContext {
    const currentEditor = editorRef.current;
    const currentSession = sessionRef.current;
    if (!currentEditor || !currentSession) throw new Error('El editor no está disponible.');
    let bot: CanonicalBot;
    try {
      bot = serializeEditorState(currentEditor);
    } catch {
      const nodes = currentEditor.nodes.map((node) => ({
              id: node.id,
              type: node.data.actionType,
              params: structuredClone(node.data.params),
              ...(Object.keys(node.slots).length ? { slots: structuredClone(node.slots) } : {}),
            }));
      bot = parseCanonicalBot({
        ...currentEditor.metadata,
        flow: currentEditor.representation === 'readOnlyGraph'
          ? { nodes: nodes.map(({ slots: _slots, ...node }) => node), edges: structuredClone(currentEditor.legacyEdges) }
          : { root: currentEditor.root, nodes },
      });
    }
    const activeProposal = agentProposalRef.current;
    return {
      bot,
      validationIssues: validateExecutionReadiness(currentEditor, currentSession.botDirectoryPath),
      selectedBlockId: currentEditor.selectedNodeId,
      ...(activeProposal && activeProposal.editorToken === currentSession.editorToken ? {
        workingBot: structuredClone(activeProposal.proposed),
        workingValidationIssues: structuredClone(activeProposal.validationIssues),
        proposalVersion: activeProposal.proposal.version,
      } : {}),
    };
  }

  async function receiveAiProposal(
    proposal: AiBotProposal,
    requestContext: AiEditorContext,
    signal: AbortSignal
  ) {
    const currentEditor = editorRef.current;
    const currentSession = sessionRef.current;
    if (!currentEditor || !currentSession) return;
    const requestEditorToken = currentSession.editorToken;
    function assertCurrentRequest() {
      signal.throwIfAborted();
      if (
        sessionRef.current?.editorToken !== requestEditorToken
        || editorRef.current !== currentEditor
      ) throw new ProposalPatchError('El bot cambió mientras se verificaba la propuesta.');
    }
    assertCurrentRequest();
    if (proposalBusyNow()) {
      setError({ code: 'BOT_INVALID', message: 'La propuesta se descartó porque el editor estaba ocupado.' });
      return;
    }
    try {
      const validatedProposal = aiBotProposalSchema.parse(proposal);
      const requestOriginal = parseCanonicalBot(requestContext.bot);
      const requestBaseline = parseCanonicalBot(requestContext.workingBot ?? requestContext.bot);
      const baselineRevision = await canonicalBotRevision(requestBaseline);
      assertCurrentRequest();
      if (baselineRevision !== validatedProposal.baselineBotRevision) {
        throw new ProposalPatchError('La propuesta parte de una versión distinta del bot.');
      }
      if (proposalBusyNow()) {
        throw new ProposalPatchError('La propuesta se descartó porque el editor cambió de estado.');
      }
      assertCurrentRequest();
      const active = agentProposalRef.current;
      let original: CanonicalBot;
      if (requestContext.workingBot !== undefined) {
        if (
          !active
          || active.editorToken !== currentSession.editorToken
          || requestContext.proposalVersion !== active.proposal.version
          || validatedProposal.version !== active.proposal.version + 1
          || canonicalString(active.proposed) !== canonicalString(requestBaseline)
        ) throw new ProposalPatchError('La propuesta anterior cambió. Volvé a intentarlo.');
        original = active.original;
      } else {
        const liveBot = serializeEditorState(currentEditor);
        if (
          validatedProposal.version !== 1
          || canonicalString(liveBot) !== canonicalString(requestOriginal)
        ) throw new ProposalPatchError('El bot cambió mientras se generaba la propuesta.');
        original = liveBot;
      }
      const proposed = parseCanonicalBot(validateProposalResult(requestBaseline, validatedProposal));
      assertCurrentRequest();
      const proposedEditor = createEditorState(proposed);
      assertCurrentRequest();
      const roundTrip = serializeEditorState(proposedEditor);
      assertCurrentRequest();
      if (canonicalProposalBotString(roundTrip) !== canonicalProposalBotString(proposed)) {
        throw new ProposalPatchError('La propuesta no se puede representar de forma segura en el editor.');
      }
      const validationIssues = validateExecutionReadiness(proposedEditor, currentSession.botDirectoryPath);
      assertCurrentRequest();

      const isOriginalEmpty = original.flow.nodes.length === 0;
      const hasBlockingErrors = validationIssues.some((issue) => issue.severity === 'error');

      if (isOriginalEmpty && !hasBlockingErrors && requestContext.workingBot === undefined) {
        const editorToken = currentSession.editorToken;
        const acceptedDraft = proposed;
        savingRef.current = true;
        setSaving(true);
        setError(null);
        try {
          const response = await enqueueWrite('manual', editorToken, async () => {
            const latestSession = sessionRef.current;
            if (!latestSession || latestSession.editorToken !== editorToken || conflict) {
              throw new Error('La sesión del editor cambió.');
            }
            const saveResponse = await desktopBridge.saveBot(
              editorToken,
              latestSession.revision,
              acceptedDraft,
              true,
            );
            if (saveResponse.ok) {
              const botRevision = saveResponse.data.botRevision
                ?? await canonicalBotRevision(acceptedDraft);
              const nextSession = {
                ...latestSession,
                revision: saveResponse.data.revision,
                editorBotRevision: botRevision,
                saved: acceptedDraft,
              };
              sessionRef.current = nextSession;
              setSession(nextSession);
            } else if (saveResponse.error.code === 'BOT_CHANGED_EXTERNALLY') {
              setConflict(true);
            }
            return saveResponse;
          });
          if (
            !mountedRef.current
            || sessionRef.current?.editorToken !== editorToken
          ) return;
          if (!response.ok) {
            if (response.error.code !== 'BOT_CHANGED_EXTERNALLY') {
              setError({ code: response.error.code, message: errorMessage(response.error.code, 'save') });
            }
            return;
          }
          const nextEditor = createEditorState(acceptedDraft);
          editorRef.current = nextEditor;
          setEditor(nextEditor);
          const publication = {
            editor: nextEditor,
            saved: acceptedDraft,
            ...assessEditorState(nextEditor, acceptedDraft),
          };
          assessmentRef.current = publication;
          setAssessment(publication);
          agentProposalRef.current = null;
          persistedProposalRef.current = null;
          setAgentProposal(null);
          setValidationVisible(false);
          setIssues([]);
          return;
        } catch {
          if (mountedRef.current) {
            setError({ code: 'BOT_SAVE_FAILED', message: errorMessage('BOT_SAVE_FAILED', 'save') });
          }
          return;
        } finally {
          savingRef.current = false;
          if (mountedRef.current) {
            setSaving(false);
          }
        }
      }

      const next: AgentProposalDraft = {
        proposal: validatedProposal,
        operationBaseline: structuredClone(requestBaseline),
        original: structuredClone(original),
        proposed,
        editor: proposedEditor,
        validationIssues,
        editorToken: currentSession.editorToken,
      };
      if (proposalBusyNow()) {
        throw new ProposalPatchError('La propuesta se descartó porque el editor cambió de estado.');
      }
      assertCurrentRequest();
      if (!(await persistAgentProposal(next))) return;
      assertCurrentRequest();
      persistedProposalRef.current = next;
      agentProposalRef.current = next;
      setAgentProposal(next);
      setError(null);
      setValidationVisible(false);
      setIssues([]);
    } catch (proposalError) {
      if (signal.aborted) return;
      const message = proposalError instanceof ProposalPatchError
        ? proposalError.message
        : 'AutoClick AI generó una propuesta que no se puede aplicar.';
      setError({ code: 'BOT_INVALID', message });
    }
  }

  async function captureCoordinates(nodeId: string) {
    const currentEditor = editorRef.current;
    const currentSession = sessionRef.current;
    const node = currentEditor?.nodes.find((candidate) => candidate.id === nodeId);
    if (
      !currentEditor ||
      !currentSession ||
      captureActiveRef.current ||
      ['starting', 'running', 'cancel_requested'].includes(executionRef.current.status) ||
      currentEditor.selectedNodeId !== nodeId ||
      !node ||
      !['mouse.move', 'mouse.click', 'mouse.rightClick', 'mouse.doubleClick'].includes(node.data.actionType)
    )
      return;

    const generation = ++captureGenerationRef.current;
    const editorToken = currentSession.editorToken;
    const actionType = node.data.actionType;
    captureActiveRef.current = true;
    setCaptureInFlight(true);
    setCaptureNodeId(nodeId);
    setCaptureFeedback(null);
    const response = await desktopBridge.captureMousePosition();

    captureActiveRef.current = false;
    if (mountedRef.current) {
      setCaptureInFlight(false);
      setCaptureNodeId(null);
    }
    if (!mountedRef.current || captureGenerationRef.current !== generation) return;
    const latestEditor = editorRef.current;
    const latestSession = sessionRef.current;
    const latestNode = latestEditor?.nodes.find((candidate) => candidate.id === nodeId);
    const current =
      latestSession?.editorToken === editorToken &&
      latestEditor?.selectedNodeId === nodeId &&
      latestNode?.data.actionType === actionType;
    if (!current) return;

    if (response.ok) {
      dispatch({ type: 'coordinatesChanged', nodeId, x: response.data.x, y: response.data.y });
      setCaptureFeedback(null);
    } else if (response.error.code === 'CAPTURE_CANCELLED') {
      setCaptureFeedback({ nodeId, kind: 'status', message: 'Selección cancelada.' });
    } else {
      setCaptureFeedback({
        nodeId,
        kind: 'error',
        message: captureErrorMessage(response.error.code),
      });
    }
    window.setTimeout(() => {
      const focusEditor = editorRef.current;
      const focusSession = sessionRef.current;
      const focusNode = focusEditor?.nodes.find((candidate) => candidate.id === nodeId);
      if (
        mountedRef.current &&
        captureGenerationRef.current === generation &&
        focusSession?.editorToken === editorToken &&
        focusEditor?.selectedNodeId === nodeId &&
        focusNode?.data.actionType === actionType
      )
        captureButtonRef.current?.focus({ preventScroll: true });
    }, 0);
  }

  async function cancelExecution() {
    const current = executionRef.current;
    if (current.status === 'starting' && !current.runId) {
      cancelAfterStartRef.current = true;
      return;
    }
    if (!current.runId || !['starting', 'running', 'cancel_requested'].includes(current.status))
      return;
    dispatchExecution({ type: 'cancelRequested', runId: current.runId });
    const response = await desktopBridge.cancelExecution(current.runId);
    if (!mountedRef.current || response.ok) return;
    dispatchExecution({
      type: 'requestFailed',
      runId: current.runId,
      error: { ...response.error, message: executionErrorMessage(response.error.code) },
    });
  }

  async function execute() {
    const currentEditor = editorRef.current;
    const currentSession = sessionRef.current;
    const assessed = assessmentRef.current;
    if (
      !currentEditor ||
      !currentSession?.editorToken ||
      executionStartingRef.current ||
      savingRef.current ||
      captureActiveRef.current ||
      assessed?.editor !== currentEditor ||
      assessed.saved !== currentSession.saved ||
      !assessed.serializable ||
      !assessed.draft
    )
      return;
    const currentIssues = validateExecutionReadiness(
      currentEditor,
      currentSession.botDirectoryPath
    );
    if (currentIssues.length) {
      setIssues(currentIssues);
      setValidationVisible(true);
      return;
    }

    await startDraftExecution(currentSession, assessed.draft, currentEditor);
  }

  async function startDraftExecution(
    currentSession: Session,
    draft: CanonicalBot,
    draftEditor: BotEditorState
  ) {
    executionStartingRef.current = true;
    cancelAfterStartRef.current = false;
    const executionNodes = orderedNodes(draftEditor).map((editorNode) => draft.flow.nodes.find((node) => node.id === editorNode.id)!);
    executionDraftNodesRef.current = executionNodes;
    dispatchExecution({
      type: 'resetForNewRun',
      orderedBlockIds: executionNodes.map((node) => node.id),
    });
    const response = await desktopBridge.executeBot(currentSession.editorToken, draft);
    executionStartingRef.current = false;
    if (!mountedRef.current) {
      if (response.ok) void desktopBridge.cancelExecution(response.data.runId);
      return;
    }
    if (!response.ok) {
      dispatchExecution({
        type: 'startFailed',
        error: { ...response.error, message: executionErrorMessage(response.error.code) },
      });
      return;
    }
    dispatchExecution({ type: 'runStarted', result: response.data });
    if (cancelAfterStartRef.current) {
      cancelAfterStartRef.current = false;
      dispatchExecution({ type: 'cancelRequested', runId: response.data.runId });
      const cancellation = await desktopBridge.cancelExecution(response.data.runId);
      if (!mountedRef.current || cancellation.ok) return;
      dispatchExecution({
        type: 'requestFailed',
        runId: response.data.runId,
        error: { ...cancellation.error, message: executionErrorMessage(cancellation.error.code) },
      });
    }
  }

  async function executeProposal() {
    const active = agentProposalRef.current;
    const currentSession = sessionRef.current;
    if (
      !active
      || !currentSession
      || active.editorToken !== currentSession.editorToken
      || active.validationIssues.length > 0
      || proposalBusyNow()
    ) return;
    await startDraftExecution(currentSession, active.proposed, active.editor);
  }

  async function acceptProposal() {
    const active = agentProposalRef.current;
    const currentSession = sessionRef.current;
    if (
      !active
      || !currentSession
      || active.editorToken !== currentSession.editorToken
      || active.validationIssues.some((issue) => issue.severity === 'error')
      || proposalBusyNow()
    ) return;

    acceptingProposalRef.current = true;
    setAcceptingProposal(true);
    savingRef.current = true;
    setSaving(true);
    setError(null);
    const editorToken = currentSession.editorToken;
    const acceptedDraft = active.proposed;
    try {
      const response = await enqueueWrite('manual', editorToken, async () => {
        const latestSession = sessionRef.current;
        if (!latestSession || latestSession.editorToken !== editorToken || conflict) {
          throw new Error('La sesión del editor cambió.');
        }
        const saveResponse = await desktopBridge.saveBot(
          editorToken,
          latestSession.revision,
          acceptedDraft,
          true,
        );
        if (saveResponse.ok) {
          const botRevision = saveResponse.data.botRevision
            ?? await canonicalBotRevision(acceptedDraft);
          const nextSession = {
            ...latestSession,
            revision: saveResponse.data.revision,
            editorBotRevision: botRevision,
            saved: acceptedDraft,
          };
          sessionRef.current = nextSession;
          setSession(nextSession);
        } else if (saveResponse.error.code === 'BOT_CHANGED_EXTERNALLY') {
          setConflict(true);
        }
        return saveResponse;
      });
      if (
        !mountedRef.current
        || agentProposalRef.current !== active
        || sessionRef.current?.editorToken !== editorToken
      ) return;
      if (!response.ok) {
        if (response.error.code !== 'BOT_CHANGED_EXTERNALLY') {
          setError({ code: response.error.code, message: errorMessage(response.error.code, 'save') });
        }
        return;
      }
      const nextEditor = createEditorState(acceptedDraft);
      editorRef.current = nextEditor;
      setEditor(nextEditor);
      const publication = {
        editor: nextEditor,
        saved: acceptedDraft,
        ...assessEditorState(nextEditor, acceptedDraft),
      };
      assessmentRef.current = publication;
      setAssessment(publication);
      agentProposalRef.current = null;
      persistedProposalRef.current = null;
      setAgentProposal(null);
      setValidationVisible(false);
      setIssues([]);
    } catch {
      if (mountedRef.current) {
        setError({ code: 'BOT_SAVE_FAILED', message: errorMessage('BOT_SAVE_FAILED', 'save') });
      }
    } finally {
      acceptingProposalRef.current = false;
      savingRef.current = false;
      if (mountedRef.current) {
        setAcceptingProposal(false);
        setSaving(false);
      }
    }
  }

  async function rejectProposal() {
    if (proposalBusyNow()) return;
    const active = agentProposalRef.current;
    const currentSession = sessionRef.current;
    if (!active || !currentSession || active.editorToken !== currentSession.editorToken) return;
    agentProposalRef.current = null;
    setAgentProposal(null);
    setPendingRestoreRetry(null);
    try {
      const response = await enqueueWrite('ai', currentSession.editorToken, async () => {
        const latestSession = sessionRef.current;
        if (!latestSession || latestSession.editorToken !== currentSession.editorToken) {
          throw new Error('La sesión del editor cambió.');
        }
        const saved = await desktopBridge.savePendingAiProposal(
          latestSession.editorToken,
          latestSession.revision,
          null,
        );
        if (saved.ok) {
          const nextSession = { ...latestSession, revision: saved.data.revision };
          sessionRef.current = nextSession;
          setSession(nextSession);
        } else if (saved.error.code === 'BOT_CHANGED_EXTERNALLY') {
          setConflict(true);
        }
        return saved;
      });
      if (!response.ok) {
        agentProposalRef.current = active;
        setAgentProposal(active);
        setError({ code: response.error.code, message: 'No se pudo descartar la propuesta pendiente.' });
        return;
      }
      persistedProposalRef.current = null;
    } catch {
      agentProposalRef.current = active;
      setAgentProposal(active);
      setError({ code: 'BOT_PENDING_AI_SAVE_FAILED', message: 'No se pudo descartar la propuesta pendiente.' });
    }
  }

  function leaveConflict() {
    allowNextNavigationRef.current = true;
    navigate('/explorer');
  }

  if (loading) {
    return (
      <main className="grid min-h-screen place-items-center bg-bg" role="status">
        <div className="flex flex-col items-center gap-3 text-center">
          <Mascot interactive={false} size={72} state="walk" />
          <p className="m-0 font-extrabold">Cargando editor…</p>
        </div>
      </main>
    );
  }

  if (!editor || !session) {
    return (
      <main className="grid min-h-screen place-items-center bg-bg p-5">
        <section
          className="w-full max-w-lg rounded-panel border border-border bg-surface p-6 text-center shadow-sm"
          role="alert">
          <AlertTriangle aria-hidden="true" className="mx-auto mb-3 text-danger" size={28} />
          <h1 className="m-0 text-xl font-extrabold">No se pudo abrir el editor</h1>
          <p className="mt-2 mb-5 leading-5 text-text-muted">{error?.message}</p>
          <div className="flex flex-col justify-center gap-2 sm:flex-row">
            <Button onClick={() => navigate('/explorer')} variant="secondary">
              <ArrowLeft aria-hidden="true" size={16} />
              Volver al Explorador
            </Button>
            <Button onClick={() => void loadFromDisk()}>
              <RefreshCw aria-hidden="true" size={16} />
              Intentar nuevamente
            </Button>
          </div>
        </section>
      </main>
    );
  }

  return (
    <DndContext
      accessibility={{
        announcements: createSequenceAnnouncements(editor),
        screenReaderInstructions: {
          draggable:
            'Para levantar un bloque, presioná Espacio. Usá las flechas para moverlo. Presioná Espacio para soltarlo o Escape para cancelar.',
        },
      }}
      collisionDetection={sequenceCollisionDetection}
      onDragCancel={cancelDrag}
      onDragEnd={stopDrag}
      onDragStart={startDrag}
      sensors={sensors}>
      <main className="flex h-dvh min-h-0 flex-col overflow-hidden bg-bg">
        {error ? (
          <div className="border-b border-border bg-surface px-3 py-2 sm:px-4">
            <Alert className="mb-0">
              <span className="flex items-center justify-between gap-3">
                <span>{error.message}</span>
                {pendingRestoreRetry ? (
                  <button
                    className="shrink-0 font-bold underline"
                    onClick={() => void restorePendingProposal(
                      pendingRestoreRetry.pending,
                      pendingRestoreRetry.editorToken,
                      pendingRestoreRetry.loadGeneration,
                    )}
                    type="button">
                    Reintentar propuesta
                  </button>
                ) : null}
              </span>
            </Alert>
          </div>
        ) : null}
        <div className="relative flex min-h-0 flex-1 flex-col lg:flex-row">
          <BotAiProvider
            blocked={saving || activeWrite === 'manual' || conflict}
            initialState={session.initialAi}
            key={session.editorToken}
            onProposal={receiveAiProposal}
            onUnsyncedChange={(value) => {
              aiUnsyncedRef.current = value;
              setAiUnsynced(value);
            }}
            save={persistBotAi}>
            <div className="flex min-h-0 w-full shrink-0 flex-col lg:w-[380px] lg:shrink-0 lg:border-r lg:border-border">
              {aiChatOpen ? (
                <motion.div
                  animate={{ opacity: 1, x: 0 }}
                  className="flex h-[min(70dvh,42rem)] min-h-0 w-full shrink-0 flex-col lg:h-auto lg:flex-1"
                  initial={{ opacity: 0, x: 10 }}
                  key="ai-panel"
                  transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}>
                  <EditorAiPanel getEditorContext={getAiEditorContext} onClose={() => setAiChatOpen(false)} />
                </motion.div>
              ) : (
                <motion.div
                  animate={{ opacity: 1, x: 0 }}
                  className="flex min-h-0 flex-1 flex-col"
                  initial={{ opacity: 0, x: -10 }}
                  key="toolbar"
                  transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}>
                  <EditorToolbar
                    description={editor.metadata.description}
                    editingDisabled={Boolean(agentProposal)}
                    name={editor.metadata.name}
                    onBack={() => navigate('/explorer')}
                    onCatalogOpen={() => setCatalogOpen(true)}
                    onChangeDescription={(description) => dispatch({ type: 'metadataChanged', description })}
                    onChangeName={(name) => dispatch({ type: 'metadataChanged', name })}
                  />
                  <ActionCatalog
                    canCancel={canCancel}
                    canExecute={canExecute}
                    canSave={canSave}
                    cancelling={execution.status === 'cancel_requested'}
                    dirty={dirty}
                    disabled={Boolean(agentProposal)}
                    onAdd={addAction}
                    onCancel={() => void cancelExecution()}
                    onClose={() => setCatalogOpen(false)}
                    onExecute={() => void execute()}
                    onSave={() => void save()}
                    onValidate={validate}
                    open={catalogOpen}
                    saving={saving}
                  />
                </motion.div>
              )}
            </div>
          </BotAiProvider>
          <section
            aria-label="Editor visual"
            className="relative flex min-w-0 flex-1 flex-col focus-visible:outline-none focus-visible:shadow-focus"
            ref={editorRegionRef}
            tabIndex={-1}>
            {agentProposal && proposalCurrent ? (
              <ProposalComparison
                accepting={acceptingProposal}
                editingDisabled={proposalEditingDisabled}
                editingDisabledReason={proposalEditingDisabledReason}
                canAccept={canAcceptProposal}
                canExecute={canExecuteProposal}
                canReject={canRejectProposal}
                executionStatuses={execution.blocks}
                goToTargets={getGoToTargetOptions(agentProposal.editor, selectedProposalNode)}
                onAccept={() => void acceptProposal()}
                onExecute={() => void executeProposal()}
                onProposalChange={(nodeId, fieldName, value) =>
                  dispatchProposal({ type: 'parameterChanged', nodeId, fieldName, value })
                }
                onProposalSelect={(nodeId) => dispatchProposal({ type: 'nodeSelected', nodeId })}
                onProposalToggle={(nodeId) => dispatchProposal({ type: 'nodeCollapsed', nodeId })}
                onReject={() => void rejectProposal()}
                original={agentProposal.original}
                proposed={agentProposal.proposed}
                proposalEditor={agentProposal.editor}
                summary={agentProposal.proposal.summary}
                validationIssues={agentProposal.validationIssues}
                version={agentProposal.proposal.version}
              />
            ) : (
              <>
                <div className="min-h-0 flex-1" data-testid="sequence-region">
                  <SequenceStack
                    executionStatuses={execution.blocks}
                    issues={issues}
                    state={editor}
                    onDelete={(nodeId) => dispatch({ type: 'nodeDeleted', nodeId })}
                    onMove={(nodeId, to, toIndex) => dispatch({ type: 'nodeMoved', nodeId, to, toIndex })}
                    onSelect={(nodeId) => {
                      dispatch({ type: 'nodeSelected', nodeId });
                      setPropertiesOpen(true);
                    }}
                    onToggle={(nodeId) => dispatch({ type: 'nodeCollapsed', nodeId })}
                    readOnly={editor.representation === 'readOnlyGraph'}
                  />
                </div>
                <ValidationPanel issues={issues} onFocus={focusIssue} visible={validationVisible} />
              </>
            )}
            <AiChatBubble onOpen={() => setAiChatOpen(true)} open={aiChatOpen} ref={aiBubbleRef} />
          </section>
          <OverlayDialog
            ariaLabel="Configuración del bloque"
            className="hidden inset-0 h-screen w-screen p-4 open:grid open:place-items-center"
            focusKey={selectedNode?.id}
            onDismiss={() => setPropertiesOpen(false)}
            open={propertiesOpen && Boolean(selectedNode)}>
            <div className="@container max-h-[85vh] w-full max-w-2xl overflow-hidden rounded-panel border border-border bg-surface shadow-overlay">
              <div className="flex items-center gap-3 border-b border-border px-5 pt-4 pb-3.5">
                <span className="grid size-10 shrink-0 place-items-center rounded-control bg-blue-50 text-primary shadow-sm">
                  <SelectedActionIcon aria-hidden="true" size={19} />
                </span>
                <h2 className="m-0 min-w-0 flex-1 truncate text-lg font-extrabold">
                  {selectedAction?.title ?? selectedNode?.data.actionType}
                </h2>
                <button
                  aria-label="Cerrar configuración del bloque"
                  className="shrink-0 rounded-control p-1.5 text-text-muted transition-colors hover:bg-black/5 hover:text-text focus-visible:outline-none focus-visible:shadow-focus"
                  data-dialog-initial-focus
                  onClick={() => setPropertiesOpen(false)}
                  type="button">
                  <X aria-hidden="true" size={18} />
                </button>
              </div>
              <div className="max-h-[calc(85vh-4.5rem)] overflow-y-auto">
                <ConfigurationPanel
                  captureActive={captureActive}
                  captureButtonRef={captureButtonRef}
                  captureDisabled={captureInFlight || executionActive || Boolean(agentProposal)}
                  captureFeedback={
                    captureFeedback?.nodeId === selectedNode?.id ? captureFeedback : null
                  }
                  captureNodeId={captureNodeId}
                  disabled={Boolean(agentProposal)}
                  hideHeader
                  issues={issues}
                  goToTargets={getGoToTargetOptions(editor, selectedNode)}
                  node={selectedNode}
                  onCaptureCoordinates={(nodeId) => void captureCoordinates(nodeId)}
                  onChange={(fieldName, value) =>
                    selectedNode &&
                    dispatch({ type: 'parameterChanged', nodeId: selectedNode.id, fieldName, value })
                  }
                />
              </div>
            </div>
          </OverlayDialog>
        </div>
        <ExecutionConsole
          currentBlockName={currentBlockName}
          execution={execution}
          key={session.editorToken}
        />
      </main>
      <OverlayDialog
        className="inset-0 h-screen w-screen p-4"
        dismissible={false}
        labelledBy="conflict-title"
        onDismiss={() => {}}
        open={conflict}
        restoreFocus={false}>
        <div className="mx-auto mt-[max(12vh,3rem)] w-full max-w-md rounded-panel border border-border bg-surface p-5 shadow-overlay">
          <AlertTriangle aria-hidden="true" className="mb-3 text-warning" size={25} />
          <h2 className="m-0 text-lg font-extrabold" id="conflict-title">
            El bot cambió en disco
          </h2>
          <p className="mt-2 mb-5 leading-5 text-text-muted">
            No se sobrescribió el archivo. Recargá la versión actual o volvé al Explorador.
          </p>
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button onClick={leaveConflict} variant="secondary">
              Volver al Explorador
            </Button>
            <Button data-dialog-initial-focus onClick={() => void loadFromDisk()}>
              <RefreshCw aria-hidden="true" size={16} />
              Recargar desde disco
            </Button>
          </div>
        </div>
      </OverlayDialog>
      {execution.runId ? (
        <ExecutionPolling dispatch={dispatchExecution} runId={execution.runId} />
      ) : null}
      <NavigationPrompt
        allowNextNavigationRef={allowNextNavigationRef}
        conflict={conflict}
        controlRef={navigationPromptControlRef}
        executionActive={executionActive}
        onExecutionLeaveAttempt={() => void cancelExecution()}
        protectedState={
          dirty || saving || pendingWrites > 0 || aiUnsynced || conflict || executionActive || Boolean(agentProposal)
        }
        saving={saving || pendingWrites > 0}
      />
      <DragOverlay dropAnimation={null}>
        {activeDragActionType ? <DragBlockPreview actionType={activeDragActionType} /> : null}
      </DragOverlay>
    </DndContext>
  );
}

export function EditorPage() {
  return (
    <MotionConfig reducedMotion="user">
      <EditorPageContent />
    </MotionConfig>
  );
}

export function getGoToTargetOptions(editor: BotEditorState, selectedNode: BotEditorNode | null) {
  if (!selectedNode || selectedNode.data.actionType !== 'flow.goTo') return [];
  const containers = [editor.root, ...editor.nodes.flatMap((node) => Object.values(node.slots))];
  const container = containers.find((ids) => ids.includes(selectedNode.id)) ?? [];
  const byId = new Map(editor.nodes.map((node) => [node.id, node]));
  return container.filter((id) => id !== selectedNode.id).map((id) => {
    const target = byId.get(id);
    return { id, label: `${actionsById.get(target?.data.actionType ?? '')?.title ?? id} (${id})` };
  });
}
