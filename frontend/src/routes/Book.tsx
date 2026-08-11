import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { req, useBook } from "../api/screens";
import { EmptyState } from "../components/EmptyState";

const SLEEVES = {
  high_growth: {
    label: "High growth",
    // Exit discipline differs per sleeve, so the UI states it where positions
    // are assigned rather than leaving it as folklore.
    exit: "Exit on price. A growth position is a bet on continuation, so a broken price structure is the thesis breaking — respect the stop and don't renegotiate it.",
  },
  deeply_undervalued: {
    label: "Deeply undervalued",
    exit: "Exit on time and thesis, not price. A cheap stock getting cheaper is not automatically wrong. Set a date by which the re-rating should have started, and a specific fact that would prove the thesis wrong.",
  },
} as const;

export function Book() {
  const client = useQueryClient();
  const { data, isLoading } = useBook();
  const [capital, setCapital] = useState<number | "">("");
  const [form, setForm] = useState({
    instrument: "", instrument_type: "share", side: "buy",
    quantity: "", price: "", stop: "", sleeve: "high_growth", currency: "GBP",
  });

  const positions = data?.positions ?? [];
  const notional = data?.total_notional ?? 0;
  const committed = typeof capital === "number" ? capital : null;

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-5xl px-4 py-4 sm:px-6">
        <h1 className="font-display text-3xl font-semibold tracking-tight">Book</h1>

        {isLoading ? (
          <p className="mt-3 text-sm text-text-muted">Loading positions…</p>
        ) : positions.length === 0 ? (
          <div className="mt-4 space-y-4">
            <EmptyState title="No open positions">
              <p>Positions appear here once trades are recorded. Every position is derived from the event log, so nothing here is typed twice.</p>
              <p>Use the form below to record your first trade — it writes a TradeExecuted event, the same path the broker import will use later.</p>
            </EmptyState>
          </div>
        ) : (
          <>
            {/* Exposure rail: notional against committed capital, with the
                spread-bet overhang shown separately rather than folded in. */}
            <section className="mt-4">
              <div className="flex flex-wrap items-baseline gap-3">
                <h2 className="font-display text-lg font-semibold">Exposure</h2>
                <label className="text-xs text-text-muted">
                  Committed capital
                  <input type="number" value={capital} onChange={(e) => setCapital(e.target.value === "" ? "" : Number(e.target.value))}
                    className="tabular ml-2 h-7 w-32 rounded border border-border bg-surface-raised px-1 text-text" />
                </label>
              </div>
              {committed ? (
                <div className="mt-2">
                  <div className="relative h-6 w-full overflow-hidden rounded bg-surface-sunken">
                    <div className="absolute inset-y-0 left-0 bg-lens-quality opacity-70"
                      style={{ width: `${Math.min(100, (notional / committed) * 100)}%` }} />
                    {notional > committed && (
                      <div className="absolute inset-y-0 right-0 bg-warning opacity-70"
                        style={{ width: `${Math.min(60, ((notional - committed) / committed) * 100)}%` }} />
                    )}
                  </div>
                  <p className="mt-1 text-xs text-text-muted">
                    <span className="tabular">{notional.toLocaleString()}</span> notional against{" "}
                    <span className="tabular">{committed.toLocaleString()}</span> committed —{" "}
                    <span className="tabular">{((notional / committed) * 100).toFixed(0)}%</span>.
                    {notional > committed && " Spread bets control more than the margin posted, so notional exceeds capital."}
                  </p>
                </div>
              ) : (
                <p className="mt-1 text-xs text-text-muted">Enter committed capital to see exposure against it.</p>
              )}
            </section>

            <section className="mt-5">
              <h2 className="font-display text-lg font-semibold">Positions</h2>
              <table className="mt-2 w-full text-sm">
                <thead className="text-[11px] uppercase tracking-wide text-text-muted">
                  <tr>
                    <th className="text-left font-medium">Ticker</th><th className="text-left font-medium">Type</th>
                    <th className="text-left font-medium">Sleeve</th><th className="text-right font-medium">Size</th>
                    <th className="text-right font-medium">Entry</th><th className="text-right font-medium">Stop</th>
                    <th className="text-right font-medium">Risk</th>
                  </tr>
                </thead>
                <tbody>
                  {positions.map((p) => (
                    <tr key={String(p.stream_id)} className="border-t border-border">
                      <td className="tabular py-1">{String(p.ticker)}</td>
                      {/* Instrument type is shown, never inferred. */}
                      <td className="py-1 text-xs">{String(p.instrument_type)}</td>
                      <td className="py-1 text-xs">
                        {p.sleeve ? SLEEVES[p.sleeve as keyof typeof SLEEVES]?.label : <span className="text-warning">unassigned</span>}
                      </td>
                      <td className="tabular py-1 text-right">{Number(p.size).toLocaleString()}</td>
                      <td className="tabular py-1 text-right">{Number(p.entry_price).toFixed(2)}</td>
                      <td className="tabular py-1 text-right">{p.current_stop ? Number(p.current_stop).toFixed(2) : "—"}</td>
                      <td className="tabular py-1 text-right">{p.current_risk ? Number(p.current_risk).toFixed(0) : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>

            <section className="mt-5">
              <h2 className="font-display text-lg font-semibold">Correlated clusters</h2>
              <p className="text-xs text-text-muted">
                Positions sharing a driver are one bet wearing several names. Sector is a
                coarse proxy for that driver and is labelled as such.
              </p>
              <div className="mt-2 space-y-2">
                {(data?.clusters ?? []).map((cluster) => (
                  <div key={cluster.driver} className="rounded-md border border-border p-2">
                    <div className="flex items-baseline justify-between">
                      <span className="text-sm">{cluster.driver.replace(/_/g, " ")}</span>
                      <span className="tabular text-xs text-text-muted">
                        {cluster.positions.length} position{cluster.positions.length === 1 ? "" : "s"} ·{" "}
                        {cluster.notional.toLocaleString()} notional
                      </span>
                    </div>
                    <p className="tabular mt-1 text-[11px] text-text-muted">{cluster.positions.join(" · ")}</p>
                    {cluster.positions.length > 1 && (
                      <p className="mt-1 text-[11px] text-warning">
                        These move together. Treat this as one position of {cluster.notional.toLocaleString()}, not {cluster.positions.length}.
                      </p>
                    )}
                  </div>
                ))}
              </div>
            </section>
          </>
        )}

        <section className="mt-6">
          <h2 className="font-display text-lg font-semibold">Record a trade</h2>
          <div className="mt-1 grid gap-2 text-xs sm:grid-cols-2">
            {Object.entries(SLEEVES).map(([key, sleeve]) => (
              <div key={key} className="rounded-md border border-border p-2">
                <p className="text-sm font-medium">{sleeve.label}</p>
                <p className="mt-1 text-text-muted">{sleeve.exit}</p>
              </div>
            ))}
          </div>
          <form className="mt-3 grid gap-2 sm:grid-cols-3" onSubmit={async (e) => {
            e.preventDefault();
            if (!form.instrument || !form.quantity || !form.price) return;
            await req("/book/trades", { method: "POST", body: JSON.stringify({
              instrument: form.instrument, instrument_type: form.instrument_type, side: form.side,
              quantity: Number(form.quantity), price: Number(form.price),
              stop: form.stop ? Number(form.stop) : null, sleeve: form.sleeve,
              currency: form.currency, occurred_at: new Date().toISOString() }) });
            setForm({ ...form, instrument: "", quantity: "", price: "", stop: "" });
            client.invalidateQueries({ queryKey: ["book"] });
          }}>
            <input placeholder="Ticker" value={form.instrument} onChange={(e) => setForm({ ...form, instrument: e.target.value.toUpperCase() })}
              className="tabular h-8 rounded border border-border bg-surface-raised px-2 text-sm" />
            <select value={form.instrument_type} onChange={(e) => setForm({ ...form, instrument_type: e.target.value })}
              aria-label="Instrument type" className="h-8 rounded border border-border bg-surface-raised px-2 text-sm">
              <option value="share">share</option><option value="spreadbet">spreadbet</option><option value="option">option</option>
            </select>
            <select value={form.sleeve} onChange={(e) => setForm({ ...form, sleeve: e.target.value })}
              aria-label="Sleeve" className="h-8 rounded border border-border bg-surface-raised px-2 text-sm">
              <option value="high_growth">high growth</option><option value="deeply_undervalued">deeply undervalued</option>
            </select>
            <select value={form.side} onChange={(e) => setForm({ ...form, side: e.target.value })}
              aria-label="Side" className="h-8 rounded border border-border bg-surface-raised px-2 text-sm">
              <option value="buy">buy</option><option value="sell">sell</option>
            </select>
            <input placeholder="Quantity" type="number" value={form.quantity} onChange={(e) => setForm({ ...form, quantity: e.target.value })}
              className="tabular h-8 rounded border border-border bg-surface-raised px-2 text-sm" />
            <input placeholder="Price" type="number" value={form.price} onChange={(e) => setForm({ ...form, price: e.target.value })}
              className="tabular h-8 rounded border border-border bg-surface-raised px-2 text-sm" />
            <input placeholder="Stop (sets R)" type="number" value={form.stop} onChange={(e) => setForm({ ...form, stop: e.target.value })}
              className="tabular h-8 rounded border border-border bg-surface-raised px-2 text-sm" />
            <button type="submit" className="h-8 rounded border border-border px-3 text-sm sm:col-span-2">Record trade</button>
          </form>
          <p className="mt-1 text-[11px] text-text-muted">
            The stop entered here sets R for the life of the position. Leave it blank and
            initial risk stays unknown rather than being invented later.
          </p>
        </section>
      </div>
    </div>
  );
}
