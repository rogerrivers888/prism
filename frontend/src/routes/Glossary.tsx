import { useMemo, useState } from "react";
import { CATEGORY_LABEL, useGlossaryTerms } from "../api/glossary";
import { useGlossary } from "../components/GlossaryProvider";

const ORDER = [
  "platform",
  "lens",
  "backtest",
  "value",
  "quality",
  "growth",
  "trend",
  "momentum",
  "cycle",
  "context",
];

export default function Glossary() {
  const { data, isLoading, error } = useGlossaryTerms();
  const { open } = useGlossary();
  const [query, setQuery] = useState("");

  const grouped = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const matching = (data ?? []).filter((term) => {
      if (!needle) return true;
      // Searching aliases too, so looking up "P/E" finds it even though the
      // entry is titled "P/E ratio", and "bps" finds "Basis point".
      return (
        term.term.toLowerCase().includes(needle) ||
        term.short_definition.toLowerCase().includes(needle) ||
        term.aliases.some((alias) => alias.toLowerCase().includes(needle))
      );
    });
    const buckets = new Map<string, typeof matching>();
    for (const term of matching) {
      const list = buckets.get(term.category) ?? [];
      list.push(term);
      buckets.set(term.category, list);
    }
    return ORDER.filter((c) => buckets.has(c)).map((c) => [c, buckets.get(c)!] as const);
  }, [data, query]);

  const total = data?.length ?? 0;
  const shown = grouped.reduce((sum, [, list]) => sum + list.length, 0);

  return (
    <div className="mx-auto max-w-4xl p-6">
      <header>
        <h1 className="font-display text-2xl uppercase tracking-wide">Glossary</h1>
        <p className="mt-1 max-w-2xl text-sm text-text-muted">
          Every term Prism uses, in plain English. Any of these will also be clickable
          wherever it appears elsewhere in the app.
        </p>
      </header>

      <input
        type="search"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder="Search terms, definitions and abbreviations…"
        aria-label="Search the glossary"
        className="mt-4 w-full rounded border border-border bg-surface-raised px-3 py-2 text-sm"
      />
      <p className="mt-1 text-xs text-text-muted">
        {isLoading ? "Loading…" : `${shown} of ${total} terms`}
      </p>
      {error && <p className="mt-2 text-sm text-warn">{(error as Error).message}</p>}

      {!isLoading && shown === 0 && (
        <p className="mt-6 text-sm text-text-muted">
          Nothing matches “{query}”. Try a shorter word, or the abbreviation.
        </p>
      )}

      <div className="mt-6 space-y-8">
        {grouped.map(([category, list]) => (
          <section key={category}>
            <h2 className="font-display text-lg font-semibold">
              {CATEGORY_LABEL[category] ?? category}
            </h2>
            <ul className="mt-2 divide-y divide-border border-y border-border">
              {list.map((term) => (
                <li key={term.slug}>
                  <button
                    type="button"
                    onClick={() => open(term.slug, { from: "the glossary" })}
                    className="w-full px-1 py-2 text-left hover:bg-surface-sunken"
                  >
                    <span className="text-sm font-medium">{term.term}</span>
                    {term.user_note && (
                      <span className="ml-2 text-[10px] uppercase tracking-wide text-text-muted">
                        your note
                      </span>
                    )}
                    <span className="mt-0.5 block text-sm text-text-muted">
                      {term.short_definition}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </div>
  );
}
