"use client";

import type { ReactNode } from "react";
import { motion, useReducedMotion } from "framer-motion";
import { easeOutExpo } from "../../lib/motion";

export function AuthSplitFrame({
  eyebrow,
  title,
  description,
  visual,
  children,
}: {
  eyebrow?: string;
  title: string;
  description: string;
  visual: ReactNode;
  children: ReactNode;
}) {
  const shouldReduceMotion = useReducedMotion();

  return (
    <section className="auth-split-page">
      <motion.div
        className="auth-split-shell"
        initial={shouldReduceMotion ? false : { opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.5, ease: easeOutExpo }}
      >
        <motion.div
          className="auth-split-visual"
          initial={shouldReduceMotion ? false : { opacity: 0, x: -18 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.6, ease: easeOutExpo }}
        >
          {visual}
          <span className="auth-split-led" aria-hidden="true" />
          <span className="auth-split-node" aria-hidden="true" />
        </motion.div>
        <motion.div
          className="auth-split-form"
          initial={shouldReduceMotion ? false : { opacity: 0, x: 18 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.6, ease: easeOutExpo, delay: 0.05 }}
        >
          {eyebrow && (
            <motion.p
              className="eyebrow"
              initial={shouldReduceMotion ? false : { opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.45, ease: easeOutExpo, delay: 0.12 }}
            >
              {eyebrow}
            </motion.p>
          )}
          <motion.h1
            className="auth-split-title"
            initial={shouldReduceMotion ? false : { opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.45, ease: easeOutExpo, delay: 0.18 }}
          >
            {title}
          </motion.h1>
          <motion.p
            className="auth-split-desc"
            initial={shouldReduceMotion ? false : { opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.45, ease: easeOutExpo, delay: 0.24 }}
          >
            {description}
          </motion.p>
          {children}
        </motion.div>
      </motion.div>
    </section>
  );
}
