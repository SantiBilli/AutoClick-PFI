"use client";
import { useMemo, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { Area, AreaChart, ReferenceDot, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";
import { Panel } from "../ui/Panel";
import { AnimatedCounter } from "../ui/AnimatedCounter";
import { formatNumber } from "../../lib/formatters";
import { easeOutExpo, springSnappy } from "../../lib/motion";
import type { UsagePoint } from "../../lib/usage";

const RANGES = [
  { id: "3", label: "3 meses", months: 3 },
  { id: "6", label: "6 meses", months: 6 },
  { id: "12", label: "12 meses", months: 12 },
] as const;

function ChartTooltip({ active, payload }: { active?: boolean; payload?: { payload: UsagePoint }[] }) {
  if (!active || !payload?.length) return null;
  const item = payload[0].payload;
  return (
    <div className="chart-tooltip">
      <strong>{item.label}</strong>
      <span>{formatNumber(item.tokens)} tokens</span>
    </div>
  );
}

export function UsageTrendCard({ series, scopeLabel }: { series: UsagePoint[]; scopeLabel: string }) {
  const reduceMotion = useReducedMotion();
  const [rangeId, setRangeId] = useState<(typeof RANGES)[number]["id"]>("6");
  const [activePeriod, setActivePeriod] = useState<string | null>(null);

  const range = RANGES.find((item) => item.id === rangeId) ?? RANGES[1];
  const data = useMemo(() => series.slice(Math.max(0, series.length - range.months)), [series, range.months]);
  const active = data.find((point) => point.period === activePeriod) ?? data[data.length - 1];
  const activeIndex = data.findIndex((point) => point.period === active?.period);
  const previous = activeIndex > 0 ? data[activeIndex - 1] : null;
  const delta = previous && previous.tokens > 0 ? Math.round(((active.tokens - previous.tokens) / previous.tokens) * 100) : null;
  const peak = data.reduce((best, point) => Math.max(best, point.tokens), 0);

  const DeltaIcon = delta === null || delta === 0 ? Minus : delta > 0 ? ArrowUpRight : ArrowDownRight;

  return (
    <Panel className="trend-card" hover spotlight>
      <p className="trend-card__label">Consumo de {scopeLabel}</p>
      <div className="trend-card__value">
        <AnimatePresence mode="wait" initial={false}>
          <motion.span
            key={active?.period ?? "none"}
            initial={reduceMotion ? false : { opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={reduceMotion ? undefined : { opacity: 0, y: -10 }}
            transition={{ duration: 0.28, ease: easeOutExpo }}
          >
            <AnimatedCounter value={active?.tokens ?? 0} />
          </motion.span>
        </AnimatePresence>
        <span>tokens</span>
      </div>
      <p className="trend-card__sub">
        <span className={`metric-card__delta metric-card__delta--${delta === null || delta === 0 ? "flat" : delta > 0 ? "up" : "down"}`}>
          <DeltaIcon size={12} aria-hidden="true" />
          {delta === null ? "s/d" : `${delta > 0 ? "+" : ""}${delta}%`}
        </span>
        {previous ? `vs. ${previous.label}` : "sin período previo"}
      </p>

      <div className="trend-tabs" role="group" aria-label="Rango del gráfico">
        {RANGES.map((item) => {
          const selected = item.id === rangeId;
          return (
            <button
              key={item.id}
              className="trend-tabs__btn"
              type="button"
              aria-pressed={selected}
              onClick={() => {
                setRangeId(item.id);
                setActivePeriod(null);
              }}
            >
              {selected && <motion.span className="trend-tabs__pill" layoutId="trend-range-pill" transition={springSnappy} />}
              <span className="trend-tabs__label">{item.label}</span>
            </button>
          );
        })}
      </div>

      <div className="trend-card__canvas">
        <ResponsiveContainer width="100%" height={168}>
          <AreaChart data={data} margin={{ top: 14, right: 18, left: 14, bottom: 0 }}>
            <defs>
              <linearGradient id="trendFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#2563eb" stopOpacity={0.26} />
                <stop offset="100%" stopColor="#2563eb" stopOpacity={0} />
              </linearGradient>
            </defs>
            <XAxis dataKey="label" hide />
            <YAxis hide domain={[0, Math.max(peak * 1.25, 1)]} />
            <Tooltip content={<ChartTooltip />} cursor={{ stroke: "var(--dash-line-strong)", strokeDasharray: "3 4" }} />
            <Area
              type="monotone"
              dataKey="tokens"
              stroke="var(--dash-ink)"
              strokeWidth={2.4}
              fill="url(#trendFill)"
              dot={false}
              activeDot={{ r: 4, fill: "var(--dash-ink)", stroke: "#fff", strokeWidth: 2 }}
              animationDuration={reduceMotion ? 0 : 1100}
              animationEasing="ease-out"
            />
            {/* Rendered as siblings, not inside a fragment: recharts inspects its
                direct children to place reference elements. */}
            {active && <ReferenceLine x={active.label} stroke="var(--dash-accent)" strokeDasharray="3 5" strokeOpacity={0.55} />}
            {active && <ReferenceDot x={active.label} y={active.tokens} r={6} fill="var(--dash-accent)" stroke="#fff" strokeWidth={3} />}
          </AreaChart>
        </ResponsiveContainer>
      </div>

      <div className="trend-months" role="group" aria-label="Elegir período">
        {data.map((point) => (
          <button
            key={point.period}
            type="button"
            aria-pressed={point.period === active?.period}
            onClick={() => setActivePeriod(point.period)}
          >
            {point.label}
          </button>
        ))}
      </div>
    </Panel>
  );
}
