import { describe, expect, it } from "vitest";
import {
  annualised,
  explainDrawdown,
  explainEdge,
  explainExpectancy,
  explainSample,
  explainTotalReturn,
  explainWinRate,
  yearsBetween,
} from "../lib/explain";

describe("plain-English translation", () => {
  it("turns a total return into a yearly rate and says both", () => {
    const text = explainTotalReturn(645, "2010-01-01", "2025-01-01");
    expect(text).toContain("645%");
    expect(text).toContain("15 years");
    // The bit that confused Roger: why a modest yearly rate makes a huge total.
    expect(text).toContain("compounds");
  });

  it("computes the yearly rate correctly", () => {
    // 11% a year for 15 years really does make about +378%; 645% is ~14.4%.
    const years = yearsBetween("2010-01-01", "2025-01-01");
    expect(years).toBeCloseTo(15, 0);
    expect(annualised(645, 15)).toBeCloseTo(14.4, 0);
  });

  it("never shows a return without a duration", () => {
    const text = explainTotalReturn(120, "2020-01-01", "2025-01-01");
    expect(text).toMatch(/years/);
  });

  it("turns expectancy in R into pence per pound risked", () => {
    expect(explainExpectancy(0.902)).toContain("90p");
    expect(explainExpectancy(0.902)).toContain("£1 risked");
    expect(explainExpectancy(-0.5)).toContain("LOST");
  });

  it("states the edge per trade, not per year, and in money", () => {
    const text = explainEdge(6.2, 400);
    expect(text).toContain("6.20%");
    expect(text).toContain("each trade");
    expect(text).toContain("400 test trades");
    // Per-trade must never be described as annual — it would read better and
    // be false.
    expect(text).not.toMatch(/a year|per year|annual/i);
  });

  it("says plainly when the edge is negative", () => {
    expect(explainEdge(-1.2)).toContain("WORSE");
    expect(explainEdge(-1.2)).toContain("Picking at random would have done better");
  });

  it("expresses a drawdown as money out of a real pot", () => {
    const text = explainDrawdown(-41);
    expect(text).toContain("41%");
    expect(text).toContain("£41,000");
  });

  it("expresses a win rate as trades in every hundred", () => {
    expect(explainWinRate(0.533)).toContain("53 trades in every 100");
  });

  it("refuses to dress up a small sample", () => {
    expect(explainSample(11)).toContain("far too few");
    expect(explainSample(0)).toContain("No trades yet");
    expect(explainSample(4000)).toContain("4,000");
  });

  it("uses no statistical notation anywhere", () => {
    const all = [
      explainTotalReturn(645, "2010-01-01", "2025-01-01"),
      explainExpectancy(0.9),
      explainEdge(6.2, 400),
      explainDrawdown(-41),
      explainWinRate(0.5),
      explainSample(11),
    ].join(" ");
    expect(all).not.toMatch(/\bp\s*[=<]|\bp-value|\bn\s*=|confidence interval|Sharpe/i);
  });

  it("handles missing numbers without printing undefined", () => {
    for (const text of [
      explainExpectancy(null),
      explainEdge(undefined),
      explainDrawdown(null),
      explainTotalReturn(null),
    ]) {
      expect(text).not.toContain("undefined");
      expect(text.length).toBeGreaterThan(10);
    }
  });
});
