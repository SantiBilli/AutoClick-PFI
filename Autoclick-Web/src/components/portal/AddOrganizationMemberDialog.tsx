"use client";

import { useEffect, useState } from "react";
import { Modal } from "../ui/Modal";
import { Button } from "../ui/Button";
import { useDemoStore } from "../../lib/demo-store";

const EMAIL_FORMAT = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function AddOrganizationMemberDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { organization, addOrganizationMember } = useDemoStore();
  const [email, setEmail] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (open) {
      setEmail("");
      setError("");
    }
  }, [open]);

  const trimmedEmail = email.trim();
  const isPlausibleEmail = EMAIL_FORMAT.test(trimmedEmail);
  const formatHint = trimmedEmail.length > 0 && !isPlausibleEmail ? "Ingresá un email con formato válido." : "";
  const message = error || formatHint;

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!organization || !isPlausibleEmail) return;
    try { await addOrganizationMember(email.trim().toLowerCase()); onClose(); }
    catch (e) { setError(e instanceof Error ? e.message : 'No se pudo agregar a la persona.'); }
  };

  return (
    <Modal open={open} title="Agregar usuario a la organización" onClose={onClose}>
      <form className="auth-form" onSubmit={submit} noValidate>
        <label className="form-field" htmlFor="organization-member-email">
          Email del usuario
          <input id="organization-member-email" type="email" value={email} onChange={(event) => { setEmail(event.target.value); setError(""); }} placeholder="usuario@organizacion.com" required autoFocus />
        </label>
        <p className="form-note form-note--left">El email debe pertenecer a una cuenta registrada en AutoClick que todavía no esté asignada a una organización.</p>
        {message && <p className="form-error" role="alert">{message}</p>}
        <div className="dialog-actions">
          <Button type="button" variant="ghost" onClick={onClose}>Cancelar</Button>
          <Button type="submit" disabled={!isPlausibleEmail}>Agregar a organización</Button>
        </div>
      </form>
    </Modal>
  );
}
