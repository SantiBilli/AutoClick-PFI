"use client";
import { trackActivity } from './api-activity';
import { Amplify } from 'aws-amplify';
import { signIn, signOut, signUp, confirmSignUp, resendSignUpCode, resetPassword, confirmResetPassword, confirmSignIn, fetchAuthSession } from 'aws-amplify/auth';

type PublicCloudConfig = { userPoolId: string; userPoolClientId: string; apiUrl: string };
let configuration: Promise<PublicCloudConfig> | undefined;
export function configureCloud(): Promise<PublicCloudConfig> {
  if (!configuration) {
    configuration = (async () => {
      const response = await fetch('/api/public-config', { cache: 'no-store', signal: AbortSignal.timeout(15000) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.message || 'No se pudo cargar la configuración de AutoClick.');
      if (!data.userPoolId || !data.userPoolClientId || !data.apiUrl) throw new Error('La configuración de AutoClick está incompleta.');
      Amplify.configure({ Auth: { Cognito: { userPoolId: data.userPoolId, userPoolClientId: data.userPoolClientId } } });
      return data as PublicCloudConfig;
    })().catch(error => {
      configuration = undefined; // A transient failure must not poison later login attempts.
      throw error;
    });
  }
  return configuration;
}
export function authMessage(error: unknown): string {
  const name = error instanceof Error ? error.name : '';
  const messages: Record<string, string> = {
    NotAuthorizedException: 'El correo, la contraseña o el código son incorrectos.',
    UserNotFoundException: 'No se pudo completar la operación con esos datos.',
    UserNotConfirmedException: 'Confirmá tu correo antes de iniciar sesión.',
    UsernameExistsException: 'Ya existe una cuenta con ese correo. Probá iniciar sesión o recuperar la contraseña.',
    CodeMismatchException: 'El código de verificación es incorrecto.',
    ExpiredCodeException: 'El código venció. Solicitá uno nuevo.',
    InvalidPasswordException: 'Usá al menos 10 caracteres, mayúsculas, minúsculas y números.',
    LimitExceededException: 'Se alcanzó el límite de intentos. Esperá y volvé a intentar.',
    UserAlreadyAuthenticatedException: 'Hay una sesión abierta. Volvé a intentar para ingresar con esta cuenta.',
  };
  return messages[name] ?? (error instanceof Error ? error.message : 'No se pudo completar la operación.');
}
async function loginRequest(email: string, password: string) {
  await configureCloud();
  const credentials = { username: email.trim().toLowerCase(), password };
  let result;
  try { result = await signIn(credentials); }
  catch (error) {
    if (!(error instanceof Error) || error.name !== 'UserAlreadyAuthenticatedException') throw error;
    // An explicit login must authenticate the submitted account, even when an
    // earlier login succeeded in Cognito but loading the portal failed.
    await signOut();
    window.dispatchEvent(new Event('autoclick-auth'));
    result = await signIn(credentials);
  }
  if (result.isSignedIn) { window.dispatchEvent(new Event('autoclick-auth')); return 'authenticated'; }
  if (result.nextStep.signInStep === 'CONFIRM_SIGN_IN_WITH_NEW_PASSWORD_REQUIRED') return 'new-password';
  throw new Error('Completá la confirmación de tu cuenta para continuar.');
}
async function finishNewPasswordRequest(password: string) {
  const result = await confirmSignIn({ challengeResponse: password });
  if (!result.isSignedIn) throw new Error('No se pudo completar el cambio de contraseña.');
  window.dispatchEvent(new Event('autoclick-auth'));
}
async function registerRequest(email: string, password: string, name: string) {
  await configureCloud();
  await signUp({ username: email.trim().toLowerCase(), password, options: { userAttributes: { email: email.trim().toLowerCase(), name: name.trim() } } });
  sessionStorage.setItem('autoclick-confirm-email', email.trim().toLowerCase());
}
async function verifyRequest(email: string, code: string) { await configureCloud(); await confirmSignUp({ username: email.trim().toLowerCase(), confirmationCode: code.trim() }); }
async function resendRequest(email: string) { await configureCloud(); await resendSignUpCode({ username: email.trim().toLowerCase() }); }
async function recoverRequest(email: string) { await configureCloud(); await resetPassword({ username: email.trim().toLowerCase() }); sessionStorage.setItem('autoclick-confirm-email', email.trim().toLowerCase()); }
async function resetRequest(email: string, code: string, password: string) { await configureCloud(); await confirmResetPassword({ username: email.trim().toLowerCase(), confirmationCode: code.trim(), newPassword: password }); }
async function logoutRequest() { await configureCloud(); await signOut(); window.dispatchEvent(new Event('autoclick-auth')); sessionStorage.setItem('autoclick-logged-out', '1'); window.location.assign('/login'); }
export async function accessToken() { await configureCloud(); return (await fetchAuthSession()).tokens?.accessToken.toString(); }

async function cloudApiRequest<T>(path: string, method = 'GET', body?: unknown, publicRequest = false): Promise<T> {
  const { apiUrl: base } = await configureCloud();
  const token = publicRequest ? undefined : await accessToken();
  if (!publicRequest && !token) throw new Error('Iniciá sesión para continuar.');
  let response: Response;
  for (let attempt = 0; ; attempt++) {
    response = await fetch(`${base.replace(/\/$/, '')}${path}`, { method, cache: 'no-store',
      headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(35000),
    });
    // Only safe reads are retried. Never repeat a mutation after an ambiguous response.
    if (method !== 'GET' || ![503, 504].includes(response.status) || attempt >= 2) break;
    await new Promise(resolve => setTimeout(resolve, 1500));
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.message ?? 'No se pudo completar la operación. Volvé a intentar.');
  return data as T;
}

export function login(email: string, password: string) { return trackActivity(() => loginRequest(email, password), 'Sesión iniciada correctamente.'); }

export function finishNewPassword(password: string) { return trackActivity(() => finishNewPasswordRequest(password), 'Contraseña actualizada.'); }

export function register(email: string, password: string, name: string) { return trackActivity(() => registerRequest(email, password, name), 'Cuenta creada. Revisá tu correo para confirmarla.'); }

export function verify(email: string, code: string) { return trackActivity(() => verifyRequest(email, code), 'Correo confirmado.'); }

export function resend(email: string) { return trackActivity(() => resendRequest(email), 'Código reenviado.'); }

export function recover(email: string) { return trackActivity(() => recoverRequest(email), 'Solicitud enviada. Revisá tu correo.'); }

export function reset(email: string, code: string, password: string) { return trackActivity(() => resetRequest(email, code, password), 'Contraseña actualizada.'); }

export function logout() { return trackActivity(() => logoutRequest(), 'Sesión cerrada.'); }

export function deleteAccount(confirmationEmail: string) {
  return trackActivity(async () => {
    const result = await cloudApiRequest<{ status: 'deleted' | 'deleting' }>('/v1/me', 'DELETE', { confirmationEmail });
    // The durable deletion request already blocks access, including old sessions.
    try { await signOut(); }
    catch { /* The backend denies all further account access even if revocation is unavailable. */ }
    sessionStorage.setItem('autoclick-account-deletion', result.status);
    window.location.replace('/login');
  });
}

export function cloudApi<T>(path: string, method = 'GET', body?: unknown, publicRequest = false, notify = true): Promise<T> {
  const success = !notify ? '' : method !== 'GET' ? 'Cambio realizado correctamente.' : path === '/v1/desktop/download' ? 'Descarga preparada correctamente.' : '';
  return trackActivity(() => cloudApiRequest<T>(path, method, body, publicRequest), success);
}
