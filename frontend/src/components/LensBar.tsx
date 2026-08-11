import { LENS_BAR_CLASS, type LensCell, type LensName } from "../api/universe";

/** Density carries score alongside fill length.
 *
 * Bar length alone does not survive scanning: at a glance, a 91 and a 7 in
 * the same hue read as "some orange", and the eye has to measure. Varying
 * opacity AND chroma with the score makes a high score visibly denser and a
 * low one visibly washed out, so magnitude registers before you read the
 * number.
 *
 * Hue is untouched — it still means only which lens this is, never a verdict.
 * A weak value score is a pale version of the value hue, not a different
 * colour and certainly not red. */
function scoreOpacity(score: number): number {
  return 0.32 + (clamp(score) / 100) * 0.68;
}

function clamp(score: number): number {
  return Math.max(0, Math.min(100, score));
}

/** Chroma multiplier: low scores desaturate toward the surface, high scores
 *  reach full chroma. Applied via a CSS filter so the hue variable stays the
 *  single source of truth. */
function scoreSaturation(score: number): number {
  return 0.45 + (clamp(score) / 100) * 0.75;
}

type Props = {
  lens: LensName;
  cell: LensCell | undefined;
  /** false shows the peer-relative score, true the absolute band reading. */
  absolute: boolean;
  compact?: boolean;
};

export function LensBar({ lens, cell, absolute, compact = false }: Props) {
  const score = cell ? (absolute ? cell.score_absolute : cell.score) : null;

  // A lens that does not apply to this sector says so. It is not a zero and
  // not a blank — Cycle on a consumer staples name has nothing to report.
  if (cell && !cell.applicable) {
    return (
      <div
        className={compact ? "flex-1" : "flex items-center gap-2"}
        title={`${lens}: not applicable to this sector`}
      >
        <div className="h-5 flex-1 rounded-sm border border-dashed border-border" />
        {!compact && (
          <span className="tabular w-11 text-right text-xs text-text-muted">
            n/a
          </span>
        )}
      </div>
    );
  }

  // Coverage too thin to score. Showing 0 here would be a lie: it would read
  // as "scores badly" rather than "we could not measure it".
  if (score === null || score === undefined) {
    const coverage = cell ? Math.round(cell.coverage * 100) : 0;
    return (
      <div
        className={compact ? "flex-1" : "flex items-center gap-2"}
        title={`${lens}: no score — ${coverage}% coverage, below the 50% minimum`}
      >
        <div className="h-5 flex-1 rounded-sm bg-[repeating-linear-gradient(135deg,var(--border)_0_4px,transparent_4px_8px)] border border-border" />
        {!compact && (
          <span className="tabular w-11 text-right text-xs text-text-muted">
            {coverage}%
          </span>
        )}
      </div>
    );
  }

  const width = `${Math.max(2, Math.min(100, score))}%`;

  return (
    <div
      className={compact ? "flex-1" : "flex items-center gap-2"}
      title={`${lens}: ${score.toFixed(1)}`}
    >
      <div className="relative h-5 flex-1 overflow-hidden rounded-sm bg-surface-sunken">
        <div
          className={`absolute inset-y-0 left-0 ${LENS_BAR_CLASS[lens]}`}
          style={{
            width,
            opacity: scoreOpacity(score),
            filter: `saturate(${scoreSaturation(score)})`,
          }}
        />
      </div>
      {!compact && (
        <span className="tabular w-11 text-right text-xs text-text">
          {score.toFixed(1)}
        </span>
      )}
    </div>
  );
}

/** Phone layout: the six bars collapse to one strip rather than six columns. */
export function LensStrip({
  lenses,
  absolute,
}: {
  lenses: Record<string, LensCell>;
  absolute: boolean;
}) {
  return (
    <div className="flex gap-1">
      {(["trend", "growth", "quality", "value", "momentum", "cycle"] as LensName[]).map(
        (lens) => (
          <LensBar
            key={lens}
            lens={lens}
            cell={lenses[lens]}
            absolute={absolute}
            compact
          />
        ),
      )}
    </div>
  );
}
