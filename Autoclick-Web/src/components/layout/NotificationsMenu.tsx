"use client";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { AlertTriangle, Bell, CircleCheck, PiggyBank, TrendingUp } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useDemoStore } from "../../lib/demo-store";
import { formatNumber } from "../../lib/formatters";

interface PortalNotice {
  id: string;
  icon: LucideIcon;
  tone: "warn" | "info" | "ok";
  title: string;
  detail: string;
}

/**
 * Notices are derived from the same state the dashboard renders, so the bell
 * never shows something the portal cannot back up with real numbers.
 */
function buildNotices({
  usage,
  limit,
  unassigned,
  hasDesktopAccess,
  accessReason,
  emptyAreas,
  version,
}: {
  usage: number;
  limit: number;
  unassigned: number;
  hasDesktopAccess: boolean;
  accessReason: string | null;
  emptyAreas: string[];
  version: string;
}): PortalNotice[] {
  const notices: PortalNotice[] = [];
  const percent = limit > 0 ? Math.round((usage / limit) * 100) : 0;

  if (!hasDesktopAccess && accessReason) {
    notices.push({ id: "access", icon: AlertTriangle, tone: "warn", title: "Acceso a Desktop bloqueado", detail: accessReason });
  }
  if (limit > 0 && percent >= 80) {
    notices.push({
      id: "usage",
      icon: TrendingUp,
      tone: percent >= 100 ? "warn" : "info",
      title: `Consumo al ${percent}% del límite`,
      detail: `${formatNumber(usage)} de ${formatNumber(limit)} tokens del período en curso.`,
    });
  }
  if (unassigned > 0) {
    notices.push({
      id: "unassigned",
      icon: PiggyBank,
      tone: "info",
      title: "Saldo sin asignar",
      detail: `Quedan ${formatNumber(unassigned)} tokens para repartir entre las áreas.`,
    });
  }
  for (const name of emptyAreas.slice(0, 2)) {
    notices.push({ id: `empty-${name}`, icon: AlertTriangle, tone: "info", title: `${name} sin consumo`, detail: "El área todavía no registró uso en este período." });
  }
  if (notices.length === 0) {
    notices.push({ id: "ok", icon: CircleCheck, tone: "ok", title: "Todo en orden", detail: `Sin alertas de consumo. AutoClick Desktop ${version} disponible.` });
  }
  return notices;
}

export function NotificationsMenu() {
  const {
    organizationUsage,
    organizationTokenLimit,
    organizationUnassignedTokens,
    hasDesktopAccess,
    accessReason,
    visibleAreas,
    tokenUsage,
    organization,
    desktopVersion,
  } = useDemoStore();

  const emptyAreas = visibleAreas
    .filter((area) => area.status === "active" && !tokenUsage.some((item) => item.areaId === area.id && item.organizationId === organization?.id && item.tokensUsed > 0))
    .map((area) => area.name);

  const notices = buildNotices({
    usage: organizationUsage,
    limit: organizationTokenLimit,
    unassigned: organizationUnassignedTokens,
    hasDesktopAccess,
    accessReason,
    emptyAreas,
    version: desktopVersion,
  });
  const alerts = notices.filter((notice) => notice.tone !== "ok").length;

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button className="portal-iconbtn" type="button" aria-label={alerts > 0 ? `Notificaciones: ${alerts} sin leer` : "Notificaciones"}>
          <Bell size={18} aria-hidden="true" />
          {alerts > 0 && <span className="portal-iconbtn__dot" aria-hidden="true" />}
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content className="dash-menu dash-menu--wide" align="end" sideOffset={10} collisionPadding={12}>
          <div className="dash-menu__title">
            <strong>Notificaciones</strong>
            <span>{alerts > 0 ? `${alerts} sin leer` : "Al día"}</span>
          </div>
          <div className="dash-menu__sep" />
          <ul className="dash-notices">
            {notices.map((notice) => {
              const Icon = notice.icon;
              return (
                <li className="dash-notice" key={notice.id}>
                  <span className={`dash-notice__icon dash-notice__icon--${notice.tone}`}>
                    <Icon size={15} aria-hidden="true" />
                  </span>
                  <div>
                    <strong>{notice.title}</strong>
                    <small>{notice.detail}</small>
                  </div>
                </li>
              );
            })}
          </ul>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
