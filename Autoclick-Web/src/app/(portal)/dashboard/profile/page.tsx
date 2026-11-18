"use client";
import { PageIntro } from "../../../../components/ui/PageHeader";
import { ProfileView } from "../../../../components/portal/ProfileView";

export default function DashboardProfilePage() {
  return (
    <div className="dash-stack">
      <PageIntro description="Los datos de tu cuenta y los accesos que tenés dentro de la organización." />
      <ProfileView />
    </div>
  );
}
