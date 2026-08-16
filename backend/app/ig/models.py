"""IG projections. Disposable read models over the IG event streams."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, Numeric, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class IGAccount(Base):
    __tablename__ = "ig_accounts"

    account_id: Mapped[str] = mapped_column(Text, primary_key=True)
    type: Mapped[str]
    regime: Mapped[str]
    label: Mapped[str | None]
    currency: Mapped[str | None]
    is_preferred: Mapped[bool] = mapped_column(Boolean, server_default=func.false())
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class IGEpicMap(Base):
    __tablename__ = "ig_epic_map"

    epic: Mapped[str] = mapped_column(Text, primary_key=True)
    ticker: Mapped[str | None]
    instrument_name: Mapped[str | None]
    instrument_type: Mapped[str | None]
    kind: Mapped[str]
    option_right: Mapped[str | None]
    option_strike: Mapped[Decimal | None] = mapped_column(Numeric)
    option_expiry: Mapped[date | None] = mapped_column(Date)
    underlying_ticker: Mapped[str | None]
    needs_review: Mapped[bool] = mapped_column(Boolean, server_default=func.true())
    mapped_by: Mapped[str | None]
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class IGPosition(Base):
    __tablename__ = "ig_positions"

    deal_id: Mapped[str] = mapped_column(Text, primary_key=True)
    account_id: Mapped[str]
    epic: Mapped[str]
    direction: Mapped[str]
    size: Mapped[Decimal] = mapped_column(Numeric)
    open_level: Mapped[Decimal | None] = mapped_column(Numeric)
    current_level: Mapped[Decimal | None] = mapped_column(Numeric)
    currency: Mapped[str | None]
    stop_level: Mapped[Decimal | None] = mapped_column(Numeric)
    limit_level: Mapped[Decimal | None] = mapped_column(Numeric)
    contract_size: Mapped[Decimal | None] = mapped_column(Numeric)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expiry: Mapped[str | None]
    instrument_type: Mapped[str | None]
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_event_id: Mapped[int]


class OptionPosition(Base):
    __tablename__ = "option_positions"

    deal_id: Mapped[str] = mapped_column(Text, primary_key=True)
    account_id: Mapped[str]
    epic: Mapped[str]
    underlying_ticker: Mapped[str | None]
    right: Mapped[str]
    strike: Mapped[Decimal] = mapped_column(Numeric)
    expiry: Mapped[date] = mapped_column(Date)
    contracts: Mapped[Decimal] = mapped_column(Numeric)
    direction: Mapped[str]
    multiplier: Mapped[Decimal] = mapped_column(Numeric, server_default="100")
    premium: Mapped[Decimal | None] = mapped_column(Numeric)
    currency: Mapped[str | None]
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    iv_at_entry: Mapped[Decimal | None] = mapped_column(Numeric)
    iv_estimated: Mapped[bool] = mapped_column(Boolean, server_default=func.true())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OptionMark(Base):
    __tablename__ = "option_marks"

    deal_id: Mapped[str] = mapped_column(Text, primary_key=True)
    as_of: Mapped[date] = mapped_column(Date, primary_key=True)
    mark: Mapped[Decimal] = mapped_column(Numeric)
    underlying_price: Mapped[Decimal | None] = mapped_column(Numeric)
    implied_vol: Mapped[Decimal | None] = mapped_column(Numeric)
    iv_estimated: Mapped[bool] = mapped_column(Boolean, server_default=func.true())
    delta: Mapped[Decimal | None] = mapped_column(Numeric)
    theta_per_day: Mapped[Decimal | None] = mapped_column(Numeric)


class IGBalance(Base):
    __tablename__ = "ig_balances"

    account_id: Mapped[str] = mapped_column(Text, primary_key=True)
    as_of: Mapped[date] = mapped_column(Date, primary_key=True)
    balance: Mapped[Decimal | None] = mapped_column(Numeric)
    deposit: Mapped[Decimal | None] = mapped_column(Numeric)
    profit_loss: Mapped[Decimal | None] = mapped_column(Numeric)
    available: Mapped[Decimal | None] = mapped_column(Numeric)


class FundingAccrual(Base):
    __tablename__ = "funding_accruals"

    deal_id: Mapped[str] = mapped_column(Text, primary_key=True)
    as_of: Mapped[date] = mapped_column(Date, primary_key=True)
    notional: Mapped[Decimal] = mapped_column(Numeric)
    annual_rate_pct: Mapped[Decimal] = mapped_column(Numeric)
    charge: Mapped[Decimal] = mapped_column(Numeric)
    currency: Mapped[str | None]
    estimated: Mapped[bool] = mapped_column(Boolean, server_default=func.true())


class IGReconciliation(Base):
    __tablename__ = "ig_reconciliation"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[str]
    kind: Mapped[str]
    deal_id: Mapped[str | None]
    epic: Mapped[str | None]
    ticker: Mapped[str | None]
    prism_stream_id: Mapped[object | None] = mapped_column(UUID(as_uuid=True))
    detail: Mapped[dict] = mapped_column(JSONB)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric)
    status: Mapped[str] = mapped_column(Text, server_default="pending")
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class IGClosedTrade(Base):
    """A trade IG has already closed, from its transaction history."""

    __tablename__ = "ig_closed_trades"

    reference: Mapped[str] = mapped_column(Text, primary_key=True)
    account_id: Mapped[str]
    instrument_name: Mapped[str | None]
    ticker: Mapped[str | None]
    kind: Mapped[str] = mapped_column(Text, server_default="unknown")
    direction: Mapped[str | None]
    size: Mapped[Decimal | None] = mapped_column(Numeric)
    open_level: Mapped[Decimal | None] = mapped_column(Numeric)
    close_level: Mapped[Decimal | None] = mapped_column(Numeric)
    profit_loss: Mapped[Decimal | None] = mapped_column(Numeric)
    currency: Mapped[str | None]
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    days_held: Mapped[int | None]
    option_right: Mapped[str | None]
    option_strike: Mapped[Decimal | None] = mapped_column(Numeric)
