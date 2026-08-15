import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useStrategy } from "../api/strategies";
import { useGlossary } from "../components/GlossaryProvider";
import { PromoteFlow } from "../components/PromoteFlow";
import { useRegisterScreen } from "../components/ScreenContext";
import {
  annualised,
  explainDrawdown,
  explainEdge,
  explainPerTrade,
  explainTotalReturn,
  explainWinRate,
  windowLabel,
  yearsBetween,
} from "../lib/explain";
import { markDone } from "../lib/progress";

const pct = (v: number | null | undefined, digits = 2) =>
  v === null || v === undefined ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(digits)}%`;

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-[11px] font-medium uppercase tracking-wide text-text-muted">
        {label}
      </dt>
      <dd className="mt-0.5 text-sm leading-relaxed">{children}</dd>
    </div>
  );
}

/** A line-and-area equity curve, drawn from whatever points exist. */
function EquityCurve({ points }: { points: [string, number][] }) {
  if (points.length < 2) {
    return (
      <p className="text-sm text-text-muted">
        Not enough history to draw a curve yet.
      </p>
    );
  }
  const values = points.map(([, v]) => v);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const path = points
    .map(([, v], i) => {
      const x = (i / (points.length - 1)) * 100;
      const y = 100 - ((v - min) / span) * 100;
      return `${i === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
  return (
    <div>
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="h-32 w-full">
        <path d={path} fill="none" stroke="currentColor" strokeWidth="0.6"
              vectorEffect="non-scaling-stroke" className="text-text" />
      </svg>
      <div className="flex justify-between font-mono text-[10px] text-text-muted">
        <span>{points[0][0]}</span>
        <span>
          {min.toLocaleString(undefined, { maximumFractionDigits: 0 })} –{" "}
          {max.toLocaleString(undefined, { maximumFractionDigits: 0 })}
        </span>
        <span>{points[points.length - 1][0]}</span>
      </div>
    </div>
  );
}

function MetricList({ values }: { values: Record<string, number> }) {
  const { open } = useGlossary();
  const entries = Object.entries(values).filter(([, v]) => typeof v === "number");
  if (!entries.length) return null;
  return (
    <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5">
      {entries.map(([key, value]) => {
        const bare = key.split(":")[1] ?? key;
        return (
          <button
            key={key}
            type="button"
            onClick={() => open(bare, { from: "a strategy holding" })}
            className="font-mono text-[11px] text-text-muted underline decoration-dotted underline-offset-2"
            title={`What does "${bare}" mean?`}
          >
            {bare} {Number(value).toFixed(2)}
          </button>
        );
      })}
    </div>
  );
}

export default function Strategy() {
  const { id } = useParams<{ id: string }>();
  const { data, isLoading, error } = useStrategy(id);
  const { prose } = useGlossary();
  const [showJson, setShowJson] = useState(false);

  useEffect(() => {
    if (data) markDone("read_strategy");
  }, [data]);

  useRegisterScreen(
    data ? `Strategy: ${data.name}` : "Strategy",
    data
      ? {
          name: data.name, authority: data.authority, hypothesis: data.hypothesis,
          stage: data.stage, rules_plain: data.rules_plain,
          backtest_summary: data.backtest?.overall,
          beat_random_pct_per_trade: data.backtest?.excess_over_drift_pct,
          holdings: data.holdings.length,
        }
      : null,
    [
      "Explain this strategy to me in simple terms",
      "Should I promote this? Argue both sides",
      "What would have to go wrong for this to lose money?",
      "What is this strategy blind to?",
    ],
  );

  if (isLoading) return <p className="p-6 text-sm text-text-muted">Loading…</p>;
  if (error || !data)
    return <p className="p-6 text-sm text-negative">{(error as Error)?.message}</p>;

  const backtest = data.backtest;
  const overall = backtest?.overall ?? {};
  const deflation = backtest?.deflation ?? {};

  return (
    <div className="mx-auto max-w-4xl space-y-8 p-6">
      <header>
        <Link to="/strategies" className="text-xs text-text-muted hover:underline">
          ← all strategies
        </Link>
        <h1 className="mt-1 font-display text-2xl">{data.name}</h1>
        <p className="text-sm text-text-muted">
          {data.authority} · {data.horizon} horizon · {data.stage} · {data.status}
        </p>
      </header>

      {/* The decision this page exists for, before three screens of tables. */}
      <PromoteFlow strategy={data} />

      {data.decay_warning && (
        <div className="border-l-2 border-warning bg-warning/10 px-3 py-2 text-sm">
          {data.decay_warning}
        </div>
      )}

      {data.duplicate_of && (
        <div className="border-l-2 border-warning bg-warning/10 px-3 py-2 text-sm">
          <p className="font-medium">
            Flagged as a duplicate of another strategy
            {data.duplicate_correlation
              ? ` (return streams ${(data.duplicate_correlation * 100).toFixed(0)}% alike)`
              : ""}
            .
          </p>
          <p className="mt-1 text-text-muted">
            {data.duplicate_override_note
              ? `Overridden: ${data.duplicate_override_note}`
              : "Activation is blocked until this is overridden in writing."}
          </p>
        </div>
      )}

      <section className="space-y-4">
        <h2 className="font-display text-lg font-semibold">What it believes, and who came up with it</h2>
        <dl className="space-y-3">
          <Field label="Hypothesis">{prose(data.hypothesis)}</Field>
          {data.citation && (
            <Field label="Source">
              <span className="text-text-muted">{data.citation}</span>
            </Field>
          )}
          <Field label="Predicted before testing">{prose(data.predicted_performance)}</Field>
          {data.encoding_deviations && (
            <Field label="Where this departs from the source">
              {prose(data.encoding_deviations)}
            </Field>
          )}
          <Field label="Expected decay">{prose(data.decay_note)}</Field>
        </dl>
      </section>

      <section>
        <h2 className="font-display text-lg font-semibold">The exact rules it follows</h2>
        <p className="mt-1 text-sm text-text-muted">
          These run automatically. There is no judgement involved and no way for the
          strategy to change its mind.
        </p>
        <ul className="mt-2 space-y-1 text-sm">
          {data.rules_plain.map((line, index) => (
            <li key={index}>{line}</li>
          ))}
        </ul>
        <button
          type="button"
          onClick={() => setShowJson((v) => !v)}
          className="mt-2 text-xs text-text-muted underline"
        >
          {showJson ? "Hide" : "Show"} the exact rules the engine runs
        </button>
        {showJson && (
          <pre className="mt-2 overflow-x-auto rounded border border-border bg-surface-sunken p-3 font-mono text-[11px]">
            {JSON.stringify(data.rules_json, null, 2)}
          </pre>
        )}
      </section>

      <section>
        <h2 className="font-display text-lg font-semibold">
          How it did in testing, and with pretend money
        </h2>
        <p className="mt-1 text-sm leading-relaxed text-text-muted">
          The left column is what it would have done on past data{" "}
          {windowLabel(backtest?.window?.start, backtest?.window?.end) &&
            `(${windowLabel(backtest?.window?.start, backtest?.window?.end)})`}
          . The right is what it has actually done since you started it. If the right
          column ends up far worse than the left, that usually means the test was fitted
          to its own history and the strategy never really worked.
        </p>
        <table className="mt-2 w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left font-mono text-[10px] uppercase tracking-wider text-text-muted">
              <th className="py-1">Measure</th>
              <th className="py-1 text-right">Backtest</th>
              <th className="py-1 text-right">Paper</th>
            </tr>
          </thead>
          <tbody className="tabular">
            <tr className="border-b border-border/50">
              <td className="py-1">Completed trades</td>
              <td className="py-1 text-right">{overall.round_trips ?? "—"}</td>
              <td className="py-1 text-right">{String(data.paper.trades ?? 0)}</td>
            </tr>
            <tr className="border-b border-border/50">
              <td className="py-1">Total return</td>
              <td className="py-1 text-right">{pct(overall.total_return_pct)}</td>
              <td className="py-1 text-right">
                {pct(data.paper.total_return_pct as number | null)}
              </td>
            </tr>
            <tr className="border-b border-border/50">
              <td className="py-1">Mean per trade</td>
              <td className="py-1 text-right">{pct(overall.mean_trade_return_pct, 3)}</td>
              <td className="py-1 text-right">—</td>
            </tr>
            <tr className="border-b border-border/50">
              <td className="py-1">Max drawdown</td>
              <td className="py-1 text-right">{pct(overall.max_drawdown_pct, 1)}</td>
              <td className="py-1 text-right">
                {pct(data.paper.max_drawdown_pct as number | null, 1)}
              </td>
            </tr>
          </tbody>
        </table>

        {backtest && (
          <div className="mt-3 space-y-1.5 text-sm leading-relaxed text-text-muted">
            <p>
              <strong>In plain English:</strong>{" "}
              {explainTotalReturn(overall.total_return_pct, backtest.window?.start, backtest.window?.end)}
            </p>
            <p>{explainPerTrade(overall.mean_trade_return_pct)}, and it {explainWinRate(overall.win_rate)}.</p>
            <p>{explainEdge(backtest.excess_over_drift_pct, overall.round_trips)}</p>
            <p>On the way, {explainDrawdown(overall.max_drawdown_pct)}.</p>
            <p>{prose(backtest.track_record_verdict ?? "")}</p>
          </div>
        )}

        {deflation?.per_trade && (
          <p className="mt-2 text-sm leading-relaxed text-text-muted">
            {deflation.per_trade.survives
              ? `Its average trade of ${pct(deflation.per_trade.observed_mean_pct, 3)} clears the ${pct(
                  deflation.per_trade.expected_best_of_n_under_null_pct,
                  3,
                )} that the best of ${deflation.n_trials} worthless variations would have shown anyway.`
              : `Its average trade of ${pct(deflation.per_trade.observed_mean_pct, 3)} does NOT clear the ${pct(
                  deflation.per_trade.expected_best_of_n_under_null_pct,
                  3,
                )} that the best of ${deflation.n_trials} worthless variations would have shown anyway. Treat it as unproven.`}
          </p>
        )}
      </section>

      {data.equity_curve.length > 1 && (
        <section>
          <h2 className="font-display text-lg font-semibold">What the pretend £100,000 is worth over time</h2>
          <div className="mt-2">
            <EquityCurve points={data.equity_curve} />
          </div>
        </section>
      )}

      {backtest?.regimes && Object.keys(backtest.regimes).length > 0 && (
        <section>
          <h2 className="font-display text-lg font-semibold">How it did in each stretch of years</h2>
          {/* This table confused Roger: the rows are yearly rates, the headline
              is a compounded total, and nothing said so. */}
          <p className="mt-1 text-sm leading-relaxed text-text-muted">
            The average return of a single trade in each period — not the total for that
            period. These build on each other over time, which is why modest yearly
            numbers add up to a much bigger total: earning{" "}
            {(() => {
              const years = yearsBetween(backtest?.window?.start, backtest?.window?.end);
              const perYear = annualised(overall.total_return_pct ?? 0, years);
              return years && perYear
                ? `about ${Math.abs(perYear).toFixed(0)}% a year for ${years.toFixed(0)} years really does compound to ${(overall.total_return_pct ?? 0).toFixed(0)}%`
                : "a steady yearly return compounds into a much larger total";
            })()}
            . A period where it lost money is more informative than one where it won —
            look for whether it ever stopped working entirely.
          </p>
          <table className="mt-2 w-full text-sm">
            <tbody className="tabular">
              {Object.entries(backtest.regimes).map(([label, stats]: [string, any]) => (
                <tr key={label} className="border-b border-border/50">
                  <td className="py-1">{label}</td>
                  <td className="py-1 text-right text-text-muted">
                    {stats.trades} trades
                    {stats.underpowered && " (too few to trust)"}
                  </td>
                  <td className="py-1 text-right">{pct(stats.mean_return_pct, 3)}</td>
                  <td className="py-1 text-right text-text-muted">
                    {(stats.win_rate * 100).toFixed(0)}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <section>
        <h2 className="font-display text-lg font-semibold">
          What it owns right now {data.holdings.length > 0 && `(${data.holdings.length})`}
        </h2>
        {data.holdings.length === 0 ? (
          <p className="mt-1 text-sm text-text-muted">
            {data.stage === "backtest"
              ? "It owns nothing because it has not been started. Once you give it pretend money it will buy shares by its own rules and they will be listed here, each with the exact rule that caused it."
              : "It owns nothing right now. Its rules did not find anything worth holding at the last rebalance, which is a normal state rather than a fault."}
          </p>
        ) : (
          <ul className="mt-2 divide-y divide-border border-y border-border">
            {data.holdings.map((holding) => (
              <li key={holding.ticker} className="py-2">
                <div className="flex flex-wrap items-baseline gap-x-2">
                  <Link to={`/company/${holding.ticker}`} className="text-sm font-medium hover:underline">
                    {holding.ticker}
                  </Link>
                  <span className="text-xs text-text-muted">{holding.name}</span>
                  <span className="tabular ml-auto text-sm">{pct(holding.unrealised_pct)}</span>
                </div>
                {/* Why this is held: the rule that fired, and the numbers behind it. */}
                <p className="mt-0.5 font-mono text-[11px] text-text-muted">
                  {holding.rule_fired} · since {holding.opened_at}
                </p>
                <MetricList values={holding.metric_values} />
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <h2 className="font-display text-lg font-semibold">Everything it has bought and sold</h2>
        {data.trades.length === 0 ? (
          <p className="mt-1 text-sm text-text-muted">
            {data.stage === "backtest"
              ? "No trades because it has not been started. Nothing here has ever bought or sold anything."
              : "No trades yet — the first will appear after the next overnight run, tomorrow at about 7am."}
          </p>
        ) : (
          <ul className="mt-2 divide-y divide-border border-y border-border">
            {data.trades.map((trade, index) => (
              <li key={index} className="py-2">
                <div className="flex flex-wrap items-baseline gap-x-2 text-sm">
                  <span className="font-mono text-xs uppercase">{trade.side}</span>
                  <Link to={`/company/${trade.ticker}`} className="font-medium hover:underline">
                    {trade.ticker}
                  </Link>
                  <span className="tabular text-xs text-text-muted">
                    {trade.quantity.toFixed(2)} @ {trade.price.toFixed(2)}
                  </span>
                  <span className="tabular ml-auto text-xs text-text-muted">
                    cost {(trade.spread_cost + trade.commission).toFixed(2)}
                  </span>
                </div>
                <p className="mt-0.5 font-mono text-[11px] text-text-muted">
                  {trade.rule_fired} · signalled {trade.signal_date}, filled {trade.fill_date}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>

    </div>
  );
}
