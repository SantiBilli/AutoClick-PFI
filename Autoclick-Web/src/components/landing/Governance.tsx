"use client";

import { motion } from "framer-motion";
import { CheckCircle2, Eye, KeyRound, MapPin, Users } from "lucide-react";
import { SectionHeading } from "../ui/SectionHeading";
import { SectionConnector } from "../ui/SectionConnector";
import { easeOutExpo } from "../../lib/motion";

const steps = [
  [Users, "Usuario identificado", "Responsable y área asignados.", 0.3],
  [KeyRound, "Permiso validado", "Alcance verificado antes de ejecutar.", 1.5],
  [Eye, "Actividad registrada", "Cada evento queda asociado al flujo.", 2.7],
] as const;

const fadeScale = (delay: number) => ({
  hidden: { opacity: 0, scale: 0.6 },
  visible: { opacity: 1, scale: 1, transition: { duration: 0.4, delay, ease: easeOutExpo } },
});
const fadeUpSmall = (delay: number) => ({
  hidden: { opacity: 0, y: 8 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.4, delay, ease: easeOutExpo } },
});
const drawLine = (delay: number) => ({
  hidden: { scaleY: 0 },
  visible: { scaleY: 1, transition: { duration: 0.4, delay, ease: easeOutExpo } },
});
const badgePop = (delay: number) => ({
  hidden: { opacity: 0, scale: 0.9 },
  visible: { opacity: 1, scale: 1, transition: { duration: 0.4, delay, ease: easeOutExpo } },
});

export function Governance() {
  return <section className="governance-band" id="seguridad" aria-labelledby="governance-title">
    <div className="section-wrap">
      <SectionConnector height={28} />
      <div className="governance-layout">
        <div className="governance-copy">
          <SectionHeading
            id="governance-title"
            title="Automatizar también es decidir quién puede hacer qué."
            accentWord="decidir"
            description="Antes de ejecutar, AutoClick identifica al responsable, valida sus permisos y registra cada acción para mantener el control del proceso."
          />
        </div>

        <motion.div className="gov-sequence" initial="hidden" whileInView="visible" viewport={{ once: true, margin: "-80px" }}>
          {steps.map(([Icon, title, text, delay], index) => <div className="gov-step" key={title}>
            <span className="gov-step__icon-slot">
              {index > 0 && <motion.span className="gov-step__wire" variants={drawLine(delay - 0.4)} />}
              <motion.span className="gov-step__icon" variants={fadeScale(delay)}>
                <Icon size={17} />
              </motion.span>
            </span>
            <motion.span className="gov-step__body" variants={fadeUpSmall(delay + 0.05)}>
              <strong>{title}</strong><small>{text}</small>
            </motion.span>
          </div>)}

          <div className="gov-final">
            <motion.span className="gov-final__wire" variants={drawLine(3.5)} />
            <motion.span className="gov-final__badge" variants={badgePop(3.9)}>
              <CheckCircle2 size={15} /> Flujo aprobado
            </motion.span>
            <motion.span className="gov-final__tag" variants={fadeUpSmall(4.3)}>
              <MapPin size={13} /> Ejecución local
            </motion.span>
          </div>
        </motion.div>
      </div>
    </div>
  </section>;
}
