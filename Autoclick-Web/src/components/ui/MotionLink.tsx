"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import type { ReactNode } from "react";
import { pressable, pressableStrong } from "../../lib/motion";

export const MotionLink = motion.create(Link);

export function CTALink({
  href,
  className = "",
  id,
  strong = false,
  ariaLabel,
  children,
}: {
  href: string;
  className?: string;
  id?: string;
  strong?: boolean;
  ariaLabel?: string;
  children?: ReactNode;
}) {
  return (
    <MotionLink href={href} id={id} className={className} aria-label={ariaLabel} {...(strong ? pressableStrong : pressable)}>
      {children}
    </MotionLink>
  );
}
