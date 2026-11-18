"use client";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Layers3 } from "lucide-react";
import { useState } from "react";
import { ChartCard } from "./ChartCard";
import { EmptyState } from "../ui/EmptyState";
import { formatNumber } from "../../lib/formatters";

/** 12.000 -> "12k": keeps the axis narrow enough to never clip. */
function compactTokens(value: number) {
  return value >= 1000 ? `${Math.round(value / 100) / 10}k` : String(value);
}

export interface AreaUsageDatum {
  name: string;
  tokens: number;
  limit: number;
}

function ChartTooltip({ active, payload }: { active?: boolean; payload?: { payload: AreaUsageDatum }[] }) {
  if (!active || !payload?.length) return null;
  const item = payload[0].payload;
  const percent = item.limit > 0 ? Math.round((item.tokens / item.limit) * 100) : null;
  return (
    <div className="chart-tooltip">
      <strong>{item.name}</strong>
      <span>
        {formatNumber(item.tokens)} tokens
        {item.limit ? ` de ${formatNumber(item.limit)}` : ""}
      </span>
      {percent !== null && <span>{percent}% del límite del área</span>}
    </div>
  );
}

export function ConsumptionChart({ data }: { data: AreaUsageDatum[] }) {
  const [hovered, setHovered] = useState<number | null>(null);
  const hasData = data.length > 0 && data.some((item) => item.tokens > 0);
  const top = data.reduce((best, item) => (item.tokens > best.tokens ? item : best), { name: "", tokens: 0, limit: 0 });

  return (
    <ChartCard
      eyebrow="Consumo"
      title="Tokens por área"
      description="Distribución del uso del período en curso entre las áreas que podés ver."
      action={hasData ? <span className="ui-badge ui-badge--blue">Lidera {top.name}</span> : undefined}
    >
      {hasData ? (
        <div className="chart-canvas">
          <ResponsiveContainer width="100%" height={216}>
            <BarChart data={data} margin={{ top: 6, right: 6, left: 0, bottom: 0 }} barCategoryGap="34%" onMouseLeave={() => setHovered(null)}>
              <defs>
                <linearGradient id="barActive" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#4f8cf7" />
                  <stop offset="100%" stopColor="#2563eb" />
                </linearGradient>
              </defs>
              <CartesianGrid vertical={false} stroke="var(--dash-line)" strokeDasharray="4 6" />
              <XAxis dataKey="name" tickLine={false} axisLine={false} tick={{ fill: "var(--dash-muted)", fontSize: 11, fontWeight: 600 }} dy={6} />
              <YAxis tickLine={false} axisLine={false} tick={{ fill: "var(--dash-faint)", fontSize: 11 }} width={40} tickFormatter={compactTokens} />
              <Tooltip content={<ChartTooltip />} cursor={{ fill: "rgb(37 99 235 / .05)", radius: 10 }} />
              <Bar
                dataKey="tokens"
                radius={[10, 10, 4, 4]}
                animationDuration={950}
                animationEasing="ease-out"
                onMouseEnter={(_, index: number) => setHovered(index)}
              >
                {data.map((entry, index) => (
                  <Cell
                    key={entry.name}
                    fill={hovered === null || hovered === index ? "url(#barActive)" : "#d5e0f6"}
                    style={{ transition: "fill .25s ease" }}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <EmptyState
          icon={<Layers3 size={22} aria-hidden="true" />}
          title="Todavía no hay consumo"
          description="Cuando las áreas empiecen a usar tokens vas a ver la distribución acá."
        />
      )}
    </ChartCard>
  );
}
