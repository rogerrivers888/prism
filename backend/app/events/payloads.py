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


EventPayload = Annotated[
    Union[TradeExecuted, StopMoved, StreamVoided],
    Field(discriminator="event_type"),
]

payload_adapter: TypeAdapter[EventPayload] = TypeAdapter(EventPayload)
