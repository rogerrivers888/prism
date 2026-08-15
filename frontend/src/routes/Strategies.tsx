import { Link } from "react-router-dom";
import {
  HORIZON_LABEL,
  useLeaderboard,
  useTradesToday,
  type LeaderboardRow,
} from "../api/strategies";
import { useGlossary } from "../components/GlossaryProvider";
import { NothingYet, PagePurpose } from "../components/PagePurpose";
import { useRegisterScreen } from "../components/ScreenContext";
import {
  explainCosts,
  explainEdge,
  explainExpectancy,
} from "../lib/explain";

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
  const promoted = row.stage !== "backtest";
  return (
    <li className="border-b border-border/60 py-4">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <Link
          to={`/strategies/${row.strategy_id}`}
          className="text-sm font-medium underline-offset-2 hover:underline"
        >
          {row.name}
        </Link>
        <StageChip row={row} />
        <span className="text-xs text-text-muted">from {row.authority}</span>
        {row.duplicate_of && (
          <span className="rounded border border-warning px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-warning">
            nearly the same as another one
          </span>
        )}
      </div>

      {/* State, in words. "backtest/registered" meant nothing to anyone. */}
      <p className="mt-1 text-sm">
        {promoted
          ? "Trading pretend money now — you can watch what it buys and why."
          : "Not started. It has only been tested on past data."}
      </p>

      <p className="mt-1 text-xs leading-relaxed text-text-muted">
        {prose(row.track_record_verdict)}
      </p>

      {/* Every figure with its meaning beside it, not in a tooltip. */}
      <dl className="mt-3 grid gap-3 sm:grid-cols-2">
        <div>
          <dt className="text-[11px] font-medium uppercase tracking-wide text-text-muted">
            Beat random by
          </dt>
          <dd className="tabular text-sm">
            {row.backtest_excess_over_drift_pct === null
              ? "—"
              : `${row.backtest_excess_over_drift_pct >= 0 ? "+" : ""}${row.backtest_excess_over_drift_pct.toFixed(2)}% per trade`}
          </dd>
          <p className="mt-0.5 text-xs leading-relaxed text-text-muted">
            {explainEdge(row.backtest_excess_over_drift_pct)}
          </p>
        </div>
        <div>
          <dt className="text-[11px] font-medium uppercase tracking-wide text-text-muted">
            Expectancy
          </dt>
          <dd className="tabular text-sm">
            {row.expectancy_r === null ? "—" : `${row.expectancy_r.toFixed(3)}R`}
          </dd>
          <p className="mt-0.5 text-xs leading-relaxed text-text-muted">
            {explainExpectancy(row.expectancy_r)}
          </p>
        </div>
        {promoted && (
          <>
            <div>
              <dt className="text-[11px] font-medium uppercase tracking-wide text-text-muted">
                Pretend money so far
              </dt>
              <dd className="tabular text-sm">
                {row.trades} trades
                {row.total_return_pct !== null && `, ${row.total_return_pct >= 0 ? "+" : ""}${row.total_return_pct.toFixed(1)}%`}
              </dd>
              <p className="mt-0.5 text-xs leading-relaxed text-text-muted">
                {row.started
                  ? `Started ${row.started}. Far too early to judge.`
                  : "No trades yet — its first will come after the next overnight run."}
              </p>
            </div>
            <div>
              <dt className="text-[11px] font-medium uppercase tracking-wide text-text-muted">
                Lost to fees
              </dt>
              <dd className="tabular text-sm">
                {row.cost_drag_pct === null ? "—" : `${row.cost_drag_pct.toFixed(2)}%`}
              </dd>
              <p className="mt-0.5 text-xs leading-relaxed text-text-muted">
                {explainCosts(row.cost_drag_pct)}
              </p>
            </div>
          </>
        )}
      </dl>

      {row.deflated_survives !== null && (
        <p className="mt-2 text-xs leading-relaxed text-text-muted">
          {row.deflated_survives
            ? "Its result is bigger than luck alone would produce, given how many similar ideas were tried."
            : "A result this good would be expected from luck alone, given how many similar ideas were tried. Treat it as unproven."}
        </p>
      )}

      <Link
        to={`/strategies/${row.strategy_id}`}
        className="mt-3 inline-block rounded border border-border px-3 py-1.5 text-xs hover:bg-surface-sunken"
      >
        {promoted ? "See what it owns and why →" : "Read it, and decide whether to start it →"}
      </Link>
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
  const { prose } = useGlossary();

  const rows = Object.values(data?.boards ?? {}).flat();
  const promotedCount = rows.filter((row) => row.stage !== "backtest").length;
  useRegisterScreen(
    "Strategies leaderboard",
    { strategies: rows.length, trading: promotedCount,
      names: rows.map((r) => ({ name: r.name, stage: r.stage,
        beat_random_pct_per_trade: r.backtest_excess_over_drift_pct })) },
    [
      "What is this page actually asking me to do?",
      "Which of these should I be most sceptical about?",
      "Explain 'beat random by' — why is that the number to look at?",
    ],
  );

  return (
    <div className="mx-auto max-w-5xl space-y-8 p-6">
      <header className="space-y-4">
        <div className="flex items-start justify-between gap-3">
          <h1 className="font-display text-2xl uppercase tracking-wide">Strategies</h1>
        </div>
        <PagePurpose
          id="strategies"
          title="Strategies"
          what="Twelve different approaches to picking shares, competing against each other with pretend money. Each one was written down — what it believes and what it expects to earn — before it was ever tested, so it cannot quietly rewrite its own story afterwards."
          firstStep="reading one that interests you, then deciding whether it deserves £100,000 of pretend money. Nothing here uses real money, and nothing starts without you."
        />
        {data && (
          <div className="mt-3 space-y-2">
            {/* The two things that make these numbers smaller than they look,
                said in words before the tables that contain them. */}
            <div className="max-w-2xl border-l-2 border-warning bg-warning/10 px-3 py-2 text-sm leading-relaxed">
              <p className="font-medium">Two things to know before reading any of this</p>
              <p className="mt-1 text-text-muted">
                <strong>These are tests on the past, not results.</strong>{" "}
                {prose(data.universe_warning)}
              </p>
              {data.cohort_deflation && (
                <p className="mt-1.5 text-text-muted">
                  <strong>Twelve were tried, so one looks best by chance.</strong>{" "}
                  If all twelve were worthless, the luckiest would still look like a winner.
                  Being top of this list is not evidence.
                </p>
              )}
            </div>
            <p className="max-w-2xl border-l-2 border-border pl-3 text-xs text-text-muted">
              Ordered by how they did across their whole history, never by the last few weeks —
              sorting by recent performance just promotes whatever got lucky.
            </p>
          </div>
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
          {promotedCount === 0 ? (
            <NothingYet
              headline="No strategies are trading yet"
              because="Nothing appears here until you start one with pretend money. Every strategy above has only been tested on past data — none is doing anything right now."
              action={{ label: "Review the strategies above and start one", onClick: () => window.scrollTo({ top: 0, behavior: "smooth" }) }}
            />
          ) : (
            <TradesToday />
          )}
        </div>
      </section>
    </div>
  );
}
