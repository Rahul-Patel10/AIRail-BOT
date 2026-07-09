"""
services/journey_planner.py — BFS-Based Connecting Journey Planner
===================================================================
Entry point: find_best_route()

Search flow:
  1. Ensure the in-memory railway graph is built (graph_builder).
  2. Search for direct trains in the graph (Phase 3).
     If any are found → return immediately; NEVER run BFS.
  3. Run backward Dijkstra from destination to pre-compute
     remaining-distance heuristics for every reachable station.
  4. Run BFS with a hard cap of MAX_BFS_POPS queue operations.
     At each step apply all 7 pruning rules (route_validator).
  5. Score and rank candidate journeys (route_ranker).
  6. Return top 3 routes as serialisable dicts.

If a train encountered during BFS has no schedule in memory,
optionally fetch it live via the RailRadar API and inject it
into the graph dynamically.
"""

from __future__ import annotations

import heapq
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime

from typing import Dict, List, Optional, Set

from services.graph_builder import get_graph, build_network_graph, update_graph_with_train
from services.route_validator import (
    check_max_changes,
    check_no_loop,
    check_distance_ratio,
    check_forward_progress,
    check_min_segment_length,
    check_layover_window,
    check_train_runs_on_date,
    parse_time_to_minutes,
    layover_minutes,
)
from services.route_ranker import (
    Journey,
    JourneySegment,
    rank_journeys,
    journey_to_dict,
)

logger = logging.getLogger(__name__)

# ── Safety guards ─────────────────────────────────────────────────────────────

# Hard limit on BFS node expansions — prevents runaway searches on large graphs
MAX_BFS_POPS: int = 5_000

# Maximum candidate journeys to collect before stopping BFS early
MAX_CANDIDATES: int = 30


# ── Search state ──────────────────────────────────────────────────────────────

@dataclass
class SearchState:
    """
    Represents one node in the BFS exploration tree.
    Moves through the graph station by station, accumulating journey info.
    """
    # Where we are right now
    current_station: str

    # The clock time at this station (arrival of the latest train, "HH:MM")
    current_time: str

    # The train we are currently riding (None = at origin, not yet boarded)
    current_train: str | None = None

    # Ordered list of train numbers used so far
    trains_used: List[str] = field(default_factory=list)

    # Set of all stations visited (for loop prevention)
    visited: Set[str] = field(default_factory=set)

    # Cumulative distance covered from origin
    distance: float = 0.0

    # Number of train changes made (= len(trains_used) - 1 when > 0)
    changes: int = 0

    # Ordered itinerary of completed JourneySegments
    itinerary: List[JourneySegment] = field(default_factory=list)

    # Interchange stations (all stations where a train change was made)
    interchange_stations: List[str] = field(default_factory=list)

    # Cumulative waiting time at interchanges (minutes)
    total_waiting: int = 0


# ── Dijkstra helper ───────────────────────────────────────────────────────────

def _backward_dijkstra(destination: str) -> Dict[str, float]:
    """
    Run Dijkstra on the *reverse* adjacency graph starting from `destination`.

    Returns a dict mapping station_code -> shortest remaining distance to reach
    `destination` from that station.  Stations not in the dict are unreachable.

    This gives us the admissible heuristic used in Rules 3 and 4.
    """
    graph = get_graph()
    dist: Dict[str, float] = {destination: 0.0}
    # Min-heap: (distance, station)
    heap = [(0.0, destination)]

    while heap:
        d, stn = heapq.heappop(heap)
        if d > dist.get(stn, float("inf")):
            continue
        for prev_stn, seg_dist, _train in graph.station_adj_rev.get(stn, []):
            new_dist = d + seg_dist
            if new_dist < dist.get(prev_stn, float("inf")):
                dist[prev_stn] = new_dist
                heapq.heappush(heap, (new_dist, prev_stn))

    return dist


# ── Direct train search ───────────────────────────────────────────────────────

def _search_direct_trains(
    source: str,
    destination: str,
    travel_date: Optional[date],
) -> List[dict]:
    """
    Phase 3 — Search the in-memory graph for trains that connect source directly
    to destination without any interchange.

    A train qualifies if:
      - It has a stop at `source` (departure exists) *before* a stop at `destination`.
      - It runs on `travel_date` (or date is unknown).

    Returns a list of direct-train dicts (same shape as journey_to_dict output
    but with a single segment).
    """
    graph = get_graph()
    results = []

    candidate_trains = graph.station_to_trains.get(source, set())
    for train_no in candidate_trains:
        route = graph.train_routes.get(train_no, [])
        src_stop = dst_stop = None

        for stop in route:
            if stop["station"] == source and stop["departure"] not in ("--:--", ""):
                src_stop = stop
            elif stop["station"] == destination and src_stop is not None:
                dst_stop = stop
                break

        if src_stop is None or dst_stop is None:
            continue

        # Check operating days
        meta = graph.train_metadata.get(train_no, {})
        run_days = meta.get("run_days", "Daily")
        if not check_train_runs_on_date(run_days, travel_date):
            continue

        seg_dist = dst_stop["distance"] - src_stop["distance"]
        dep_mins = parse_time_to_minutes(src_stop["departure"]) or 0
        arr_mins = parse_time_to_minutes(dst_stop["arrival"])
        travel_mins = 0
        if arr_mins is not None:
            travel_mins = arr_mins - dep_mins
            if travel_mins < 0:
                travel_mins += 24 * 60  # overnight

        seg = JourneySegment(
            train_no=train_no,
            train_name=meta.get("name", train_no),
            from_station=source,
            to_station=destination,
            departure=src_stop["departure"],
            arrival=dst_stop["arrival"],
            distance_km=max(seg_dist, 0),
            travel_time_mins=travel_mins,
        )
        j = Journey(
            segments=[seg],
            total_distance=max(seg_dist, 0),
            total_travel_time=travel_mins,
            total_waiting=0,
            changes=0,
        )
        results.append(j)

    return results


# ── BFS ───────────────────────────────────────────────────────────────────────

def _run_bfs(
    source: str,
    destination: str,
    travel_date: Optional[date],
    remaining_dist: Dict[str, float],
    min_total_dist: float,
    max_changes: int,
) -> List[Journey]:
    """
    Phase 4 + 5 — BFS with branch pruning.

    The queue holds SearchState objects.  At each pop we:
      a) Check if we have reached the destination → record candidate.
      b) Expand all trains available at the current station.
      c) For each downstream stop on each train apply Rules 1-6.
      d) If all rules pass, push the new state.

    A hard cap of MAX_BFS_POPS prevents runaway execution on dense graphs.
    """
    graph   = get_graph()
    candidates: List[Journey] = []
    pops    = 0

    initial_state = SearchState(
        current_station=source,
        current_time="00:00",
        visited={source},
    )
    queue: deque[SearchState] = deque([initial_state])

    while queue and pops < MAX_BFS_POPS and len(candidates) < MAX_CANDIDATES:
        state = queue.popleft()
        pops += 1

        # ── Expand all trains departing from current_station ──────────────────
        trains_here = graph.station_to_trains.get(state.current_station, set())

        for train_no in trains_here:
            # Skip the train we're already riding — we don't alight and re-board.
            # The current segment already handles all downstream stops on that train.
            if train_no == state.current_train:
                continue

            route = graph.train_routes.get(train_no)
            if not route:
                continue

            # Find the position of current_station in this train's route
            src_idx = None
            for idx, stop in enumerate(route):
                if (
                    stop["station"] == state.current_station
                    and stop["departure"] not in ("--:--", "")
                ):
                    src_idx = idx
                    break
            if src_idx is None:
                continue  # Train doesn't depart from here

            # Check whether this train runs on the travel date
            meta     = graph.train_metadata.get(train_no, {})
            run_days = meta.get("run_days", "Daily")
            if not check_train_runs_on_date(run_days, travel_date):
                continue

            # If we are already on this train (continuing same train), skip it
            # — changing to the same train doesn't count as an interchange.
            # NOTE: this check is now redundant due to current_train skip above
            # but kept as a safety guard for edge cases.
            is_continuation = False

            src_stop = route[src_idx]

            # ── Layover check before boarding ────────────────────────────────
            if state.trains_used and not is_continuation:
                # We are changing trains — validate the layover window
                if not check_layover_window(state.current_time, src_stop["departure"]):
                    continue

            # Determine how many changes boarding this train represents
            new_changes = state.changes
            if state.trains_used and not is_continuation:
                new_changes += 1

            # Rule 1: max changes
            if not check_max_changes(new_changes, max_changes):
                continue

            # ── Explore every downstream stop of this train ──────────────────
            for dst_idx in range(src_idx + 1, len(route)):
                dst_stop = route[dst_idx]
                next_stn = dst_stop["station"]

                # Rule 2: loop prevention
                if not check_no_loop(next_stn, state.visited):
                    continue

                seg_dist = dst_stop["distance"] - src_stop["distance"]
                if seg_dist <= 0:
                    continue

                # Rule 4: forward progress (only if we have remaining-dist data)
                next_remaining  = remaining_dist.get(next_stn,  float("inf"))
                cur_remaining   = remaining_dist.get(state.current_station, float("inf"))
                if not check_forward_progress(cur_remaining, next_remaining):
                    continue

                # Rule 3: distance ratio (prospective)
                if not check_distance_ratio(
                    state.distance, seg_dist, next_remaining, min_total_dist
                ):
                    continue

                # Rule 5: minimum segment length
                if not check_min_segment_length(seg_dist, min_total_dist):
                    continue

                # ── Compute timing for this segment ──────────────────────────
                dep_mins = parse_time_to_minutes(src_stop["departure"]) or 0
                arr_mins = parse_time_to_minutes(dst_stop["arrival"])
                travel_mins = 0
                if arr_mins is not None:
                    travel_mins = arr_mins - dep_mins
                    if travel_mins < 0:
                        travel_mins += 24 * 60

                # Compute layover at the interchange (if changing trains here)
                wait = 0
                if state.trains_used and not is_continuation:
                    w = layover_minutes(state.current_time, src_stop["departure"])
                    wait = w if w is not None else 0

                # ── Build the next segment ───────────────────────────────────
                new_seg = JourneySegment(
                    train_no=train_no,
                    train_name=meta.get("name", train_no),
                    from_station=state.current_station,
                    to_station=next_stn,
                    departure=src_stop["departure"],
                    arrival=dst_stop["arrival"],
                    distance_km=seg_dist,
                    travel_time_mins=travel_mins,
                )

                new_itinerary  = state.itinerary + [new_seg]
                new_trains     = state.trains_used + ([train_no] if not is_continuation or not state.trains_used else [])
                new_visited    = state.visited | {next_stn}
                new_distance   = state.distance + seg_dist
                new_waiting    = state.total_waiting + (wait if not is_continuation else 0)
                new_interchanges = (
                    state.interchange_stations + [state.current_station]
                    if (state.trains_used and not is_continuation)
                    else state.interchange_stations
                )

                # ── Check if destination reached ─────────────────────────────
                if next_stn == destination:
                    j = Journey(
                        segments=new_itinerary,
                        total_distance=int(new_distance),
                        total_travel_time=sum(s.travel_time_mins for s in new_itinerary),
                        total_waiting=new_waiting,
                        changes=new_changes,
                        interchange_stations=new_interchanges,
                    )
                    candidates.append(j)
                    logger.debug(
                        f"[BFS] Candidate found: {' → '.join(s.from_station for s in new_itinerary)} → {destination} "
                        f"({new_changes} change(s), {int(new_distance)} km)"
                    )
                    # Don't expand further from destination
                    continue

                # ── Push new state onto the queue ────────────────────────────
                new_state = SearchState(
                    current_station=next_stn,
                    current_time=dst_stop["arrival"] if dst_stop["arrival"] not in ("--:--", "") else src_stop["departure"],
                    current_train=train_no,   # remember which train we boarded
                    trains_used=new_trains,
                    visited=new_visited,
                    distance=new_distance,
                    changes=new_changes,
                    itinerary=new_itinerary,
                    interchange_stations=new_interchanges,
                    total_waiting=new_waiting,
                )
                queue.append(new_state)

    logger.info(
        f"[BFS] Completed: {pops} node(s) popped, "
        f"{len(candidates)} candidate route(s) found."
    )
    if pops >= MAX_BFS_POPS:
        logger.warning(
            f"[BFS] Safety cap reached ({MAX_BFS_POPS} pops). "
            "Results may be incomplete — consider tightening pruning or reducing graph size."
        )

    return candidates


def _parse_travel_date(travel_date: str | None) -> Optional[date]:
    """
    Accepts both YYYY-MM-DD and DD-MM-YYYY.
    """

    if not travel_date:
        return None

    travel_date = str(travel_date).strip()

    if not travel_date:
        return None

    for fmt in ("%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(travel_date, fmt).date()
        except ValueError:
            continue

    logger.warning(
        f"[JourneyPlanner] Invalid travel date: {travel_date}"
    )

    return None


def refresh_graph_with_train(train_payload: dict) -> bool:
    """
    Updates the in-memory railway graph after
    RailRadar downloads a new train schedule.

    This allows the planner to immediately
    use newly cached trains without rebuilding
    the whole graph.
    """

    if not train_payload:
        return False

    try:
        update_graph_with_train(train_payload)

        logger.info(
            "[JourneyPlanner] Graph updated for "
            f"{train_payload.get('train_no')}"
        )

        return True

    except Exception as exc:

        logger.warning(
            f"[JourneyPlanner] Graph refresh failed: {exc}"
        )

        return False
    

# ── Public API ────────────────────────────────────────────────────────────────

def find_best_route(
    source: str,
    destination: str,
    travel_date: str | None = None,
    max_changes: int = 2,
) -> List[dict]:
    """
    Main entry point for the journey planner.

    Parameters
    ----------
    source       : Origin station code (e.g. "ADI").
    destination  : Destination station code (e.g. "HWH").
    travel_date  : ISO date string "YYYY-MM-DD" or None.
    max_changes  : Maximum allowed train interchanges (default 2).

    Returns
    -------
    A list of up to 3 journey dicts, each containing:
      - changes, total_distance_km, total_travel_mins, total_waiting_mins
      - score, summary
      - segments: [{train_no, train_name, from_station, to_station,
                    departure, arrival, distance_km, travel_time_mins}]

    Returns an empty list if no route is found.
    """
    # ── Ensure graph is loaded ────────────────────────────────────────────────
    graph = get_graph()
    if not graph.loaded:
        logger.info("[JourneyPlanner] Graph not loaded — building now…")
        build_network_graph()
        graph = get_graph()

    # Parse travel date

    parsed_date = _parse_travel_date(travel_date)

    source      = source.upper().strip()
    destination = destination.upper().strip()

    if source == destination:
        logger.warning("[JourneyPlanner] Source and destination are the same.")
        return []

    if source not in graph.station_to_trains and source not in graph.station_adj:
        logger.warning(f"[JourneyPlanner] Source station '{source}' not found in graph.")
        return []

    # ── Phase 3: Direct train search ─────────────────────────────────────────
    direct_journeys = _search_direct_trains(source, destination, parsed_date)
    if direct_journeys:
        ranked_direct = rank_journeys(direct_journeys)
        logger.info(
            f"[JourneyPlanner] {len(direct_journeys)} direct train(s) found — skipping BFS."
        )
        return [journey_to_dict(j) for j in ranked_direct]

    logger.info(
        "[JourneyPlanner] Planner selected.\n"
        f"Source      : {source}\n"
        f"Destination : {destination}\n"
        f"Travel Date : {parsed_date}\n"
        f"Mode        : BFS Journey Search"
    )

    # ── Backward Dijkstra to get remaining distances ──────────────────────────
    remaining_dist = _backward_dijkstra(destination)
    min_total_dist = remaining_dist.get(source, 0.0)

    if min_total_dist == 0 and source != destination:
        logger.warning(
            f"[JourneyPlanner] Destination '{destination}' is unreachable from '{source}' "
            "in the current graph. No routes available."
        )
        return []

    # ── Phase 4 + 5: BFS with pruning ────────────────────────────────────────
    candidates = _run_bfs(
        source=source,
        destination=destination,
        travel_date=parsed_date,
        remaining_dist=remaining_dist,
        min_total_dist=min_total_dist,
        max_changes=max_changes,
    )

    if not candidates:
        logger.info(
            f"[JourneyPlanner] BFS found no valid connecting routes "
            f"{source} → {destination}."
        )
        return []

    # ── Phase 7 + 8: Score, rank, return ─────────────────────────────────────
    top_routes = rank_journeys(candidates)
    return [journey_to_dict(j) for j in top_routes]


def plan_journey(
    source_code: str,
    destination_code: str,
    travel_date: str | None = None,
    max_changes: int = 2,
) -> dict:
    """
    Public wrapper used by RailRadar.

    Provides a stable interface that
    future planners can reuse without
    changing RailRadar.
    """

    routes = find_best_route(
        source=source_code,
        destination=destination_code,
        travel_date=travel_date,
        max_changes=max_changes,
    )

    return {
        "planner": "journey_planner",
        "source": source_code,
        "destination": destination_code,
        "routes": routes,
        "route_count": len(routes),
        "success": len(routes) > 0,
    }
