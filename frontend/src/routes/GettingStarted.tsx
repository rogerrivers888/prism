import { Link } from "react-router-dom";
import { useBook, useDecisions } from "../api/screens";
import { useLeaderboard } from "../api/strategies";
import { useUniverse } from "../api/universe";
import { isMarked, type StepKey } from "../lib/progress";
import { useRegisterScreen } from "../components/ScreenContext";

type Step = {
  key: StepKey;
  title: string;
  what: string;
  where: string;
  to: string;
  done: boolean;
};

/** A checklist, not a carousel.
 *
 *  It ticks off what Roger has genuinely done — a promoted strategy, a logged
 *  position, a written thesis are read from the server, not from a "next"
 *  button. A tour you can click through without doing anything teaches
 *  nothing, which is roughly what happened the first time.
 */
export default function GettingStarted() {
  const universe = useUniverse();
  const strategies = useLeaderboard();
  const book = useBook();
  const decisions = useDecisions();

  const anyPromoted = Object.values(strategies.data?.boards ?? {})
    .flat()
    .some((row) => row.stage !== "backtest");
  const anyPosition = (book.data?.positions?.length ?? 0) > 0;
  const anyThesis = (decisions.data?.length ?? 0) > 0;

  const steps: Step[] = [
    {
      key: "added_company",
      title: "Look at the companies Prism tracks",
      what:
        "Every company is scored six different ways — how cheap it is, how fast it is growing, " +
        "how good the business is, and so on. You do not need to add anything to start: " +
        `Prism already follows ${universe.data?.count ?? "hundreds of"} companies.`,
      where: "Universe",
      to: "/",
      done: isMarked("added_company") || (universe.data?.count ?? 0) > 0,
    },
    {
      key: "ran_screen",
      title: "Narrow them down to a handful",
      what:
        "The Screener lets you say what you want — cheap, growing, not falling apart — and " +
        "shows only the companies that match. This is how you go from hundreds to a shortlist.",
      where: "Screener",
      to: "/screener",
      done: isMarked("ran_screen"),
    },
    {
      key: "read_strategy",
      title: "Read one of the twelve strategies",
      what:
        "Each is a written-down way of picking shares — some from famous investors, some " +
        "Prism's own. Open one and read what it believes and how it did in testing.",
      where: "Strategies",
      to: "/strategies",
      done: isMarked("read_strategy"),
    },
    {
      key: "promoted_strategy",
      title: "Start one with pretend money",
      what:
        "Pick a strategy you find convincing and give it £100,000 of pretend money. It will " +
        "trade every day by its own rules so you can watch whether it actually works. " +
        "No real money is involved.",
      where: "Strategies",
      to: "/strategies",
      done: anyPromoted,
    },
    {
      key: "logged_position",
      title: "Record a share you actually own",
      what:
        "The Book is your real portfolio. Logging what you hold, and where you would sell, " +
        "is what lets Prism show you how much you actually have at risk.",
      where: "Book",
      to: "/book",
      done: anyPosition,
    },
    {
      key: "wrote_thesis",
      title: "Write down why, before you act",
      what:
        "Before buying or selling, record what you believe, what would prove you wrong, and " +
        "how it could fail. Months later this is the only way to tell a good decision from " +
        "a lucky one.",
      where: "Decisions",
      to: "/decisions",
      done: anyThesis,
    },
  ];

  const completed = steps.filter((step) => step.done).length;
  useRegisterScreen("Getting started", { completed, total: steps.length }, [
    "What should I do first?",
    "I don't understand what this app is for — explain it simply",
    "What is the difference between the Book and the Strategies pages?",
  ]);

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-6">
      <header>
        <h1 className="font-display text-2xl uppercase tracking-wide">Getting started</h1>
        <p className="mt-1 max-w-2xl text-sm leading-relaxed text-text-muted">
          Prism is a research tool for your own investing. It scores companies, tests ways of
          picking them, and keeps an honest record of your decisions. It never tells you what
          to buy.
        </p>
        <p className="mt-3 text-sm">
          <span className="tabular font-medium">
            {completed} of {steps.length}
          </span>{" "}
          done. There is no rush and no wrong order.
        </p>
        <div className="mt-2 h-1.5 w-full overflow-hidden rounded bg-surface-sunken">
          <div
            className="h-full bg-accent transition-all"
            style={{ width: `${(completed / steps.length) * 100}%` }}
          />
        </div>
      </header>

      <ol className="space-y-3">
        {steps.map((step, index) => (
          <li
            key={step.key}
            className={`rounded-md border p-4 ${
              step.done ? "border-border bg-surface-sunken" : "border-border"
            }`}
          >
            <div className="flex items-start gap-3">
              <span
                aria-hidden
                className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border text-[11px] ${
                  step.done
                    ? "border-accent bg-accent text-surface"
                    : "border-border text-text-muted"
                }`}
              >
                {step.done ? "✓" : index + 1}
              </span>
              <div className="min-w-0 flex-1">
                <h2 className="text-sm font-medium">
                  {step.title}
                  {step.done && (
                    <span className="ml-2 text-[11px] uppercase tracking-wide text-text-muted">
                      done
                    </span>
                  )}
                </h2>
                <p className="mt-1 text-sm leading-relaxed text-text-muted">{step.what}</p>
                <Link
                  to={step.to}
                  className="mt-2 inline-block rounded border border-border px-2.5 py-1 text-xs hover:bg-surface-sunken"
                >
                  Go to {step.where} →
                </Link>
              </div>
            </div>
          </li>
        ))}
      </ol>

      <section className="rounded-md border border-border p-4">
        <h2 className="font-display text-base font-semibold">If you only read one thing</h2>
        <p className="mt-1 text-sm leading-relaxed text-text-muted">
          The <Link to="/principles" className="underline">Principles</Link> page explains how
          Prism thinks and, more importantly, why most of what looks like a good investing idea
          turns out not to be. Ten minutes, plain English.
        </p>
      </section>
    </div>
  );
}
