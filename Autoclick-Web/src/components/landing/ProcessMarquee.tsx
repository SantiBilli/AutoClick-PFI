import {
  BarChart3,
  ClipboardCheck,
  FileCheck2,
  FileSpreadsheet,
  FolderSync,
  Globe2,
  Layers,
  Laptop,
  ReceiptText,
  ShieldCheck,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

const processes = [
  [ReceiptText, "Conciliación de comprobantes"],
  [FileCheck2, "Descargar facturas"],
  [FileSpreadsheet, "Actualizar Excel"],
  [ClipboardCheck, "Validar información"],
  [BarChart3, "Generar reportes"],
  [Layers, "Clasificar documentos"],
  [Globe2, "Automatizar tareas web"],
  [Laptop, "Ejecutar procesos de Desktop"],
  [FolderSync, "Consolidar archivos"],
  [ShieldCheck, "Auditar resultados"],
] as const;

function Pill({ icon: Icon, label, tint }: { icon: LucideIcon; label: string; tint: boolean }) {
  return (
    <span className={`marquee__pill ${tint ? "marquee__pill--tint" : ""}`.trim()}>
      <Icon size={15} aria-hidden="true" />
      {label}
    </span>
  );
}

export function ProcessMarquee() {
  return (
    <div className="marquee-wrap">
      <div className="marquee" role="group" aria-label="Ejemplos de procesos que podés automatizar con AutoClick">
        <div className="marquee__track" aria-hidden="true">
          {[0, 1].map((copy) => (
            <div className="marquee__set" key={copy}>
              {processes.map(([Icon, label], index) => (
                <Pill icon={Icon} label={label} tint={index % 3 === 0} key={`${copy}-${label}`} />
              ))}
            </div>
          ))}
        </div>
        <span className="sr-only">{processes.map(([, label]) => label).join(", ")}</span>
      </div>
    </div>
  );
}
