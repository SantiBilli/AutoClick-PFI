"use client";
import { useMemo, useState } from "react";
import { UserPlus } from "lucide-react";
import { Button } from "../../../../components/ui/Button";
import { PageIntro } from "../../../../components/ui/PageHeader";
import { FilterBar } from "../../../../components/ui/FilterBar";
import { MembersTable } from "../../../../components/portal/MembersTable";
import { AddOrganizationMemberDialog } from "../../../../components/portal/AddOrganizationMemberDialog";
import { useDemoStore } from "../../../../lib/demo-store";
import { areaMembershipRoleLabels } from "../../../../lib/role-labels";

export default function UsersPage() {
  const { role, organization, visibleAreas, visibleAreaMemberships } = useDemoStore();
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [areaFilter, setAreaFilter] = useState("");
  const [roleFilter, setRoleFilter] = useState("");
  const canAdd = (role === "ORGANIZATION_OWNER" || role === "AUTOCLICK_ADMIN") && !!organization;

  const filter = useMemo(() => ({ search, areaId: areaFilter, role: roleFilter }), [search, areaFilter, roleFilter]);

  return (
    <div className="dash-stack">
      <PageIntro
        description="Usuarios registrados en tu organización y las áreas donde participan."
        actions={canAdd && <Button onClick={() => setOpen(true)}><UserPlus size={16} aria-hidden="true" /> Agregar a organización</Button>}
      />
      <FilterBar
        searchValue={search}
        onSearchChange={setSearch}
        searchPlaceholder="Buscar por nombre o email"
        filters={[
          {
            id: "area",
            label: "Área",
            value: areaFilter,
            onChange: setAreaFilter,
            options: [{ value: "", label: "Todas las áreas" }, ...visibleAreas.map((area) => ({ value: area.id, label: area.name }))],
          },
          {
            id: "role",
            label: "Rol",
            value: roleFilter,
            onChange: setRoleFilter,
            options: [{ value: "", label: "Todos los roles" }, ...Object.entries(areaMembershipRoleLabels).map(([value, label]) => ({ value, label }))],
          },
        ]}
        resultCount={visibleAreaMemberships.length}
        resultLabel="usuarios en total"
      />
      <MembersTable filter={filter} />
      {canAdd && <AddOrganizationMemberDialog open={open} onClose={() => setOpen(false)} />}
    </div>
  );
}
