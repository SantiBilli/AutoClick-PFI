"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { showSuccess } from "../../../lib/api-activity";
import { motion, useReducedMotion } from "framer-motion";
import { Loader2 } from "lucide-react";
import { AuthSplitFrame } from "../../../components/public/AuthSplitFrame";
import { AuthField, AuthPasswordField } from "../../../components/public/AuthFields";
import { LoginVisual } from "../../../components/public/AuthVisuals";
import { login, finishNewPassword, authMessage, cloudApi } from "../../../lib/cloud-auth";
import { staggerFast, fadeUp } from "../../../lib/motion";

export default function LoginPage() {
  const router = useRouter();
  const shouldReduceMotion = useReducedMotion();
  const [newPasswordRequired, setNewPasswordRequired] = useState(false);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [success, setSuccess] = useState(false);
  const [nudge, setNudge] = useState(0);
  const hasFocused = useRef(false);
  const [deletionStatus, setDeletionStatus] = useState('');
  useEffect(() => {
    const status = sessionStorage.getItem('autoclick-account-deletion');
    if (status === 'deleted' || status === 'deleting') {
      sessionStorage.removeItem('autoclick-account-deletion');
      setDeletionStatus(status);
      showSuccess(status === 'deleted' ? 'Cuenta eliminada correctamente.' : 'Solicitud de eliminación recibida.');
    }
  }, []);

  function handleFocusCapture() {
    if (!hasFocused.current) {
      hasFocused.current = true;
      setNudge((count) => count + 1);
    }
  }

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    if (!String(data.get("email")).includes("@") || String(data.get("password")).length < 6) {
      setError("Ingresá un correo válido y una contraseña de al menos 6 caracteres.");
      return;
    }
    setError("");
    setSubmitting(true);
    try {
      if (newPasswordRequired) await finishNewPassword(String(data.get("password")));
      else if (await login(String(data.get("email")), String(data.get("password"))) === 'new-password') {
        setNewPasswordRequired(true); setError('Elegí una nueva contraseña de al menos 10 caracteres, mayúsculas, minúsculas y números.'); return;
      }
      const profile = await cloudApi<{role: string}>('/v1/me');
      setSuccess(true); router.push(profile.role === 'AUTOCLICK_ADMIN' ? '/admin' : '/dashboard');
    } catch (e) { setError(authMessage(e)); }
    finally { setSubmitting(false); }

  }

  return (
    <AuthSplitFrame
      title="Volvé a tu espacio de trabajo."
      description="Ingresá para continuar diseñando y gestionando tus flujos."
      visual={<LoginVisual nudge={nudge} success={success} />}
    >
      {deletionStatus && <p className="account-deactivation-notice" role="status">{deletionStatus === 'deleted' ? 'Tu cuenta fue eliminada. Ya no podés iniciar sesión con esa cuenta.' : 'La eliminación está en proceso. Tu acceso ya está bloqueado y el sistema reintentará completar la eliminación automáticamente.'}</p>}
      <motion.form
        className="auth-form"
        variants={staggerFast}
        initial={shouldReduceMotion ? false : "hidden"}
        animate="visible"
        noValidate
        onSubmit={submit}
        onFocusCapture={handleFocusCapture}
      >
        <motion.div variants={fadeUp}>
          <AuthField
            label="Correo electrónico"
            name="email"
            type="email"
            placeholder="nombre@empresa.com"
            autoComplete="email"
            validate={(value) => /\S+@\S+\.\S+/.test(value)}
          />
        </motion.div>
        <motion.div variants={fadeUp}>
          <AuthPasswordField
            label="Contraseña"
            name="password"
            placeholder="Mínimo 6 caracteres"
            autoComplete="current-password"
            validate={(value) => value.length >= 6}
            labelEnd={
              <Link className="auth-forgot-link" href="/forgot-password">
                ¿Olvidaste tu contraseña?
              </Link>
            }
          />
        </motion.div>

        {error && (
          <motion.p
            className="form-error"
            role="alert"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1, x: shouldReduceMotion ? 0 : [0, -4, 4, -2, 0] }}
            transition={{ duration: 0.35 }}
          >
            {error}
          </motion.p>
        )}
        <motion.div variants={fadeUp}>
          <motion.button
            type="submit"
            className="ui-button ui-button--primary ui-button--lg auth-submit"
            disabled={submitting}
            whileHover={{ scale: 1.01, y: -1 }}
            whileTap={{ scale: 0.98 }}
            transition={{ duration: 0.15 }}
          >
            {submitting ? (
              <>
                <Loader2 className="auth-spinner" size={16} aria-hidden="true" /> Ingresando…
              </>
            ) : (
              "Iniciar sesión"
            )}
          </motion.button>
        </motion.div>
      </motion.form>
    </AuthSplitFrame>
  );
}
