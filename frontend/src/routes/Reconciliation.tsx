import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { API_BASE_URL } from "../api/config";
import { useReconciliation } from "../api/ig";
import { useGlossary } from "../components/GlossaryProvider";
import { NothingYet, PagePurpose } from "../components/PagePurpose";
import { useRegisterScreen } from "../components/ScreenContext";

/** Reviewing what IG says against what Prism knows.
 *
 *  Nothing on this screen has been applied. That is deliberate: a wrong
 *  automatic merge attaches one trade's reasoning to another's fills, and
 *  there is no way to notice afterwards.
 */

const KIND_HEADING: Record<string, string> = {
  ig_only: "IG has these — Prism does not",
  matched: "These look like the same position in both",
  prism_only: "Prism has these — IG does not",
};

const KIND_EXPLANATION: Record<string, string> = {
  ig_only:
    "You hold these at IG but have never written down why. Importing one records it in Prism and asks you for your thesis — which is the whole point of keeping a decision log.",
  matched:
    "Prism thinks these are the same trade you already recorded. Accepting links the two records together; it does not merge them, so your reasoning and IG's fills both stay intact.",
  prism_only:
    "You recorded these by hand but IG does not report them. Either they were closed, or they are held somewhere other than IG. Prism will never delete them on its own.",
};

export default function Reconciliation() {
  const { data, isLoading, error } = useReconciliation();
  const queryClient = useQueryClient();
  const { prose } = useGlossary();
  const [busy, setBusy] = useState<number | null>(null);

  useRegisterScreen(
    "IG reconciliation review",
    { pending: data?.pending.length ?? 0, counts: data?.counts },
    [
      "What is this page asking me to decide?",
      "What happens if I accept one of these?",
      "Why does Prism not just import everything automatically?",
    ],
  );

  const resolve = async (id: number, accept: boolean) => {
    setBusy(id);
    try {
      await fetch(`${API_BASE_URL}/ig/reconciliation/${id}`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ accept }),
      });
      await queryClient.invalidateQueries({ queryKey: ["ig-reconciliation"] });
      await queryClient.invalidateQueries({ queryKey: ["ig-book"] });
    } finally {
      setBusy(null);
    }
  };

  const kinds = ["ig_only", "matched", "prism_only"] as const;

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-6">
      <header>
        <h1 className="font-display text-2xl uppercase tracking-wide">Reconciliation</h1>
        <div className="mt-3 max-w-3xl">
          <PagePurpose
            id="reconciliation"
            title="Reconciliation"
            what="Where IG's record of what you hold and Prism's record disagree. Nothing here has been applied — Prism will not merge or delete anything on its own, because a wrong automatic merge cannot be spotted afterwards."
            firstStep="looking at the first group: positions IG knows about that you have never written down. Importing one asks you for your thesis, which is the habit the whole app is built around."
          />
        </div>
      </header>

      {isLoading && <p className="text-sm text-text-muted">Loading…</p>}
      {error && <p className="text-sm text-negative">{(error as Error).message}</p>}

      {data && data.pending.length === 0 && (
        <NothingYet
          headline="Nothing to review"
          because="IG and Prism agree about everything they both know about — or the overnight sync has not run yet."
        />
      )}

      {data &&
        kinds.map((kind) => {
          const rows = data.pending.filter((row) => row.kind === kind);
          if (rows.length === 0) return null;
          return (
            <section key={kind}>
              <h2 className="font-display text-lg font-semibold">
                {KIND_HEADING[kind]}{" "}
                <span className="text-sm font-normal text-text-muted">({rows.length})</span>
              </h2>
              <p className="mt-1 max-w-2xl text-sm leading-relaxed text-text-muted">
                {prose(KIND_EXPLANATION[kind])}
              </p>
              <ul className="mt-2 divide-y divide-border border-y border-border">
                {rows.map((row) => {
                  const detail = row.detail as Record<string, unknown>;
                  const name =
                    (detail.instrument_name as string) ??
                    row.ticker ??
                    (detail.ticker as string) ??
                    row.epic ??
                    "unknown";
                  return (
                    <li key={row.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-3">
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium">{name}</p>
                        <p className="text-xs text-text-muted">
                          {String(detail.direction ?? "")} {String(detail.size ?? detail.ig_size ?? "")}
                          {detail.needs_mapping ? " · not linked to a company Prism tracks" : ""}
                          {row.confidence !== null && kind === "matched"
                            ? ` · ${Math.round(row.confidence * 100)}% sure these are the same`
                            : ""}
                        </p>
                        {typeof detail.reason === "string" && (
                          <p className="mt-0.5 text-xs text-text-muted">{detail.reason}</p>
                        )}
                      </div>
                      <div className="flex gap-2">
                        <button
                          type="button"
                          disabled={busy === row.id}
                          onClick={() => resolve(row.id, true)}
                          className="rounded border border-accent bg-accent px-3 py-1 text-xs font-medium text-surface disabled:opacity-40"
                        >
                          {kind === "matched" ? "Yes, same position" : "Import it"}
                        </button>
                        <button
                          type="button"
                          disabled={busy === row.id}
                          onClick={() => resolve(row.id, false)}
                          className="rounded border border-border px-3 py-1 text-xs disabled:opacity-40"
                        >
                          Not now
                        </button>
                      </div>
                    </li>
                  );
                })}
              </ul>
            </section>
          );
        })}

      {data && <p className="text-xs text-text-muted">{data.note}</p>}
    </div>
  );
}
