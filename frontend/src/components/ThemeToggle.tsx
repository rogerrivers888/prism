import { useTheme } from "../theme/ThemeProvider";

const LABEL = { light: "Light", dark: "Dark", system: "System" } as const;

export function ThemeToggle() {
  const { choice, cycle } = useTheme();
  return (
    <button
      type="button"
      onClick={cycle}
      aria-label={`Theme: ${LABEL[choice]}. Click to change.`}
      className="rounded-md border border-border px-2 py-1 text-xs text-text-muted hover:text-text"
    >
      {LABEL[choice]}
    </button>
  );
}
