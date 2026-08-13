import { useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { useCompany, useMetricHistory, usePeers, type LensDetail } from "../api/company";
import { LENSES, LENS_BAR_CLASS, LENS_TEXT_CLASS, type LensName } from "../api/universe";
import { AskClaude } from "../components/AskClaude";
import { Drawer, DrawerStack } from "../components/Drawer";
import { useGlossary } from "../components/GlossaryProvider";
import { EarningsPanel } from "../components/EarningsPanel";
import { MetricChart } from "../components/MetricChart";

/** What a disagreement between two named lenses usually means.
 *
 * Deliberately descriptive, not prescriptive: it names the shape and the
 * question to ask, and stops short of saying what to do about it. */
function shapeOf(high: string, low: string): string {
  const pair = `${high}|${low}`;
  const shapes: Record<string, string> = {
    "value|quality":
      "Cheap but weak. The classic value trap shape: the price is low because the business is poor. The question is whether the weakness is temporary or terminal.",
    "quality|value":
      "Excellent but expensive. A good business at a demanding price. The question is whether the quality is durable enough to grow into the valuation.",
    "value|growth":
      "Cheap and shrinking. Often a business in structural decline where the low multiple is a warning rather than an opportunity.",
    "growth|value":
      "Growing fast and priced for it. The question is what happens to the multiple if growth slows even slightly.",
    "momentum|value":
      "The market likes it more than the fundamentals justify on price. Either the market knows something the accounts don't yet show, or it's running ahead of itself.",
    "value|momentum":
      "Cheap and unloved. Nothing has gone right recently, which is why it's cheap. The question is what would change that.",
    "cycle|value":
      "Favourable point in the cycle but not obviously cheap — much of the recovery may already be priced in.",
    "quality|cycle":
      "A good business at a poor point in its cycle. Often the more forgiving shape, since quality survives downturns.",
  };
  return (
    shapes[pair] ??
    `${high} is the strongest reading and ${low} the weakest. Those two lenses are measuring different things about the same company, and the gap is the question worth investigating.`
  );
}

export function Company() {
  const { ticker = "" } = useParams();
  const { data, isLoading, error } = useCompany(ticker);
  const { open: openTerm } = useGlossary();
  const [absolute, setAbsolute] = useState(false);
  const [openLens, setOpenLens] = useState<LensName | null>(null);
  const [askOpen, setAskOpen] = useState(false);
  const [chartMetrics, setChartMetrics] = useState<string[]>(["roic", "pe_ratio"]);
  const [range, setRange] = useState<"12M" | "5Y" | "MAX">("5Y");

  const peers = usePeers(ticker, openLens);
  const history = useMetricHistory(ticker, chartMetrics, range);

  const detail = useMemo(
    () => data?.lenses.find((l) => l.lens === openLens) ?? null,
    [data, openLens],
  );

  if (isLoading) return <div className="p-6 text-sm text-text-muted">Loading {ticker}…</div>;
  if (error || !data)
    return (
      <div className="p-6 text-negative" role="alert">
        Couldn't load {ticker}: {(error as Error)?.message ?? "not found"}
      </div>
    );

  const scoreOf = (lens: LensDetail) => (absolute ? lens.score_absolute : lens.score);

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-5xl px-4 py-4 sm:px-6">
        <header className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="font-display text-3xl font-semibold tracking-tight">
              {data.ticker}
            </h1>
            <p className="text-sm text-text-muted">{data.name}</p>
            {/* A just-added company has no stored row until the nightly run;
                the scores below were computed on the spot. */}
            {!data.stored && (
              <p className="mt-1 inline-block rounded border border-warning/50 px-2 py-0.5 text-[11px] text-warning">
                Scored just now, not yet stored — the nightly run at 02:00 UTC will
                persist these and add it to the daily job.
              </p>
            )}
            <p className="mt-1 text-xs text-text-muted">
              {data.sector.replace(/_/g, " ")}
              {data.subsector ? ` · ${data.subsector}` : ""} · {data.exchange}
              {data.quote_currency && data.quote_currency !== data.currency && (
                <>
                  {" · "}
                  <span className="text-warning" title="Quoted in a minor unit — 1/100 of the reporting currency">
                    quoted {data.quote_currency}, reports {data.currency}
                  </span>
                </>
              )}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <div className="flex overflow-hidden rounded-md border border-border">
              <button
                type="button"
                onClick={() => setAbsolute(false)}
                aria-pressed={!absolute}
                className={`px-3 py-1 text-xs ${!absolute ? "bg-surface-sunken font-medium" : "text-text-muted"}`}
              >
                Relative
              </button>
              <button
                type="button"
                onClick={() => setAbsolute(true)}
                aria-pressed={absolute}
                className={`px-3 py-1 text-xs ${absolute ? "bg-surface-sunken font-medium" : "text-text-muted"}`}
              >
                Absolute
              </button>
            </div>
            <button
              type="button"
              onClick={() => setAskOpen(true)}
              className="rounded-md border border-border px-3 py-1 text-xs hover:bg-surface-raised"
            >
              Ask Claude
            </button>
          </div>
        </header>

        {/* Lens ribbon — vertical bars, click to open the breakdown. */}
        <section className="mt-5">
          <div className="flex items-end gap-2 sm:gap-4">
            {LENSES.map((name) => {
              const lens = data.lenses.find((l) => l.lens === name);
              const score = lens ? scoreOf(lens) : null;
              const height = score === null ? 4 : Math.max(4, score);
              return (
                <button
                  key={name}
                  type="button"
                  onClick={() => setOpenLens(name)}
                  className="group flex flex-1 flex-col items-center gap-1"
                  aria-label={`${name} lens breakdown`}
                >
                  <span className="tabular text-xs">
                    {score === null ? (lens?.applicable === false ? "n/a" : "—") : score.toFixed(1)}
                  </span>
                  <span className="flex h-28 w-full items-end rounded-sm bg-surface-sunken">
                    <span
                      className={`w-full rounded-sm ${LENS_BAR_CLASS[name]}`}
                      style={{
                        height: `${height}%`,
                        opacity: score === null ? 0.18 : 0.32 + (score / 100) * 0.68,
                        filter: `saturate(${score === null ? 0.3 : 0.45 + (score / 100) * 0.75})`,
                      }}
                    />
                  </span>
                  <span className={`text-[11px] ${LENS_TEXT_CLASS[name]} group-hover:underline`}>
                    {name}
                  </span>
                </button>
              );
            })}
          </div>

          {/* Dispersion, with the shape spelled out in plain English. */}
          <div className="mt-4 rounded-md border border-border bg-surface-raised p-3">
            {data.dispersion === null ? (
              <p className="text-sm text-text-muted">
                No dispersion figure — only {data.usable_lenses ?? 0} lenses produced a
                score, and a gap between two readings is a coin toss rather than a
                disagreement.
              </p>
            ) : (
              <>
                <p className="text-sm">
                  <span className="tabular text-lg font-medium">
                    {data.dispersion.toFixed(1)}
                  </span>{" "}
                  points between{" "}
                  <span className={LENS_TEXT_CLASS[data.highest_lens as LensName]}>
                    {data.highest_lens}
                  </span>{" "}
                  and{" "}
                  <span className={LENS_TEXT_CLASS[data.lowest_lens as LensName]}>
                    {data.lowest_lens}
                  </span>
                  .
                </p>
                <p className="mt-1 text-sm text-text-muted">
                  {shapeOf(data.highest_lens ?? "", data.lowest_lens ?? "")}
                </p>
              </>
            )}
          </div>
        </section>

        {/* Relative vs absolute vs sector median, side by side. */}
        <section className="mt-5">
          <h2 className="font-display text-lg font-semibold">Relative and absolute</h2>
          <p className="text-xs text-text-muted">
            Peer percentiles are normalised inside a sector, so only the absolute
            reading can tell you the sector itself is stretched.
          </p>
          <div className="mt-2 overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-[11px] uppercase tracking-wide text-text-muted">
                <tr>
                  <th className="py-1 text-left font-medium">Lens</th>
                  <th className="py-1 text-right font-medium">Relative</th>
                  <th className="py-1 text-right font-medium">Absolute</th>
                  <th className="py-1 text-right font-medium">Premium</th>
                  <th className="py-1 text-right font-medium">Sector median</th>
                  <th className="py-1 text-right font-medium">Coverage</th>
                </tr>
              </thead>
              <tbody>
                {data.lenses.map((lens) => (
                  <tr key={lens.lens} className="border-t border-border">
                    <td className={`py-1 ${LENS_TEXT_CLASS[lens.lens as LensName]}`}>
                      {lens.lens}
                    </td>
                    <td className="tabular py-1 text-right">
                      {lens.score?.toFixed(1) ?? (lens.applicable ? "—" : "n/a")}
                    </td>
                    <td className="tabular py-1 text-right">
                      {lens.score_absolute?.toFixed(1) ?? "—"}
                    </td>
                    <td
                      className="tabular py-1 text-right"
                      title="Relative minus absolute. Large positive on value means cheap within an expensive sector."
                    >
                      {lens.relative_premium === null || lens.relative_premium === undefined
                        ? "—"
                        : `${lens.relative_premium > 0 ? "+" : ""}${lens.relative_premium.toFixed(1)}`}
                    </td>
                    <td className="tabular py-1 text-right text-text-muted">
                      {lens.sector_median?.toFixed(1) ?? "—"}
                    </td>
                    <td className="tabular py-1 text-right text-text-muted">
                      {Math.round(lens.coverage * 100)}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        {/* Metric chart */}
        <section className="mt-5">
          <h2 className="font-display text-lg font-semibold">Earnings</h2>
          <div className="mt-3">
            <EarningsPanel ticker={ticker!} />
          </div>
        </section>

        <section className="mt-6">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="font-display text-lg font-semibold">History</h2>
            <div className="flex gap-1">
              {(["12M", "5Y", "MAX"] as const).map((option) => (
                <button
                  key={option}
                  type="button"
                  onClick={() => setRange(option)}
                  aria-pressed={range === option}
                  className={`rounded border px-2 py-0.5 text-xs ${range === option ? "border-border-strong bg-surface-sunken" : "border-border text-text-muted"}`}
                >
                  {option}
                </button>
              ))}
            </div>
          </div>
          <div className="mt-2 flex flex-wrap gap-1">
            {["roic", "gross_profitability", "pe_ratio", "ev_ebitda", "fcf_yield", "revenue_growth_yoy", "days_inventory", "net_debt_to_ebitda"].map((metric) => {
              const on = chartMetrics.includes(metric);
              return (
                <button
                  key={metric}
                  type="button"
                  onClick={() =>
                    setChartMetrics((current) =>
                      current.includes(metric)
                        ? current.filter((m) => m !== metric)
                        : current.length >= 4
                          ? current
                          : [...current, metric],
                    )
                  }
                  aria-pressed={on}
                  className={`tabular rounded-full border px-2 py-0.5 text-[11px] ${on ? "border-border-strong bg-surface-sunken" : "border-border text-text-muted"}`}
                >
                  {metric}
                </button>
              );
            })}
            <span className="self-center text-[11px] text-text-muted">
              {chartMetrics.length}/4
            </span>
          </div>
          <div className="mt-3">
            {history.isLoading ? (
              <p className="text-sm text-text-muted">Rebuilding history…</p>
            ) : (
              <MetricChart series={history.data ?? []} />
            )}
          </div>
        </section>
      </div>

      <DrawerStack>
        {openLens && detail && (
          <Drawer
            title={`${openLens} lens`}
            subtitle={`${data.ticker} · ${Math.round(detail.coverage * 100)}% coverage`}
            onClose={() => setOpenLens(null)}
            width="w-[min(92vw,30rem)]"
          >
            <LensBreakdown
              detail={detail}
              absolute={absolute}
              onMetric={(metric, value) =>
                openTerm(metric, {
                  from: `the ${data.name} company page`,
                  valueLabel:
                    value === null || value === undefined
                      ? "no value for this company"
                      : `this company: ${value.toLocaleString(undefined, { maximumFractionDigits: 4 })}`,
                  detail: { ticker: data.ticker, metric, value },
                })
              }
              peers={peers.data ?? []}
              self={data.ticker}
            />
          </Drawer>
        )}
        {askOpen && (
          <AskClaude
            context={{
              screen: "company",
              ticker: data.ticker,
              name: data.name,
              sector: data.sector,
              as_of: data.as_of,
              dispersion: data.dispersion,
              highest_lens: data.highest_lens,
              lowest_lens: data.lowest_lens,
              lenses: data.lenses.map((l) => ({
                lens: l.lens,
                score: l.score,
                score_absolute: l.score_absolute,
                sector_median: l.sector_median,
                coverage: l.coverage,
                applicable: l.applicable,
                metrics: (l.inputs as { metrics?: unknown })?.metrics,
              })),
            }}
            onClose={() => setAskOpen(false)}
          />
        )}
      </DrawerStack>
    </div>
  );
}

function LensBreakdown({
  detail,
  absolute,
  onMetric,
  peers,
  self,
}: {
  detail: LensDetail;
  absolute: boolean;
  onMetric: (metric: string, value?: number | null) => void;
  peers: { ticker: string; name: string; is_self: boolean; score: number | null; metrics: Record<string, { value?: number | null }> }[];
  self: string;
}) {
  const inputs = detail.inputs as {
    declared?: string[];
    display_only?: string[];
    metrics?: Record<string, {
      value: number | null; score: number | null; score_absolute: number | null;
      method: string | null; peer_count: number | null; excluded: string | null;
    }>;
    flags?: string[];
    reason?: string;
  };
  const metrics = inputs.metrics ?? {};
  const names = [...(inputs.declared ?? []), ...(inputs.display_only ?? [])];

  if (!detail.applicable) {
    return (
      <p className="text-sm text-text-muted">
        This lens doesn't apply to this company's sector, so it reports nothing
        rather than a number. A cycle reading on a business without inventory or
        pricing cycles would be noise dressed as signal.
      </p>
    );
  }

  return (
    <div className="space-y-4">
      <table className="w-full text-sm">
        <thead className="text-[11px] uppercase tracking-wide text-text-muted">
          <tr>
            <th className="py-1 text-left font-medium">Metric</th>
            <th className="py-1 text-right font-medium">Value</th>
            <th className="py-1 text-right font-medium">Score</th>
            <th className="py-1 text-right font-medium">Method</th>
          </tr>
        </thead>
        <tbody>
          {names.map((name) => {
            const cell = metrics[name];
            const displayOnly = (inputs.display_only ?? []).includes(name);
            return (
              <tr key={name} className="border-t border-border align-top">
                <td className="py-1">
                  <button
                    type="button"
                    onClick={() => onMetric(name, cell?.value)}
                    className="tabular text-left underline decoration-dotted underline-offset-2 hover:text-text"
                  >
                    {name}
                  </button>
                  {displayOnly && (
                    <span className="ml-1 text-[10px] text-text-muted">display only</span>
                  )}
                  {cell?.excluded && (
                    <p className="text-[11px] text-warning">{cell.excluded.replace(/_/g, " ")}</p>
                  )}
                </td>
                <td className="py-1 text-right">
                  <button
                    type="button"
                    onClick={() => onMetric(name, cell?.value)}
                    className="tabular underline decoration-dotted underline-offset-2"
                  >
                    {cell?.value === null || cell?.value === undefined
                      ? "—"
                      : cell.value.toLocaleString(undefined, { maximumFractionDigits: 3 })}
                  </button>
                </td>
                <td className="tabular py-1 text-right">
                  {(() => {
                    const score = absolute ? cell?.score_absolute : cell?.score;
                    return score === null || score === undefined ? "—" : score.toFixed(1);
                  })()}
                </td>
                <td className="py-1 text-right text-[11px] text-text-muted">
                  {cell?.method === "peer_percentile"
                    ? `rank of ${cell.peer_count}`
                    : cell?.method === "absolute_bands"
                      ? `bands (${cell.peer_count} peers)`
                      : "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {(inputs.flags ?? []).length > 0 && (
        <div className="rounded-md border border-warning/50 p-2 text-xs text-warning">
          {inputs.flags?.map((flag) => (
            <p key={flag}>{flag.replace(/_/g, " ")}</p>
          ))}
        </div>
      )}

      <section>
        <h3 className="text-[11px] font-medium uppercase tracking-wide text-text-muted">
          What this lens is blind to
        </h3>
        <p className="mt-1 text-sm leading-relaxed">{BLIND_SPOTS[detail.lens]}</p>
      </section>

      {peers.length > 0 && (
        <section>
          <h3 className="text-[11px] font-medium uppercase tracking-wide text-text-muted">
            Sector peers on this lens
          </h3>
          <table className="mt-1 w-full text-xs">
            <tbody>
              {peers.slice(0, 15).map((peer) => (
                <tr
                  key={peer.ticker}
                  className={`border-t border-border ${peer.ticker === self ? "bg-surface-sunken font-medium" : ""}`}
                >
                  <td className="tabular py-1">{peer.ticker}</td>
                  <td className="truncate py-1 text-text-muted">{peer.name}</td>
                  <td className="tabular py-1 text-right">
                    {peer.score === null ? "—" : peer.score.toFixed(1)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}

const BLIND_SPOTS: Record<string, string> = {
  trend:
    "Everything about the business. It reads price against its own past and nothing else — a company can be in a perfect uptrend while the accounts deteriorate, and the trend will be the last thing to notice.",
  growth:
    "Whether growth is profitable or bought. It can't see that revenue was acquired rather than earned, or that margins fell to buy it. It also says nothing about durability.",
  quality:
    "Price. A superb business at any valuation scores identically. Quality also flatters companies at a cyclical peak, when returns on capital look structural but are temporary.",
  value:
    "Whether cheap is deserved. Every value trap in history screened well on these metrics right up until the earnings that supported them disappeared.",
  momentum:
    "Cause. It measures that the price moved, not why. It's also the fastest to reverse — the strongest twelve-month returns are frequently followed by the worst.",
  cycle:
    "The absolute level of anything. It reads direction and tightness in inventory and pricing, but a tightening cycle in a structurally declining industry is still a declining industry.",
};
