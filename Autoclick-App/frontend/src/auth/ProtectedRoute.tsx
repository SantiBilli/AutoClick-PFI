import { Navigate, Outlet } from 'react-router-dom';
import { useAuth } from '@/auth/AuthProvider';

export function ProtectedRoute() {
  const auth = useAuth();
  if (auth.status === 'loading') return <div role="status">Verificando sesión…</div>;
  if (auth.status === 'anonymous') return <Navigate to="/login" replace />;
  return <Outlet />;
}
