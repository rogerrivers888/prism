import { beforeEach, describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ThemeProvider, resolveTheme } from "../theme/ThemeProvider";
import { ThemeToggle } from "../components/ThemeToggle";

function mockPrefersDark(matches: boolean) {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: (query: string) => ({
      matches, media: query, onchange: null,
      addEventListener: () => {}, removeEventListener: () => {},
      addListener: () => {}, removeListener: () => {}, dispatchEvent: () => false,
    }),
  });
}

describe("theme", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.classList.remove("dark");
    mockPrefersDark(false);
  });

  it("follows prefers-color-scheme when there is no stored choice", () => {
    mockPrefersDark(true);
    render(<ThemeProvider><ThemeToggle /></ThemeProvider>);
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(screen.getByRole("button")).toHaveTextContent("System");
  });

  it("persists a manual choice and applies it to the document", async () => {
    const user = userEvent.setup();
    render(<ThemeProvider><ThemeToggle /></ThemeProvider>);

    await user.click(screen.getByRole("button")); // system -> light
    expect(localStorage.getItem("prism.theme")).toBe("light");
    expect(document.documentElement.classList.contains("dark")).toBe(false);

    await user.click(screen.getByRole("button")); // light -> dark
    expect(localStorage.getItem("prism.theme")).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("restores the stored choice on reload, overriding the OS", () => {
    localStorage.setItem("prism.theme", "dark");
    mockPrefersDark(false); // OS says light, stored choice must win
    render(<ThemeProvider><ThemeToggle /></ThemeProvider>);
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("resolves system against the OS preference", () => {
    expect(resolveTheme("system", true)).toBe("dark");
    expect(resolveTheme("system", false)).toBe("light");
    expect(resolveTheme("light", true)).toBe("light");
  });
});
