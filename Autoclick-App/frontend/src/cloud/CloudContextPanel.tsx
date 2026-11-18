import { useEffect, useState } from 'react';
import { Panel } from '@/components/Panel';
import { requireDesktopSession, cloudEnabled, type CloudProfile } from './client';

export function CloudContextPanel() {
  const [profile, setProfile] = useState<CloudProfile | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    if (!cloudEnabled) return;
    const controller = new AbortController();
    requireDesktopSession(controller.signal).then(data => {
      setProfile(data);
    }).catch(e => { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : 'No se pudo cargar tu organización.'); });
    return () => controller.abort();
  }, []);
  if (!cloudEnabled) return null;
  const areas = profile?.areas.filter(a => a.status === 'active' && a.organizationId === profile.organization?.id) ?? [];
  const used = profile?.tokenUsage.filter(r => r.userId === profile.user.id && r.organizationId === profile.organization?.id && r.period === profile.period).reduce((n, r) => n + r.tokensUsed, 0) ?? 0;
  return <Panel className="mt-5 p-6">
    <h2 className="m-0 text-lg font-extrabold">Organización y consumo de IA</h2>
    <p className="my-3 text-[13px] text-text-muted">{profile?.unlimited ? 'Tu cuenta tiene acceso de administrador de AutoClick.' : 'Tu cuenta está vinculada a una única organización.'}</p>
    {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
    {!profile && !error && <p>Cargando permisos…</p>}
    {profile?.unlimited && <p className="text-sm">IA sin límite de cuota. No necesitás una organización ni un área para usar Desktop.</p>}
    {profile?.organization && !profile.unlimited && <>
      <div className="mb-3 text-sm">Organización
        <p className="mt-1 rounded-control border border-border bg-bg p-3">{profile.organization.name}</p>
        <p className="my-3 text-text-muted">Límite mensual de la organización: {profile.organization.monthlyTokenLimit.toLocaleString('es-AR')} tokens.</p>
      </div>
      {areas.length === 0 && <p>Un administrador debe asignarte un área activa para usar IA.</p>}
      <p className="mt-3 text-sm text-text-muted">Este mes consumiste {used.toLocaleString('es-AR')} tokens.</p>
    </>}
  </Panel>;
}
