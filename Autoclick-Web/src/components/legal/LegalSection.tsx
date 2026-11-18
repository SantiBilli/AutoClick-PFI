import type { ReactNode } from "react";
import { Reveal } from "../ui/Reveal";

export function LegalSection({
  id,
  title,
  tint = false,
  children,
}: {
  id: string;
  title: string;
  tint?: boolean;
  children: ReactNode;
}) {
  return (
    <Reveal as="section" id={id} className={`legal-section ${tint ? "legal-section--tint" : ""}`.trim()}>
      <h2>{title}</h2>
      {children}
    </Reveal>
  );
}
