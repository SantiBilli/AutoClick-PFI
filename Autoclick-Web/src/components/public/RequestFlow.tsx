"use client";

import { motion, useReducedMotion } from "framer-motion";
import { FolderKanban, Inbox, Laptop, MessagesSquare, Rocket, ShieldCheck } from "lucide-react";
import { RequestMailLink } from "./RequestForm";
import { easeOutExpo } from "../../lib/motion";

const MOMENTS = [
  {
    icon: Inbox,
    title: "Revisamos tu caso",
    body: "Leemos la solicitud y preparamos preguntas concretas sobre el proceso que nos contaste.",
  },
  {
    icon: MessagesSquare,
    title: "Conversamos por videollamada",
    body: "Te mostramos el flujo funcionando y estimamos el consumo de tokens de tu equipo.",
  },
  {
    icon: Rocket,
    title: "Activamos tu organización",
    body: "Creamos las áreas, cargamos a las personas y habilitamos AutoClick Desktop.",
  },
];

const GUARANTEES = [
  { icon: ShieldCheck, label: "Ejecución local, tus datos no salen de tu entorno" },
  { icon: FolderKanban, label: "Áreas, roles y límites de tokens por equipo" },
  { icon: Laptop, label: "AutoClick Desktop para cada persona habilitada" },
];

export function RequestFlow() {
  const reduceMotion = useReducedMotion();

  return (
    <section className="request-flow section-wrap" aria-labelledby="request-flow-title">
      <h2 id="request-flow-title">Qué pasa después de enviarla</h2>

      <ol className="request-timeline">
        {/* La línea se dibuja al entrar en pantalla: marca el orden de los tres momentos. */}
        <motion.span
          className="request-timeline__rail"
          aria-hidden="true"
          initial={reduceMotion ? false : { scaleX: 0 }}
          whileInView={{ scaleX: 1 }}
          viewport={{ once: true, margin: "-80px" }}
          transition={{ duration: 0.9, ease: easeOutExpo }}
        />
        {MOMENTS.map((moment, index) => {
          const Icon = moment.icon;
          return (
            <motion.li
              key={moment.title}
              className="request-moment"
              initial={reduceMotion ? false : { opacity: 0, y: 22 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: "-60px" }}
              transition={{ duration: 0.55, delay: 0.15 + index * 0.12, ease: easeOutExpo }}
            >
              <span className="request-moment__node">
                <Icon size={19} aria-hidden="true" />
              </span>
              <h3>{moment.title}</h3>
              <p>{moment.body}</p>
            </motion.li>
          );
        })}
      </ol>
    </section>
  );
}

export function RequestContact() {
  const reduceMotion = useReducedMotion();

  return (
    <section className="section-wrap request-contact-wrap" aria-labelledby="request-contact-title">
      <motion.div
        className="request-contact"
        initial={reduceMotion ? false : { opacity: 0, y: 24 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true, margin: "-80px" }}
        transition={{ duration: 0.6, ease: easeOutExpo }}
      >
        <div className="request-contact__copy">
          <h2 id="request-contact-title">¿Preferís escribirnos?</h2>
          <p>Contanos el proceso por correo y seguimos la conversación desde ahí.</p>
          <RequestMailLink />
        </div>
        <ul className="request-guarantees">
          {GUARANTEES.map((item, index) => {
            const Icon = item.icon;
            return (
              <motion.li
                key={item.label}
                initial={reduceMotion ? false : { opacity: 0, x: 14 }}
                whileInView={{ opacity: 1, x: 0 }}
                viewport={{ once: true }}
                transition={{ duration: 0.45, delay: 0.1 + index * 0.08, ease: easeOutExpo }}
              >
                <Icon size={17} aria-hidden="true" />
                {item.label}
              </motion.li>
            );
          })}
        </ul>
      </motion.div>
    </section>
  );
}
