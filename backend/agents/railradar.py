"""
agents/railradar.py — RailRadar Agent (Train Search & Route Solver)
====================================================================
Handles train-related queries using RailRadar API first, with SQLite fallback.
"""

import os
import random
import httpx
from datetime import date, datetime
import json

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import Session, Train, Station, TrainSchedule, SeatAvailability
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from services.journey_planner import (
    plan_journey,
    refresh_graph_with_train,
)
from services.query_normalizer import normalize_date, normalize_params
from services.context_manager import save_search_context, get_search_context
from services.railradar_client import get_railradar_client
from services.railradar_adapter import (
    normalize_trains_between,
    normalize_train_route,
    normalize_live_status,
)
from services.route_validator import check_train_runs_on_date
from services.train_filter import (
    parse_time_constraint,
    filter_trains_by_time,
)
from services.station_resolver import resolve_station_with_chroma
from dotenv import load_dotenv

load_dotenv()


def _get_llm():
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return None
    return ChatGroq(
        model=os.environ.get("GROQ_MODEL", "llama3-8b-8192"),
        groq_api_key=api_key,
        temperature=0.3,
    )


def _resolve_station(db, query):
    match = resolve_station_with_chroma(query, db=db)
    if not match:
        return None
    return db.query(Station).filter(Station.code == match["code"]).first()


def _normalize_live_status_payload(payload: dict) -> dict:
    if not isinstance(payload, dict):
        return {}
    current = payload.get("current_station") or payload.get("currentLocation") or payload.get("station")
    next_station = payload.get("next_station") or payload.get("nextStation") or payload.get("next_stop")
    delay = payload.get("delay_mins") or payload.get("delay") or payload.get("delayMinutes") or 0
    status = payload.get("status") or payload.get("train_status") or payload.get("state") or "Live status available"

    return {
        "current_station": current or "Unknown",
        "next_station": next_station or "Unknown",
        "delay_mins": int(delay) if str(delay).isdigit() else 0,
        "status": status,
        "eta": payload.get("eta") or payload.get("expected_arrival") or payload.get("expectedArrival"),
        "last_updated": payload.get("last_updated") or payload.get("updated_at") or datetime.utcnow().isoformat(timespec="seconds"),
    }


def _parse_travel_date(travel_date: str | None) -> date | None:
    if not travel_date:
        return None

    value = str(travel_date).strip()
    if not value:
        return None

    for fmt in ("%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue

    return None


def _format_history_excerpt(history: list[dict] | None, limit: int = 6) -> str:
    if not history:
        return ""

    lines = []
    for item in history[-limit:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or item.get("type") or "message").strip().lower()
        content = str(item.get("content") or item.get("text") or "").strip()
        if content:
            lines.append(f"{role}: {content}")

    return "\n".join(lines)


def _live_status_simulation(db, train, train_no: str) -> dict:
    schedule = (
        db.query(TrainSchedule)
        .filter(TrainSchedule.train_no == train_no)
        .order_by(TrainSchedule.stop_number)
        .all()
    )
    if not schedule:
        return {
            "error": f"No schedule available for train {train_no}.",
            "trace_step": f"[RailRadar] Live status failed: no schedule found for {train_no}.",
        }

    current = schedule[0]
    next_stop = schedule[1] if len(schedule) > 1 else schedule[0]
    fallback_delay = random.choice([0, 3, 5, 8, 10, 15])
    return {
        "train_no": train_no,
        "train_name": train.train_name,
        "current_station": current.station_code,
        "next_station": next_stop.station_code,
        "delay_mins": fallback_delay,
        "status": "Running",
        "eta": f"Approx. {fallback_delay + 5} min",
        "last_updated": datetime.utcnow().isoformat(timespec="seconds"),
        "trace_step": f"[RailRadar] Used SQLite fallback live status simulation for {train.train_name} ({train_no}).",
    }


def resolve_train_number(train_no_or_name: str) -> str:
    if train_no_or_name is None:
        return train_no_or_name

    train_no_or_name = str(train_no_or_name).strip()
    if not train_no_or_name:
        return train_no_or_name

    if train_no_or_name.isdigit():
        return train_no_or_name

    cleaned_name = train_no_or_name
    
    # 1. Search in local DB
    with Session() as db:
        train = db.query(Train).filter(Train.train_name.ilike(cleaned_name)).first()
        if train:
            return train.train_no
        train = db.query(Train).filter(Train.train_name.ilike(f"%{cleaned_name}%")).first()
        if train:
            return train.train_no

    # 2. Check via RailRadar lookup API
    client = get_railradar_client()
    if client:
        try:
            lookup_data = client.train_lookup()
            if lookup_data and lookup_data.get("success"):
                trains_dict = lookup_data.get("data", {})
                for num, name in trains_dict.items():
                    if name.strip().lower() == cleaned_name.lower():
                        return num
                for num, name in trains_dict.items():
                    if cleaned_name.lower() in name.lower():
                        return num
        except Exception:
            pass

    return cleaned_name


def get_live_train_status(train_no: str) -> dict:
    train_no = resolve_train_number(train_no)
    with Session() as db:
        train = db.query(Train).filter(Train.train_no == train_no).first()
        train_name = train.train_name if train else "Unknown"

        client = get_railradar_client()
        if client:

            api_result = client.live_status(train_no)

            
            if not api_result.get("success"):

                if api_result.get("status_code") == 429:
                    return {
                        "error": "RailRadar API rate limit exceeded. Please wait a minute.",
                        "status_code": 429,
                        "trace_step": "[RailRadar] Live Status API rate limited."
                    }

            else:

                normalized = normalize_live_status(
                    api_result,
                    train_no,
                    train_name
                )
                
                if normalized:
                    return normalized

        if not train:
            return {
                "error": f"Train {train_no} not found.",
                "trace_step": f"[RailRadar] Live status failed: train {train_no} not found.",
            }

        base_url = os.environ.get("LIVE_TRAIN_API_BASE_URL", "").strip()
        timeout = int(os.environ.get("LIVE_TRAIN_API_TIMEOUT", "15"))
        headers = {}
        api_key = os.environ.get("LIVE_TRAIN_API_KEY", "").strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        if base_url:
            try:
                response = httpx.get(
                    f"{base_url.rstrip('/')}/{train_no}",
                    headers=headers,
                    timeout=timeout,
                )
                response.raise_for_status()
                data = response.json()
                normalized = _normalize_live_status_payload(data)
                if normalized:
                    return {
                        "train_no": train_no,
                        "train_name": train.train_name,
                        "current_station": normalized.get("current_station", "Unknown"),
                        "next_station": normalized.get("next_station", "Unknown"),
                        "delay_mins": normalized.get("delay_mins", 0),
                        "status": normalized.get("status", "Live status available"),
                        "eta": normalized.get("eta"),
                        "last_updated": normalized.get("last_updated"),
                        "trace_step": f"[RailRadar] Fetched live status for {train.train_name} ({train_no}) via LIVE_TRAIN_API.",
                    }
            except Exception:
                pass

        return _live_status_simulation(db, train, train_no)


def _search_trains_sqlite(db, src_station, dst_station, travel_date: str = None) -> dict:
    from sqlalchemy import and_

    parsed_date = _parse_travel_date(travel_date)

    trains_via_src = (
        db.query(TrainSchedule.train_no, TrainSchedule.stop_number)
        .filter(TrainSchedule.station_code == src_station.code)
        .subquery()
    )
    trains_via_dst = (
        db.query(TrainSchedule.train_no, TrainSchedule.stop_number)
        .filter(TrainSchedule.station_code == dst_station.code)
        .subquery()
    )
    matching = (
        db.query(trains_via_src.c.train_no)
        .join(
            trains_via_dst,
            and_(
                trains_via_src.c.train_no == trains_via_dst.c.train_no,
                trains_via_src.c.stop_number < trains_via_dst.c.stop_number,
            ),
        )
        .all()
    )
    train_nos = [r.train_no for r in matching]

    result_trains = []
    for tn in train_nos:
        train = db.query(Train).filter(Train.train_no == tn).first()
        if parsed_date and train and not check_train_runs_on_date(train.run_days, parsed_date):
            continue
        src_sched = (
            db.query(TrainSchedule)
            .filter(TrainSchedule.train_no == tn, TrainSchedule.station_code == src_station.code)
            .first()
        )
        dst_sched = (
            db.query(TrainSchedule)
            .filter(TrainSchedule.train_no == tn, TrainSchedule.station_code == dst_station.code)
            .first()
        )

        avail_data = {}
        if travel_date:
            try:
                td = date.fromisoformat(travel_date)
                avails = (
                    db.query(SeatAvailability)
                    .filter(SeatAvailability.train_no == tn, SeatAvailability.travel_date == td)
                    .all()
                )
                avail_data = {
                    a.travel_class: {"available": a.available, "waitlist": a.waitlist, "fare": a.fare}
                    for a in avails
                }
            except ValueError:
                pass

        result_trains.append({
            "train_no": train.train_no,
            "train_name": train.train_name,
            "from": src_station.name,
            "from_code": src_station.code,
            "to": dst_station.name,
            "to_code": dst_station.code,
            "departure": src_sched.departure if src_sched else "--:--",
            "arrival": dst_sched.arrival if dst_sched else "--:--",
            "run_days": train.run_days,
            "availability": avail_data,
        })

    trace = (
        f"[RailRadar] SQLite fallback: {src_station.name} → {dst_station.name}. "
        f"Found {len(result_trains)} direct train(s)."
    )
    return {
        "trains": result_trains,
        "source": src_station.name,
        "destination": dst_station.name,
        "trace_step": trace,
    }


def search_trains(
    source: str,
    destination: str,
    travel_date: str = None,
    user_message: str = "",
    trace_steps: list | None = None,
) -> dict:

    with Session() as db:
        src_station = _resolve_station(db, source)
        dst_station = _resolve_station(db, destination)

        if not src_station:
            return {
                "trains": [],
                "error": f"Station '{source}' not found.",
                "trace_step": f"[RailRadar] Station '{source}' not found.",
            }
        if not dst_station:
            return {
                "trains": [],
                "error": f"Station '{destination}' not found.",
                "trace_step": f"[RailRadar] Station '{destination}' not found.",
            }

        client = get_railradar_client()
        if client:
            api_result = client.trains_between(src_station.code, dst_station.code)

            if not api_result.get("success"):

                if api_result.get("status_code") == 429:
                    return {
                        "error": "RailRadar API rate limit exceeded. Please try again in about a minute.",
                        "status_code": 429,
                        "trace_step": "[RailRadar] RailRadar rate limit exceeded."
                    }

            else:
                normalized = normalize_trains_between(
                    api_result,
                    src_station.name,
                    dst_station.name,
                    src_station.code,
                    dst_station.code,
                )

                if normalized:
                    parsed_date = _parse_travel_date(travel_date)
                    if parsed_date:
                        normalized["trains"] = [
                            train
                            for train in normalized["trains"]
                            if check_train_runs_on_date(train.get("run_days"), parsed_date)
                        ]

                        if trace_steps is not None:
                            trace_steps.append(
                                f"[RailRadar] Applied travel date filter: {parsed_date.isoformat()}"
                            )

                        if not normalized["trains"]:
                            return {
                                "trains": [],
                                "trace_step": (
                                    f"[RailRadar] No trains run on {parsed_date.isoformat()}."
                                ),
                                "error": f"No trains run on {parsed_date.isoformat()}.",
                            }

                    # -------------------------------------------------------
                    # Apply time filtering if user requested one
                    # -------------------------------------------------------

                    constraint = parse_time_constraint(user_message)

                    if constraint:

                        normalized["trains"] = filter_trains_by_time(
                            normalized["trains"],
                            constraint,
                        )

                        if trace_steps is not None:
                            trace_steps.append(
                                f"[RailRadar] Applied time filter: "
                                f"{constraint['mode']} {constraint['time']}"
                            )

                        if not normalized["trains"]:
                            return {
                                "trains": [],
                                "trace_step": (
                                    f"[RailRadar] No trains found "
                                    f"{constraint['mode']} {constraint['time']}."
                                ),
                                "error": (
                                    f"No trains found "
                                    f"{constraint['mode']} "
                                    f"{constraint['time']}."
                                ),
                            }

                    return normalized

        return _search_trains_sqlite(db, src_station, dst_station, travel_date)


def _get_train_schedule_sqlite(db, train) -> dict:
    stops_rows = (
        db.query(TrainSchedule, Station)
        .join(Station, TrainSchedule.station_code == Station.code)
        .filter(TrainSchedule.train_no == train.train_no)
        .order_by(TrainSchedule.stop_number)
        .all()
    )

    stops = []

    for sched, station in stops_rows:

        arrival = sched.arrival or "--:--"
        departure = sched.departure or "--:--"

        # Ignore technical halts
        if (
            arrival != "--:--"
            and departure != "--:--"
            and arrival == departure
        ):
            continue

        stops.append({
            "stop_no": sched.stop_number,
            "station_code": station.code,
            "station": station.name,
            "city": station.city,
            "arrival": arrival,
            "departure": departure,
            "distance_km": sched.distance_km,
            "delay_mins": random.choice([0,0,0,5,10,15,20]),
        })

    return {
        "train_no": train.train_no,
        "train_name": train.train_name,
        "stops": stops,
        "trace_step": (
            f"[RailRadar] SQLite fallback schedule for {train.train_name} "
            f"({train.train_no}) — {len(stops)} stops."
        ),
    }


def _cache_train_schedule_in_db(normalized: dict) -> None:
    """
    Dynamically persist a train and its schedule fetched from the RailRadar API
    into the local SQLite database. This means the offline connecting-route solver
    automatically learns about new trains as users query them, without requiring
    any manual re-seeding.
    """
    train_no   = normalized.get("train_no")
    train_name = normalized.get("train_name", "Unknown")
    stops      = normalized.get("stops", [])
    if not train_no or not stops:
        return

    try:
        with Session() as db:
            # Upsert train record
            train = db.query(Train).filter(Train.train_no == train_no).first()
            if not train:
                src_code  = stops[0]["station_code"] if stops else "?"
                dest_code = stops[-1]["station_code"] if stops else "?"
                db.add(Train(
                    train_no=train_no,
                    train_name=train_name,
                    source_code=src_code,
                    dest_code=dest_code,
                    run_days="Daily",
                ))
                db.flush()

            # Only insert schedule if none exists yet
            existing_count = db.query(TrainSchedule).filter(
                TrainSchedule.train_no == train_no
            ).count()
            if existing_count == 0:
                for stop in stops:
                    code = stop.get("station_code", "")
                    if not code or code == "???":
                        continue
                    # Upsert station if missing
                    if not db.query(Station).filter(Station.code == code).first():
                        db.add(Station(
                            code=code,
                            name=stop.get("station", code),
                            city=stop.get("station", code),
                            state="Unknown",
                            zone="Unknown",
                        ))
                    db.flush()
                    db.add(TrainSchedule(
                        train_no=train_no,
                        stop_number=int(stop.get("stop_no", 0)),
                        station_code=code,
                        arrival=stop.get("arrival", "--:--"),
                        departure=stop.get("departure", "--:--"),
                        distance_km=int(stop.get("distance_km") or 0),
                    ))
                db.commit()
                print(f"[Cache] Persisted {len(stops)} stops for train {train_no} ({train_name}) to SQLite.")
                # Keep planner graph synchronized
                try:
                    refresh_graph_with_train(normalized)
                except Exception as exc:
                    print(f"[Planner] Graph refresh failed: {exc}")
    except Exception as exc:
        # Non-fatal: just log and continue
        print(f"[Cache] Warning: failed to persist train {train_no} to SQLite: {exc}")


def get_train_schedule(train_no: str) -> dict:
    train_no = resolve_train_number(train_no)
    client = get_railradar_client()

    if client:

        api_result = client.train_details(train_no)

        if not api_result.get("success"):

            if api_result.get("status_code") == 429:
                return {
                    "error": "RailRadar API rate limit exceeded. Please wait a minute.",
                    "status_code": 429,
                    "trace_step": "[RailRadar] Train Details API rate limited."
                }

        else:

            normalized = normalize_train_route(
                api_result,
                train_no
            )

            if normalized:

                _cache_train_schedule_in_db(normalized)

                return normalized

    with Session() as db:
        train = db.query(Train).filter(Train.train_no == train_no).first()
        if not train:
            return {
                "error": f"Train {train_no} not found.",
                "trace_step": f"[RailRadar] Train {train_no} not in DB.",
            }
        return _get_train_schedule_sqlite(db, train)


def planner_search(
    source: str,
    destination: str,
    travel_date: str | None = None,
) -> dict:
    """
    Planner adapter.

    RailRadar works with station names.

    Journey Planner works with station codes.

    This function bridges both.
    """

    with Session() as db:

        src_station = _resolve_station(db, source)
        dst_station = _resolve_station(db, destination)

        if not src_station or not dst_station:

            return {
                "success": False,
                "routes": [],
                "error": "Invalid station names.",
                "trace_step": (
                    "[Planner] Failed to resolve station names."
                ),
            }

        planner_result = plan_journey(
            source_code=src_station.code,
            destination_code=dst_station.code,
            travel_date=travel_date,
        )

        planner_result["source"] = src_station.name
        planner_result["destination"] = dst_station.name

        planner_result["trace_step"] = (
            f"[Planner] {src_station.code} → "
            f"{dst_station.code} "
            f"({planner_result['route_count']} routes)"
        )

        return planner_result
    

def find_connecting_routes(source: str, destination: str, travel_date: str = None) -> dict:
    with Session() as db:
        src_station = _resolve_station(db, source)
        dst_station = _resolve_station(db, destination)
        parsed_date = _parse_travel_date(travel_date)

        if not src_station or not dst_station:
            return {
                "routes": [],
                "error": "Invalid station names.",
                "trace_step": "[RailRadar] Connecting route search failed — invalid stations.",
            }

        trains_from_src = (
            db.query(TrainSchedule.train_no, TrainSchedule.stop_number)
            .filter(TrainSchedule.station_code == src_station.code)
            .all()
        )
        reachable = {}
        for t_no, src_stop in trains_from_src:
            leg1_obj = db.query(Train).filter(Train.train_no == t_no).first()
            if parsed_date and leg1_obj and not check_train_runs_on_date(leg1_obj.run_days, parsed_date):
                continue
            onward_stops = (
                db.query(TrainSchedule, Station)
                .join(Station, TrainSchedule.station_code == Station.code)
                .filter(TrainSchedule.train_no == t_no, TrainSchedule.stop_number > src_stop)
                .all()
            )
            for sched, stn in onward_stops:
                if stn.code not in reachable:
                    reachable[stn.code] = []
                reachable[stn.code].append({
                    "leg1_train": t_no,
                    "change_station": stn.name,
                    "change_code": stn.code,
                    "arrive_change": sched.arrival,
                })

        connecting_routes = []
        for inter_code, leg1_options in reachable.items():
            from sqlalchemy import and_

            trains_inter_to_dst = (
                db.query(TrainSchedule.train_no, TrainSchedule.stop_number, TrainSchedule.departure)
                .filter(TrainSchedule.station_code == inter_code)
                .subquery()
            )
            trains_dst = (
                db.query(trains_inter_to_dst.c.train_no, trains_inter_to_dst.c.departure)
                .join(
                    TrainSchedule,
                    and_(
                        trains_inter_to_dst.c.train_no == TrainSchedule.train_no,
                        TrainSchedule.station_code == dst_station.code,
                        trains_inter_to_dst.c.stop_number < TrainSchedule.stop_number,
                    ),
                )
                .all()
            )

            for leg1 in leg1_options[:2]:
                if parsed_date:
                    leg1_train_obj = db.query(Train).filter(Train.train_no == leg1["leg1_train"]).first()
                    if leg1_train_obj and not check_train_runs_on_date(leg1_train_obj.run_days, parsed_date):
                        continue
                for leg2_train, leg2_dep in trains_dst[:2]:
                    if leg2_train == leg1["leg1_train"]:
                        continue
                    leg2_obj = db.query(Train).filter(Train.train_no == leg2_train).first()
                    if parsed_date and leg2_obj and not check_train_runs_on_date(leg2_obj.run_days, parsed_date):
                        continue
                    leg1_obj = db.query(Train).filter(Train.train_no == leg1["leg1_train"]).first()

                    connecting_routes.append({
                        "leg1": {
                            "train_no": leg1["leg1_train"],
                            "train_name": leg1_obj.train_name if leg1_obj else "",
                            "from": src_station.name,
                            "to": leg1["change_station"],
                            "arrive": leg1["arrive_change"],
                        },
                        "change_station": leg1["change_station"],
                        "leg2": {
                            "train_no": leg2_train,
                            "train_name": leg2_obj.train_name if leg2_obj else "",
                            "from": leg1["change_station"],
                            "to": dst_station.name,
                            "depart": leg2_dep,
                        },
                    })
                    if len(connecting_routes) >= 3:
                        break
                if len(connecting_routes) >= 3:
                    break

        trace = (
            f"[RailRadar] Connecting route search: {src_station.name} → {dst_station.name}. "
            f"Found {len(connecting_routes)} option(s)."
        )
        return {
            "routes": connecting_routes,
            "source": src_station.name,
            "destination": dst_station.name,
            "trace_step": trace,
        }


RAILRADAR_SYSTEM = """
You are the RailRadar formatter for an Indian railway assistant.

Use only the provided tool output. Do not infer missing station names,
train numbers, dates, fares, or availability.
If the tool output is incomplete, say so explicitly.

Formatting rules:
- For train search results, use a Markdown table with train number, name,
    from, to, departure, arrival, run days, and availability.
- For schedules, use a compact bullet list or table of stops.
- For connecting routes, clearly separate Leg 1 and Leg 2 and keep the
    transfer station explicit.
- If seat availability is present, show it in a per-class table.
- Mention train number and name wherever they are available.
- Keep the answer concise, factual, and easy to scan.
"""

RAILRADAR_EXTRACTION_PROMPT = """
Extract travel parameters for the RailRadar assistant.

Use the conversation context to resolve references like "that train",
"same route", "there", "this train", or omitted station names.

Return ONLY valid JSON.
Do not include markdown.
Do not explain your reasoning.
Do not guess missing values.
Use null when information is unavailable.

Conversation context:
{history_context}

User message:
{user_message}

Return format:
{{
    "action": "search_trains | get_schedule | get_live_status | find_best_route",
    "source": null,
    "destination": null,
    "train_no": null,
    "date": null,
    "departure_after": null,
    "departure_before": null,
    "arrival_after": null,
    "arrival_before": null,
    "station": null,
    "train_name": null
}}

=========================
ACTION SELECTION RULES
=========================

Choose ONLY ONE action.

1. search_trains
Use when the user wants to search for trains between locations.

Examples:
- Trains from Ahmedabad to Delhi
- Find trains between Mumbai and Surat
- Morning trains to Jaipur
- Evening trains from Pune

Fill:
- source
- destination
- date if mentioned
- time filters if mentioned

------------------------------------

2. get_schedule

Use when the user asks for:

- train route
- route
- train schedule
- timetable
- stops
- stoppages
- stations
- station list
- complete route
- where does this train stop
- all stations

Examples:

User:
What is the route of 15018?

Output:
action = "get_schedule"

User:
Show the stations of Rajdhani Express.

Output:
action = "get_schedule"

User:
Train schedule for 22960.

Output:
action = "get_schedule"

Fill:
- train_no if available
- otherwise train_name

------------------------------------

3. get_live_status

Use ONLY when the user asks for LIVE or CURRENT running information.

Examples:

- live status
- current status
- running status
- where is train now
- where has train reached
- current location
- delay
- ETA
- expected arrival
- is train running late

Examples:

User:
Current status of 22960.

Output:
action = "get_live_status"

User:
Where is Kashi Express now?

Output:
action = "get_live_status"

Fill:
- train_no if available
- otherwise train_name

------------------------------------

4. find_best_route

Use when the user asks for journey planning rather than a specific train.

Examples:

- Best route from Ahmedabad to Katra
- Connecting trains to Srinagar
- Multi-leg journey
- Cheapest route
- Fastest route
- How can I travel from X to Y

Fill:
- source
- destination
- date if mentioned

=========================
IMPORTANT RULES
=========================

If the query contains BOTH "route" and a train number,
ALWAYS choose get_schedule.

If the query contains BOTH "schedule" and a train number,
ALWAYS choose get_schedule.

If the query contains BOTH "stations" and a train number,
ALWAYS choose get_schedule.

If the query asks for current position, delay, ETA, or live running,
ALWAYS choose get_live_status.

Never use get_live_status for a route or schedule request.

Never use get_schedule for a live status request.

Never guess train numbers or stations.

Always return valid JSON only.
"""


def run(user_message: str, history: list[dict], trace_steps: list[str], session_id: str = None) -> dict:
    llm = _get_llm()
    history_context = _format_history_excerpt(history)
    extract_prompt = RAILRADAR_EXTRACTION_PROMPT.format(
        history_context=history_context or "(none)",
        user_message=user_message,
    )
    try:
        if llm is None:
            raise Exception("No LLM")
        extract_resp = llm.invoke([HumanMessage(content=extract_prompt)])
        raw = extract_resp.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        params = json.loads(raw.strip())
        
        # Normalize extracted values
        
        params = normalize_params(params)
        query = user_message.lower()

        if any(word in query for word in [
            "route",
            "schedule",
            "stoppage",
            "stoppages",
            "station",
            "stations",
            "timetable",
        ]):
            if params.get("train_no") or params.get("train_name"):
                params["action"] = "get_schedule"

    except Exception:
        params = {"action": "search_trains", "source": None, "destination": None, "train_no": None, "date": None}

    action = params.get("action", "search_trains")
    if session_id:
        ctx = get_search_context(session_id)
        if ctx:
            if not params.get("source"):
                params["source"] = ctx.get("source")
            if not params.get("destination"):
                params["destination"] = ctx.get("destination")
            if not params.get("date"):
                stored_date = ctx.get("travel_date")
                params["travel_date_iso"] = stored_date
                params["date"] = normalize_date(stored_date)
            trace_steps.append(
                f"[Memory] Context restored: {params.get('source')} -> {params.get('destination')}"
            )

    trace_steps.append(
        f"[RailRadar] Selected Action: {action}"
    )

    trace_steps.append(
        f"[RailRadar] Parameters | "
        f"Source='{params.get('source')}', "
        f"Destination='{params.get('destination')}', "
        f"Train='{params.get('train_no')}', "
        f"Date='{params.get('date')}'"
    )

    if action == "get_schedule" and params.get("train_no"):
        tool_result = get_train_schedule(params["train_no"])
    elif action == "get_live_status" and params.get("train_no"):
        tool_result = get_live_train_status(params["train_no"])
    elif action == "find_best_route":
        tool_result = planner_search(
            params["source"],
            params["destination"],
            params.get("date"),
        )

        if not tool_result.get("success"):

            tool_result = find_connecting_routes(
                params["source"],
                params["destination"],
                params.get("date"),
            )
    else:
        if params.get("source") and params.get("destination"):
            tool_result = search_trains(params["source"], params["destination"], params.get("date"))
            if tool_result:
                trace_steps.append(
                    f"[RailRadar] Direct trains found : {len(tool_result)}"
                )
            else:
                trace_steps.append(
                    "[RailRadar] No direct trains found."
                )
            if session_id and "error" not in tool_result:
                save_search_context(
                    session_id=session_id,
                    source=params["source"],
                    destination=params["destination"],
                    travel_date=(
                        params.get("travel_date_iso")
                        or params.get("date")
                    ),
                )
                trace_steps.append(
                    f"[Memory] Saved route context: {params['source']} → {params['destination']}"
                )
        else:
            tool_result = {
                "error": "Could not extract source/destination from message.",
                "trace_step": "[RailRadar] Extraction failed.",
            }

    trace_steps.append(tool_result.get("trace_step", ""))

    trains_found = tool_result.get("trains", [])

    connecting = None

    if (
        action == "search_trains"
        and len(trains_found) == 0
        and params.get("source")
        and params.get("destination")
    ):

        trace_steps.append(
            "[RailRadar] No direct trains found."
        )

        trace_steps.append(
            "[Planner] Starting route planning."
        )

        trace_steps.append(
            f"[Planner] Source      : {params['source']}"
        )

        trace_steps.append(
            f"[Planner] Destination : {params['destination']}"
        )

        trace_steps.append(
            f"[Planner] Travel Date : {params.get('travel_date_iso') or params.get('date') or 'Not specified'}"
        )

        planner_result = planner_search(
            params["source"],
            params["destination"],
            params.get("travel_date_iso")
            or params.get("date"),
        )
        if planner_result.get("success"):

            trace_steps.append(
                "[Planner] Route planning completed successfully."
            )

            trace_steps.append(
                f"[Planner] Routes Found : {planner_result.get('route_count', 0)}"
            )

        trace_steps.append(
            planner_result.get("trace_step", "")
        )

        if planner_result.get("success"):

            trace_steps.append(
                "[Planner] Planner returned routes."
            )

            connecting = planner_result

        else:

            trace_steps.append(
                "[Planner] No valid route found."
            )

            trace_steps.append(
                "[Planner] Switching to legacy connecting route search."
            )

            trace_steps.append(
                "[RailRadar] Falling back to legacy connector."
            )

            connecting = find_connecting_routes(
                params["source"],
                params["destination"],
                params.get("date"),
            )

            trace_steps.append(
                "[Legacy] Connecting route search completed."
            )

            if connecting.get("routes"):

                trace_steps.append(
                    f"[Legacy] Routes Found : {len(connecting['routes'])}"
                )

            else:

                trace_steps.append(
                    "[Legacy] No connecting routes found."
                )

            if connecting.get("trace_step"):

                trace_steps.append(connecting["trace_step"])
        
# Handle API failures gracefully

    if tool_result.get("status_code") == 429:

        return {
            "response": (
                "⚠️ RailRadar API request limit has been reached.\n\n"
                "Please wait about a minute before trying again."
            ),
            "intent": "railradar",
            "trace_steps": trace_steps,
            "raw_data": {},
            "sources": [],
        }

    if tool_result.get("error"):

        return {
            "response": f"❌ {tool_result['error']}",
            "intent": "railradar",
            "trace_steps": trace_steps,
            "raw_data": {},
            "sources": [],
        }
    
    context_str = f"Tool output:\n{tool_result}"

    if connecting:

        if connecting.get("planner") == "journey_planner":

            context_str += (
                "\n\nJourney Planner Result:\n"
                f"{connecting}"
            )

        else:

            context_str += (
                "\n\nLegacy Connecting Routes:\n"
                f"{connecting}"
            )

    try:
        if llm is None:
            raise Exception("LLM not available. Please set GROQ_API_KEY.")
        format_resp = llm.invoke([
            SystemMessage(content=RAILRADAR_SYSTEM),
            HumanMessage(content=(
                f"User asked: \"{user_message}\"\n\n{context_str}\n\n"
                "Write a helpful, formatted markdown response."
            )),
        ])
        final_text = format_resp.content
    except Exception as e:
        final_text = (
            "**(Offline Fallback Mode Activated - AI Quota Reached)**\n\n"
            "I found the following raw data for your query:\n```json\n"
            f"{json.dumps(tool_result, indent=2)}\n```"
        )
        trace_steps.append(f"[RailRadar] Formatting failed due to API error: {e}")

    return {
        "response": final_text,
        "intent": "railradar",
        "trace_steps": trace_steps,
        "raw_data": tool_result,
        "sources": [],
    }


def clean_route(stops):

    cleaned = []

    for stop in stops:

        arr = stop.get("arrival")
        dep = stop.get("departure")

        if arr == dep:
            continue

        cleaned.append(stop)

    return cleaned
