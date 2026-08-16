import { useEffect, useMemo, useRef, useState } from "react";

/** A date-range picker: presets on the left, three months in view.
 *
 *  Opens below its trigger rather than over it, like every other control here.
 *  Presets cover the ranges asked for day to day; the calendar is for
 *  everything else, and picking a start then an end is the whole interaction.
 */

export type Range = { from: Date | null; to: Date | null };

export const ALL_TIME: Range = { from: null, to: null };

const startOfDay = (date: Date) => {
  const copy = new Date(date);
  copy.setHours(0, 0, 0, 0);
  return copy;
};

const daysAgo = (days: number) => {
  const date = new Date();
  date.setDate(date.getDate() - days);
  return startOfDay(date);
};

const monthsAgo = (months: number) => {
  const date = new Date();
  date.setMonth(date.getMonth() - months);
  return startOfDay(date);
};

const PRESETS: { label: string; range: () => Range }[] = [
  { label: "Today", range: () => ({ from: startOfDay(new Date()), to: new Date() }) },
  { label: "Last 7 days", range: () => ({ from: daysAgo(7), to: new Date() }) },
  { label: "Last 30 days", range: () => ({ from: daysAgo(30), to: new Date() }) },
  { label: "Last 3 months", range: () => ({ from: monthsAgo(3), to: new Date() }) },
  { label: "Last 6 months", range: () => ({ from: monthsAgo(6), to: new Date() }) },
  { label: "Last year", range: () => ({ from: monthsAgo(12), to: new Date() }) },
  {
    label: "This year",
    range: () => ({ from: new Date(new Date().getFullYear(), 0, 1), to: new Date() }),
  },
  { label: "All time", range: () => ALL_TIME },
];

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];
const WEEKDAYS = ["M", "T", "W", "T", "F", "S", "S"];

const sameDay = (a: Date | null, b: Date | null) =>
  Boolean(a && b && a.toDateString() === b.toDateString());

const format = (date: Date) =>
  `${date.getDate()} ${MONTH_NAMES[date.getMonth()].slice(0, 3)} ${date.getFullYear()}`;

export function describeRange(range: Range): string {
  if (!range.from && !range.to) return "Any time";
  if (range.from && !range.to) return `From ${format(range.from)}`;
  if (!range.from && range.to) return `Until ${format(range.to)}`;
  return `${format(range.from!)} – ${format(range.to!)}`;
}

export function withinRange(stamp: string | null, range: Range): boolean {
  if (!range.from && !range.to) return true;
  if (!stamp) return false;
  const date = new Date(stamp);
  if (range.from && date < range.from) return false;
  if (range.to) {
    // Inclusive of the whole end day, which is what picking a date means.
    const end = new Date(range.to);
    end.setHours(23, 59, 59, 999);
    if (date > end) return false;
  }
  return true;
}

function Month({
  month, range, hovered, onPick, onHover,
}: {
  month: Date;
  range: Range;
  hovered: Date | null;
  onPick: (date: Date) => void;
  onHover: (date: Date | null) => void;
}) {
  const year = month.getFullYear();
  const index = month.getMonth();
  const first = new Date(year, index, 1);
  // Monday-first, which is what a UK user expects.
  const offset = (first.getDay() + 6) % 7;
  const total = new Date(year, index + 1, 0).getDate();
  const today = startOfDay(new Date());

  const cells: (Date | null)[] = [
    ...Array.from({ length: offset }, () => null),
    ...Array.from({ length: total }, (_, i) => new Date(year, index, i + 1)),
  ];

  // While choosing the second date, shade what the range would become.
  const provisionalEnd = range.from && !range.to ? hovered : range.to;

  return (
    <div className="w-52">
      <div className="mb-1 text-center text-xs font-medium">
        {MONTH_NAMES[index]} {year}
      </div>
      <div className="grid grid-cols-7 text-center text-[10px] text-text-muted">
        {WEEKDAYS.map((day, i) => (
          <div key={i} className="py-0.5">{day}</div>
        ))}
      </div>
      <div className="grid grid-cols-7">
        {cells.map((date, i) => {
          if (!date) return <div key={i} />;
          const isStart = sameDay(date, range.from);
          const isEnd = sameDay(date, provisionalEnd);
          const inside =
            range.from && provisionalEnd && date > range.from && date < provisionalEnd;
          const future = date > today;
          return (
            <button
              key={i}
              type="button"
              disabled={future}
              onClick={() => onPick(date)}
              onMouseEnter={() => onHover(date)}
              className={`tabular h-7 text-[11px] ${
                isStart || isEnd
                  ? "bg-accent font-medium text-accent-contrast"
                  : inside
                    ? "bg-surface-sunken"
                    : future
                      ? "text-text-muted/40"
                      : "hover:bg-surface-sunken"
              } ${sameDay(date, today) && !isStart && !isEnd ? "underline" : ""}`}
            >
              {date.getDate()}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function DateRangePicker({
  value, onChange, label = "Date range",
}: {
  value: Range;
  onChange: (range: Range) => void;
  label?: string;
}) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<Range>(value);
  const [hovered, setHovered] = useState<Date | null>(null);
  const [anchor, setAnchor] = useState(() => {
    const date = new Date();
    date.setMonth(date.getMonth() - 2);
    return new Date(date.getFullYear(), date.getMonth(), 1);
  });
  const wrapper = useRef<HTMLDivElement>(null);

  useEffect(() => setDraft(value), [value]);

  useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => {
      if (!wrapper.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const months = useMemo(
    () => [0, 1, 2].map((i) => new Date(anchor.getFullYear(), anchor.getMonth() + i, 1)),
    [anchor],
  );

  const pick = (date: Date) => {
    // First click sets the start; the second sets the end, swapping if it is
    // earlier so a backwards selection still makes sense.
    if (!draft.from || (draft.from && draft.to)) {
      setDraft({ from: date, to: null });
      return;
    }
    const next =
      date < draft.from ? { from: date, to: draft.from } : { from: draft.from, to: date };
    setDraft(next);
    onChange(next);
    setOpen(false);
  };

  const shift = (by: number) =>
    setAnchor(new Date(anchor.getFullYear(), anchor.getMonth() + by, 1));

  return (
    <div ref={wrapper} className="relative">
      <button
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={label}
        onClick={() => setOpen((current) => !current)}
        className="flex items-center gap-1.5 rounded border border-border bg-surface-raised px-2 py-1 text-xs hover:bg-surface-sunken"
      >
        <span>{describeRange(value)}</span>
        <span aria-hidden className="text-text-muted">{open ? "▴" : "▾"}</span>
      </button>

      {open && (
        <div
          role="dialog"
          aria-label={label}
          className="absolute left-0 top-full z-40 mt-1 flex max-w-[95vw] overflow-x-auto rounded-md border border-border bg-surface-raised shadow-lg"
        >
          <div className="w-36 shrink-0 border-r border-border py-2">
            {PRESETS.map((preset) => (
              <button
                key={preset.label}
                type="button"
                onClick={() => {
                  const next = preset.range();
                  setDraft(next);
                  onChange(next);
                  setOpen(false);
                }}
                className="block w-full px-3 py-1.5 text-left text-xs hover:bg-surface-sunken"
              >
                {preset.label}
              </button>
            ))}
          </div>

          <div className="p-3">
            <div className="mb-2 flex items-center justify-between gap-3">
              <button type="button" onClick={() => shift(-1)} aria-label="Previous month"
                className="rounded px-2 py-0.5 text-xs hover:bg-surface-sunken">←</button>
              <span className="text-xs text-text-muted">
                {draft.from && !draft.to ? "Now pick the end date" : describeRange(draft)}
              </span>
              <button type="button" onClick={() => shift(1)} aria-label="Next month"
                className="rounded px-2 py-0.5 text-xs hover:bg-surface-sunken">→</button>
            </div>

            <div className="flex gap-4" onMouseLeave={() => setHovered(null)}>
              {months.map((month) => (
                <Month key={month.toISOString()} month={month} range={draft}
                       hovered={hovered} onPick={pick} onHover={setHovered} />
              ))}
            </div>

            <div className="mt-2 flex justify-between border-t border-border pt-2">
              <button
                type="button"
                onClick={() => { setDraft(ALL_TIME); onChange(ALL_TIME); setOpen(false); }}
                className="text-xs text-text-muted underline"
              >
                clear
              </button>
              <button type="button" onClick={() => setOpen(false)}
                className="rounded border border-border px-2 py-0.5 text-xs">Close</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
