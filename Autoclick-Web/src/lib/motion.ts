import type { Transition, Variants } from "framer-motion";

export const easeOutExpo: Transition["ease"] = [0.16, 1, 0.3, 1];

export const fadeUp: Variants = {
  hidden: { opacity: 0, y: 24 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.6, ease: easeOutExpo } },
};

export const fadeIn: Variants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: { duration: 0.5, ease: easeOutExpo } },
};

export const scaleIn: Variants = {
  hidden: { opacity: 0, scale: 0.96 },
  visible: { opacity: 1, scale: 1, transition: { duration: 0.5, ease: easeOutExpo } },
};

export const staggerContainer: Variants = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.12, delayChildren: 0.05 } },
};

export const staggerFast: Variants = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.045 } },
};

export const pressable = {
  whileHover: { y: -1, scale: 1.02 },
  whileTap: { scale: 0.97 },
  transition: { duration: 0.15, ease: easeOutExpo },
};

export const pressableStrong = {
  whileHover: { y: -3, scale: 1.03 },
  whileTap: { scale: 0.96 },
  transition: { duration: 0.18, ease: easeOutExpo },
};

export const iconPop: Variants = {
  hidden: { opacity: 0, scale: 0.4, rotate: -12 },
  visible: { opacity: 1, scale: 1, rotate: 0, transition: { type: "spring", stiffness: 320, damping: 18 } },
};

export const word: Variants = {
  hidden: { opacity: 0, y: "0.6em" },
  visible: { opacity: 1, y: 0, transition: { duration: 0.55, ease: easeOutExpo } },
};

export const cardLift = {
  whileHover: { y: -6, transition: { duration: 0.25, ease: easeOutExpo } },
};

export const fadeUpBlur: Variants = {
  hidden: { opacity: 0, y: 26, filter: "blur(6px)" },
  visible: { opacity: 1, y: 0, filter: "blur(0px)", transition: { duration: 0.65, ease: easeOutExpo } },
};

export const staggerCards: Variants = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.09, delayChildren: 0.08 } },
};

/* ── Portal redesign presets ─────────────────────────────────────────────── */

/** Weighty spring used for anything the user directly manipulates. */
export const springSoft: Transition = { type: "spring", stiffness: 260, damping: 30, mass: 0.9 };
export const springSnappy: Transition = { type: "spring", stiffness: 420, damping: 34 };

/** Scroll-reveal pair: a container staggers its children as it enters the viewport. */
export const revealGroup: Variants = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.07, delayChildren: 0.04 } },
};

export const revealItem: Variants = {
  hidden: { opacity: 0, y: 18, filter: "blur(5px)" },
  visible: { opacity: 1, y: 0, filter: "blur(0px)", transition: { duration: 0.55, ease: easeOutExpo } },
};

/** Shared viewport config so every reveal in the portal triggers at the same point. */
export const revealViewport = { once: true, margin: "-60px 0px -40px" } as const;

/** Standard scroll-reveal props for a section that staggers its children. */
export const revealProps = {
  variants: revealGroup,
  initial: "hidden",
  whileInView: "visible",
  viewport: revealViewport,
} as const;

export const liftOnHover = {
  whileHover: { y: -4, transition: { duration: 0.25, ease: easeOutExpo } },
} as const;
