import { useState } from "react";
import { usePromote, type StrategyDetail } from "../api/strategies";
import {
  explainDrawdown,
  explainEdge,
  explainPerTrade,
  windowLabel,
} from "../lib/explain";
import { markDone } from "../lib/progress";
import { useGlossary } from "./GlossaryProvider";

/** Turning a strategy on, in language that says what actually happens.
 *
 *  Roger could not find this at all — the old version was a disabled button
 *  labelled "Promote to paper trading" below three screens of tables. The
 *  words "promote" and "paper" are both jargon: one sounds like a job, the
 *  other like stationery. This says "pretend money" and shows exactly what
 *  will happen and when, before anything is committed.
 */

/** An honest one-line verdict, computed from the numbers rather than written
 *  by a model, so it can never contradict the table beside it. */
export function honestView(strategy: StrategyDetail): { line: string; warm: boolean } {
  const backtest = strategy.backtest;
  if (!backtest) {
    return { line: "This has never been tested, so there is nothing to judge yet.", warm: false };
  }
  const gate = backtest.gate ?? {};
  const overall = backtest.overall ?? {};
  const excess = backtest.excess_over_drift_pct;
  const trades = overall.round_trips ?? 0;
  const deflation = backtest.deflation?.per_trade;

  if (!gate.eligible_for_paper) {
    return {
      line:
        "I would not put money behind this. In testing it failed the basic check: " +
        (gate.blocking_reasons ?? []).join("; ") + ".",
      warm: false,
    };
  }
  if (excess !== null && excess !== undefined && excess < 1) {
    return {
      line:
        `It passed, but barely — it beat random picking by ${excess.toFixed(2)}% a trade, ` +
        "which is small enough that a few unlucky months would wipe it out. Worth watching " +
        "with pretend money; not worth believing yet.",
      warm: true,
    };
  }
  if (deflation && deflation.survives === false) {
    return {
      line:
        "It looks good, but no better than the best of several worthless strategies would " +
        "look by luck alone. Testing it with pretend money is how you find out which it is.",
      warm: true,
    };
  }
  return {
    line:
      `It cleared every check in testing across ${trades.toLocaleString()} trades. That is a ` +
      "reason to watch it with pretend money for a few years — not a reason to trust it. " +
      "Backtests have historically told you almost nothing about what happens next.",
    warm: true,
  };
}

export function PromoteFlow({ strategy }: { strategy: StrategyDetail }) {
  const promote = usePromote();
  const { prose } = useGlossary();
  const [confirming, setConfirming] = useState(false);
  const [note, setNote] = useState("");

  const backtest = strategy.backtest;
  const eligible = Boolean(backtest?.gate?.eligible_for_paper);
  const verdict = honestView(strategy);

  // ---- already running -------------------------------------------------
  if (strategy.stage !== "backtest") {
    const trading = strategy.status === "active";
    return (
      <div className="rounded-md border border-accent bg-accent/10 p-4">
        <p className="font-display text-base font-semibold">
          {trading ? "This is trading pretend money now" : "Promoted, but paused"}
        </p>
        <p className="mt-1 text-sm leading-relaxed">
          {trading ? (
            <>
              It has £100,000 of pretend money and buys and sells according to its own rules.
              No real money is involved anywhere.{" "}
              {strategy.trades.length === 0
                ? "Its first trades will appear after the next overnight run — tomorrow at about 7am UK time."
                : `It has made ${strategy.trades.length} trades so far.`}
            </>
          ) : (
            <>It has been promoted but is not currently trading. Nothing is being bought or sold.</>
          )}
        </p>
        <p className="mt-2 text-xs text-text-muted">
          What happens next: every weeknight Prism updates the data, works out what this
          strategy wants to own, and fills those orders at the next morning's opening price.
          Come back in a few years — that is genuinely how long it takes to mean anything.
        </p>
      </div>
    );
  }

  // ---- not eligible ----------------------------------------------------
  if (!eligible) {
    return (
      <div className="rounded-md border border-border p-4">
        <p className="font-display text-base font-semibold">
          Not ready for pretend money yet
        </p>
        <p className="mt-1 text-sm leading-relaxed">{prose(verdict.line)}</p>
        <p className="mt-2 text-xs text-text-muted">
          Prism will not let this one start trading, even pretend money, because it did not
          pass the tests below. That is deliberate.
        </p>
      </div>
    );
  }

  // ---- the actual flow -------------------------------------------------
  if (!confirming) {
    return (
      <div className="rounded-md border border-accent p-4">
        <p className="font-display text-base font-semibold">Ready for pretend money</p>
        <p className="mt-1 text-sm leading-relaxed">{prose(verdict.line)}</p>
        <button
          type="button"
          onClick={() => setConfirming(true)}
          className="mt-3 rounded border border-accent bg-accent px-4 py-2 text-sm font-medium text-surface"
        >
          Put this to work with pretend money
        </button>
      </div>
    );
  }

  const overall = backtest?.overall ?? {};
  const span = windowLabel(backtest?.window?.start, backtest?.window?.end);

  return (
    <div className="rounded-md border border-accent p-4">
      <h3 className="font-display text-base font-semibold">
        Before you start it: here is exactly what happens
      </h3>

      <ol className="mt-2 space-y-1.5 text-sm leading-relaxed">
        <li>
          <span className="font-medium">1.</span> This strategy gets{" "}
          <strong>£100,000 of pretend money</strong>. No real money is involved, anywhere.
          Prism cannot place a real order — it has no connection to a broker.
        </li>
        <li>
          <span className="font-medium">2.</span> Starting <strong>tomorrow at about 7am</strong>{" "}
          UK time, it will buy and sell shares according to its own written rules, at the
          real opening prices of the day.
        </li>
        <li>
          <span className="font-medium">3.</span> You will see every trade it makes and the
          exact rule that caused it. You can pause it at any time.
        </li>
      </ol>

      <div className="mt-3 border-t border-border pt-3">
        <p className="text-[11px] font-medium uppercase tracking-wide text-text-muted">
          What it believes
        </p>
        <p className="mt-0.5 text-sm leading-relaxed">{prose(strategy.hypothesis)}</p>
      </div>

      <div className="mt-3 border-t border-border pt-3">
        <p className="text-[11px] font-medium uppercase tracking-wide text-text-muted">
          How it did in testing
        </p>
        <p className="mt-0.5 text-sm leading-relaxed">
          Tested over {span || "the available history"} against the companies that were
          genuinely in the index at each date, including those that later went bust.{" "}
          {explainPerTrade(overall.mean_trade_return_pct)}.{" "}
          {explainEdge(backtest?.excess_over_drift_pct, overall.round_trips)}{" "}
          At its worst, {explainDrawdown(overall.max_drawdown_pct)}.
        </p>
      </div>

      <div className="mt-3 border-t border-border pt-3">
        <p className="text-[11px] font-medium uppercase tracking-wide text-text-muted">
          My honest view
        </p>
        <p className="mt-0.5 text-sm leading-relaxed">{prose(verdict.line)}</p>
        <p className="mt-1 text-sm leading-relaxed text-text-muted">
          {backtest?.track_record_verdict
            ? prose(backtest.track_record_verdict)
            : "There is no live record yet, so nothing here has been proved outside testing."}
        </p>
      </div>

      <label className="mt-3 block">
        <span className="text-[11px] font-medium uppercase tracking-wide text-text-muted">
          Why are you starting it? (kept permanently)
        </span>
        <input
          value={note}
          onChange={(event) => setNote(event.target.value)}
          placeholder="e.g. I want to see whether the value screens hold up live"
          className="mt-1 w-full rounded border border-border bg-surface px-2 py-1.5 text-sm"
        />
      </label>

      <div className="mt-3 flex flex-wrap gap-2">
        <button
          type="button"
          disabled={promote.isPending}
          onClick={() =>
            promote.mutate(
              { id: strategy.strategy_id, stage: "paper", note: note || undefined },
              { onSuccess: () => markDone("promoted_strategy") },
            )
          }
          className="rounded border border-accent bg-accent px-4 py-2 text-sm font-medium text-surface disabled:opacity-40"
        >
          {promote.isPending ? "Starting…" : "Yes — start it with pretend money"}
        </button>
        <button
          type="button"
          onClick={() => setConfirming(false)}
          className="rounded border border-border px-4 py-2 text-sm"
        >
          Not yet
        </button>
      </div>
      {promote.error && (
        <p className="mt-2 text-sm text-negative">{promote.error.message}</p>
      )}
    </div>
  );
}
