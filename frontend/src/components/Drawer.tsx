import { useEffect, type ReactNode } from "react";

/** Right-hand drawers that stack side by side, not modals.
 *
 * A modal would hide the thing being asked about. These sit beside the
 * content: open a lens, and the table stays readable on the left; ask Claude,
 * and the lens breakdown stays visible while the conversation runs beside it.
 * On a phone there is no room for two, so they become tabs. */
export function DrawerStack({ children }: { children: ReactNode }) {
  return (
    <div className="pointer-events-none fixed inset-y-0 right-0 z-40 flex max-w-full">
      {children}
    </div>
  );
}

export function Drawer({
  title,
  subtitle,
  onClose,
  width = "w-[min(92vw,26rem)]",
  children,
}: {
  title: string;
  subtitle?: string;
  onClose: () => void;
  width?: string;
  children: ReactNode;
}) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <aside
      className={`pointer-events-auto flex h-full ${width} flex-col border-l border-border bg-surface-raised shadow-xl`}
      role="dialog"
      aria-label={title}
    >
      <header className="flex items-start gap-2 border-b border-border px-4 py-3">
        <div className="min-w-0 flex-1">
          <h2 className="font-display text-lg font-semibold leading-tight">{title}</h2>
          {subtitle && <p className="truncate text-xs text-text-muted">{subtitle}</p>}
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label={`Close ${title}`}
          className="rounded px-2 py-0.5 text-sm text-text-muted hover:text-text"
        >
          ✕
        </button>
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">{children}</div>
    </aside>
  );
}
