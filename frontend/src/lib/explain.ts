/** Plain English for every number in Prism.
 *
 * The rule this file enforces: a figure never stands alone. Roger is an
 * intermediate investor with no statistics background, and his verdict on the
 * platform was "I have no idea how to use this". A number he cannot read is
 * worse than no number, because it looks like information.
 *
 * Two things every translation must carry:
 *   1. What the number MEANS in money or plain outcomes, not what it is called.
 *   2. Over what period, or per what. A return with no duration is unreadable —
 *      "+645%" is meaningless until you know it took fifteen years.
 *
 * These are deliberately verbose. Terseness is what broke the old screens.
 */

const POSITION = 10_000;

export const money = (pounds: number) =>
  `£${Math.round(Math.abs(pounds)).toLocaleString()}`;

/** Years between two ISO dates, for turning totals into yearly rates. */
export function yearsBetween(start?: string | null, end?: string | null): number | null {
  if (!start || !end) return null;
  const a = new Date(start).getTime();
  const b = new Date(end).getTime();
  if (Number.isNaN(a) || Number.isNaN(b) || b <= a) return null;
  return (b - a) / (365.25 * 24 * 60 * 60 * 1000);
}

/** Compound a total return down to a yearly rate.
 *
 *  This is the maths that surprised Roger: 11% a year for 15 years really does
 *  make +645%, because each year builds on the last. Wherever both figures
 *  appear, they are shown together so the relationship is visible rather than
 *  looking like a contradiction.
 */
export function annualised(totalPct: number, years: number | null): number | null {
  if (!years || years <= 0) return null;
  const growth = 1 + totalPct / 100;
  if (growth <= 0) return null;
  return (Math.pow(growth, 1 / years) - 1) * 100;
}

export function windowLabel(start?: string | null, end?: string | null): string {
  const years = yearsBetween(start, end);
  if (!start || !end) return "";
  const from = start.slice(0, 4);
  const to = end.slice(0, 4);
  return years ? `${from}–${to}, ${years.toFixed(0)} years` : `${from}–${to}`;
}

/** Total return, always with its duration and its yearly equivalent. */
export function explainTotalReturn(
  totalPct: number | null | undefined,
  start?: string | null,
  end?: string | null,
): string {
  if (totalPct === null || totalPct === undefined) return "Not enough history to say.";
  const years = yearsBetween(start, end);
  const perYear = annualised(totalPct, years);
  const span = windowLabel(start, end);
  if (perYear === null) {
    return `${totalPct >= 0 ? "Grew" : "Fell"} ${Math.abs(totalPct).toFixed(0)}% in total.`;
  }
  return (
    `${totalPct >= 0 ? "+" : ""}${totalPct.toFixed(0)}% in total over ${span} — ` +
    `about ${perYear >= 0 ? "" : "−"}${Math.abs(perYear).toFixed(0)}% a year. ` +
    `${Math.abs(perYear).toFixed(0)}% a year compounds to ${Math.abs(totalPct).toFixed(0)}% ` +
    `because each year builds on the one before.`
  );
}

/** Expectancy in R. The unit nobody understands until it is pounds. */
export function explainExpectancy(r: number | null | undefined): string {
  if (r === null || r === undefined) return "Not enough completed trades to say.";
  const pence = Math.round(Math.abs(r) * 100);
  if (r >= 0) {
    return `for every £1 risked, this made ${pence}p on average across all its trades, winners and losers together`;
  }
  return `for every £1 risked, this LOST ${pence}p on average across all its trades`;
}

/** Excess over the control. Per trade, not per year — saying "a year" would
 *  be easier to read and would be false. */
export function explainEdge(
  excessPct: number | null | undefined,
  trades?: number | null,
): string {
  if (excessPct === null || excessPct === undefined) return "No comparison available yet.";
  const pounds = money((excessPct / 100) * POSITION);
  const context = trades ? ` across ${trades.toLocaleString()} test trades` : "";
  if (excessPct <= 0) {
    return (
      `Did WORSE than picking companies at random from the same list, by ` +
      `${Math.abs(excessPct).toFixed(2)}% on each trade${context}. Picking at random would have done better.`
    );
  }
  return (
    `Beat picking companies at random from the same list by ${excessPct.toFixed(2)}% ` +
    `on each trade${context} — about ${pounds} per ${money(POSITION)} put in, per trade.`
  );
}

export function explainWinRate(rate: number | null | undefined): string {
  if (rate === null || rate === undefined) return "No completed trades yet.";
  return `made money on about ${Math.round(rate * 100)} trades in every 100`;
}

export function explainDrawdown(pct: number | null | undefined): string {
  if (pct === null || pct === undefined) return "No history to measure yet.";
  const drop = Math.abs(pct);
  return (
    `at its worst point you would have been down ${drop.toFixed(0)}% from the highest ` +
    `value reached — ${money((drop / 100) * 100_000)} of a ${money(100_000)} pot, ` +
    `before it recovered`
  );
}

export function explainCosts(pct: number | null | undefined): string {
  if (pct === null || pct === undefined) return "No trades yet, so nothing paid in fees.";
  return (
    `${pct.toFixed(2)}% of the pot has gone on the cost of buying and selling — ` +
    `${money((pct / 100) * 100_000)} out of ${money(100_000)}`
  );
}

/** A per-trade percentage in pounds on a position someone might take. */
export function explainPerTrade(pct: number | null | undefined): string {
  if (pct === null || pct === undefined) return "No completed trades yet.";
  const pounds = money((pct / 100) * POSITION);
  const direction = pct >= 0 ? "made" : "lost";
  return `the average trade ${direction} ${Math.abs(pct).toFixed(2)}% — ${pounds} on a ${money(POSITION)} position`;
}

export function explainLensScore(score: number | null | undefined, lens: string): string {
  if (score === null || score === undefined) {
    return `No ${lens} score — not enough of the underlying data was available, so Prism refuses to guess.`;
  }
  const band =
    score >= 80 ? "very strong" : score >= 60 ? "above average" :
    score >= 40 ? "middling" : score >= 20 ? "weak" : "very weak";
  return `${score.toFixed(0)} out of 100 — ${band} on this measure compared with others in its industry. Not a buy or sell signal.`;
}

export function explainDispersion(value: number | null | undefined): string {
  if (value === null || value === undefined) return "Not enough scores to compare.";
  const band = value >= 60 ? "The six views disagree sharply" :
    value >= 30 ? "The six views disagree somewhat" : "The six views broadly agree";
  return `${band} about this company (${value.toFixed(0)} points between the highest and lowest score). Disagreement means something needs explaining — it is not a signal to buy.`;
}

/** Sample-size honesty, in words rather than a count. */
export function explainSample(n: number, unit = "trades"): string {
  if (n === 0) return `No ${unit} yet.`;
  if (n < 30) return `Only ${n} ${unit} — far too few to mean anything. Treat this as a story, not evidence.`;
  if (n < 100) return `${n} ${unit} — a small sample. Suggestive at best.`;
  return `${n.toLocaleString()} ${unit}.`;
}

/** Risk in R for the book: what one position can lose. */
export function explainRisk(riskPct: number | null | undefined): string {
  if (riskPct === null || riskPct === undefined) return "No stop set, so the loss is not capped.";
  return `if the stop is hit you lose ${riskPct.toFixed(1)}% of the pot on this position`;
}
