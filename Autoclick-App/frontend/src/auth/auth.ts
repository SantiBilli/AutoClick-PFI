import { Amplify } from 'aws-amplify';
import { confirmSignIn, getCurrentUser, signIn, signOut } from 'aws-amplify/auth';
import { cognitoUserPoolsTokenProvider } from 'aws-amplify/auth/cognito';
import {
  defaultStorage,
  sessionStorage as browserSessionStorage,
  type KeyValueStorageInterface,
} from 'aws-amplify/utils';
import { z } from 'zod';
import { DesktopAccessError, requireDesktopSession } from '@/cloud/client';

const configSchema = z.object({
  region: z.string().min(1),
  userPoolId: z.string().min(1),
  userPoolClientId: z.string().min(1),
});

export type AuthUser = { username: string; userId: string };
export type LoginOutcome = 'authenticated' | 'new-password-required';

const cognitoStoragePrefix = 'CognitoIdentityServiceProvider';
const userTokenKeys = [
  'accessToken',
  'idToken',
  'clockDrift',
  'refreshToken',
  'signInDetails',
  'oauthMetadata',
] as const;

async function clearStoredSession(
  storage: KeyValueStorageInterface,
  userPoolClientId: string,
): Promise<void> {
  const lastUserKey = `${cognitoStoragePrefix}.${userPoolClientId}.LastAuthUser`;
  const username = await storage.getItem(lastUserKey);
  if (!username) {
    await storage.removeItem(lastUserKey);
    return;
  }

  const userPrefix = `${cognitoStoragePrefix}.${userPoolClientId}.${username}`;
  await Promise.all([
    ...userTokenKeys.map((key) => storage.removeItem(`${userPrefix}.${key}`)),
    storage.removeItem(lastUserKey),
  ]);
}

export function configureAuth(): void {
  cognitoUserPoolsTokenProvider.setKeyValueStorage(defaultStorage);

  const config = configSchema.parse({
    region: import.meta.env.VITE_AWS_REGION,
    userPoolId: import.meta.env.VITE_COGNITO_USER_POOL_ID,
    userPoolClientId: import.meta.env.VITE_COGNITO_CLIENT_ID,
  });

  Amplify.configure({
    Auth: {
      Cognito: {
        userPoolId: config.userPoolId,
        userPoolClientId: config.userPoolClientId,
      },
    },
  });
}

async function validateDesktopAccess(): Promise<void> {
  try {
    await requireDesktopSession();
  } catch (error) {
    if (error instanceof DesktopAccessError && error.retryable) throw error;
    // Remove this Desktop client's session; the web session stays independent.
    try { await logout(); } catch { /* Keep the original access error. */ }
    throw error;
  }
}

export async function loadCurrentUser(): Promise<AuthUser | null> {
  try {
    const user = await getCurrentUser();
    await validateDesktopAccess();
    return { username: user.username, userId: user.userId };
  } catch {
    return null;
  }
}

export async function login(
  email: string,
  password: string,
  remember: boolean,
): Promise<LoginOutcome> {
  const storage = remember ? defaultStorage : browserSessionStorage;
  const previousStorage = remember ? browserSessionStorage : defaultStorage;

  const userPoolClientId = configSchema.shape.userPoolClientId.parse(
    import.meta.env.VITE_COGNITO_CLIENT_ID,
  );
  await clearStoredSession(previousStorage, userPoolClientId);
  cognitoUserPoolsTokenProvider.setKeyValueStorage(storage);

  const credentials = { username: email.trim().toLowerCase(), password };
  let result;
  try { result = await signIn(credentials); }
  catch (error) {
    if (!(error instanceof Error) || error.name !== 'UserAlreadyAuthenticatedException') throw error;
    await logout();
    cognitoUserPoolsTokenProvider.setKeyValueStorage(storage);
    result = await signIn(credentials);
  }
  if (result.isSignedIn) {
    await validateDesktopAccess();
    return 'authenticated';
  }

  if (result.nextStep.signInStep === 'CONFIRM_SIGN_IN_WITH_NEW_PASSWORD_REQUIRED') {
    return 'new-password-required';
  }

  throw new Error(`Inicio de sesión incompleto: ${result.nextStep.signInStep}`);
}

export async function completeNewPassword(password: string): Promise<void> {
  const result = await confirmSignIn({ challengeResponse: password });
  if (!result.isSignedIn) {
    throw new Error(`Inicio de sesión incompleto: ${result.nextStep.signInStep}`);
  }
  await validateDesktopAccess();
}

export async function logout(): Promise<void> {
  try {
    await signOut();
  } finally {
    const userPoolClientId = configSchema.shape.userPoolClientId.parse(
      import.meta.env.VITE_COGNITO_CLIENT_ID,
    );
    await Promise.all([
      clearStoredSession(defaultStorage, userPoolClientId),
      clearStoredSession(browserSessionStorage, userPoolClientId),
    ]);
  }
}
