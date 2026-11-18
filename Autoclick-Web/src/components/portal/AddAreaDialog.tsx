"use client";
import { useState } from "react";
import { Modal } from "../ui/Modal";
import { Button } from "../ui/Button";
import { useDemoStore } from "../../lib/demo-store";

export function AddAreaDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { addArea } = useDemoStore();
  const [name, setName] = useState("");

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!name.trim()) return;
    if (!(await addArea({ name: name.trim() }).catch(() => false))) return;
    setName("");
    onClose();
  };

  return (
    <Modal open={open} title="Agregar área" onClose={onClose}>
      <form className="auth-form" onSubmit={submit}>
        <label className="form-field" htmlFor="area-name">
          Nombre del área
          <input id="area-name" value={name} onChange={(event) => setName(event.target.value)} required />
        </label>
        <div className="dialog-actions">
          <Button type="button" variant="ghost" onClick={onClose}>Cancelar</Button>
          <Button type="submit">Agregar área</Button>
        </div>
      </form>
    </Modal>
  );
}
