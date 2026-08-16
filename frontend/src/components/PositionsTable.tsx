import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { usePositions, useIGBook, type PositionRow, type PositionTotals } from "../api/ig";
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

type SortKey = "name" | "notional" | "at_risk" | "pl" | "expiry" | "opened";

function TotalsBar({ totals, label }: { totals: PositionTotals; label: string }) {
  return (
    <div className="grid grid-cols-2 gap-3 rounded-md border border-border bg-surface-sunken p-3 sm:grid-cols-4">
      <div>
        <div className="text-[11px] uppercase tracking-wide text-text-muted">
          {label}
        </div>
        <div className="tabular text-lg">{totals.positions}</div>
      </div>
      <div>
        <div className="text-[11px] uppercase tracking-wide text-text-muted">
          Total position value
        </div>
        <div className="tabular text-lg">{money(totals.notional)}</div>
        <p className="mt-0.5 text-[11px] leading-tight text-text-muted">
          How much value moves with the market.
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
                <dt className="text-xs text-text-muted">Position value</dt>
                <dd className="tabular">{money(row.notional, row.currency ?? "GBP")}</dd>
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
  const [tab, setTab] = useState<"open" | "closed">("open");
  const [sector, setSector] = useState<string>("all");
  const [kind, setKind] = useState<string>("all");
  const [period, setPeriod] = useState<string>("all");
  const [sort, setSort] = useState<SortKey>("notional");
  const [descending, setDescending] = useState(true);
  const [openRow, setOpenRow] = useState<PositionRow | null>(null);

  const source = tab === "open" ? data?.open ?? [] : data?.closed ?? [];

  const rows = useMemo(() => {
    const cutoff =
      period === "all"
        ? null
        : new Date(Date.now() - Number(period) * 24 * 60 * 60 * 1000);
    const filtered = source.filter((row) => {
      if (sector !== "all" && row.sector !== sector) return false;
      if (kind !== "all" && row.kind !== kind) return false;
      if (cutoff) {
        const stamp = row.closed_at ?? row.opened_at;
        if (!stamp || new Date(stamp) < cutoff) return false;
      }
      return true;
    });
    const value = (row: PositionRow): number | string => {
      switch (sort) {
        case "name": return row.ticker ?? row.name;
        case "notional": return row.notional ?? 0;
        case "at_risk": return row.at_risk ?? 0;
        case "pl": return (row.closed_at ? row.realised_pl : row.unrealised_pl) ?? 0;
        case "expiry": return row.days_to_expiry ?? 99999;
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
  }, [source, sector, kind, period, sort, descending]);

  // Totals follow the filters, so narrowing to one sector answers "how much
  // do I have in semiconductors" rather than leaving a stale headline.
  const totals = useMemo<PositionTotals>(() => {
    const known = rows.filter((r) => r.at_risk !== null);
    return {
      positions: rows.length,
      notional: rows.reduce((sum, r) => sum + (r.notional ?? 0), 0),
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

        <select
          value={kind}
          onChange={(event) => setKind(event.target.value)}
          aria-label="Filter by type"
          className="rounded border border-border bg-surface-raised px-2 py-1 text-xs"
        >
          <option value="all">All types</option>
          {data.kinds.map((value) => (
            <option key={value} value={value}>
              {value === "option" ? "Options" : value === "equity" ? "Shares" : value}
            </option>
          ))}
        </select>

        <select
          value={sector}
          onChange={(event) => setSector(event.target.value)}
          aria-label="Filter by sector"
          className="rounded border border-border bg-surface-raised px-2 py-1 text-xs"
        >
          <option value="all">All sectors</option>
          {data.sectors.map((value) => (
            <option key={value} value={value}>
              {value.replace(/_/g, " ")}
            </option>
          ))}
        </select>

        <select
          value={period}
          onChange={(event) => setPeriod(event.target.value)}
          aria-label="Filter by period"
          className="rounded border border-border bg-surface-raised px-2 py-1 text-xs"
        >
          <option value="all">Any time</option>
          <option value="30">Last 30 days</option>
          <option value="90">Last 3 months</option>
          <option value="365">Last year</option>
        </select>

        {(kind !== "all" || sector !== "all" || period !== "all") && (
          <button
            type="button"
            onClick={() => {
              setKind("all");
              setSector("all");
              setPeriod("all");
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

      {rows.length === 0 ? (
        <p className="rounded border border-dashed border-border p-4 text-sm text-text-muted">
          Nothing matches those filters.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[46rem] text-sm">
            <thead>
              <tr className="border-b border-border text-left text-[11px] uppercase tracking-wide text-text-muted">
                {header("name", "Position")}
                <th className="py-1 font-medium">Type</th>
                {header("notional", "Value", "text-right")}
                {header("at_risk", "Can lose", "text-right")}
                {header("pl", tab === "open" ? "P/L now" : "P/L taken", "text-right")}
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
                    </td>
                    <td className="py-2 text-xs text-text-muted">
                      {row.kind === "option" ? "Option" : "Share bet"}
                    </td>
                    <td className="tabular py-2 text-right">
                      {money(row.notional, row.currency ?? "GBP")}
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
