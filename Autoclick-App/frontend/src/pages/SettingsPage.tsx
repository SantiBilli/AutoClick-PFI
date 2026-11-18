import { LogOut, Mail, ShieldCheck } from 'lucide-react';
import { motion, MotionConfig } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '@/auth/AuthProvider';
import { Button } from '@/components/Button';
import { Panel } from '@/components/Panel';
import { fadeUp, staggerContainer } from '@/lib/motion';
import { CloudContextPanel } from '@/cloud/CloudContextPanel';

export function SettingsPage() {
  const auth = useAuth();
  const navigate = useNavigate();

  if (auth.status !== 'authenticated') return null;

  async function closeSession() {
    await auth.signOut();
    navigate('/login', { replace: true });
  }

  return (
    <MotionConfig reducedMotion="user">
      <motion.div
        animate="show"
        className="mx-auto w-full max-w-[720px]"
        initial="hidden"
        variants={staggerContainer()}
      >
        <motion.div variants={fadeUp}>
          <p className="m-0 text-[11px] font-extrabold tracking-[0.14em] text-secondary uppercase">
            Preferencias
          </p>
          <h1 className="mt-1.5 mb-6 text-[clamp(26px,4vw,34px)] leading-tight font-extrabold tracking-[-0.03em]">
            Configuración
          </h1>
        </motion.div>

        <motion.div variants={fadeUp}>
          <Panel className="relative overflow-hidden p-6">
            <span
              aria-hidden="true"
              className="pointer-events-none absolute -top-8 -right-8 size-32 rounded-full bg-blue-50/70 blur-2xl"
            />
            <div className="relative flex items-start gap-4">
              <motion.div
                aria-hidden="true"
                className="pointer-events-none grid size-12 shrink-0 place-items-center rounded-panel border border-blue-100 bg-blue-50 text-primary"
              >
                <ShieldCheck className="pointer-events-none" size={22} strokeWidth={1.8} />
              </motion.div>
              <div className="min-w-0 flex-1">
                <h2 className="m-0 text-lg font-extrabold">Cuenta</h2>
                <p className="mt-1 mb-4 flex items-center gap-1.5 text-[13px] text-text-muted">
                  <span aria-hidden="true" className="pointer-events-none relative inline-flex size-2 shrink-0">
                    <motion.span
                      animate={{ scale: 2.2, opacity: 0 }}
                      className="absolute inset-0 rounded-full bg-success/60"
                      initial={{ scale: 1, opacity: 0.7 }}
                      transition={{ duration: 1.6, repeat: Infinity, ease: 'easeOut' }}
                    />
                    <span className="relative inline-flex size-2 rounded-full bg-success" />
                  </span>
                  Sesión activa en este dispositivo
                </p>
                <div className="mb-5 flex items-center gap-2 rounded-control border border-border bg-bg px-3.5 py-3 text-[13px]">
                  <Mail aria-hidden="true" className="pointer-events-none shrink-0 text-text-muted" size={16} />
                  <span className="truncate font-mono">{auth.user.username}</span>
                </div>
                <Button variant="secondary" onClick={closeSession}>
                  <LogOut aria-hidden="true" className="pointer-events-none" size={16} />
                  Cerrar sesión
                </Button>
              </div>
            </div>
          </Panel>
        </motion.div>
        <CloudContextPanel />
      </motion.div>
    </MotionConfig>
  );
}
