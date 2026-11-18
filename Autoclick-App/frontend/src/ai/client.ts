import type { AiChatRequest, AiStreamEvent } from '@/ai/types';
import { authorizeAi, cloudEnabled } from '@/cloud/client';
import type { AiMessageMetrics } from '@/ai/types';
import { aiBotProposalSchema } from '@/ai/proposalSchema';
import { aiBotDraftSchema, type AiBotDraft } from '@/ai/botDraft';

export const AI_MAX_SSE_FRAME_CHARS = 64 * 1024;

export class AiClientError extends Error {
  constructor(readonly code: string, message: string, readonly requestId?: string) {
    super(requestId ? `${message} (ID: ${requestId})` : message);
    this.name = 'AiClientError';
  }
}

type StreamCallbacks = {
  onStart(event: Extract<AiStreamEvent, { type: 'start' }>): void;
  onThinking(content: string): void;
  onStatus?(status: Extract<AiStreamEvent, { type: 'status' }>): void;
  onDelta(content: string): void;
  onProposal?(proposal: Extract<AiStreamEvent, { type: 'proposal' }>['proposal'], signal: AbortSignal): void | Promise<void>;
  onBotDraft?(draft: AiBotDraft, signal: AbortSignal): void | Promise<void>;
  onDone(finishReason: string, metrics: AiMessageMetrics): void | Promise<void>;
};

function endpoint(baseUrl: string, path: string): string {
  return `${baseUrl.replace(/\/+$/, '')}${path}`;
}

export async function fetchAiHealth(baseUrl: string, signal?: AbortSignal): Promise<unknown> {
  const response = await fetch(endpoint(baseUrl, '/health'), { signal, headers: { Accept: 'application/json' } });
  if (!response.ok) throw await responseError(response);
  return response.json();
}

export async function streamAiChat(baseUrl: string, request: AiChatRequest, signal: AbortSignal, callbacks: StreamCallbacks): Promise<void> {
  const cloudHeaders = cloudEnabled ? await authorizeAi(signal) : {};
  signal.throwIfAborted();
  const response = await fetch(endpoint(baseUrl, '/v1/chat/stream'), {
    method: 'POST',
    headers: { Accept: 'text/event-stream', 'Content-Type': 'application/json', ...cloudHeaders },
    body: JSON.stringify(request),
    signal,
  });
  if (!response.ok) throw await responseError(response);
  if (!response.body) throw new AiClientError('INVALID_RESPONSE', 'La respuesta del servicio AI no contiene un stream.');

  let started = false;
  let answerStarted = false;
  let terminal = false;
  let finishReason = '';
  let metrics: AiMessageMetrics | null = null;
  let proposalSeen = false;
  let pendingProposal: Extract<AiStreamEvent, { type: 'proposal' }>['proposal'] | null = null;
  let pendingBotDraft: AiBotDraft | null = null;
  let botDraftSeen = false;
  let requestId: string | undefined;
  for await (const event of parseSseStream(response.body)) {
    if (terminal) throw new AiClientError('INVALID_RESPONSE', 'El servicio AI envió datos después de finalizar.');
    if (event.type === 'start') {
      if (started) throw new AiClientError('INVALID_RESPONSE', 'El servicio AI inició la respuesta más de una vez.');
      started = true;
      requestId = event.requestId;
      callbacks.onStart(event);
    } else if (event.type === 'thinking') {
      if (!started || answerStarted) throw new AiClientError('INVALID_RESPONSE', 'El servicio AI envió razonamiento fuera de orden.');
      callbacks.onThinking(event.content);
    } else if (event.type === 'status') {
      if (!started || answerStarted) throw new AiClientError('INVALID_RESPONSE', 'El servicio AI envió estado fuera de orden.');
      callbacks.onStatus?.(event);
    } else if (event.type === 'delta') {
      if (!started) throw new AiClientError('INVALID_RESPONSE', 'El servicio AI respondió fuera de orden.');
      answerStarted = true;
      callbacks.onDelta(event.content);
    } else if (event.type === 'proposal') {
      if (!started || !answerStarted || proposalSeen) throw new AiClientError('INVALID_RESPONSE', 'El servicio AI envió una propuesta fuera de orden.');
      proposalSeen = true;
      pendingProposal = event.proposal;
    } else if (event.type === 'botDraft') {
      if (!started || !answerStarted || botDraftSeen) throw new AiClientError('INVALID_RESPONSE', 'El servicio AI envió un borrador fuera de orden.');
      botDraftSeen = true;
      pendingBotDraft = event.draft;
    } else if (event.type === 'done') {
      if (!started) throw new AiClientError('INVALID_RESPONSE', 'El servicio AI finalizó fuera de orden.');
      terminal = true;
      finishReason = event.finishReason;
      metrics = event.metrics;
    } else {
      terminal = true;
      throw new AiClientError(event.code, event.message, event.requestId ?? requestId);
    }
  }
  if (!terminal) throw new AiClientError('INVALID_RESPONSE', 'La conexión AI terminó antes de completar la respuesta.');
  if (!metrics) throw new AiClientError('INVALID_RESPONSE', 'El servicio AI finalizó sin métricas válidas.');
  const proposal = pendingProposal;
  const onProposal = callbacks.onProposal;
  if (proposal && onProposal) {
    await runTerminalCallback(() => onProposal(proposal, signal), signal);
  }
  const botDraft = pendingBotDraft;
  const onBotDraft = callbacks.onBotDraft;
  if (botDraft && onBotDraft) {
    await runTerminalCallback(() => onBotDraft(botDraft, signal), signal);
  }
  await runTerminalCallback(() => callbacks.onDone(finishReason, metrics), signal);
}

async function runTerminalCallback(callback: () => void | Promise<void>, signal: AbortSignal): Promise<void> {
  signal.throwIfAborted();
  const pending = callback();
  if (!pending) {
    signal.throwIfAborted();
    return;
  }
  await new Promise<void>((resolve, reject) => {
    const onAbort = () => {
      signal.removeEventListener('abort', onAbort);
      reject(signal.reason ?? new DOMException('aborted', 'AbortError'));
    };
    signal.addEventListener('abort', onAbort, { once: true });
    Promise.resolve(pending).then(
      () => {
        signal.removeEventListener('abort', onAbort);
        resolve();
      },
      (error) => {
        signal.removeEventListener('abort', onAbort);
        reject(error);
      }
    );
  });
}

export async function* parseSseStream(stream: ReadableStream<Uint8Array>): AsyncGenerator<AiStreamEvent> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let completed = false;
  try {
    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      while (true) {
        const delimiter = /\r?\n\r?\n|\r\r/.exec(buffer);
        if (!delimiter || delimiter.index === undefined) break;
        const frame = buffer.slice(0, delimiter.index);
        if (frame.length > AI_MAX_SSE_FRAME_CHARS) throw invalidFrameSize();
        buffer = buffer.slice(delimiter.index + delimiter[0].length);
        const event = parseFrame(frame.replaceAll('\r\n', '\n').replaceAll('\r', '\n'));
        if (event) yield event;
      }
      if (buffer.length > AI_MAX_SSE_FRAME_CHARS) throw invalidFrameSize();
      if (done) {
        completed = true;
        break;
      }
    }
    if (buffer.trim()) {
      const event = parseFrame(buffer.replaceAll('\r\n', '\n').replaceAll('\r', '\n'));
      if (event) yield event;
    }
  } finally {
    if (!completed) {
      try {
        await reader.cancel();
      } catch {
        // Preserve the protocol error or consumer cancellation that stopped iteration.
      }
    }
    reader.releaseLock();
  }
}

function invalidFrameSize(): AiClientError {
  return new AiClientError('INVALID_RESPONSE', 'El servicio AI envió un evento demasiado grande.');
}

function parseFrame(frame: string): AiStreamEvent | null {
  let eventName = '';
  const data: string[] = [];
  for (const line of frame.split('\n')) {
    if (!line || line.startsWith(':')) continue;
    const colon = line.indexOf(':');
    const field = colon < 0 ? line : line.slice(0, colon);
    let value = colon < 0 ? '' : line.slice(colon + 1);
    if (value.startsWith(' ')) value = value.slice(1);
    if (field === 'event') eventName = value;
    if (field === 'data') data.push(value);
  }
  if (!eventName && !data.length) return null;
  let payload: unknown;
  try {
    payload = JSON.parse(data.join('\n'));
  } catch {
    throw new AiClientError('INVALID_RESPONSE', 'El servicio AI envió un evento inválido.');
  }
  if (!payload || typeof payload !== 'object') throw new AiClientError('INVALID_RESPONSE', 'El servicio AI envió un evento inválido.');
  const value = payload as Record<string, unknown>;
  if (eventName === 'start' && typeof value.requestId === 'string' && typeof value.model === 'string') return { type: 'start', requestId: value.requestId, model: value.model };
  if (eventName === 'thinking' && typeof value.content === 'string') return { type: 'thinking', content: value.content };
  if (eventName === 'status') {
    const stage = typeof value.stage === 'string' ? value.stage : undefined;
    const content = typeof value.content === 'string' ? value.content : (stage ?? '');
    return {
      type: 'status',
      content,
      ...(stage ? { stage } : {}),
    };
  }
  if (eventName === 'delta' && typeof value.content === 'string') return { type: 'delta', content: value.content };
  if (eventName === 'proposal') {
    const proposal = aiBotProposalSchema.safeParse(value);
    if (proposal.success) return { type: 'proposal', proposal: proposal.data };
    if (Array.isArray(value.operations) && value.operations.length === 0) return null;
    throw new AiClientError('INVALID_RESPONSE', 'El servicio AI envió una propuesta de cambios inválida.');
  }
  if (eventName === 'botDraft') {
    const draft = aiBotDraftSchema.safeParse(value);
    if (draft.success) return { type: 'botDraft', draft: draft.data };
    throw new AiClientError('INVALID_RESPONSE', 'El servicio AI envió un borrador de bot inválido.');
  }
  if (eventName === 'done' && typeof value.finishReason === 'string') {
    const metrics = parseMetrics(value.metrics);
    if (metrics) return { type: 'done', finishReason: value.finishReason, metrics };
  }
  if (eventName === 'error' && typeof value.code === 'string' && typeof value.message === 'string' && typeof value.requestId === 'string') return { type: 'error', code: value.code, message: value.message, requestId: value.requestId };
  throw new AiClientError('INVALID_RESPONSE', 'El servicio AI envió un evento desconocido o incompleto.');
}

function parseMetrics(input: unknown): AiMessageMetrics | null {
  if (!input || typeof input !== 'object' || Array.isArray(input)) return null;
  const value = input as Record<string, unknown>;
  if (Object.keys(value).some((key) => !['totalTimeMs', 'inputTokens', 'outputTokens'].includes(key))) return null;
  if (!isCount(value.totalTimeMs) || !isNullableCount(value.inputTokens) || !isNullableCount(value.outputTokens)) return null;
  return { totalTimeMs: value.totalTimeMs, inputTokens: value.inputTokens, outputTokens: value.outputTokens };
}

function isCount(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
}

function isNullableCount(value: unknown): value is number | null {
  return value === null || isCount(value);
}

async function responseError(response: Response): Promise<AiClientError> {
  try {
    const body = await response.json() as { code?: unknown; message?: unknown; error?: { code?: unknown; message?: unknown } };
    const error = body.error ?? body;
    if (typeof error.code === 'string' && typeof error.message === 'string') return new AiClientError(error.code, error.message);
  } catch {
    // The public fallback deliberately excludes raw response data.
  }
  return new AiClientError('API_UNAVAILABLE', 'No se pudo comunicar con el servicio de AutoClick AI.');
}
