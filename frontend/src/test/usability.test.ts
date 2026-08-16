import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/** The rules Roger asked for, enforced as tests rather than as intentions.
 *
 *  His verdict was "I have no idea how to use this". These pin the fixes so a
 *  later change cannot quietly reintroduce a screen with no explanation on it.
 */

const ROUTES = join(__dirname, "..", "routes");
const screens = readdirSync(ROUTES).filter((f) => f.endsWith(".tsx"));
const read = (file: string) => readFileSync(join(ROUTES, file), "utf8");

// Company detail and Strategy detail are drill-downs reached from a listing;
// they carry their own explanatory panels but are listed here explicitly so
// adding a screen forces a decision rather than silently opting out.
const EVERY_SCREEN = [
  "Universe.tsx", "Company.tsx", "Screener.tsx", "Research.tsx", "Book.tsx",
  "Decisions.tsx", "Strategies.tsx", "Backtest.tsx", "Glossary.tsx",
  "Principles.tsx", "GettingStarted.tsx", "Reconciliation.tsx",
];

describe("every screen explains itself", () => {
  it("has no screens missing from the checklist", () => {
    const known = new Set([...EVERY_SCREEN, "Strategy.tsx"]);
    for (const screen of screens) {
      expect(known.has(screen), `${screen} is new — give it a purpose panel`).toBe(true);
    }
  });

  it("every screen says what it is for", () => {
    for (const screen of EVERY_SCREEN) {
      const source = read(screen);
      const explains =
        source.includes("PagePurpose") ||
        // GettingStarted IS the explanation; it carries its own standfirst.
        screen === "GettingStarted.tsx";
      expect(explains, `${screen} has no "What is this page for?" panel`).toBe(true);
    }
  });

  it("every screen can be asked about", () => {
    for (const screen of EVERY_SCREEN.concat("Strategy.tsx")) {
      const source = read(screen);
      expect(
        source.includes("useRegisterScreen"),
        `${screen} does not register context for Ask Claude`,
      ).toBe(true);
    }
  });
});

describe("jargon does not stand alone", () => {
  const BANNED: [string, string][] = [
    ["Backtest edge", "renamed to 'Beat random by'"],
    ["Cost drag", "renamed to 'Lost to fees'"],
    [">Disp<", "renamed to 'Disagreement'"],
  ];

  it("the renamed columns are gone", () => {
    for (const screen of screens) {
      const source = read(screen);
      for (const [phrase, why] of BANNED) {
        expect(source.includes(phrase), `${screen} still uses "${phrase}" — ${why}`).toBe(false);
      }
    }
  });

  it("screens showing performance numbers also import their translations", () => {
    for (const screen of ["Strategies.tsx", "Strategy.tsx", "Backtest.tsx"]) {
      const source = read(screen);
      expect(
        source.includes("lib/explain"),
        `${screen} shows numbers without importing plain-English translations`,
      ).toBe(true);
    }
  });
});

describe("empty states say why they are empty", () => {
  it("Book and Decisions explain that the user has not done something yet", () => {
    for (const screen of ["Book.tsx", "Decisions.tsx"]) {
      const source = read(screen);
      expect(source.includes("NothingYet"), `${screen} lacks an explained empty state`).toBe(true);
    }
    expect(read("Book.tsx")).toContain("log your first position");
    expect(read("Decisions.tsx")).toContain("write down your first decision");
  });

  it("Strategies says why nothing is trading", () => {
    expect(read("Strategies.tsx")).toContain("No strategies are trading yet");
  });
});

describe("the promote flow is findable", () => {
  const promote = readFileSync(
    join(__dirname, "..", "components", "PromoteFlow.tsx"),
    "utf8",
  );

  it("uses plain words rather than 'promote to paper'", () => {
    expect(promote).toContain("Put this to work with pretend money");
  });

  it("states what happens, when, and that no real money is involved", () => {
    expect(promote).toContain("£100,000 of pretend money");
    expect(promote).toContain("7am");
    expect(promote).toMatch(/No real money is involved/i);
  });

  it("shows an honest view including the sample-size caveat", () => {
    expect(promote).toContain("My honest view");
    expect(promote).toContain("track_record_verdict");
  });

  it("appears above the tables on the strategy page", () => {
    const source = read("Strategy.tsx");
    const flow = source.indexOf("<PromoteFlow");
    const tables = source.indexOf("How it did in testing");
    expect(flow).toBeGreaterThan(-1);
    expect(flow).toBeLessThan(tables);
  });
});
