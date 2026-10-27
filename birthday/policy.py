import calendar
import re
from datetime import date


def parse_birthday(value):
    """Accept an unambiguous month/day, including February 29."""
    match = re.fullmatch(r"\s*(\d{1,2})\s*/\s*(\d{1,2})\s*", value)
    if not match:
        raise ValueError("Use MM/DD, for example 07/24. Do not enter a year.")
    month, day = map(int, match.groups())
    try:
        date(2000, month, day)
    except ValueError:
        raise ValueError("Please enter a valid month and day.") from None
    return month, day


def is_due(birthday, today):
    month, day = birthday["month"], birthday["day"]
    if (month, day) == (2, 29) and not calendar.isleap(today.year):
        month, day = 2, 28
    return (today.month, today.day) == (month, day) and birthday.get("last_year") != today.year


def render_message(template, member):
    # Replace only the supported token; ordinary braces are safe.
    text = template.replace("{member}", member.mention)
    if "{member}" not in template:
        text = f"{member.mention} {text}"
    return text
