import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { useGlossaryTerms, type GlossaryTerm } from "../api/glossary";
import { buildMatcher, linkify, type Matcher } from "../lib/autolink";
import { GlossaryDrawer } from "./GlossaryDrawer";

type OpenContext = {
  from?: string;
  detail?: unknown;
  /** The value on screen for this term, e.g. "this company: 12.4". */
  valueLabel?: string;
};

type GlossaryValue = {
  terms: GlossaryTerm[];
  matcher: Matcher | null;
  open: (slug: string, context?: OpenContext) => void;
  /** Linkify a passage. Pass a shared `seen` set to make "first mention only"
   *  span several passages, e.g. a whole conversation. */
  prose: (text: string, seen?: Set<string>) => ReactNode;
};

const Context = createContext<GlossaryValue | null>(null);

export function useGlossary(): GlossaryValue {
  const value = useContext(Context);
  if (!value) throw new Error("useGlossary used outside GlossaryProvider");
  return value;
}

/** Holds the glossary and owns the drawers.
 *
 * Central so that any linked term anywhere opens the same drawer without every
 * screen having to wire one up — which is what makes auto-linking usable in
 * prose the screens don't own, like Claude's replies.
 */
export function GlossaryProvider({ children }: { children: ReactNode }) {
  const { data } = useGlossaryTerms();
  const terms = useMemo(() => data ?? [], [data]);
  const matcher = useMemo(() => (terms.length ? buildMatcher(terms) : null), [terms]);

  const [openSlug, setOpenSlug] = useState<string | null>(null);
  const [openContext, setOpenContext] = useState<OpenContext>({});

  const open = useCallback((slug: string, context: OpenContext = {}) => {
    setOpenSlug(slug);
    setOpenContext(context);
  }, []);

  const prose = useCallback(
    (text: string, seen?: Set<string>) =>
      linkify(text, matcher, open, { alreadyLinked: seen }),
    [matcher, open],
  );

  const value = useMemo(
    () => ({ terms, matcher, open, prose }),
    [terms, matcher, open, prose],
  );

  const term = openSlug ? terms.find((t) => t.slug === openSlug) ?? null : null;

  return (
    <Context.Provider value={value}>
      {children}
      {term && (
        <GlossaryDrawer
          term={term}
          context={openContext}
          onClose={() => setOpenSlug(null)}
        />
      )}
    </Context.Provider>
  );
}
