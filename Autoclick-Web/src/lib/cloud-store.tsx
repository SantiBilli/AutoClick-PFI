"use client";
import { trackActivity } from "./api-activity";
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { accessToken, authMessage, cloudApi } from './cloud-auth';
import type { User, Organization, Area, OrganizationMembership, AreaMembership, TokenUsage, DemoRole } from './domain';

export interface OrganizationSettingsPatch { name?: string; status?: 'active' | 'inactive'; startsAt?: string; endsAt?: string | null; monthlyTokenLimit?: number }
export interface BusinessRequest { id: string; companyName: string; contactName: string; contactEmail: string; estimatedUsers: number; useCase: string; notes: string; status: string; createdAt: string }
interface Snapshot { user: User; role: DemoRole; organization: Organization | null; organizations: Organization[]; users: User[]; areas: Area[]; organizationMemberships: OrganizationMembership[]; areaMemberships: AreaMembership[]; tokenUsage: TokenUsage[]; desktopVersion: string; downloadUrl: string; period: string; businessRequests: BusinessRequest[]; desktopUnlimited?: boolean }
const empty: Snapshot = { user: { id: '', name: '', email: '', status: 'inactive', avatarInitials: '' }, role: 'AREA_MEMBER', organization: null, organizations: [], users: [], areas: [], organizationMemberships: [], areaMemberships: [], tokenUsage: [], desktopVersion: '3.0', downloadUrl: '', period: '', businessRequests: [] };
export const today = new Date().toISOString().slice(0, 10);
export const isCurrentMembership = (m: OrganizationMembership) => m.status === 'active' && m.startsAt <= today && (!m.endsAt || m.endsAt >= today);
export const isOrganizationCurrent = (o: Organization) => o.status === 'active' && o.startsAt <= today && (!o.endsAt || o.endsAt >= today);
export const isValidTokenLimit = (n: unknown): n is number => typeof n === 'number' && Number.isSafeInteger(n) && n >= 0;
export const isWithinOrganizationTokenLimit = (used: number, limit: number) => used < limit;
export const canUpdateOrganizationSettings = (role: DemoRole) => role === 'AUTOCLICK_ADMIN';
export const canUpdateAreaTokenLimit = (role: DemoRole) => role === 'AUTOCLICK_ADMIN' || role === 'ORGANIZATION_OWNER';
export const isValidIsoDate = (v: unknown): v is string => typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v) && !Number.isNaN(Date.parse(v));
export const isValidDateRange = (a: unknown, b: unknown) => isValidIsoDate(a) && (b === null || (isValidIsoDate(b) && b >= a));
export const getOrganizationTokenTotals = (id: string | undefined, orgs: Organization[], areas: Area[], usage: TokenUsage[]) => {
  const limit = orgs.find(o => o.id === id)?.monthlyTokenLimit ?? 0;
  const assigned = areas.filter(a => a.organizationId === id).reduce((s, a) => s + a.tokenLimit, 0);
  return { limit, assigned, unassigned: Math.max(0, limit - assigned), usage: usage.filter(u => u.organizationId === id && u.period === today.slice(0, 7)).reduce((s, u) => s + u.tokensUsed, 0) };
};

function useCloudState() {
  const [snapshot, setSnapshot] = useState<Snapshot>(empty);
  const [dataState, setDataState] = useState<'loading' | 'ready' | 'error'>('loading');
  const [error, setError] = useState('');
  const [authenticated, setAuthenticated] = useState(false);
  const managementSelection = useRef('');
  const isPlatformAdmin = useRef(false);
  const generation = useRef(0);
  const refresh = useCallback(async () => {
    const version = ++generation.current;
    try {
      const token = await accessToken();
      if (!token) { if (version === generation.current) { setAuthenticated(false); setSnapshot(empty); setDataState('ready'); } return; }
      const result = await cloudApi<Snapshot>(`/v1/portal${isPlatformAdmin.current && managementSelection.current ? `?organizationId=${encodeURIComponent(managementSelection.current)}` : ''}`);
      if (version !== generation.current) return;
      if (result.role !== 'AUTOCLICK_ADMIN' && result.organizationMemberships.filter(m => m.userId === result.user.id).length > 1) throw new Error('La asignación de tu organización necesita una corrección administrativa. Contactá al administrador.');
      isPlatformAdmin.current = result.role === 'AUTOCLICK_ADMIN';
      if (!isPlatformAdmin.current) managementSelection.current = '';
      setAuthenticated(true); setSnapshot(result); setDataState('ready'); setError('');
    } catch (e) { if (version === generation.current) { setError(authMessage(e)); setDataState('error'); } }
  }, []);
  useEffect(() => { void refresh(); const listener = () => { managementSelection.current = ''; isPlatformAdmin.current = false; setDataState('loading'); void refresh(); }; window.addEventListener('autoclick-auth', listener); return () => { window.removeEventListener('autoclick-auth', listener); }; }, [refresh]);
  useEffect(() => {
    if (!authenticated) return;
    let lastRefresh = Date.now();
    const renew = () => { if (Date.now() - lastRefresh >= 45 * 60 * 1000) { lastRefresh = Date.now(); void refresh(); } };
    const timer = setInterval(renew, 45 * 60 * 1000);
    window.addEventListener('focus', renew);
    return () => { clearInterval(timer); window.removeEventListener('focus', renew); };
  }, [authenticated, refresh]);
  const mutate = async (path: string, method: string, body?: unknown) => {
    try { return await trackActivity(async () => { await cloudApi(path, method, body); await refresh(); return true; }); }
    catch (e) { setError(authMessage(e)); throw e; }
  };
  const organization = snapshot.organization;
  const totals = getOrganizationTokenTotals(organization?.id, snapshot.organizations, snapshot.areas, snapshot.tokenUsage);
  const visibleAreas = snapshot.areas.filter(a => a.organizationId === organization?.id);
  const visibleAreaMemberships = snapshot.areaMemberships.filter(m => visibleAreas.some(a => a.id === m.areaId) && m.status === 'active');
  const usage = snapshot.tokenUsage.filter(u => u.period === snapshot.period && u.organizationId === organization?.id);
  const ownUsage = usage.filter(u => u.userId === snapshot.user.id).reduce((s, u) => s + u.tokensUsed, 0);
  const desktopOrganizations = snapshot.organizations.filter(o => isOrganizationCurrent(o) && snapshot.organizationMemberships.some(m => m.userId === snapshot.user.id && m.organizationId === o.id && isCurrentMembership(m)));
  const hasDesktopAccess = snapshot.desktopUnlimited === true || desktopOrganizations.length === 1;
  return { ...snapshot, dataState, error, authenticated, refresh, clearError: () => setError(''),
    manageOrganization: async (id: string) => {
      if (snapshot.role !== 'AUTOCLICK_ADMIN') throw new Error('Tu organización está determinada por tu cuenta.');
      managementSelection.current = id; setDataState('loading'); await refresh();
    },
    setRole: () => { /* Roles are assigned by the server; kept only for old imports. */ },
    visibleAreas, visibleAreaMemberships, organizationUsage: totals.usage, organizationTokenLimit: totals.limit,
    organizationAssignedTokens: totals.assigned, organizationUnassignedTokens: totals.unassigned,
    currentAreaUsage: usage.reduce((s, u) => s + u.tokensUsed, 0), ownUsage, hasDesktopAccess,
    accessReason: hasDesktopAccess ? null : 'Tu cuenta necesita una organización activa. Contactá al administrador.',
    addOrganization: (name: string, ownerId: string) => mutate('/v1/organizations', 'POST', { name, ownerId }),
    updateOrganization: (id: string, status: 'active' | 'inactive') => mutate(`/v1/organizations/${id}`, 'PATCH', { status }),
    updateOrganizationSettings: async (id: string, patch: OrganizationSettingsPatch) => {
      try { await mutate(`/v1/organizations/${id}`, 'PATCH', patch); return { accepted: true, error: null }; }
      catch (e) { return { accepted: false, error: authMessage(e) }; }
    },
    updateOrganizationMembership: (id: string, patch: Partial<Pick<OrganizationMembership, 'status' | 'startsAt' | 'endsAt'>>) => mutate(`/v1/organization-memberships/${id}`, 'PATCH', patch),
    addOrganizationMember: (userId: string) => mutate(`/v1/organizations/${organization?.id}/members`, 'POST', userId.includes('@') ? { email: userId } : { userId }),
    addArea: (input: { name: string; organizationId?: string }) => mutate(`/v1/organizations/${input.organizationId ?? organization?.id}/areas`, 'POST', { name: input.name }),
    assignAreaMember: (userId: string, areaId: string, role: 'AREA_ADMIN' | 'AREA_MEMBER') => mutate(`/v1/areas/${areaId}/members`, 'POST', { userId, role }),
    removeAreaMember: (id: string) => { const member = snapshot.areaMemberships.find(m => m.id === id); return mutate(`/v1/areas/${member?.areaId}/members/${id}`, 'DELETE'); },
    updateAreaTokenLimit: (id: string, tokenLimit: number) => mutate(`/v1/areas/${id}`, 'PATCH', { tokenLimit }),
    saveProfile: (name: string) => mutate('/v1/me', 'PATCH', { name }),
    updateUser: (id: string, status: string) => mutate(`/v1/users/${id}`, 'PATCH', { status }),
    updateBusinessRequest: (id: string, status: string) => mutate(`/v1/business-requests/${id}`, 'PATCH', { status }),
  };
}
type CloudState = ReturnType<typeof useCloudState>;
const Context = createContext<CloudState | null>(null);
export function CloudProvider({ children }: { children: ReactNode }) {
  const value = useCloudState();
  return <Context.Provider value={value}>{children}</Context.Provider>;
}
export function useCloudStore() { const value = useContext(Context); if (!value) throw new Error('CloudProvider es requerido'); return value; }
export function CloudGate({ children }: { children: ReactNode }) {
  const state = useCloudStore(); const router = useRouter(); const path = usePathname();
  const portal = path.startsWith('/dashboard') || path.startsWith('/admin');
  useEffect(() => { if (portal && state.dataState === 'ready' && !state.authenticated) router.replace('/login'); }, [portal, state.dataState, state.authenticated, router]);
  if (!portal) return <>{children}</>;
  if (state.dataState === 'loading') return <div className="app-boot" role="status">Cargando tu cuenta…</div>;
  if (state.dataState === 'error') return <div className="app-boot"><p role="alert">{state.error}</p><button onClick={() => void state.refresh()}>Volver a intentar</button></div>;
  if (!state.authenticated) return null;
  return <>{state.error && <div className="form-error" role="alert">{state.error}<button type="button" onClick={state.clearError}>Cerrar</button></div>}{children}</>;
}
