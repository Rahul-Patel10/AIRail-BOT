# Railway Assistant Implementation Plan

## Goal
Make the bot answer correctly first, then improve UX, then clean up architecture.

## Phase 1: Reliability First

### 1. RailRadar Agent
Focus files:
- `backend/agents/railradar.py`
- `backend/services/query_normalizer.py`
- `backend/services/railradar_adapter.py`
- `backend/services/context_manager.py`

Tasks:
- Fix train search, route, live status, and station board routing.
- Improve follow-up handling for multi-turn queries.
- Make API failure handling explicit instead of silently falling back to misleading data.
- Standardize the output shape across RailRadar flows.

Done when:
- Train search returns correct results.
- Train route and live status resolve train names reliably.
- Follow-up questions reuse stored context.
- Offline fallback is clearly labeled.

### 2. Parser
Focus files:
- `backend/services/query_normalizer.py`
- `backend/agents/railradar.py`

Tasks:
- Normalize relative dates such as today, tomorrow, next Friday.
- Parse time windows like after 5 PM and before Surat.
- Detect train-type keywords such as Rajdhani and Vande Bharat.
- Return structured fields for downstream routing.

Done when:
- Time-aware and date-aware queries map to structured parameters.
- Search and sorting decisions no longer depend on weak string matching.

### 3. Adapter Layer
Focus files:
- `backend/services/railradar_adapter.py`

Tasks:
- Make search, route, live status, and board responses consistent.
- Use stable field names wherever possible.
- Preserve the metadata the frontend needs for display.

Done when:
- The frontend can render each endpoint with the same general contract.

### 4. Context Manager
Focus files:
- `backend/services/context_manager.py`
- `backend/agents/railradar.py`

Tasks:
- Store `train_no`, `train_name`, `last_action`, `selected_train`, and `selected_station`.
- Reuse stored context for follow-up queries.
- Prevent stale context from overriding a new explicit request.

Done when:
- Queries like “where is it now?” work after a route or train lookup.

### 5. Supervisor
Focus files:
- `backend/agents/supervisor.py`
- `backend/main.py`

Tasks:
- Prefer regex and rules before LLM fallback.
- Make intent routing more deterministic.
- Keep the LLM as the last resort.

Done when:
- PNR, rail search, policy, and guardrail queries route consistently.

## Phase 2: Correctness and UX

### 6. Session Persistence
Focus files:
- `frontend/src/App.jsx`

Tasks:
- Stop creating a fresh session on every page load.
- Preserve chat history across refreshes.
- Keep message storage tied to the same session.

Done when:
- Reloading the page does not wipe the conversation.

### 7. Source and Trace Panels
Focus files:
- `frontend/src/App.jsx`
- `backend/agents/rag.py`

Tasks:
- Align frontend expectations with backend source payloads.
- Show real retrieval evidence in the source panel.
- Improve the execution trace so it reflects actual agent behavior.

Done when:
- The source panel and trace panel always show valid data.

### 8. Error Handling
Focus files:
- `frontend/src/App.jsx`
- `backend/agents/prs.py`
- `backend/agents/rag.py`
- `backend/agents/railradar.py`

Tasks:
- Show explicit failures instead of generic fallback text where possible.
- Surface watchlist fetch errors.
- Separate live API failures from offline fallback mode.

Done when:
- Users can tell what failed and why.

## Phase 3: Stability Hardening

### 9. Cache Safety
Focus files:
- `backend/services/cache.py`
- `backend/services/railradar_client.py`

Tasks:
- Add a cache size limit or eviction strategy.
- Make cache keys deterministic.
- Keep cache entries reliable across repeated calls.

Done when:
- Cache behavior is predictable and memory usage stays bounded.

### 10. WebSocket Cleanup
Focus files:
- `backend/main.py`
- `frontend/src/App.jsx`

Tasks:
- Prevent reconnect loops after intentional unmounts.
- Clean stale websocket connections.
- Make alert delivery more robust on disconnects.

Done when:
- One browser session maps to one clean websocket lifecycle.

### 11. Null-Safety and Response Guards
Focus files:
- `backend/services/station_resolver.py`
- `backend/services/railradar_adapter.py`
- `backend/agents/prs.py`
- `backend/agents/rag.py`

Tasks:
- Guard Chroma and API response shape assumptions.
- Handle missing metadata safely.
- Keep agent fallbacks from crashing on bad payloads.

Done when:
- Unexpected payload shapes fail gracefully.

## Phase 4: Portfolio Polish

### 12. Documentation
Focus files:
- `README.md`

Tasks:
- Update setup and run instructions.
- Document the main features and flow.
- Add screenshots, architecture notes, and a short demo section.

Done when:
- A reviewer can understand and run the project quickly.

## Recommended Execution Order
1. RailRadar Agent
2. Parser
3. Adapter Layer
4. Context Manager
5. Supervisor
6. Session Persistence
7. Source and Trace Panels
8. Error Handling
9. Cache Safety
10. WebSocket Cleanup
11. Null-Safety and Response Guards
12. Documentation

## First Milestone
The project is ready for the next stage when these are true:
- Train search answers are correct.
- Route and live-status queries resolve reliably.
- Follow-up questions reuse context.
- The frontend keeps the same session across refreshes.
- The source and trace panels display real data.
