import { fetchAuthSession } from 'aws-amplify/auth';

export const cloudEnabled = Boolean(import.meta.env.VITE_AUTOCLICK_CLOUD_URL);
export const CLOUD_REQUEST_TIMEOUT_MS = 35_000;
const CLOUD_MAX_ATTEMPTS = 3;
const CLOUD_RETRY_DELAY_MS = 1_500;
type Organization = { id: string; name: string; status: string; monthlyTokenLimit: number };
type Area = { id: string; organizationId: string; name: string; status: string; tokenLimit: number };
export type CloudProfile = {
  user: { id: string; name: string };
  organization: Organization | null;
  unlimited?: boolean;
  organizations: Organization[];
  areas: Area[];
  tokenUsage: { userId: string; organizationId: string; areaId: string; period: string; tokensUsed: number; reservedTokens: number }[];
  period: string;
};

class CloudApiError extends Error {
  constructor(public code: string, message: string, public status: number) { super(message); }
}

export class DesktopAccessError extends Error {
  constructor(message: string, public retryable = false) { super(message); }
}

export async function requireDesktopSession(signal?: AbortSignal): Promise<CloudProfile> {
  if (!cloudEnabled) throw new DesktopAccessError('Falta configurar la conexión de Desktop con AutoClick. Contactá al administrador.');
  try {
    return await cloudApi<CloudProfile>('/desktop/session', undefined, signal);
  } catch (error) {
    const messages: Record<string, string> = {
      DESKTOP_MEMBERSHIP_REQUIRED: 'Tu cuenta es válida, pero necesitás pertenecer a una organización activa para ingresar a Desktop. Pedí al administrador que te incorpore.',
      ORGANIZATION_ASSIGNMENT_INVALID: 'La asignación de tu organización necesita una corrección administrativa. Contactá al administrador.',
      DESKTOP_ORGANIZATION_AMBIGUOUS: 'La asignación de tu organización necesita una corrección administrativa. Contactá al administrador.',
      FORBIDDEN: 'Tu cuenta no tiene acceso habilitado a Desktop. Contactá al administrador.',
      UNAUTHENTICATED: 'La sesión venció. Volvé a iniciar sesión.',
      SERVICE_UNAVAILABLE: 'El servicio de AutoClick todavía se está iniciando. Esperá unos segundos y volvé a intentar; tu cuenta sigue conectada.',
    };
    if (signal?.aborted) throw error;
    throw new DesktopAccessError((error instanceof CloudApiError && messages[error.code]) || 'No se pudo verificar tu acceso a Desktop. Revisá tu conexión e intentá nuevamente.', !(error instanceof CloudApiError) || error.status >= 500);
  }
}

export async function cloudApi<T>(path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  signal?.throwIfAborted();
  const session = await fetchAuthSession().catch(error => {
    signal?.throwIfAborted();
    if (error instanceof Error && error.name === 'TimeoutError') throw cloudTransportError(true);
    throw error;
  });
  signal?.throwIfAborted();
  const token = session.tokens?.accessToken.toString();
  if (!token) throw new Error('Iniciá sesión para usar los servicios de AutoClick.');
  for (let attempt = 0; ; attempt++) {
    signal?.throwIfAborted();
    try {
      return await cloudAttempt<T>(path, token, body, signal);
    } catch (error) {
      if (body !== undefined || signal?.aborted || !transientCloudError(error) || attempt >= CLOUD_MAX_ATTEMPTS - 1) throw error;
    }
    // Only reads retry here; ordinary mutations must not be repeated.
    await waitForCloudRetry(signal);
  }
}

function cloudTransportError(timedOut: boolean): CloudApiError {
  return new CloudApiError(timedOut ? 'CLOUD_TIMEOUT' : 'CLOUD_UNAVAILABLE',
    timedOut ? 'El servicio de AutoClick tardó demasiado en responder. Revisá tu conexión e intentá nuevamente.'
      : 'No se pudo conectar con el servicio de AutoClick. Revisá tu conexión e intentá nuevamente.', 0);
}

function transientCloudError(error: unknown): boolean {
  return error instanceof CloudApiError &&
    (['CLOUD_TIMEOUT', 'CLOUD_UNAVAILABLE'].includes(error.code) || [502, 503, 504].includes(error.status));
}

async function cloudAttempt<T>(path: string, token: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const controller = new AbortController();
  const onAbort = () => controller.abort(signal?.reason);
  signal?.addEventListener('abort', onAbort, { once: true });
  const timeout = setTimeout(() => controller.abort(new DOMException('Cloud request timed out', 'TimeoutError')), CLOUD_REQUEST_TIMEOUT_MS);
  try {
    signal?.throwIfAborted();
    const response = await fetch(`${import.meta.env.VITE_AUTOCLICK_CLOUD_URL.replace(/\/+$/, '')}/v1${path}`, {
      method: body === undefined ? 'GET' : 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      signal: controller.signal,
    });
    // Reading the body belongs to the attempt too. Do not swallow a timeout
    // here and accidentally return an empty authorization as a success.
    const data = await response.json().catch(error => {
      if (controller.signal.aborted || !(error instanceof SyntaxError)) throw error;
      if (response.ok) throw new CloudApiError('INVALID_RESPONSE', 'El servicio de AutoClick devolvió una respuesta incompleta. Intentá nuevamente.', response.status);
      return {};
    });
    signal?.throwIfAborted();
    if (!response.ok) throw new CloudApiError(data.code || (response.status >= 500 ? 'SERVICE_UNAVAILABLE' : 'REQUEST_FAILED'), data.message || 'No se pudo conectar con AutoClick.', response.status);
    return data as T;
  } catch (error) {
    signal?.throwIfAborted();
    if (error instanceof CloudApiError) throw error;
    throw cloudTransportError(controller.signal.aborted || (error instanceof Error && error.name === 'TimeoutError'));
  } finally {
    clearTimeout(timeout);
    signal?.removeEventListener('abort', onAbort);
  }
}

function waitForCloudRetry(signal?: AbortSignal): Promise<void> {
  signal?.throwIfAborted();
  return new Promise((resolve, reject) => {
    const onAbort = () => {
      clearTimeout(timer);
      signal?.removeEventListener('abort', onAbort);
      reject(signal?.reason);
    };
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort);
      resolve();
    }, CLOUD_RETRY_DELAY_MS);
    signal?.addEventListener('abort', onAbort, { once: true });
  });
}

export async function authorizeAi(signal: AbortSignal): Promise<Record<string, string>> {
  const profile = await requireDesktopSession(signal);
  if (!profile.unlimited && !profile.areas.some(a => a.status === 'active' && a.organizationId === profile.organization?.id)) {
    throw new Error('Un administrador debe asignarte un área activa para usar IA.');
  }
  for (let attempt = 0; ; attempt++) {
    signal.throwIfAborted();
    try {
      const result = await cloudApi<{ requestId: string; authorization: string }>('/ai/authorize', {
        requestId: crypto.randomUUID(),
      }, signal);
      if (!result || typeof result.requestId !== 'string' || !result.requestId || typeof result.authorization !== 'string' || !result.authorization) throw new CloudApiError('INVALID_RESPONSE', 'AutoClick no devolvió una autorización válida. Intentá nuevamente.', 0);
      return { Authorization: `Bearer ${result.authorization}`, 'X-AutoClick-Request-Id': result.requestId };
    } catch (error) {
      if (signal.aborted || !transientCloudError(error) || attempt >= CLOUD_MAX_ATTEMPTS - 1) throw error;
    }
    // No worker request has been sent yet. A lost, unclaimed ticket expires
    // without token charges (the service only charges measured inference).
    // Use a fresh ID; never replay an uncertain POST or generate twice.
    await waitForCloudRetry(signal);
  }
}
