"""
main.py — FastAPI Application Entry Point
==========================================
Coordinates the Supervisor and Sub-agents. Includes:
  - CORS middleware for React frontend connectivity
  - Intent classification routing for chat messages
  - Chat logs persistence in SQLite
  - Active PNR watchlist API
  - WebSocket endpoints for live PNR status shift notifications
  - Background scheduler simulating PNR status changes and notifying active clients
"""

import os
import sys
import json
import asyncio
import random
from typing import List, Dict
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

# Make local backend imports work when running from the repo root
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

load_dotenv()

from database import init_db, Session as DBSession, ChatSession, PNRWatchlist, PNRRecord, Train
from bootstrap import run_bootstrap
from agents import supervisor, railradar, prs, rag, guardrail

app = FastAPI(title="Indian Railway Assistant Bot API")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For local development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Database on Startup
def reset_runtime_state() -> None:
    """Clear transient conversation state so each server start feels like a fresh session."""
    with DBSession() as db:
        db.query(ChatSession).delete()
        db.query(PNRWatchlist).delete()
        db.commit()

    try:
        from services.context_manager import collection
        existing = collection.get()
        ids = existing.get("ids", []) or []
        if ids:
            collection.delete(ids=ids)
    except Exception as exc:
        print(f"[Startup] Failed to clear search context: {exc}")

    active_connections.clear()


@app.on_event("startup")
async def startup_event():
    run_bootstrap()
    reset_runtime_state()

    # Pre-build the in-memory railway network graph so the Journey Planner
    # BFS has all train/schedule data ready without hitting SQLite on each search.
    try:
        from services.graph_builder import build_network_graph
        build_network_graph()
    except Exception as graph_err:
        print(f"[Startup] Warning: failed to build railway graph — {graph_err}")

    asyncio.create_task(pnr_watcher_loop())

# Active WebSocket connections: session_id -> List[WebSocket]
active_connections: Dict[str, List[WebSocket]] = {}

class MessageHistoryItem(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    message: str
    session_id: str
    history: List[MessageHistoryItem]

class WatchlistRequest(BaseModel):
    pnr: str
    session_id: str

@app.get("/")
def read_root():
    return {"status": "online", "service": "Railway Assistant Bot API"}

@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest):
    session_id = request.session_id
    user_message = request.message
    history_list = [h.dict() for h in request.history]
    
    # 1. Log user message to DB
    with DBSession() as db:
        db.add(ChatSession(
            session_id=session_id,
            role="user",
            content=user_message
        ))
        db.commit()

    # 2. Classify intent via Supervisor
    try:
        classify_result = supervisor.classify_intent(user_message, history_list)
        intent = classify_result["intent"]
        trace_steps = [classify_result["trace_step"]]
    except Exception as e:
        fallback = supervisor._fallback_classify(user_message)
        intent = fallback["intent"]
        trace_steps = [f"[Supervisor] Fallback intent classification used because: {e}"]
    
    agent_response = {}
    
    # 3. Route to the appropriate sub-agent
    try:
        if intent == "greeting":
            agent_response = supervisor.handle_greeting()
        elif intent == "railradar":
            agent_response = railradar.run(user_message, history_list, trace_steps, session_id=session_id)
        elif intent == "prs":
            agent_response = prs.run(user_message, history_list, trace_steps, session_id=session_id)
        elif intent == "rag":
            agent_response = rag.run(user_message, history_list, trace_steps)
        elif intent == "guardrail":
            agent_response = guardrail.run(user_message, history_list, trace_steps)
        else:
            agent_response = rag.run(user_message, history_list, trace_steps)
    except Exception as e:
        agent_response = {
            "response": f"Apologies, I encountered an internal error while processing your request: {str(e)}",
            "intent": intent,
            "trace_steps": trace_steps + [f"[System Error] Agent execution failed: {str(e)}"],
            "raw_data": {"error": str(e)},
            "sources": []
        }
    
    # 4. Log assistant response and trace to DB
    with DBSession() as db:
        db.add(ChatSession(
            session_id=session_id,
            role="assistant",
            content=agent_response.get("response", ""),
            intent=intent,
            agent_trace=json.dumps(agent_response.get("trace_steps", []))
        ))
        db.commit()
        
    return agent_response

@app.get("/api/pnr-watchlist/{session_id}")
def get_watchlist(session_id: str):
    """Retrieve all watched PNRs for a specific session."""
    with DBSession() as db:
        watches = db.query(PNRWatchlist).filter(
            PNRWatchlist.session_id == session_id,
            PNRWatchlist.is_active == True
        ).all()
        
        result = []
        for w in watches:
            pnr_record = db.query(PNRRecord).filter(PNRRecord.pnr == w.pnr).first()
            if pnr_record:
                train = db.query(Train).filter(Train.train_no == pnr_record.train_no).first()
                result.append({
                    "pnr": w.pnr,
                    "passenger_name": pnr_record.passenger_name,
                    "train_no": pnr_record.train_no,
                    "train_name": train.train_name if train else "Unknown Train",
                    "travel_date": pnr_record.travel_date.isoformat(),
                    "last_status": w.last_status,
                    "current_status": pnr_record.booking_status,
                    "coach": pnr_record.coach,
                    "seat_no": pnr_record.seat_no,
                    "added_at": w.created_at.isoformat()
                })
        return result

@app.post("/api/pnr-watchlist")
def add_to_watchlist(request: WatchlistRequest):
    """Add a PNR directly to the watchlist."""
    result = prs.add_pnr_to_watchlist(request.pnr, request.session_id)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result

@app.get("/api/live-train/{train_no}")
def get_live_train_status(train_no: str):
    """Return live-ish train status data for a given train number."""
    result = railradar.get_live_train_status(train_no)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result

# ── WebSocket Manager ───────────────────────────────────────────────────────────
@app.websocket("/api/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()
    if session_id not in active_connections:
        active_connections[session_id] = []
    active_connections[session_id].append(websocket)
    
    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[WS] Connection error for {session_id}: {e}")
    finally:
        if session_id in active_connections and websocket in active_connections[session_id]:
            active_connections[session_id].remove(websocket)
            if not active_connections[session_id]:
                del active_connections[session_id]

# ── PNR Background Status Watcher / Simulator ──────────────────────────────────
async def pnr_watcher_loop():
    """
    Background loop checking active PNR watchlist items every 15 seconds.
    Simulates random status changes for demo purposes (e.g., WL to RAC or CNF).
    Sends WebSocket alerts to connected clients when a status change is detected.
    """
    print("[Watcher] Background PNR Watcher scheduler started.")
    await asyncio.sleep(5)  # Let server startup stabilize
    
    while True:
        try:
            with DBSession() as db:
                watchlist_items = db.query(PNRWatchlist).filter(PNRWatchlist.is_active == True).all()
                
                for item in watchlist_items:
                    pnr_rec = db.query(PNRRecord).filter(PNRRecord.pnr == item.pnr).first()
                    if not pnr_rec:
                        continue
                        
                    current_status = pnr_rec.booking_status
                    if "WL" in current_status or "RAC" in current_status:
                        if random.random() < 0.25:
                            old_status = current_status
                            if "WL" in current_status:
                                new_status = random.choice(["RAC/2", "CNF"])
                            else:
                                new_status = "CNF"
                                
                            if new_status == "CNF":
                                pnr_rec.coach = random.choice(["B1", "B2", "A1", "C2"])
                                pnr_rec.seat_no = str(random.randint(1, 64))
                            elif "RAC" in new_status:
                                pnr_rec.coach = "RD"
                                pnr_rec.seat_no = "RAC " + new_status.split("/")[-1]
                                
                            pnr_rec.booking_status = new_status
                            db.commit()
                            print(f"[Watcher] Simulated PNR status change for {item.pnr}: {old_status} -> {new_status}")

                    latest_status = pnr_rec.booking_status
                    if latest_status != item.last_status:
                        print(f"[Watcher] Status shift detected for PNR {item.pnr}: {item.last_status} -> {latest_status}")
                        
                        old_saved_status = item.last_status
                        item.last_status = latest_status
                        db.commit()
                        
                        if item.session_id in active_connections:
                            payload = {
                                "type": "pnr_alert",
                                "pnr": item.pnr,
                                "passenger_name": pnr_rec.passenger_name,
                                "train_no": pnr_rec.train_no,
                                "old_status": old_saved_status,
                                "new_status": latest_status,
                                "coach": pnr_rec.coach,
                                "seat_no": pnr_rec.seat_no
                            }
                            
                            for connection in active_connections[item.session_id]:
                                try:
                                    await connection.send_text(json.dumps(payload))
                                except Exception as e:
                                    print(f"[Watcher] Failed to send WS message: {e}")
                                    
        except Exception as e:
            print(f"[Watcher] Error in watchlist checker: {e}")
            
        await asyncio.sleep(15)
