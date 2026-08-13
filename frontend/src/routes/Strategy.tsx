import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { usePromote, useStrategy, type StrategyDetail } from "../api/strategies";
import { useGlossary } from "../components/GlossaryProvider";

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

function Promote({ strategy }: { strategy: StrategyDetail }) {
  const promote = usePromote();
  const [note, setNote] = useState("");
  const gate = strategy.backtest?.gate;
  const eligible = gate?.eligible_for_paper;

  if (strategy.stage !== "backtest") {
    return (
      <p className="text-sm text-text-muted">
        Already promoted to <strong>{strategy.stage}</strong>.
      </p>
    );
  }

  return (
    <div className="space-y-2">
      {!eligible && gate && (
        <div className="border-l-2 border-warning bg-warning/10 px-3 py-2 text-sm">
          <p className="font-medium">Not eligible for paper trading.</p>
          <ul className="mt-1 list-disc pl-4 text-text-muted">
            {(gate.blocking_reasons ?? []).map((reason: string) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </div>
      )}
      {eligible && (
        <p className="text-sm text-text-muted">
          Passed the backtest gate. Promotion is still your call — the machine never
          promotes anything on its own.
        </p>
      )}
      <input
        value={note}
        onChange={(event) => setNote(event.target.value)}
        placeholder="Why you're promoting it (recorded permanently)"
        className="w-full rounded border border-border bg-surface px-2 py-1 text-sm"
      />
      <button
        type="button"
        disabled={!eligible || promote.isPending}
        onClick={() =>
          promote.mutate({ id: strategy.strategy_id, stage: "paper", note: note || undefined })
        }
        className="rounded border border-border px-3 py-1.5 text-sm disabled:opacity-40"
      >
        {promote.isPending ? "Promoting…" : "Promote to paper trading"}
      </button>
      {promote.error && (
        <p className="text-sm text-negative">{promote.error.message}</p>
      )}
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
        <h2 className="font-display text-lg font-semibold">What it believes</h2>
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
        <h2 className="font-display text-lg font-semibold">The rules</h2>
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
        <h2 className="font-display text-lg font-semibold">Backtest and paper, side by side</h2>
        <p className="mt-1 text-xs text-text-muted">
          A large gap between these two is the warning sign: it usually means the
          backtest was fitted to its own history.
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
          <p className="mt-3 text-sm leading-relaxed text-text-muted">
            {prose(backtest.track_record_verdict ?? "")}
          </p>
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
          <h2 className="font-display text-lg font-semibold">Paper equity</h2>
          <div className="mt-2">
            <EquityCurve points={data.equity_curve} />
          </div>
        </section>
      )}

      {backtest?.regimes && Object.keys(backtest.regimes).length > 0 && (
        <section>
          <h2 className="font-display text-lg font-semibold">By period</h2>
          <table className="mt-2 w-full text-sm">
            <tbody className="tabular">
              {Object.entries(backtest.regimes).map(([label, stats]: [string, any]) => (
                <tr key={label} className="border-b border-border/50">
                  <td className="py-1">{label}</td>
                  <td className="py-1 text-right text-text-muted">
                    {stats.underpowered ? `n=${stats.trades}` : stats.trades}
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
          Holdings {data.holdings.length > 0 && `(${data.holdings.length})`}
        </h2>
        {data.holdings.length === 0 ? (
          <p className="mt-1 text-sm text-text-muted">
            Nothing held — this strategy has not been promoted to paper trading yet.
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
        <h2 className="font-display text-lg font-semibold">Trade history</h2>
        {data.trades.length === 0 ? (
          <p className="mt-1 text-sm text-text-muted">No trades yet.</p>
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

      <section>
        <h2 className="font-display text-lg font-semibold">Promotion</h2>
        <div className="mt-2">
          <Promote strategy={data} />
        </div>
      </section>
    </div>
  );
}
