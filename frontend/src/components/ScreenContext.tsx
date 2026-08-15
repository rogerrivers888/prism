import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { AskClaude } from "./AskClaude";

type Value = {
  /** What the current screen is showing, handed to Claude verbatim. */
  setContext: (screen: string, detail: unknown, prompts?: string[]) => void;
  open: (seedPrompt?: string) => void;
};

const Context = createContext<Value | null>(null);

export function useScreenContext(): Value {
  const value = useContext(Context);
  if (!value) throw new Error("useScreenContext used outside ScreenContextProvider");
  return value;
}

/** Ask Claude, available on every screen rather than just Company.
 *
 *  Roger's complaint was that "what am I looking at?" had nowhere to go on
 *  eight of nine screens. The button lives in the shell; each screen registers
 *  what it is currently showing, so the answer is always about the numbers in
 *  front of him rather than the app in general.
 */
export function ScreenContextProvider({ children }: { children: ReactNode }) {
  const [screen, setScreen] = useState("Prism");
  const [detail, setDetail] = useState<unknown>(null);
  const [prompts, setPrompts] = useState<string[]>([]);
  const [open, setOpen] = useState(false);
  const [seed, setSeed] = useState<string | undefined>();

  const value = useMemo<Value>(
    () => ({
      setContext: (nextScreen, nextDetail, nextPrompts) => {
        setScreen(nextScreen);
        setDetail(nextDetail);
        setPrompts(nextPrompts ?? []);
      },
      open: (seedPrompt) => {
        setSeed(seedPrompt);
        setOpen(true);
      },
    }),
    [],
  );

  return (
    <Context.Provider value={value}>
      {children}
      <button
        type="button"
        onClick={() => {
          setSeed(undefined);
          setOpen(true);
        }}
        className="fixed bottom-4 right-4 z-30 rounded-full border border-border bg-surface-raised px-4 py-2 text-sm shadow-lg hover:bg-surface-sunken"
      >
        Ask Claude about this page
      </button>
      {open && (
        <AskClaude
          context={{ screen, showing: detail }}
          suggestions={
            prompts.length
              ? prompts
              : [
                  "What am I looking at on this page?",
                  "Which number here matters most, and why?",
                  "What is this page not telling me?",
                ]
          }
          seedPrompt={seed}
          onClose={() => {
            setOpen(false);
            setSeed(undefined);
          }}
        />
      )}
    </Context.Provider>
  );
}

/** Registers a screen's context on mount and whenever its data changes. */
export function useRegisterScreen(
  screen: string,
  detail: unknown,
  prompts?: string[],
): void {
  const { setContext } = useScreenContext();
  // Keyed on the serialised payload: a re-render with identical data must not
  // loop, but a real data change should update what Claude can see.
  const serialised = JSON.stringify(detail ?? null);
  const promptKey = (prompts ?? []).join("|");
  useEffect(() => {
    setContext(screen, detail === undefined ? null : JSON.parse(serialised), prompts);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [screen, serialised, promptKey]);
}
