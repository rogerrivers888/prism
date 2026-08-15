import { useEffect, useState, type ReactNode } from "react";

/** "What is this page for?" — on every screen, above everything else.
 *
 *  Two sentences on the screen's job and what to do first. Dismissible once
 *  read, and brought back by the ? button that replaces it, so the help is
 *  never gone for good but never nags either.
 */
export function PagePurpose({
  id,
  title,
  what,
  firstStep,
  children,
}: {
  id: string;
  title: string;
  /** What this screen is for, in one or two plain sentences. */
  what: string;
  /** The single thing to do first. */
  firstStep: string;
  children?: ReactNode;
}) {
  const key = `prism.purpose.${id}.dismissed`;
  const [dismissed, setDismissed] = useState(true);

  useEffect(() => {
    setDismissed(window.localStorage.getItem(key) === "1");
  }, [key]);

  const dismiss = () => {
    window.localStorage.setItem(key, "1");
    setDismissed(true);
  };
  const restore = () => {
    window.localStorage.removeItem(key);
    setDismissed(false);
  };

  if (dismissed) {
    return (
      <button
        type="button"
        onClick={restore}
        aria-label={`What is the ${title} page for?`}
        className="rounded-full border border-border px-2 py-0.5 text-xs text-text-muted hover:bg-surface-sunken"
      >
        ? What is this page for
      </button>
    );
  }

  return (
    <section className="rounded-md border border-border bg-surface-sunken p-4">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <h2 className="font-display text-base font-semibold">What is this page for?</h2>
          <p className="mt-1 text-sm leading-relaxed">{what}</p>
          <p className="mt-2 text-sm leading-relaxed">
            <span className="font-medium">Start by:</span> {firstStep}
          </p>
          {children}
        </div>
        <button
          type="button"
          onClick={dismiss}
          className="shrink-0 rounded px-2 py-0.5 text-xs text-text-muted hover:text-text"
        >
          Got it
        </button>
      </div>
    </section>
  );
}

/** An empty panel that says WHY it is empty and gives the button that fills it.
 *
 *  The distinction that matters: empty because nothing happened yet is a
 *  different message from empty because nothing matched. The first needs an
 *  action, the second needs a hint.
 */
export function NothingYet({
  headline,
  because,
  action,
}: {
  headline: string;
  because: string;
  action?: { label: string; onClick?: () => void; to?: string };
}) {
  return (
    <div className="rounded-md border border-dashed border-border p-5 text-center">
      <p className="font-display text-base font-semibold">{headline}</p>
      <p className="mx-auto mt-1 max-w-md text-sm text-text-muted">{because}</p>
      {action && (
        <div className="mt-3">
          {action.to ? (
            <a
              href={action.to}
              className="inline-block rounded border border-accent bg-accent px-3 py-1.5 text-sm font-medium text-surface"
            >
              {action.label}
            </a>
          ) : (
            <button
              type="button"
              onClick={action.onClick}
              className="rounded border border-accent bg-accent px-3 py-1.5 text-sm font-medium text-surface"
            >
              {action.label}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

/** A number and its meaning, together, permanently.
 *
 *  Not a tooltip. Roger asked for the translation beside the figure because a
 *  tooltip is a thing you have to know to hover over, and he did not.
 */
export function Figure({
  label,
  value,
  meaning,
  tone = "neutral",
}: {
  label: ReactNode;
  value: ReactNode;
  meaning: ReactNode;
  tone?: "neutral" | "warn" | "good";
}) {
  const edge =
    tone === "warn" ? "border-l-warning" : tone === "good" ? "border-l-accent" : "border-l-border";
  return (
    <div className={`border-l-2 ${edge} pl-3`}>
      <div className="text-[11px] font-medium uppercase tracking-wide text-text-muted">
        {label}
      </div>
      <div className="tabular mt-0.5 text-lg leading-tight">{value}</div>
      <p className="mt-0.5 text-xs leading-relaxed text-text-muted">{meaning}</p>
    </div>
  );
}
