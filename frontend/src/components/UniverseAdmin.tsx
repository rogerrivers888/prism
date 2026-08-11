import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { API_BASE_URL } from "../api/config";
import { req } from "../api/screens";
import { Drawer } from "./Drawer";

type Health = {
  total: number;
  sectors: { sector: string; members: number; ranks_on_peers: boolean }[];
  thin_sectors: string[];
};

export const useUniverseHealth = () =>
  useQuery({
    queryKey: ["universe-health"],
    queryFn: async (): Promise<Health> => {
      const response = await fetch(`${API_BASE_URL}/universe/health`);
      if (!response.ok) throw new Error("health failed");
      return response.json();
    },
  });

export function UniverseAdmin({ onClose }: { onClose: () => void }) {
  const client = useQueryClient();
  const health = useUniverseHealth();
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);

  const tickers = input.split(/[\s,]+/).map((t) => t.trim()).filter(Boolean);

  const add = async () => {
    if (!tickers.length || busy) return;
    setBusy(true); setError(null); setResult(null);
    try {
      setResult(await req("/universe/securities", { method: "POST", body: JSON.stringify({ tickers }) }));
      setInput("");
      client.invalidateQueries({ queryKey: ["universe"] });
      client.invalidateQueries({ queryKey: ["universe-health"] });
    } catch (exc) {
      setError((exc as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Drawer title="Universe" subtitle={`${health.data?.total ?? "—"} active securities`} onClose={onClose}>
      <div className="space-y-4">
        {/* The universe should stay large. Say so where it can be shrunk. */}
        <div className="rounded-md border border-border bg-surface p-3 text-xs leading-relaxed">
          <p className="font-medium">Keep this large.</p>
          <p className="mt-1 text-text-muted">
            Peer percentiles need at least 8 members in a sector. Below that, every
            metric in that sector silently falls back to absolute bands — the scores
            still appear, but they stop being rankings.
          </p>
          <p className="mt-1 text-text-muted">
            Narrowing your attention belongs in the watchlist, not here.
          </p>
        </div>

        <section>
          <h3 className="text-[11px] font-medium uppercase tracking-wide text-text-muted">Add securities</h3>
          <textarea value={input} onChange={(e) => setInput(e.target.value)} rows={3}
            placeholder="MU, NVDA, ASML.US, VLX.LSE — paste a list, one or many"
            className="tabular mt-1 w-full rounded border border-border bg-surface-raised px-2 py-1 text-sm" />
          <div className="mt-1 flex items-center gap-2">
            <button type="button" onClick={() => void add()} disabled={busy || !tickers.length}
              className="rounded border border-border px-3 py-1 text-xs disabled:opacity-40">
              {busy ? "ingesting…" : `Add ${tickers.length || ""}`.trim()}
            </button>
            <span className="text-[11px] text-text-muted">
              {tickers.length > 0 && `~${tickers.length * 3} API calls · a few seconds each`}
            </span>
          </div>
          {busy && (
            <p className="mt-2 text-xs text-text-muted">
              Fetching full price history and fundamentals. This takes a few seconds per
              ticker and can't be hurried — the first ingest pulls decades of data.
            </p>
          )}
          {result && (
            <div className="mt-2 rounded border border-border p-2 text-xs">
              <p>Ingested {String(result.ingested)} of {String(result.requested)}
                {Number(result.already_held) > 0 && `, ${String(result.already_held)} already held`}.</p>
              {Object.keys((result.failed as object) ?? {}).length > 0 && (
                <p className="mt-1 text-warning">Failed: {Object.keys(result.failed as object).join(", ")}</p>
              )}
              <p className="mt-1 text-text-muted">
                They'll be scored on tonight's run, and added to the nightly job automatically.
              </p>
            </div>
          )}
          {error && <p className="mt-2 text-xs text-negative">{error}</p>}
        </section>

        <section>
          <h3 className="text-[11px] font-medium uppercase tracking-wide text-text-muted">
            Peer counts by sector
          </h3>
          {(health.data?.thin_sectors.length ?? 0) > 0 && (
            <p className="mt-1 rounded border border-warning/50 p-2 text-xs text-warning">
              {health.data?.thin_sectors.length} sector
              {health.data?.thin_sectors.length === 1 ? " has" : "s have"} fewer than 8
              members and score on bands rather than ranks.
            </p>
          )}
          <table className="mt-1 w-full text-xs">
            <tbody>
              {(health.data?.sectors ?? []).map((sector) => (
                <tr key={sector.sector} className="border-t border-border">
                  <td className="py-1">{sector.sector.replace(/_/g, " ")}</td>
                  <td className="tabular py-1 text-right">{sector.members}</td>
                  <td className="py-1 pl-2 text-right text-[10px]">
                    {sector.ranks_on_peers ? (
                      <span className="text-text-muted">ranks</span>
                    ) : (
                      <span className="text-warning">bands only</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </div>
    </Drawer>
  );
}
