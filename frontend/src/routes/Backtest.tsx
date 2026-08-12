import { useState } from "react";
import {
  useRunBacktest,
  useRunSegments,
  useRunSweep,
  type BacktestResult,
  type Caveat,
  type Params,
  type Segment,
  type SegmentsResult,
  type SweepResult,
} from "../api/backtest";

/** Caveats render above the numbers, not below them.
 *
 *  The brief was explicit that results must carry their caveats rather than
 *  footnote them, and placement is the whole of that instruction: a warning
 *  under a table is read after the reader has already believed the table. */
function Caveats({ items }: { items: Caveat[] }) {
  if (!items.length) return null;
  const tone: Record<string, string> = {
    high: "border-l-warn bg-warn/10",
    medium: "border-l-muted bg-surface-2",
    low: "border-l-border bg-surface-2",
  };
  return (
    <div className="space-y-2">
      {items.map((caveat) => (
        <div
          key={caveat.title}
          className={`border-l-4 px-4 py-3 text-sm ${tone[caveat.severity] ?? tone.low}`}
        >
          <div className="flex items-baseline gap-2">
            <span className="font-mono text-[10px] uppercase tracking-wider text-muted">
              {caveat.severity}
            </span>
            <span className="font-medium text-fg">{caveat.title}</span>
          </div>
          <p className="mt-1 text-muted">{caveat.body}</p>
        </div>
      ))}
    </div>
  );
}

function Stat({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="border border-border bg-surface-2 px-3 py-2">
      <div className="font-mono text-[10px] uppercase tracking-wider text-muted">{label}</div>
      <div className="mt-1 font-mono text-lg tabular-nums text-fg">{value}</div>
      {hint ? <div className="mt-0.5 text-xs text-muted">{hint}</div> : null}
    </div>
  );
}

const pct = (value: number | null | undefined, digits = 3) =>
  value === null || value === undefined ? "—" : `${value >= 0 ? "+" : ""}${value.toFixed(digits)}%`;

/** A horizontal histogram of the trade distribution.
 *
 *  The brief asked for the distribution rather than just the average, and the
 *  reason shows here: the mean sits inside a spread running from roughly -6%
 *  to +6%, which is the fact that decides whether the mean is worth acting on. */
function Distribution({ distribution }: { distribution: Record<string, number> }) {
  const points: [string, number][] = [
    ["worst", distribution.worst],
    ["p5", distribution.p5],
    ["p25", distribution.p25],
    ["p50", distribution.p50],
    ["p75", distribution.p75],
    ["p95", distribution.p95],
    ["best", distribution.best],
  ];
  const bound = Math.max(...points.map(([, v]) => Math.abs(v ?? 0)), 1);
  return (
    <div className="space-y-1">
      {points.map(([label, value]) => (
        <div key={label} className="flex items-center gap-2 text-xs">
          <span className="w-10 shrink-0 font-mono text-muted">{label}</span>
          <div className="relative h-3 flex-1 bg-surface-2">
            <div className="absolute inset-y-0 left-1/2 w-px bg-border" />
            <div
              className={`absolute inset-y-0 ${value >= 0 ? "bg-accent" : "bg-warn"}`}
              style={{
                left: value >= 0 ? "50%" : `${50 - (Math.abs(value) / bound) * 50}%`,
                width: `${(Math.abs(value ?? 0) / bound) * 50}%`,
              }}
            />
          </div>
          <span className="w-16 shrink-0 text-right font-mono tabular-nums text-fg">
            {(value ?? 0).toFixed(2)}%
          </span>
        </div>
      ))}
    </div>
  );
}

function Breakdown({
  title,
  rows,
}: {
  title: string;
  rows: Record<string, { trades: number; mean_return_pct: number; win_rate: number }>;
}) {
  const entries = Object.entries(rows).sort((a, b) => b[1].mean_return_pct - a[1].mean_return_pct);
  return (
    <div>
      <h4 className="mb-2 font-mono text-[10px] uppercase tracking-wider text-muted">{title}</h4>
      <table className="w-full text-xs">
        <tbody>
          {entries.map(([key, row]) => (
            <tr key={key} className="border-b border-border/50">
              <td className="py-1 pr-2 text-fg">{key}</td>
              <td className="py-1 text-right font-mono tabular-nums text-muted">{row.trades}</td>
              <td className="py-1 pl-2 text-right font-mono tabular-nums text-fg">
                {pct(row.mean_return_pct)}
              </td>
              {/* n<30 is greyed with the count shown, as everywhere else. */}
              <td className="py-1 pl-2 text-right font-mono tabular-nums text-muted">
                {row.trades < 30 ? `n=${row.trades}` : `${(row.win_rate * 100).toFixed(0)}%`}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Results({ result }: { result: BacktestResult }) {
  const { overall, excess_over_drift_pct: excess, excess_significance: sig } = result;
  if (!overall.trades) {
    return <p className="text-sm text-muted">No trades matched these parameters.</p>;
  }
  const drift = result.control_unconditional_drift;

  return (
    <div className="space-y-6">
      <Caveats items={result.caveats} />

      {/* The headline is the excess, not the return. A long-only hold in a
          rising market earns something regardless of when it is placed, so the
          gross number answers a question nobody asked. */}
      <div className="border border-border bg-surface-2 p-4">
        <div className="font-mono text-[10px] uppercase tracking-wider text-muted">
          Excess over simply being long for the same number of days
        </div>
        <div className="mt-1 flex items-baseline gap-3">
          <span className="font-mono text-3xl tabular-nums text-fg">{pct(excess)}</span>
          <span className="text-sm text-muted">per trade</span>
        </div>
        {sig ? (
          <p className="mt-2 text-sm text-muted">
            90% bootstrap band {pct(sig.p5)} to {pct(sig.p95)}.{" "}
            {sig.inside_noise
              ? "That band contains zero, so this is not distinguishable from noise."
              : "That band excludes zero."}
            {result.variants_tested > 1
              ? ` ${result.variants_tested} parameter combinations were tested, so treat a single surviving variant with suspicion.`
              : ""}
          </p>
        ) : null}
      </div>

      <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
        <Stat label="Trades" value={overall.trades.toLocaleString()} />
        <Stat
          label="Mean net"
          value={pct(overall.mean_return_pct)}
          hint={`gross ${pct(overall.mean_gross_return_pct)}, costs ${overall.cost_drag_pct.toFixed(3)}%`}
        />
        <Stat label="Median net" value={pct(overall.median_return_pct)} />
        <Stat label="Win rate" value={`${(overall.win_rate * 100).toFixed(1)}%`} />
        <Stat label="Expectancy (R)" value={overall.expectancy_r.toFixed(4)} />
        <Stat label="Std dev" value={`${overall.stdev_pct.toFixed(2)}%`} />
        <Stat
          label="Max drawdown"
          value={`${overall.max_drawdown_pct.toFixed(1)}%`}
          hint="sequence sketch, not a portfolio"
        />
        <Stat
          label="Drift control"
          value={pct(drift?.mean_return_pct)}
          hint={drift ? `${drift.samples.toLocaleString()} random holds` : undefined}
        />
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <div>
          <h3 className="mb-2 text-sm font-medium text-fg">Distribution of trade returns</h3>
          <Distribution distribution={overall.distribution} />
          <p className="mt-2 text-xs text-muted">
            Mean holding period {overall.mean_holding_days} days.{" "}
            {overall.caught_by_early_report.toLocaleString()} trades were closed early because the
            company reported sooner than expected.
          </p>
        </div>
        <div className="space-y-4">
          {Object.entries(result.breakdowns).map(([name, rows]) => (
            <Breakdown key={name} title={name.replace(/_/g, " ")} rows={rows} />
          ))}
        </div>
      </div>

      <div className="border-t border-border pt-3 text-xs text-muted">
        Expected report date missed the actual by a median of{" "}
        {result.expectation_error_days.median ?? "—"} days;{" "}
        {result.expectation_error_days.within_2_days !== null
          ? `${(result.expectation_error_days.within_2_days * 100).toFixed(0)}% landed within two days.`
          : ""}{" "}
        Skipped:{" "}
        {Object.entries(result.skipped)
          .map(([key, value]) => `${key.replace(/_/g, " ")} ${value}`)
          .join(", ")}
        .
      </div>
    </div>
  );
}

function SweepTable({ sweep }: { sweep: SweepResult }) {
  return (
    <div className="space-y-3">
      <div className="border-l-4 border-l-warn bg-warn/10 px-4 py-3 text-sm">
        <div className="font-medium text-fg">
          {sweep.variants_tested} variants tested
        </div>
        <p className="mt-1 text-muted">
          {sweep.verdict.negative_variants} of {sweep.verdict.total_variants} produced a negative
          excess over drift, and the mean across all variants is{" "}
          {pct(sweep.verdict.mean_excess_pct)}.{" "}
          {sweep.verdict.coherent
            ? "The variants agree in sign, which is what a real effect looks like."
            : "The sign flips between adjacent parameter settings. A real effect varies smoothly with the parameter; noise changes sign. Read the best variant as the best of several draws, not as a finding."}
        </p>
      </div>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-left font-mono text-[10px] uppercase tracking-wider text-muted">
            <th className="py-1">Enter</th>
            <th className="py-1">Exit</th>
            <th className="py-1 text-right">Trades</th>
            <th className="py-1 text-right">Mean</th>
            <th className="py-1 text-right">Drift</th>
            <th className="py-1 text-right">Excess</th>
            <th className="py-1 text-right">90% band</th>
          </tr>
        </thead>
        <tbody>
          {sweep.variants.map((variant) => {
            const isBest =
              sweep.best &&
              variant.enter_days_before === sweep.best.enter_days_before &&
              variant.exit_days_before === sweep.best.exit_days_before;
            return (
              <tr
                key={`${variant.enter_days_before}-${variant.exit_days_before}`}
                className={`border-b border-border/50 ${isBest ? "bg-surface-2" : ""}`}
              >
                <td className="py-1 font-mono tabular-nums">{variant.enter_days_before}d</td>
                <td className="py-1 font-mono tabular-nums">{variant.exit_days_before}d</td>
                <td className="py-1 text-right font-mono tabular-nums text-muted">
                  {variant.trades.toLocaleString()}
                </td>
                <td className="py-1 text-right font-mono tabular-nums">
                  {pct(variant.mean_return_pct)}
                </td>
                <td className="py-1 text-right font-mono tabular-nums text-muted">
                  {pct(variant.drift_pct)}
                </td>
                <td className="py-1 text-right font-mono tabular-nums text-fg">
                  {pct(variant.excess_over_drift_pct)}
                </td>
                <td className="py-1 text-right font-mono text-xs tabular-nums text-muted">
                  {variant.excess_significance
                    ? `${pct(variant.excess_significance.p5)} ${pct(variant.excess_significance.p95)}`
                    : "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

const FAMILY_LABEL: Record<string, string> = {
  sector: "Sector",
  market_cap_quintile: "Market cap quintile",
  lens_dispersion: "Lens disagreement",
  valuation_premium: "Valuation premium vs sector",
  priced_for_perfection: "Priced for perfection",
  realised_vol_quintile: "Realised volatility quintile",
};

function SegmentRow({ row }: { row: Segment }) {
  return (
    <tr className="border-b border-border/50">
      <td className="py-1 pr-2">
        {row.segment}
        {row.underpowered ? (
          <span className="ml-2 font-mono text-[10px] uppercase text-muted">underpowered</span>
        ) : null}
      </td>
      {/* Sample size sits next to the name, not at the end, because it is the
          first thing that decides whether the rest of the row means anything. */}
      <td className={`py-1 text-right font-mono tabular-nums ${row.underpowered ? "text-muted" : "text-fg"}`}>
        {row.trades.toLocaleString()}
      </td>
      <td className="py-1 text-right font-mono tabular-nums text-muted">{pct(row.drift_pct)}</td>
      <td className={`py-1 text-right font-mono tabular-nums ${row.underpowered ? "text-muted" : "text-fg"}`}>
        {pct(row.excess_pct)}
      </td>
      <td className="py-1 text-right font-mono text-xs tabular-nums text-muted">
        {pct(row.p5)} {pct(row.p95)}
      </td>
      <td className="py-1 text-right font-mono text-xs tabular-nums text-muted">
        {row.p_value.toFixed(4)}
      </td>
      <td className="py-1 pl-2 text-right font-mono text-[10px] uppercase tracking-wider">
        {row.significant_bonferroni ? (
          <span className="text-fg">bonf</span>
        ) : row.significant_fdr ? (
          <span className="text-fg">fdr</span>
        ) : row.significant_uncorrected ? (
          <span className="text-muted">uncorr only</span>
        ) : (
          <span className="text-muted">—</span>
        )}
      </td>
    </tr>
  );
}

function Segments({ result }: { result: SegmentsResult }) {
  const families = Array.from(new Set(result.segments.map((s) => s.family)));
  const { correction: c } = result;
  const isolated = Object.entries(result.neighbour_agreement).filter(([, v]) => v.isolated);

  return (
    <div className="space-y-5">
      {/* The count of tests leads. Reading one row out of thirty as if it were
          one test is the failure mode this whole screen exists to prevent. */}
      <div className="border-l-4 border-l-warn bg-warn/10 px-4 py-3 text-sm">
        <div className="font-medium text-fg">{result.segment_tests_run} segment tests were run</div>
        <p className="mt-1 text-muted">
          At an uncorrected 5% threshold, roughly{" "}
          {c.expected_false_positives_uncorrected} of them would look significant by chance alone.{" "}
          {c.significant_uncorrected} did. After Benjamini-Hochberg FDR control,{" "}
          {c.significant_fdr} survive; at Bonferroni ({c.bonferroni_alpha.toFixed(5)}),{" "}
          {c.significant_bonferroni} do. Any single row below is one of{" "}
          {result.segment_tests_run}, not one test.
        </p>
      </div>

      {isolated.length ? (
        <div className="border-l-4 border-l-warn bg-warn/10 px-4 py-3 text-sm">
          <div className="font-medium text-fg">
            Positive but isolated: {isolated.map(([name]) => name).join(", ")}
          </div>
          <p className="mt-1 text-muted">
            No adjacent sector agrees in sign. A real effect in one sector should echo, weaker, in
            its neighbours; one that appears in exactly one place and nowhere next door is noise
            wearing a sector label.
          </p>
        </div>
      ) : null}

      {families.map((family) => (
        <div key={family}>
          <h4 className="mb-1 font-mono text-[10px] uppercase tracking-wider text-muted">
            {FAMILY_LABEL[family] ?? family}
          </h4>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left font-mono text-[10px] uppercase tracking-wider text-muted">
                <th className="py-1">Segment</th>
                <th className="py-1 text-right">Trades</th>
                <th className="py-1 text-right">Drift</th>
                <th className="py-1 text-right">Excess</th>
                <th className="py-1 text-right">90% band</th>
                <th className="py-1 text-right">p</th>
                <th className="py-1 pl-2 text-right">Survives</th>
              </tr>
            </thead>
            <tbody>
              {result.segments
                .filter((s) => s.family === family)
                .sort((a, b) => b.excess_pct - a.excess_pct)
                .map((row) => (
                  <SegmentRow key={`${row.family}-${row.segment}`} row={row} />
                ))}
            </tbody>
          </table>
        </div>
      ))}

      <p className="border-t border-border pt-3 text-xs text-muted">
        Each segment is compared against a control drawn from the same names that produced its
        trades ({result.control_pool.tickers} tickers, {result.control_pool.draws_each} random{" "}
        {result.holding_days}-day holds each), so a volatile segment is not credited for being
        volatile. Market-cap quintiles use today's market cap, not the cap at the time of each
        trade — that is a known limitation, and it biases toward classifying past winners as large.
      </p>
    </div>
  );
}

const DEFAULTS: Params = {
  enter_days_before: 10,
  exit_days_before: 2,
  start: "2010-01-01",
  end: "2026-08-01",
  spread_bps: 10,
  commission_bps: 5,
};

function Field({
  label,
  value,
  onChange,
  type = "number",
  hint,
}: {
  label: string;
  value: string | number;
  onChange: (value: string) => void;
  type?: string;
  hint?: string;
}) {
  return (
    <label className="block">
      <span className="font-mono text-[10px] uppercase tracking-wider text-muted">{label}</span>
      <input
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="mt-1 w-full border border-border bg-surface px-2 py-1 font-mono text-sm tabular-nums text-fg focus:border-accent focus:outline-none"
      />
      {hint ? <span className="mt-0.5 block text-[10px] text-muted">{hint}</span> : null}
    </label>
  );
}

export default function Backtest() {
  const [params, setParams] = useState<Params>(DEFAULTS);
  const run = useRunBacktest();
  const sweep = useRunSweep();
  const segments = useRunSegments();

  const set = (key: keyof Params) => (value: string) =>
    setParams((previous) => ({
      ...previous,
      [key]: key === "start" || key === "end" ? value : Number(value),
    }));

  const invalid = params.enter_days_before <= params.exit_days_before;

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <header>
        <h1 className="font-display text-2xl uppercase tracking-wide text-fg">Backtest</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted">
          Buy a fixed number of days before a company is <em>expected</em> to report, sell before it
          does, never hold through the announcement. The entry uses the report date as it was
          forecastable at the time from prior reporting history — not the date that actually
          happened.
        </p>
      </header>

      <div className="grid grid-cols-2 gap-3 border border-border bg-surface-2 p-4 md:grid-cols-6">
        <Field
          label="Enter (days before)"
          value={params.enter_days_before}
          onChange={set("enter_days_before")}
        />
        <Field
          label="Exit (days before)"
          value={params.exit_days_before}
          onChange={set("exit_days_before")}
        />
        <Field label="Start" value={params.start} onChange={set("start")} type="date" />
        <Field label="End" value={params.end} onChange={set("end")} type="date" />
        <Field
          label="Spread (bps)"
          value={params.spread_bps}
          onChange={set("spread_bps")}
          hint="paid twice"
        />
        <Field
          label="Commission (bps)"
          value={params.commission_bps}
          onChange={set("commission_bps")}
          hint="paid twice"
        />
      </div>

      {invalid ? (
        <p className="text-sm text-warn">Entry must be earlier than exit.</p>
      ) : null}

      <div className="flex gap-2">
        <button
          type="button"
          disabled={invalid || run.isPending}
          onClick={() => run.mutate(params)}
          className="border border-accent bg-accent px-4 py-2 text-sm font-medium text-surface disabled:opacity-40"
        >
          {run.isPending ? "Running…" : "Run backtest"}
        </button>
        <button
          type="button"
          disabled={sweep.isPending}
          onClick={() =>
            sweep.mutate({
              enter_days: [5, 10, 20],
              exit_days: [1, 3],
              start: params.start,
              end: params.end,
            })
          }
          className="border border-border px-4 py-2 text-sm text-fg disabled:opacity-40"
        >
          {sweep.isPending ? "Sweeping…" : "Sweep 6 variants"}
        </button>
        <button
          type="button"
          disabled={invalid || segments.isPending}
          onClick={() => segments.mutate(params)}
          className="border border-border px-4 py-2 text-sm text-fg disabled:opacity-40"
        >
          {segments.isPending ? "Segmenting…" : "Segment by sector, size and froth"}
        </button>
      </div>

      {run.isPending || sweep.isPending || segments.isPending ? (
        <p className="text-sm text-muted">
          Walking every ticker's price history. This takes a minute or two.
        </p>
      ) : null}
      {run.error ? <p className="text-sm text-warn">{run.error.message}</p> : null}
      {sweep.error ? <p className="text-sm text-warn">{sweep.error.message}</p> : null}
      {segments.error ? <p className="text-sm text-warn">{segments.error.message}</p> : null}

      {segments.data ? <Segments result={segments.data} /> : null}

      {sweep.data ? <SweepTable sweep={sweep.data} /> : null}
      {run.data ? <Results result={run.data} /> : null}
    </div>
  );
}
