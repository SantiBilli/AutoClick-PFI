"use client";

import { motion } from "framer-motion";

export function AnimatedCheck({ delay = 0 }: { delay?: number }) {
  return (
    <motion.svg width={16} height={16} viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <motion.path
        d="M3 8.5 6.5 12 13 4.5"
        stroke="#2563eb"
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
        initial={{ pathLength: 0, opacity: 0 }}
        whileInView={{ pathLength: 1, opacity: 1 }}
        viewport={{ once: true }}
        transition={{ duration: 0.5, delay, ease: "easeOut" }}
      />
    </motion.svg>
  );
}
