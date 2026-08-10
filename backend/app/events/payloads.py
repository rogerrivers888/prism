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
    side: Literal["buy", "sell"]
    quantity: Decimal
    price: Decimal
    currency: str = "GBP"


class StopMoved(_Payload):
    event_type: Literal["StopMoved"] = "StopMoved"
    instrument: str
    previous_stop: Decimal | None = None
    new_stop: Decimal


EventPayload = Annotated[
    Union[TradeExecuted, StopMoved],
    Field(discriminator="event_type"),
]

payload_adapter: TypeAdapter[EventPayload] = TypeAdapter(EventPayload)
