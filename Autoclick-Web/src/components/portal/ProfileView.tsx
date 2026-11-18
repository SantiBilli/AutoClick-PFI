"use client";
import { ProfilePhotoEditor } from "./ProfilePhotoEditor";
import { DeactivateAccount } from "./DeactivateAccount";
import { Avatar } from "../ui/Avatar";
import Link from "next/link";
import { motion } from "framer-motion";
import { Building2, CalendarRange, FolderKanban, Mail, Settings, ShieldCheck } from "lucide-react";
import { Panel } from "../ui/Panel";
import { Badge } from "../ui/Badge";
import { today, useDemoStore } from "../../lib/demo-store";
import { areaMembershipRoleLabels, roleLabels } from "../../lib/role-labels";
import { formatDate, formatNumber } from "../../lib/formatters";
import { revealGroup, revealItem, revealViewport } from "../../lib/motion";

/** Account screen behind the "Mi perfil" entry of the topbar menu. */
export function ProfileView() {
  const { user, role, organization, organizationMemberships, areaMemberships, visibleAreas, tokenUsage } = useDemoStore();
  const canOpenSettings = true;
  const membership = organizationMemberships.find((item) => item.userId === user.id && item.organizationId === organization?.id);
  const myAreas = areaMemberships.filter((item) => item.userId === user.id && item.status === "active" && visibleAreas.some((area) => area.id === item.areaId));
  const ownUsage = tokenUsage
    .filter((item) => item.userId === user.id && item.period === today.slice(0, 7) && item.organizationId === organization?.id)
    .reduce((sum, item) => sum + item.tokensUsed, 0);

  return (
    <motion.div className="profile-grid" variants={revealGroup} initial="hidden" whileInView="visible" viewport={revealViewport}>
      <Panel className="profile-card">
        <div className="profile-card__identity">
          <Avatar user={user} className="portal-avatar profile-card__avatar" />
          <div>
            <h2>{user.name}</h2>
            <p className="portal-muted"><Mail size={14} aria-hidden="true" /> {user.email}</p>
            <div className="profile-card__badges">
              <Badge tone="blue">{roleLabels[role]}</Badge>
              {organization && <Badge tone="slate">{organization.name}</Badge>}
              <Badge tone={user.status === "active" ? "green" : "amber"}>{user.status === "active" ? "Cuenta activa" : "Cuenta inactiva"}</Badge>
            </div>
          </div>
        </div>
        <ProfilePhotoEditor />
        <dl className="profile-facts">
          <div>
            <dt><ShieldCheck size={14} aria-hidden="true" /> Rol en la organización</dt>
            <dd>{membership ? (membership.role === "ORGANIZATION_OWNER" ? "Dueño de organización" : "Miembro de organización") : "Sin membresía"}</dd>
          </div>
          <div>
            <dt><CalendarRange size={14} aria-hidden="true" /> Miembro desde</dt>
            <dd>{membership ? formatDate(membership.startsAt) : "—"}</dd>
          </div>
          <div>
            <dt><Building2 size={14} aria-hidden="true" /> Organización</dt>
            <dd>{organization?.name ?? "AutoClick"}</dd>
          </div>
          <div>
            <dt><FolderKanban size={14} aria-hidden="true" /> Tokens de este período</dt>
            <dd>{formatNumber(ownUsage)}</dd>
          </div>
        </dl>
        {canOpenSettings && (
          <Link className="ui-button ui-button--ghost ui-button--md profile-card__action" href="/dashboard/settings">
            <Settings size={16} aria-hidden="true" /> Editar en configuración
          </Link>
        )}
      </Panel>

      <Panel className="portal-card profile-areas" variants={revealItem}>
        <div className="portal-card__heading">
          <div>
            <p className="dash-eyebrow">Acceso</p>
            <h2>Tus áreas</h2>
          </div>
          <Badge tone="slate">{myAreas.length}</Badge>
        </div>
        {myAreas.length > 0 ? (
          <ul className="profile-areas__list">
            {myAreas.map((item) => {
              const area = visibleAreas.find((entry) => entry.id === item.areaId);
              if (!area) return null;
              return (
                <li key={item.id}>
                  <Link href={`/dashboard/areas/${area.id}`}>
                    <span className="table-icon"><FolderKanban size={15} aria-hidden="true" /></span>
                    <span>
                      <strong>{area.name}</strong>
                      <small>{areaMembershipRoleLabels[item.role]}</small>
                    </span>
                    <Badge tone={area.status === "active" ? "green" : "slate"}>{area.status === "active" ? "Activa" : "Archivada"}</Badge>
                  </Link>
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="portal-muted">Todavía no estás asignado a ningún área.</p>
        )}
      </Panel>
      <Panel className="profile-card"><DeactivateAccount /></Panel>
    </motion.div>
  );
}
