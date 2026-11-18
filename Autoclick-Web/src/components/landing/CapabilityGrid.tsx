"use client";

import { motion } from "framer-motion";
import { FileSpreadsheet, FolderSync, Globe2, MousePointer2, Network, Workflow } from "lucide-react";
import { Reveal, RevealItem } from "../ui/Reveal";
import { SectionHeading } from "../ui/SectionHeading";
import { SectionConnector } from "../ui/SectionConnector";
import { onSpotlightMove } from "../ui/Spotlight";

const items = [
  [MousePointer2, "Desktop", "Automatizá aplicaciones de escritorio sin perder el control del proceso."],
  [Globe2, "Web", "Diseñá recorridos web repetibles con pasos claros y observables."],
  [FileSpreadsheet, "Excel y archivos", "Transformá planillas, documentos y carpetas en entradas de un flujo."],
  [Workflow, "Decisiones guiadas", "Agregá pasos de clasificación y revisión para acelerar el trabajo del equipo."],
  [Network, "Conexiones autorizadas", "Conectá las herramientas que tu organización necesita, con permisos claros."],
  [FolderSync, "Ejecución local", "Tus automatizaciones corren cerca de tus datos y de tus herramientas."],
] as const;

const tints = ["tint-1", "tint-2", "tint-3", "tint-4", "tint-2", "tint-1"] as const;

export function CapabilityGrid() {
  return <section className="section-wrap section-funcionalidades" id="funcionalidades" aria-labelledby="capabilities-title">
    <SectionConnector height={32} />
    <SectionHeading id="capabilities-title" title="De la idea al flujo, sin saltos." accentWord="flujo" description="Todo lo necesario para convertir trabajo repetitivo en una operación trazable." />
    <Reveal as="div" stagger className="capability-grid">
      {items.map(([Icon, title, text], index) => {
        const alt = index % 2 === 1;
        return <RevealItem as="article" className={`capability-card ${tints[index % tints.length]}`} key={title} onMouseMove={onSpotlightMove}>
          <motion.span className="capability-icon" whileHover={{ scale: alt ? 1.12 : 1.18, rotate: alt ? 8 : -8 }} transition={{ type: "spring", stiffness: 320, damping: 14 }}><Icon size={21} /></motion.span>
          <h3>{title}</h3>
          <p>{text}</p>
        </RevealItem>;
      })}
    </Reveal>
  </section>;
}
