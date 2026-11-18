"use client";

import { usePathname } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useState, type ReactNode } from "react";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";
import { useDemoStore } from "../../lib/demo-store";
import { navigationByRole } from "../portal/PortalRouteGuard";
import { navItems } from "../../lib/portal-nav";
import { easeOutExpo } from "../../lib/motion";

const SIDEBAR_COLLAPSE_KEY = "autoclick-sidebar-collapsed";

/** Longest nav entry whose href is a prefix of the current path. */
function matchSection(pathname: string) {
  const href = Object.keys(navItems)
    .filter((item) => pathname === item || pathname.startsWith(`${item}/`))
    .sort((a, b) => b.length - a.length)[0];
  return href ? { href, ...navItems[href] } : null;
}

export function PortalShell({ children }: { children: ReactNode }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [collapseHydrated, setCollapseHydrated] = useState(false);
  const pathname = usePathname();
  const { role, user, organization } = useDemoStore();
  const nav = navigationByRole[role].map((href) => ({ href, ...navItems[href] }));

  useEffect(() => {
    if (window.localStorage.getItem(SIDEBAR_COLLAPSE_KEY) === "1") setCollapsed(true);
    setCollapseHydrated(true);
  }, []);

  useEffect(() => {
    if (collapseHydrated) window.localStorage.setItem(SIDEBAR_COLLAPSE_KEY, collapsed ? "1" : "0");
  }, [collapseHydrated, collapsed]);

  useEffect(() => {
    if (!menuOpen) return;
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMenuOpen(false);
    };
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, [menuOpen]);

  const section = matchSection(pathname);
  const isHome = pathname === "/dashboard" || pathname === "/admin";
  const isSection = !!navItems[pathname];
  const rootLabel = organization?.name ?? (role === "AUTOCLICK_ADMIN" ? "AutoClick" : "Portal");

  return (
    <div className="portal-shell">
      <a className="skip-link" href="#portal-content">Ir al contenido</a>
      <Sidebar
        role={role}
        nav={nav}
        pathname={pathname}
        menuOpen={menuOpen}
        collapsed={collapsed}
        onCloseMenu={() => setMenuOpen(false)}
        onNavigate={() => setMenuOpen(false)}
        onToggleCollapse={() => setCollapsed((value) => !value)}
      />
      <button
        className={`portal-side__backdrop ${menuOpen ? "portal-side__backdrop--visible" : ""}`.trim()}
        type="button"
        aria-label="Cerrar menú"
        tabIndex={menuOpen ? 0 : -1}
        onClick={() => setMenuOpen(false)}
      />
      <div className={`portal-main ${collapsed ? "portal-main--wide" : ""}`.trim()}>
        <Topbar
          kicker={isHome ? rootLabel : undefined}
          title={isHome ? `Hola, ${user.name.split(" ")[0]}.` : isSection ? section?.label : undefined}
          crumbs={section && !isHome ? [{ label: rootLabel }, { label: section.label, href: isSection ? undefined : section.href }] : undefined}
          onOpenMenu={() => setMenuOpen(true)}
        />
        <AnimatePresence mode="wait" initial={false}>
          <motion.main
            key={pathname}
            id="portal-content"
            className="portal-content"
            initial={{ opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.32, ease: easeOutExpo }}
          >
            {children}
          </motion.main>
        </AnimatePresence>
      </div>
    </div>
  );
}
