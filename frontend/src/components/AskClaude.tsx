import { useEffect, useMemo, useState } from "react";
import { API_BASE_URL } from "../api/config";
import { Drawer } from "./Drawer";
import { useGlossary } from "./GlossaryProvider";

type Turn = { role: "user" | "assistant"; content: string; refused?: boolean };

/** The second drawer, opening beside the first rather than over it.
 *
 * It explains and stress-tests; it does not recommend. That boundary is
 * enforced server-side in the system prompt and stated here so the user knows
 * what they're talking to. */
export function AskClaude({
  context,
  onClose,
  suggestions,
  seedPrompt,
}: {
  context: unknown;
  onClose: () => void;
  /** One-click starting questions, so a blank box is never the first thing
   *  someone who doesn't know what to ask has to face. */
  suggestions?: string[];
  /** Opens with this question already asked. */
  seedPrompt?: string;
}) {
  const { prose } = useGlossary();
  // One set for the whole conversation, so a term links on its first mention
  // and is left alone in every later reply rather than lighting up repeatedly.
  const linkedSoFar = useMemo(() => new Set<string>(), []);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [seeded, setSeeded] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const send = async (override?: string) => {
    const question = (override ?? draft).trim();
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

  useEffect(() => {
    // A seeded question is asked once, on open, so a "Explain this to me"
    // button lands on an answer rather than a blank box.
    if (seedPrompt && !seeded) {
      setSeeded(true);
      void send(seedPrompt);
    }
  }, [seedPrompt, seeded]);

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
              <div className="mt-3 space-y-1.5">
                {(suggestions ?? [
                  "Why is the value lens so much higher than absolute?",
                  "What's the strongest argument against this being cheap?",
                  "What is this lens missing?",
                ]).map((prompt) => (
                  <button
                    key={prompt}
                    type="button"
                    onClick={() => void send(prompt)}
                    className="block w-full rounded border border-border px-2 py-1.5 text-left text-sm text-text hover:bg-surface-sunken"
                  >
                    {prompt}
                  </button>
                ))}
              </div>
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
              <p className="whitespace-pre-wrap leading-relaxed">
                {turn.role === "assistant" ? prose(turn.content, linkedSoFar) : turn.content}
              </p>
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
