"use client";

import { motion } from "framer-motion";
import type { MouseEventHandler, ReactNode } from "react";
import { fadeUp, staggerContainer } from "../../lib/motion";

interface RevealProps {
  as?: "div" | "section" | "ul" | "li" | "article" | "footer";
  stagger?: boolean;
  delay?: number;
  className?: string;
  id?: string;
  children?: ReactNode;
  onMouseMove?: MouseEventHandler<HTMLElement>;
}

export function Reveal({ as = "div", stagger = false, delay = 0, className = "", id, children, onMouseMove }: RevealProps) {
  const MotionTag = motion[as];
  const variants = stagger ? staggerContainer : fadeUp;

  return (
    <MotionTag
      className={className}
      id={id}
      variants={variants}
      initial="hidden"
      whileInView="visible"
      viewport={{ once: true, margin: "-80px" }}
      transition={stagger ? undefined : { delay }}
      onMouseMove={onMouseMove}
    >
      {children}
    </MotionTag>
  );
}

export function RevealItem({ as = "div", className = "", id, children, onMouseMove }: RevealProps) {
  const MotionTag = motion[as];
  return (
    <MotionTag className={className} id={id} variants={fadeUp} onMouseMove={onMouseMove}>
      {children}
    </MotionTag>
  );
}
