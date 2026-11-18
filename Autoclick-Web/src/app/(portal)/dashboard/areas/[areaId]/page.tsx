"use client";
import { useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { Coins, Users } from "lucide-react";
import { Button } from "../../../../../components/ui/Button";
import { EmptyState } from "../../../../../components/ui/EmptyState";
import { PageHeader } from "../../../../../components/ui/PageHeader";
import { Panel } from "../../../../../components/ui/Panel";
import { RobotHelper } from "../../../../../components/ui/RobotHelper";
import { Select } from "../../../../../components/ui/Select";
import { UsageProgress } from "../../../../../components/portal/UsageProgress";
import { MembersTable } from "../../../../../components/portal/MembersTable";
import { today, useDemoStore } from "../../../../../lib/demo-store";
import { formatNumber } from "../../../../../lib/formatters";

export default function AreaDetailPage() {
  const { areaId } = useParams<{ areaId: string }>();
  const { user, organization, visibleAreas, visibleAreaMemberships, role, organizationTokenLimit, organizationAssignedTokens, organizationUnassignedTokens, updateAreaTokenLimit, tokenUsage } = useDemoStore();
  const area = visibleAreas.find((item) => item.id === areaId);
  const [draftLimit, setDraftLimit] = useState<string | null>(null);
  const [custom, setCustom] = useState(false);
  const [saveError, setSaveError] = useState("");

  if (!area) {
    return (
      <EmptyState
        title="Área no encontrada"
        description="No tenés acceso a esta área."
        icon={<RobotHelper pose="explaining" size="sm" float={false} />}
        action={<Link className="ui-button ui-button--primary ui-button--md" href="/dashboard/areas">Volver a áreas</Link>}
      />
    );
  }

  const canEdit = role === "ORGANIZATION_OWNER" || role === "AUTOCLICK_ADMIN";
  const canViewOrganizationAllocation = canEdit;
  const selectedLimit = draftLimit ?? String(area.tokenLimit);
  const customMode = custom || !["0", "5000", "10000", "12000", "14000", "24000", "50000"].includes(selectedLimit);
  const availableForArea = organizationUnassignedTokens + area.tokenLimit;

  const saveLimit = async () => {
    const nextLimit = Number(selectedLimit);
    if (!/^[0-9]+$/.test(selectedLimit) || !Number.isSafeInteger(nextLimit) || nextLimit < 0) {
      setDraftLimit(null);
      setSaveError("El límite del área debe ser un número entero no negativo.");
      return;
    }
    if (nextLimit > availableForArea) {
      setDraftLimit(null);
      setSaveError(`El límite supera el saldo disponible para esta área: ${availableForArea.toLocaleString("es-AR")} tokens.`);
      return;
    }
    if (!(await updateAreaTokenLimit(area.id, nextLimit).catch(() => false))) {
      setDraftLimit(null);
      setSaveError("No se pudo guardar el límite del área.");
      return;
    }
    setDraftLimit(null);
    setSaveError("");
  };

  const visibleUsage = tokenUsage.filter((item) => item.organizationId === organization?.id && item.areaId === area.id && item.period === today.slice(0, 7) && (role !== "AREA_MEMBER" || item.userId === user.id));
  const usage = visibleUsage.reduce((sum, item) => sum + item.tokensUsed, 0);
  const usageLabel = role === "AREA_MEMBER" ? "Tu uso del período" : "Uso total del período";
  const areaPercent = area.tokenLimit > 0 ? Math.min(100, Math.round((usage / area.tokenLimit) * 100)) : 0;
  const memberCount = visibleAreaMemberships.filter((item) => item.areaId === area.id).length;

  return (
    <div className="dash-stack">
      <PageHeader
        eyebrow="Detalle de área"
        title={area.name}
        description={`${usageLabel}: ${usage.toLocaleString("es-AR")} tokens.`}
        status={<span className={`ui-badge ${area.status === "active" ? "ui-badge--green" : "ui-badge--amber"}`}>{area.status === "active" ? "Activa" : "Inactiva"}</span>}
        back={{ href: "/dashboard/areas", label: "Volver a áreas" }}
      />

      <div className="area-detail-grid">
        <Panel className="portal-card area-settings" hover spotlight selfReveal>
          <div className="portal-card__heading">
            <div>
              <p className="dash-eyebrow">Límite del área</p>
              <h2>Tokens disponibles</h2>
              <p className="portal-muted">Definí el máximo de tokens que este equipo puede consumir por período.</p>
            </div>
          </div>
          {canViewOrganizationAllocation && (
            <UsageProgress
              used={organizationAssignedTokens}
              limit={organizationTokenLimit}
              segments={[
                { label: "Límite mensual de la organización", value: organizationTokenLimit },
                { label: "Tokens asignados", value: organizationAssignedTokens },
                { label: "Saldo sin asignar", value: organizationUnassignedTokens },
              ]}
            />
          )}
          <div className="area-limit-control">
            <label className="form-field">
              Tokens por período
              <Select
                value={customMode ? "custom" : selectedLimit}
                disabled={!canEdit}
                onChange={(event) => { setCustom(event.target.value === "custom"); if (event.target.value !== "custom") setDraftLimit(event.target.value); setSaveError(""); }}
                aria-label="Límite de tokens"
              >
                <option value="0">0</option>
                <option value="5000">5.000</option>
                <option value="10000">10.000</option>
                <option value="12000">12.000</option>
                <option value="14000">14.000</option>
                <option value="24000">24.000</option>
                <option value="50000">50.000</option><option value="custom">Personalizado</option>
              </Select>
            </label>
            {customMode && <label className="form-field">Cantidad personalizada<input aria-label="Cantidad personalizada de tokens" type="number" min="0" max={availableForArea} step="1" disabled={!canEdit} value={selectedLimit} onChange={event => { setDraftLimit(event.target.value); setSaveError(""); }} /></label>}
            {canEdit ? (
              <Button type="button" onClick={saveLimit}>Guardar límite</Button>
            ) : (
              <p className="portal-muted">Solo el dueño puede editar límites. Tu rol puede consultar este límite, pero no modificarlo.</p>
            )}
            {saveError && <p className="form-error" role="alert">{saveError}</p>}
          </div>
        </Panel>

        <Panel tone="ink" className="area-usage-card" selfReveal>
          <div>
            <p className="dash-eyebrow">{usageLabel}</p>
            <strong className="area-usage-card__value">{formatNumber(usage)}</strong>
            <p>{area.tokenLimit > 0 ? `${areaPercent}% del límite asignado al área (${formatNumber(area.tokenLimit)} tokens).` : "El área todavía no tiene un límite asignado."}</p>
            <div className="settings-plan__meter" role="img" aria-label={`${areaPercent}% del límite del área`}>
              <span style={{ width: `${areaPercent}%` }} />
            </div>
            <div className="alloc-card__legend">
              <div><Users size={13} aria-hidden="true" /> Miembros <b>{memberCount}</b></div>
              <div><Coins size={13} aria-hidden="true" /> Límite del área <b>{formatNumber(area.tokenLimit)}</b></div>
            </div>
          </div>
        </Panel>
      </div>

      <MembersTable areaId={area.id} />
    </div>
  );
}
