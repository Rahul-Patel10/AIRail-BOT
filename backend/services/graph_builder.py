"""
services/graph_builder.py — Railway Network In-Memory Graph Builder
====================================================================
Loads the entire SQLite railway dataset ONCE at startup and builds
several index structures for fast, repeated BFS lookups.

Data structures built:
  station_to_trains  : dict[station_code -> set of train_nos that depart there]
  train_routes       : dict[train_no    -> ordered list of stop dicts]
  station_distance   : dict[(src, dst)  -> direct distance_km (where dst is downstream of src)]
  train_metadata     : dict[train_no    -> {name, run_days}]
  station_adj        : dict[station     -> list of (next_station, distance, train_no)]
  station_adj_rev    : dict[station     -> list of (prev_station, distance, train_no)]

All public data is stored in the _graph singleton so it is built once
and shared across the lifetime of the process.
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple, Optional

logger = logging.getLogger(__name__)


# ── Singleton container ────────────────────────────────────────────────────────

@dataclass
class _RailwayGraph:
    """
    In-memory representation of the entire railway network.
    Populated once by build_network_graph() on startup.
    """
    # Maps station_code -> set of train numbers that have a *departure* from that station
    station_to_trains: Dict[str, Set[str]] = field(default_factory=dict)

    # Maps train_no -> list of stop dicts ordered by stop_number
    # Each stop: {"station": str, "arrival": str, "departure": str,
    #             "distance": int, "stop_number": int}
    train_routes: Dict[str, List[dict]] = field(default_factory=dict)

    # Maps (src_code, dst_code) -> distance_km  (dst downstream of src on some train)
    station_distance: Dict[Tuple[str, str], int] = field(default_factory=dict)

    # Maps train_no -> {"name": str, "run_days": str}
    train_metadata: Dict[str, dict] = field(default_factory=dict)

    # Forward adjacency:  station -> [(next_station, dist_km, train_no), ...]
    station_adj: Dict[str, List[Tuple[str, int, str]]] = field(default_factory=dict)

    # Backward adjacency: station -> [(prev_station, dist_km, train_no), ...]
    station_adj_rev: Dict[str, List[Tuple[str, int, str]]] = field(default_factory=dict)

    # Whether the graph has been populated
    loaded: bool = False


# Module-level singleton — imported by journey_planner and other callers
_graph = _RailwayGraph()


def get_graph() -> _RailwayGraph:
    """Return the module-level singleton railway graph."""
    return _graph


# ── Builder ────────────────────────────────────────────────────────────────────

def build_network_graph(force: bool = False) -> _RailwayGraph:
    """
    Populate the in-memory railway graph from SQLite.

    Parameters
    ----------
    force : bool
        Re-build even if the graph is already loaded (useful for tests).

    Returns
    -------
    _RailwayGraph
        The populated singleton instance.
    """
    global _graph

    if _graph.loaded and not force:
        logger.debug("[GraphBuilder] Graph already loaded — skipping rebuild.")
        return _graph

    logger.info("[GraphBuilder] Building in-memory railway network graph from SQLite…")

    # Import here to avoid circular imports at module load time
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from database import Session, Train, TrainSchedule

    with Session() as db:
        # ── Step 1: load all train metadata ───────────────────────────────────
        all_trains = db.query(Train).all()
        for t in all_trains:
            _graph.train_metadata[t.train_no] = {
                "name":     t.train_name,
                "run_days": t.run_days or "Daily",
            }

        # ── Step 2: load all schedules ordered by stop_number ─────────────────
        all_schedules = (
            db.query(TrainSchedule)
            .order_by(TrainSchedule.train_no, TrainSchedule.stop_number)
            .all()
        )

        # Group by train
        train_stops: Dict[str, List[TrainSchedule]] = {}
        for sched in all_schedules:
            train_stops.setdefault(sched.train_no, []).append(sched)

        # ── Step 3: build indexes from grouped stops ───────────────────────────
        for train_no, stops in train_stops.items():
            # Sort by stop_number defensively
            stops = sorted(stops, key=lambda s: s.stop_number)

            route = []
            for s in stops:
                route.append({
                    "station":     s.station_code,
                    "arrival":     s.arrival   or "--:--",
                    "departure":   s.departure or "--:--",
                    "distance":    s.distance_km or 0,
                    "stop_number": s.stop_number,
                })
            _graph.train_routes[train_no] = route

            # Build station_to_trains (only stations where the train departs)
            for stop in route:
                if stop["departure"] not in ("--:--", None, ""):
                    code = stop["station"]
                    _graph.station_to_trains.setdefault(code, set()).add(train_no)

            # Build station_distance and adjacency lists using consecutive pairs
            for i in range(len(route)):
                src = route[i]
                for j in range(i + 1, len(route)):
                    dst = route[j]
                    seg_dist = dst["distance"] - src["distance"]
                    if seg_dist <= 0:
                        continue

                    pair = (src["station"], dst["station"])
                    # Keep the shortest known distance between any two station pair
                    if pair not in _graph.station_distance or _graph.station_distance[pair] > seg_dist:
                        _graph.station_distance[pair] = seg_dist

                    # Forward adjacency: only add the immediate next stop per train
                    if j == i + 1:
                        _graph.station_adj.setdefault(src["station"], []).append(
                            (dst["station"], seg_dist, train_no)
                        )
                        _graph.station_adj_rev.setdefault(dst["station"], []).append(
                            (src["station"], seg_dist, train_no)
                        )

    _graph.loaded = True
    logger.info(
        "[GraphBuilder] Graph ready — "
        f"{len(_graph.train_routes)} trains, "
        f"{len(_graph.station_to_trains)} stations, "
        f"{len(_graph.station_distance)} station-distance pairs."
    )
    return _graph


def update_graph_with_train(train_no: str, stops: List[dict]) -> None:
    """
    Dynamically extend the in-memory graph with a newly fetched train schedule.
    Called after a live RailRadar API fetch so the BFS can use fresh data
    without requiring a full graph rebuild.

    Parameters
    ----------
    train_no : str
        The train number being added / updated.
    stops : list[dict]
        List of stop dicts in the same format as `get_train_schedule` returns
        (keys: station_code, arrival, departure, distance_km, stop_no).
    """
    if not stops:
        return

    # Normalise the stop dicts to the internal format
    route = []
    for s in stops:
        route.append({
            "station":     s.get("station_code") or s.get("station", ""),
            "arrival":     s.get("arrival",   "--:--"),
            "departure":   s.get("departure", "--:--"),
            "distance":    int(s.get("distance_km") or s.get("distance") or 0),
            "stop_number": int(s.get("stop_no")     or s.get("stop_number") or 0),
        })

    route = sorted(route, key=lambda x: x["stop_number"])
    _graph.train_routes[train_no] = route

    for stop in route:
        if stop["departure"] not in ("--:--", None, ""):
            _graph.station_to_trains.setdefault(stop["station"], set()).add(train_no)

    for i in range(len(route)):
        src = route[i]
        for j in range(i + 1, len(route)):
            dst = route[j]
            seg_dist = dst["distance"] - src["distance"]
            if seg_dist <= 0:
                continue
            pair = (src["station"], dst["station"])
            if pair not in _graph.station_distance or _graph.station_distance[pair] > seg_dist:
                _graph.station_distance[pair] = seg_dist
            if j == i + 1:
                _graph.station_adj.setdefault(src["station"], []).append(
                    (dst["station"], seg_dist, train_no)
                )
                _graph.station_adj_rev.setdefault(dst["station"], []).append(
                    (src["station"], seg_dist, train_no)
                )

    logger.info(f"[GraphBuilder] Dynamically added train {train_no} ({len(route)} stops) to graph.")
