"use client";

import { motion } from "framer-motion";
import { easeOutExpo } from "../../lib/motion";

type SectionConnectorProps = {
  className?: string;
  /** Length of the connector. Number is treated as px; strings (e.g. "clamp(...)") pass through as-is. */
  height?: number | string;
  /**
   * Anchors the connector above the bottom edge of its `position: relative` parent
   * (e.g. a carousel) instead of taking up space in normal document flow. Use this
   * when the connector must never overlap content that scrolls or reflows below it.
   */
  floating?: boolean;
  /** Clearance in px between the node and the floating parent's top edge. Only used when `floating`. */
  gap?: number;
};

export function SectionConnector({ className = "", height = 40, floating = false, gap = 14 }: SectionConnectorProps) {
  const resolvedHeight = typeof height === "number" ? `${height}px` : height;
  return (
    <span
      className={`section-connector ${floating ? "section-connector--floating" : ""} ${className}`.trim()}
      aria-hidden="true"
      style={floating ? { height: resolvedHeight, bottom: `calc(100% + ${gap}px)` } : { height: resolvedHeight }}
    >
      <motion.span
        className="section-connector__line"
        initial={{ scaleY: 0 }}
        whileInView={{ scaleY: 1 }}
        viewport={{ once: true, margin: "-40px" }}
        transition={{ duration: 0.5, ease: easeOutExpo }}
      />
      <motion.span
        className="section-connector__dot"
        initial={{ opacity: 0, scale: 0.4 }}
        whileInView={{ opacity: 1, scale: 1 }}
        viewport={{ once: true, margin: "-40px" }}
        transition={{ duration: 0.3, delay: 0.4, ease: easeOutExpo }}
      />
    </span>
  );
}
