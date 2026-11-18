"use client";

import Image from "next/image";
import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion, useInView, useReducedMotion } from "framer-motion";
import type { CSSProperties, ReactNode } from "react";
import { ArrowRight, Download, Filter, FolderCheck, Globe2, Search } from "lucide-react";
import { AnimatedCheck } from "../ui/AnimatedCheck";
import { SectionConnector } from "../ui/SectionConnector";
import { easeOutExpo } from "../../lib/motion";

const PHASE = {
  IDLE: 0,
  USER_1: 1,
  TYPING_1: 2,
  AI_1: 3,
  BLOCKS: 4,
  QUESTION: 5,
  USER_2: 6,
  TYPING_2: 7,
  FINAL: 8,
  PREVIEW: 9,
  READY: 10,
} as const;

type Phase = (typeof PHASE)[keyof typeof PHASE];

const BLOCKS = [
  { icon: Globe2, label: "Abrir web" },
  { icon: Search, label: "Buscar facturas" },
  { icon: Download, label: "Descargar archivos" },
  { icon: FolderCheck, label: "Guardar en carpeta" },
] as const;

const PREVIEW_STEPS = [
  { icon: Globe2, label: "Abrir la web" },
  { icon: Filter, label: "Filtrar pendientes" },
  { icon: Download, label: "Descargar facturas" },
  { icon: FolderCheck, label: "Guardar en carpeta" },
] as const;

const CAPSULES = [
  "Descargá las facturas pendientes.",
  "Guardalas en una carpeta.",
  "Avisame si falta algún archivo.",
  "Hacelo todos los meses.",
] as const;

const ROBOT_SRC = {
  neutral: "/mascot/AutoClick_Robot_Neutral.png",
  thinking: "/mascot/AutoClick_Robot_Explicando.png",
  success: "/mascot/AutoClick_Robot_Exito.png",
} as const;

function RobotAvatar({ className = "" }: { className?: string }) {
  return (
    <span className={`ai-flow-avatar ${className}`.trim()}>
      <Image src={ROBOT_SRC.neutral} alt="" width={72} height={72} />
    </span>
  );
}

function Bubble({ role, text }: { role: "user" | "ai"; text: string }) {
  return (
    <div className={`ai-flow-msg-row ai-flow-msg-row--${role}`}>
      {role === "ai" && <RobotAvatar />}
      <div className={`ai-flow-msg ai-flow-msg--${role}`}>{text}</div>
    </div>
  );
}

function TypingIndicator() {
  return (
    <div className="ai-flow-msg-row ai-flow-msg-row--ai">
      <RobotAvatar />
      <div className="chat-typing ai-flow-typing"><span /><span /><span /></div>
    </div>
  );
}

type Entry = { id: string; node: ReactNode };

export function AiCapabilities() {
  const sectionRef = useRef<HTMLElement>(null);
  const hasRunRef = useRef(false);
  const inView = useInView(sectionRef, { amount: 0.35, once: true });
  const shouldReduceMotion = useReducedMotion();
  const reduced = Boolean(shouldReduceMotion);

  const [phase, setPhase] = useState<Phase>(PHASE.IDLE);
  const [blocksCount, setBlocksCount] = useState(0);
  const [stepsCount, setStepsCount] = useState(0);

  useEffect(() => {
    if (!inView || hasRunRef.current) return;
    hasRunRef.current = true;

    if (reduced) {
      setPhase(PHASE.READY);
      setBlocksCount(BLOCKS.length);
      setStepsCount(PREVIEW_STEPS.length);
      return;
    }

    let cancelled = false;
    const timeouts: ReturnType<typeof setTimeout>[] = [];
    let t = 0;
    const at = (ms: number, fn: () => void) => {
      t = ms;
      timeouts.push(setTimeout(() => { if (!cancelled) fn(); }, ms));
    };

    at(2200, () => setPhase(PHASE.USER_1));
    at(t + 700, () => setPhase(PHASE.TYPING_1));
    at(t + 900, () => setPhase(PHASE.AI_1));
    at(t + 500, () => setPhase(PHASE.BLOCKS));
    BLOCKS.forEach((_, i) => at(t + 230, () => setBlocksCount(i + 1)));
    at(t + 500, () => setPhase(PHASE.QUESTION));
    at(t + 900, () => setPhase(PHASE.USER_2));
    at(t + 700, () => setPhase(PHASE.TYPING_2));
    at(t + 900, () => setPhase(PHASE.FINAL));
    at(t + 700, () => setPhase(PHASE.PREVIEW));
    at(t + 450, () => {});
    PREVIEW_STEPS.forEach((_, i) => at(t + 260, () => setStepsCount(i + 1)));
    at(t + 450, () => setPhase(PHASE.READY));

    return () => {
      cancelled = true;
      timeouts.forEach(clearTimeout);
    };
  }, [inView, reduced]);

  const pose = phase >= PHASE.READY ? "success" : phase === PHASE.TYPING_1 || phase === PHASE.TYPING_2 ? "thinking" : "neutral";
  const ready = phase >= PHASE.READY;
  const previewOpen = phase >= PHASE.PREVIEW;

  const entries: Entry[] = [];
  if (phase >= PHASE.USER_1) entries.push({ id: "u1", node: <Bubble key="u1" role="user" text="Necesito un flujo que ingrese a una web, descargue las facturas pendientes y las guarde en una carpeta." /> });
  if (phase === PHASE.TYPING_1) entries.push({ id: "t1", node: <TypingIndicator key="t1" /> });
  if (phase >= PHASE.AI_1) entries.push({
    id: "ai1", node: <div key="ai1">
      <Bubble role="ai" text="Perfecto. Preparé un primer borrador con acceso web, búsqueda de facturas, descarga y guardado local." />
      {blocksCount > 0 && (
        <div className="ai-flow-blocks">
          {BLOCKS.slice(0, blocksCount).map(({ icon: Icon, label }) => (
            <span className="ai-flow-block-chip" key={label}><Icon size={11} aria-hidden="true" /> {label}</span>
          ))}
        </div>
      )}
    </div>,
  });
  if (phase >= PHASE.QUESTION) entries.push({ id: "q", node: <Bubble key="q" role="ai" text="¿Querés descargar todas las facturas o solamente las que todavía están pendientes?" /> });
  if (phase >= PHASE.USER_2) entries.push({ id: "u2", node: <Bubble key="u2" role="user" text="Solamente las pendientes." /> });
  if (phase === PHASE.TYPING_2) entries.push({ id: "t2", node: <TypingIndicator key="t2" /> });
  if (phase >= PHASE.FINAL) entries.push({ id: "f", node: <Bubble key="f" role="ai" text="Listo. Actualicé el flujo y agregué una validación antes de descargar." /> });

  const visible = entries.slice(previewOpen ? -2 : -3);

  return <section className="ai-flow-outer" id="ia" aria-labelledby="ai-title" ref={sectionRef}>
    <SectionConnector height="clamp(26px, 3vw, 34px)" />

    <div className="ai-flow-header">
      <h2 className="ai-flow-title" id="ai-title">
        <span className="ai-flow-line-mask">
          <motion.span
            className="ai-flow-line"
            initial={reduced ? { opacity: 0 } : { y: "100%", opacity: 0 }}
            whileInView={{ y: 0, opacity: 1 }}
            viewport={{ once: true, margin: "-80px" }}
            transition={{ duration: 0.55, delay: 0.55, ease: easeOutExpo }}
          >
            Creación asistida por IA
          </motion.span>
        </span>
      </h2>

      <p className="ai-flow-tagline">
        <span className="ai-flow-line-mask">
          <motion.span
            className="ai-flow-line"
            initial={reduced ? { opacity: 0 } : { y: "100%", opacity: 0 }}
            whileInView={{ y: 0, opacity: 1 }}
            viewport={{ once: true, margin: "-80px" }}
            transition={{ duration: 0.5, delay: 0.78, ease: easeOutExpo }}
          >
            Contalo como te salga.
          </motion.span>
        </span>
        <span className="ai-flow-line-mask">
          <motion.span
            className="ai-flow-line"
            initial={reduced ? { opacity: 0 } : { y: "100%", opacity: 0 }}
            whileInView={{ y: 0, opacity: 1 }}
            viewport={{ once: true, margin: "-80px" }}
            transition={{ duration: 0.5, delay: 0.9, ease: easeOutExpo }}
          >
            <span className="ai-flow-accent-wrap">
              <span className="ai-flow-accent">ClickIA</span>
              <motion.span
                className="ai-flow-underline-bar"
                aria-hidden="true"
                initial={{ scaleX: 0 }}
                whileInView={{ scaleX: 1 }}
                viewport={{ once: true, margin: "-80px" }}
                transition={{ duration: 0.45, delay: 1.15, ease: easeOutExpo }}
              />
            </span>
            {" lo transforma en un "}
            <span className="ai-flow-accent ai-flow-accent--flujo">flujo</span>.
          </motion.span>
        </span>
      </p>

      <motion.p
        className="ai-flow-desc"
        initial={reduced ? { opacity: 0 } : { opacity: 0, y: 10 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true, margin: "-80px" }}
        transition={{ duration: 0.5, delay: 1.3, ease: easeOutExpo }}
      >
        Describí el proceso con tus palabras. ClickIA propone los bloques, completa lo que falta y te deja revisar cada paso antes de ejecutarlo.
      </motion.p>
    </div>

    <div className="ai-flow-shell">
      <div className="ai-flow-shell__bg" aria-hidden="true" />

      <div className="ai-flow-demo">
        <motion.div
          className="ai-flow-robot-stage"
          initial={reduced ? { opacity: 0 } : { opacity: 0, x: 24 }}
          whileInView={{ opacity: 1, x: 0 }}
          viewport={{ once: true, margin: "-80px" }}
          transition={{ duration: 0.55, delay: 1.75, ease: easeOutExpo }}
        >
          <div className="ai-flow-robot-scene">
            <div className="ai-flow-robot-anchor">
              <motion.div
                className="ai-flow-robot-float"
                animate={reduced ? undefined : { y: [0, -5, 0], rotate: [0, -1, 0, 1, 0] }}
                transition={{ duration: 6, repeat: Infinity, ease: "easeInOut" }}
              >
                <span className="ai-flow-robot-shadow" aria-hidden="true" />
                <div className="ai-flow-robot-pose">
                  <AnimatePresence mode="sync">
                    <motion.img
                      key={pose}
                      src={ROBOT_SRC[pose]}
                      alt={pose === "neutral" ? "Robot asistente ClickIA" : ""}
                      className="ai-flow-robot-img"
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      exit={{ opacity: 0 }}
                      transition={{ duration: 0.35, ease: easeOutExpo }}
                    />
                  </AnimatePresence>
                </div>
              </motion.div>
            </div>

            <div className="ai-flow-capsules" aria-hidden="true">
              {CAPSULES.map((text, i) => {
                const outX = i % 2 === 0 ? -14 : 14;
                const outY = i < 2 ? -14 : 14;
                return (
                  <motion.div
                    className={`ai-flow-capsule-wrap ai-flow-capsule-wrap--${i + 1}`}
                    key={text}
                    initial={reduced ? { opacity: 0 } : { opacity: 0, x: outX, y: outY }}
                    whileInView={{ opacity: 1, x: 0, y: 0 }}
                    viewport={{ once: true, margin: "-80px" }}
                    transition={{ duration: 0.5, delay: 1.95 + i * 0.15, ease: easeOutExpo }}
                  >
                    <motion.span
                      className="ai-flow-capsule"
                      animate={reduced ? undefined : { y: [0, -3, 0] }}
                      transition={{ duration: 4.5 + i * 0.4, repeat: Infinity, ease: "easeInOut", delay: 2.6 + i * 0.15 }}
                    >
                      {text}
                    </motion.span>
                  </motion.div>
                );
              })}
            </div>
          </div>
        </motion.div>

        <span
          className={`ai-flow-link ${phase === PHASE.TYPING_1 || phase === PHASE.TYPING_2 ? "is-active" : ""}`.trim()}
          aria-hidden="true"
        />

        <motion.div
          className={`ai-flow-chat ${ready ? "is-ready" : ""}`.trim()}
          initial={reduced ? { opacity: 0 } : { opacity: 0, x: -30 }}
          whileInView={{ opacity: 1, x: 0 }}
          viewport={{ once: true, margin: "-80px" }}
          transition={{ duration: 0.55, delay: 1.65, ease: easeOutExpo }}
          aria-label="Vista previa del asistente ClickIA armando un flujo"
        >
          <div className="ai-flow-chat__header">
            <RobotAvatar />
            <span className="ai-flow-chat__meta">
              <strong>ClickIA</strong>
              <span className="ai-flow-chat__status"><span className="ai-flow-chat__pulse" aria-hidden="true" /> En línea</span>
            </span>
          </div>

          <div className="ai-flow-chat__body" role="log" aria-live="polite" aria-label="Conversación de ejemplo entre un usuario y ClickIA">
            <div className={`ai-flow-messages ${previewOpen ? "is-compact" : ""}`.trim()}>
              <AnimatePresence mode="popLayout" initial={false}>
                {visible.map((entry, i) => (
                  <motion.div
                    className={`ai-flow-entry ${i === 0 && visible.length > 1 ? "is-dimmed" : ""}`.trim()}
                    layout={!reduced}
                    key={entry.id}
                    initial={reduced ? { opacity: 0 } : { opacity: 0, y: 14, scale: 0.98 }}
                    animate={{ opacity: 1, y: 0, scale: 1 }}
                    exit={reduced ? { opacity: 0 } : { opacity: 0, y: -16 }}
                    transition={{ duration: 0.38, ease: easeOutExpo }}
                  >
                    {entry.node}
                  </motion.div>
                ))}
              </AnimatePresence>
            </div>

            <div className={`ai-flow-preview-panel ${previewOpen ? "is-visible" : ""} ${ready ? "is-ready" : ""}`.trim()}>
              <div className="ai-flow-preview-panel__top">
                <span className="ui-badge ui-badge--blue">BORRADOR LISTO</span>
                <span className="ai-flow-preview-panel__name">Descarga mensual de facturas</span>
                <span className="ai-flow-preview-panel__state">
                  {ready ? <><AnimatedCheck delay={0.1} /> Listo</> : "Generando…"}
                </span>
              </div>
              <div className="ai-flow-preview-panel__steps" style={{ "--flow-progress": stepsCount / PREVIEW_STEPS.length } as CSSProperties}>
                <span className="ai-flow-preview-panel__track" aria-hidden="true"><span className="ai-flow-preview-panel__fill" /></span>
                {PREVIEW_STEPS.map(({ icon: Icon, label }, i) => (
                  <span className={`ai-flow-preview-panel__step ${i < stepsCount ? "is-active" : ""}`.trim()} key={label} title={label}>
                    <span className="ai-flow-preview-panel__icon"><Icon size={12} aria-hidden="true" /></span>
                    <span className="ai-flow-preview-panel__label">{label}</span>
                  </span>
                ))}
              </div>
              <button type="button" className="ui-button ui-button--primary ui-button--sm ai-flow-preview-panel__cta">
                Revisar flujo <ArrowRight size={14} />
              </button>
            </div>
          </div>
        </motion.div>
      </div>
    </div>
  </section>;
}
