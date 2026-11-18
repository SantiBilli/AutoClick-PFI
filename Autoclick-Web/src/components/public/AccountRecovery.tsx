"use client";
import Link from 'next/link';
import { useEffect, useState } from 'react';
import { AuthFrame, Field } from './AuthFrame';
import { Button } from '../ui/Button';
import { verify, resend, recover, reset, authMessage } from '../../lib/cloud-auth';

export function AccountRecovery({ mode }: { mode: 'verify' | 'forgot' | 'reset' }) {
  const [email, setEmail] = useState(''); const [done, setDone] = useState(false);
  const [error, setError] = useState(''); const [notice, setNotice] = useState(''); const [busy, setBusy] = useState(false);
  useEffect(() => { setEmail(sessionStorage.getItem('autoclick-confirm-email') ?? ''); }, []);
  const copy = {
    verify: { eyebrow: 'Confirmar cuenta', title: 'Confirmá tu correo.', description: 'Ingresá el código que recibiste por correo.', button: 'Confirmar correo', success: 'Correo confirmado' },
    forgot: { eyebrow: 'Recuperar acceso', title: '¿No recordás tu contraseña?', description: 'Te ayudamos a volver a entrar sin perder el contexto de tu espacio.', button: 'Enviar código', success: 'Revisá tu correo' },
    reset: { eyebrow: 'Nueva contraseña', title: 'Elegí una contraseña segura.', description: 'Usá al menos 10 caracteres, mayúsculas, minúsculas y números.', button: 'Guardar contraseña', success: 'Contraseña actualizada' },
  }[mode];
  return <AuthFrame eyebrow={copy.eyebrow} title={copy.title} description={copy.description}>{done ? <div className="success-state"><div className="success-mark">✓</div><h2>{copy.success}</h2>{mode === 'forgot' && <p>Si la cuenta permite recuperación, recibirás un código para restablecer tu contraseña.</p>}<Link className="ui-button ui-button--primary" href={mode === 'forgot' ? '/reset-password' : '/login'}>{mode === 'forgot' ? 'Restablecer contraseña' : 'Iniciar sesión'}</Link></div> : <form className="auth-form" onSubmit={async e => {
    e.preventDefault(); const data = new FormData(e.currentTarget); setError(''); setNotice('');
    if (mode === 'reset' && (String(data.get('password')).length < 10 || data.get('password') !== data.get('confirm'))) { setError('Las contraseñas deben coincidir y tener al menos 10 caracteres.'); return; }
    setBusy(true);
    try {
      if (mode === 'verify') await verify(email, String(data.get('code')));
      if (mode === 'forgot') await recover(email);
      if (mode === 'reset') await reset(email, String(data.get('code')), String(data.get('password')));
      setDone(true);
    } catch (err) { setError(authMessage(err)); } finally { setBusy(false); }
  }}><label className="form-field">Correo electrónico<input type="email" required value={email} onChange={e => setEmail(e.target.value)} autoComplete="email" placeholder="nombre@organizacion.com" /></label>
    {mode !== 'forgot' && <Field label="Código recibido" name="code" placeholder="Código de verificación" />}
    {mode === 'reset' && <><Field label="Nueva contraseña" name="password" type="password" placeholder="Mínimo 10 caracteres" /><Field label="Repetir contraseña" name="confirm" type="password" placeholder="Volvé a escribirla" /></>}
    {error && <p className="form-error" role="alert">{error}</p>}{notice && <p className="form-note" role="status">{notice}</p>}
    <Button type="submit" disabled={busy} size="lg">{copy.button}</Button>
    {mode === 'verify' && <Button variant="ghost" disabled={busy || !email} onClick={async () => { setBusy(true); setError(''); try { await resend(email); setNotice('Te enviamos un nuevo código.'); } catch (e) { setError(authMessage(e)); } finally { setBusy(false); } }}>Reenviar código</Button>}
    <Link className="form-link centered" href="/login">Volver a iniciar sesión</Link>
  </form>}</AuthFrame>;
}
