import { useEarnings } from "../api/backtest";

/** Next report plus the last eight actuals.
 *
 *  A future date is a forecast that moves, so it is labelled as one. The table
 *  behind it is the record of how the forecast has historically related to the
 *  outcome, which is the only thing that makes the countdown meaningful. */
export function EarningsPanel({ ticker }: { ticker: string }) {
  const { data, isLoading, error } = useEarnings(ticker);

  if (isLoading) return <p className="text-sm text-text-muted">Loading earnings…</p>;
  if (error || !data) {
    return <p className="text-sm text-text-muted">No earnings dates on file for {ticker}.</p>;
  }

  const surpriseTone = (value: number | null) => {
    if (value === null) return "text-text-muted";
    // Neutral typography, not green/red: a beat is not automatically good and
    // the colour system reserves hue for lens identity.
    return "text-text";
  };

  return (
    <div className="space-y-4">
      <div className="flex items-baseline gap-4">
        {data.next_report_date ? (
          <>
            <div>
              <div className="font-mono text-[10px] uppercase tracking-wider text-text-muted">
                Next report
              </div>
              <div className="tabular text-lg">{data.next_report_date}</div>
            </div>
            <div>
              <div className="font-mono text-[10px] uppercase tracking-wider text-text-muted">
                Days
              </div>
              <div className="tabular text-lg">{data.days_to_earnings}</div>
            </div>
            {data.next_is_estimated ? (
              <span className="text-xs text-text-muted">
                Estimated date — it has not been confirmed and will move.
              </span>
            ) : (
              <span className="text-xs text-text-muted">Confirmed date.</span>
            )}
          </>
        ) : (
          <p className="text-sm text-text-muted">
            No future report date on file. That means we have not observed one, not that none is
            scheduled.
          </p>
        )}
      </div>

      {data.history.length ? (
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-border text-left font-mono text-[10px] uppercase tracking-wider text-text-muted">
              <th className="py-1">Period</th>
              <th className="py-1">Reported</th>
              <th className="py-1 text-right">Est</th>
              <th className="py-1 text-right">Actual</th>
              <th className="py-1 text-right">Surprise</th>
            </tr>
          </thead>
          <tbody>
            {data.history.map((row) => (
              <tr key={row.period_end} className="border-b border-border/50">
                <td className="py-1 tabular">{row.period_end}</td>
                <td className="py-1 tabular text-text-muted">{row.report_date ?? "—"}</td>
                <td className="py-1 text-right tabular text-text-muted">
                  {row.eps_estimate === null ? "—" : row.eps_estimate.toFixed(2)}
                </td>
                <td className="py-1 text-right tabular">
                  {row.eps_actual === null ? "—" : row.eps_actual.toFixed(2)}
                </td>
                <td className={`py-1 text-right tabular ${surpriseTone(row.surprise_percent)}`}>
                  {row.surprise_percent === null
                    ? "—"
                    : `${row.surprise_percent >= 0 ? "+" : ""}${row.surprise_percent.toFixed(1)}%`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </div>
  );
}
