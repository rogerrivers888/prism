import { Link } from "react-router-dom";
import {
  HORIZON_LABEL,
  useLeaderboard,
  useTradesToday,
  type LeaderboardRow,
} from "../api/strategies";
import { useGlossary } from "../components/GlossaryProvider";

const pct = (v: number | null | undefined, digits = 2) =>
  v === null || v === undefined ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(digits)}%`;

const STATUS_LABEL: Record<string, string> = {
  registered: "registered",
  active: "trading paper",
  paused: "paused",
  retired: "retired",
};

function StageChip({ row }: { row: LeaderboardRow }) {
  return (
    <span className="whitespace-nowrap rounded border border-border px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-text-muted">
      {row.stage} · {STATUS_LABEL[row.status] ?? row.status}
    </span>
  );
}

function Row({ row }: { row: LeaderboardRow }) {
  const { prose } = useGlossary();
  return (
    <li className="border-b border-border/60 py-3">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <Link
          to={`/strategies/${row.strategy_id}`}
          className="text-sm font-medium underline-offset-2 hover:underline"
        >
          {row.name}
        </Link>
        <StageChip row={row} />
        <span className="text-xs text-text-muted">{row.authority}</span>
        {row.duplicate_of && (
          <span className="rounded border border-warning px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-warning">
            duplicate
          </span>
        )}
      </div>

      {/* The sample-size sentence, given the same weight as the numbers rather
          than tucked underneath them. Most rows say "meaningless" and should. */}
      <p className="mt-1 text-xs leading-relaxed text-text-muted">
        {prose(row.track_record_verdict)}
      </p>

      <dl className="mt-2 grid grid-cols-3 gap-x-4 gap-y-1 text-xs sm:grid-cols-6">
        <div>
          <dt className="text-text-muted">Trades</dt>
          <dd className="tabular">{row.trades}</dd>
        </div>
        <div>
          <dt className="text-text-muted">Paper return</dt>
          <dd className="tabular">{pct(row.total_return_pct)}</dd>
        </div>
        <div>
          <dt className="text-text-muted">Expectancy</dt>
          <dd className="tabular">
            {row.expectancy_r === null ? "—" : `${row.expectancy_r.toFixed(3)}R`}
          </dd>
        </div>
        <div>
          <dt className="text-text-muted">Max drawdown</dt>
          <dd className="tabular">{pct(row.max_drawdown_pct, 1)}</dd>
        </div>
        <div>
          <dt className="text-text-muted">Cost drag</dt>
          <dd className="tabular">{pct(row.cost_drag_pct, 2)}</dd>
        </div>
        <div>
          <dt className="text-text-muted">Backtest edge</dt>
          <dd className="tabular">{pct(row.backtest_excess_over_drift_pct, 3)}</dd>
        </div>
      </dl>

      {/* The deflated view: what the family's best would show on luck alone. */}
      {row.deflated_survives !== null && (
        <p className="mt-1.5 text-xs text-text-muted">
          {row.deflated_survives
            ? `Clears the bar set by trying ${row.family_size} related ${
                row.family_size === 1 ? "idea" : "ideas"
              }.`
            : `Does not clear the bar set by trying ${row.family_size} related ${
                row.family_size === 1 ? "idea" : "ideas"
              } — a result this good would be expected from luck alone.`}
        </p>
      )}
    </li>
  );
}

function TradesToday() {
  const { data } = useTradesToday();
  const { prose } = useGlossary();
  if (!data || !data.trades.length) {
    return (
      <p className="text-sm text-text-muted">
        {data?.note ?? "No trades yet — nothing has been promoted to paper trading."}
      </p>
    );
  }
  return (
    <div>
      <p className="text-xs text-text-muted">Filled {data.date}</p>
      <ul className="mt-2 divide-y divide-border border-y border-border">
        {data.trades.map((trade, index) => (
          <li key={index} className="py-2 text-sm">
            <div className="flex flex-wrap items-baseline gap-x-2">
              <span className="font-mono text-xs uppercase">{trade.side}</span>
              <Link to={`/company/${trade.ticker}`} className="font-medium hover:underline">
                {trade.ticker}
              </Link>
              <span className="text-xs text-text-muted">{trade.strategy}</span>
            </div>
            {/* Why, in the same breath as what. */}
            <p className="mt-0.5 font-mono text-[11px] text-text-muted">
              {trade.rule_fired}
            </p>
            <p className="text-[11px] text-text-muted">
              {prose(
                Object.entries(trade.metric_values)
                  .slice(0, 4)
                  .map(([k, v]) => `${k.split(":")[1] ?? k} ${Number(v).toFixed(2)}`)
                  .join(" · "),
              )}
            </p>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function Strategies() {
  const { data, isLoading, error } = useLeaderboard();

  return (
    <div className="mx-auto max-w-5xl space-y-8 p-6">
      <header>
        <h1 className="font-display text-2xl uppercase tracking-wide">Strategies</h1>
        <p className="mt-1 max-w-2xl text-sm text-text-muted">
          Twelve pre-registered strategies, each written down with its hypothesis and
          expected performance before any backtest ran. Nothing here is a
          recommendation, and nothing is promoted automatically.
        </p>
        {data && (
          <p className="mt-2 max-w-2xl border-l-2 border-border pl-3 text-xs text-text-muted">
            {data.ranked_on}
          </p>
        )}
      </header>

      {isLoading && <p className="text-sm text-text-muted">Loading…</p>}
      {error && <p className="text-sm text-negative">{(error as Error).message}</p>}

      {data &&
        ["short", "medium", "long"].map((horizon) => {
          const rows = data.boards[horizon] ?? [];
          if (!rows.length) return null;
          return (
            <section key={horizon}>
              <h2 className="font-display text-lg font-semibold">
                {HORIZON_LABEL[horizon]}
              </h2>
              <ul className="mt-2 border-t border-border">
                {rows.map((row) => (
                  <Row key={row.strategy_id} row={row} />
                ))}
              </ul>
            </section>
          );
        })}

      <section>
        <h2 className="font-display text-lg font-semibold">What traded today</h2>
        <div className="mt-2">
          <TradesToday />
        </div>
      </section>
    </div>
  );
}
