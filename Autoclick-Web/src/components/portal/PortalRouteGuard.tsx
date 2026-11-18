"use client";
import Link from "next/link";
import { ShieldAlert } from "lucide-react";
import { usePathname } from "next/navigation";
import { useDemoStore } from "../../lib/demo-store";
import type { Area, DemoRole } from "../../lib/domain";

export type PortalSection = "admin" | "dashboard";
export const navigationByRole = { AUTOCLICK_ADMIN: ["/admin", "/admin/organizations"], ORGANIZATION_OWNER: ["/dashboard", "/dashboard/areas", "/dashboard/users", "/dashboard/settings"], AREA_ADMIN: ["/dashboard", "/dashboard/areas"], AREA_MEMBER: ["/dashboard", "/dashboard/areas"] } as const;
export function canAccessPortalPath(pathname: string, role: DemoRole, visibleAreas: Area[]) { if (pathname.startsWith("/admin")) return role === "AUTOCLICK_ADMIN";
  if (pathname === "/dashboard/profile" || pathname === "/dashboard/settings") return true; if (!pathname.startsWith("/dashboard") ) return false; if (pathname === "/dashboard/users") return role === "ORGANIZATION_OWNER" || role === "AUTOCLICK_ADMIN"; if (pathname.startsWith("/dashboard/areas/")) { const areaId = pathname.slice("/dashboard/areas/".length).split("/")[0]; return visibleAreas.some((area) => area.id === areaId); } return pathname === "/dashboard" || pathname === "/dashboard/areas"; }
export function PortalRouteGuard({ children, section }: { children: React.ReactNode; section: PortalSection }) { const pathname = usePathname(); const { role, visibleAreas } = useDemoStore(); const sectionAllowed = section === "admin" ? role === "AUTOCLICK_ADMIN" : true; const forbidden = !sectionAllowed || !canAccessPortalPath(pathname, role, visibleAreas); if (!forbidden) return <>{children}</>; const areaRouteForbidden = pathname.startsWith("/dashboard/areas/"); return <section className="portal-access-state" aria-labelledby="portal-access-title"><span className="portal-access-state__icon"><ShieldAlert size={25} /></span><p className="eyebrow">{areaRouteForbidden ? "Área restringida" : "Acceso restringido"}</p><h1 id="portal-access-title">{areaRouteForbidden ? "Área no encontrada" : "No tenés acceso a esta sección"}</h1><p>{areaRouteForbidden ? "No tenés acceso a esta área." : "Tu cuenta no tiene el permiso necesario para ver esta pantalla."}</p><Link className="ui-button ui-button--primary ui-button--md" href={role === "AUTOCLICK_ADMIN" ? "/admin" : "/dashboard"}>Volver al inicio</Link></section>; }
