"use client";
import { motion, useReducedMotion } from "framer-motion";
import { ArrowDownRight, ArrowUpRight, Minus, type LucideIcon } from "lucide-react";
import type { MouseEvent } from "react";
import { AnimatedCounter } from "./AnimatedCounter";
import { easeOutExpo, revealItem } from "../../lib/motion";

const TONE_COLOR = { blue: "var(--dash-accent)", cyan: "#3f7fa6", amber: "var(--dash-warn)", green: "var(--dash-positive)" } as const;

export type MetricTone = keyof typeof TONE_COLOR;

export type MetricVisual =
  | { type: "radial"; percent: number }
  | { type: "bar"; percent: number }
  | { type: "ratio"; active: number; total: number }
  | { type: "delta"; percent: number | null }
  | { type: "none" };

export function MetricCard({
  icon: Icon,
  tone = "blue",
  label,
  value,
  helper,
  visual = { type: "none" },
  className = "",
}: {
  icon: LucideIcon;
  tone?: MetricTone;
  label: string;
  value: number | string;
  helper?: string;
  visual?: MetricVisual;
  className?: string;
}) {
  const reduceMotion = !!useReducedMotion();
  const numeric = typeof value === "number" ? value : null;
  const color = TONE_COLOR[tone];

  const trackPointer = (event: MouseEvent<HTMLElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    event.currentTarget.style.setProperty("--mx", `${event.clientX - bounds.left}px`);
    event.currentTarget.style.setProperty("--my", `${event.clientY - bounds.top}px`);
  };

  return (
    <motion.article
      className={`ui-card metric-card dash-panel--spot ${className}`.trim()}
      variants={revealItem}
      whileHover={reduceMotion ? undefined : { y: -4, transition: { duration: 0.25, ease: easeOutExpo } }}
      onMouseMove={trackPointer}
    >
      <div className="metric-card__top">
        <motion.span
          className="metric-card__icon"
          initial={reduceMotion ? false : { scale: 0.6, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ type: "spring", stiffness: 340, damping: 18 }}
        >
          <Icon size={18} strokeWidth={2} aria-hidden="true" />
        </motion.span>
        {visual.type === "radial" && <RadialMeter percent={visual.percent} color={color} reduceMotion={reduceMotion} />}
        {visual.type === "delta" && <DeltaChip percent={visual.percent} />}
      </div>
      <span className="metric-card__label">{label}</span>
      <strong className="metric-card__value">{numeric !== null ? <AnimatedCounter value={numeric} /> : value}</strong>
      {helper && <small className="metric-card__helper">{helper}</small>}
      {visual.type === "bar" && <MiniBar percent={visual.percent} color={color} reduceMotion={reduceMotion} />}
      {visual.type === "ratio" && <RatioDots active={visual.active} total={visual.total} color={color} />}
    </motion.article>
  );
}

function RadialMeter({ percent, color, reduceMotion }: { percent: number; color: string; reduceMotion: boolean }) {
  const size = 40;
  const stroke = 4;
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const clamped = Math.max(0, Math.min(100, percent));
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label={`${clamped}% del límite`}>
      <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="var(--dash-line)" strokeWidth={stroke} />
      <motion.circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        stroke={color}
        strokeWidth={stroke}
        strokeLinecap="round"
        strokeDasharray={circumference}
        initial={{ strokeDashoffset: circumference }}
        whileInView={{ strokeDashoffset: circumference - (clamped / 100) * circumference }}
        viewport={{ once: true }}
        transition={reduceMotion ? { duration: 0 } : { duration: 1.1, ease: easeOutExpo }}
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
      />
    </svg>
  );
}

function DeltaChip({ percent }: { percent: number | null }) {
  if (percent === null) return <span className="metric-card__delta metric-card__delta--flat"><Minus size={12} aria-hidden="true" /> s/d</span>;
  const up = percent > 0;
  const flat = percent === 0;
  const Icon = flat ? Minus : up ? ArrowUpRight : ArrowDownRight;
  return (
    <span className={`metric-card__delta metric-card__delta--${flat ? "flat" : up ? "up" : "down"}`}>
      <Icon size={12} aria-hidden="true" /> {up ? "+" : ""}{percent}%
    </span>
  );
}

function MiniBar({ percent, color, reduceMotion }: { percent: number; color: string; reduceMotion: boolean }) {
  const clamped = Math.max(0, Math.min(100, percent));
  return (
    <div className="metric-card__bar" role="img" aria-label={`${clamped}%`}>
      <motion.span
        className="metric-card__bar-fill"
        style={{ background: color }}
        initial={{ width: 0 }}
        whileInView={{ width: `${clamped}%` }}
        viewport={{ once: true }}
        transition={reduceMotion ? { duration: 0 } : { duration: 0.9, ease: easeOutExpo }}
      />
    </div>
  );
}

function RatioDots({ active, total, color }: { active: number; total: number; color: string }) {
  return (
    <div className="metric-card__ratio" aria-hidden="true">
      {Array.from({ length: total }).map((_, index) => (
        <motion.span
          key={index}
          className="metric-card__dot"
          style={{ background: index < active ? color : "var(--dash-line-strong)" }}
          initial={{ scale: 0 }}
          whileInView={{ scale: 1 }}
          viewport={{ once: true }}
          transition={{ delay: index * 0.06, duration: 0.3, ease: easeOutExpo }}
        />
      ))}
    </div>
  );
}
