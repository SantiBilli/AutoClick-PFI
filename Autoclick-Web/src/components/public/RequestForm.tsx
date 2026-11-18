"use client";

import Link from "next/link";
import { cloudApi, authMessage } from "../../lib/cloud-auth";
import { useId, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { ArrowRight, Loader2, Mail, ShieldCheck } from "lucide-react";
import { RobotHelper } from "../ui/RobotHelper";
import { easeOutExpo } from "../../lib/motion";

type FormValues = {
  companyName: string;
  contactName: string;
  contactEmail: string;
  estimatedUsers: string;
  useCase: string;
  notes: string;
};

type FieldName = keyof FormValues;

const EMPTY: FormValues = { companyName: "", contactName: "", contactEmail: "", estimatedUsers: "", useCase: "", notes: "" };

const REQUIRED: FieldName[] = ["companyName", "contactName", "contactEmail", "estimatedUsers", "useCase"];

function validate(values: FormValues) {
  const errors: Partial<Record<FieldName, string>> = {};
  for (const field of REQUIRED) {
    if (!values[field].trim()) errors[field] = "Este campo es obligatorio.";
  }
  const email = values.contactEmail.trim();
  if (email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) errors.contactEmail = "Ingresá un correo válido.";
  const users = values.estimatedUsers.trim();
  if (users && (!Number.isInteger(Number(users)) || Number(users) < 1)) errors.estimatedUsers = "Ingresá una cantidad entera mayor a cero.";
  return errors;
}

export function RequestForm() {
  const reduceMotion = useReducedMotion();
  const [values, setValues] = useState<FormValues>(EMPTY);
  const [errors, setErrors] = useState<Partial<Record<FieldName, string>>>({});
  const [status, setStatus] = useState<"idle" | "sending" | "sent">("idle");

  const update = (field: FieldName, value: string) => {
    setValues((current) => ({ ...current, [field]: value }));
    setErrors((current) => ({ ...current, [field]: undefined }));
  };

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const nextErrors = validate(values);
    if (Object.keys(nextErrors).length > 0) {
      setErrors(nextErrors);
      // Lleva el foco al primer campo con problema en vez de dejarlo al azar.
      const first = REQUIRED.find((field) => nextErrors[field]) ?? "contactEmail";
      document.querySelector<HTMLElement>(`[name="${first}"]`)?.focus();
      return;
    }
    setStatus("sending");
    try { await cloudApi("/v1/business-requests", "POST", { ...values, estimatedUsers: Number(values.estimatedUsers) }, true); setStatus("sent"); } catch (e) { setErrors({ contactEmail: authMessage(e) }); setStatus("idle"); }
  };

  if (status === "sent") {
    return (
      <motion.div
        className="request-card request-card--done"
        role="status"
        aria-live="polite"
        initial={reduceMotion ? false : { opacity: 0, y: 14 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, ease: easeOutExpo }}
      >
        <RobotHelper pose="success" size="md" />
        <h2>Recibimos tu solicitud</h2>
        <p>
          Quedó registrada a nombre de <strong>{values.companyName.trim()}</strong>. El contacto indicado es{" "}
          <strong>{values.contactEmail.trim()}</strong> para coordinar la primera conversación.
        </p>
        <dl className="request-recap">
          <div>
            <dt>Caso de uso</dt>
            <dd>{values.useCase.trim()}</dd>
          </div>
          <div>
            <dt>Usuarios estimados</dt>
            <dd>{values.estimatedUsers.trim()}</dd>
          </div>
        </dl>
        <div className="request-card__actions">
          <Link className="ui-button ui-button--primary ui-button--md" href="/">
            Volver al inicio <ArrowRight size={16} aria-hidden="true" />
          </Link>
          <button
            className="ui-button ui-button--ghost ui-button--md"
            type="button"
            onClick={() => {
              setValues(EMPTY);
              setStatus("idle");
            }}
          >
            Cargar otra solicitud
          </button>
        </div>
        <p className="request-note">La solicitud se guarda para que el equipo de AutoClick pueda revisarla.</p>
      </motion.div>
    );
  }

  return (
    <motion.div
      className="request-card"
      initial={reduceMotion ? false : { opacity: 0, y: 18 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.6, ease: easeOutExpo, delay: 0.1 }}
    >
      <div className="request-card__head">
        <h2>Solicitud de acceso</h2>
        <p>Respondemos con un alcance inicial y la configuración sugerida de áreas y límites.</p>
      </div>

      <form className="request-form" onSubmit={submit} noValidate>
        <div className="request-form__grid">
          <TextField label="Empresa" name="companyName" placeholder="Metalúrgica Del Plata" value={values.companyName} error={errors.companyName} onChange={update} autoComplete="organization" />
          <TextField label="Nombre de contacto" name="contactName" placeholder="Sofía Martínez" value={values.contactName} error={errors.contactName} onChange={update} autoComplete="name" />
          <TextField label="Correo de contacto" name="contactEmail" type="email" placeholder="sofia@tuempresa.com.ar" value={values.contactEmail} error={errors.contactEmail} onChange={update} autoComplete="email" />
          <TextField label="Usuarios estimados" name="estimatedUsers" type="number" inputMode="numeric" min={1} placeholder="25" value={values.estimatedUsers} error={errors.estimatedUsers} onChange={update} />
        </div>

        <TextField
          label="Caso de uso"
          name="useCase"
          placeholder="Conciliación de facturas entre el ERP y el banco"
          value={values.useCase}
          error={errors.useCase}
          onChange={update}
          hint="Un proceso concreto alcanza para empezar."
        />

        <TextareaField label="Notas" name="notes" optional placeholder="Sistemas involucrados, volumen mensual, fechas límite." value={values.notes} error={errors.notes} onChange={update} />

        <div className="request-form__foot">
          <button className="ui-button ui-button--primary ui-button--lg" type="submit" disabled={status === "sending"}>
            {status === "sending" ? (
              <>
                <Loader2 size={17} className="request-spinner" aria-hidden="true" /> Enviando
              </>
            ) : (
              <>
                Enviar solicitud <ArrowRight size={17} aria-hidden="true" />
              </>
            )}
          </button>
          <p className="request-note">
            <ShieldCheck size={14} aria-hidden="true" />
            Al enviar confirmás que leíste la <Link href="/privacidad">política de privacidad</Link>.
          </p>
        </div>
      </form>

      <p className="request-card__login">
        ¿Tu organización ya tiene AutoClick? <Link href="/login">Iniciá sesión</Link>
      </p>
    </motion.div>
  );
}

interface FieldProps {
  label: string;
  name: FieldName;
  value: string;
  error?: string;
  hint?: string;
  optional?: boolean;
  placeholder?: string;
  onChange: (name: FieldName, value: string) => void;
}

function TextField({
  label,
  name,
  value,
  error,
  hint,
  placeholder,
  onChange,
  type = "text",
  ...attributes
}: FieldProps & { type?: string } & Omit<React.InputHTMLAttributes<HTMLInputElement>, "id" | "name" | "value" | "placeholder" | "onChange">) {
  const id = useId();
  const describedBy = [error ? `${id}-error` : null, hint && !error ? `${id}-hint` : null].filter(Boolean).join(" ") || undefined;

  return (
    <div className={`request-field ${error ? "request-field--invalid" : ""}`.trim()}>
      <label htmlFor={id}>{label}</label>
      <input
        {...attributes}
        id={id}
        name={name}
        type={type}
        value={value}
        placeholder={placeholder}
        aria-invalid={Boolean(error)}
        aria-describedby={describedBy}
        onChange={(event) => onChange(name, event.target.value)}
      />
      {hint && !error && <span className="request-field__hint" id={`${id}-hint`}>{hint}</span>}
      <AnimatePresence>
        {error && (
          <motion.span
            className="request-field__error"
            id={`${id}-error`}
            role="alert"
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
          >
            {error}
          </motion.span>
        )}
      </AnimatePresence>
    </div>
  );
}

function TextareaField({ label, name, value, error, optional, placeholder, onChange }: FieldProps) {
  const id = useId();
  return (
    <div className={`request-field ${error ? "request-field--invalid" : ""}`.trim()}>
      <label htmlFor={id}>
        {label}
        {optional && <span className="request-field__optional">Opcional</span>}
      </label>
      <textarea
        id={id}
        name={name}
        rows={4}
        value={value}
        placeholder={placeholder}
        aria-invalid={Boolean(error)}
        aria-describedby={error ? `${id}-error` : undefined}
        onChange={(event) => onChange(name, event.target.value)}
      />
      {error && (
        <span className="request-field__error" id={`${id}-error`} role="alert">
          {error}
        </span>
      )}
    </div>
  );
}

/** Contacto directo para quien prefiere escribir en vez de completar el formulario. */
export function RequestMailLink() {
  return (
    <a className="request-mail" href="mailto:business@autoclick.com.ar">
      <Mail size={16} aria-hidden="true" /> business@autoclick.com.ar
    </a>
  );
}
