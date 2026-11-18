"use client";
import Link from "next/link";
import { Building2 } from "lucide-react";
import { PageIntro } from "../../../components/ui/PageHeader";
import { Panel } from "../../../components/ui/Panel";
import { useDemoStore } from "../../../lib/demo-store";
import { formatNumber } from "../../../lib/formatters";
import { AdminRequests } from "../../../components/portal/AdminRequests";

export default function AdminPage() {
  const { organizations, areas } = useDemoStore();
  return (
    <div className="dash-stack">
      <PageIntro description="Gestioná las organizaciones de la plataforma, sus contratos y sus accesos." />
      <div className="admin-grid">
        {organizations.map((organization) => (
          <Panel className="admin-card" key={organization.id} hover spotlight selfReveal>
            <div className="admin-card__top">
              <span className="metric-card__icon"><Building2 size={18} aria-hidden="true" /></span>
              <span className={`ui-badge ${organization.status === "active" ? "ui-badge--green" : "ui-badge--amber"}`}>
                {organization.status === "active" ? "Activa" : "Inactiva"}
              </span>
            </div>
            <h2>{organization.name}</h2>
            <p className="portal-muted">
              {formatNumber(organization.monthlyTokenLimit)} tokens por mes · {areas.filter((area) => area.organizationId === organization.id).length} áreas
            </p>
            <Link className="table-action admin-card__link" href={`/admin/organizations/${organization.id}`}>Administrar organización</Link>
          </Panel>
        ))}
      </div>
      <AdminRequests />
    </div>
  );
}
