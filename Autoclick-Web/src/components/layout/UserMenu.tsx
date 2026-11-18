"use client";
import { Avatar } from "../ui/Avatar";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import Link from "next/link";
import { useApiActivity } from "../../lib/api-activity";
import { logout } from "../../lib/cloud-auth";
import { ChevronDown, LogOut, Settings, UserRound } from "lucide-react";
import { useDemoStore } from "../../lib/demo-store";
import { roleLabels } from "../../lib/role-labels";

export function UserMenu() {
  const busy = useApiActivity().pending > 0;
  const { user, role, organization } = useDemoStore();
  const canOpenSettings = role === "ORGANIZATION_OWNER";
  const profileHref = role === "AUTOCLICK_ADMIN" ? "/admin/profile" : "/dashboard/profile";

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button className="portal-userbtn" type="button" aria-label={`Cuenta de ${user.name}`}>
          <Avatar user={user} />
          <span className="portal-userbtn__meta">
            <strong>{user.name}</strong>
            <small>{roleLabels[role]}</small>
          </span>
          <ChevronDown size={15} aria-hidden="true" />
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content className="dash-menu" align="end" sideOffset={10} collisionPadding={12}>
          <div className="dash-menu__head">
            <Avatar user={user} className="portal-avatar portal-avatar--lg" />
            <div>
              <strong>{user.name}</strong>
              <small>{user.email}</small>
            </div>
          </div>
          <div className="dash-menu__sep" />
          <DropdownMenu.Item asChild>
            <Link className="dash-menu__item" href={profileHref}>
              <UserRound size={15} aria-hidden="true" /> Mi perfil
            </Link>
          </DropdownMenu.Item>
          {canOpenSettings && (
            <DropdownMenu.Item asChild>
              <Link className="dash-menu__item" href="/dashboard/settings">
                <Settings size={15} aria-hidden="true" /> Configuración
              </Link>
            </DropdownMenu.Item>
          )}
          {organization && (
            <>
              <div className="dash-menu__sep" />
              <p className="dash-menu__note">
                Organización activa
                <b>{organization.name}</b>
              </p>
            </>
          )}
          <div className="dash-menu__sep" />
          <DropdownMenu.Item asChild>
            <button className="dash-menu__item dash-menu__item--danger" type="button" disabled={busy} onClick={() => void logout().catch(() => {})}>
              <LogOut size={15} aria-hidden="true" /> Cerrar sesión
            </button>
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
