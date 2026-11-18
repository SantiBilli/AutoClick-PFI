"use client";
import { motion, useReducedMotion } from "framer-motion";
import { CircleCheck, ShieldAlert } from "lucide-react";
import { Panel } from "../ui/Panel";
import { formatNumber } from "../../lib/formatters";

/**
 * Rail card for roles without organisation-wide allocation: instead of the
 * split of the monthly limit, it answers "can I work right now, and with what".
 */
export function AccessCard({
  hasAccess,
  reason,
  areaCount,
  version,
  usage,
}: {
  hasAccess: boolean;
  reason: string;
  areaCount: number;
  version: string;
  usage: number;
}) {
  const reduceMotion = useReducedMotion();

  return (
    <Panel tone="ink" className="alloc-card access-card">
      <div>
        <p className="dash-eyebrow">Tu acceso</p>
        <h2>{hasAccess ? "Listo para trabajar" : "Acceso limitado"}</h2>
        <p>{hasAccess ? `Podés usar AutoClick Desktop ${version} en las áreas que tenés asignadas.` : reason}</p>
        <div className="alloc-card__legend">
          <div>
            <i style={{ background: "#5b93ff" }} aria-hidden="true" />
            Áreas asignadas <b>{areaCount}</b>
          </div>
          <div>
            <i style={{ background: "rgb(255 255 255 / .25)" }} aria-hidden="true" />
            Tokens del período <b>{formatNumber(usage)}</b>
          </div>
        </div>
      </div>
      <motion.span
        className={`access-card__seal ${hasAccess ? "access-card__seal--ok" : "access-card__seal--warn"}`}
        animate={reduceMotion || !hasAccess ? undefined : { scale: [1, 1.05, 1] }}
        transition={{ duration: 3.5, repeat: Infinity, ease: "easeInOut" }}
        aria-hidden="true"
      >
        {hasAccess ? <CircleCheck size={30} /> : <ShieldAlert size={30} />}
      </motion.span>
    </Panel>
  );
}
