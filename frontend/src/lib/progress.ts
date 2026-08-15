/** The getting-started checklist, tracking what Roger has ACTUALLY done.
 *
 *  Half the steps are derived from real server state — a promoted strategy, a
 *  logged position, a written thesis — because a checklist that ticks itself
 *  when you click "next" teaches nothing. The other half (visiting a screen,
 *  running a screen) can only be observed locally.
 */

export const STEP_KEYS = [
  "added_company",
  "ran_screen",
  "read_strategy",
  "promoted_strategy",
  "logged_position",
  "wrote_thesis",
] as const;

export type StepKey = (typeof STEP_KEYS)[number];

const storageKey = (key: StepKey) => `prism.progress.${key}`;

export function markDone(key: StepKey): void {
  try {
    window.localStorage.setItem(storageKey(key), "1");
  } catch {
    // Private browsing or a blocked store: the checklist degrades to
    // server-derived steps only, which is a cosmetic loss.
  }
}

export function isMarked(key: StepKey): boolean {
  try {
    return window.localStorage.getItem(storageKey(key)) === "1";
  } catch {
    return false;
  }
}
