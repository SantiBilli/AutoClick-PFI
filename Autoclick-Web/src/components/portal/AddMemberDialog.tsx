"use client";
import { useState } from "react";
import { Modal } from "../ui/Modal";
import { Button } from "../ui/Button";
import { Select } from "../ui/Select";
import { isCurrentMembership, useDemoStore } from "../../lib/demo-store";
import type { AreaMembershipRole } from "../../lib/domain";

export function AddMemberDialog({ areaId, open, onClose }: { areaId: string; open: boolean; onClose: () => void }) {
  const { role: demoRole, organization, users, organizationMemberships, assignAreaMember } = useDemoStore();
  const candidates = users.filter((user) => user.status === "active" && organizationMemberships.some((membership) => membership.userId === user.id && membership.organizationId === organization?.id && isCurrentMembership(membership)));
  const [userId, setUserId] = useState(candidates[0]?.id ?? "");
  const selectedUserId = candidates.some(user => user.id === userId) ? userId : candidates[0]?.id ?? "";
  const [memberRole, setMemberRole] = useState<AreaMembershipRole>("AREA_MEMBER");
  const canAssignAdmin = demoRole === "ORGANIZATION_OWNER" || demoRole === "AUTOCLICK_ADMIN";
  return <Modal open={open} title="Agregar miembro al área" onClose={onClose}><form className="auth-form" onSubmit={async (event) => { event.preventDefault(); if (selectedUserId) { if (!(await assignAreaMember(selectedUserId, areaId, memberRole).catch(() => false))) return; onClose(); } }}><label className="form-field">Persona<Select searchable people={candidates} value={selectedUserId} onChange={(event) => setUserId(event.target.value)} aria-label="Persona a agregar">{candidates.map((user) => <option key={user.id} value={user.id}>{user.name} · {user.email}</option>)}</Select></label><label className="form-field">Rol por área<Select value={memberRole} onChange={(event) => setMemberRole(event.target.value as AreaMembershipRole)} aria-label="Rol del miembro"><option value="AREA_MEMBER">Miembro de área</option>{canAssignAdmin && <option value="AREA_ADMIN">Administrador de área</option>}</Select></label><div className="dialog-actions"><Button variant="ghost" onClick={onClose}>Cancelar</Button><Button type="submit" disabled={!selectedUserId}>Agregar miembro</Button></div></form></Modal>;
}
