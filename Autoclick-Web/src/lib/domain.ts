export type DemoRole = "AUTOCLICK_ADMIN" | "ORGANIZATION_OWNER" | "AREA_ADMIN" | "AREA_MEMBER";
export type UserStatus = "active" | "inactive";
export type OrganizationStatus = "active" | "inactive";
export type AreaStatus = "active" | "inactive";
export type OrganizationMembershipRole = "AUTOCLICK_ADMIN" | "ORGANIZATION_OWNER" | "ORGANIZATION_MEMBER";
export type AreaMembershipRole = "AREA_ADMIN" | "AREA_MEMBER";
export type MembershipStatus = "active" | "inactive" | "expired";
export type DemoDataState = "ready" | "loading" | "error";

export interface User { id: string; name: string; email: string; status: UserStatus; avatarInitials: string; avatarUrl?: string; }
export interface Organization { id: string; name: string; status: OrganizationStatus; plan: "PROFESIONAL" | "EMPRESARIAL"; createdAt: string; startsAt: string; endsAt: string | null; monthlyTokenLimit: number; }
export interface OrganizationMembership { id: string; userId: string; organizationId: string; role: OrganizationMembershipRole; status: MembershipStatus; startsAt: string; endsAt: string | null; }
export interface Area { id: string; organizationId: string; name: string; status: AreaStatus; tokenLimit: number; createdAt: string; }
export interface AreaMembership { id: string; userId: string; areaId: string; role: AreaMembershipRole; status: MembershipStatus; }
export interface TokenUsage { id: string; organizationId: string; areaId: string; userId: string; tokensUsed: number; period: string; }
