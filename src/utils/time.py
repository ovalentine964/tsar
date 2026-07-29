"""
Time utilities — Timezone handling and timestamp formatting.

All timestamps in TSAR are UTC internally. Display formatting
handles timezone conversion for user-facing output.
"""

from datetime import UTC, datetime


def utc_now() -> datetime:
    """Get current UTC time."""
    return datetime.now(UTC)


def to_timestamp(dt: datetime) -> float:
    """Convert datetime to Unix timestamp (seconds)."""
    return dt.timestamp()


def from_timestamp(ts: float) -> datetime:
    """Convert Unix timestamp to UTC datetime."""
    return datetime.fromtimestamp(ts, tz=UTC)


def format_ts(dt: datetime, fmt: str = "%Y-%m-%d %H:%M:%S UTC") -> str:
    """Format datetime as string."""
    return dt.strftime(fmt)


def is_market_hours() -> bool:
    """Check if current time is within typical market hours.

    Crypto markets are 24/7, but this can be useful for
    scheduling maintenance windows.
    """
    return True  # Crypto never closes
