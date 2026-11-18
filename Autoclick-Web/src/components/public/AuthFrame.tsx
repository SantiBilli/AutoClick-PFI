import Link from "next/link";
import type { ReactNode } from "react";
import { Reveal } from "../ui/Reveal";
import { BrandMark } from "../ui/BrandMark";

export function AuthFrame({ eyebrow, title, description, children }: { eyebrow: string; title: string; description: string; children: ReactNode }) {
  return <section className="auth-page"><Reveal as="div" className="auth-card"><Link className="auth-brand" href="/"><BrandMark /></Link><div className="auth-heading"><p className="eyebrow">{eyebrow}</p><h1>{title}</h1><p>{description}</p></div>{children}</Reveal></section>;
}

export function Field({ label, name, type = "text", placeholder, required = true, value, onChange, ...attributes }: { label?: string; name: string; type?: string; placeholder?: string; required?: boolean; value?: string; onChange?: React.ChangeEventHandler<HTMLInputElement> } & React.InputHTMLAttributes<HTMLInputElement>) {
  return <>{label ? <label className="form-field"><span>{label}</span><input {...attributes} name={name} type={type} placeholder={placeholder} required={required} value={value} onChange={onChange} /></label> : <input {...attributes} name={name} type={type} placeholder={placeholder} required={required} value={value} onChange={onChange} />}</>;
}
