import type { TokenUsage } from "./domain";

const MONTH_LABELS = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"];

export interface UsagePoint {
  period: string;
  label: string;
  tokens: number;
}

/** "2026-08" -> "Ago". Falls back to the raw period if it is not a valid month. */
export function periodLabel(period: string): string {
  const month = Number(period.slice(5, 7));
  return MONTH_LABELS[month - 1] ?? period;
}

/** Moves a "YYYY-MM" period by `offset` months (negative goes back in time). */
export function shiftPeriod(period: string, offset: number): string {
  const year = Number(period.slice(0, 4));
  const month = Number(period.slice(5, 7));
  const index = year * 12 + (month - 1) + offset;
  return `${String(Math.floor(index / 12)).padStart(4, "0")}-${String((index % 12) + 1).padStart(2, "0")}`;
}

/** The `count` periods ending at `current`, oldest first. */
export function recentPeriods(current: string, count: number): string[] {
  return Array.from({ length: count }, (_, index) => shiftPeriod(current, index - (count - 1)));
}

/**
 * Totals already-scoped usage rows into one point per period, so a chart can
 * render a continuous series even for months with no recorded consumption.
 */
export function buildUsageSeries(rows: TokenUsage[], periods: string[]): UsagePoint[] {
  const totals = new Map<string, number>(periods.map((period) => [period, 0]));
  for (const row of rows) {
    if (!totals.has(row.period)) continue;
    totals.set(row.period, (totals.get(row.period) ?? 0) + row.tokensUsed);
  }
  return periods.map((period) => ({ period, label: periodLabel(period), tokens: totals.get(period) ?? 0 }));
}

/** Percentage change between the last two points; null when there is no base to compare against. */
export function trendDelta(series: UsagePoint[]): number | null {
  if (series.length < 2) return null;
  const previous = series[series.length - 2].tokens;
  const current = series[series.length - 1].tokens;
  if (previous <= 0) return null;
  return Math.round(((current - previous) / previous) * 100);
}
