/** Empty panels are the default state of a new install, so they explain what
 *  belongs there rather than showing nothing and looking broken. */
export function EmptyState({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-md border border-dashed border-border p-5">
      <h3 className="font-display text-lg font-semibold">{title}</h3>
      <div className="mt-1 space-y-1 text-sm text-text-muted">{children}</div>
    </div>
  );
}

export function SampleSize({ n, children }: { n: number; children: React.ReactNode }) {
  // Below n=30 a rate is noise. It is shown greyed with the count attached
  // rather than hidden, because hiding it invites recomputing it by hand.
  const thin = n < 30;
  return (
    <span
      className={thin ? "text-text-muted" : ""}
      title={thin ? `n=${n} — too few to mean anything; treat as anecdote` : `n=${n}`}
    >
      {children}
      <span className="tabular ml-1 text-[11px]">(n={n})</span>
    </span>
  );
}
