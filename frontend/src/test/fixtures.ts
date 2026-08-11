import type { UniverseOut, UniverseRow } from "../api/universe";

function cell(score: number | null, absolute: number | null, coverage = 1, applicable = true) {
  return { score, score_absolute: absolute, coverage, applicable };
}

export const ROWS: UniverseRow[] = [
  {
    ticker: "MU", name: "Micron Technology", sector: "semiconductors",
    subsector: "Semiconductors", size: "mega", currency: "USD",
    quote_currency: "USD", market_cap: 9e11, dispersion: 28.9, usable_lenses: 6,
    lenses: {
      trend: cell(81.6, 78.9), growth: cell(93.7, 100), quality: cell(80.9, 92.4),
      // Relative and absolute differ sharply — this is the toggle's whole point.
      value: cell(64.8, 34.2), momentum: cell(88.2, 94.6), cycle: cell(80.7, 66.5),
    },
  },
  {
    ticker: "THIN", name: "Sparse Data Co", sector: "industrials",
    subsector: "Conglomerates", size: "mid", currency: "USD",
    quote_currency: "USD", market_cap: 5e9, dispersion: null, usable_lenses: 2,
    lenses: {
      // Coverage below the minimum: a null score, NOT a zero.
      trend: cell(null, null, 0.4), growth: cell(null, null, 0.2),
      quality: cell(55.0, 50.0), value: cell(45.0, 40.0),
      momentum: cell(null, null, 0.25),
      // Cycle does not apply outside cyclical sectors.
      cycle: cell(null, null, 0, false),
    },
  },
  {
    ticker: "MID", name: "Middling Industries", sector: "industrials",
    subsector: "Railroads", size: "large", currency: "USD",
    quote_currency: "USD", market_cap: 5e10, dispersion: 12.5, usable_lenses: 5,
    lenses: {
      trend: cell(50, 60), growth: cell(52, 62), quality: cell(48, 58),
      value: cell(55, 65), momentum: cell(51, 61), cycle: cell(null, null, 0, false),
    },
  },
];

export const UNIVERSE: UniverseOut = {
  as_of: "2026-08-11",
  scoring_version: "v2",
  computed_at: "2026-08-11T17:03:45Z",
  stale_days: 0,
  count: ROWS.length,
  rows: ROWS,
};
