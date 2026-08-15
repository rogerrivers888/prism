import { useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useVirtualizer } from "@tanstack/react-virtual";
import { API_BASE_URL, API_BASE_URL_IS_DEFAULT } from "../api/config";
import { LENSES, useUniverse, type LensName } from "../api/universe";
import { LensBar, LensStrip } from "../components/LensBar";
import { DispersionCell } from "../components/Dispersion";
import { DrawerStack } from "../components/Drawer";
import { UniverseAdmin, useUniverseHealth } from "../components/UniverseAdmin";
import { AskClaude } from "../components/AskClaude";
import { PagePurpose } from "../components/PagePurpose";
import { useRegisterScreen } from "../components/ScreenContext";
import { StalenessBanner } from "../components/StalenessBanner";
import {
  filterRows,
  flatten,
  groupRows,
  sectorsOf,
  sortRows,
  type GroupKey,
  type SortKey,
} from "../lib/universe-view";

const ROW_HEIGHT = 44;
const HEADER_HEIGHT = 32;

export function Universe() {
  const navigate = useNavigate();
  const { data, isLoading, error } = useUniverse();

  // Dispersion descending by default: where the methodologies disagree is
  // the research question, so it leads.
  const [sortKey, setSortKey] = useState<SortKey>("dispersion");
  // Off by default: it is useful when hunting a catalyst and pure clutter
  // the rest of the time.
  const [showEarnings, setShowEarnings] = useState(false);
  const [descending, setDescending] = useState(true);
  const [absolute, setAbsolute] = useState(false);
  const [group, setGroup] = useState<GroupKey>("none");
  const [sectors, setSectors] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState("");
  const [adminOpen, setAdminOpen] = useState(false);
  const [askOpen, setAskOpen] = useState(false);

  const health = useUniverseHealth();

  const rows = data?.rows ?? [];
  const allSectors = useMemo(() => sectorsOf(rows), [rows]);

  const items = useMemo(() => {
    const filtered = filterRows(rows, sectors, search);
    const sorted = sortRows(filtered, sortKey, descending, absolute);
    return flatten(groupRows(sorted, group));
  }, [rows, sectors, search, sortKey, descending, absolute, group]);

  const scrollRef = useRef<HTMLDivElement>(null);
  const virtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: (index) =>
      items[index]?.kind === "header" ? HEADER_HEIGHT : ROW_HEIGHT,
    overscan: 12,
  });

  useRegisterScreen(
    "Universe",
    {
      companies: rows.length,
      showing: items.filter((i) => i.kind === "row").length,
      sorted_by: sortKey,
      scores_shown: absolute ? "absolute" : "relative to industry",
      as_of: data?.as_of,
    },
    [
      "What am I looking at on this page?",
      "What does 'disagreement' mean and why is it the default sort?",
      "What is the difference between the relative and absolute scores?",
    ],
  );

  const toggleSort = (key: SortKey) => {
    if (key === sortKey) setDescending((value) => !value);
    else {
      setSortKey(key);
      setDescending(key !== "ticker");
    }
  };

  const toggleSector = (sector: string) => {
    setSectors((current) => {
      const next = new Set(current);
      if (next.has(sector)) next.delete(sector);
      else next.add(sector);
      return next;
    });
  };

  if (error) {
    // Name the URL that failed. Without it, a build pointed at the wrong
    // backend looks identical to a backend that is down.
    return (
      <div className="p-6" role="alert">
        <p className="text-negative">
          Could not load the universe: {(error as Error).message}
        </p>
        <p className="mt-2 text-sm text-text-muted">
          Tried <code className="tabular">{API_BASE_URL}</code>
          {API_BASE_URL_IS_DEFAULT
            ? " (the built-in default — VITE_API_BASE_URL was not set at build time)"
            : " (from VITE_API_BASE_URL)"}
        </p>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-border px-4 py-3 sm:px-6">
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
          <h1 className="font-display text-3xl font-semibold tracking-tight">
            Universe
          </h1>
          <p className="text-sm text-text-muted">
            {isLoading
              ? "loading…"
              : `showing ${items.filter((i) => i.kind === "row").length} of ${rows.length} companies`}
          </p>
        </div>

        <div className="mt-2 max-w-3xl">
        <PagePurpose
          id="universe"
          title="Universe"
          what="Every company Prism tracks, each scored six different ways — how cheap it is, how fast it is growing, how good the business is, how the share price is behaving, and so on. Each score runs 0 to 100 and compares the company with others in its own industry."
          firstStep="clicking any company to investigate it. Or sort by 'Disagreement' — that finds companies where the six views contradict each other, which is usually where something interesting is going on."
        />
        </div>

        {data && <StalenessBanner asOf={data.as_of} staleDays={data.stale_days} />}

        <div className="mt-1 flex flex-wrap items-center gap-2 text-xs">
          <button type="button" onClick={() => setAdminOpen(true)}
            className="rounded border border-border px-2 py-0.5 text-text-muted hover:text-text">
            Manage universe
          </button>
          <button type="button" onClick={() => setAskOpen(true)}
            className="rounded border border-border px-2 py-0.5 text-text-muted hover:text-text">
            Ask Claude
          </button>
          {(health.data?.thin_sectors.length ?? 0) > 0 && (
            <button type="button" onClick={() => setAdminOpen(true)} className="text-warning underline">
              {health.data?.thin_sectors.length} sector
              {health.data?.thin_sectors.length === 1 ? "" : "s"} below 8 peers — scoring on bands
            </button>
          )}
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <input
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search ticker or name"
            aria-label="Search ticker or name"
            className="h-8 min-w-44 flex-1 rounded-md border border-border bg-surface-raised px-2 text-sm placeholder:text-text-muted sm:flex-none"
          />

          {/* The toggle that matters: percentiles are normalised inside a
              sector, so only the absolute reading carries cross-sector
              information. */}
          <div className="flex overflow-hidden rounded-md border border-border">
            <button
              type="button"
              onClick={() => setAbsolute(false)}
              aria-pressed={!absolute}
              className={`px-3 py-1 text-xs ${!absolute ? "bg-surface-sunken font-medium text-text" : "text-text-muted"}`}
            >
              Relative
            </button>
            <button
              type="button"
              onClick={() => setAbsolute(true)}
              aria-pressed={absolute}
              className={`px-3 py-1 text-xs ${absolute ? "bg-surface-sunken font-medium text-text" : "text-text-muted"}`}
            >
              Absolute
            </button>
          </div>

          <label className="flex items-center gap-1 text-xs text-text-muted">
            <input
              type="checkbox"
              checked={showEarnings}
              onChange={(event) => setShowEarnings(event.target.checked)}
            />
            Earnings
          </label>

          <label className="flex items-center gap-1 text-xs text-text-muted">
            Group
            <select
              value={group}
              onChange={(event) => setGroup(event.target.value as GroupKey)}
              aria-label="Group by"
              className="h-8 rounded-md border border-border bg-surface-raised px-2 text-xs text-text"
            >
              <option value="none">None</option>
              <option value="sector">Sector</option>
              <option value="size">Size</option>
            </select>
          </label>
        </div>

        <div className="mt-2 flex flex-wrap gap-1">
          {allSectors.map((sector) => (
            <button
              key={sector}
              type="button"
              onClick={() => toggleSector(sector)}
              aria-pressed={sectors.has(sector)}
              className={`rounded-full border px-2 py-0.5 text-[11px] ${
                sectors.has(sector)
                  ? "border-border-strong bg-surface-sunken text-text"
                  : "border-border text-text-muted"
              }`}
            >
              {sector.replace(/_/g, " ")}
            </button>
          ))}
          {sectors.size > 0 && (
            <button
              type="button"
              onClick={() => setSectors(new Set())}
              className="px-2 py-0.5 text-[11px] text-text-muted underline"
            >
              clear
            </button>
          )}
        </div>
      </div>

      {/* Column headings: six lens columns on desktop, one strip on phones. */}
      <div className="hidden border-b border-border bg-surface-raised px-6 py-1.5 text-[11px] uppercase tracking-wide text-text-muted lg:flex">
        <button
          type="button"
          onClick={() => toggleSort("ticker")}
          className="w-56 shrink-0 text-left hover:text-text"
        >
          Company {sortKey === "ticker" && (descending ? "▾" : "▴")}
        </button>
        {LENSES.map((lens) => (
          <button
            key={lens}
            type="button"
            onClick={() => toggleSort(lens)}
            className="flex-1 text-left hover:text-text"
          >
            {lens} {sortKey === lens && (descending ? "▾" : "▴")}
          </button>
        ))}
        <button
          type="button"
          onClick={() => toggleSort("dispersion")}
          className="w-28 shrink-0 text-right hover:text-text"
        >
          Disagreement {sortKey === "dispersion" && (descending ? "▾" : "▴")}
        </button>
        <button
          type="button"
          hidden={!showEarnings}
          onClick={() => toggleSort("earnings")}
          className="hidden w-14 text-right text-[10px] uppercase tracking-wide text-text-muted md:block"
        >
          Days to results {sortKey === "earnings" && (descending ? "▾" : "▴")}
        </button>
      </div>

      <DrawerStack>
        {adminOpen && <UniverseAdmin onClose={() => setAdminOpen(false)} />}
        {askOpen && (
          <AskClaude
            context={{ screen: "universe", as_of: data?.as_of, showing: absolute ? "absolute" : "relative",
              visible: items.filter((i) => i.kind === "row").slice(0, 25).map((i) => i.kind === "row" ? {
                ticker: i.row.ticker, sector: i.row.sector, dispersion: i.row.dispersion } : null) }}
            onClose={() => setAskOpen(false)}
          />
        )}
      </DrawerStack>

      <div ref={scrollRef} className="flex-1 overflow-auto">
        <div
          style={{ height: virtualizer.getTotalSize(), position: "relative" }}
        >
          {virtualizer.getVirtualItems().map((virtualRow) => {
            const item = items[virtualRow.index];
            if (!item) return null;

            const style = {
              position: "absolute" as const,
              top: 0,
              left: 0,
              width: "100%",
              height: virtualRow.size,
              transform: `translateY(${virtualRow.start}px)`,
            };

            if (item.kind === "header") {
              return (
                <div
                  key={virtualRow.key}
                  style={style}
                  className="flex items-center gap-2 border-y border-border bg-surface-sunken px-4 text-xs font-medium uppercase tracking-wide text-text-muted sm:px-6"
                >
                  {item.label.replace(/_/g, " ")}
                  <span className="tabular text-[11px]">{item.count}</span>
                </div>
              );
            }

            const row = item.row;
            return (
              <div
                key={virtualRow.key}
                style={style}
                role="button"
                tabIndex={0}
                onClick={() => navigate(`/company/${row.ticker}`)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    navigate(`/company/${row.ticker}`);
                  }
                }}
                className="flex cursor-pointer items-center border-b border-border px-4 hover:bg-surface-raised sm:px-6"
                data-testid={`row-${row.ticker}`}
              >
                <div className="flex w-40 shrink-0 flex-col justify-center lg:w-56">
                  <span className="tabular text-sm font-medium">{row.ticker}</span>
                  <span className="truncate text-[11px] text-text-muted">
                    {row.name}
                  </span>
                </div>

                {/* Phones get one compact strip; wide screens get six columns. */}
                <div className="flex-1 lg:hidden">
                  <LensStrip lenses={row.lenses} absolute={absolute} />
                </div>
                <div className="hidden flex-1 items-center gap-3 lg:flex">
                  {LENSES.map((lens: LensName) => (
                    <div key={lens} className="flex-1">
                      <LensBar
                        lens={lens}
                        cell={row.lenses[lens]}
                        absolute={absolute}
                      />
                    </div>
                  ))}
                </div>

                {showEarnings ? (
                  <div className="hidden w-14 shrink-0 text-right md:block">
                    {row.days_to_earnings === null || row.days_to_earnings === undefined ? (
                      <span className="tabular text-xs text-text-muted" title="No future report date on file">
                        —
                      </span>
                    ) : (
                      <span className="tabular text-xs">{row.days_to_earnings}d</span>
                    )}
                  </div>
                ) : null}

                <div className="w-20 shrink-0 text-right lg:w-28">
                  <DispersionCell
                    lenses={row.lenses}
                    absolute={absolute}
                    fallback={row.dispersion}
                  />
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
