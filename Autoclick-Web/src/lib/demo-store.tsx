"use client";
import type { Area, DemoRole, Organization, OrganizationMembership, TokenUsage } from "./domain";

export const today = new Date().toISOString().slice(0, 10);
export function isValidDemoRole(value: unknown): value is DemoRole {
  return value === "AUTOCLICK_ADMIN" || value === "ORGANIZATION_OWNER" || value === "AREA_ADMIN" || value === "AREA_MEMBER";
}
export function isValidIsoDate(value: unknown): value is string {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(date.getTime()) && date.toISOString().slice(0, 10) === value;
}
export function isValidDateRange(startsAt: unknown, endsAt: unknown): startsAt is string {
  return isValidIsoDate(startsAt) && (endsAt === null || (isValidIsoDate(endsAt) && endsAt >= startsAt));
}
export const isValidTokenLimit = (value: unknown): value is number => typeof value === "number" && Number.isInteger(value) && value >= 0;
export const isValidOrganizationStatus = (value: unknown): value is Organization["status"] => value === "active" || value === "inactive";
export const isValidMembershipStatus = (value: unknown): value is OrganizationMembership["status"] => value === "active" || value === "inactive" || value === "expired";
export const isWithinOrganizationTokenLimit = (usage: number, limit: number) => usage < limit;
export const canUpdateOrganizationSettings = (role: DemoRole) => role === "AUTOCLICK_ADMIN";
export const canUpdateAreaTokenLimit = (role: DemoRole) => role === "ORGANIZATION_OWNER";
export const isOrganizationCurrent = (organization: Organization) => organization.status === "active" && isValidDateRange(organization.startsAt, organization.endsAt) && organization.startsAt <= today && (!organization.endsAt || organization.endsAt >= today);
export const isCurrentMembership = (membership: OrganizationMembership) => membership.status === "active" && isValidDateRange(membership.startsAt, membership.endsAt) && membership.startsAt <= today && (!membership.endsAt || membership.endsAt >= today);
export type OrganizationSettingsPatch = Partial<Pick<Organization, "status" | "startsAt" | "endsAt" | "monthlyTokenLimit">>;
export function getOrganizationTokenTotals(organizationId: string | undefined, organizations: Organization[], areas: Area[], tokenUsage: TokenUsage[]) {
  const organization = organizations.find((item) => item.id === organizationId);
  const assigned = areas.filter((area) => area.organizationId === organizationId).reduce((sum, area) => sum + area.tokenLimit, 0);
  const usage = tokenUsage.filter((item) => item.organizationId === organizationId && item.period === today.slice(0, 7)).reduce((sum, item) => sum + item.tokensUsed, 0);
  const limit = organization?.monthlyTokenLimit ?? 0;
  return { usage, limit, assigned, unassigned: Math.max(0, limit - assigned) };
}
export function updateOrganizationSettingsInState(role: DemoRole, organizations: Organization[], areas: Area[], id: string, patch: OrganizationSettingsPatch) {
  if (!canUpdateOrganizationSettings(role) || Object.values(patch).some((value) => value === undefined)) return { accepted: false, organizations, error: "No se pudo guardar la configuración de la organización." };
  const current = organizations.find((item) => item.id === id);
  if (!current) return { accepted: false, organizations, error: "No se pudo guardar la configuración de la organización." };
  const next = { ...current, ...patch };
  if (!isValidOrganizationStatus(next.status) || !isValidDateRange(next.startsAt, next.endsAt) || !isValidTokenLimit(next.monthlyTokenLimit)) return { accepted: false, organizations, error: "No se pudo guardar la configuración de la organización." };
  const assignedTokens = areas.filter((area) => area.organizationId === id).reduce((sum, area) => sum + area.tokenLimit, 0);
  if (next.monthlyTokenLimit < assignedTokens) return { accepted: false, organizations, error: `El límite mensual no puede ser menor que los ${assignedTokens.toLocaleString("es-AR")} tokens asignados a las áreas.` };
  return { accepted: true, organizations: organizations.map((item) => item.id === id ? next : item), error: null };
}

export function updateAreaTokenLimitInState(role: DemoRole, organization: Organization | null, areas: Area[], areaId: string, tokenLimit: number) {
  const area = areas.find((item) => item.id === areaId);
  if (!organization || !area || area.organizationId !== organization.id || !canUpdateAreaTokenLimit(role) || !isValidTokenLimit(tokenLimit)) return { accepted: false, areas };
  const assignedWithoutArea = areas.filter((item) => item.organizationId === organization.id && item.id !== areaId).reduce((sum, item) => sum + item.tokenLimit, 0);
  if (assignedWithoutArea + tokenLimit > organization.monthlyTokenLimit) return { accepted: false, areas };
  return { accepted: true, areas: areas.map((item) => item.id === areaId ? { ...item, tokenLimit } : item) };
}
export function updateOrganizationMembershipInState(role: DemoRole, memberships: OrganizationMembership[], id: string, patch: Partial<Pick<OrganizationMembership, "status" | "startsAt" | "endsAt">>) {
  if (role !== "AUTOCLICK_ADMIN" || Object.values(patch).some((value) => value === undefined)) return { accepted: false, memberships };
  const current = memberships.find((item) => item.id === id);
  if (!current) return { accepted: false, memberships };
  const next = { ...current, ...patch };
  if (!isValidMembershipStatus(next.status) || !isValidDateRange(next.startsAt, next.endsAt)) return { accepted: false, memberships };
  return { accepted: true, memberships: memberships.map((item) => item.id === id ? next : item) };
}

export { CloudProvider as DemoStoreProvider, useCloudStore as useDemoStore } from "./cloud-store";
