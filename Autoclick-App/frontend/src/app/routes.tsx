import { Navigate, createHashRouter } from 'react-router-dom';
import { lazy, Suspense } from 'react';
import { useAuth } from '@/auth/AuthProvider';
import { ProtectedRoute } from '@/auth/ProtectedRoute';
import { RouteLoading } from '@/components/RouteLoading';
import { LoginPage } from '@/pages/LoginPage';

const AppLayout = lazy(() => import('@/layout/AppLayout').then((module) => ({ default: module.AppLayout })));
const AutoClickAiPage = lazy(() => import('@/pages/AutoClickAiPage').then((module) => ({ default: module.AutoClickAiPage })));
const EditorPage = lazy(() => import('@/features/editor/EditorPage').then((module) => ({ default: module.EditorPage })));
const ExplorerPage = lazy(() => import('@/pages/ExplorerPage').then((module) => ({ default: module.ExplorerPage })));
const SettingsPage = lazy(() => import('@/pages/SettingsPage').then((module) => ({ default: module.SettingsPage })));

function LoginRoute() {
  const auth = useAuth();
  if (auth.status === 'loading') return <RouteLoading label="Verificando sesión…" />;
  if (auth.status === 'authenticated') return <Navigate to="/explorer" replace />;
  return <LoginPage />;
}

export const router = createHashRouter([
  { path: '/login', element: <LoginRoute /> },
  {
    element: <ProtectedRoute />,
    children: [
      {
        element: <Suspense fallback={<RouteLoading label="Cargando AutoClick…" />}><AppLayout /></Suspense>,
        children: [
          { path: '/explorer', element: <Suspense fallback={<RouteLoading label="Cargando Explorador…" />}><ExplorerPage /></Suspense> },
          { path: '/autoclick-ai', element: <Suspense fallback={<RouteLoading label="Cargando AutoClick AI…" />}><AutoClickAiPage /></Suspense> },
          { path: '/settings', element: <Suspense fallback={<RouteLoading label="Cargando Configuración…" />}><SettingsPage /></Suspense> },
        ],
      },
      { path: '/bots/:entryId', element: <Suspense fallback={<RouteLoading label="Cargando editor…" />}><EditorPage /></Suspense> },
    ],
  },
  { path: '*', element: <Navigate to="/explorer" replace /> },
]);
