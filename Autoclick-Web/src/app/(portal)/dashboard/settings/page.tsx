"use client";
import { useState } from "react";
import { CalendarRange, Coins, Lock, Mail, ShieldCheck } from "lucide-react";
import { Button } from "../../../../components/ui/Button";
import { Panel } from "../../../../components/ui/Panel";
import { PageIntro } from "../../../../components/ui/PageHeader";
import { useDemoStore } from "../../../../lib/demo-store";
import { roleLabels } from "../../../../lib/role-labels";
import { formatDate, formatNumber } from "../../../../lib/formatters";

const PLAN_LABELS = { PROFESIONAL: "Profesional", EMPRESARIAL: "Empresarial" } as const;

export default function SettingsPage() {
  const { user, organization, role, organizationUsage, organizationTokenLimit, saveProfile, updateOrganizationSettings } = useDemoStore();
  const [name, setName] = useState(user.name);
  const [orgName, setOrgName] = useState(organization?.name ?? "");
  const [nameError, setNameError] = useState("");
  const [orgError, setOrgError] = useState("");

  const savePersonal = async (event: React.FormEvent) => {
    event.preventDefault();
    if (name.trim().length < 3) {
      setNameError("Ingresá un nombre de al menos 3 caracteres.");
      return;
    }
    setNameError("");
    try { await saveProfile(name); } catch (e) { setNameError(e instanceof Error ? e.message : "No se pudo guardar."); }
  };

  const saveOrganization = async (event: React.FormEvent) => {
    event.preventDefault();
    if (orgName.trim().length < 2) {
      setOrgError("El nombre de la organización no puede quedar vacío.");
      return;
    }
    setOrgError("");
    if (!organization) return; const result = await updateOrganizationSettings(organization.id, { name: orgName }); if (!result.accepted) setOrgError(result.error ?? "No se pudo guardar.");
  };

  const usagePercent = organizationTokenLimit > 0 ? Math.min(100, Math.round((organizationUsage / organizationTokenLimit) * 100)) : 0;

  return (
    <div className="dash-stack">
      <PageIntro description="Administrá la información visible de tu cuenta y de tu organización." />

      <div className="settings-grid">
        <Panel className="portal-card" hover spotlight selfReveal>
          <div className="portal-card__heading">
            <div>
              <p className="dash-eyebrow">Cuenta</p>
              <h2>Datos personales</h2>
            </div>
          </div>
          <form className="settings-form" onSubmit={savePersonal} noValidate>
            <label className="form-field">
              Nombre
              <input value={name} onChange={(event) => setName(event.target.value)} aria-invalid={!!nameError} minLength={3} required />
            </label>
            {nameError && <p className="form-error" role="alert">{nameError}</p>}
            <div className="form-field form-field--readonly">
              <span>Email</span>
              <span className="form-field__readonly-value"><Mail size={13} aria-hidden="true" /> {user.email}</span>
            </div>
            <div className="form-field form-field--readonly">
              <span>Rol actual</span>
              <span className="form-field__readonly-value"><Lock size={13} aria-hidden="true" /> {roleLabels[role]}</span>
            </div>
            <Button type="submit">Guardar cambios</Button>
          </form>
        </Panel>

        {(role === "ORGANIZATION_OWNER" || role === "AUTOCLICK_ADMIN") && <Panel className="portal-card" hover spotlight selfReveal>
          <div className="portal-card__heading">
            <div>
              <p className="dash-eyebrow">Organización</p>
              <h2>Información general</h2>
            </div>
          </div>
          <form className="settings-form" onSubmit={saveOrganization} noValidate>
            <label className="form-field">
              Nombre de la organización
              <input value={orgName} onChange={(event) => setOrgName(event.target.value)} aria-invalid={!!orgError} required />
            </label>
            {orgError && <p className="form-error" role="alert">{orgError}</p>}
            <div className="form-field form-field--readonly">
              <span>Plan</span>
              <span className="form-field__readonly-value"><ShieldCheck size={13} aria-hidden="true" /> {organization ? PLAN_LABELS[organization.plan] : "—"}</span>
            </div>
            <div className="form-field form-field--readonly">
              <span>Vigencia</span>
              <span className="form-field__readonly-value">
                <CalendarRange size={13} aria-hidden="true" />
                {organization ? `Desde ${formatDate(organization.startsAt)}${organization.endsAt ? ` hasta ${formatDate(organization.endsAt)}` : " · sin vencimiento"}` : "—"}
              </span>
            </div>
            <Button type="submit">Guardar cambios</Button>
          </form>
        </Panel>}

        <Panel tone="ink" className="settings-plan" selfReveal>
          <div>
            <p className="dash-eyebrow">Plan vigente</p>
            <h2>{organization ? PLAN_LABELS[organization.plan] : "Sin organización"}</h2>
            <p>
              {organizationTokenLimit > 0
                ? `Usaste ${formatNumber(organizationUsage)} de ${formatNumber(organizationTokenLimit)} tokens del período en curso.`
                : "Todavía no hay un límite mensual configurado."}
            </p>
            <div className="settings-plan__meter" role="img" aria-label={`${usagePercent}% del límite mensual consumido`}>
              <span style={{ width: `${usagePercent}%` }} />
            </div>
            <div className="settings-plan__foot">
              <span><Coins size={14} aria-hidden="true" /> {usagePercent}% consumido</span>
              <span>Los límites los administra AutoClick</span>
            </div>
          </div>
        </Panel>
      </div>

    </div>
  );
}
