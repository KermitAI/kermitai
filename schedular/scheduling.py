"""Schedule validation and DST-aware daily occurrence calculation."""
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def interval(value):
    match = re.fullmatch(r"\s*(\d+)\s*(minutes?|hours?|days?|weeks?)\s*", value.lower())
    if not match:
        raise ValueError("Use whole minutes, hours, days or weeks, e.g. 15 minutes or 2 hours.")
    seconds = int(match[1]) * {"minute": 60, "hour": 3600, "day": 86400, "week": 604800}[match[2].rstrip("s")]
    if seconds < 900:
        raise ValueError("The minimum interval is 15 minutes.")
    if seconds > 31536000:
        raise ValueError("The maximum interval is 365 days.")
    return seconds


def daily_times(value):
    parts = [part.strip() for part in value.split(",")]
    if not parts or any(not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", part) for part in parts):
        raise ValueError("Use 24-hour times separated by commas, e.g. 09:00, 17:30.")
    minutes = sorted({int(part[:2]) * 60 + int(part[3:]) for part in parts})
    if len(minutes) != len(parts):
        raise ValueError("Each daily time must be unique.")
    if min((minutes[(i + 1) % len(minutes)] - minute) % 1440 or 1440 for i, minute in enumerate(minutes)) < 15:
        raise ValueError("Daily times must be at least 15 minutes apart, including across midnight.")
    return [f"{minute // 60:02}:{minute % 60:02}" for minute in minutes]


def zone(value):
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("Use an IANA timezone such as America/Toronto, Europe/London or UTC.") from None


def next_run(schedule, now):
    if schedule["mode"] == "interval":
        return now + schedule["interval"]
    tz = zone(schedule["timezone"])
    today = datetime.fromtimestamp(now, tz).date()
    candidates = []
    for offset in range(4):
        day = today + timedelta(days=offset)
        for value in schedule["times"]:
            hour, minute = map(int, value.split(":"))
            local = datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)
            stamp = local.timestamp()
            # Skip nonexistent spring-forward times; use the first fall-back occurrence only.
            if datetime.fromtimestamp(stamp, tz).replace(tzinfo=None) != local.replace(tzinfo=None):
                continue
            if stamp > now:
                candidates.append(stamp)
    return min(candidates)
