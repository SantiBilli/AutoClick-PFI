"use client";
import { useRef } from "react";
import { motion, useInView, useReducedMotion } from "framer-motion";
import { Panel } from "../ui/Panel";
import { AnimatedCounter } from "../ui/AnimatedCounter";
import { formatNumber } from "../../lib/formatters";
import { easeOutExpo } from "../../lib/motion";

/**
 * Dark counterpart to the rest of the rail: one number (how much of the monthly
 * limit is already committed to areas) plus the split behind it.
 */
export function AllocationCard({ assigned, unassigned, limit }: { assigned: number; unassigned: number; limit: number }) {
  const reduceMotion = useReducedMotion();
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true, margin: "-40px" });
  const percent = limit > 0 ? Math.min(100, Math.round((assigned / limit) * 100)) : 0;

  const size = 108;
  const stroke = 11;
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;

  return (
    <Panel tone="ink" className="alloc-card">
      <div>
        <p className="dash-eyebrow">Asignación</p>
        <h2>Límite mensual</h2>
        {limit > 0 ? (
          <>
            <p>{formatNumber(assigned)} de {formatNumber(limit)} tokens ya están repartidos entre tus áreas.</p>
            <div className="alloc-card__legend">
              <div>
                <i style={{ background: "#5b93ff" }} aria-hidden="true" />
                Asignado <b>{formatNumber(assigned)}</b>
              </div>
              <div>
                <i style={{ background: "rgb(255 255 255 / .25)" }} aria-hidden="true" />
                Sin asignar <b>{formatNumber(Math.max(0, unassigned))}</b>
              </div>
            </div>
          </>
        ) : (
          <p>Todavía no hay un límite mensual configurado para la organización.</p>
        )}
      </div>

      <div className="alloc-dial" ref={ref}>
        <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label={`${percent}% del límite asignado`}>
          <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="rgb(255 255 255 / .16)" strokeWidth={stroke} />
          <motion.circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke="url(#allocStroke)"
            strokeWidth={stroke}
            strokeLinecap="round"
            strokeDasharray={circumference}
            initial={{ strokeDashoffset: circumference }}
            animate={{ strokeDashoffset: inView ? circumference - (percent / 100) * circumference : circumference }}
            transition={reduceMotion ? { duration: 0 } : { duration: 1.3, ease: easeOutExpo }}
            transform={`rotate(-90 ${size / 2} ${size / 2})`}
          />
          <defs>
            <linearGradient id="allocStroke" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stopColor="#8fb4ff" />
              <stop offset="100%" stopColor="#3b7bf6" />
            </linearGradient>
          </defs>
        </svg>
        <span className="alloc-dial__label">
          <strong><AnimatedCounter value={percent} formatter={(value) => `${value}%`} /></strong>
          <span>asignado</span>
        </span>
      </div>
    </Panel>
  );
}
