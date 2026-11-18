"use client";

import { useEffect, useRef } from "react";
import type { ComponentType, ReactNode } from "react";
import Image from "next/image";
import { AnimatePresence, motion, useAnimationControls, useReducedMotion } from "framer-motion";
import { LogIn, PenTool, PlayCircle, ShieldCheck, UserPlus, Workflow } from "lucide-react";
import { easeOutExpo } from "../../lib/motion";

type FlowStep = { icon: ComponentType<{ size?: number }>; label: string };

function useRobotReaction(nudge: number) {
  const controls = useAnimationControls();
  const shouldReduceMotion = useReducedMotion();

  useEffect(() => {
    if (nudge > 0 && !shouldReduceMotion) {
      controls.start({ scale: [1, 1.035, 1], rotate: [0, -1.5, 0], transition: { duration: 0.45, ease: "easeOut" } });
    }
  }, [nudge, shouldReduceMotion, controls]);

  return controls;
}

function RobotFloater({ src, floatDisabled }: { src: string; floatDisabled: boolean }) {
  const shouldReduceMotion = useReducedMotion();

  return (
    <motion.div
      className="auth-visual-robot-float"
      animate={shouldReduceMotion || floatDisabled ? undefined : { y: [0, -4, 0] }}
      transition={{ duration: 4.6, repeat: Infinity, ease: "easeInOut" }}
    >
      <div className="auth-visual-robot-pose">
        <AnimatePresence>
          <motion.div
            key={src}
            className="auth-visual-robot-img-wrap"
            initial={shouldReduceMotion ? false : { opacity: 0, scale: 0.85 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={shouldReduceMotion ? undefined : { opacity: 0, scale: 0.92 }}
            transition={{ duration: 0.3, ease: easeOutExpo }}
          >
            <Image className="auth-visual-robot-img" src={src} alt="" width={140} height={140} priority />
          </motion.div>
        </AnimatePresence>
      </div>
      <span className="auth-visual-robot-shadow" aria-hidden="true" />
    </motion.div>
  );
}

function SpeechBubble({ lines, bubbleKey }: { lines: string[]; bubbleKey: string }) {
  const shouldReduceMotion = useReducedMotion();
  const mountedOnceRef = useRef(false);
  const isFirstAppearance = !mountedOnceRef.current;

  useEffect(() => {
    mountedOnceRef.current = true;
  }, []);

  return (
    <AnimatePresence mode="wait">
      <motion.div
        key={bubbleKey}
        className="auth-visual-bubble"
        initial={shouldReduceMotion ? false : { opacity: 0, y: 8, scale: 0.95 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={shouldReduceMotion ? undefined : { opacity: 0, y: 4, scale: 0.97 }}
        transition={{ duration: 0.3, delay: shouldReduceMotion || !isFirstAppearance ? 0 : 0.3, ease: easeOutExpo }}
      >
        {lines.map((line) => (
          <p key={line}>{line}</p>
        ))}
        <span className="auth-visual-bubble__tail" aria-hidden="true" />
      </motion.div>
    </AnimatePresence>
  );
}

function FlowNodes({ steps }: { steps: FlowStep[] }) {
  const shouldReduceMotion = useReducedMotion();
  const items: ReactNode[] = [];

  steps.forEach((step, index) => {
    items.push(
      <div className="auth-visual-flow__step" key={`node-${step.label}`}>
        <motion.span
          className="auth-visual-flow__node"
          initial={shouldReduceMotion ? false : { opacity: 0, scale: 0.6 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.35, delay: shouldReduceMotion ? 0 : 0.55 + index * 0.15, ease: easeOutExpo }}
        >
          <step.icon size={15} />
        </motion.span>
        <span className="auth-visual-flow__label">{step.label}</span>
      </div>,
    );
    if (index < steps.length - 1) {
      items.push(
        <motion.span
          className="auth-visual-flow__line"
          key={`line-${index}`}
          initial={shouldReduceMotion ? false : { scaleX: 0 }}
          animate={{ scaleX: 1 }}
          transition={{ duration: 0.3, delay: shouldReduceMotion ? 0 : 0.65 + index * 0.15, ease: easeOutExpo }}
        />,
      );
    }
  });

  return (
    <div className="auth-visual-flow" aria-hidden="true">
      {items}
    </div>
  );
}

export function LoginVisual({ nudge, success }: { nudge: number; success: boolean }) {
  const reactionControls = useRobotReaction(nudge);
  const robotSrc = success ? "/mascot/AutoClick_Robot_Exito.png" : "/mascot/AutoClick_Robot_Neutral.png";

  return (
    <div className="auth-visual-stage">
      <motion.div className="auth-visual-robot-zone" animate={reactionControls}>
        <SpeechBubble
          bubbleKey={success ? "success" : "idle"}
          lines={success ? ["¡Todo listo!", "Te llevamos a tu espacio…"] : ["¡Qué bueno verte de nuevo!", "Tus flujos están listos."]}
        />
        <RobotFloater src={robotSrc} floatDisabled={success} />
      </motion.div>
      <FlowNodes
        steps={[
          { icon: LogIn, label: "Ingresar" },
          { icon: PenTool, label: "Diseñar" },
          { icon: PlayCircle, label: "Ejecutar" },
        ]}
      />
    </div>
  );
}

export function RegisterVisual({ nudge, success }: { nudge: number; success: boolean }) {
  const reactionControls = useRobotReaction(nudge);
  const robotSrc = success ? "/mascot/AutoClick_Robot_Exito.png" : "/mascot/AutoClick_Robot_Explicando.png";

  return (
    <div className="auth-visual-stage">
      <motion.div className="auth-visual-robot-zone" animate={reactionControls}>
        <SpeechBubble
          bubbleKey={success ? "success" : "idle"}
          lines={success ? ["¡Cuenta creada!", "Ya casi estás adentro."] : ["Te acompaño en tu primer flujo."]}
        />
        <RobotFloater src={robotSrc} floatDisabled={success} />
      </motion.div>
      <FlowNodes
        steps={[
          { icon: UserPlus, label: "Creá tu cuenta" },
          { icon: Workflow, label: "Diseñá tu flujo" },
          { icon: ShieldCheck, label: "Ejecutalo con control" },
        ]}
      />
    </div>
  );
}
