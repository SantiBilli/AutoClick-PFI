import type { AreaMembershipRole, DemoRole } from "./domain";

export const roleLabels: Record<DemoRole, string> = {
  AUTOCLICK_ADMIN: "Admin. AutoClick",
  ORGANIZATION_OWNER: "Dueño de organización",
  AREA_ADMIN: "Administrador de área",
  AREA_MEMBER: "Miembro de área",
};

export const areaMembershipRoleLabels: Record<AreaMembershipRole, string> = {
  AREA_ADMIN: "Administrador de área",
  AREA_MEMBER: "Miembro de área",
};

/** Short forms for tight surfaces (collapsed sidebar, chips). */
export const roleShortLabels: Record<DemoRole, string> = {
  AUTOCLICK_ADMIN: "Admin",
  ORGANIZATION_OWNER: "Dueño",
  AREA_ADMIN: "Adm. área",
  AREA_MEMBER: "Miembro",
};
