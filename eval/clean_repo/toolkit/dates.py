"""Date and duration helpers."""

from datetime import date, timedelta


def days_between(start: date, end: date) -> int:
    """Number of days from `start` to `end` (negative if `end` is earlier)."""
    return (end - start).days


def is_leap_year(year: int) -> bool:
    """True for leap years in the Gregorian calendar."""
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def add_business_days(start: date, days: int) -> date:
    """Move forward `days` working days, skipping Saturdays and Sundays."""
    if days < 0:
        raise ValueError("days must not be negative")
    current = start
    remaining = days
    while remaining > 0:
        current += timedelta(days=1)
        if current.weekday() < 5:
            remaining -= 1
    return current


def format_duration(seconds: int) -> str:
    """Format seconds as '1h 02m 03s'. The hours part is left out when it is zero."""
    if seconds < 0:
        raise ValueError("seconds must not be negative")
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    return f"{minutes}m {secs:02d}s"
