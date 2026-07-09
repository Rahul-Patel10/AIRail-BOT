"""
services/route_ranker.py — Journey Candidate Scoring & Ranking
===============================================================
Implements the scoring formula and returns the top-N candidate routes.

Scoring formula (lower is better):
    score = (changes × 1_000)
          + (waiting_time_mins × 3)
          + distance_km
          + travel_time_mins
          + (non-major interchange penalty × 500 per interchange)

Ranking order (tie-breaking):
    1. Fewest train changes
    2. Shortest total travel time (departure to final arrival)
    3. Shortest total distance
    4. Least total waiting / layover time
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional

from services.route_validator import is_major_junction, MINOR_JUNCTION_PENALTY

logger = logging.getLogger(__name__)

# Maximum number of routes to return
TOP_N_ROUTES: int = 3


# ── Data model for a complete candidate journey ───────────────────────────────

@dataclass
class JourneySegment:
    """One leg of a multi-leg journey (a single continuous train ride)."""
    train_no:    str
    train_name:  str
    from_station: str
    to_station:  str
    departure:   str          # "HH:MM"
    arrival:     str          # "HH:MM"
    distance_km: int
    travel_time_mins: int     # computed from departure → arrival


@dataclass
class Journey:
    """
    A complete journey composed of one or more segments.
    Populated by journey_planner.py, ranked here.
    """
    segments:         List[JourneySegment] = field(default_factory=list)
    total_distance:   int   = 0
    total_travel_time: int  = 0   # minutes of actual train time
    total_waiting:    int   = 0   # minutes waiting at interchange stations
    changes:          int   = 0   # number of train changes (= segments - 1)
    score:            float = 0.0
    interchange_stations: List[str] = field(default_factory=list)

    # Human-readable summary built by the ranker
    summary: str = ""


# ── Scoring ───────────────────────────────────────────────────────────────────

def _compute_score(journey: Journey) -> float:
    """
    Compute the numeric score for a candidate journey.
    Lower scores are better.

    Scoring components:
      changes          × 1 000  — strongly prefer fewer interchanges
      waiting_time     × 3      — penalise long layovers
      distance_km      × 1      — prefer shorter paths
      travel_time_mins × 1      — prefer faster journeys
      minor_penalty    × 500    — each non-major interchange station adds this
    """
    penalty = sum(
        MINOR_JUNCTION_PENALTY
        for stn in journey.interchange_stations
        if not is_major_junction(stn)
    )

    return (
        journey.changes       * 1_000
        + journey.total_waiting  * 3
        + journey.total_distance
        + journey.total_travel_time
        + penalty
    )


def _build_summary(journey: Journey) -> str:
    """Build a short human-readable summary of the journey segments."""
    parts = []
    for i, seg in enumerate(journey.segments):
        prefix = f"Leg {i + 1}"
        parts.append(
            f"{prefix}: {seg.train_name} ({seg.train_no}) | "
            f"{seg.from_station} {seg.departure} → {seg.to_station} {seg.arrival} | "
            f"{seg.distance_km} km"
        )
    changes_str = f"{journey.changes} change{'s' if journey.changes != 1 else ''}"
    summary_header = (
        f"🚆 {len(journey.segments)}-train journey | {changes_str} | "
        f"{journey.total_distance} km | ~{journey.total_travel_time} min travel | "
        f"~{journey.total_waiting} min wait"
    )
    return summary_header + "\n" + "\n".join(parts)


# ── Public API ────────────────────────────────────────────────────────────────

def rank_journeys(candidates: List[Journey], top_n: int = TOP_N_ROUTES) -> List[Journey]:
    """
    Score all candidate journeys and return the best `top_n`.

    Parameters
    ----------
    candidates : list of Journey objects produced by the BFS.
    top_n      : number of routes to return (default 3).

    Returns
    -------
    Sorted list of the best journeys (ascending score), length ≤ top_n.
    """
    if not candidates:
        return []

    for journey in candidates:
        journey.score   = _compute_score(journey)
        journey.summary = _build_summary(journey)

    ranked = sorted(candidates, key=lambda j: j.score)
    top    = ranked[:top_n]

    logger.info(
        f"[RouteRanker] {len(candidates)} candidates scored → returning top {len(top)}. "
        f"Best score: {top[0].score:.0f}"
    )
    return top


def journey_to_dict(journey: Journey) -> dict:
    """
    Serialise a Journey dataclass to a plain dict suitable for JSON responses.
    """
    return {
        "changes":            journey.changes,
        "total_distance_km":  journey.total_distance,
        "total_travel_mins":  journey.total_travel_time,
        "total_waiting_mins": journey.total_waiting,
        "score":              round(journey.score, 2),
        "summary":            journey.summary,
        "interchange_stations": journey.interchange_stations,
        "segments": [
            {
                "train_no":        seg.train_no,
                "train_name":      seg.train_name,
                "from_station":    seg.from_station,
                "to_station":      seg.to_station,
                "departure":       seg.departure,
                "arrival":         seg.arrival,
                "distance_km":     seg.distance_km,
                "travel_time_mins": seg.travel_time_mins,
            }
            for seg in journey.segments
        ],
    }
