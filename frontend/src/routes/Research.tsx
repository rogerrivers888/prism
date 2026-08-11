import { useState } from "react";
import { req, useClips, usePoints, useSectorAggregates, type Point } from "../api/screens";
import { useQueryClient } from "@tanstack/react-query";
import { EmptyState } from "../components/EmptyState";
import { AskClaude } from "../components/AskClaude";
import { DrawerStack } from "../components/Drawer";

export function Research() {
  const client = useQueryClient();
  const [scope, setScope] = useState("semiconductors");
  const points = usePoints(scope);
  const [search, setSearch] = useState("");
  const clips = useClips(search);
  const aggregates = useSectorAggregates();
  const [stressing, setStressing] = useState<Point | null>(null);

  const [draft, setDraft] = useState({ body: "", stance: "for" as "for" | "against", source_title: "", source_url: "" });
  const [clipDraft, setClipDraft] = useState({ title: "", body: "", url: "" });

  const refresh = () => {
    client.invalidateQueries({ queryKey: ["points"] });
    client.invalidateQueries({ queryKey: ["clips"] });
  };

  const sectorRows = (aggregates.data ?? []).filter((r) => r.sector === scope);

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-5xl px-4 py-4 sm:px-6">
        <h1 className="font-display text-3xl font-semibold tracking-tight">Research</h1>

        <label className="mt-2 flex items-center gap-2 text-xs text-text-muted">
          Sector
          <input value={scope} onChange={(e) => setScope(e.target.value)}
            className="tabular h-8 rounded border border-border bg-surface-raised px-2 text-sm text-text" />
        </label>

        {/* The evidence the case is argued against. */}
        <section className="mt-4">
          <h2 className="font-display text-lg font-semibold">Sector readings</h2>
          {sectorRows.length === 0 ? (
            <p className="mt-1 text-sm text-text-muted">No aggregates for that sector.</p>
          ) : (
            <table className="mt-1 w-full text-sm">
              <thead className="text-[11px] uppercase tracking-wide text-text-muted">
                <tr><th className="text-left font-medium">Lens</th><th className="text-right font-medium">Median relative</th>
                <th className="text-right font-medium">Median absolute</th><th className="text-right font-medium">Members</th></tr>
              </thead>
              <tbody>
                {sectorRows.map((r) => (
                  <tr key={String(r.lens)} className="border-t border-border">
                    <td className="py-1">{String(r.lens)}</td>
                    <td className="tabular py-1 text-right">{r.median_score === null ? "—" : Number(r.median_score).toFixed(1)}</td>
                    <td className="tabular py-1 text-right">{r.median_score_absolute === null ? "—" : Number(r.median_score_absolute).toFixed(1)}</td>
                    <td className="tabular py-1 text-right text-text-muted">{String(r.member_count)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        <section className="mt-6 grid gap-4 lg:grid-cols-2">
          {(["for", "against"] as const).map((stance) => (
            <div key={stance}>
              <h2 className="font-display text-lg font-semibold capitalize">The case {stance}</h2>
              <div className="mt-2 space-y-2">
                {(points.data ?? []).filter((p) => p.stance === stance).map((point) => (
                  <article key={point.id} className="rounded-md border border-border p-3">
                    <p className="text-sm leading-relaxed">{point.body}</p>
                    {point.source_title && (
                      <p className="mt-1 text-[11px] text-text-muted">
                        {point.source_url ? (
                          <a href={point.source_url} target="_blank" rel="noreferrer" className="underline">{point.source_title}</a>
                        ) : point.source_title}
                      </p>
                    )}
                    {point.stress_test && (
                      <p className="mt-2 rounded bg-surface-sunken p-2 text-xs leading-relaxed">
                        <span className="font-medium">Stress test: </span>{point.stress_test}
                      </p>
                    )}
                    <div className="mt-2 flex gap-2 text-[11px]">
                      <button type="button" onClick={async () => {
                        await req(`/research/points/${point.id}`, { method: "PATCH", body: JSON.stringify({ pinned: !point.pinned }) });
                        refresh();
                      }} className="text-text-muted hover:text-text">{point.pinned ? "unpin" : "pin"}</button>
                      <button type="button" onClick={() => setStressing(point)} className="text-text-muted hover:text-text">stress-test with Claude</button>
                      <button type="button" onClick={async () => {
                        await req(`/research/points/${point.id}`, { method: "DELETE" }); refresh();
                      }} className="text-text-muted hover:text-negative">delete</button>
                    </div>
                  </article>
                ))}
                {(points.data ?? []).filter((p) => p.stance === stance).length === 0 && (
                  <EmptyState title={`Nothing ${stance} yet`}>
                    <p>Write the argument {stance} this sector here, one point at a time, each with the source it came from.</p>
                    <p>Pin the ones that survive scrutiny.</p>
                  </EmptyState>
                )}
              </div>
            </div>
          ))}
        </section>

        <form className="mt-4 space-y-2 rounded-md border border-border p-3" onSubmit={async (e) => {
          e.preventDefault();
          if (!draft.body.trim()) return;
          await req("/research/points", { method: "POST", body: JSON.stringify({
            scope_type: "sector", scope_value: scope, stance: draft.stance, body: draft.body,
            source_title: draft.source_title || null, source_url: draft.source_url || null }) });
          setDraft({ body: "", stance: draft.stance, source_title: "", source_url: "" });
          refresh();
        }}>
          <div className="flex gap-2">
            <select value={draft.stance} onChange={(e) => setDraft({ ...draft, stance: e.target.value as "for" | "against" })}
              aria-label="Stance" className="h-8 rounded border border-border bg-surface-raised px-2 text-xs">
              <option value="for">for</option><option value="against">against</option>
            </select>
            <input placeholder="Source title" value={draft.source_title} onChange={(e) => setDraft({ ...draft, source_title: e.target.value })}
              className="h-8 flex-1 rounded border border-border bg-surface-raised px-2 text-sm" />
            <input placeholder="Source URL" value={draft.source_url} onChange={(e) => setDraft({ ...draft, source_url: e.target.value })}
              className="h-8 flex-1 rounded border border-border bg-surface-raised px-2 text-sm" />
          </div>
          <textarea placeholder="The point itself" value={draft.body} onChange={(e) => setDraft({ ...draft, body: e.target.value })}
            rows={2} className="w-full rounded border border-border bg-surface-raised px-2 py-1 text-sm" />
          <button type="submit" className="rounded border border-border px-3 py-1 text-xs">Add point</button>
        </form>

        <section className="mt-8">
          <div className="flex flex-wrap items-baseline gap-3">
            <h2 className="font-display text-lg font-semibold">Clipped research</h2>
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search everything clipped"
              aria-label="Search clips" className="h-8 flex-1 rounded border border-border bg-surface-raised px-2 text-sm" />
          </div>
          <form className="mt-2 space-y-2 rounded-md border border-border p-3" onSubmit={async (e) => {
            e.preventDefault();
            if (!clipDraft.body.trim()) return;
            await req("/research/clips", { method: "POST", body: JSON.stringify({
              title: clipDraft.title || clipDraft.body.slice(0, 60), body: clipDraft.body, url: clipDraft.url || null }) });
            setClipDraft({ title: "", body: "", url: "" });
            refresh();
          }}>
            <div className="flex gap-2">
              <input placeholder="Title" value={clipDraft.title} onChange={(e) => setClipDraft({ ...clipDraft, title: e.target.value })}
                className="h-8 flex-1 rounded border border-border bg-surface-raised px-2 text-sm" />
              <input placeholder="URL (optional)" value={clipDraft.url} onChange={(e) => setClipDraft({ ...clipDraft, url: e.target.value })}
                className="h-8 flex-1 rounded border border-border bg-surface-raised px-2 text-sm" />
            </div>
            <textarea placeholder="Paste the text" value={clipDraft.body} rows={3}
              onChange={(e) => setClipDraft({ ...clipDraft, body: e.target.value })}
              className="w-full rounded border border-border bg-surface-raised px-2 py-1 text-sm" />
            <button type="submit" className="rounded border border-border px-3 py-1 text-xs">Clip it</button>
          </form>

          <div className="mt-3 space-y-2">
            {(clips.data ?? []).map((clip) => (
              <article key={clip.id} className="rounded-md border border-border p-3">
                <h3 className="text-sm font-medium">{clip.title}</h3>
                {clip.summary && <p className="mt-1 text-xs text-text-muted">{clip.summary}</p>}
                <p className="mt-1 line-clamp-3 text-xs leading-relaxed text-text-muted">{clip.body}</p>
                {clip.tickers.length > 0 && (
                  <p className="tabular mt-1 text-[11px] text-text-muted">{clip.tickers.join(" · ")}</p>
                )}
              </article>
            ))}
            {(clips.data ?? []).length === 0 && (
              <EmptyState title="Nothing clipped yet">
                <p>Paste an article, a transcript, or a note. It becomes searchable across everything else you've saved.</p>
              </EmptyState>
            )}
          </div>
        </section>
      </div>

      <DrawerStack>
        {stressing && (
          <AskClaude
            context={{ screen: "research", sector: scope, stance: stressing.stance, point: stressing.body,
              source: stressing.source_title, instruction: "Stress-test this argument. Name the strongest objection and what evidence would settle it." }}
            onClose={() => setStressing(null)}
          />
        )}
      </DrawerStack>
    </div>
  );
}
