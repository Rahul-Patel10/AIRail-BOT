from __future__ import annotations

from datetime import datetime, timedelta
import re

DAY_NAMES = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

RELATIVE_DATES = {
    "today": 0,
    "tomorrow": 1,
    "day after tomorrow": 2,
    "after tomorrow": 2,
}

TIME_KEYWORDS = {
    "morning": "06:00",
    "early morning": "05:00",
    "afternoon": "12:00",
    "evening": "17:00",
    "night": "20:00",
    "late night": "22:00",
    "noon": "12:00",
    "midnight": "00:00",
}


def _next_weekday(day_name: str) -> str:
    today = datetime.today()
    target = DAY_NAMES.get(day_name.lower())
    if target is None:
        return today.strftime("%d-%m-%Y")
    days_ahead = (target - today.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return (today + timedelta(days=days_ahead)).strftime("%d-%m-%Y")


def normalize_date_text(date_str: str | None) -> str | None:
    if not date_str:
        return None

    value = str(date_str).strip().lower()
    if not value:
        return None

    if value in RELATIVE_DATES:
        return (datetime.today() + timedelta(days=RELATIVE_DATES[value])).strftime("%d-%m-%Y")

    if value.startswith("next "):
        return _next_weekday(value[5:].strip())

    if value in DAY_NAMES:
        return _next_weekday(value)

    if value in {"day after tomorrow", "after tomorrow"}:
        return (datetime.today() + timedelta(days=2)).strftime("%d-%m-%Y")

    try:
        datetime.strptime(value, "%d-%m-%Y")
        return value
    except ValueError:
        pass

    return value


def normalize_time_text(time_str: str | None) -> str | None:
    if not time_str:
        return None

    value = str(time_str).strip().lower()
    if not value:
        return None

    if value in TIME_KEYWORDS:
        return TIME_KEYWORDS[value]

    if re.fullmatch(r"\d{1,2}:\d{2}", value):
        parts = value.split(":")
        hour = int(parts[0])
        minute = int(parts[1])
        return f"{hour:02d}:{minute:02d}"

    if re.fullmatch(r"\d{1,2}", value):
        return f"{int(value):02d}:00"

    match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)", value)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2) or "0")
        if match.group(3) == "pm" and hour != 12:
            hour += 12
        if match.group(3) == "am" and hour == 12:
            hour = 0
        return f"{hour:02d}:{minute:02d}"

    for fmt in ["%I %p", "%I%p", "%I:%M %p", "%I:%M%p"]:
        try:
            return datetime.strptime(value, fmt).strftime("%H:%M")
        except ValueError:
            continue

    return value
