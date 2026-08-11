/** Scores are computed nightly. If the last run did not happen, the numbers
 *  on screen are yesterday's while looking exactly like today's — so say so
 *  rather than letting a reader assume they are current. */
export function StalenessBanner({
  asOf,
  staleDays,
}: {
  asOf: string | null;
  staleDays: number | null;
}) {
  if (!asOf) {
    return (
      <p className="mt-1 text-xs text-warning" role="status">
        No scores have been computed yet.
      </p>
    );
  }

  const stale = staleDays !== null && staleDays >= 1;
  return (
    <p
      className={`mt-1 text-xs ${stale ? "text-warning" : "text-text-muted"}`}
      role="status"
    >
      Scored {asOf}
      {staleDays === null
        ? " · age unknown"
        : stale
          ? ` · ${staleDays} day${staleDays === 1 ? "" : "s"} old — the nightly run may not have completed`
          : " · current"}
    </p>
  );
}
