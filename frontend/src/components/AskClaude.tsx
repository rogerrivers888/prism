import { useState } from "react";
import { API_BASE_URL } from "../api/config";
import { Drawer } from "./Drawer";

type Turn = { role: "user" | "assistant"; content: string; refused?: boolean };

/** The second drawer, opening beside the first rather than over it.
 *
 * It explains and stress-tests; it does not recommend. That boundary is
 * enforced server-side in the system prompt and stated here so the user knows
 * what they're talking to. */
export function AskClaude({
  context,
  onClose,
}: {
  context: unknown;
  onClose: () => void;
}) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const send = async () => {
    const question = draft.trim();
    if (!question || busy) return;
    const next = [...turns, { role: "user" as const, content: question }];
    setTurns(next);
    setDraft("");
    setBusy(true);
    setError(null);

    try {
      const response = await fetch(`${API_BASE_URL}/assistant`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          messages: next.map((t) => ({ role: t.role, content: t.content })),
          context,
        }),
      });
      if (response.status === 503) {
        setError(
          "Ask Claude isn't configured — ANTHROPIC_API_KEY isn't set on the API service.",
        );
        return;
      }
      if (!response.ok) throw new Error(`assistant returned ${response.status}`);
      const data = await response.json();
      setTurns([
        ...next,
        { role: "assistant", content: data.reply, refused: data.refused },
      ]);
    } catch (exc) {
      setError((exc as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Drawer title="Ask Claude" subtitle="explains and stress-tests — never recommends" onClose={onClose}>
      <div className="flex h-full flex-col">
        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto">
          {turns.length === 0 && (
            <div className="rounded-md border border-border bg-surface p-3 text-sm text-text-muted">
              <p>Ask about anything on screen. It can see the numbers you can.</p>
              <p className="mt-2">
                It won't tell you whether to buy or sell — it's here to explain a
                figure, argue the other side of your thesis, and say what a lens
                is blind to.
              </p>
              <ul className="mt-2 list-disc pl-4">
                <li>"Why is the value lens so much higher than absolute?"</li>
                <li>"What's the strongest argument against this being cheap?"</li>
                <li>"What is this lens missing?"</li>
              </ul>
            </div>
          )}
          {turns.map((turn, index) => (
            <div
              key={index}
              className={
                turn.role === "user"
                  ? "ml-6 rounded-md bg-surface-sunken px-3 py-2 text-sm"
                  : "rounded-md border border-border px-3 py-2 text-sm"
              }
            >
              {turn.refused && (
                <p className="mb-1 text-[11px] uppercase tracking-wide text-warning">
                  declined
                </p>
              )}
              <p className="whitespace-pre-wrap leading-relaxed">{turn.content}</p>
            </div>
          ))}
          {busy && <p className="text-sm text-text-muted">thinking…</p>}
          {error && (
            <p className="rounded-md border border-negative px-3 py-2 text-sm text-negative">
              {error}
            </p>
          )}
        </div>

        <form
          className="mt-3 flex gap-2 border-t border-border pt-3"
          onSubmit={(event) => {
            event.preventDefault();
            void send();
          }}
        >
          <input
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="Ask about what's on screen"
            aria-label="Ask Claude a question"
            className="h-9 flex-1 rounded-md border border-border bg-surface px-2 text-sm"
          />
          <button
            type="submit"
            disabled={busy || !draft.trim()}
            className="rounded-md border border-border px-3 text-sm disabled:opacity-40"
          >
            Ask
          </button>
        </form>
      </div>
    </Drawer>
  );
}
