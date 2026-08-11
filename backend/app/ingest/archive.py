"""Raw response archive.

Every provider response is stored verbatim before anything reads it. Parsing
then runs against the archive, so a parser bug is fixed and re-run without
spending another call — and the original evidence of what the provider
actually said is never overwritten by our interpretation of it.
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Identity, Text, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class RawResponse(Base):
    __tablename__ = "raw_responses"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    ticker: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    payload: Mapped[object] = mapped_column(JSONB, nullable=False)


async def archive(
    session: AsyncSession,
    provider: str,
    endpoint: str,
    ticker: str | None,
    payload: object,
) -> RawResponse:
    """Store a response verbatim and return the row."""
    row = RawResponse(
        provider=provider, endpoint=endpoint, ticker=ticker, payload=payload
    )
    session.add(row)
    await session.flush()
    return row


async def latest(
    session: AsyncSession, provider: str, endpoint: str, ticker: str | None
) -> RawResponse | None:
    """Most recent archived response for this provider/endpoint/ticker."""
    return (
        await session.execute(
            select(RawResponse)
            .where(
                RawResponse.provider == provider,
                RawResponse.endpoint == endpoint,
                RawResponse.ticker == ticker,
            )
            .order_by(RawResponse.fetched_at.desc(), RawResponse.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
