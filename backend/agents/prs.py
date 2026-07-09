import os
import json
import re
from datetime import datetime
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from dotenv import load_dotenv
from services.pnr_service import get_live_pnr_status
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import Session, PNRRecord, PNRWatchlist, Train, Station

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


def _resolve_station_name(db, code: str) -> str:
    if not code:
        return "Unknown"
    station = db.query(Station).filter(Station.code == code).first()
    return station.name if station else code


def check_pnr_status(pnr: str) -> dict:
    """
    Fetch live PNR status from NTES.
    Falls back gracefully if anything fails.
    """

    tool_result = get_live_pnr_status(pnr)

    if "error" in tool_result:
        return tool_result

    pnr_data = tool_result.get("pnr_data", {})

    # Resolve station names from your local database
    with Session() as db:

        from_code = pnr_data.get("from_code")
        to_code = pnr_data.get("to_code")

        pnr_data["from_station"] = _resolve_station_name(
            db,
            from_code,
        )

        pnr_data["to_station"] = _resolve_station_name(
            db,
            to_code,
        )

        # Optional enrichment:
        train = (
            db.query(Train)
            .filter(Train.train_no == pnr_data.get("train_no"))
            .first()
        )

        if train and not pnr_data.get("train_name"):
            pnr_data["train_name"] = train.train_name

    tool_result["pnr_data"] = pnr_data

    return tool_result


def add_pnr_to_watchlist(pnr: str, session_id: str) -> dict:
    if not re.fullmatch(r"\d{10}", pnr):
        return {"error": "Invalid PNR. Must be a 10-digit number."}

    with Session() as db:
        record = db.query(PNRRecord).filter(PNRRecord.pnr == pnr).first()
        if not record:
            return {"error": f"PNR {pnr} not found in database."}

        existing = (
            db.query(PNRWatchlist)
            .filter(PNRWatchlist.pnr == pnr, PNRWatchlist.session_id == session_id)
            .first()
        )

        if existing:
            existing.is_active = True
            existing.last_status = record.booking_status
            existing.updated_at = datetime.utcnow()
        else:
            db.add(PNRWatchlist(
                pnr=pnr,
                session_id=session_id,
                last_status=record.booking_status,
                is_active=True,
            ))

        db.commit()

    return {
        "success": True,
        "pnr": pnr,
        "message": f"PNR {pnr} added to your watchlist. You will be notified of status changes.",
    }


PRS_SYSTEM = """
You are AIrail, an Indian Railways assistant specialized in PNR and booking status.

You have access to this tool:
- check_pnr_status:
  Fetches LIVE PNR information from NTES including:

  • Booking status
  • Current status
  • Coach
  • Berth
  • Seat
  • Train details
  • Boarding station
  • Destination
  • Chart preparation status
  • Journey class
  • Fare
  • Passenger information

## How to Use the Tool

A PNR number is always exactly 10 digits. If the user provides a PNR that is not 10 digits, do not call the tool — ask them to verify the number first.

Never infer or predict PNR status from memory. Always use the tool result before responding.

## How to Reason

Before replying, understand what the status means for the user’s journey. A confirmed ticket, waitlisted ticket, RAC ticket, or cancelled ticket all require different guidance. Think about whether the user needs reassurance, next steps, or a clear explanation of their booking condition.

## How to Respond

- State the booking status clearly first: confirmed, waitlisted, RAC, or cancelled
- Include coach, berth, and seat information when available
- Mention whether the chart has been prepared if that information is available
- Keep responses calm, clear, and practical
- If multiple passengers are on the same PNR, present each passenger's status clearly
- Use concise markdown formatting when helpful

## Handling Errors

If the tool returns an error:
- Explain it in plain language
- Ask the user to double-check the PNR if it looks invalid
- Suggest verifying directly on the official booking platform if needed
- Never leave the user without a next step

## What You Do Not Do

- Never guess a PNR status
- Never present assumed data as live data
- Never ignore passenger-level details on multi-passenger PNRs
"""


def run(user_message: str, history: list[dict], trace_steps: list[str], session_id: str = None) -> dict:
    llm = _get_llm()

    pnr_match = re.search(r"\b\d{10}\b", user_message)
    pnr = pnr_match.group(0) if pnr_match else None

    if not pnr:
        return {
            "response": "Could you please provide your 10-digit PNR number?",
            "intent": "prs",
            "trace_steps": trace_steps + ["[PRS] No PNR found in user message."],
            "raw_data": {},
            "sources": [],
        }

    trace_steps.append(f"[PRS] Extracted PNR: {pnr}")
    tool_result = check_pnr_status(pnr)
    trace_steps.append(tool_result.get("trace_step", ""))

    watch_requested = bool(re.search(r"\bwatch\b", user_message, re.IGNORECASE))
    watch_result = None
    if watch_requested and session_id and "error" not in tool_result:
        watch_result = add_pnr_to_watchlist(pnr, session_id)
        if watch_result.get("success"):
            trace_steps.append(f"[PRS] PNR {pnr} added to watchlist.")
        else:
            trace_steps.append(f"[PRS] Watchlist add failed: {watch_result.get('error')}")

    context_str = f"Tool output for PNR {pnr}:\n{json.dumps(tool_result, indent=2)}"
    if watch_result:
        context_str += f"\n\nWatchlist result:\n{json.dumps(watch_result, indent=2)}"

    try:
        if llm is None:
            raise Exception("LLM not available. Please set GROQ_API_KEY.")
        format_resp = llm.invoke([
            SystemMessage(content=PRS_SYSTEM),
            HumanMessage(content=(
                f"User asked: \"{user_message}\"\n\n{context_str}\n\n"
                "Write a helpful markdown response."
                + (" Mention that the PNR was added to the watchlist." if watch_result and watch_result.get("success") else "")
            )),
        ])
        final_text = format_resp.content
    except Exception as e:
        final_text = (
            "**(Offline Fallback Mode Activated - AI Quota Reached)**\n\n"
            f"Here is the raw data for PNR {pnr}:\n```json\n"
            f"{json.dumps(tool_result, indent=2)}\n```"
        )
        if watch_result and watch_result.get("success"):
            final_text += f"\n\nPNR {pnr} has been added to your watchlist."
        trace_steps.append(f"[PRS] Formatting failed: {e}")

    return {
        "response": final_text,
        "intent": "prs",
        "trace_steps": trace_steps,
        "raw_data": tool_result,
        "sources": [],
    }
