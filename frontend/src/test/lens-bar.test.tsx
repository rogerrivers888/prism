import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { LensBar } from "../components/LensBar";

describe("LensBar", () => {
  it("renders a null score as an explicit no-score state with coverage, never as zero", () => {
    render(
      <LensBar
        lens="growth"
        cell={{ score: null, score_absolute: null, coverage: 0.2, applicable: true }}
        absolute={false}
      />,
    );
    // Coverage is shown so the reader knows WHY there is no score...
    expect(screen.getByText("20%")).toBeInTheDocument();
    // ...and nothing renders a 0, which would read as "scores badly" rather
    // than "could not be measured".
    expect(screen.queryByText("0.0")).not.toBeInTheDocument();
    expect(screen.getByTitle(/no score/i)).toBeInTheDocument();
  });

  it("distinguishes an inapplicable lens from an unscorable one", () => {
    render(
      <LensBar
        lens="cycle"
        cell={{ score: null, score_absolute: null, coverage: 0, applicable: false }}
        absolute={false}
      />,
    );
    expect(screen.getByText("n/a")).toBeInTheDocument();
    expect(screen.getByTitle(/not applicable/i)).toBeInTheDocument();
  });

  it("shows the reading selected by the absolute toggle", () => {
    const cell = { score: 64.8, score_absolute: 34.2, coverage: 1, applicable: true };
    const { rerender } = render(<LensBar lens="value" cell={cell} absolute={false} />);
    expect(screen.getByText("64.8")).toBeInTheDocument();

    rerender(<LensBar lens="value" cell={cell} absolute />);
    expect(screen.getByText("34.2")).toBeInTheDocument();
    expect(screen.queryByText("64.8")).not.toBeInTheDocument();
  });
});
