import type { MetricSeries } from "../api/company";
import { LENS_STROKE_CLASS, type LensName } from "../api/universe";

/** Small multiples, not a shared axis.
 *
 * Metrics on this screen have incompatible units — a P/E of 19 and a ROIC of
 * 49% and days inventory of 126 share no scale. Forcing them onto one axis
 * would make the largest number flat-line everything else, so each series
 * gets its own panel scaled to its own range, with the range labelled. */
const SERIES_HUE: LensName[] = ["quality", "value", "growth", "momentum"];

export function MetricChart({ series }: { series: MetricSeries[] }) {
  if (series.length === 0) {
    return (
      <p className="text-sm text-text-muted">
        Pick up to four metrics to chart.
      </p>
    );
  }

  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {series.map((entry, index) => (
        <Panel key={entry.metric} entry={entry} hue={SERIES_HUE[index % 4]} />
      ))}
    </div>
  );
}

function Panel({ entry, hue }: { entry: MetricSeries; hue: LensName }) {
  const points = entry.points ?? [];

  if (entry.unavailable_reason) {
    return (
      <div className="rounded-md border border-border p-3">
        <h4 className="tabular text-xs font-medium">{entry.metric}</h4>
        <p className="mt-1 text-xs text-warning">{entry.unavailable_reason}</p>
        {entry.suggested_alternative && (
          <p className="mt-1 text-xs text-text-muted">
            Try <code className="tabular">{entry.suggested_alternative}</code> instead.
          </p>
        )}
      </div>
    );
  }

  if (points.length < 2) {
    return (
      <div className="rounded-md border border-border p-3">
        <h4 className="tabular text-xs font-medium">{entry.metric}</h4>
        <p className="mt-1 text-xs text-text-muted">
          Not enough history in this window to draw a line.
        </p>
      </div>
    );
  }

  const values = points.map(([, value]) => value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const width = 240;
  const height = 56;

  const path = points
    .map(([, value], index) => {
      const x = (index / (points.length - 1)) * width;
      const y = height - ((value - min) / span) * height;
      return `${index === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  const latest = values[values.length - 1];

  return (
    <div className="rounded-md border border-border p-3">
      <div className="flex items-baseline justify-between gap-2">
        <h4 className="tabular text-xs font-medium">{entry.metric}</h4>
        <span className="tabular text-sm">{latest.toFixed(2)}</span>
      </div>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="mt-2 h-14 w-full"
        preserveAspectRatio="none"
        role="img"
        aria-label={`${entry.metric} from ${points[0][0]} to ${points[points.length - 1][0]}`}
      >
        <path
          d={path}
          fill="none"
          strokeWidth={1.5}
          vectorEffect="non-scaling-stroke"
          className={LENS_STROKE_CLASS[hue]}
        />
      </svg>
      {/* Each panel labels its own range, since the scales are not shared. */}
      <div className="mt-1 flex justify-between text-[10px] text-text-muted">
        <span className="tabular">{min.toFixed(2)}</span>
        <span>{points[0][0]} → {points[points.length - 1][0]}</span>
        <span className="tabular">{max.toFixed(2)}</span>
      </div>
    </div>
  );
}
