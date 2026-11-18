import { formatNumber } from "../../lib/formatters";

export interface UsageSegment {
  label: string;
  value: number;
}

export function UsageProgress({ used, limit, segments }: { used: number; limit: number; segments?: UsageSegment[] }) {
  const pct = limit > 0 ? Math.min(100, Math.round((used / limit) * 100)) : 0;
  return (
    <div className="usage-progress">
      <div className="usage-progress__track" role="img" aria-label={`${formatNumber(used)} de ${formatNumber(limit)} tokens utilizados`}>
        <span className="usage-progress__fill" style={{ width: `${pct}%` }} />
      </div>
      {segments && segments.length > 0 && (
        <div className="usage-progress__segments">
          {segments.map((segment) => (
            <div className="usage-progress__segment" key={segment.label}>
              <span>{segment.label}</span>
              <strong>{formatNumber(segment.value)}</strong>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
