import { useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { req, useDecisions, type DecisionOut } from "../api/screens";
import { EmptyState, SampleSize } from "../components/EmptyState";

const ERROR_TAGS = ["analytical", "informational", "behavioural", "sizing", "timing", "none"] as const;

export function Decisions() {
  const client = useQueryClient();
  const { data, isLoading } = useDecisions();
  const [audit, setAudit] = useState<Record<string, unknown>[] | null>(null);
  const [form, setForm] = useState({ ticker: "", kind: "buy", thesis: "", premortem: "", falsifier: "", sizing_note: "" });

  const decisions = data ?? [];
  const closed = decisions.filter((d) => d.status === "closed");
  const refresh = () => client.invalidateQueries({ queryKey: ["decisions"] });

  // The 2x2: decision quality against outcome quality. Kept separate so a
  // good decision with a bad outcome is visibly different from a bad one.
  const grid = useMemo(() => {
    const cell = (dq: string, good: boolean) =>
      closed.filter((d) => d.decision_quality === dq &&
        (good ? d.outcome_quality === "good" : d.outcome_quality === "bad"));
    return {
      goodGood: cell("good", true), goodBad: cell("good", false),
      badGood: cell("bad", true), badBad: cell("bad", false),
    };
  }, [closed]);

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-5xl px-4 py-4 sm:px-6">
        <h1 className="font-display text-3xl font-semibold tracking-tight">Decisions</h1>
        <p className="text-sm text-text-muted">
          One continuous record: raised, taken, declined, closed. Entry requires a
          thesis, a pre-mortem and a falsifier, because a decision you can't state a
          failure mode for is one you can't learn from afterwards.
        </p>

        <section className="mt-5">
          <h2 className="font-display text-lg font-semibold">Decision quality vs outcome</h2>
          <p className="text-xs text-text-muted">
            Judged separately on purpose. Collapsing them lets luck rewrite the process.
          </p>
          <div className="mt-2 grid grid-cols-2 gap-2 text-sm">
            {[
              ["Good decision, good outcome", grid.goodGood, "Process worked and paid. Repeatable."],
              ["Good decision, bad outcome", grid.goodBad, "Right call, wrong roll. Do not change the process on this evidence."],
              ["Bad decision, good outcome", grid.badGood, "Got away with it. The most dangerous quadrant — it teaches the wrong lesson."],
              ["Bad decision, bad outcome", grid.badBad, "Process failed. This is where the error tags earn their keep."],
            ].map(([label, items, note]) => (
              <div key={label as string} className="rounded-md border border-border p-3">
                <p className="text-xs font-medium">{label as string}</p>
                <p className="tabular mt-1 text-2xl">{(items as DecisionOut[]).length}</p>
                <p className="mt-1 text-[11px] text-text-muted">{note as string}</p>
              </div>
            ))}
          </div>
          <p className="mt-2 text-xs">
            {/* Sample-size honesty: never a win rate on six trades. */}
            <SampleSize n={closed.length}>
              {closed.length === 0
                ? "No closed decisions yet."
                : `${((grid.goodGood.length + grid.goodBad.length) / closed.length * 100).toFixed(0)}% of closed decisions were well-made`}
            </SampleSize>
            {closed.length < 30 && closed.length > 0 && (
              <span className="ml-2 text-text-muted">
                — too few to draw a conclusion from. Treat as anecdote until n reaches 30.
              </span>
            )}
          </p>
        </section>

        <section className="mt-6">
          <h2 className="font-display text-lg font-semibold">Raise a decision</h2>
          <form className="mt-2 space-y-2" onSubmit={async (e) => {
            e.preventDefault();
            if (!form.thesis.trim() || !form.premortem.trim() || !form.falsifier.trim()) return;
            await req("/decisions", { method: "POST", body: JSON.stringify({ ...form, ticker: form.ticker || null }) });
            setForm({ ticker: "", kind: "buy", thesis: "", premortem: "", falsifier: "", sizing_note: "" });
            refresh();
          }}>
            <div className="flex gap-2">
              <input placeholder="Ticker" value={form.ticker} onChange={(e) => setForm({ ...form, ticker: e.target.value.toUpperCase() })}
                className="tabular h-8 w-32 rounded border border-border bg-surface-raised px-2 text-sm" />
              <select value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}
                aria-label="Kind" className="h-8 rounded border border-border bg-surface-raised px-2 text-sm">
                {["buy", "sell", "trim", "add", "hold"].map((k) => <option key={k} value={k}>{k}</option>)}
              </select>
            </div>
            <textarea required placeholder="Thesis — why this, why now" rows={2} value={form.thesis}
              onChange={(e) => setForm({ ...form, thesis: e.target.value })}
              className="w-full rounded border border-border bg-surface-raised px-2 py-1 text-sm" />
            <textarea required placeholder="Pre-mortem — it's a year later and this went badly. What happened?" rows={2} value={form.premortem}
              onChange={(e) => setForm({ ...form, premortem: e.target.value })}
              className="w-full rounded border border-border bg-surface-raised px-2 py-1 text-sm" />
            <textarea required placeholder="Falsifier — what specific fact would prove this thesis wrong?" rows={2} value={form.falsifier}
              onChange={(e) => setForm({ ...form, falsifier: e.target.value })}
              className="w-full rounded border border-border bg-surface-raised px-2 py-1 text-sm" />
            <button type="submit" className="rounded border border-border px-3 py-1 text-sm">Raise it</button>
          </form>
        </section>

        <section className="mt-6">
          <h2 className="font-display text-lg font-semibold">The record</h2>
          {isLoading ? (
            <p className="mt-2 text-sm text-text-muted">Loading…</p>
          ) : decisions.length === 0 ? (
            <div className="mt-2">
              <EmptyState title="No decisions recorded">
                <p>Every suggestion raised, action taken, and candidate declined goes here — including the ones you passed on, which are the hardest to learn from later if they aren't written down.</p>
                <p>Closing a decision requires tagging what went wrong: analytical, informational, behavioural, sizing or timing.</p>
              </EmptyState>
            </div>
          ) : (
            <div className="mt-2 space-y-2">
              {decisions.map((decision) => (
                <article key={decision.stream_id} className="rounded-md border border-border p-3">
                  <div className="flex flex-wrap items-baseline gap-2">
                    <span className="tabular text-sm font-medium">{decision.ticker ?? "—"}</span>
                    <span className="text-xs text-text-muted">{decision.kind}</span>
                    <span className={`rounded-full border px-2 py-0.5 text-[10px] ${
                      decision.status === "closed" ? "border-border-strong" : "border-border text-text-muted"}`}>
                      {decision.status}
                    </span>
                    {decision.error_tag && decision.error_tag !== "none" && (
                      <span className="text-[10px] text-warning">{decision.error_tag} error</span>
                    )}
                    <span className="ml-auto text-[11px] text-text-muted">
                      {new Date(decision.raised_at).toLocaleDateString()}
                    </span>
                  </div>
                  <dl className="mt-2 space-y-1 text-xs">
                    <div><dt className="inline font-medium">Thesis: </dt><dd className="inline text-text-muted">{decision.thesis}</dd></div>
                    <div><dt className="inline font-medium">Pre-mortem: </dt><dd className="inline text-text-muted">{decision.premortem}</dd></div>
                    <div><dt className="inline font-medium">Falsifier: </dt><dd className="inline text-text-muted">{decision.falsifier}</dd></div>
                  </dl>
                  <div className="mt-2 flex flex-wrap gap-2 text-[11px]">
                    {decision.status === "raised" && (
                      <>
                        <button type="button" onClick={async () => { await req(`/decisions/${decision.stream_id}/take`, { method: "POST" }); refresh(); }}
                          className="rounded border border-border px-2 py-0.5">take</button>
                        <button type="button" onClick={async () => {
                          const reason = prompt("Why decline?"); if (!reason) return;
                          await req(`/decisions/${decision.stream_id}/decline?reason=${encodeURIComponent(reason)}`, { method: "POST" }); refresh();
                        }} className="rounded border border-border px-2 py-0.5">decline</button>
                      </>
                    )}
                    {decision.status !== "closed" && (
                      <CloseForm streamId={decision.stream_id} onDone={refresh} />
                    )}
                    <button type="button" onClick={async () => {
                      setAudit(await req(`/decisions/${decision.stream_id}/audit`));
                    }} className="text-text-muted hover:text-text underline">audit trail</button>
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>

        {audit && (
          <section className="mt-4 rounded-md border border-border p-3">
            <div className="flex items-baseline justify-between">
              <h3 className="font-display text-base font-semibold">Audit trail</h3>
              <button type="button" onClick={() => setAudit(null)} className="text-xs text-text-muted">close</button>
            </div>
            <p className="mt-1 text-[11px] text-text-muted">
              When it happened and when we were told are different facts, so both are shown.
            </p>
            <table className="mt-2 w-full text-xs">
              <thead className="text-[10px] uppercase tracking-wide text-text-muted">
                <tr><th className="text-left font-medium">Event</th><th className="text-left font-medium">Occurred</th>
                <th className="text-left font-medium">Recorded</th><th className="text-left font-medium">Actor</th></tr>
              </thead>
              <tbody>
                {audit.map((event) => (
                  <tr key={String(event.id)} className="border-t border-border">
                    <td className="py-1">{String(event.event_type)}</td>
                    <td className="tabular py-1">{new Date(String(event.occurred_at)).toLocaleString()}</td>
                    <td className="tabular py-1">{new Date(String(event.recorded_at)).toLocaleString()}</td>
                    <td className="py-1 text-text-muted">{String(event.actor)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        )}
      </div>
    </div>
  );
}

function CloseForm({ streamId, onDone }: { streamId: string; onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [state, setState] = useState({ decision_quality: "good", outcome_quality: "good", error_tag: "none", note: "" });

  if (!open) return <button type="button" onClick={() => setOpen(true)} className="rounded border border-border px-2 py-0.5">close</button>;

  return (
    <form className="mt-1 flex w-full flex-wrap gap-2" onSubmit={async (e) => {
      e.preventDefault();
      await req(`/decisions/${streamId}/close`, { method: "POST", body: JSON.stringify(state) });
      setOpen(false); onDone();
    }}>
      <select value={state.decision_quality} onChange={(e) => setState({ ...state, decision_quality: e.target.value })}
        aria-label="Decision quality" className="h-7 rounded border border-border bg-surface-raised px-1 text-[11px]">
        <option value="good">good decision</option><option value="bad">bad decision</option>
      </select>
      <select value={state.outcome_quality} onChange={(e) => setState({ ...state, outcome_quality: e.target.value })}
        aria-label="Outcome quality" className="h-7 rounded border border-border bg-surface-raised px-1 text-[11px]">
        <option value="good">good outcome</option><option value="bad">bad outcome</option><option value="neutral">neutral</option>
      </select>
      <select value={state.error_tag} onChange={(e) => setState({ ...state, error_tag: e.target.value })}
        aria-label="Error tag" className="h-7 rounded border border-border bg-surface-raised px-1 text-[11px]">
        {ERROR_TAGS.map((tag) => <option key={tag} value={tag}>{tag}</option>)}
      </select>
      <button type="submit" className="rounded border border-border px-2 py-0.5 text-[11px]">save</button>
    </form>
  );
}
