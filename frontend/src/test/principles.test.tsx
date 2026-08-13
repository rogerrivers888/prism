import { describe, expect, it } from "vitest";
import { PRINCIPLES } from "../content/principles";

describe("principles", () => {
  it("covers the four sections that were specified", () => {
    expect(PRINCIPLES.map((p) => p.slug)).toEqual([
      "how-prism-thinks",
      "why-we-test-this-way",
      "what-the-machine-is",
      "rules-we-hold-ourselves-to",
    ]);
  });

  it("stays short enough to reread in ten minutes", () => {
    const words = PRINCIPLES.flatMap((p) =>
      p.sections.flatMap((s) => s.paragraphs),
    )
      .join(" ")
      .split(/\s+/).length;
    // ~250 wpm for careful reading of dense material.
    expect(words).toBeLessThan(2600);
    expect(words).toBeGreaterThan(1200);
  });

  it("uses no statistical notation anywhere", () => {
    const text = PRINCIPLES.flatMap((p) =>
      p.sections.flatMap((s) => [s.heading, ...s.paragraphs]),
    ).join(" ");
    expect(text).not.toMatch(/\bp\s*[=<]|\bp-value|\bn\s*=|confidence interval/i);
  });

  it("carries the earnings-drift case study as the worked example", () => {
    const testing = PRINCIPLES.find((p) => p.slug === "why-we-test-this-way")!;
    const worked = testing.sections.find((s) => s.heading.includes("worked example"));
    expect(worked).toBeDefined();
    const text = worked!.paragraphs.join(" ");
    // The whole point of the story: the control killed it.
    expect(text).toContain("+0.239%");
    expect(text).toContain("+0.173%");
    expect(text).toContain("control");
  });

  it("names the Quantopian evidence with its actual number", () => {
    const machine = PRINCIPLES.find((p) => p.slug === "what-the-machine-is")!;
    const text = machine.sections.flatMap((s) => s.paragraphs).join(" ");
    expect(text).toContain("888");
    expect(text).toMatch(/McLean and Pontiff/);
  });

  it("states each of the four self-imposed rules", () => {
    const rules = PRINCIPLES.find((p) => p.slug === "rules-we-hold-ourselves-to")!;
    const headings = rules.sections.map((s) => s.heading.toLowerCase()).join(" | ");
    expect(headings).toContain("before testing");
    expect(headings).toContain("tweak is a new strategy");
    expect(headings).toContain("nothing is edited");
    expect(headings).toContain("sample is too small");
  });
});
