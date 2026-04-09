from __future__ import annotations

from datetime import datetime, timedelta, timezone


UTC = timezone.utc



def current_minute_key(now: datetime | None = None) -> str:
    now = (now or datetime.now(UTC)).astimezone(UTC)
    return now.replace(second=0, microsecond=0).isoformat()



def previous_minute_key(now: datetime | None = None) -> str:
    now = (now or datetime.now(UTC)).astimezone(UTC).replace(second=0, microsecond=0)
    return (now - timedelta(minutes=1)).isoformat()



def points_to_level(total_points: int, points_per_level: int) -> int:
    if points_per_level <= 0:
        return 0
    return total_points // points_per_level



def seconds_until_next_minute(now: datetime | None = None) -> float:
    now = (now or datetime.now(UTC)).astimezone(UTC)
    next_minute = (now + timedelta(minutes=1)).replace(second=0, microsecond=0)
    return max((next_minute - now).total_seconds(), 0.25)
