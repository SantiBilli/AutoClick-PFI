"use client";
import { PageIntro } from "../../../../components/ui/PageHeader";
import { ProfileView } from "../../../../components/portal/ProfileView";

export default function AdminProfilePage() {
  return (
    <div className="dash-stack">
      <PageIntro description="Los datos de tu cuenta de administración de AutoClick." />
      <ProfileView />
    </div>
  );
}
