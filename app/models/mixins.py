"""Shared model mixins and small helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from ..extensions import db


def utcnow() -> datetime:
    """Current time as naive UTC (the database stores UTC)."""
    return datetime.now(UTC).replace(tzinfo=None)


def to_decimal(value: object) -> Decimal:
    """Coerce a value to :class:`decimal.Decimal`, treating ``None`` as zero.

    Database aggregates (``SUM``, ``CASE`` expressions) may surface as ``float``
    on SQLite; this normalizes them back to exact ``Decimal`` values so money is
    never handled as floating point.
    """
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


class TimestampMixin:
    """Adds ``created_at`` / ``updated_at`` columns to a model."""

    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )
