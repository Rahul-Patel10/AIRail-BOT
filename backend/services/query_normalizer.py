"""
services/query_normalizer.py

Normalizes user-extracted parameters before they are sent
to the RailRadar API.
"""

from datetime import datetime
from utils.date_parser import normalize_date_text, normalize_time_text


def normalize_date(date_str: str | None):
    """
    Returns DD-MM-YYYY.

    This format is used by the RailRadar API.
    """

    if not date_str:
        return None

    return normalize_date_text(date_str)

def normalize_date_iso(date_str: str | None):
    """
    Converts any supported date into ISO format.

    Returns

    YYYY-MM-DD

    Used by Journey Planner.
    """

    if not date_str:
        return None

    value = normalize_date(date_str)

    if not value:
        return None

    try:
        return datetime.strptime(
            value,
            "%d-%m-%Y",
        ).strftime("%Y-%m-%d")

    except ValueError:
        return None


def normalize_time(time_str: str | None):
    """Converts natural-language times into HH:MM."""
    if not time_str:
        return None
    return normalize_time_text(time_str)


def normalize_params(params: dict):
    """Normalizes every extracted parameter."""
    if not params:
        return {}

    normalized = dict(params)

    if normalized.get("train_no") is not None:
        normalized["train_no"] = str(normalized["train_no"]).strip() or None

    travel_date = (
        normalized.get("date")
        or normalized.get("travel_date")
    )

    normalized["date"] = normalize_date(travel_date)

    normalized["travel_date_iso"] = normalize_date_iso(
        travel_date
    )
    normalized["departure_after"] = normalize_time(
        normalized.get("departure_after") or normalized.get("after_time")
    )
    normalized["departure_before"] = normalize_time(
        normalized.get("departure_before") or normalized.get("before_time")
    )
    normalized["arrival_after"] = normalize_time(normalized.get("arrival_after"))
    normalized["arrival_before"] = normalize_time(normalized.get("arrival_before"))

    if normalized.get("train_type"):
        normalized["train_type"] = str(normalized["train_type"]).strip()

    if normalized.get("sort_by"):
        normalized["sort_by"] = str(normalized["sort_by"]).strip().lower()

    return normalized