"use client";

import { motion } from "framer-motion";
import { ArrowRight, FileSpreadsheet, FolderLock, Globe2, MonitorCheck, MousePointer2, ShieldCheck, Users, Zap } from "lucide-react";
import { Reveal, RevealItem } from "../ui/Reveal";
import { SectionHeading } from "../ui/SectionHeading";
import { SectionConnector } from "../ui/SectionConnector";
import { easeOutExpo } from "../../lib/motion";

export function Faq() {
  return <section className="section-wrap faq-section" id="faq" aria-labelledby="faq-title">
    <SectionConnector height={28} />
    <SectionHeading id="faq-title" title="Lo importante, sin letra chica." accentWord="importante" description="Respuestas claras para entender cómo AutoClick se integra a tu operación." />

    <Reveal as="div" stagger className="faq-grid">
      <RevealItem as="div" className="faq-card faq-card--tools">
        <div className="faq-hub" aria-hidden="true">
          <svg className="faq-hub__lines" viewBox="0 0 100 100">
            <path d="M50 50 L20 22" /><path d="M50 50 L80 22" /><path d="M50 50 L50 88" />
          </svg>
          <span className="faq-hub__node faq-hub__node--1"><Globe2 size={13} /></span>
          <span className="faq-hub__node faq-hub__node--2"><FileSpreadsheet size={13} /></span>
          <span className="faq-hub__node faq-hub__node--3"><MousePointer2 size={13} /></span>
          <span className="faq-hub__core"><Zap size={15} /></span>
        </div>
        <div>
          <h3>¿AutoClick reemplaza nuestras herramientas?</h3>
          <p>No necesariamente. Conecta tareas entre Desktop, web, Excel y archivos para que tu equipo trabaje con lo que ya conoce.</p>
        </div>
      </RevealItem>

      <RevealItem as="div" className="faq-card faq-card--exec">
        <div className="faq-monitor" aria-hidden="true">
          <span className="faq-monitor__screen"><MonitorCheck size={17} /></span>
          <span className="faq-monitor__flow" />
          <span className="faq-monitor__lock"><FolderLock size={15} /></span>
        </div>
        <h3>¿Dónde se ejecutan los flujos?</h3>
        <p>La ejecución es local, cerca de tus herramientas y datos. La gestión web ayuda a ordenar el trabajo y sus permisos.</p>
      </RevealItem>

      <RevealItem as="div" className="faq-card faq-card--security">
        <div className="faq-security-row" aria-hidden="true">
          <span><ShieldCheck size={15} /></span>
          <span><Users size={15} /></span>
          <span><MonitorCheck size={15} /></span>
        </div>
        <h3>¿Cómo se protegen los procesos?</h3>
        <p>Cada organización define sus permisos y puede revisar la actividad de sus flujos desde un espacio centralizado.</p>
      </RevealItem>

      <RevealItem as="div" className="faq-card faq-card--start">
        <div className="faq-steps" aria-hidden="true">
          <span className="faq-steps__dot">1</span>
          <span className="faq-steps__line faq-steps__line--done" />
          <span className="faq-steps__dot">2</span>
          <span className="faq-steps__line" />
          <span className="faq-steps__dot">3</span>
        </div>
        <h3>¿Cómo empezamos?</h3>
        <p>Contanos qué proceso querés ordenar y coordinamos un primer alcance para AutoClick Business.</p>
        <motion.a
          className="text-link faq-link"
          href="#precios"
          whileHover={{ y: -1 }}
          transition={{ duration: 0.15, ease: easeOutExpo }}
        >
          Conocé AutoClick Business <ArrowRight size={15} />
        </motion.a>
      </RevealItem>
    </Reveal>
  </section>;
}
