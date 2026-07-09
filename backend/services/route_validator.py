"""
services/route_validator.py — Railway-Specific Route Pruning Rules
===================================================================
Contains all stateless validation helpers used by the BFS in
journey_planner.py to prune invalid or unrealistic route branches.

Rules implemented
-----------------
Rule 1  check_max_changes          – Do not exceed the maximum allowed train changes.
Rule 2  check_no_loop              – Reject any station already visited in this path.
Rule 3  check_distance_ratio       – Total path distance ≤ 1.75 × minimum railway distance.
Rule 4  check_forward_progress     – Each hop must reduce remaining distance to destination.
Rule 5  check_min_segment_length   – Every segment must be > 20 % of minimum trip distance.
Rule 6  check_layover_window       – Transfer time: 20 min ≤ layover ≤ 6 h.
Rule 7  MAJOR_JUNCTIONS            – Interchange at minor stations incurs a score penalty.

Helper
------
parse_time_to_minutes  – Convert "HH:MM" to minutes-since-midnight.
minutes_diff           – Signed or unsigned difference between two time values
                         (handles overnight crossings).
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Set

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

# Max allowed ratio of (path distance) / (min direct railway distance).
MAX_DISTANCE_RATIO: float = 1.75

# Minimum fraction of total trip distance a single leg must cover.
MIN_SEGMENT_FRACTION: float = 0.20

# Minimum transfer time in minutes between two trains.
MIN_LAYOVER_MINUTES: int = 20

# Maximum transfer time in minutes (6 hours).
MAX_LAYOVER_MINUTES: int = 360

# Penalty added to the journey score for interchanging at a minor station.
MINOR_JUNCTION_PENALTY: int = 500

# Well-known major interchange junctions in India.
# Expanding at one of these is preferred over small stops.
MAJOR_JUNCTIONS: Set[str] = {
    "ADI",   # Ahmedabad
    "BRC",   # Vadodara
    "ST",    # Surat
    "BCT",   # Mumbai Central
    "CSTM",  # Mumbai CST
    "NDLS",  # New Delhi
    "CNB",   # Kanpur
    "ALD",   # Prayagraj
    "NGP",   # Nagpur
    "PUNE",  # Pune
    "HWH",   # Howrah / Kolkata
    "MAS",   # Chennai
    "SBC",   # Bengaluru
    "SC",    # Secunderabad
    "HYB",   # Hyderabad
    "BPL",   # Bhopal
    "ET",    # Itarsi
    "JP",    # Jaipur
    "LKO",   # Lucknow
    "PNBE",  # Patna
    "GWL",   # Gwalior
    "MGS",   # Mughal Sarai / Pt Deen Dayal Upadhyaya Jn
    "BSP",   # Bilaspur
    "R",     # Raipur
    "AGC",   # Agra Cantt
    "KOTA",  # Kota
    "GKP",   # Gorakhpur
    "CNB",   # Kanpur Central
    "VSKP",  # Visakhapatnam
    "GHY",   # Guwahati
}


# ── Time Helpers ──────────────────────────────────────────────────────────────

def parse_time_to_minutes(time_str: str) -> int | None:
    """
    Parse "HH:MM" into minutes since midnight.

    Returns None if the value is missing or invalid (e.g. "--:--").
    """
    if not time_str or time_str.strip() in ("--:--", "None", ""):
        return None
    parts = time_str.strip().split(":")
    if len(parts) != 2:
        return None
    try:
        h, m = int(parts[0]), int(parts[1])
        if 0 <= h <= 23 and 0 <= m <= 59:
            return h * 60 + m
    except ValueError:
        pass
    return None


def layover_minutes(arrival_str: str, departure_str: str) -> int | None:
    """
    Compute how many minutes elapse between a train's arrival and the
    next train's departure at the same interchange station.

    Handles overnight rollovers (arrival 23:30 → departure 01:00 = +90 min).

    Returns None if either time is invalid.
    """
    arr = parse_time_to_minutes(arrival_str)
    dep = parse_time_to_minutes(departure_str)
    if arr is None or dep is None:
        return None

    diff = dep - arr
    # If next train departs "before" arrival in clock terms it crosses midnight
    if diff < 0:
        diff += 24 * 60
    return diff


# ── Pruning Rules ─────────────────────────────────────────────────────────────

def check_max_changes(changes: int, max_changes: int) -> bool:
    """
    Rule 1 — Do not expand states where we have exceeded max_changes.

    Parameters
    ----------
    changes    : number of train changes already made in this path.
    max_changes: upper limit (default 2 → at most 3 trains).

    Returns True if the state is still valid (changes ≤ max).
    """
    return changes <= max_changes


def check_no_loop(next_station: str, visited: Set[str]) -> bool:
    """
    Rule 2 — Prevent visiting the same station twice in one journey path.

    Returns True if next_station has NOT been visited yet.
    """
    return next_station not in visited


def check_distance_ratio(
    distance_so_far: float,
    segment_distance: float,
    remaining_to_dest: float,
    min_total_distance: float,
) -> bool:
    """
    Rule 3 — Reject routes whose cumulative distance is unrealistically long.

    The check is: (distance_so_far + segment_distance + remaining_to_dest)
                  ≤ MAX_DISTANCE_RATIO × min_total_distance

    This is a *prospective* check — if even the heuristic minimum
    remaining distance exceeds the ratio, we prune now.

    Returns True if the ratio constraint is satisfied.
    """
    if min_total_distance <= 0:
        return True  # no reference distance → skip check
    prospective = distance_so_far + segment_distance + remaining_to_dest
    return prospective <= MAX_DISTANCE_RATIO * min_total_distance


def check_forward_progress(
    current_remaining: float,
    next_remaining: float,
) -> bool:
    """
    Rule 4 — Every step must bring us closer to the destination.

    Uses pre-computed shortest distances (backward Dijkstra) to verify
    that next_remaining < current_remaining.

    Returns True if the hop makes genuine forward progress.
    """
    # Allow a tiny tolerance (≤ 1 km) for stations at equal graph distance
    return next_remaining < current_remaining + 1


def check_min_segment_length(
    segment_distance: float,
    min_total_distance: float,
) -> bool:
    """
    Rule 5 — Reject trivially short segments (e.g. changing trains after 30 km
    on a 1 500 km journey).

    Segment must be at least MIN_SEGMENT_FRACTION of the minimum trip distance.
    Returns True if the segment is long enough.
    """
    if min_total_distance <= 0:
        return True  # no reference → skip check
    return segment_distance >= MIN_SEGMENT_FRACTION * min_total_distance


def check_layover_window(arrival_str: str, departure_str: str) -> bool:
    """
    Rule 6 — Transfer time must fall within [MIN_LAYOVER_MINUTES, MAX_LAYOVER_MINUTES].

    If either time is unknown ("--:--") we allow the transfer — the live API
    or fallback estimation will catch bad timings later.

    Returns True if the layover is feasible.
    """
    arr = parse_time_to_minutes(arrival_str)
    dep = parse_time_to_minutes(departure_str)

    if arr is None or dep is None:
        # One timing is unknown — be permissive rather than over-pruning
        return True

    wait = layover_minutes(arrival_str, departure_str)
    if wait is None:
        return True

    return MIN_LAYOVER_MINUTES <= wait <= MAX_LAYOVER_MINUTES


def is_major_junction(station_code: str) -> bool:
    """Return True if the station is a recognised major interchange junction."""
    return station_code in MAJOR_JUNCTIONS


def check_train_runs_on_date(run_days: str, travel_date: date | None) -> bool:
    """
    Check whether a train operates on the given calendar date.

    The `run_days` field stores either "Daily" or a comma-separated list
    of abbreviated weekday names: "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun".

    Parameters
    ----------
    run_days    : train's run_days string from the database.
    travel_date : the calendar date for travel. If None, we skip the check.

    Returns True if the train runs on that date (or date is unknown).
    """
    if travel_date is None:
        return True  # no date constraint — assume it runs

    run_days = (run_days or "Daily").strip()
    if run_days.lower() == "daily":
        return True

    # Python weekday(): Mon=0 … Sun=6
    day_map = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}
    day_abbr = day_map.get(travel_date.weekday(), "")
    allowed = [d.strip() for d in run_days.split(",")]
    return day_abbr in allowed
