import type { ReactNode } from "react";
import type { GlossaryTerm } from "../api/glossary";

/** Auto-linking glossary terms in prose Claude and the backtest produce.
 *
 * Deliberately done here rather than by asking Claude to mark up its own
 * output. A model asked to tag its own jargon is inconsistent between
 * responses and invents terms that aren't in the glossary; matching against a
 * known list cannot do either.
 */

// Single and double-character aliases are dropped from matching. "R" as an
// alias for R-multiple would match the letter R anywhere in a sentence, and
// the display entry still keeps it — this only governs what gets linked.
const MIN_MATCH_LENGTH = 3;

export type Matcher = {
  pattern: RegExp;
  slugFor: Map<string, string>;
};

function escapeRegex(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function buildMatcher(terms: GlossaryTerm[]): Matcher | null {
  const slugFor = new Map<string, string>();
  for (const entry of terms) {
    for (const phrase of [entry.term, ...entry.aliases]) {
      const key = phrase.toLowerCase();
      if (phrase.length < MIN_MATCH_LENGTH) continue;
      // First writer wins, so a term's own name beats another term's alias.
      if (!slugFor.has(key)) slugFor.set(key, entry.slug);
    }
  }
  if (slugFor.size === 0) return null;

  // Longest first, so "free cash flow yield" is matched before "free cash
  // flow". Regex alternation is ordered, so this ordering *is* the rule.
  const phrases = [...slugFor.keys()].sort((a, b) => b.length - a.length);

  // Custom boundaries rather than \b: terms contain "/" and "-" ("P/E",
  // "book-to-bill"), and \b treats those as boundaries in the wrong places.
  // Also stops a match starting or ending inside a number.
  const pattern = new RegExp(
    `(?<![\\p{L}\\p{N}])(${phrases.map(escapeRegex).join("|")})(?![\\p{L}\\p{N}])`,
    "giu",
  );
  return { pattern, slugFor };
}

// Fenced blocks and inline spans. Anything inside is left exactly as written:
// linking a term inside code would corrupt something meant to be copied.
const CODE = /(```[\s\S]*?```|`[^`\n]*`)/g;

export function linkify(
  text: string,
  matcher: Matcher | null,
  onOpen: (slug: string) => void,
  options: { alreadyLinked?: Set<string> } = {},
): ReactNode {
  if (!matcher || !text) return text;

  // Shared across the whole passage so a term links on first mention only.
  const linked = options.alreadyLinked ?? new Set<string>();
  const out: ReactNode[] = [];
  let key = 0;

  for (const chunk of text.split(CODE)) {
    if (!chunk) continue;
    if (chunk.startsWith("`")) {
      out.push(<span key={key++}>{chunk}</span>);
      continue;
    }

    let cursor = 0;
    matcher.pattern.lastIndex = 0;
    let match: RegExpExecArray | null;
    while ((match = matcher.pattern.exec(chunk)) !== null) {
      const slug = matcher.slugFor.get(match[1].toLowerCase());
      if (!slug || linked.has(slug)) continue;
      linked.add(slug);

      if (match.index > cursor) out.push(chunk.slice(cursor, match.index));
      out.push(
        <button
          key={key++}
          type="button"
          onClick={() => onOpen(slug)}
          title={`What does "${match![1]}" mean?`}
          className="cursor-pointer border-b border-dotted border-current text-inherit underline-offset-2 hover:border-solid focus:outline-none focus-visible:ring-1 focus-visible:ring-current"
        >
          {/* Original casing preserved: matching is case-insensitive, display is not. */}
          {match[1]}
        </button>,
      );
      cursor = match.index + match[1].length;
    }
    if (cursor < chunk.length) out.push(chunk.slice(cursor));
  }

  return out;
}
