"""Event payload models.

Payloads form a discriminated union on ``event_type`` so an unknown type is
rejected at write time rather than silently stored as an opaque blob.
"""

from decimal import Decimal
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TradeExecuted(_Payload):
    event_type: Literal["TradeExecuted"] = "TradeExecuted"
    instrument: str
    # Spread bets, options and shares need different maths for everything
    # downstream; this must be captured at write time, not inferred later.
    instrument_type: Literal["spreadbet", "option", "share"]
    side: Literal["buy", "sell"]
    quantity: Decimal
    price: Decimal
    currency: str = "GBP"
    # Stop attached to the order, if any. On the opening trade this is the
    # only place initial_risk (R) can come from — R is defined at entry.
    stop: Decimal | None = None
    # Which sleeve this position is bought for. An operator decision made at
    # entry, never inferred from the numbers, because it determines the exit
    # discipline: price stops for growth, time and thesis stops for value.
    sleeve: Literal["high_growth", "deeply_undervalued"] | None = None


class StopMoved(_Payload):
    event_type: Literal["StopMoved"] = "StopMoved"
    instrument: str
    previous_stop: Decimal | None = None
    new_stop: Decimal


class StreamVoided(_Payload):
    """Supersedes an entire stream — e.g. events too malformed to project.

    The ledger is append-only, so bad history is never edited or deleted;
    it is voided by a later event that says so, and why.
    """

    event_type: Literal["StreamVoided"] = "StreamVoided"
    reason: str


class WatchlistAdded(_Payload):
    event_type: Literal["WatchlistAdded"] = "WatchlistAdded"
    ticker: str
    note: str | None = None


class WatchlistRemoved(_Payload):
    event_type: Literal["WatchlistRemoved"] = "WatchlistRemoved"
    ticker: str


class DecisionRaised(_Payload):
    """A candidate action, recorded before it is acted on.

    thesis, premortem and falsifier are required: a decision you cannot state
    a failure mode for is not one you can learn from afterwards.
    """

    event_type: Literal["DecisionRaised"] = "DecisionRaised"
    ticker: str | None = None
    kind: Literal["buy", "sell", "trim", "add", "hold"]
    thesis: str
    premortem: str
    falsifier: str
    sizing_note: str | None = None


class DecisionTaken(_Payload):
    event_type: Literal["DecisionTaken"] = "DecisionTaken"
    note: str | None = None


class DecisionDeclined(_Payload):
    event_type: Literal["DecisionDeclined"] = "DecisionDeclined"
    reason: str


class DecisionClosed(_Payload):
    """Decision quality and outcome quality are judged separately.

    A good decision can have a bad outcome. Collapsing the two is how a
    process gets rewritten by luck.
    """

    event_type: Literal["DecisionClosed"] = "DecisionClosed"
    decision_quality: Literal["good", "bad"]
    outcome_quality: Literal["good", "bad", "neutral"]
    error_tag: Literal[
        "analytical", "informational", "behavioural", "sizing", "timing", "none"
    ]
    note: str | None = None


class StrategyRegistered(_Payload):
    """A strategy exists from the moment it is written down — before any
    backtest runs. Prediction first, evidence second, so the evidence can
    never quietly rewrite the prediction."""

    event_type: Literal["StrategyRegistered"] = "StrategyRegistered"
    name: str
    # What it believes and WHY it should work, in plain English.
    hypothesis: str
    # Who this derives from: "Piotroski 2000", "Roger's idea, 2026-08-12".
    authority: str
    citation: str | None = None
    # The executable rule-set, validated against the rule vocabulary at
    # registration. JSON the engine runs, not prose.
    rules: dict
    horizon: Literal["short", "medium", "long"]
    expected_trade_frequency: str
    expected_holding_period: str
    # Written down before testing. The backtest then confirms or embarrasses.
    predicted_performance: str
    # Tweaks are new strategies with lineage; the family counts as multiple
    # trials in any deflation maths.
    parent_strategy_id: str | None = None
    decay_note: str
    # Where the encoding had to deviate from the source (missing data, proxy
    # metrics), stated at registration rather than discovered later.
    encoding_deviations: str | None = None


class StrategyActivated(_Payload):
    event_type: Literal["StrategyActivated"] = "StrategyActivated"
    # Set when activation went ahead despite a duplicate flag; the override
    # is recorded, not silent.
    duplicate_override_note: str | None = None


class StrategyPaused(_Payload):
    event_type: Literal["StrategyPaused"] = "StrategyPaused"
    reason: str


class StrategyRetired(_Payload):
    event_type: Literal["StrategyRetired"] = "StrategyRetired"
    reason: str


class StrategyPromoted(_Payload):
    """backtest -> paper -> proven. Promotion is a human act: the engine can
    recommend it, only Roger can do it."""

    event_type: Literal["StrategyPromoted"] = "StrategyPromoted"
    stage: Literal["paper", "proven"]
    note: str | None = None


class PaperTradeExecuted(_Payload):
    """A fill in the paper book. Signal one day, fill at the NEXT day's open —
    a same-day-close fill would be trading on a price that had already gone."""

    event_type: Literal["PaperTradeExecuted"] = "PaperTradeExecuted"
    ticker: str
    side: Literal["buy", "sell"]
    quantity: Decimal
    price: Decimal
    currency: str = "GBP"
    spread_cost: Decimal
    commission: Decimal
    signal_date: str
    fill_date: str
    # Full traceability: the rule that fired and the metric values that
    # triggered it travel with the trade forever.
    rule_fired: str
    metric_values: dict


class IGPositionObserved(_Payload):
    """What IG reported for one position at one moment.

    An observation, not an instruction. occurred_at carries IG's own timestamp
    where it gives one, recorded_at is when Prism looked — the two must never
    be collapsed, because a position opened on Tuesday and first seen on
    Thursday is a different fact from one opened on Thursday.
    """

    event_type: Literal["IGPositionObserved"] = "IGPositionObserved"
    account_id: str
    deal_id: str
    epic: str
    direction: Literal["BUY", "SELL"]
    size: Decimal
    open_level: Decimal | None = None
    current_level: Decimal | None = None
    currency: str | None = None
    stop_level: Decimal | None = None
    limit_level: Decimal | None = None
    contract_size: Decimal | None = None
    instrument_type: str | None = None
    instrument_name: str | None = None
    # IG's expiry string: "-" for cash positions, "SEP-26" or a date for
    # dated products and options.
    expiry: str | None = None


class IGPositionClosed(_Payload):
    """IG stopped reporting a position we had seen.

    Recorded as its own event rather than by deleting a row: the ledger is
    append-only, and "gone from the feed" is an observation about IG, not
    proof of what happened.
    """

    event_type: Literal["IGPositionClosed"] = "IGPositionClosed"
    account_id: str
    deal_id: str
    last_seen: str


class IGTradeDetected(_Payload):
    """A transaction IG reports in its history."""

    event_type: Literal["IGTradeDetected"] = "IGTradeDetected"
    account_id: str
    reference: str
    epic: str | None = None
    instrument_name: str | None = None
    transaction_type: str | None = None
    size: Decimal | None = None
    open_level: Decimal | None = None
    close_level: Decimal | None = None
    profit_loss: Decimal | None = None
    currency: str | None = None
    cash_transaction: bool = False


class IGBalanceObserved(_Payload):
    event_type: Literal["IGBalanceObserved"] = "IGBalanceObserved"
    account_id: str
    balance: Decimal | None = None
    deposit: Decimal | None = None
    profit_loss: Decimal | None = None
    available: Decimal | None = None
    currency: str | None = None


class FundingCharged(_Payload):
    """Overnight funding on a leveraged position, computed by Prism.

    Explicitly estimated: IG bills its own figure and Prism does not receive
    it per-position. The number exists to make an invisible cost visible, and
    it is labelled as an estimate everywhere it appears.
    """

    event_type: Literal["FundingCharged"] = "FundingCharged"
    account_id: str
    deal_id: str
    as_of: str
    # The whole point: funding is charged on the full position value, not on
    # the margin actually put up.
    notional: Decimal
    annual_rate_pct: Decimal
    charge: Decimal
    currency: str | None = None
    estimated: bool = True


EventPayload = Annotated[
    Union[
        TradeExecuted,
        StopMoved,
        StreamVoided,
        WatchlistAdded,
        WatchlistRemoved,
        DecisionRaised,
        DecisionTaken,
        DecisionDeclined,
        DecisionClosed,
        StrategyRegistered,
        StrategyActivated,
        StrategyPaused,
        StrategyRetired,
        StrategyPromoted,
        PaperTradeExecuted,
        IGPositionObserved,
        IGPositionClosed,
        IGTradeDetected,
        IGBalanceObserved,
        FundingCharged,
    ],
    Field(discriminator="event_type"),
]

payload_adapter: TypeAdapter[EventPayload] = TypeAdapter(EventPayload)
