import { describe, expect, it } from "vitest";
import { ROWS } from "./fixtures";
import { scoreOf, sortRows } from "../lib/universe-view";

describe("sorting", () => {
  it("orders by dispersion descending, with unscorable names last", () => {
    const sorted = sortRows(ROWS, "dispersion", true, false);
    expect(sorted.map((r) => r.ticker)).toEqual(["MU", "MID", "THIN"]);
  });

  it("orders by dispersion ascending without floating nulls to the top", () => {
    const sorted = sortRows(ROWS, "dispersion", false, false);
    // THIN has no dispersion. It is unranked, not "the lowest", so it stays
    // at the bottom in both directions.
    expect(sorted.map((r) => r.ticker)).toEqual(["MID", "MU", "THIN"]);
  });

  it("sorts by a lens using whichever reading is displayed", () => {
    const relative = sortRows(ROWS, "value", true, false).map((r) => r.ticker);
    const absolute = sortRows(ROWS, "value", true, true).map((r) => r.ticker);
    // MU is the cheapest against its peers (64.8) but the most expensive in
    // absolute terms (34.2), so the toggle genuinely reorders the table.
    expect(relative[0]).toBe("MU");
    expect(absolute[0]).toBe("MID");
  });
});

describe("scoreOf", () => {
  it("returns null for an inapplicable lens rather than a number", () => {
    const mid = ROWS.find((r) => r.ticker === "MID")!;
    expect(scoreOf(mid, "cycle", false)).toBeNull();
  });

  it("switches reading with the absolute flag", () => {
    const mu = ROWS.find((r) => r.ticker === "MU")!;
    expect(scoreOf(mu, "value", false)).toBe(64.8);
    expect(scoreOf(mu, "value", true)).toBe(34.2);
  });
});
