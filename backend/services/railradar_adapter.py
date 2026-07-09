"""
services/railradar_adapter.py — Normalize RailRadar API payloads to agent response shapes.
"""

from sqlalchemy.orm import descriptor_props
from datetime import datetime

# Map API-facing station codes back to internal DB codes
_STATION_CODE_API_TO_DB = {
    "MMCT": "BCT",
}


def _db_station_code(code: str) -> str:
    """Map API station codes (e.g. MMCT) back to our SQLite DB codes (e.g. BCT)."""
    if not code:
        return code
    return _STATION_CODE_API_TO_DB.get(code.upper(), code.upper())


def _str_station(val) -> str:
    """Safely convert a station value that may be a dict or string to a plain string."""
    if isinstance(val, dict):
        return (
            val.get("station_name")
            or val.get("name")
            or val.get("station_code")
            or val.get("code")
            or "Unknown"
        )
    return str(val) if val else "Unknown"


def _unwrap_data(payload: dict) -> dict | list | None:
    if not isinstance(payload, dict):
        return None
    if payload.get("data") is not None:
        return payload["data"]
    return payload


def normalize_trains_between(
    payload: dict,
    source_name: str,
    destination_name: str,
    source_code: str,
    dest_code: str,
) -> dict | None:
    data = _unwrap_data(payload)
    if data is None:
        return None

    trains_raw = data if isinstance(data, list) else data.get("trains", [])
    if not isinstance(trains_raw, list):
        return None

    result_trains = []
    for item in trains_raw:
        if not isinstance(item, dict):
            continue

        # The API wraps train info under item["train"] and timing under item["from"]/item["to"]
        train_info = item.get("train") or item
        from_info  = item.get("from") or {}
        to_info    = item.get("to") or {}

        train_no   = str(train_info.get("number") or train_info.get("train_number") or train_info.get("train_no") or "")
        train_name = train_info.get("name") or train_info.get("train_name") or "Unknown"
        run_days_raw = train_info.get("runDays") or train_info.get("run_days") or train_info.get("days") or "Daily"
        run_days   = ", ".join(d.capitalize() for d in run_days_raw) if isinstance(run_days_raw, list) else run_days_raw

        departure  = from_info.get("departure") or item.get("departure") or item.get("departure_time") or "--:--"
        arrival    = to_info.get("arrival") or item.get("arrival") or item.get("arrival_time") or "--:--"

        result_trains.append({
            "train_no":    train_no,
            "train_name":  train_name,
            "from":        source_name,
            "from_code":   source_code,
            "to":          destination_name,
            "to_code":     dest_code,
            "departure":   departure,
            "arrival":     arrival,
            "run_days":    run_days,
            "availability": item.get("availability") or {},
        })

    if not result_trains:
        return None

    return {
        "trains": result_trains,
        "source": source_name,
        "destination": destination_name,
        "trace_step": (
            f"[RailRadar] Fetched via RailRadar API: {source_name} → "
            f"{destination_name}. Found {len(result_trains)} direct train(s)."
        ),
    }


def normalize_train_route(payload: dict, train_no: str) -> dict | None:
    """
    Normalizes both the /route (GeoJSON) endpoint and the /trains/{no} (details)
    endpoint into a common stop-list format. The /details endpoint returns stops
    under data['schedule'] where each stop has a nested 'station' dict.
    """
    data = _unwrap_data(payload)
    if data is None:
        return None

    train_name = "Unknown"
    stops_raw = []

    if isinstance(data, dict):
        # /trains/{no} details API puts name/number at top level
        train_name = (
            data.get("train_name") or data.get("name")
            or data.get("trainName") or train_name
        )
        stops_raw = (
            data.get("schedule")
            or data.get("route")
            or data.get("stops")
            or []
        )
    elif isinstance(data, list):
        stops_raw = data
    else:
        return None

    stops = []

    for idx, item in enumerate(stops_raw):

        if not isinstance(item, dict):
            continue

        # ----------------------------------------------------------
        # Resolve station name/code
        # ----------------------------------------------------------

        station_obj = item.get("station") or {}

        if isinstance(station_obj, dict) and station_obj:
            raw_code = (
                station_obj.get("code")
                or item.get("station_code")
                or "???"
            )

            station_name = (
                station_obj.get("name")
                or item.get("station_name")
                or ""
            )

        else:

            raw_code = (
                item.get("station_code")
                or item.get("code")
                or item.get("station")
                or "???"
            )

            station_name = (
                item.get("station_name")
                or item.get("name")
                or ""
            )

        station_code = _db_station_code(raw_code) or raw_code

        arrival = (
            item.get("arrival")
            or item.get("arrival_time")
            or "--:--"
        )

        departure = (
            item.get("departure")
            or item.get("departure_time")
            or "--:--"
        )

        # ----------------------------------------------------------
        # Skip technical halts
        # ----------------------------------------------------------

        # ----------------------------------------------------------
# Skip technical halts
# Keep first and last station even if arrival == departure
# ----------------------------------------------------------

        is_first = idx == 0
        is_last = idx == len(stops_raw) - 1

        if (
            not is_first
            and not is_last
            and arrival not in ("--:--", "", None)
            and departure not in ("--:--", "", None)
            and arrival == departure
        ):
            continue

        stops.append({
            "station_code": station_code,
            "arrival": arrival,
            "departure": departure,
            "distance_km": item.get("distance_km")
                            or item.get("distance")
                            or 0,
            "stop_no": item.get("sequence")
                    or item.get("stop_number")
                    or item.get("stop_no")
                    or idx + 1,
            "station": station_name,
        })

    if not stops:
        return None

    return {
        "train_no":   train_no,
        "train_name": train_name,
        "stops":      stops,
        "trace_step": (
            f"[RailRadar] Fetched route via RailRadar API for {train_name} "
            f"({train_no}) — {len(stops)} stops."
        ),
    }

from datetime import datetime


def normalize_live_status(payload: dict, train_no: str, train_name: str = "Unknown") -> dict | None:
    data = _unwrap_data(payload)

    if not isinstance(data, dict):
        if isinstance(payload, dict) and not payload.get("success", True):
            return None
        data = payload if isinstance(payload, dict) else {}

    # ---------------------------------------------------------------------
    # Route information
    # ---------------------------------------------------------------------
    route = data.get("route") or []

    current_location = data.get("currentLocation") or {}

    current = None
    next_station = None
    eta = None
    current_seq = None

    # ---------------------------------------------------------------------
    # Find current station from currentLocation
    # ---------------------------------------------------------------------
    if isinstance(current_location, dict):

        current_seq = current_location.get("sequence")
        current_code = current_location.get("stationCode")

        # First try sequence match
        if current_seq is not None:

            for stop in route:

                if stop.get("sequence") == current_seq:

                    current = (
                        stop.get("stationName")
                        or stop.get("station")
                        or stop.get("stationCode")
                    )

                    break

        # Fallback to station code
        if current is None and current_code:

            for stop in route:

                if stop.get("stationCode") == current_code:

                    current = (
                        stop.get("stationName")
                        or stop.get("station")
                        or stop.get("stationCode")
                    )

                    break

    # ---------------------------------------------------------------------
    # Fallback for APIs that directly expose current station
    # ---------------------------------------------------------------------
    if current is None:

        current = (
            data.get("current_station")
            or data.get("current_station_name")
            or data.get("current_station_code")
            or data.get("currentStation")
            or data.get("currentStationName")
            or data.get("currentLocation")
            or data.get("station")
        )

    # ---------------------------------------------------------------------
    # Find next station using route sequence
    # ---------------------------------------------------------------------
    if route and current_seq is not None:

        for stop in route:

            if stop.get("sequence", -1) > current_seq:

                next_station = (
                    stop.get("stationName")
                    or stop.get("station")
                    or stop.get("stationCode")
                )

                eta = (
                    stop.get("actualArrival")
                    or stop.get("scheduledArrival")
                    or stop.get("scheduledDeparture")
                )

                break

    # ---------------------------------------------------------------------
    # Fallback for APIs exposing next station directly
    # ---------------------------------------------------------------------
    if next_station is None:

        next_station = (
            data.get("next_station")
            or data.get("next_station_name")
            or data.get("next_station_code")
            or data.get("nextStation")
            or data.get("nextStationName")
            or data.get("next_stop")
        )

    # ---------------------------------------------------------------------
    # Fallback ETA
    # ---------------------------------------------------------------------
    if eta is None:

        eta = (
            data.get("eta")
            or data.get("expected_arrival")
            or data.get("expectedArrival")
            or data.get("estimatedArrival")
            or data.get("arrivalTime")
        )

    # ---------------------------------------------------------------------
    # Delay
    # ---------------------------------------------------------------------
    delay = (
        data.get("delay_mins")
        or data.get("delay")
        or data.get("delayMinutes")
        or 0
    )

    try:
        delay_mins = int(delay)
    except (TypeError, ValueError):
        delay_mins = 0

    # ---------------------------------------------------------------------
    # Convert dicts into printable strings
    # ---------------------------------------------------------------------
    current = _str_station(current)
    next_station = _str_station(next_station)

    # ---------------------------------------------------------------------
    # If nothing useful exists, abort
    # ---------------------------------------------------------------------
    if current == "Unknown" and next_station == "Unknown" and not data.get("status"):

        return None

    # ---------------------------------------------------------------------
    # Train name
    # ---------------------------------------------------------------------
    raw_name = (
        data.get("train_name")
        or data.get("trainName")
        or train_name
    )

    if isinstance(raw_name, dict):

        raw_name = raw_name.get("name") or train_name

    # ---------------------------------------------------------------------
    # Status
    # ---------------------------------------------------------------------
    status = (
        data.get("status")
        or data.get("train_status")
        or data.get("state")
        or "Live status available"
    )

    # ---------------------------------------------------------------------
    # Return
    # ---------------------------------------------------------------------
    return {

        "train_no": train_no,

        "train_name": str(raw_name),

        "current_station": current,

        "next_station": next_station,

        "delay_mins": delay_mins,

        "status": str(status),

        "eta": eta,

        "last_updated": (
            data.get("last_updated")
            or data.get("updated_at")
            or datetime.utcnow().isoformat(timespec="seconds")
        ),

        "trace_step": (
            f"[RailRadar] Fetched live status via RailRadar API for {train_no}."
        ),
    }