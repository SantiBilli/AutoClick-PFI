"use client";

import { useEffect, useRef, useState } from "react";
import type { ComponentType, MouseEvent } from "react";
import Image from "next/image";
import { motion, useInView, useReducedMotion } from "framer-motion";
import {
  CheckCircle2,
  Clock,
  Globe,
  GripVertical,
  MessageCircleMore,
  MousePointerClick,
  Play,
  Save,
  Search,
  Send,
  X,
} from "lucide-react";
import { easeOutExpo } from "../../lib/motion";

type Category = "ejecucion" | "navegador" | "mouse";

interface FlowStep {
  category: Category;
  title: string;
}

const CATEGORY_META: Record<Category, { name: string; icon: ComponentType<{ size?: number }> }> = {
  ejecucion: { name: "Ejecución", icon: Clock },
  navegador: { name: "Navegador", icon: Globe },
  mouse: { name: "Mouse", icon: MousePointerClick },
};

const flowSteps: FlowStep[] = [
  { category: "ejecucion", title: "Iniciar flujo" },
  { category: "navegador", title: "Portal de pagos" },
  { category: "ejecucion", title: "Cargar página" },
  { category: "mouse", title: "Iniciar sesión" },
  { category: "mouse", title: "Buscar comprobante" },
  { category: "ejecucion", title: "Confirmar carga" },
  { category: "mouse", title: "Descargar PDF" },
];

const railGroups: { category: Category; blocks: string[] }[] = [
  { category: "ejecucion", blocks: ["Esperar", "Detener"] },
  { category: "mouse", blocks: ["Click", "Mover mouse"] },
];

type ChatMessage = { role: "ai" | "user"; text: string };

const chatScript: ChatMessage[] = [
  { role: "ai", text: "¡Hola! Soy ClickIA 👋 Contame qué flujo querés armar." },
  { role: "user", text: "Quiero entrar al portal de pagos y descargar el último comprobante." },
  { role: "ai", text: "Perfecto. Agregué “Abrir URL” y dos bloques de Click para iniciar sesión y buscar el comprobante." },
  { role: "user", text: "Sumale una espera entre cada paso para que no falle." },
  { role: "ai", text: "Listo, agregué 3 bloques de Espera. Tu flujo ya tiene 7 pasos." },
  { role: "user", text: "Genial, probemos." },
  { role: "ai", text: "Ejecutando en tu Desktop… ✅ Comprobante descargado." },
];

const STEP_MS = 950;
const STEP_HOLD_MS = 1800;
const MSG_MS = 1300;
const AI_TYPING_MS = 900;
const CHAT_HOLD_MS = 2400;

export function HeroVisual() {
  const stageRef = useRef<HTMLDivElement>(null);
  const inView = useInView(stageRef, { amount: 0.4 });
  const shouldReduceMotion = useReducedMotion();

  const [activeStep, setActiveStep] = useState(0);
  const [tilt, setTilt] = useState({ x: 0, y: 0 });
  const finePointer = useRef(false);

  const [visibleCount, setVisibleCount] = useState(shouldReduceMotion ? chatScript.length : 0);
  const [typing, setTyping] = useState(false);

  const stepRefs = useRef<(HTMLLIElement | null)[]>([]);
  const chatBodyRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    finePointer.current = window.matchMedia("(pointer: fine)").matches;
  }, []);

  const handlePointerMove = (event: MouseEvent<HTMLDivElement>) => {
    if (shouldReduceMotion || !finePointer.current) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const px = (event.clientX - rect.left) / rect.width - 0.5;
    const py = (event.clientY - rect.top) / rect.height - 0.5;
    setTilt({ x: py * -6, y: px * 6 });
  };

  const handlePointerLeave = () => setTilt({ x: 0, y: 0 });

  useEffect(() => {
    if (!inView) return;
    if (shouldReduceMotion) {
      setActiveStep(flowSteps.length);
      return;
    }
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;

    const advance = (step: number) => {
      if (cancelled) return;
      setActiveStep(step);
      timer = setTimeout(() => advance(step < flowSteps.length ? step + 1 : 0), step < flowSteps.length ? STEP_MS : STEP_HOLD_MS);
    };
    advance(0);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [inView, shouldReduceMotion]);

  useEffect(() => {
    stepRefs.current[activeStep]?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [activeStep]);

  useEffect(() => {
    if (!inView || shouldReduceMotion) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;

    const reveal = (count: number) => {
      if (cancelled) return;
      if (count >= chatScript.length) {
        timer = setTimeout(() => {
          setVisibleCount(0);
          reveal(0);
        }, CHAT_HOLD_MS);
        return;
      }
      const isAi = chatScript[count].role === "ai";
      if (isAi) setTyping(true);
      timer = setTimeout(() => {
        setTyping(false);
        setVisibleCount(count + 1);
        reveal(count + 1);
      }, isAi ? AI_TYPING_MS : MSG_MS);
    };
    reveal(0);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [inView, shouldReduceMotion]);

  useEffect(() => {
    chatBodyRef.current?.scrollTo({ top: chatBodyRef.current.scrollHeight, behavior: "smooth" });
  }, [visibleCount, typing]);

  const done = activeStep >= flowSteps.length;

  return <motion.div
    className="hero-visual"
    ref={stageRef}
    initial={{ opacity: 0, y: 24, rotate: -2 }}
    whileInView={{ opacity: 1, y: 0, rotate: 0 }}
    viewport={{ once: true, amount: 0.3 }}
    transition={{ duration: 0.7, ease: easeOutExpo }}
    onMouseMove={handlePointerMove}
    onMouseLeave={handlePointerLeave}
  >
    <motion.div className="hero-visual__tilt" animate={{ rotateX: tilt.x, rotateY: tilt.y }} transition={{ type: "spring", stiffness: 160, damping: 16 }}>
      <div className="hero-visual__stage">
        <motion.div className="hero-visual__float" animate={shouldReduceMotion ? undefined : { y: [0, -9, 0] }} transition={{ duration: 7, repeat: Infinity, ease: "easeInOut" }}>
          <div className="editor-window" aria-label="Editor de flujos de AutoClick, ejemplo de un flujo de conciliación de pagos">
            <div className="editor-window__bar">
              <span className="editor-window__dots" aria-hidden="true"><i /><i /><i /></span>
              <span className="editor-window__title"><span className="status-dot" aria-hidden="true" /> AutoClick</span>
              <span className={`editor-window__status ${done ? "editor-window__status--done" : "editor-window__status--running"}`}>
                {done ? <><CheckCircle2 size={12} /> Completado</> : <><Play size={11} fill="currentColor" /> En ejecución</>}
              </span>
            </div>
            <div className="editor-window__toolbar">
              <span className="editor-window__toolbar-label">Bloques</span>
              <span className="editor-window__toolbar-actions">
                <span><Save size={12} /></span>
                <span><CheckCircle2 size={12} /></span>
                <span><Play size={11} fill="currentColor" /></span>
              </span>
            </div>
            <div className="editor-window__body">
              <div className="editor-rail" aria-hidden="true">
                <div className="editor-rail__search"><Search size={11} /> <span>Buscar bloques…</span></div>
                {railGroups.map(({ category, blocks }) => {
                  const meta = CATEGORY_META[category];
                  return <div className={`editor-rail__group tone-${category}`} key={category}>
                    <span className="editor-rail__group-label"><span className="editor-rail__dot" />{meta.name}</span>
                    {blocks.map((block) => <span className="editor-rail__chip" key={block}><span className="editor-rail__chip-icon"><meta.icon size={11} /></span> {block}</span>)}
                  </div>;
                })}
              </div>
              <div className="editor-window__canvas-wrap">
                <div className="editor-window__canvas">
                  <ol className="editor-blocks">
                    {flowSteps.map(({ category, title }, index) => {
                      const connected = index > 0 && index <= activeStep;
                      const meta = CATEGORY_META[category];
                      return <li
                        className={`editor-block tone-${category} ${connected ? "editor-block--connected" : ""}`.trim()}
                        key={`${title}-${index}`}
                        ref={(el) => { stepRefs.current[index] = el; }}
                      >
                        <GripVertical className="editor-block__grip" size={13} aria-hidden="true" />
                        <span className="editor-block__badge">{index + 1}</span>
                        <span className="editor-block__icon"><meta.icon size={16} /></span>
                        <div className="editor-block__text"><small>{meta.name}</small><strong>{title}</strong></div>
                      </li>;
                    })}
                  </ol>
                </div>
                <div className="editor-window__canvas-fade" aria-hidden="true" />
              </div>
            </div>
          </div>

          <div className="ai-chat-anchor">
            <motion.div
              className="ai-chat-card"
              initial={{ opacity: 0, y: 20, rotate: -5 }}
              whileInView={{ opacity: 1, y: 0, rotate: -2 }}
              viewport={{ once: true, amount: 0.3 }}
              transition={{ duration: 0.6, ease: easeOutExpo, delay: 0.25 }}
              aria-label="Vista previa del asistente ClickIA armando el flujo"
            >
              <div className="ai-chat-card__header">
                <span className="ai-chat-card__avatar">
                  <Image src="/mascot/AutoClick_Robot_Neutral.png" alt="" width={30} height={30} />
                </span>
                <span className="ai-chat-card__title">
                  <strong>ClickIA</strong>
                  <span><span className="ai-chat-card__pulse" /> En línea</span>
                </span>
                <MessageCircleMore className="ai-chat-card__hint" size={14} aria-hidden="true" />
                <span className="ai-chat-card__close"><X size={13} /></span>
              </div>
              <div className="ai-chat-card__body" ref={chatBodyRef}>
                {chatScript.slice(0, visibleCount).map((message, index) => <motion.div
                  key={index}
                  className={`chat-msg chat-msg--${message.role}`}
                  initial={{ opacity: 0, y: 8, scale: 0.97 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  transition={{ duration: 0.35, ease: easeOutExpo }}
                >
                  {message.text}
                </motion.div>)}
                {typing && <div className="chat-typing" aria-hidden="true"><span /><span /><span /></div>}
              </div>
              <div className="ai-chat-card__input">
                <span className="ai-chat-card__input-field">Escribí tu consulta sobre el flujo…</span>
                <span className="ai-chat-card__send"><Send size={13} /></span>
              </div>
            </motion.div>
          </div>
        </motion.div>
      </div>
    </motion.div>
  </motion.div>;
}
