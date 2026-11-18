"use client";
import { useRef, useState } from 'react';
import { Button } from '../ui/Button';
import { Modal } from '../ui/Modal';
import { AuthField } from '../public/AuthFields';
import { useCloudStore } from '../../lib/cloud-store';
import { authMessage, deleteAccount } from '../../lib/cloud-auth';

export function DeactivateAccount() {
  const { user, role } = useCloudStore();
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState('');
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);
  const submitting = useRef(false);
  const protectedAdmin = role === 'AUTOCLICK_ADMIN';
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting.current || email.trim().toLowerCase() !== user.email.toLowerCase()) return;
    submitting.current = true; setPending(true); setError('');
    try { await deleteAccount(email); }
    catch (e) { setError(authMessage(e)); }
    finally { submitting.current = false; setPending(false); }
  }
  return <section className="account-deactivation" aria-labelledby="deactivate-account-heading">
    <h3 id="deactivate-account-heading">Eliminar cuenta</h3>
    <p className="portal-muted">Se dará de baja tu cuenta y se suprimirán los datos personales asociados, previa verificación de identidad. Perderás el acceso a la web, a AutoClick Desktop y a las consultas de IA.</p>
    {protectedAdmin && <p className="portal-muted">Tu cuenta administra AutoClick. Su baja debe gestionarla otro administrador.</p>}
    <Button variant="danger" disabled={protectedAdmin} onClick={() => { setEmail(''); setError(''); setOpen(true); }}>Eliminar cuenta</Button>
    <Modal open={open} title="Confirmar eliminación de cuenta" onClose={() => { if (!pending) setOpen(false); }}>
      <form onSubmit={submit} className="account-deactivation-form">
        <p>Se eliminarán tu identidad de acceso, tu perfil y tu foto, y se cerrará esta sesión. La eliminación es irreversible. Los consumos de la organización se conservarán sin vincularlos con tu perfil. Los bots y archivos guardados en tu equipo no se borrarán. Los respaldos y registros técnicos se conservan hasta vencer sus plazos de retención.</p>
        {role === 'ORGANIZATION_OWNER' && <p>La organización y sus miembros se conservarán, pero ya no podrás administrarla. Coordiná previamente la continuidad de la administración.</p>}
        <AuthField label={`Escribí tu correo para confirmar: ${user.email}`} name="confirmationEmail" type="email" value={email} onChange={e => setEmail(e.target.value)} autoComplete="off" />
        {error && <p className="form-error" role="alert">{error}</p>}
        <div className="account-deactivation-actions">
          <Button variant="ghost" disabled={pending} onClick={() => setOpen(false)}>Cancelar</Button>
          <Button type="submit" variant="danger" disabled={pending || email.trim().toLowerCase() !== user.email.toLowerCase()}>{pending ? 'Eliminando…' : 'Confirmar eliminación'}</Button>
        </div>
      </form>
    </Modal>
  </section>;
}
