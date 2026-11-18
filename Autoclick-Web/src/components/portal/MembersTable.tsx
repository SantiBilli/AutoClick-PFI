"use client";
import { Avatar } from "../ui/Avatar";
import { useMemo, useState } from "react";
import { motion } from "framer-motion";
import { UserPlus, UserRoundX } from "lucide-react";
import { useDemoStore } from "../../lib/demo-store";
import { areaMembershipRoleLabels } from "../../lib/role-labels";
import { Button } from "../ui/Button";
import { Badge } from "../ui/Badge";
import { Panel } from "../ui/Panel";
import { revealItem } from "../../lib/motion";
import { ConfirmDialog } from "../ui/ConfirmDialog";
import { DataTable } from "./DataTable";
import { AddMemberDialog } from "./AddMemberDialog";

const COLUMNS = [
  { key: "person", header: "Persona" },
  { key: "area", header: "Área" },
  { key: "role", header: "Rol" },
  { key: "action", header: "Acción" },
];

export interface MembersTableFilter {
  search: string;
  areaId: string;
  role: string;
}

export function MembersTable({ areaId, filter }: { areaId?: string; filter?: MembersTableFilter }) {
  const { users, user, visibleAreaMemberships, visibleAreas, areaMemberships, role, removeAreaMember } = useDemoStore();
  const [open, setOpen] = useState(false);
  const [pendingRemoval, setPendingRemoval] = useState<string | null>(null);
  const selectedArea = areaId ? visibleAreas.find((item) => item.id === areaId) : undefined;
  const canManage = (role === "ORGANIZATION_OWNER" || role === "AUTOCLICK_ADMIN") || (role === "AREA_ADMIN" && !!areaId && areaMemberships.some((item) => item.userId === user.id && item.areaId === areaId && item.role === "AREA_ADMIN" && item.status === "active"));

  const rows = useMemo(() => {
    const base = visibleAreaMemberships.filter((item) => !areaId || item.areaId === areaId);
    if (!filter) return base;
    const query = filter.search.trim().toLowerCase();
    return base.filter((membership) => {
      const person = users.find((item) => item.id === membership.userId);
      const matchesSearch = !query || Boolean(person?.name.toLowerCase().includes(query)) || Boolean(person?.email.toLowerCase().includes(query));
      const matchesArea = !filter.areaId || membership.areaId === filter.areaId;
      const matchesRole = !filter.role || membership.role === filter.role;
      return matchesSearch && matchesArea && matchesRole;
    });
  }, [visibleAreaMemberships, areaId, filter, users]);

  const removalTarget = pendingRemoval ? rows.find((item) => item.id === pendingRemoval) : undefined;
  const removalPerson = removalTarget ? users.find((item) => item.id === removalTarget.userId) : undefined;

  return (
    <>
      <Panel className="portal-card" selfReveal>
        <div className="portal-card__heading">
          <div><p className="dash-eyebrow">Directorio</p><h2>{selectedArea ? `Miembros de ${selectedArea.name}` : "Miembros de las áreas"}</h2></div>
          {canManage && areaId ? (
            <Button onClick={() => setOpen(true)}><UserPlus size={16} aria-hidden="true" /> Agregar miembro</Button>
          ) : (
            <Badge tone="slate">{rows.length} {rows.length === 1 ? "persona" : "personas"}</Badge>
          )}
        </div>
        <DataTable columns={COLUMNS} isEmpty={rows.length === 0} empty="Ningún usuario coincide con los filtros aplicados.">
          {rows.map((membership) => {
            const person = users.find((item) => item.id === membership.userId);
            const area = visibleAreas.find((item) => item.id === membership.areaId);
            return (
              <motion.tr key={membership.id} variants={revealItem}>
                <td><span className="table-primary"><Avatar user={person} className="avatar" /><span><strong>{person?.name}</strong><small>{person?.email}</small></span></span></td>
                <td>{area && <Badge tone="blue">{area.name}</Badge>}</td>
                <td><span className="ui-badge ui-badge--slate">{areaMembershipRoleLabels[membership.role]}</span></td>
                <td>
                  {canManage && membership.userId !== user.id ? (
                    <button className="table-action table-button" type="button" onClick={() => setPendingRemoval(membership.id)}>
                      <UserRoundX size={14} aria-hidden="true" /> Quitar
                    </button>
                  ) : (
                    <span className="portal-muted">Solo lectura</span>
                  )}
                </td>
              </motion.tr>
            );
          })}
        </DataTable>
      </Panel>
      <AddMemberDialog areaId={areaId ?? ""} open={open} onClose={() => setOpen(false)} />
      <ConfirmDialog
        open={!!pendingRemoval}
        title="Quitar miembro del área"
        description={removalPerson ? `${removalPerson.name} perderá el acceso a esta área. Esta acción no se puede deshacer.` : undefined}
        confirmLabel="Quitar"
        tone="danger"
        onConfirm={async () => { if (pendingRemoval && !(await removeAreaMember(pendingRemoval).catch(() => false))) return; setPendingRemoval(null); }}
        onClose={() => setPendingRemoval(null)}
      />
    </>
  );
}
