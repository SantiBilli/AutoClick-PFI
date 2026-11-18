"use client";
import { motion, type HTMLMotionProps } from "framer-motion";
import type { MouseEvent, ReactNode } from "react";
import { revealItem, revealViewport } from "../../lib/motion";

export type PanelTone = "plain" | "flat" | "soft" | "ink";

const TONE_CLASS: Record<PanelTone, string> = {
  plain: "",
  flat: "dash-panel--flat",
  soft: "dash-panel--soft",
  ink: "dash-panel--ink",
};

export interface PanelProps extends Omit<HTMLMotionProps<"div">, "children"> {
  tone?: PanelTone;
  /** Lift on hover — for cards that lead somewhere or group an interaction. */
  hover?: boolean;
  /** Cursor-following highlight; pairs with `hover` on feature surfaces. */
  spotlight?: boolean;
  /** Opt out of the scroll-reveal variants when a parent drives the animation. */
  reveal?: boolean;
  /** Trigger the reveal from the card itself — for panels with no motion parent. */
  selfReveal?: boolean;
  className?: string;
  children?: ReactNode;
}

/**
 * The portal's single card surface. Elevation is expressed with tone + shadow
 * rather than borders, so cards only stand out where hierarchy needs them to.
 */
export function Panel({
  tone = "plain",
  hover = false,
  spotlight = false,
  reveal = true,
  selfReveal = false,
  className = "",
  children,
  onMouseMove,
  ...motionProps
}: PanelProps) {
  const trackPointer = (event: MouseEvent<HTMLDivElement>) => {
    if (spotlight) {
      const bounds = event.currentTarget.getBoundingClientRect();
      event.currentTarget.style.setProperty("--mx", `${event.clientX - bounds.left}px`);
      event.currentTarget.style.setProperty("--my", `${event.clientY - bounds.top}px`);
    }
    onMouseMove?.(event);
  };

  return (
    <motion.div
      className={`dash-panel ${TONE_CLASS[tone]} ${hover ? "dash-panel--hover" : ""} ${spotlight ? "dash-panel--spot" : ""} ${className}`
        .replace(/\s+/g, " ")
        .trim()}
      variants={reveal ? revealItem : undefined}
      initial={selfReveal ? "hidden" : undefined}
      whileInView={selfReveal ? "visible" : undefined}
      viewport={selfReveal ? revealViewport : undefined}
      onMouseMove={trackPointer}
      {...motionProps}
    >
      {children}
    </motion.div>
  );
}
