"""Local time for the owner: Philippine time (UTC+8, no daylight saving)."""
from datetime import date, datetime, timedelta, timezone

PHT = timezone(timedelta(hours=8), "PHT")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def now() -> datetime:
    """Naive local datetime in Philippine time, to the second."""
    return _utcnow().astimezone(PHT).replace(tzinfo=None, microsecond=0)


def today() -> date:
    return now().date()
