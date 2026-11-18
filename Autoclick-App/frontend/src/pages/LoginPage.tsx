import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { AnimatePresence, motion, MotionConfig } from 'framer-motion';
import { useAuth } from '@/auth/AuthProvider';
import { DesktopAccessError } from '@/cloud/client';
import { Alert } from '@/components/Alert';
import { Button } from '@/components/Button';
import { Input } from '@/components/Input';
import { LogoMark } from '@/components/LogoMark';
import { Mascot } from '@/components/Mascot';
import { fadeUp, staggerContainer } from '@/lib/motion';

const authMessages: Record<string, string> = {
  NotAuthorizedException: 'El correo o la contraseña son incorrectos.',
  UserNotConfirmedException: 'La cuenta todavía no está confirmada.',
  UserNotFoundException: 'El correo o la contraseña son incorrectos.',
  InvalidPasswordException: 'La nueva contraseña no cumple los requisitos de seguridad.',
  LimitExceededException:
    'Se alcanzó el límite de intentos. Esperá unos minutos y volvé a intentar.',
  NetworkError: 'No se pudo conectar con el servicio de autenticación.',
};

export function safeMessage(error: unknown) {
  if (error instanceof DesktopAccessError) return error.message;
  const name = error instanceof Error ? error.name : '';
  return authMessages[name] ?? 'No se pudo iniciar sesión. Intentá nuevamente.';
}

export function LoginPage() {
  const auth = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [remember, setRemember] = useState(false);
  const [step, setStep] = useState<'credentials' | 'new-password'>('credentials');
  const [newPassword, setNewPassword] = useState('');
  const [newPasswordConfirmation, setNewPasswordConfirmation] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setError(null);

    try {
      const outcome = await auth.signIn(email.trim(), password, remember);
      if (outcome === 'new-password-required') {
        setPassword('');
        setStep('new-password');
        return;
      }
      navigate('/explorer', { replace: true });
    } catch (caught) {
      setError(safeMessage(caught));
    } finally {
      setPending(false);
    }
  }

  async function submitNewPassword(event: FormEvent) {
    event.preventDefault();
    setError(null);
    if (newPassword !== newPasswordConfirmation) {
      setError('Las contraseñas nuevas no coinciden.');
      return;
    }

    setPending(true);
    try {
      await auth.confirmNewPassword(newPassword);
      navigate('/explorer', { replace: true });
    } catch (caught) {
      setError(safeMessage(caught));
    } finally {
      setPending(false);
    }
  }

  return (
    <MotionConfig reducedMotion="user">
      <main className="min-h-screen min-[960px]:grid min-[960px]:grid-cols-[minmax(360px,0.9fr)_minmax(520px,1.1fr)]">
        <section className="relative hidden flex-col justify-between overflow-hidden bg-grid-glow p-[64px] text-white min-[960px]:flex">
          <div className="pointer-events-none absolute inset-0 bg-noise" />
          <motion.div
            animate={{ opacity: 1, y: 0 }}
            className="relative flex items-center gap-2.5 text-[17px] font-extrabold"
            initial={{ opacity: 0, y: -10 }}
            transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}>
            <LogoMark size={34} variant="dark" />
            AutoClick
          </motion.div>

          <div className="relative">
            <motion.span
              animate={{ opacity: 1, y: 0 }}
              className="mb-4 inline-block text-[12px] font-extrabold tracking-[0.14em] text-sky-300"
              initial={{ opacity: 0, y: 10 }}
              transition={{ duration: 0.5, delay: 0.1, ease: [0.16, 1, 0.3, 1] }}>
              AUTOMATIZACIÓN DE ESCRITORIO
            </motion.span>
            <motion.h1
              animate={{ opacity: 1, y: 0 }}
              className="my-0 max-w-[650px] text-[clamp(36px,4vw,58px)] leading-[1.05] font-bold tracking-[-0.04em]"
              initial={{ opacity: 0, y: 16 }}
              transition={{ duration: 0.6, delay: 0.18, ease: [0.16, 1, 0.3, 1] }}>
              Diseñá procesos claros.{' '}
              <span className="text-gradient-blue">Ejecutalos con control.</span>
            </motion.h1>
          </div>

          <motion.div
            animate={{ opacity: 1, y: 0 }}
            className="relative flex items-end justify-between"
            initial={{ opacity: 0, y: 20 }}
            transition={{ duration: 0.6, delay: 0.3, ease: [0.16, 1, 0.3, 1] }}>
            <p className="m-0 max-w-xs text-[13px] leading-5 text-white/60">
              Armá bots locales bloque por bloque, validalos y ejecutalos con visibilidad total del
              proceso.
            </p>
            <Mascot
              className="drop-shadow-[0_18px_30px_rgba(0,0,0,0.4)]"
              decorative={false}
              size={130}
            />
          </motion.div>
        </section>

        <section className="relative flex min-h-screen items-center justify-center bg-app-canvas p-6 min-[480px]:p-10 min-[960px]:min-h-0">
          <motion.form
            animate="show"
            className="grid w-full max-w-[420px] gap-3"
            initial="hidden"
            onSubmit={step === 'credentials' ? submit : submitNewPassword}
            variants={staggerContainer(0.05)}>
            <motion.p
              className="m-0 flex items-center gap-2 text-[32px] font-extrabold text-primary"
              variants={fadeUp}>
              <LogoMark size={64} variant="light" />
              AutoClick
            </motion.p>
            <AnimatePresence initial={false} mode="wait">
              {step === 'credentials' ? (
                <motion.div
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: -12 }}
                  initial={{ opacity: 0, x: 12 }}
                  key="credentials"
                  transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}>
                  <h2 className="mt-2 mb-0 text-[30px] font-bold">Ingresá a AutoClick</h2>
                  <p className="mt-0 mb-5 text-text-muted">
                    Accedé a tus automatizaciones locales.
                  </p>
                  <div className="grid gap-3">
                    <div>
                      <label className="mb-1.5 block text-[13px] font-bold" htmlFor="email">
                        Correo
                      </label>
                      <Input
                        id="email"
                        type="email"
                        autoComplete="email"
                        required
                        value={email}
                        onChange={(event) => setEmail(event.target.value)}
                      />
                    </div>
                    <div>
                      <label className="mb-1.5 block text-[13px] font-bold" htmlFor="password">
                        Contraseña
                      </label>
                      <Input
                        id="password"
                        type="password"
                        autoComplete="current-password"
                        required
                        value={password}
                        onChange={(event) => setPassword(event.target.value)}
                      />
                    </div>
                    <label className="flex cursor-pointer items-center gap-2 text-text-muted">
                      <input
                        type="checkbox"
                        checked={remember}
                        onChange={(event) => setRemember(event.target.checked)}
                        className="size-4 accent-primary"
                      />
                      Recordarme
                    </label>
                  </div>
                </motion.div>
              ) : (
                <motion.div
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: -12 }}
                  initial={{ opacity: 0, x: 12 }}
                  key="new-password"
                  transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}>
                  <h2 className="mt-2 mb-0 text-[30px] font-bold">Creá una contraseña nueva</h2>
                  <p className="mt-0 mb-5 leading-5 text-text-muted">
                    Es tu primer ingreso. Usá al menos 10 caracteres, una mayúscula, una minúscula y
                    un número.
                  </p>
                  <div className="grid gap-3">
                    <div>
                      <label className="mb-1.5 block text-[13px] font-bold" htmlFor="new-password">
                        Nueva contraseña
                      </label>
                      <Input
                        id="new-password"
                        type="password"
                        autoComplete="new-password"
                        minLength={10}
                        required
                        value={newPassword}
                        onChange={(event) => setNewPassword(event.target.value)}
                      />
                    </div>
                    <div>
                      <label
                        className="mb-1.5 block text-[13px] font-bold"
                        htmlFor="new-password-confirmation">
                        Repetir nueva contraseña
                      </label>
                      <Input
                        id="new-password-confirmation"
                        type="password"
                        autoComplete="new-password"
                        minLength={10}
                        required
                        value={newPasswordConfirmation}
                        onChange={(event) => setNewPasswordConfirmation(event.target.value)}
                      />
                    </div>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
            <AnimatePresence>{error ? <Alert>{error}</Alert> : null}</AnimatePresence>
            <motion.div variants={fadeUp}>
              <Button className="shimmer-sweep w-full" disabled={pending} type="submit">
                {pending
                  ? step === 'credentials'
                    ? 'Ingresando…'
                    : 'Guardando…'
                  : step === 'credentials'
                    ? 'Ingresar'
                    : 'Guardar contraseña e ingresar'}
              </Button>
            </motion.div>
          </motion.form>
        </section>
      </main>
    </MotionConfig>
  );
}
