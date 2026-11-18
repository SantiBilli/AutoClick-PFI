"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { Avatar } from "../../../../../components/ui/Avatar";
import { Button } from "../../../../../components/ui/Button";
import { PageHeader } from "../../../../../components/ui/PageHeader";
import { Select } from "../../../../../components/ui/Select";
import { getOrganizationTokenTotals, useDemoStore } from "../../../../../lib/demo-store";
import type { OrganizationStatus } from "../../../../../lib/domain";

export default function OrganizationAdminPage() {
  const { organizationId } = useParams<{ organizationId: string }>();
  const { organizations, users, organizationMemberships, areas, tokenUsage, organizationUsage, organizationAssignedTokens, organizationUnassignedTokens, updateOrganizationSettings, manageOrganization, updateOrganizationMembership } = useDemoStore();
  const router = useRouter();
  const organization = organizations.find((item) => item.id === organizationId);
  const [status, setStatus] = useState<OrganizationStatus>("active");
  const [startsAt, setStartsAt] = useState("");
  const [endsAt, setEndsAt] = useState("");
  const [monthlyTokenLimit, setMonthlyTokenLimit] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!organization) return;
    setStatus(organization.status);
    setStartsAt(organization.startsAt);
    setEndsAt(organization.endsAt ?? "");
    setMonthlyTokenLimit(String(organization.monthlyTokenLimit));
    setError(null);
  }, [organization]);

  if (!organization) return <p>Organización no encontrada.</p>;

  const members = organizationMemberships.filter((item) => item.organizationId === organization.id);
  const selectedTotals = getOrganizationTokenTotals(organization.id, organizations, areas, tokenUsage);
  const totals = organizationUsage || selectedTotals.assigned || selectedTotals.unassigned ? selectedTotals : { usage: organizationUsage, assigned: organizationAssignedTokens, unassigned: organizationUnassignedTokens };

  const saveSettings = async () => {
    const parsedLimit = Number(monthlyTokenLimit);
    if (!/^[0-9]+$/.test(monthlyTokenLimit) || !Number.isSafeInteger(parsedLimit) || parsedLimit < 0) {
      setError("El límite mensual debe ser un número entero no negativo.");
      return;
    }
    if (!startsAt || (endsAt && endsAt < startsAt)) {
      setError("La fecha de fin no puede ser anterior a la fecha de inicio.");
      return;
    }
    const result = await updateOrganizationSettings(organization.id, { status, startsAt, endsAt: endsAt || null, monthlyTokenLimit: parsedLimit });
    setError(result.error);
  };

  return (
    <div className="dash-stack">
      <PageHeader
        eyebrow="Administración AutoClick"
        title={organization.name}
        description="Contrato, límites de tokens y miembros de la organización."
        back={{ href: "/admin/organizations", label: "Volver a organizaciones" }}
        status={<span className={`ui-badge ${organization.status === "active" ? "ui-badge--green" : "ui-badge--amber"}`}>{organization.status === "active" ? "Activa" : "Inactiva"}</span>}
      />
      <section className="ui-card portal-card">
        <div className="portal-card__heading" style={{ alignItems: "center" }}>
          <div>
            <p className="eyebrow">Personas</p>
            <h2>Miembros de la organización</h2>
          </div>
          <Button onClick={async () => { await manageOrganization(organization.id); router.push('/dashboard/areas'); }}>
            Gestionar áreas y miembros
          </Button>
        </div>
        <div className="table-wrap"><table className="portal-table"><thead><tr><th>Usuario</th><th>Rol</th><th>Relación</th><th>Estado</th></tr></thead><tbody>{members.map((membership) => { const user = users.find((item) => item.id === membership.userId); return <tr key={membership.id}><td><span className="table-primary"><Avatar user={user} className="avatar" />{user?.name}</span></td><td>{membership.role === "ORGANIZATION_OWNER" ? "Dueño" : "Miembro"}</td><td>{membership.role === "ORGANIZATION_OWNER" ? "Propietario" : "Usuario"}</td><td><Select aria-label={`Estado de ${user?.name}`} value={membership.status} onChange={e => { void updateOrganizationMembership(membership.id, { status: e.target.value as 'active' | 'inactive' | 'expired' }).catch(() => {}); }}><option value="active">Activo</option><option value="inactive">Inactivo</option><option value="expired">Vencido</option></Select></td></tr>; })}</tbody></table></div>
      </section>
      <section className="ui-card portal-card">
        <div className="portal-card__heading"><div><p className="eyebrow">Límites y acceso</p><h2>Configuración de la organización</h2></div></div>
        <div className="admin-stats"><div className="portal-stat"><span>Tokens utilizados</span><strong>{totals.usage.toLocaleString("es-AR")}</strong></div><div className="portal-stat"><span>Tokens asignados</span><strong>{totals.assigned.toLocaleString("es-AR")}</strong></div><div className="portal-stat"><span>Tokens sin asignar</span><strong>{totals.unassigned.toLocaleString("es-AR")}</strong></div></div>
        <div className="form-grid" style={{ marginTop: "1.5rem" }}>
          <label className="form-field">Estado<Select value={status} onChange={(event) => setStatus(event.target.value as OrganizationStatus)}><option value="active">Activa</option><option value="inactive">Inactiva</option></Select></label>
          <label className="form-field">Inicio<input type="date" value={startsAt} onChange={(event) => setStartsAt(event.target.value)} /></label>
          <label className="form-field">Fin<input type="date" value={endsAt} onChange={(event) => setEndsAt(event.target.value)} /></label>
          <label className="form-field">Límite mensual de tokens<input type="number" min="0" step="1" value={monthlyTokenLimit} onChange={(event) => setMonthlyTokenLimit(event.target.value)} /></label>
        </div>
        {error && <p className="form-error" role="alert">{error}</p>}
        <Button onClick={saveSettings} style={{ marginTop: "1rem" }}>Guardar configuración</Button>
      </section>
    </div>
  );
}
