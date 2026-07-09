"""
services/train_filter.py

Extracts simple time constraints from user text and filters train lists
by departure or arrival time.
"""

from __future__ import annotations

import re
from typing import Iterable

from utils.date_parser import normalize_time_text


_WINDOWS = {
    "early morning": ("05:00", "08:59"),
    "morning": ("05:00", "11:59"),
    "afternoon": ("12:00", "16:59"),
    "evening": ("17:00", "19:59"),
    "late night": ("22:00", "23:59"),
    "night": ("20:00", "23:59"),
    "noon": ("12:00", "12:30"),
}


def _to_minutes(time_str: str | None) -> int | None:
    if not time_str:
        return None

    value = normalize_time_text(time_str)
    if not value:
        return None

    match = re.fullmatch(r"(\d{2}):(\d{2})", value)
    if not match:
        return None

    hour = int(match.group(1))
    minute = int(match.group(2))
    if hour > 23 or minute > 59:
        return None
    return hour * 60 + minute


def _pick_time(train: dict) -> str | None:
    departure = train.get("departure")
    arrival = train.get("arrival")
    if departure and departure != "--:--":
        return departure
    if arrival and arrival != "--:--":
        return arrival
    return None


def _match_window(train_minutes: int, start_minutes: int, end_minutes: int) -> bool:
    if end_minutes >= start_minutes:
        return start_minutes <= train_minutes <= end_minutes
    return train_minutes >= start_minutes or train_minutes <= end_minutes


def parse_time_constraint(user_message: str) -> dict | None:
    if not user_message:
        return None

    text = re.sub(r"\s+", " ", user_message.strip().lower())
    if not text:
        return None

    for keyword, (start, end) in sorted(_WINDOWS.items(), key=lambda item: len(item[0]), reverse=True):
        if re.search(rf"\b{re.escape(keyword)}\b", text):
            return {
                "mode": "between",
                "time": f"{start}-{end}",
                "start": start,
                "end": end,
            }

    between_patterns = [
        r"\b(?:between|from)\s+(.+?)\s+(?:and|to|-)\s+(.+?)(?:$|[,.?])",
        r"\b(?:trains?)\s+(?:from|between)\s+(.+?)\s+(?:and|to|-)\s+(.+?)(?:$|[,.?])",
    ]
    for pattern in between_patterns:
        match = re.search(pattern, text)
        if match:
            start = normalize_time_text(match.group(1))
            end = normalize_time_text(match.group(2))
            if start and end:
                return {
                    "mode": "between",
                    "time": f"{start}-{end}",
                    "start": start,
                    "end": end,
                }

    after_match = re.search(r"\b(?:after|later than|from)\s+(.+?)(?:$|[,.?])", text)
    if after_match:
        time_value = normalize_time_text(after_match.group(1))
        if time_value:
            return {"mode": "after", "time": time_value}

    before_match = re.search(r"\b(?:before|until|till|upto|up to)\s+(.+?)(?:$|[,.?])", text)
    if before_match:
        time_value = normalize_time_text(before_match.group(1))
        if time_value:
            return {"mode": "before", "time": time_value}

    return None


def filter_trains_by_time(trains: Iterable[dict], constraint: dict) -> list[dict]:
    if not trains:
        return []
    if not constraint:
        return list(trains)

    mode = constraint.get("mode")
    if mode not in {"after", "before", "between"}:
        return list(trains)

    time_value = constraint.get("time")
    if mode == "between":
        start_value = constraint.get("start")
        end_value = constraint.get("end")
        if not start_value or not end_value:
            if isinstance(time_value, str) and "-" in time_value:
                start_value, end_value = time_value.split("-", 1)

        start_minutes = _to_minutes(start_value)
        end_minutes = _to_minutes(end_value)
        if start_minutes is None or end_minutes is None:
            return list(trains)

        filtered = []
        for train in trains:
            train_time = _to_minutes(_pick_time(train))
            if train_time is None:
                filtered.append(train)
                continue
            if _match_window(train_time, start_minutes, end_minutes):
                filtered.append(train)
        return filtered

    threshold = _to_minutes(time_value)
    if threshold is None:
        return list(trains)

    filtered = []
    for train in trains:
        train_time = _to_minutes(_pick_time(train))
        if train_time is None:
            filtered.append(train)
            continue
        if mode == "after" and train_time >= threshold:
            filtered.append(train)
        elif mode == "before" and train_time <= threshold:
            filtered.append(train)

    return filtered