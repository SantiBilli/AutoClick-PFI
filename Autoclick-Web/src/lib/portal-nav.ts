import { Building2, FolderKanban, LayoutDashboard, Settings, UserRound, Users } from "lucide-react";
import type { LucideIcon } from "lucide-react";

export interface PortalNavEntry {
  label: string;
  icon: LucideIcon;
  /** Small line shown under the label while the sidebar is expanded. */
  hint: string;
  /** Sidebar group heading the entry belongs to. */
  group: "principal" | "organizacion" | "plataforma";
}

export const navItems: Record<string, PortalNavEntry> = {
  "/admin": { label: "Resumen", icon: LayoutDashboard, hint: "Estado de la plataforma", group: "principal" },
  "/admin/organizations": { label: "Organizaciones", icon: Building2, hint: "Altas y contratos", group: "plataforma" },
  "/dashboard": { label: "Resumen", icon: LayoutDashboard, hint: "Consumo y accesos", group: "principal" },
  "/dashboard/areas": { label: "Áreas", icon: FolderKanban, hint: "Equipos y límites", group: "organizacion" },
  "/dashboard/users": { label: "Usuarios", icon: Users, hint: "Personas y roles", group: "organizacion" },
  "/dashboard/settings": { label: "Configuración", icon: Settings, hint: "Cuenta y organización", group: "plataforma" },
  // Reachable from the topbar account menu; deliberately not part of navigationByRole.
  "/dashboard/profile": { label: "Mi perfil", icon: UserRound, hint: "Tu cuenta", group: "plataforma" },
  "/admin/profile": { label: "Mi perfil", icon: UserRound, hint: "Tu cuenta", group: "plataforma" },
};

export const navGroupLabels: Record<PortalNavEntry["group"], string> = {
  principal: "Principal",
  organizacion: "Organización",
  plataforma: "Plataforma",
};

export const navGroupOrder: PortalNavEntry["group"][] = ["principal", "organizacion", "plataforma"];
