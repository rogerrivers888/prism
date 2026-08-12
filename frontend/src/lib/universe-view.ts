import { LENSES, type LensName, type UniverseRow } from "../api/universe";

export type SortKey = "dispersion" | "ticker" | "earnings" | LensName;
export type GroupKey = "none" | "sector" | "size";

/** Pull the value a sort or a bar should use, honouring the relative/absolute
 *  toggle. Null means "no score", which is different from a low score and is
 *  always sorted last regardless of direction. */
export function scoreOf(
  row: UniverseRow,
  lens: LensName,
  absolute: boolean,
): number | null {
  const cell = row.lenses[lens];
  if (!cell || !cell.applicable) return null;
  const value = absolute ? cell.score_absolute : cell.score;
  return value ?? null;
}

export function sortRows(
  rows: UniverseRow[],
  key: SortKey,
  descending: boolean,
  absolute: boolean,
): UniverseRow[] {
  const valueOf = (row: UniverseRow): number | string | null => {
    if (key === "ticker") return row.ticker;
    if (key === "dispersion") return row.dispersion ?? null;
    // Negated so "descending" means soonest first, matching every other
    // column where descending puts the most interesting row on top.
    if (key === "earnings")
      return row.days_to_earnings === null || row.days_to_earnings === undefined
        ? null
        : -row.days_to_earnings;
    return scoreOf(row, key, absolute);
  };

  return [...rows].sort((a, b) => {
    const left = valueOf(a);
    const right = valueOf(b);

    // Missing values sink to the bottom either way: a name we could not score
    // is not "the worst", it is unranked, and it should not crowd the top of
    // an ascending sort.
    if (left === null && right === null) return a.ticker.localeCompare(b.ticker);
    if (left === null) return 1;
    if (right === null) return -1;

    if (typeof left === "string" || typeof right === "string") {
      const compared = String(left).localeCompare(String(right));
      return descending ? -compared : compared;
    }
    const compared = left - right;
    return descending ? -compared : compared;
  });
}

export function groupRows(
  rows: UniverseRow[],
  key: GroupKey,
): { label: string; rows: UniverseRow[] }[] {
  if (key === "none") return [{ label: "", rows }];

  const buckets = new Map<string, UniverseRow[]>();
  for (const row of rows) {
    const label = key === "sector" ? row.sector : row.size;
    const bucket = buckets.get(label);
    if (bucket) bucket.push(row);
    else buckets.set(label, [row]);
  }
  return [...buckets.entries()]
    .map(([label, groupedRows]) => ({ label, rows: groupedRows }))
    .sort((a, b) => b.rows.length - a.rows.length);
}

export function sectorsOf(rows: UniverseRow[]): string[] {
  return [...new Set(rows.map((row) => row.sector))].sort();
}

export function filterRows(
  rows: UniverseRow[],
  sectors: Set<string>,
  search: string,
): UniverseRow[] {
  const needle = search.trim().toLowerCase();
  return rows.filter((row) => {
    if (sectors.size > 0 && !sectors.has(row.sector)) return false;
    if (!needle) return true;
    return (
      row.ticker.toLowerCase().includes(needle) ||
      row.name.toLowerCase().includes(needle)
    );
  });
}

/** Rows flattened into a single virtualisable list, with group headers as
 *  their own entries so one virtualiser handles the whole table. */
export type FlatItem =
  | { kind: "header"; label: string; count: number }
  | { kind: "row"; row: UniverseRow };

export function flatten(
  groups: { label: string; rows: UniverseRow[] }[],
): FlatItem[] {
  const items: FlatItem[] = [];
  for (const group of groups) {
    if (group.label) {
      items.push({ kind: "header", label: group.label, count: group.rows.length });
    }
    for (const row of group.rows) items.push({ kind: "row", row });
  }
  return items;
}

export const LENS_ORDER = LENSES;
