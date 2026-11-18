import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import {
  completeNewPassword,
  loadCurrentUser,
  login,
  logout,
  type AuthUser,
  type LoginOutcome,
} from '@/auth/auth';

type AuthState =
  | { status: 'loading'; user: null }
  | { status: 'anonymous'; user: null }
  | { status: 'authenticated'; user: AuthUser };

type AuthContextValue = AuthState & {
  signIn(email: string, password: string, remember: boolean): Promise<LoginOutcome>;
  confirmNewPassword(password: string): Promise<void>;
  signOut(): Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ status: 'loading', user: null });

  useEffect(() => {
    let active = true;
    loadCurrentUser().then((user) => {
      if (active) {
        setState(user ? { status: 'authenticated', user } : { status: 'anonymous', user: null });
      }
    });
    return () => {
      active = false;
    };
  }, []);

  const value: AuthContextValue = {
    ...state,
    async signIn(email, password, remember) {
      const outcome = await login(email, password, remember);
      if (outcome === 'new-password-required') return outcome;
      const user = await loadCurrentUser();
      if (!user) throw new Error('Cognito no devolvió una sesión autenticada');
      setState({ status: 'authenticated', user });
      return 'authenticated';
    },
    async confirmNewPassword(password) {
      await completeNewPassword(password);
      const user = await loadCurrentUser();
      if (!user) throw new Error('Cognito no devolvió una sesión autenticada');
      setState({ status: 'authenticated', user });
    },
    async signOut() {
      try {
        await logout();
      } finally {
        setState({ status: 'anonymous', user: null });
      }
    },
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error('useAuth debe utilizarse dentro de AuthProvider');
  return value;
}
