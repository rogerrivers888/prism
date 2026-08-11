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
    ],
    Field(discriminator="event_type"),
]

payload_adapter: TypeAdapter[EventPayload] = TypeAdapter(EventPayload)
