"use client";
import { useState } from "react";
import { Plus } from "lucide-react";
import { Button } from "../../../../components/ui/Button";
import { EmptyState } from "../../../../components/ui/EmptyState";
import { PageIntro } from "../../../../components/ui/PageHeader";
import { RobotHelper } from "../../../../components/ui/RobotHelper";
import { AreaTable } from "../../../../components/portal/AreaTable";
import { AddAreaDialog } from "../../../../components/portal/AddAreaDialog";
import { useDemoStore } from "../../../../lib/demo-store";

export default function AreasPage() {
  const { visibleAreas, role, organization } = useDemoStore();
  const [open, setOpen] = useState(false);
  const canCreate = (role === "ORGANIZATION_OWNER" || role === "AUTOCLICK_ADMIN") && !!organization;

  return (
    <div className="dash-stack">
      <PageIntro
        description={canCreate ? "Administrá equipos, miembros y límites de tokens por área." : "Tus áreas asignadas y su uso de tokens."}
        actions={canCreate && <Button onClick={() => setOpen(true)}><Plus size={17} aria-hidden="true" /> Agregar área</Button>}
      />
      {visibleAreas.length ? (
        <AreaTable />
      ) : (
        <EmptyState
          title="Sin áreas asignadas"
          description="No hay áreas disponibles para este contexto."
          icon={<RobotHelper pose="explaining" size="sm" float={false} />}
        />
      )}
      {canCreate && <AddAreaDialog open={open} onClose={() => setOpen(false)} />}
    </div>
  );
}
