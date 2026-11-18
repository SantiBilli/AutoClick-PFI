"use client";
import { Avatar } from "../ui/Avatar";
import { motion } from "framer-motion";
import { Activity } from "lucide-react";
import { ChartCard } from "./ChartCard";
import { EmptyState } from "../ui/EmptyState";
import { formatNumber } from "../../lib/formatters";
import { easeOutExpo, revealGroup, revealItem, revealViewport } from "../../lib/motion";

export interface ActivityRow {
  id: string;
  label: string;
  value: number;
  total: number;
  /** Two-letter chip; falls back to the first letters of the label. */
  initials?: string;
  avatarUrl?: string;
  sub?: string;
}

export function ActivityPanel({
  rows,
  title = "Uso por área",
  description = "Ranking de consumo dentro del período en curso.",
  eyebrow = "Ranking",
}: {
  rows: ActivityRow[];
  title?: string;
  description?: string;
  eyebrow?: string;
}) {
  const hasData = rows.length > 0 && rows.some((row) => row.value > 0);
  const top = rows.reduce((best, row) => Math.max(best, row.value), 0);

  return (
    <ChartCard eyebrow={eyebrow} title={title} description={description}>
      {hasData ? (
        <motion.ul className="rank-list" variants={revealGroup} initial="hidden" whileInView="visible" viewport={revealViewport}>
          {rows.map((row) => {
            const share = row.total > 0 ? Math.round((row.value / row.total) * 100) : 0;
            const width = top > 0 ? Math.max(6, Math.round((row.value / top) * 100)) : 0;
            return (
              <motion.li className="rank-row" key={row.id} variants={revealItem}>
                <Avatar className="avatar" user={{ name: row.label, avatarInitials: row.initials ?? row.label.slice(0, 2).toUpperCase(), avatarUrl: row.avatarUrl }} />
                <span className="rank-row__meta">
                  <strong>{row.label}</strong>
                  <small>{row.sub ?? `${share}% del total`}</small>
                  <span className="rank-row__bar">
                    <motion.span
                      initial={{ width: 0 }}
                      whileInView={{ width: `${width}%` }}
                      viewport={{ once: true }}
                      transition={{ duration: 0.85, ease: easeOutExpo }}
                    />
                  </span>
                </span>
                <span className="rank-row__value">{formatNumber(row.value)}</span>
              </motion.li>
            );
          })}
        </motion.ul>
      ) : (
        <EmptyState
          icon={<Activity size={22} aria-hidden="true" />}
          title="Sin actividad todavía"
          description="Cuando haya consumo registrado vas a ver el ranking acá."
        />
      )}
    </ChartCard>
  );
}
