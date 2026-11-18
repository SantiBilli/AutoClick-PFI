"use client";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { easeOutExpo } from "../../lib/motion";

const ROBOT_SRC = {
  neutral: "/mascot/AutoClick_Robot_Neutral.png",
  explaining: "/mascot/AutoClick_Robot_Explicando.png",
  success: "/mascot/AutoClick_Robot_Exito.png",
} as const;

export type RobotPose = keyof typeof ROBOT_SRC;

const SIZE_PX = { sm: 56, md: 96, lg: 136, xl: 184 } as const;

export function RobotHelper({
  pose = "neutral",
  size = "md",
  float = true,
  className = "",
}: {
  pose?: RobotPose;
  size?: keyof typeof SIZE_PX;
  float?: boolean;
  className?: string;
}) {
  const reduceMotion = useReducedMotion();
  const px = SIZE_PX[size];
  const shouldFloat = float && !reduceMotion;

  return (
    <motion.div
      className={`robot-helper ${className}`.trim()}
      style={{ width: px, height: px }}
      animate={shouldFloat ? { y: [0, -4, 0] } : undefined}
      transition={shouldFloat ? { duration: 5, repeat: Infinity, ease: "easeInOut" } : undefined}
      aria-hidden="true"
    >
      <span className="robot-helper__shadow" />
      <AnimatePresence mode="wait">
        <motion.img
          key={pose}
          src={ROBOT_SRC[pose]}
          alt=""
          className="robot-helper__img"
          initial={reduceMotion ? false : { opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={reduceMotion ? undefined : { opacity: 0 }}
          transition={{ duration: 0.3, ease: easeOutExpo }}
        />
      </AnimatePresence>
    </motion.div>
  );
}
