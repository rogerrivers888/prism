import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export type ThemeChoice = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";

const STORAGE_KEY = "prism.theme";

type ThemeContextValue = {
  /** What the user chose, including "system". */
  choice: ThemeChoice;
  /** What is actually on screen once "system" is resolved. */
  resolved: ResolvedTheme;
  setChoice: (choice: ThemeChoice) => void;
  /** Cycles light → dark → system, for the header control. */
  cycle: () => void;
};

const ThemeContext = createContext<ThemeContextValue | null>(null);

function readStoredChoice(): ThemeChoice {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "light" || stored === "dark" || stored === "system") {
      return stored;
    }
  } catch {
    // Private browsing or a blocked storage API: fall back to the OS.
  }
  return "system";
}

function systemPrefersDark(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-color-scheme: dark)").matches
  );
}

export function resolveTheme(
  choice: ThemeChoice,
  prefersDark: boolean,
): ResolvedTheme {
  if (choice === "system") return prefersDark ? "dark" : "light";
  return choice;
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [choice, setChoiceState] = useState<ThemeChoice>(readStoredChoice);
  const [prefersDark, setPrefersDark] = useState(systemPrefersDark);

  // Follow the OS while the choice is "system", including live changes.
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = (event: MediaQueryListEvent) =>
      setPrefersDark(event.matches);
    query.addEventListener?.("change", onChange);
    return () => query.removeEventListener?.("change", onChange);
  }, []);

  const resolved = resolveTheme(choice, prefersDark);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", resolved === "dark");
  }, [resolved]);

  const setChoice = useCallback((next: ThemeChoice) => {
    setChoiceState(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // A theme we cannot persist is still a theme we can apply.
    }
  }, []);

  const cycle = useCallback(() => {
    setChoice(
      choice === "light" ? "dark" : choice === "dark" ? "system" : "light",
    );
  }, [choice, setChoice]);

  const value = useMemo(
    () => ({ choice, resolved, setChoice, cycle }),
    [choice, resolved, setChoice, cycle],
  );

  return (
    <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
  );
}

export function useTheme() {
  const context = useContext(ThemeContext);
  if (!context) throw new Error("useTheme must be used inside a ThemeProvider");
  return context;
}
