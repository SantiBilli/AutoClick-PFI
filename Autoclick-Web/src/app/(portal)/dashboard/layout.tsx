import type { ReactNode } from "react";
import { PortalShell } from "../../../components/layout/PortalShell";
import { PortalRouteGuard } from "../../../components/portal/PortalRouteGuard";

export default function DashboardLayout({ children }: { children: ReactNode }) { return <PortalShell><PortalRouteGuard section="dashboard">{children}</PortalRouteGuard></PortalShell>; }
