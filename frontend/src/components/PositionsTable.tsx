import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { usePositions, useIGBook, type PositionRow, type PositionTotals } from "../api/ig";
import { LENSES, useUniverse, type LensName, type UniverseRow } from "../api/universe";
import { LensStrip } from "./LensBar";
import { DateRangePicker, withinRange, ALL_TIME, type Range } from "./DateRangePicker";
import { Dropdown } from "./Dropdown";
import { Drawer, DrawerStack } from "./Drawer";
import { useGlossary } from "./GlossaryProvider";
import { NothingYet } from "./PagePurpose";

/** The positions table: scan here, drill in the drawer.
 *
 *  Two totals sit at the top because they answer different questions and are
 *  wildly different on a leveraged book. Notional is how much value moves with
 *  the market. At risk is how much can actually be lost. Showing only one is
 *  how people misjudge the size of what they are holding.
 */

const money = (value: number | null | undefined, code = "GBP", digits = 0) => {
  if (value === null || value === undefined) return "—";
  const symbol = code === "USD" ? "$" : code === "EUR" ? "€" : "£";
  return `${value < 0 ? "−" : ""}${symbol}${Math.abs(value).toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}`;
};

const pl = (value: number | null | undefined, code = "GBP") => {
  if (value === null || value === undefined) return "—";
  return `${value >= 0 ? "+" : "−"}${money(Math.abs(value), code, 2).replace("−", "")}`;
};

type SortKey =
  | "name" | "notional" | "market_value" | "at_risk" | "pl" | "expiry" | "opened"
  | "earnings";

function TotalsBar({ totals, label }: { totals: PositionTotals; label: string }) {
  return (
    <div className="grid grid-cols-2 gap-3 rounded-md border border-border bg-surface-sunken p-3 sm:grid-cols-5">
      <div>
        <div className="text-[11px] uppercase tracking-wide text-text-muted">
          {label}
        </div>
        <div className="tabular text-lg">{totals.positions}</div>
      </div>
      <div>
        <div className="text-[11px] uppercase tracking-wide text-text-muted">
          Notional — what you control
        </div>
        <div className="tabular text-lg">{money(totals.notional)}</div>
        <p className="mt-0.5 text-[11px] leading-tight text-text-muted">
          The full value of the shares behind these bets. An option controls
          its whole notional for a fraction of the price.
        </p>
      </div>
      <div>
        <div className="text-[11px] uppercase tracking-wide text-text-muted">
          What it is worth now
        </div>
        <div className="tabular text-lg">{money(totals.market_value)}</div>
        <p className="mt-0.5 text-[11px] leading-tight text-text-muted">
          What you would get back selling today
          {totals.delta_exposure > 0 &&
            ` · moves like ${money(totals.delta_exposure)} of stock`}
          .
        </p>
      </div>
      <div>
        <div className="text-[11px] uppercase tracking-wide text-text-muted">
          Most you could lose
        </div>
        <div className="tabular text-lg">{money(totals.at_risk)}</div>
        <p className="mt-0.5 text-[11px] leading-tight text-text-muted">
          {totals.at_risk_unknown > 0
            ? `On ${totals.at_risk_known} of ${totals.positions}. ${totals.at_risk_unknown} has no stop, so its loss is not capped.`
            : "Premiums paid and stop distances."}
        </p>
      </div>
      <div>
        <div className="text-[11px] uppercase tracking-wide text-text-muted">
          {totals.realised_pl !== 0 ? "Profit / loss taken" : "Profit / loss so far"}
        </div>
        <div className="tabular text-lg">
          {pl(totals.realised_pl !== 0 ? totals.realised_pl : totals.unrealised_pl)}
        </div>
        {totals.funding_paid > 0 && (
          <p className="mt-0.5 text-[11px] leading-tight text-text-muted">
            After {money(totals.funding_paid, "GBP", 2)} of interest.
          </p>
        )}
      </div>
    </div>
  );
}

/** How the closed trades actually went — the only honest scoreboard there is. */
/** The book seen through Prism's research rather than through money.
 *
 *  Answers a question the money view cannot: are the things you own actually
 *  any good by your own criteria? A large position on a company scoring badly
 *  everywhere is worth noticing.
 */
function ResearchView({
  rows,
  lensFor,
  onOpen,
}: {
  rows: PositionRow[];
  lensFor: (ticker: string | null) => UniverseRow | undefined;
  onOpen: (row: PositionRow) => void;
}) {
  const withScores = rows.filter((row) => lensFor(row.ticker));
  const missing = rows.length - withScores.length;

  return (
    <div className="space-y-2">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[46rem] text-sm">
          <thead>
            <tr className="border-b border-border text-left text-[11px] uppercase tracking-wide text-text-muted">
              <th className="py-1 font-medium">Position</th>
              <th className="py-1 text-right font-medium">Notional</th>
              {LENSES.map((lens) => (
                <th key={lens} className="py-1 text-center font-medium capitalize">
                  {lens}
                </th>
              ))}
              <th className="py-1 text-right font-medium">Disagreement</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const scored = lensFor(row.ticker);
              return (
                <tr
                  key={row.deal_id}
                  onClick={() => onOpen(row)}
                  className="cursor-pointer border-b border-border/50 hover:bg-surface-sunken"
                >
                  <td className="py-2">
                    <span className="font-medium">{row.ticker ?? row.name}</span>
                    {row.right && (
                      <span className="ml-1 text-xs text-text-muted">
                        {row.right} {row.strike}
                      </span>
                    )}
                  </td>
                  <td className="tabular py-2 text-right">
                    {money(row.notional, row.currency ?? "GBP")}
                  </td>
                  {LENSES.map((lens) => {
                    const cell = scored?.lenses[lens];
                    const score = cell?.applicable ? cell.score : null;
                    return (
                      <td key={lens} className="tabular py-2 text-center">
                        {score === null || score === undefined ? (
                          <span className="text-text-muted/50">—</span>
                        ) : (
                          <span
                            className={
                              score >= 70
                                ? "font-medium"
                                : score <= 30
                                  ? "text-text-muted"
                                  : ""
                            }
                          >
                            {score.toFixed(0)}
                          </span>
                        )}
                      </td>
                    );
                  })}
                  <td className="tabular py-2 text-right text-text-muted">
                    {scored?.dispersion?.toFixed(0) ?? "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="text-xs leading-relaxed text-text-muted">
        Each score runs 0–100 against others in the same industry, and none of them is
        a buy or sell signal. Disagreement is the gap between the highest and lowest —
        a big number means the six views contradict each other about something you own.
        {missing > 0 &&
          ` ${missing} position${missing === 1 ? " is" : "s are"} not linked to a company Prism tracks, so ${
            missing === 1 ? "it has" : "they have"
          } no scores.`}
      </p>
    </div>
  );
}

/** Where the money actually is. Rectangles sized by notional, shaded by one
 *  lens, so concentration and quality are visible at the same time. */
function MapView({
  rows,
  lensFor,
  onOpen,
}: {
  rows: PositionRow[];
  lensFor: (ticker: string | null) => UniverseRow | undefined;
  onOpen: (row: PositionRow) => void;
}) {
  const [lens, setLens] = useState<LensName>("quality");
  const total = rows.reduce((sum, row) => sum + (row.notional ?? 0), 0);
  if (total <= 0) return null;

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-text-muted">Shade by</span>
        <Dropdown
          label="Lens"
          value={lens}
          onChange={(value) => setLens(value as LensName)}
          options={LENSES.map((value) => ({
            value,
            label: value.charAt(0).toUpperCase() + value.slice(1),
          }))}
        />
      </div>

      <div className="flex flex-wrap gap-1">
        {rows.map((row) => {
          const share = (row.notional ?? 0) / total;
          const scored = lensFor(row.ticker);
          const cell = scored?.lenses[lens];
          const score = cell?.applicable ? cell.score : null;
          return (
            <button
              key={row.deal_id}
              type="button"
              onClick={() => onOpen(row)}
              title={`${row.ticker ?? row.name}: ${money(row.notional, row.currency ?? "GBP")} — ${
                Math.round(share * 100)
              }% of the book${score !== null && score !== undefined ? `, ${lens} ${score.toFixed(0)}` : ""}`}
              style={{
                flexGrow: Math.max(share * 100, 4),
                flexBasis: `${Math.max(share * 100, 12)}%`,
                minHeight: `${Math.max(share * 260, 56)}px`,
                // Opacity carries the score; hue stays the lens's own identity
                // so colour never becomes a verdict.
                opacity: score === null || score === undefined ? 0.25 : 0.35 + (score / 100) * 0.65,
              }}
              className={`flex flex-col justify-between rounded border border-border p-2 text-left ${LENS_BG[lens]}`}
            >
              <span className="text-xs font-medium">{row.ticker ?? row.name.slice(0, 14)}</span>
              <span className="tabular text-[11px]">
                {money(row.notional, row.currency ?? "GBP")}
                <span className="ml-1 opacity-70">{Math.round(share * 100)}%</span>
              </span>
            </button>
          );
        })}
      </div>
      <p className="text-xs leading-relaxed text-text-muted">
        Box size is how much of your notional exposure each position represents. Stronger
        shading means a higher {lens} score; a pale box is a large holding Prism rates
        poorly, or one it cannot score at all.
      </p>
    </div>
  );
}

const LENS_BG: Record<LensName, string> = {
  trend: "bg-lens-trend",
  growth: "bg-lens-growth",
  quality: "bg-lens-quality",
  value: "bg-lens-value",
  momentum: "bg-lens-momentum",
  cycle: "bg-lens-cycle",
};

function ClosedSummary({ rows }: { rows: PositionRow[] }) {
  const settled = rows.filter((r) => r.realised_pl !== null);
  if (settled.length === 0) return null;

  const wins = settled.filter((r) => (r.realised_pl ?? 0) > 0);
  const losses = settled.filter((r) => (r.realised_pl ?? 0) <= 0);
  const net = settled.reduce((sum, r) => sum + (r.realised_pl ?? 0), 0);
  const averageWin = wins.length
    ? wins.reduce((sum, r) => sum + (r.realised_pl ?? 0), 0) / wins.length
    : 0;
  const averageLoss = losses.length
    ? losses.reduce((sum, r) => sum + (r.realised_pl ?? 0), 0) / losses.length
    : 0;
  const held = settled.filter((r) => r.days_held !== null);
  const averageHold = held.length
    ? Math.round(held.reduce((sum, r) => sum + (r.days_held ?? 0), 0) / held.length)
    : null;

  return (
    <div className="rounded-md border border-border p-3 text-sm leading-relaxed">
      <p>
        <strong>{settled.length} closed trades.</strong> You made money on{" "}
        {wins.length} and lost on {losses.length} — a win rate of{" "}
        {Math.round((wins.length / settled.length) * 100)}%. Together they came to{" "}
        <strong className={net >= 0 ? "text-positive" : "text-negative"}>
          {pl(net)}
        </strong>
        .
      </p>
      <p className="mt-1 text-text-muted">
        The average winner made {money(averageWin, "GBP", 2)} and the average loser
        cost {money(Math.abs(averageLoss), "GBP", 2)}
        {averageHold !== null && `, held for about ${averageHold} days`}.{" "}
        {averageWin > Math.abs(averageLoss)
          ? "Your winners are bigger than your losers, which is what lets a win rate near half still make money."
          : "Your losers are bigger than your winners, so the win rate has to stay high for this to work."}
      </p>
      {settled.length < 30 && (
        <p className="mt-1 text-xs text-text-muted">
          {settled.length} trades is far too few to tell skill from luck. Treat this
          as a record of what happened, not evidence about what will.
        </p>
      )}
    </div>
  );
}

function Detail({ row, onClose }: { row: PositionRow; onClose: () => void }) {
  const { prose } = useGlossary();
  const book = useIGBook();
  const option = book.data?.accounts
    .flatMap((a) => a.options)
    .find((o) => o.deal_id === row.deal_id);

  return (
    <DrawerStack>
      <Drawer
        title={row.ticker ?? row.name}
        subtitle={`${row.account_label ?? row.account_id} · ${
          row.closed_at ? "closed" : "open"
        }`}
        onClose={onClose}
        width="w-[min(96vw,34rem)]"
      >
        <div className="space-y-4">
          {option && (
            <section className="space-y-2 text-sm leading-relaxed">
              <p className="font-medium">{prose(option.breakeven_line)}</p>
              <p className="text-text-muted">{prose(option.decay_line)}</p>
              <p className="text-text-muted">{prose(option.leverage_line)}</p>
              <p
                className={
                  row.at_risk_basis.startsWith("UNCAPPED")
                    ? "font-medium text-warning"
                    : "text-text-muted"
                }
              >
                {prose(option.max_loss_line)}
              </p>
              <p className="text-text-muted">{prose(option.probability_line)}</p>
              {option.earnings_warning && (
                <p className="border-l-2 border-warning bg-warning/10 px-3 py-2">
                  {prose(option.earnings_warning)}
                </p>
              )}
            </section>
          )}

          <section>
            <h3 className="text-[11px] font-medium uppercase tracking-wide text-text-muted">
              The numbers
            </h3>
            <dl className="mt-1 grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
              <div>
                <dt className="text-xs text-text-muted">Notional — what you control</dt>
                <dd className="tabular">{money(row.notional, row.currency ?? "GBP")}</dd>
              </div>
              <div>
                <dt className="text-xs text-text-muted">Worth now</dt>
                <dd className="tabular">{money(row.market_value, row.currency ?? "GBP")}</dd>
                {row.delta_exposure !== null && row.kind === "option" && (
                  <p className="mt-0.5 text-[11px] leading-tight text-text-muted">
                    Currently moves like {money(row.delta_exposure, row.currency ?? "GBP")} of
                    the shares.
                  </p>
                )}
              </div>
              <div>
                <dt className="text-xs text-text-muted">Most you could lose</dt>
                <dd className="tabular">{money(row.at_risk, row.currency ?? "GBP")}</dd>
                <p className="mt-0.5 text-[11px] leading-tight text-text-muted">
                  {row.at_risk_basis}
                </p>
              </div>
              <div>
                <dt className="text-xs text-text-muted">Bought at</dt>
                <dd className="tabular">{row.open_level ?? "—"}</dd>
              </div>
              <div>
                <dt className="text-xs text-text-muted">Worth now</dt>
                <dd className="tabular">{row.current_level ?? "—"}</dd>
              </div>
              <div>
                <dt className="text-xs text-text-muted">
                  {row.closed_at ? "Profit / loss taken" : "Profit / loss so far"}
                </dt>
                <dd className="tabular">
                  {pl(row.closed_at ? row.realised_pl : row.unrealised_pl, row.currency ?? "GBP")}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-text-muted">Held for</dt>
                <dd className="tabular">
                  {row.days_held !== null ? `${row.days_held} days` : "—"}
                </dd>
              </div>
              {row.funding_paid ? (
                <div>
                  <dt className="text-xs text-text-muted">Interest paid</dt>
                  <dd className="tabular">{money(row.funding_paid, "GBP", 2)}</dd>
                </div>
              ) : null}
              {row.expiry && (
                <div>
                  <dt className="text-xs text-text-muted">Expires</dt>
                  <dd className="tabular">
                    {row.expiry}
                    {row.days_to_expiry !== null && ` · ${row.days_to_expiry} days`}
                  </dd>
                </div>
              )}
            </dl>
          </section>

          {row.ticker && (
            <Link
              to={`/company/${row.ticker}`}
              className="inline-block rounded border border-border px-3 py-1.5 text-sm hover:bg-surface-sunken"
            >
              See Prism's research on {row.ticker} →
            </Link>
          )}
        </div>
      </Drawer>
    </DrawerStack>
  );
}

export function PositionsTable() {
  const { data, isLoading, error } = usePositions();
  const universe = useUniverse();
  // Lens scores live in the universe payload, already cached for the other
  // screens, so joining by ticker costs nothing extra.
  const lensFor = useMemo(() => {
    const index = new Map<string, UniverseRow>();
    for (const row of universe.data?.rows ?? []) index.set(row.ticker, row);
    return (ticker: string | null) => (ticker ? index.get(ticker) : undefined);
  }, [universe.data]);
  const [tab, setTab] = useState<"open" | "closed">("open");
  const [sector, setSector] = useState<string>("all");
  const [kind, setKind] = useState<string>("all");
  const [range, setRange] = useState<Range>(ALL_TIME);
  const [view, setView] = useState<"money" | "research" | "map">("money");
  const [sort, setSort] = useState<SortKey>("notional");
  const [descending, setDescending] = useState(true);
  const [openRow, setOpenRow] = useState<PositionRow | null>(null);

  const source = tab === "open" ? data?.open ?? [] : data?.closed ?? [];

  const rows = useMemo(() => {
    const filtered = source.filter((row) => {
      if (sector !== "all" && row.sector !== sector) return false;
      if (kind !== "all" && row.kind !== kind) return false;
      if (!withinRange(row.closed_at ?? row.opened_at, range)) return false;
      return true;
    });
    const value = (row: PositionRow): number | string => {
      switch (sort) {
        case "name": return row.ticker ?? row.name;
        case "notional": return row.notional ?? 0;
        case "market_value": return row.market_value ?? 0;
        case "at_risk": return row.at_risk ?? 0;
        case "pl": return (row.closed_at ? row.realised_pl : row.unrealised_pl) ?? 0;
        case "expiry": return row.days_to_expiry ?? 99999;
        case "earnings": return row.days_to_earnings ?? 99999;
        case "opened": return row.opened_at ? new Date(row.opened_at).getTime() : 0;
      }
    };
    return [...filtered].sort((a, b) => {
      const left = value(a);
      const right = value(b);
      if (typeof left === "string" || typeof right === "string") {
        const compared = String(left).localeCompare(String(right));
        return descending ? -compared : compared;
      }
      return descending ? right - left : left - right;
    });
  }, [source, sector, kind, range, sort, descending]);

  // Totals follow the filters, so narrowing to one sector answers "how much
  // do I have in semiconductors" rather than leaving a stale headline.
  const totals = useMemo<PositionTotals>(() => {
    const known = rows.filter((r) => r.at_risk !== null);
    return {
      positions: rows.length,
      notional: rows.reduce((sum, r) => sum + (r.notional ?? 0), 0),
      market_value: rows.reduce((sum, r) => sum + (r.market_value ?? 0), 0),
      delta_exposure: rows.reduce((sum, r) => sum + (r.delta_exposure ?? 0), 0),
      at_risk: known.reduce((sum, r) => sum + (r.at_risk ?? 0), 0),
      at_risk_known: known.length,
      at_risk_unknown: rows.length - known.length,
      unrealised_pl: rows.reduce((sum, r) => sum + (r.unrealised_pl ?? 0), 0),
      realised_pl: rows.reduce((sum, r) => sum + (r.realised_pl ?? 0), 0),
      funding_paid: rows.reduce((sum, r) => sum + (r.funding_paid ?? 0), 0),
      currency: "GBP",
    };
  }, [rows]);

  const toggleSort = (key: SortKey) => {
    if (key === sort) setDescending((value) => !value);
    else {
      setSort(key);
      setDescending(true);
    }
  };

  if (isLoading) return <p className="text-sm text-text-muted">Loading your positions…</p>;
  if (error) return <p className="text-sm text-negative">{(error as Error).message}</p>;
  if (!data || (data.open.length === 0 && data.closed.length === 0)) {
    return (
      <NothingYet
        headline="No positions yet"
        because="Prism reads your IG accounts overnight. Nothing has come back — either the sync has not run, or there is nothing open."
      />
    );
  }

  const header = (key: SortKey, label: string, className = "") => (
    <th className={`py-1 font-medium ${className}`}>
      <button type="button" onClick={() => toggleSort(key)} className="hover:text-text">
        {label} {sort === key && (descending ? "▾" : "▴")}
      </button>
    </th>
  );

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex overflow-hidden rounded-md border border-border">
          {(["open", "closed"] as const).map((value) => (
            <button
              key={value}
              type="button"
              onClick={() => setTab(value)}
              aria-pressed={tab === value}
              className={`px-3 py-1 text-xs ${
                tab === value ? "bg-surface-sunken font-medium" : "text-text-muted"
              }`}
            >
              {value === "open" ? "Open now" : "Closed"} (
              {value === "open" ? data.open.length : data.closed.length})
            </button>
          ))}
        </div>

        {/* Same book, three ways of reading it. */}
        <div className="flex overflow-hidden rounded-md border border-border">
          {([
            ["money", "Money"],
            ["research", "Research"],
            ["map", "Map"],
          ] as const).map(([value, labelText]) => (
            <button
              key={value}
              type="button"
              onClick={() => setView(value)}
              aria-pressed={view === value}
              title={
                value === "money"
                  ? "Sizes, risk and profit"
                  : value === "research"
                    ? "How Prism scores what you own"
                    : "Where your money is concentrated"
              }
              className={`px-3 py-1 text-xs ${
                view === value ? "bg-surface-sunken font-medium" : "text-text-muted"
              }`}
            >
              {labelText}
            </button>
          ))}
        </div>

        <Dropdown
          label="Type"
          value={kind}
          onChange={setKind}
          options={[
            { value: "all", label: "All types" },
            ...data.kinds.map((value) => ({
              value,
              label: value === "option" ? "Options" : value === "equity" ? "Shares" : value,
            })),
          ]}
        />

        <Dropdown
          label="Sector"
          value={sector}
          onChange={setSector}
          options={[
            { value: "all", label: "All sectors" },
            ...data.sectors.map((value) => ({
              value,
              label: value.replace(/_/g, " "),
            })),
          ]}
        />

        <DateRangePicker value={range} onChange={setRange} label="Date range" />

        {(kind !== "all" || sector !== "all" || range.from || range.to) && (
          <button
            type="button"
            onClick={() => {
              setKind("all");
              setSector("all");
              setRange(ALL_TIME);
            }}
            className="text-xs text-text-muted underline"
          >
            clear filters
          </button>
        )}
      </div>

      <TotalsBar
        totals={totals}
        label={tab === "open" ? "Open positions" : "Closed positions"}
      />

      {tab === "closed" && rows.length > 0 && (
        <ClosedSummary rows={rows} />
      )}

      {tab === "open" && Object.keys(data.totals_by_currency).length > 1 && (
        <p className="rounded border border-border px-3 py-2 text-xs leading-relaxed text-text-muted">
          These positions are in more than one currency and Prism has no
          exchange-rate feed, so the totals above add pounds and dollars
          together as if they were the same. Per currency:{" "}
          {Object.entries(data.totals_by_currency)
            .map(([code, t]) => `${money(t.notional, code)} notional in ${code}`)
            .join(" · ")}
          .
        </p>
      )}

      {rows.length === 0 ? (
        <p className="rounded border border-dashed border-border p-4 text-sm text-text-muted">
          Nothing matches those filters.
        </p>
      ) : view === "research" ? (
        <ResearchView rows={rows} lensFor={lensFor} onOpen={setOpenRow} />
      ) : view === "map" ? (
        <MapView rows={rows} lensFor={lensFor} onOpen={setOpenRow} />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[46rem] text-sm">
            <thead>
              <tr className="border-b border-border text-left text-[11px] uppercase tracking-wide text-text-muted">
                {header("name", "Position")}
                <th className="py-1 font-medium">Type</th>
                {header("notional", "Notional", "text-right")}
                {header("market_value", "Worth now", "text-right")}
                {header("at_risk", "Can lose", "text-right")}
                {header("pl", tab === "open" ? "P/L now" : "P/L taken", "text-right")}
                {header("earnings", "Next results", "text-right")}
                {header(tab === "open" ? "expiry" : "opened", tab === "open" ? "Expires" : "Closed", "text-right")}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const uncapped = row.at_risk === null;
                const profit = row.closed_at ? row.realised_pl : row.unrealised_pl;
                return (
                  <tr
                    key={row.deal_id}
                    onClick={() => setOpenRow(row)}
                    className="cursor-pointer border-b border-border/50 hover:bg-surface-sunken"
                  >
                    <td className="py-2">
                      <span className="font-medium">{row.ticker ?? row.name}</span>
                      {row.right && (
                        <span className="ml-1 text-xs text-text-muted">
                          {row.right} {row.strike}
                        </span>
                      )}
                      {row.has_earnings_warning && (
                        <span className="ml-1.5 text-[10px] uppercase tracking-wide text-warning">
                          earnings before expiry
                        </span>
                      )}
                      <span className="block text-[11px] text-text-muted">
                        {row.account_label} · {row.sector?.replace(/_/g, " ") ?? "unclassified"}
                      </span>
                      {(() => {
                        const scored = lensFor(row.ticker);
                        return scored ? (
                          <span
                            className="mt-1 block max-w-32"
                            title="How Prism scores this company across the six lenses"
                          >
                            <LensStrip lenses={scored.lenses} absolute={false} />
                          </span>
                        ) : null;
                      })()}
                    </td>
                    <td className="py-2 text-xs text-text-muted">
                      {row.kind === "option" ? "Option" : "Share bet"}
                    </td>
                    <td className="tabular py-2 text-right" title="Full value of the shares this controls">
                      {money(row.notional, row.currency ?? "GBP")}
                    </td>
                    <td className="tabular py-2 text-right text-text-muted">
                      {money(row.market_value, row.currency ?? "GBP")}
                    </td>
                    <td
                      className={`tabular py-2 text-right ${uncapped ? "text-warning" : ""}`}
                      title={row.at_risk_basis}
                    >
                      {uncapped ? "not capped" : money(row.at_risk, row.currency ?? "GBP")}
                    </td>
                    <td
                      className={`tabular py-2 text-right ${
                        profit === null ? "" : profit >= 0 ? "text-positive" : "text-negative"
                      }`}
                    >
                      {pl(profit, row.currency ?? "GBP")}
                    </td>
                    <td className="tabular py-2 text-right text-xs">
                      {row.next_earnings ? (
                        <span
                          className={
                            row.has_earnings_warning
                              ? "text-warning"
                              : "text-text-muted"
                          }
                          title={
                            row.has_earnings_warning
                              ? "Reports before this contract expires — option prices usually fall sharply straight after results"
                              : `Reports on ${row.next_earnings}`
                          }
                        >
                          {row.next_earnings.slice(5)} · {row.days_to_earnings}d
                        </span>
                      ) : (
                        <span className="text-text-muted/50">—</span>
                      )}
                    </td>
                    <td className="tabular py-2 text-right text-xs text-text-muted">
                      {tab === "open"
                        ? row.days_to_expiry !== null
                          ? `${row.days_to_expiry}d`
                          : "—"
                        : row.closed_at?.slice(0, 10) ?? "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
            {/* Repeated at the foot as well as the head. After scrolling a
                long list the totals are off screen, and the bottom of the
                table is where you look for them. */}
            <tfoot>
              <tr className="border-t-2 border-border-strong font-medium">
                <td className="py-2">
                  Total
                  <span className="ml-1.5 text-xs font-normal text-text-muted">
                    {totals.positions} {tab === "open" ? "open" : "closed"}
                    {rows.length !== (tab === "open" ? data.open.length : data.closed.length) &&
                      " (filtered)"}
                  </span>
                </td>
                <td />
                <td className="tabular py-2 text-right">{money(totals.notional)}</td>
                <td className="tabular py-2 text-right text-text-muted">
                  {money(totals.market_value)}
                </td>
                <td className="tabular py-2 text-right">
                  {money(totals.at_risk)}
                  {totals.at_risk_unknown > 0 && (
                    <span className="ml-1 text-[10px] font-normal text-warning">
                      +{totals.at_risk_unknown} uncapped
                    </span>
                  )}
                </td>
                <td
                  className={`tabular py-2 text-right ${
                    (tab === "open" ? totals.unrealised_pl : totals.realised_pl) >= 0
                      ? "text-positive"
                      : "text-negative"
                  }`}
                >
                  {pl(tab === "open" ? totals.unrealised_pl : totals.realised_pl)}
                </td>
                <td />
                <td />
              </tr>
            </tfoot>
          </table>
        </div>
      )}

      <p className="text-xs text-text-muted">
        Click any row for the detail. Value is what moves with the market; “can lose” is
        what you could actually lose — on a leveraged book those are very different
        numbers.
      </p>

      {openRow && <Detail row={openRow} onClose={() => setOpenRow(null)} />}
    </div>
  );
}
