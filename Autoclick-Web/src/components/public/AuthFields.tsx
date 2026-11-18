"use client";

import { useId, useState } from "react";
import type { ReactNode } from "react";
import { Eye, EyeOff } from "lucide-react";

interface AuthFieldBaseProps {
  label: string;
  name: string;
  placeholder?: string;
  autoComplete?: string;
  required?: boolean;
  value?: string;
  onChange?: React.ChangeEventHandler<HTMLInputElement>;
  validate?: (value: string) => boolean;
  labelEnd?: ReactNode;
}

export function AuthField({
  label,
  name,
  type = "text",
  placeholder,
  autoComplete,
  required = true,
  value,
  onChange,
  labelEnd,
}: AuthFieldBaseProps & { type?: string }) {
  const id = useId();
  return (
    <div className="auth-field">
      <div className="auth-field__label-row">
        <label htmlFor={id}>{label}</label>
        {labelEnd}
      </div>
      <div className="auth-field__control">
        <input
          id={id}
          name={name}
          type={type}
          placeholder={placeholder}
          autoComplete={autoComplete}
          required={required}
          value={value}
          onChange={onChange}
        />
      </div>
    </div>
  );
}

export function AuthPasswordField({
  label,
  name,
  placeholder,
  autoComplete,
  required = true,
  value,
  onChange,
  labelEnd,
}: AuthFieldBaseProps) {
  const id = useId();
  const [show, setShow] = useState(false);
  return (
    <div className="auth-field">
      <div className="auth-field__label-row">
        <label htmlFor={id}>{label}</label>
        {labelEnd}
      </div>
      <div className="auth-field__control auth-field__control--password">
        <input
          id={id}
          name={name}
          type={show ? "text" : "password"}
          placeholder={placeholder}
          autoComplete={autoComplete}
          required={required}
          value={value}
          onChange={onChange}
        />
        <button
          type="button"
          className="auth-field__toggle"
          aria-label={show ? "Ocultar contraseña" : "Mostrar contraseña"}
          onClick={() => setShow((current) => !current)}
        >
          {show ? <EyeOff size={16} aria-hidden="true" /> : <Eye size={16} aria-hidden="true" />}
        </button>
      </div>
    </div>
  );
}
