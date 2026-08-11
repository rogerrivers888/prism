import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { API_BASE_URL } from "../api/config";
import { req } from "../api/screens";
import { Drawer } from "./Drawer";

type SearchHit = {
  ticker: string; code: string; exchange: string; name: string;
  type: string | null; currency: string | null; already_held: boolean;
};
type Health = {
  total: number;
  sectors: { sector: string; members: number; ranks_on_peers: boolean }[];
  thin_sectors: string[];
};
type Added = { ticker: string; name: string };

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
  const navigate = useNavigate();
  const health = useUniverseHealth();

  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [staged, setStaged] = useState<SearchHit[]>([]);
  const [busy, setBusy] = useState(false);
  const [added, setAdded] = useState<Added[]>([]);
  const [failed, setFailed] = useState<[string, string][]>([]);
  const [error, setError] = useState<string | null>(null);

  // Type-ahead: debounced so a fast typist doesn't fire one request per
  // keystroke, but short enough that results feel like they arrive as you type.
  useEffect(() => {
    const text = query.trim();
    if (text.length < 2) { setHits(null); setSearching(false); return; }
    setSearching(true);
    const timer = setTimeout(async () => {
      try {
        setHits(await req<SearchHit[]>(`/universe/search?q=${encodeURIComponent(text)}`));
      } catch { setHits([]); } finally { setSearching(false); }
    }, 250);
    return () => clearTimeout(timer);
  }, [query]);

  const stagedTickers = useMemo(() => new Set(staged.map((s) => s.ticker)), [staged]);

  const stage = (hit: SearchHit) => {
    if (hit.already_held || stagedTickers.has(hit.ticker)) return;
    setStaged((current) => [...current, hit]);
    setQuery(""); setHits(null);
  };

  const confirm = async () => {
    if (!staged.length || busy) return;
    setBusy(true); setError(null); setFailed([]);
    try {
      const result = await req<{ ingested: number; failed: Record<string, string> }>(
        "/universe/securities",
        { method: "POST", body: JSON.stringify({ tickers: staged.map((s) => s.ticker) }) },
      );
      const failures = Object.entries(result.failed ?? {});
      const failedTickers = new Set(failures.map(([t]) => t));
      setAdded((current) => [
        ...staged.filter((s) => !failedTickers.has(s.ticker))
          .map((s) => ({ ticker: s.code, name: s.name })),
        ...current,
      ]);
      setFailed(failures);
      setStaged(staged.filter((s) => failedTickers.has(s.ticker)));
      client.invalidateQueries({ queryKey: ["universe"] });
      client.invalidateQueries({ queryKey: ["universe-health"] });
    } catch (exc) {
      setError((exc as Error).message);
    } finally { setBusy(false); }
  };

  return (
    <Drawer title="Add securities" subtitle={`${health.data?.total ?? "—"} in the universe`}
      onClose={onClose} width="w-[min(94vw,30rem)]">
      <div className="space-y-5">
        <section>
          <label htmlFor="ticker-search" className="text-[11px] font-medium uppercase tracking-wide text-text-muted">
            Search by company or ticker
          </label>
          <input id="ticker-search" value={query} onChange={(e) => setQuery(e.target.value)}
            placeholder="Cineverse, Micron, NVDA…" autoComplete="off"
            className="mt-1 w-full rounded border border-border bg-surface-raised px-2 py-1.5 text-sm" />

          {searching && hits === null && query.trim().length >= 2 && (
            <p className="mt-1 text-xs text-text-muted">searching…</p>
          )}

          {hits !== null && (
            <div className="mt-1 overflow-hidden rounded border border-border">
              {hits.length === 0 ? (
                <p className="px-2 py-2 text-xs text-text-muted">
                  Nothing matched “{query.trim()}”. Try fewer words, or the ticker itself.
                </p>
              ) : hits.map((hit) => {
                const disabled = hit.already_held || stagedTickers.has(hit.ticker);
                return (
                  <button key={`${hit.code}.${hit.exchange}`} type="button" disabled={disabled}
                    onClick={() => stage(hit)}
                    className="flex w-full items-baseline gap-2 border-b border-border px-2 py-2 text-left last:border-0 hover:bg-surface-sunken disabled:cursor-default disabled:opacity-45">
                    <span className="tabular w-24 shrink-0 text-xs font-medium">{hit.ticker}</span>
                    <span className="min-w-0 flex-1 truncate text-xs">{hit.name}</span>
                    <span className="shrink-0 text-[10px] text-text-muted">
                      {hit.already_held ? "already held" : stagedTickers.has(hit.ticker) ? "selected" : (hit.type ?? hit.exchange)}
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        </section>

        {staged.length > 0 && (
          <section>
            <h3 className="text-[11px] font-medium uppercase tracking-wide text-text-muted">Selected</h3>
            <ul className="mt-1 space-y-1">
              {staged.map((hit) => (
                <li key={hit.ticker} className="flex items-baseline gap-2 rounded border border-border px-2 py-1.5">
                  <span className="tabular w-24 shrink-0 text-xs font-medium">{hit.ticker}</span>
                  <span className="min-w-0 flex-1 truncate text-xs text-text-muted">{hit.name}</span>
                  <button type="button" aria-label={`Remove ${hit.ticker}`}
                    onClick={() => setStaged((c) => c.filter((s) => s.ticker !== hit.ticker))}
                    className="shrink-0 text-xs text-text-muted hover:text-text">✕</button>
                </li>
              ))}
            </ul>
            <button type="button" onClick={() => void confirm()} disabled={busy}
              className="mt-2 w-full rounded border border-border-strong bg-surface-sunken px-3 py-1.5 text-sm font-medium disabled:opacity-50">
              {busy ? `Adding ${staged.length}…` : `Confirm — add ${staged.length} ${staged.length === 1 ? "security" : "securities"}`}
            </button>
            {busy && (
              <p className="mt-1 text-xs text-text-muted">
                Pulling full price history and fundamentals. A few seconds each — this can't be hurried.
              </p>
            )}
          </section>
        )}

        {failed.length > 0 && (
          <section className="rounded border border-warning/50 p-2">
            {failed.map(([ticker, reason]) => (
              <p key={ticker} className="text-xs text-warning">
                <span className="tabular">{ticker}</span>{" "}
                {reason.includes("404")
                  ? "— the provider has no such symbol. Search for it above rather than typing it."
                  : `— ${reason.split("\n")[0]}`}
              </p>
            ))}
          </section>
        )}
        {error && <p className="text-xs text-negative">{error}</p>}

        {added.length > 0 && (
          <section>
            <h3 className="text-[11px] font-medium uppercase tracking-wide text-text-muted">Added this session</h3>
            <ul className="mt-1 space-y-1">
              {added.map((entry) => (
                <li key={entry.ticker}>
                  <button type="button" onClick={() => { navigate(`/company/${entry.ticker}`); onClose(); }}
                    className="flex w-full items-baseline gap-2 rounded border border-border px-2 py-1.5 text-left hover:bg-surface-sunken">
                    <span className="tabular w-24 shrink-0 text-xs font-medium">{entry.ticker}</span>
                    <span className="min-w-0 flex-1 truncate text-xs text-text-muted">{entry.name}</span>
                    <span className="shrink-0 text-[10px] text-text-muted">open →</span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}

        <details className="rounded border border-border p-2">
          <summary className="cursor-pointer text-xs text-text-muted">Paste a list instead</summary>
          <BulkPaste onDone={(result) => {
            setAdded((current) => [...result.added, ...current]);
            setFailed(result.failed);
            client.invalidateQueries({ queryKey: ["universe"] });
            client.invalidateQueries({ queryKey: ["universe-health"] });
          }} />
        </details>

        <section>
          <h3 className="text-[11px] font-medium uppercase tracking-wide text-text-muted">Peer counts by sector</h3>
          <p className="mt-1 text-xs text-text-muted">
            Percentiles need 8 members. Below that a sector silently scores on absolute bands
            instead of ranks, so keep the universe broad — curation belongs in the watchlist.
          </p>
          {(health.data?.thin_sectors.length ?? 0) > 0 && (
            <p className="mt-1 rounded border border-warning/50 p-2 text-xs text-warning">
              {health.data?.thin_sectors.join(", ")} below 8 members.
            </p>
          )}
          <table className="mt-1 w-full text-xs">
            <tbody>
              {(health.data?.sectors ?? []).map((sector) => (
                <tr key={sector.sector} className="border-t border-border">
                  <td className="py-1">{sector.sector.replace(/_/g, " ")}</td>
                  <td className="tabular py-1 text-right">{sector.members}</td>
                  <td className="py-1 pl-2 text-right text-[10px]">
                    {sector.ranks_on_peers
                      ? <span className="text-text-muted">ranks</span>
                      : <span className="text-warning">bands only</span>}
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

function BulkPaste({ onDone }: { onDone: (r: { added: Added[]; failed: [string, string][] }) => void }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const tickers = text.split(/[\s,]+/).map((t) => t.trim()).filter(Boolean);

  return (
    <div className="mt-2">
      <textarea value={text} onChange={(e) => setText(e.target.value)} rows={3}
        placeholder="MU NVDA ASML.US VLX.LSE"
        className="tabular w-full rounded border border-border bg-surface-raised px-2 py-1 text-sm" />
      <p className="mt-1 text-[11px] text-text-muted">
        Exact tickers only — no lookup here. Non-US listings need their exchange suffix.
        Keep batches to 20 or so; the request runs synchronously.
      </p>
      <button type="button" disabled={busy || !tickers.length}
        onClick={async () => {
          setBusy(true);
          try {
            const result = await req<{ failed: Record<string, string> }>("/universe/securities",
              { method: "POST", body: JSON.stringify({ tickers }) });
            const failures = Object.entries(result.failed ?? {});
            const failedSet = new Set(failures.map(([t]) => t.split(".")[0]));
            onDone({
              added: tickers.map((t) => t.split(".")[0].toUpperCase())
                .filter((t) => !failedSet.has(t)).map((t) => ({ ticker: t, name: "" })),
              failed: failures,
            });
            setText("");
          } finally { setBusy(false); }
        }}
        className="mt-1 rounded border border-border px-3 py-1 text-xs disabled:opacity-40">
        {busy ? "adding…" : `Add ${tickers.length || ""}`.trim()}
      </button>
    </div>
  );
}
