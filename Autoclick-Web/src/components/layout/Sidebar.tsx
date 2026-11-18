"use client";
import Link from "next/link";
import Image from "next/image";
import { motion } from "framer-motion";
import { ChevronLeft, ChevronRight, Download, X } from "lucide-react";
import type { DemoRole } from "../../lib/domain";
import { navGroupLabels, navGroupOrder, type PortalNavEntry } from "../../lib/portal-nav";
import { useDemoStore } from "../../lib/demo-store";
import { RobotHelper } from "../ui/RobotHelper";
import { cloudApi } from "../../lib/cloud-auth";
import { DESKTOP_DOWNLOADS_ENABLED } from "../../lib/desktop-downloads";
import { useState } from "react";
import { easeOutExpo, springSnappy } from "../../lib/motion";

interface NavEntry extends PortalNavEntry {
  href: string;
}

export function Sidebar({
  role,
  nav,
  pathname,
  menuOpen,
  collapsed,
  onCloseMenu,
  onNavigate,
  onToggleCollapse,
}: {
  role: DemoRole;
  nav: NavEntry[];
  pathname: string;
  menuOpen: boolean;
  collapsed: boolean;
  onCloseMenu: () => void;
  onNavigate: () => void;
  onToggleCollapse: () => void;
}) {
  const { hasDesktopAccess, desktopVersion } = useDemoStore();
  const homeHref = role === "AUTOCLICK_ADMIN" ? "/admin" : "/dashboard";
  const groups = navGroupOrder
    .map((group) => ({ group, items: nav.filter((item) => item.group === group) }))
    .filter((entry) => entry.items.length > 0);

  return (
    <aside
      className={`portal-side ${menuOpen ? "portal-side--open" : ""} ${collapsed ? "portal-side--collapsed" : ""}`.trim()}
    >
      <div className="portal-side__head">
        <Link className="portal-side__brand" href={homeHref} aria-label="AutoClick">
          <Image src="/logo/autoclick-logo-dark.png" alt="" width={30} height={30} priority />
          {!collapsed && <span>AutoClick</span>}
        </Link>
        <button className="ui-icon-button portal-side__close" type="button" aria-label="Cerrar menú" onClick={onCloseMenu}>
          <X size={19} aria-hidden="true" />
        </button>
      </div>

      <button
        className="portal-side__collapse"
        type="button"
        aria-label={collapsed ? "Expandir menú lateral" : "Contraer menú lateral"}
        aria-pressed={collapsed}
        onClick={onToggleCollapse}
      >
        {collapsed ? <ChevronRight size={14} aria-hidden="true" /> : <ChevronLeft size={14} aria-hidden="true" />}
      </button>

      <div className="portal-side__scroll">
        {/* One landmark for the whole menu; groups are headings inside it. */}
        <nav className="portal-nav" aria-label="Navegación del portal">
          {groups.map(({ group, items }) => (
            <div className="portal-nav__group" key={group}>
              {!collapsed && <p className="portal-side__group">{navGroupLabels[group]}</p>}
              {items.map((item, index) => {
                const active = pathname === item.href;
                const Icon = item.icon;
                return (
                  <motion.div
                    key={item.href}
                    initial={{ opacity: 0, x: -10 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: 0.08 + index * 0.05, duration: 0.4, ease: easeOutExpo }}
                  >
                    <Link
                      className="portal-nav__item"
                      href={item.href}
                      aria-current={active ? "page" : undefined}
                      onClick={onNavigate}
                      title={collapsed ? item.label : undefined}
                    >
                      {active && (
                        <>
                          <motion.span className="portal-nav__pill" layoutId="portal-nav-pill" transition={springSnappy} />
                          <motion.span className="portal-nav__marker" layoutId="portal-nav-marker" transition={springSnappy} />
                        </>
                      )}
                      <span className="portal-nav__icon">
                        <Icon size={17} strokeWidth={2} aria-hidden="true" />
                      </span>
                      <span className="portal-nav__text">
                        <strong>{item.label}</strong>
                        <small>{item.hint}</small>
                      </span>
                    </Link>
                  </motion.div>
                );
              })}
            </div>
          ))}
        </nav>
      </div>

      <div className="portal-side__foot">
        <DesktopPromo collapsed={collapsed} hasAccess={hasDesktopAccess} version={desktopVersion} />
      </div>
    </aside>
  );
}

function DesktopPromo({ collapsed, hasAccess, version }: { collapsed: boolean; hasAccess: boolean; version: string }) {
  const { downloadUrl } = useDemoStore();
  const [downloading, setDownloading] = useState(false);
  const available = hasAccess && downloadUrl === '/v1/desktop/download';
  async function download() {
    if (!DESKTOP_DOWNLOADS_ENABLED || !available || downloading) return;
    setDownloading(true);
    try { const result = await cloudApi<{ url: string }>(downloadUrl); window.location.assign(result.url); }
    catch { /* Shared API feedback displays the error. */ }
    finally { setDownloading(false); }
  }
  if (collapsed) {
    return (
      <button
        className="portal-promo portal-promo--compact"
        type="button"
        disabled={!DESKTOP_DOWNLOADS_ENABLED || !available || downloading} onClick={() => void download()}
        title={hasAccess ? `Descargar AutoClick Desktop ${version}` : "Descarga bloqueada"}
        aria-label={hasAccess ? `Descargar AutoClick Desktop ${version}` : "Descarga de AutoClick Desktop bloqueada"}
      >
        <Download size={17} aria-hidden="true" />
      </button>
    );
  }

  return (
    <motion.div
      className="portal-promo"
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.35, duration: 0.55, ease: easeOutExpo }}
    >
      <RobotHelper className="portal-promo__robot" pose={hasAccess ? "success" : "explaining"} size="sm" float />
      <strong>AutoClick Desktop {version}</strong>
      <p>{hasAccess ? "Automatizá tus flujos desde tu computadora." : "Regularizá tu acceso para poder descargarlo."}</p>
      <button className="portal-promo__cta" type="button" disabled={!DESKTOP_DOWNLOADS_ENABLED || !available || downloading} onClick={() => void download()}>
        <Download size={14} aria-hidden="true" /> {hasAccess ? "Obtener ahora" : "Sin acceso"}
      </button>
    </motion.div>
  );
}
