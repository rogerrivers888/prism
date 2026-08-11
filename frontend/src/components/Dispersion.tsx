import { LENS_TEXT_CLASS, type LensCell, type LensName } from "../api/universe";
import { LENSES } from "../api/universe";

/** Which two lenses are pulling apart, alongside the number.
 *
 * 90 points of disagreement is not one situation. Ford at 90 is
 * value-high/quality-low — cheap and bad. A name at 89 could be
 * quality-high/value-low — excellent and expensive. Those are opposite
 * research questions, and the number alone cannot tell them apart, so the
 * two poles are shown with it. */
export function spread(
  lenses: Record<string, LensCell>,
  absolute: boolean,
): { high: LensName; low: LensName; value: number } | null {
  const usable = LENSES.map((lens) => {
    const cell = lenses[lens];
    if (!cell || !cell.applicable) return null;
    const score = absolute ? cell.score_absolute : cell.score;
    return score === null || score === undefined ? null : { lens, score };
  }).filter((entry): entry is { lens: LensName; score: number } => entry !== null);

  // Fewer than three usable readings is a coin toss, not a disagreement.
  if (usable.length < 3) return null;

  const sorted = [...usable].sort((a, b) => b.score - a.score);
  return {
    high: sorted[0].lens,
    low: sorted[sorted.length - 1].lens,
    value: sorted[0].score - sorted[sorted.length - 1].score,
  };
}

const SHORT: Record<LensName, string> = {
  trend: "Tr",
  growth: "Gr",
  quality: "Qu",
  value: "Va",
  momentum: "Mo",
  cycle: "Cy",
};

export function DispersionCell({
  lenses,
  absolute,
  fallback,
}: {
  lenses: Record<string, LensCell>;
  absolute: boolean;
  fallback: number | null | undefined;
}) {
  const detail = spread(lenses, absolute);

  if (!detail) {
    return (
      <span
        className="tabular text-sm text-text-muted"
        title="Fewer than three usable lenses — no honest disagreement figure"
      >
        {fallback === null || fallback === undefined ? "—" : fallback.toFixed(1)}
      </span>
    );
  }

  return (
    <span
      className="flex items-center justify-end gap-1.5"
      title={`${detail.high} highest, ${detail.low} lowest — ${detail.value.toFixed(1)} points apart`}
    >
      <span className="hidden text-[10px] leading-none sm:inline">
        <span className={LENS_TEXT_CLASS[detail.high]}>{SHORT[detail.high]}</span>
        <span className="text-text-muted">/</span>
        <span className={LENS_TEXT_CLASS[detail.low]}>{SHORT[detail.low]}</span>
      </span>
      <span className="tabular text-sm">{detail.value.toFixed(1)}</span>
    </span>
  );
}
