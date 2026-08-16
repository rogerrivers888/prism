import { useEffect, useId, useRef, useState } from "react";

/** A select that opens BELOW its trigger.
 *
 *  A native <select> renders its menu over the control, so the thing you just
 *  clicked disappears behind the list and you lose your place. This anchors
 *  the panel underneath, keeps the trigger visible, and closes on Escape or
 *  a click elsewhere.
 */
export type Option = { value: string; label: string };

export function Dropdown({
  value,
  options,
  onChange,
  label,
  className = "",
}: {
  value: string;
  options: Option[];
  onChange: (value: string) => void;
  label: string;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const wrapper = useRef<HTMLDivElement>(null);
  const id = useId();

  const selected = options.find((option) => option.value === value);

  useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => {
      if (!wrapper.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  useEffect(() => {
    if (open) setActive(Math.max(0, options.findIndex((o) => o.value === value)));
  }, [open, options, value]);

  const choose = (next: string) => {
    onChange(next);
    setOpen(false);
  };

  return (
    <div ref={wrapper} className={`relative ${className}`}>
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={label}
        onClick={() => setOpen((current) => !current)}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown" && !open) {
            event.preventDefault();
            setOpen(true);
          }
        }}
        className="flex items-center gap-1.5 rounded border border-border bg-surface-raised px-2 py-1 text-xs hover:bg-surface-sunken"
      >
        <span>{selected?.label ?? label}</span>
        <span aria-hidden className="text-text-muted">
          {open ? "▴" : "▾"}
        </span>
      </button>

      {open && (
        // Positioned below, not over: top-full is the whole point.
        <ul
          role="listbox"
          id={id}
          aria-label={label}
          className="absolute left-0 top-full z-40 mt-1 max-h-72 min-w-full overflow-auto rounded-md border border-border bg-surface-raised py-1 shadow-lg"
          onKeyDown={(event) => {
            if (event.key === "ArrowDown") {
              event.preventDefault();
              setActive((i) => Math.min(i + 1, options.length - 1));
            } else if (event.key === "ArrowUp") {
              event.preventDefault();
              setActive((i) => Math.max(i - 1, 0));
            } else if (event.key === "Enter") {
              event.preventDefault();
              choose(options[active].value);
            }
          }}
          tabIndex={-1}
          ref={(node) => node?.focus()}
        >
          {options.map((option, index) => (
            <li key={option.value}>
              <button
                type="button"
                role="option"
                aria-selected={option.value === value}
                onMouseEnter={() => setActive(index)}
                onClick={() => choose(option.value)}
                className={`block w-full whitespace-nowrap px-3 py-1.5 text-left text-xs ${
                  index === active ? "bg-surface-sunken" : ""
                } ${option.value === value ? "font-medium" : ""}`}
              >
                {option.value === value && <span aria-hidden className="mr-1">✓</span>}
                {option.label}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
