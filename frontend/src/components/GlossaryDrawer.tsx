import { useEffect, useState } from "react";
import { useSaveNote, type GlossaryTerm } from "../api/glossary";
import { useGlossary } from "./GlossaryProvider";
import { AskClaude } from "./AskClaude";
import { Drawer, DrawerStack } from "./Drawer";

const SOURCE_LABEL: Record<string, string> = {
  reference: "reference",
  paper: "original paper",
};

function Section({ heading, body }: { heading: string; body: string | null }) {
  const { prose } = useGlossary();
  if (!body) return null;
  return (
    <section>
      <h3 className="text-[11px] font-medium uppercase tracking-wide text-text-muted">
        {heading}
      </h3>
      {body.split("\n\n").map((paragraph, index) => (
        <p key={index} className="mt-1 text-sm leading-relaxed">
          {/* Definitions link onward to other definitions. */}
          {prose(paragraph)}
        </p>
      ))}
    </section>
  );
}

function PersonalNote({ term }: { term: GlossaryTerm }) {
  const [draft, setDraft] = useState(term.user_note ?? "");
  const [editing, setEditing] = useState(false);
  const save = useSaveNote();

  useEffect(() => {
    setDraft(term.user_note ?? "");
    setEditing(false);
  }, [term.slug, term.user_note]);

  return (
    <section className="rounded border border-border bg-surface-sunken p-3">
      <h3 className="text-[11px] font-medium uppercase tracking-wide text-text-muted">
        Your note
      </h3>
      {editing ? (
        <>
          <textarea
            value={draft}
            autoFocus
            rows={4}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="What this means to you, in your words."
            className="mt-2 w-full rounded border border-border bg-surface px-2 py-1 text-sm"
          />
          <div className="mt-2 flex gap-2">
            <button
              type="button"
              disabled={save.isPending}
              onClick={() =>
                save.mutate(
                  { slug: term.slug, note: draft },
                  { onSuccess: () => setEditing(false) },
                )
              }
              className="rounded border border-accent bg-accent px-3 py-1 text-xs text-surface disabled:opacity-40"
            >
              {save.isPending ? "Saving…" : "Save"}
            </button>
            <button
              type="button"
              onClick={() => {
                setDraft(term.user_note ?? "");
                setEditing(false);
              }}
              className="rounded border border-border px-3 py-1 text-xs"
            >
              Cancel
            </button>
          </div>
          {save.error && <p className="mt-1 text-xs text-warn">{save.error.message}</p>}
        </>
      ) : term.user_note ? (
        <>
          <p className="mt-1 whitespace-pre-wrap text-sm leading-relaxed">{term.user_note}</p>
          <button
            type="button"
            onClick={() => setEditing(true)}
            className="mt-2 text-xs text-text-muted underline"
          >
            Edit
          </button>
        </>
      ) : (
        <button
          type="button"
          onClick={() => setEditing(true)}
          className="mt-1 text-sm text-text-muted underline"
        >
          Add your own note
        </button>
      )}
    </section>
  );
}

export function GlossaryDrawer({
  term,
  context,
  onClose,
}: {
  term: GlossaryTerm;
  context?: { from?: string; detail?: unknown; valueLabel?: string };
  onClose: () => void;
}) {
  const { terms, open } = useGlossary();
  const [asking, setAsking] = useState(false);

  // Reset the conversation when the drawer moves to a different term, so an
  // answer about P/E doesn't linger under a heading about drawdown.
  useEffect(() => setAsking(false), [term.slug]);

  const related = term.related_slugs
    .map((slug) => terms.find((t) => t.slug === slug))
    .filter((t): t is GlossaryTerm => Boolean(t));

  return (
    <DrawerStack>
      <Drawer
        title={term.term}
        subtitle={context?.valueLabel ?? term.short_definition}
        onClose={onClose}
      >
        <div className="space-y-4">
          {context?.valueLabel && (
            <p className="text-sm text-text-muted">{term.short_definition}</p>
          )}
          <Section heading="What it is" body={term.full_explanation} />
          <Section heading="Worked example" body={term.worked_example} />
          <Section heading="How to read it" body={term.how_to_read_it} />
          <Section heading="Where it misleads" body={term.common_mistakes} />

          <PersonalNote term={term} />

          {related.length > 0 && (
            <section>
              <h3 className="text-[11px] font-medium uppercase tracking-wide text-text-muted">
                Related
              </h3>
              <div className="mt-1 flex flex-wrap gap-1.5">
                {related.map((entry) => (
                  <button
                    key={entry.slug}
                    type="button"
                    onClick={() => open(entry.slug, context)}
                    className="rounded border border-border px-2 py-0.5 text-xs hover:bg-surface-sunken"
                  >
                    {entry.term}
                  </button>
                ))}
              </div>
            </section>
          )}

          {term.external_links.length > 0 && (
            <section>
              <h3 className="text-[11px] font-medium uppercase tracking-wide text-text-muted">
                Elsewhere
              </h3>
              {/* Several sources on purpose: they explain differently, and the
                  one that lands is not the same for every reader. */}
              <ul className="mt-1 space-y-1">
                {term.external_links.map((link) => (
                  <li key={link.url}>
                    <a
                      href={link.url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-sm underline underline-offset-2"
                    >
                      {link.label}
                    </a>
                    <span className="ml-1 text-[10px] text-text-muted">
                      {SOURCE_LABEL[link.source_type] ?? link.source_type}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <button
            type="button"
            onClick={() => setAsking(true)}
            className="w-full rounded border border-border px-3 py-2 text-sm hover:bg-surface-sunken"
          >
            Ask Claude about this
          </button>
        </div>
      </Drawer>

      {asking && (
        <AskClaude
          // Seeded with the term AND where it was clicked from, so asking
          // about expectancy from a backtest result knows which result.
          context={{
            asking_about: { term: term.term, definition: term.short_definition },
            clicked_from: context?.from,
            on_screen: context?.detail,
          }}
          onClose={() => setAsking(false)}
        />
      )}
    </DrawerStack>
  );
}
