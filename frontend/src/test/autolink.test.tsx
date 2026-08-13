import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { buildMatcher, linkify } from "../lib/autolink";
import type { GlossaryTerm } from "../api/glossary";

function term(slug: string, name: string, aliases: string[] = []): GlossaryTerm {
  return {
    slug,
    term: name,
    aliases,
    short_definition: "",
    full_explanation: "",
    worked_example: null,
    how_to_read_it: null,
    common_mistakes: null,
    related_slugs: [],
    external_links: [],
    category: "test",
    user_note: null,
    user_note_updated_at: null,
  };
}

const TERMS = [
  term("fcf", "Free cash flow", ["FCF"]),
  term("fcf_yield", "Free cash flow yield", ["FCF yield"]),
  term("pe_ratio", "P/E ratio", ["P/E", "price to earnings"]),
  term("drawdown", "Maximum drawdown", ["drawdown"]),
  term("r_multiple", "R-multiple", ["R"]),
];

const matcher = buildMatcher(TERMS)!;

function renderProse(text: string) {
  const onOpen = vi.fn();
  render(<div data-testid="prose">{linkify(text, matcher, onOpen)}</div>);
  return { onOpen, container: screen.getByTestId("prose") };
}

describe("auto-linking", () => {
  it("prefers the longest match", () => {
    // "Free cash flow yield" must not be linked as "Free cash flow" + " yield".
    const { container } = renderProse("The free cash flow yield is 5%.");
    const buttons = container.querySelectorAll("button");
    expect(buttons).toHaveLength(1);
    expect(buttons[0].textContent).toBe("free cash flow yield");
  });

  it("links only the first occurrence of a term", () => {
    const { container } = renderProse(
      "Free cash flow matters. Free cash flow is not profit. Free cash flow again.",
    );
    expect(container.querySelectorAll("button")).toHaveLength(1);
  });

  it("treats an alias and its term as the same entry for first-occurrence", () => {
    const { container } = renderProse("Free cash flow is cash left over. FCF for short.");
    const buttons = container.querySelectorAll("button");
    expect(buttons).toHaveLength(1);
    expect(buttons[0].textContent).toBe("Free cash flow");
  });

  it("matches case-insensitively but displays the original casing", () => {
    const { container } = renderProse("free CASH flow is the measure.");
    expect(container.querySelector("button")?.textContent).toBe("free CASH flow");
  });

  it("never links inside a fenced code block", () => {
    const { container } = renderProse(
      "```\nfree cash flow = ops - capex\n```\nFree cash flow explained.",
    );
    const buttons = container.querySelectorAll("button");
    expect(buttons).toHaveLength(1);
    // The one link is the prose after the block, not the text inside it.
    expect(container.textContent).toContain("free cash flow = ops - capex");
    expect(buttons[0].textContent).toBe("Free cash flow");
  });

  it("never links inside an inline code span", () => {
    const { container } = renderProse("Use `free cash flow` as the column name.");
    expect(container.querySelectorAll("button")).toHaveLength(0);
  });

  it("does not match inside a number or a longer word", () => {
    // "R" is below the minimum match length precisely so it cannot do this.
    const { container } = renderProse("The value 3R4 and the word PREtty stay untouched.");
    expect(container.querySelectorAll("button")).toHaveLength(0);
  });

  it("matches terms containing punctuation", () => {
    const { container } = renderProse("Its P/E is high.");
    expect(container.querySelector("button")?.textContent).toBe("P/E");
  });

  it("opens the right term when clicked", () => {
    const { onOpen, container } = renderProse("Maximum drawdown was severe.");
    container.querySelector("button")!.click();
    expect(onOpen).toHaveBeenCalledWith("drawdown");
  });

  it("carries first-occurrence state across passages when given a shared set", () => {
    const seen = new Set<string>();
    const onOpen = vi.fn();
    render(
      <div data-testid="prose">
        <p>{linkify("Free cash flow is one thing.", matcher, onOpen, { alreadyLinked: seen })}</p>
        <p>{linkify("Free cash flow again later.", matcher, onOpen, { alreadyLinked: seen })}</p>
      </div>,
    );
    expect(screen.getByTestId("prose").querySelectorAll("button")).toHaveLength(1);
  });
});
