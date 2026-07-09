from __future__ import annotations


def format_train_search(tool_result: dict, user_message: str | None = None) -> str:
    """
    Fallback formatter for direct train search results.
    Used when the Groq LLM is unavailable or rate-limited.
    """
    trains = tool_result.get("trains", []) or []
    if not trains:
        if tool_result.get("error"):
            return f"❌ {tool_result['error']}"
        return "No trains matched the requested route and time."

    source = tool_result.get("source") or ""
    destination = tool_result.get("destination") or ""
    header = (
        f"### 🚆 Trains from {source} to {destination}"
        if source and destination
        else "### 🚆 Matching trains"
    )
    lines = [header, ""]
    lines.append("| Train | Departure | Arrival | Days |")
    lines.append("| --- | --- | --- | --- |")

    for train in trains[:8]:
        train_no   = train.get("train_no")   or "—"
        train_name = train.get("train_name") or "Unknown"
        departure  = train.get("departure")  or "--:--"
        arrival    = train.get("arrival")    or "--:--"
        days       = train.get("run_days")   or "Daily"
        lines.append(f"| {train_no} {train_name} | {departure} | {arrival} | {days} |")

    return "\n".join(lines)


def format_connecting_journeys(
    journeys: list[dict],
    source: str = "",
    destination: str = "",
) -> str:
    """
    Fallback formatter for connecting-route (multi-leg) journey results.
    Produces a structured markdown response when the Groq LLM is unavailable.

    Parameters
    ----------
    journeys    : List of journey dicts from journey_planner.find_best_route().
    source      : Human-readable source station name or code.
    destination : Human-readable destination station name or code.

    Returns
    -------
    A markdown string suitable for direct display in the chat UI.
    """
    if not journeys:
        return (
            f"❌ No connecting routes found from **{source}** to **{destination}**.\n\n"
            "This may mean there are no trains with compatible interchange timings "
            "in the current database. Try adjusting the travel date or stations."
        )

    route_label = f"from **{source}** to **{destination}**" if source and destination else ""
    lines = [
        f"### 🔗 Connecting Journey Options {route_label}",
        "",
        f"Found **{len(journeys)}** connecting route(s). "
        "Direct trains were not available — these routes require a train change.\n",
    ]

    for idx, journey in enumerate(journeys, start=1):
        changes    = journey.get("changes", 0)
        dist       = journey.get("total_distance_km", 0)
        travel_min = journey.get("total_travel_mins", 0)
        wait_min   = journey.get("total_waiting_mins", 0)
        score      = journey.get("score", 0)
        summary    = journey.get("summary", "")
        segments   = journey.get("segments", [])
        interchanges = journey.get("interchange_stations", [])

        change_str = f"{changes} change{'s' if changes != 1 else ''}"

        lines.append(f"---")
        lines.append(
            f"#### 🚉 Route {idx} — {change_str} | {dist} km | "
            f"~{travel_min // 60}h {travel_min % 60}m travel | "
            f"~{wait_min} min wait"
        )
        lines.append("")

        # Segment table
        lines.append("| Leg | Train | From | Dep | To | Arr | Dist |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        for i, seg in enumerate(segments, start=1):
            train_label = f"{seg.get('train_name', '')} ({seg.get('train_no', '')})"
            lines.append(
                f"| {i} | {train_label} | {seg.get('from_station', '')} | "
                f"{seg.get('departure', '--:--')} | {seg.get('to_station', '')} | "
                f"{seg.get('arrival', '--:--')} | {seg.get('distance_km', 0)} km |"
            )

        lines.append("")
        if interchanges:
            lines.append(
                f"🔄 **Change stations:** {' → '.join(interchanges)}"
            )
        lines.append(f"📊 **Route score:** {score:.0f} (lower is better)")
        lines.append("")

    lines.append(
        "> ℹ️ Routes are ranked by: fewest changes → shortest time → shortest distance → least waiting."
    )
    return "\n".join(lines)
