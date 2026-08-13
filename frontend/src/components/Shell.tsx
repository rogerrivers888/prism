import { NavLink, Outlet } from "react-router-dom";
import { ThemeToggle } from "./ThemeToggle";

const NAV = [
  { to: "/", label: "Universe", end: true },
  { to: "/screener", label: "Screener" },
  { to: "/research", label: "Research" },
  { to: "/book", label: "Book" },
  { to: "/decisions", label: "Decisions" },
  { to: "/strategies", label: "Strategies" },
  { to: "/backtest", label: "Backtest" },
  { to: "/glossary", label: "Glossary" },
  { to: "/principles", label: "Principles" },
];

export function Shell() {
  return (
    <div className="flex h-dvh flex-col bg-surface text-text">
      <header className="flex items-center gap-4 border-b border-border px-4 py-2 sm:px-6">
        <span className="font-display text-xl font-semibold tracking-tight">
          Prism
        </span>
        <nav className="flex flex-1 gap-3 overflow-x-auto text-xs">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `whitespace-nowrap ${isActive ? "text-text" : "text-text-muted hover:text-text"}`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <ThemeToggle />
      </header>
      <main className="min-h-0 flex-1">
        <Outlet />
      </main>
    </div>
  );
}
