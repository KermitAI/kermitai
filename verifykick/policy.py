from datetime import timedelta
import re


def parse_duration(value):
    """Parse a whole-number duration from 1 minute through 365 days."""
    match = re.fullmatch(r"([0-9]{1,9})([mhd])", value.strip(), re.IGNORECASE)
    if match is None:
        raise ValueError("Use a whole number followed by m, h, or d, such as 3m, 1h, or 5d.")
    seconds = int(match[1]) * {"m": 60, "h": 3600, "d": 86400}[match[2].lower()]
    if not 60 <= seconds <= 365 * 86400:
        raise ValueError("Choose a duration from 1 minute to 365 days.")
    return seconds


def waiting_seconds(settings):
    """Preserve existing day-based configurations without resetting deadlines."""
    seconds = settings.get("time_seconds")
    return seconds if seconds is not None else settings.get("days", 7) * 86400


def format_duration(seconds):
    for unit, size in (("day", 86400), ("hour", 3600), ("minute", 60)):
        if seconds % size == 0:
            amount = seconds // size
            return f"{amount} {unit}{'' if amount == 1 else 's'}"


def is_due(member, role_id, seconds, enabled_at, now):
    """Check cached eligibility; the caller must refresh before kicking."""
    if member.bot or member.id == member.guild.owner_id:
        return False
    if member.guild_permissions.administrator or member.joined_at is None:
        return False
    if any(role.id == role_id for role in member.roles):
        return False
    me = member.guild.me
    if me is None or not me.guild_permissions.kick_members:
        return False
    if member.top_role >= me.top_role:
        return False
    return now >= max(member.joined_at, enabled_at) + timedelta(seconds=seconds)
