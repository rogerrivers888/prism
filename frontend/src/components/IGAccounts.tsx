import { Link } from "react-router-dom";
import { useIGBook, type AccountBook, type IGOption } from "../api/ig";
import { useGlossary } from "./GlossaryProvider";
import { NothingYet } from "./PagePurpose";

/** The IG book: two accounts, two regimes, deliberately never added together.
 *
 *  A pension and a leveraged spread bet account are different kinds of money.
 *  One cannot lose more than it holds; the other can, and is charged interest
 *  every night on the full position value. A single combined figure at the top
 *  would hide precisely the thing worth knowing, so there isn't one.
 */

const currency = (value: number | null | undefined, code = "GBP") => {
  if (value === null || value === undefined) return "—";
  const symbol = code === "USD" ? "$" : code === "EUR" ? "€" : "£";
  return `${value < 0 ? "−" : ""}${symbol}${Math.abs(value).toLocaleString(undefined, {
    maximumFractionDigits: 0,
  })}`;
};

function OptionCard({ option }: { option: IGOption }) {
  const { prose } = useGlossary();
  const soon = option.days_left <= 21;

  return (
    <li className="border-b border-border/60 py-4">
      <div className="flex flex-wrap items-baseline gap-x-2">
        {option.underlying ? (
          <Link to={`/company/${option.underlying}`} className="text-sm font-medium hover:underline">
            {option.underlying}
          </Link>
        ) : (
          <span className="text-sm font-medium">Unrecognised underlying</span>
        )}
        <span className="tabular text-sm">
          {option.right} at {currency(option.strike, option.currency)}
        </span>
        <span className={`text-xs ${soon ? "text-warning" : "text-text-muted"}`}>
          expires {option.expiry} — {option.days_left} days left
        </span>
        {option.direction === "short" && (
          <span className="rounded border border-warning px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-warning">
            written — uncapped risk
          </span>
        )}
      </div>

      {/* The four numbers, always, in this order: what has to happen, what it
          costs to wait, how hard it swings, and what you can lose. */}
      <div className="mt-2 space-y-1.5 text-sm leading-relaxed">
        <p className="font-medium">{prose(option.breakeven_line)}</p>
        <p className="text-text-muted">{prose(option.decay_line)}</p>
        <p className="text-text-muted">{prose(option.leverage_line)}</p>
        <p
          className={
            option.direction === "short"
              ? "font-medium text-warning"
              : "text-text-muted"
          }
        >
          {prose(option.max_loss_line)}
        </p>
        <p className="text-text-muted">{prose(option.probability_line)}</p>
      </div>

      {option.earnings_warning && (
        <p className="mt-2 border-l-2 border-warning bg-warning/10 px-3 py-2 text-sm leading-relaxed">
          {prose(option.earnings_warning)}
        </p>
      )}

      <dl className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-xs text-text-muted">
        <div>
          <dt className="inline">Paid: </dt>
          <dd className="tabular inline">{currency(option.premium_paid, option.currency)}</dd>
        </div>
        <div>
          <dt className="inline">Worth now: </dt>
          <dd className="tabular inline">{currency(option.position_value, option.currency)}</dd>
        </div>
        {option.implied_volatility !== null && (
          <div>
            <dt className="inline">Volatility priced in: </dt>
            <dd className="tabular inline">
              {(option.implied_volatility * 100).toFixed(0)}%
              {option.iv_estimated && (
                <span className="ml-1 text-[10px] uppercase">estimated</span>
              )}
            </dd>
          </div>
        )}
      </dl>
    </li>
  );
}

function AccountSection({ book }: { book: AccountBook }) {
  const { prose } = useGlossary();
  const { account } = book;
  const leveraged = account.regime === "leveraged";
  const code = account.currency ?? "GBP";
  const shares = book.positions.filter((p) => p.kind !== "option");

  return (
    <section className="rounded-md border border-border p-4">
      <header className="flex flex-wrap items-baseline gap-x-3">
        <h2 className="font-display text-lg font-semibold">
          {account.label ?? account.account_id}
        </h2>
        <span className="rounded border border-border px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-text-muted">
          {leveraged ? "borrowed money" : "your own money only"}
        </span>
      </header>

      <p className="mt-1 text-sm leading-relaxed text-text-muted">
        {prose(book.cost_of_ownership_note)}
      </p>

      <dl className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div>
          <dt className="text-[11px] uppercase tracking-wide text-text-muted">In the account</dt>
          <dd className="tabular text-sm">{currency(account.balance, code)}</dd>
        </div>
        {leveraged && (
          <>
            <div>
              <dt className="text-[11px] uppercase tracking-wide text-text-muted">
                Held as margin
              </dt>
              <dd className="tabular text-sm">{currency(account.margin_used, code)}</dd>
              <p className="mt-0.5 text-[11px] leading-relaxed text-text-muted">
                What IG is holding to keep these positions open.
              </p>
            </div>
            <div>
              <dt className="text-[11px] uppercase tracking-wide text-text-muted">
                Total position value
              </dt>
              <dd className="tabular text-sm">{currency(book.total_notional, code)}</dd>
              <p className="mt-0.5 text-[11px] leading-relaxed text-text-muted">
                {book.exposure_to_margin
                  ? `You are controlling ${book.exposure_to_margin}× the money you put up.`
                  : "The value you are exposed to, not what you paid."}
              </p>
            </div>
            <div>
              <dt className="text-[11px] uppercase tracking-wide text-text-muted">
                Paid to IG in interest this year
              </dt>
              <dd className="tabular text-sm">
                {currency(book.funding_paid_this_year, code)}
              </dd>
              <p className="mt-0.5 text-[11px] leading-relaxed text-text-muted">
                Charged nightly on the full value, win or lose.
              </p>
            </div>
          </>
        )}
      </dl>

      {shares.length > 0 && (
        <div className="mt-4">
          <h3 className="text-[11px] font-medium uppercase tracking-wide text-text-muted">
            Positions
          </h3>
          <ul className="mt-1 divide-y divide-border border-y border-border">
            {shares.map((position) => (
              <li key={position.deal_id} className="py-2 text-sm">
                <div className="flex flex-wrap items-baseline gap-x-2">
                  {position.ticker ? (
                    <Link to={`/company/${position.ticker}`} className="font-medium hover:underline">
                      {position.ticker}
                    </Link>
                  ) : (
                    <span className="font-medium">{position.name ?? position.epic}</span>
                  )}
                  <span className="text-xs text-text-muted">
                    {position.direction === "BUY" ? "betting it rises" : "betting it falls"} ·{" "}
                    {currency(position.notional, position.currency ?? code)} of exposure
                  </span>
                  {position.needs_mapping && (
                    <span className="text-[10px] uppercase tracking-wide text-warning">
                      not linked to a company Prism tracks
                    </span>
                  )}
                </div>
                {/* Funding beside the position, at the same weight as its value —
                    it is the number that decides whether a months-long hold works. */}
                {position.funding_per_month !== null && (
                  <p className="mt-0.5 text-xs leading-relaxed text-text-muted">
                    Interest: {currency(position.funding_paid_to_date, code)} paid so far,
                    about {currency(position.funding_per_month, code)} a month from here.
                    Holding it for another three months would cost roughly{" "}
                    <strong>{currency(position.funding_projected, code)}</strong> in interest
                    alone, before the price does anything.
                  </p>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {book.options.length > 0 && (
        <div className="mt-4">
          <h3 className="text-[11px] font-medium uppercase tracking-wide text-text-muted">
            Option contracts
          </h3>
          <ul className="mt-1 border-t border-border">
            {book.options.map((option) => (
              <OptionCard key={option.deal_id} option={option} />
            ))}
          </ul>
        </div>
      )}

      {shares.length === 0 && book.options.length === 0 && (
        <p className="mt-3 text-sm text-text-muted">
          Nothing open in this account.
        </p>
      )}
    </section>
  );
}

export function IGAccounts() {
  const { data, isLoading, error } = useIGBook();
  const { prose } = useGlossary();

  if (isLoading) return <p className="text-sm text-text-muted">Loading your IG accounts…</p>;
  if (error) return <p className="text-sm text-negative">{(error as Error).message}</p>;
  if (!data || data.accounts.length === 0) {
    return (
      <NothingYet
        headline="No IG accounts connected yet"
        because="Prism reads your IG accounts overnight. If this stays empty, the IG credentials are not set on the server. Prism can only ever read from IG — it cannot place, change or close a trade."
      />
    );
  }

  return (
    <div className="space-y-4">
      <p className="border-l-2 border-border pl-3 text-sm leading-relaxed text-text-muted">
        {prose(data.blended_total_note)}
      </p>

      {(data.unmapped_epics > 0 || data.pending_reconciliation > 0) && (
        <div className="rounded border border-border bg-surface-sunken p-3 text-sm">
          {data.pending_reconciliation > 0 && (
            <p>
              <strong>{data.pending_reconciliation}</strong> position
              {data.pending_reconciliation === 1 ? "" : "s"} need
              {data.pending_reconciliation === 1 ? "s" : ""} your review — IG and Prism
              disagree about what you hold.{" "}
              <Link to="/reconciliation" className="underline">
                Review them
              </Link>
              .
            </p>
          )}
          {data.unmapped_epics > 0 && (
            <p className="mt-1 text-text-muted">
              {data.unmapped_epics} instrument{data.unmapped_epics === 1 ? "" : "s"} could not
              be linked to a company Prism tracks, so they have no scores attached. They are
              still shown; nothing was guessed.
            </p>
          )}
        </div>
      )}

      {data.accounts.map((book) => (
        <AccountSection key={book.account.account_id} book={book} />
      ))}

      {data.last_sync && (
        <p className="text-xs text-text-muted">
          Last read from IG: {new Date(data.last_sync).toLocaleString()}. Prism reads
          overnight and a few times during the trading day.
        </p>
      )}
    </div>
  );
}
