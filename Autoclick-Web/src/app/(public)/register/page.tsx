"use client";
import Link from "next/link";
import { register, authMessage } from "../../../lib/cloud-auth";
import { useRef, useState } from "react";
import { motion, useReducedMotion } from "framer-motion";
import { Loader2 } from "lucide-react";
import { AuthSplitFrame } from "../../../components/public/AuthSplitFrame";
import { AuthField, AuthPasswordField } from "../../../components/public/AuthFields";
import { RegisterVisual } from "../../../components/public/AuthVisuals";
import { staggerFast, fadeUp } from "../../../lib/motion";

export default function RegisterPage() {
  const shouldReduceMotion = useReducedMotion();
  const [sent, setSent] = useState(false);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [password, setPassword] = useState("");
  const [nudge, setNudge] = useState(0);
  const hasFocused = useRef(false);

  function handleFocusCapture() {
    if (!hasFocused.current) {
      hasFocused.current = true;
      setNudge((count) => count + 1);
    }
  }

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    if (String(data.get("password")).length < 10 || data.get("password") !== data.get("confirm")) {
      setError("Las contraseñas deben coincidir y tener al menos 10 caracteres.");
      return;
    }
    setError("");
    setSubmitting(true);
    try { await register(String(data.get("email")), String(data.get("password")), String(data.get("name"))); setSent(true); }
    catch (e) { setError(authMessage(e)); }
    finally { setSubmitting(false); }
  }

  return (
    <AuthSplitFrame
      eyebrow="Primer paso"
      title="Creá tu espacio en AutoClick."
      description="Empezá a transformar procesos repetitivos en flujos claros y gobernados."
      visual={<RegisterVisual nudge={nudge} success={sent} />}
    >
      {sent ? (
        <div className="success-state">
          <div className="success-mark">✓</div>
          <h2>Revisá tu correo</h2>
          <p>Enviamos un código de verificación a tu dirección. Ingresalo en el siguiente paso para activar tu cuenta.</p>
          <Link className="ui-button ui-button--primary" href="/verify-email">
            Verificar correo
          </Link>
        </div>
      ) : (
        <motion.form
          className="auth-form"
          variants={staggerFast}
          initial={shouldReduceMotion ? false : "hidden"}
          animate="visible"
          noValidate
          onSubmit={submit}
          onFocusCapture={handleFocusCapture}
        >
          <div className="form-grid">
            <motion.div variants={fadeUp}>
              <AuthField label="Nombre completo" name="name" placeholder="Sofía Martínez" autoComplete="name" validate={(value) => value.trim().length >= 2} />
            </motion.div>
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
                placeholder="Mínimo 10 caracteres"
                autoComplete="new-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                validate={(value) => value.length >= 10}
              />
            </motion.div>
            <motion.div variants={fadeUp}>
              <AuthPasswordField
                label="Repetir contraseña"
                name="confirm"
                placeholder="Volvé a escribirla"
                autoComplete="new-password"
                validate={(value) => value.length >= 10 && value === password}
              />
            </motion.div>
          </div>
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
                  <Loader2 className="auth-spinner" size={16} aria-hidden="true" /> Creando cuenta…
                </>
              ) : (
                "Crear cuenta"
              )}
            </motion.button>
          </motion.div>
          <motion.p className="form-note" variants={fadeUp}>
            Al crear tu cuenta aceptás los <Link href="/terminos">Términos</Link> y la <Link href="/privacidad">Política de Privacidad</Link>.
          </motion.p>
          <motion.p className="form-note" variants={fadeUp}>
            ¿Ya tenés una cuenta? <Link href="/login">Iniciar sesión</Link>
          </motion.p>
        </motion.form>
      )}
    </AuthSplitFrame>
  );
}
