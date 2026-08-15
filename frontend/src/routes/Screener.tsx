import { useEffect, useMemo, useState } from "react";
import { NothingYet, PagePurpose } from "../components/PagePurpose";
import { useRegisterScreen } from "../components/ScreenContext";
import { markDone } from "../lib/progress";
import { useNavigate } from "react-router-dom";
import { LENSES, useUniverse, type UniverseRow } from "../api/universe";
import { useWatchlist, useWatchToggle } from "../api/screens";
import { LensStrip } from "../components/LensBar";
import { sectorsOf } from "../lib/universe-view";

type Range = { min: number | null; max: number | null };
const EMPTY: Range = { min: null, max: null };

export function Screener() {
  const navigate = useNavigate();
  const { data } = useUniverse();
  const watchlist = useWatchlist();
  const toggle = useWatchToggle();

  const [absolute, setAbsolute] = useState(false);
  const [lensRanges, setLensRanges] = useState<Record<string, Range>>({});
  const [capRange, setCapRange] = useState<Range>(EMPTY);
  const [earningsRange, setEarningsRange] = useState<Range>(EMPTY);
  const [sectors, setSectors] = useState<Set<string>>(new Set());
  const [excluded, setExcluded] = useState<Set<string>>(new Set());

  const rows = data?.rows ?? [];
  const allSectors = useMemo(() => sectorsOf(rows), [rows]);
  const watched = new Set((watchlist.data ?? []).map((w) => w.ticker));

  const results = useMemo(() => {
    return rows.filter((row) => {
      if (excluded.has(row.ticker)) return false;
      if (sectors.size && !sectors.has(row.sector)) return false;
      const cap = row.market_cap ? row.market_cap / 1e9 : null;
      if (capRange.min !== null && (cap === null || cap < capRange.min)) return false;
      if (capRange.max !== null && (cap === null || cap > capRange.max)) return false;

      // A row with no known report date is excluded whenever the filter is
      // active. It cannot satisfy a window we have no date for, and treating
      // unknown as "passes" would quietly pad the result with names that
      // happen to be missing data.
      const days = row.days_to_earnings;
      if (earningsRange.min !== null && (days === null || days === undefined || days < earningsRange.min))
        return false;
      if (earningsRange.max !== null && (days === null || days === undefined || days > earningsRange.max))
        return false;
      for (const [lens, range] of Object.entries(lensRanges)) {
        if (range.min === null && range.max === null) continue;
        const cell = row.lenses[lens];
        const score = cell ? (absolute ? cell.score_absolute : cell.score) : null;
        if (score === null || score === undefined) return false;
        if (range.min !== null && score < range.min) return false;
        if (range.max !== null && score > range.max) return false;
      }
      return true;
    });
  }, [rows, sectors, capRange, earningsRange, lensRanges, absolute, excluded]);

  const filtersActive =
    sectors.size > 0 || excluded.size > 0 ||
    capRange.min !== null || capRange.max !== null ||
    earningsRange.min !== null || earningsRange.max !== null ||
    Object.values(lensRanges).some((r) => r.min !== null || r.max !== null);

  // Side effect, not render: ticking the checklist during render would fire on
  // every keystroke and violates React's rules besides.
  useEffect(() => {
    if (filtersActive) markDone("ran_screen");
  }, [filtersActive]);

  useRegisterScreen(
    "Screener",
    { matching: results.length, of: rows.length, filters_in_use: filtersActive,
      scores_shown: absolute ? "absolute" : "relative to industry" },
    [
      "How do I use this page to build a shortlist?",
      "What is a sensible first filter to try?",
      "Why do relative and absolute give different answers?",
    ],
  );

  const setRange = (lens: string, key: "min" | "max", raw: string) =>
    setLensRanges((current) => ({
      ...current,
      [lens]: { ...(current[lens] ?? EMPTY), [key]: raw === "" ? null : Number(raw) },
    }));

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-border px-4 py-3 sm:px-6">
        <div className="flex flex-wrap items-baseline gap-x-4">
          <h1 className="font-display text-3xl font-semibold tracking-tight">Screener</h1>
          {/* Live count, so the effect of a filter is visible as it's typed. */}
          <p className="text-sm text-text-muted">
            <span className="tabular">{results.length}</span> of {rows.length} companies match
            {excluded.size > 0 && ` · ${excluded.size} you removed by hand`}
          </p>
          <div className="ml-auto flex overflow-hidden rounded-md border border-border">
            <button type="button" onClick={() => setAbsolute(false)} aria-pressed={!absolute}
              className={`px-3 py-1 text-xs ${!absolute ? "bg-surface-sunken font-medium" : "text-text-muted"}`}
              title="Score each company against others in its own industry">vs its industry</button>
            <button type="button" onClick={() => setAbsolute(true)} aria-pressed={absolute}
              className={`px-3 py-1 text-xs ${absolute ? "bg-surface-sunken font-medium" : "text-text-muted"}`}
              title="Score each company against fixed standards that do not move">vs fixed standards</button>
          </div>
        </div>

        <div className="mt-3 max-w-3xl">
          <PagePurpose
            id="screener"
            title="Screener"
            what="A way of going from hundreds of companies to a shortlist. Set the minimum and maximum score you will accept on any of the six measures, and only the companies that match stay on screen."
            firstStep="typing 60 in the 'min' box next to quality, and 50 next to value. That asks for decent businesses at sane prices — about the simplest useful screen there is. Then click a company to look into it."
          />
        </div>

        <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          {LENSES.map((lens) => (
            <label key={lens} className="flex items-center gap-1 text-xs">
              <span className="w-16 shrink-0 text-text-muted">{lens}</span>
              <input type="number" placeholder="min" aria-label={`${lens} minimum`}
                onChange={(e) => setRange(lens, "min", e.target.value)}
                className="tabular h-7 w-full rounded border border-border bg-surface-raised px-1" />
              <input type="number" placeholder="max" aria-label={`${lens} maximum`}
                onChange={(e) => setRange(lens, "max", e.target.value)}
                className="tabular h-7 w-full rounded border border-border bg-surface-raised px-1" />
            </label>
          ))}
          <label className="flex items-center gap-1 text-xs">
            <span className="w-16 shrink-0 text-text-muted">cap £bn</span>
            <input type="number" placeholder="min" aria-label="market cap minimum"
              onChange={(e) => setCapRange((c) => ({ ...c, min: e.target.value === "" ? null : Number(e.target.value) }))}
              className="tabular h-7 w-full rounded border border-border bg-surface-raised px-1" />
            <input type="number" placeholder="max" aria-label="market cap maximum"
              onChange={(e) => setCapRange((c) => ({ ...c, max: e.target.value === "" ? null : Number(e.target.value) }))}
              className="tabular h-7 w-full rounded border border-border bg-surface-raised px-1" />
          </label>

          <label className="flex items-center gap-1 text-xs">
            <span className="w-16 shrink-0 text-text-muted" title="Days until the company next reports its results">days to results</span>
            <input type="number" placeholder="min" aria-label="days to earnings minimum"
              onChange={(e) => setEarningsRange((c) => ({ ...c, min: e.target.value === "" ? null : Number(e.target.value) }))}
              className="tabular h-7 w-full rounded border border-border bg-surface-raised px-1" />
            <input type="number" placeholder="max" aria-label="days to earnings maximum"
              onChange={(e) => setEarningsRange((c) => ({ ...c, max: e.target.value === "" ? null : Number(e.target.value) }))}
              className="tabular h-7 w-full rounded border border-border bg-surface-raised px-1" />
          </label>
        </div>

        <div className="mt-2 flex flex-wrap gap-1">
          {allSectors.map((sector) => (
            <button key={sector} type="button" aria-pressed={sectors.has(sector)}
              onClick={() => setSectors((c) => { const n = new Set(c); n.has(sector) ? n.delete(sector) : n.add(sector); return n; })}
              className={`rounded-full border px-2 py-0.5 text-[11px] ${sectors.has(sector) ? "border-border-strong bg-surface-sunken" : "border-border text-text-muted"}`}>
              {sector.replace(/_/g, " ")}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-auto">
        {rows.length > 0 && results.length === 0 && (
          <div className="p-6">
            <NothingYet
              headline="No companies match what you asked for"
              because="The filters are too tight — nothing scores that well on everything at once. Try relaxing whichever minimum you set highest; asking for top marks on several measures at the same time usually returns nothing."
            />
          </div>
        )}
        {results.slice(0, 200).map((row: UniverseRow) => (
          <div key={row.ticker} className="flex items-center gap-3 border-b border-border px-4 py-2 sm:px-6">
            <button type="button" onClick={() => navigate(`/company/${row.ticker}`)}
              className="w-36 shrink-0 text-left">
              <span className="tabular block text-sm font-medium">{row.ticker}</span>
              <span className="block truncate text-[11px] text-text-muted">{row.name}</span>
            </button>
            <div className="min-w-0 flex-1"><LensStrip lenses={row.lenses} absolute={absolute} /></div>
            <button type="button" onClick={() => toggle.mutate({ ticker: row.ticker, watched: watched.has(row.ticker) })}
              className={`shrink-0 rounded border px-2 py-0.5 text-[11px] ${watched.has(row.ticker) ? "border-border-strong bg-surface-sunken" : "border-border text-text-muted"}`}>
              {watched.has(row.ticker) ? "watching" : "watch"}
            </button>
            <button type="button" onClick={() => setExcluded((c) => new Set(c).add(row.ticker))}
              aria-label={`Exclude ${row.ticker}`} className="shrink-0 text-xs text-text-muted hover:text-text">✕</button>
          </div>
        ))}
        {results.length > 200 && (
          <p className="px-6 py-3 text-xs text-text-muted">
            Showing the first 200 of {results.length}. Narrow the filters to see the rest.
          </p>
        )}
      </div>
    </div>
  );
}
