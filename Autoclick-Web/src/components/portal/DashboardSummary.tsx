"use client";
import { motion } from "framer-motion";
import { Gauge, Layers3, ShieldAlert, Users, Zap } from "lucide-react";
import { today, useDemoStore } from "../../lib/demo-store";
import { MetricCard } from "../ui/MetricCard";
import { DesktopDownloadCard } from "./DesktopDownloadCard";
import { ConsumptionChart } from "./ConsumptionChart";
import { UsageTrendCard } from "./UsageTrendCard";
import { AllocationCard } from "./AllocationCard";
import { AccessCard } from "./AccessCard";
import { ActivityPanel } from "./ActivityPanel";
import { buildUsageSeries, recentPeriods, trendDelta } from "../../lib/usage";
import { revealGroup, revealItem, revealProps, revealViewport } from "../../lib/motion";

export function DashboardSummary() {
  const {
    organization,
    role,
    users,
    user,
    visibleAreas,
    tokenUsage,
    organizationUsage,
    currentAreaUsage,
    ownUsage,
    organizationTokenLimit,
    organizationAssignedTokens,
    organizationUnassignedTokens,
    visibleAreaMemberships,
    desktopVersion,
    hasDesktopAccess,
    accessReason,
  } = useDemoStore();

  const isOwnerView = role === "ORGANIZATION_OWNER";
  const usage = role === "AREA_MEMBER" ? ownUsage : role === "AREA_ADMIN" ? currentAreaUsage : organizationUsage;
  const people = new Set(visibleAreaMemberships.map((item) => item.userId)).size || 1;
  const average = Math.round(usage / people);
  const blockedReason = accessReason ?? "Tu membresía no permite acceder a AutoClick Desktop.";
  const activeAreas = visibleAreas.filter((area) => area.status === "active");
  const usagePercent = organizationTokenLimit > 0 ? Math.min(100, Math.round((usage / organizationTokenLimit) * 100)) : 0;

  const currentPeriod = today.slice(0, 7);
  const inScope = tokenUsage.filter(
    (item) =>
      item.organizationId === organization?.id &&
      visibleAreas.some((area) => area.id === item.areaId) &&
      (role !== "AREA_MEMBER" || item.userId === user.id),
  );
  const scopedUsage = inScope.filter((item) => item.period === currentPeriod);
  const series = buildUsageSeries(inScope, recentPeriods(currentPeriod, 12));
  const delta = trendDelta(series);

  const areaUsageData = activeAreas.map((area) => ({
    name: area.name,
    tokens: scopedUsage.filter((item) => item.areaId === area.id).reduce((sum, item) => sum + item.tokensUsed, 0),
    limit: area.tokenLimit,
  }));

  const usageByUser = new Map<string, number>();
  for (const item of scopedUsage) usageByUser.set(item.userId, (usageByUser.get(item.userId) ?? 0) + item.tokensUsed);
  const totalUserUsage = [...usageByUser.values()].reduce((sum, value) => sum + value, 0);
  const activityRows = [...usageByUser.entries()]
    .map(([userId, value]) => {
      const person = users.find((item) => item.id === userId);
      const areaNames = [...new Set(scopedUsage.filter((item) => item.userId === userId).map((item) => visibleAreas.find((area) => area.id === item.areaId)?.name).filter(Boolean))];
      return {
        id: userId,
        label: person?.name ?? "Usuario",
        initials: person?.avatarInitials,
        avatarUrl: person?.avatarUrl,
        sub: areaNames.join(" · ") || "Sin área",
        value,
        total: totalUserUsage,
      };
    })
    .sort((a, b) => b.value - a.value)
    .slice(0, 5);

  const scopeLabel = role === "AREA_MEMBER" ? "tu usuario" : role === "AREA_ADMIN" ? "tus áreas" : "la organización";

  return (
    <div className="dash-stack">
      {!hasDesktopAccess && (
        <motion.section
          className="dash-banner"
          role="status"
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.45 }}
        >
          <span className="dash-banner__icon"><ShieldAlert size={20} aria-hidden="true" /></span>
          <div>
            <h2>Acceso a AutoClick Desktop bloqueado</h2>
            <p>{blockedReason}</p>
          </div>
        </motion.section>
      )}

      <div className="dash-grid">
        <motion.section className="dash-grid__metrics dash-metrics" aria-label="Indicadores del período" variants={revealGroup} initial="hidden" animate="visible">
          <MetricCard
            icon={Gauge}
            label="Tokens utilizados"
            value={usage}
            helper="En el período en curso"
            visual={organizationTokenLimit > 0 ? { type: "radial", percent: usagePercent } : { type: "delta", percent: delta }}
          />
          <MetricCard
            icon={Layers3}
            tone="cyan"
            label="Áreas activas"
            value={activeAreas.length}
            helper={`${visibleAreas.length} visibles para tu rol`}
            visual={visibleAreas.length > 0 ? { type: "ratio", active: activeAreas.length, total: visibleAreas.length } : { type: "none" }}
          />
          <MetricCard
            icon={Users}
            tone="amber"
            label="Promedio de tokens por usuario"
            value={average}
            helper={`Entre ${people} ${people === 1 ? "persona" : "personas"}`}
            visual={usage > 0 ? { type: "bar", percent: Math.min(100, Math.round((average / Math.max(usage, 1)) * 100)) } : { type: "none" }}
          />
          <MetricCard
            icon={Zap}
            tone="green"
            label="Versión disponible"
            value={desktopVersion}
            helper="AutoClick Desktop"
            visual={{ type: "none" }}
          />
        </motion.section>

        <motion.div className="dash-grid__feature" {...revealProps}>
          <DesktopDownloadCard
            version={desktopVersion}
            hasAccess={hasDesktopAccess}
            blockedReason={blockedReason}
            usage={usage}
            limit={organizationTokenLimit}
          />
        </motion.div>

        <motion.div className="dash-grid__panels" variants={revealGroup} initial="hidden" whileInView="visible" viewport={revealViewport}>
          <ConsumptionChart data={areaUsageData} />
          <ActivityPanel
            rows={activityRows}
            eyebrow="Personas"
            title="Consumo por persona"
            description="Quién consumió más tokens en tus áreas durante el período en curso."
          />
        </motion.div>

        <motion.div className="dash-grid__rail" variants={revealGroup} initial="hidden" animate="visible">
          <motion.div variants={revealItem}>
            <UsageTrendCard series={series} scopeLabel={scopeLabel} />
          </motion.div>
          <motion.div variants={revealItem} className="dash-grid__rail-fill">
            {isOwnerView ? (
              <AllocationCard assigned={organizationAssignedTokens} unassigned={organizationUnassignedTokens} limit={organizationTokenLimit} />
            ) : (
              <AccessCard
                hasAccess={hasDesktopAccess}
                reason={blockedReason}
                areaCount={visibleAreas.length}
                version={desktopVersion}
                usage={usage}
              />
            )}
          </motion.div>
        </motion.div>
      </div>
    </div>
  );
}
