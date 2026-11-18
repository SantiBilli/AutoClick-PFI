"use client";
import Link from "next/link";
import { motion } from "framer-motion";
import { ArrowRight, FolderKanban } from "lucide-react";
import { today, useDemoStore } from "../../lib/demo-store";
import { UsageProgress } from "./UsageProgress";
import { DataTable } from "./DataTable";
import { Panel } from "../ui/Panel";
import { Badge } from "../ui/Badge";
import { formatNumber } from "../../lib/formatters";
import { revealItem } from "../../lib/motion";

const COLUMNS = [
  { key: "area", header: "Área" },
  { key: "members", header: "Miembros" },
  { key: "usage", header: "Uso" },
  { key: "limit", header: "Límite de tokens" },
  { key: "status", header: "Estado" },
  { key: "action", header: "Acción" },
];

export function AreaTable() {
  const { role, organization, visibleAreas, visibleAreaMemberships, tokenUsage, organizationTokenLimit, organizationAssignedTokens, organizationUnassignedTokens } = useDemoStore();
  const canViewOrganizationAllocation = role === "ORGANIZATION_OWNER" || role === "AUTOCLICK_ADMIN";

  return (
    <Panel className="portal-card" selfReveal>
      <div className="portal-card__heading">
        <div>
          <p className="dash-eyebrow">Estructura</p>
          <h2>Áreas</h2>
        </div>
        <Badge tone="slate">{visibleAreas.length} en total</Badge>
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
      <DataTable columns={COLUMNS} stickyHeader={visibleAreas.length > 8} isEmpty={visibleAreas.length === 0} empty="Todavía no hay áreas en esta organización.">
        {visibleAreas.map((area) => {
          const areaUsage = tokenUsage
            .filter((item) => item.organizationId === organization?.id && item.areaId === area.id && item.period === today.slice(0, 7))
            .reduce((sum, item) => sum + item.tokensUsed, 0);
          const isArchived = area.status !== "active";
          const usagePct = area.tokenLimit > 0 ? Math.min(100, Math.round((areaUsage / area.tokenLimit) * 100)) : 0;
          return (
            <motion.tr key={area.id} className={isArchived ? "is-archived" : ""} variants={revealItem}>
              <td>
                <span className="table-primary">
                  <span className="table-icon"><FolderKanban size={16} aria-hidden="true" /></span>
                  <span>
                    <strong>{area.name}</strong>
                    <small>{formatNumber(areaUsage)} tokens este período</small>
                  </span>
                </span>
              </td>
              <td>{visibleAreaMemberships.filter((item) => item.areaId === area.id).length}</td>
              <td>
                <span className="table-usage-bar" role="img" aria-label={`${usagePct}% de uso`}>
                  <span className="table-usage-bar__fill" style={{ width: `${usagePct}%` }} />
                </span>
              </td>
              <td>{formatNumber(area.tokenLimit)}</td>
              <td>{isArchived ? <Badge tone="slate">Archivada</Badge> : <Badge tone="green">Activa</Badge>}</td>
              <td>
                <Link className="table-action" href={`/dashboard/areas/${area.id}`}>
                  Ver detalle <ArrowRight size={13} aria-hidden="true" />
                </Link>
              </td>
            </motion.tr>
          );
        })}
      </DataTable>
    </Panel>
  );
}
