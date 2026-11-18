"use client";

import { motion } from "framer-motion";
import type { ReactNode } from "react";
import { easeOutExpo } from "../../lib/motion";
import { AnimatedHeadline } from "./AnimatedHeadline";

export function SectionHeading({
  title,
  accentWord,
  description,
  id,
}: {
  title: string;
  accentWord?: string;
  description?: ReactNode;
  id?: string;
}) {
  return (
    <div className="section-heading">
      <AnimatedHeadline as="h2" id={id} text={title} accentWord={accentWord} />
      {description && (
        <motion.p
          initial={{ opacity: 0, y: 10 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-80px" }}
          transition={{ duration: 0.5, delay: 0.32, ease: easeOutExpo }}
        >
          {description}
        </motion.p>
      )}
    </div>
  );
}
