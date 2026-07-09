# Railway Assistant Bot

An AI-powered Indian Railway assistant that supports train search, PNR status lookup, IRCTC policy Q&A, live alerts, and route assistance through a hybrid architecture built on FastAPI, React, SQLite, ChromaDB, Groq, and RailRadar.

## Overview

Railway Assistant Bot is a conversational system designed to answer common Indian Railways travel questions with a mix of structured data, retrieval-augmented generation, and live API enrichment.

It solves a practical problem: railway travelers often need quick answers across multiple data sources, such as train schedules, booking status, policy rules, seat availability, and route options. Instead of forcing the user to manually check separate systems, the bot routes each query to the most suitable agent and returns a compact, traceable response.

### Core capabilities

- Train search and schedule lookup
- Live train status retrieval
- PNR status lookup and watchlist alerts
- IRCTC policy and FAQ answering through retrieval
- Unsafe/off-domain request refusal through a guardrail agent
- Session-aware follow-up query handling
- Browser-based chat UI with voice input, read-aloud output, and WebSocket alerts

### Why this architecture was chosen

The repository uses a layered design because the problem spans multiple data types and trust levels:

- Structured data is best served from SQLite.
- Semi-structured live data is best fetched from RailRadar when available.
- Policy answers need retrieval from documents rather than free-form generation.
- Intent routing benefits from a dedicated supervisor so each request is sent to the right specialist.
- Fallback logic keeps the assistant useful even when external services are unavailable.

## Technology Stack

| Layer | Technology | Purpose |
|---|---|---|
| Frontend | React, Vite, Lucide React | Chat UI, watchlist panel, trace viewer, voice features |
| Backend | FastAPI, Uvicorn, Pydantic | HTTP API, WebSockets, request validation |
| ORM / DB | SQLAlchemy, SQLite | Persistent relational data and local seed data |
| Vector DB | ChromaDB | FAQ retrieval and search-context memory |
| LLM | Groq via LangChain | Intent classification and response formatting |
| Retrieval | FlashRank | Reranking of FAQ matches |
| External API | RailRadar API | Live train data and schedule enrichment |

## High-Level Architecture

```text
+--------+
| User   |
+--------+
    |
    v
+--------------------+
| React Frontend     |
| Chat / Alerts UI   |
+--------------------+
    |
    v
+--------------------+
| FastAPI Backend    |
| /api/chat, PNR, WS |
+--------------------+
    |
    v
+--------------------+
| Supervisor Agent   |
| Intent routing     |
+--------------------+
  |        |        |        |
  |        |        |        |
  v        v        v        v
+-----------+ +------------+ +-----------+ +------------+ +------------+
| Greeting  | | RailRadar  | | PRS       | | RAG        | | Guardrail  |
| direct    | | train flow | | PNR flow  | | FAQ flow   | | refusal    |
+-----------+ +------------+ +-----------+ +------------+ +------------+
                   |
                   v
            +------------------+
            | Services Layer   |
            | cache, resolver, |
            | planner, client  |
            +------------------+
              |       |       |
              v       v       v
          SQLite   RailRadar   ChromaDB
                      API
              |
              v
           Response
```

## Request Flow

```text
User
  |
  v
Frontend
  |
  v
POST /api/chat
  |
  v
FastAPI chat endpoint
  |
  +--> write user message to SQLite chat log
  |
  +--> Supervisor intent classification
         |
         +--> Groq JSON classification when available
         +--> fallback rule-based classification when LLM fails
  |
  v
Selected agent
  |
  +--> Greeting
  |      |
  |      +--> direct canned response
  |
  +--> RailRadar
  |      |
  |      +--> extract intent parameters
  |      +--> normalize dates, times, stations
  |      +--> cache lookup
  |      +--> rate limiter
  |      +--> RailRadar API or SQLite fallback
  |      +--> save search context
  |
  +--> PRS
  |      |
  |      +--> extract 10-digit PNR
  |      +--> SQLite PNR lookup
  |      +--> optional watchlist insert
  |
  +--> RAG
  |      |
  |      +--> Chroma FAQ retrieval
  |      +--> FlashRank reranking
  |      +--> Groq response formatting or offline fallback
  |
  +--> Guardrail
         |
         +--> refusal response for off-domain or unsafe prompts
  |
  v
Formatter / final response text
  |
  +--> raw_data
  +--> trace_steps
  +--> sources
  |
  v
Frontend
  |
  +--> render assistant message
  +--> update execution trace panel
  +--> update sources panel
  +--> refresh watchlist when needed
```

## AI Decision Flow

```text
User message
  |
  v
Intent Detection
  |
  +--> unsafe / unrelated / injection
  |       |
  |       v
  |   Guardrail
  |
  v
Context Recovery
  |
  +--> last 4 chat turns
  +--> saved RailRadar session context
  |
  v
Query Normalization
  |
  +--> dates
  +--> times
  +--> station aliases
  +--> train number coercion
  |
  v
Station Resolution
  |
  +--> Chroma fuzzy match
  +--> SQLite fallback
  |
  v
Train Resolution
  |
  +--> direct train number
  +--> train name lookup
  +--> RailRadar lookup fallback
  |
  v
Agent Selection
  |
  +--> RailRadar
  +--> PRS
  +--> RAG
  +--> Greeting
  +--> Guardrail
  |
  v
RailRadar API
  |
  +--> cache hit
  +--> rate limiter
  +--> API response
  |
  v
SQLite Fallback
  |
  +--> local train tables
  +--> local schedules
  +--> local live-status simulation
  |
  v
Normalization
  |
  +--> adapter layer
  +--> date and time normalization
  |
  v
Formatter
  |
  +--> LLM markdown response
  +--> offline fallback response
  |
  v
Response
```

## Journey Planner Flow

```text
User Query
  |
  v
Direct Train Search
  |
  +--> found direct train
  |       |
  |       v
  |   Rank and return
  |
  v
No Result
  |
  v
Graph Builder
  |
  v
Journey Planner
  |
  +--> backward Dijkstra
  +--> BFS exploration
  |
  v
Route Validator
  |
  +--> loop check
  +--> layover window
  +--> forward progress
  +--> distance ratio
  +--> min segment length
  +--> max changes
  |
  v
Route Ranker
  |
  +--> score
  +--> summary
  |
  v
Train Filter
  |
  +--> time-window filtering
  |
  v
Final Journey
```

## Folder Structure

```text
backend/
  agents/
    supervisor.py
    railradar.py
    prs.py
    rag.py
    guardrail.py
  services/
    cache.py
    context_manager.py
    graph_builder.py
    journey_planner.py
    query_normalizer.py
    railradar_adapter.py
    railradar_client.py
    rate_limiter.py
    route_ranker.py
    route_validator.py
    station_indexer.py
    station_resolver.py
    train_filter.py
  utils/
    formatter.py
    date_parser.py
  main.py
  database.py
  bootstrap.py
  migrate_seed.py
  rag_setup.py

frontend/
  src/
    App.jsx
    main.jsx
```

### Backend responsibilities

- [backend/main.py](backend/main.py) is the FastAPI application entry point, API router, WebSocket manager, startup coordinator, and PNR watcher host.
- [backend/database.py](backend/database.py) defines the SQLite schema and seeds all mock railway data.
- [backend/bootstrap.py](backend/bootstrap.py) ensures SQLite tables and Chroma collections exist.
- [backend/migrate_seed.py](backend/migrate_seed.py) adds extra train data in an idempotent way.
- [backend/rag_setup.py](backend/rag_setup.py) rebuilds and tests FAQ retrieval indexes.

### Agent responsibilities

- [backend/agents/supervisor.py](backend/agents/supervisor.py) selects the intent category.
- [backend/agents/railradar.py](backend/agents/railradar.py) handles train search, schedules, live status, and connecting routes.
- [backend/agents/prs.py](backend/agents/prs.py) handles PNR status and watchlist behavior.
- [backend/agents/rag.py](backend/agents/rag.py) handles policy and FAQ questions.
- [backend/agents/guardrail.py](backend/agents/guardrail.py) blocks unsafe or unrelated requests.

### Service responsibilities

- [backend/services/cache.py](backend/services/cache.py) stores short-lived API responses.
- [backend/services/context_manager.py](backend/services/context_manager.py) stores search context for follow-up questions.
- [backend/services/graph_builder.py](backend/services/graph_builder.py) creates an in-memory railway graph.
- [backend/services/journey_planner.py](backend/services/journey_planner.py) finds multi-leg routes.
- [backend/services/query_normalizer.py](backend/services/query_normalizer.py) standardizes extracted route parameters.
- [backend/services/railradar_adapter.py](backend/services/railradar_adapter.py) normalizes RailRadar payloads.
- [backend/services/railradar_client.py](backend/services/railradar_client.py) calls RailRadar with cache and rate limiting.
- [backend/services/rate_limiter.py](backend/services/rate_limiter.py) throttles outbound requests.
- [backend/services/route_ranker.py](backend/services/route_ranker.py) scores route candidates.
- [backend/services/route_validator.py](backend/services/route_validator.py) applies route pruning rules.
- [backend/services/station_indexer.py](backend/services/station_indexer.py) rebuilds station vectors.
- [backend/services/station_resolver.py](backend/services/station_resolver.py) resolves station names to codes.
- [backend/services/train_filter.py](backend/services/train_filter.py) filters trains by time window.

## API Endpoints

| Endpoint | Method | Purpose | Agent Used | Dependencies |
|---|---|---|---|---|
| / | GET | Health check | None | FastAPI |
| /api/chat | POST | Main chat route for all queries | Supervisor plus selected agent | SQLite, Groq, RailRadar, ChromaDB, cache |
| /api/pnr-watchlist/{session_id} | GET | List active watched PNRs | None directly | SQLite |
| /api/pnr-watchlist | POST | Add a PNR to the watchlist | PRS | SQLite |
| /api/live-train/{train_no} | GET | Return live train status | RailRadar | SQLite, RailRadar API |
| /api/ws/{session_id} | WS | Push PNR alerts to the browser | Background watcher | WebSocket, SQLite |

## Database Flow

### SQLite tables

The database includes these tables:

- trains
- stations
- train_schedule
- seat_availability
- pnr_records
- pnr_watchlist
- chat_sessions

### Seeding and startup

1. [backend/bootstrap.py](backend/bootstrap.py) calls init_db from [backend/database.py](backend/database.py).
2. init_db creates tables if they do not exist.
3. If the database is empty, trains, stations, schedules, PNRs, and seat availability are seeded.
4. FAQ content is indexed into ChromaDB.
5. Stations are indexed into ChromaDB for fuzzy resolution.
6. The runtime state is cleared on server startup so each boot starts clean.

### Migration behavior

[backend/migrate_seed.py](backend/migrate_seed.py) is an idempotent data migration that inserts additional trains and schedules if missing. It is intended as a data patch, not a schema migration framework.

### RAG setup

[backend/rag_setup.py](backend/rag_setup.py) rebuilds the FAQ vector store and can run a retrieval test query. The FAQ source file exists at [backend/data/railway_faq.txt](backend/data/railway_faq.txt).

## Frontend Flow

The frontend is a single-page React app that keeps the user experience simple and fast.

### State management

- Session id is stored in localStorage.
- Message history is stored in localStorage.
- Live watchlist data is fetched from the backend.
- Trace logs and source cards are bound to the latest assistant response.

### Chat flow

1. User enters a text query or uses voice input.
2. App.jsx sends the message, session id, and current history to /api/chat.
3. The backend returns the assistant response, trace steps, raw data, and sources.
4. The UI renders markdown, structured cards, route timelines, and watchlist updates.

### Speech features

- Speech recognition is browser-native and supports voice entry.
- Speech synthesis reads assistant replies aloud when enabled.

### WebSocket behavior

The frontend opens a WebSocket connection to /api/ws/{session_id} for live PNR alerts. This channel is used for watchlist notifications, not chat streaming.

## External Services

### RailRadar API

RailRadar is the primary live-data service for train details, live status, route lookup, and trains-between queries. The backend prefers RailRadar when available, then falls back to SQLite or simulated status logic when necessary.

### Groq

Groq is used by the supervisor and response-generation agents. It handles intent classification, markdown formatting, and refusal messaging. If unavailable, the system falls back to deterministic rules or offline formatting.

### ChromaDB

ChromaDB is used for two purposes:

- FAQ retrieval for RAG
- Search-context and station-resolution memory

### FlashRank

FlashRank is used for reranking retrieved FAQ chunks. This is present in the RAG path.

## Strengths

- Clear separation of concerns across supervisor, agents, services, and UI.
- Strong fallback behavior for API failures and LLM outages.
- Useful traceability through execution steps and source metadata.
- Hybrid architecture that blends local structured data with live API enrichment.
- Watchlist and WebSocket design makes the app feel interactive beyond simple chat.
- The codebase is easy to explain in interviews because each agent has a well-defined responsibility.

## Future Improvements

These suggestions preserve existing functionality while improving maintainability and product quality:

- Add stronger typed response contracts between backend agents and the frontend.
- Add an explicit chat path for the journey planner if multi-leg route search should be user-facing.
- Add startup validation for required environment variables and optional integrations.
- Add more granular tests for RailRadar fallback behavior and WebSocket watchlist notifications.
- Add structured observability for cache hit rates, API latency, and agent routing outcomes.
- Add a dedicated developer guide describing local setup, testing, and common failure modes.
- Add authentication if the application is moved beyond local or demo usage.

## README Review Notes

The existing README already contains:

- Project summary
- Architecture diagram
- Quick start instructions
- Environment variables
- API endpoint summary
- Troubleshooting notes
- Docker guidance

The following items would improve it further:

- Project banner
- Feature table
- Folder explanation
- API examples
- Screenshots
- Expanded architecture and request-flow diagrams
- Agent explanation section
- Development guide
- Testing guide
- Contribution guide
- FAQ
- License
- Badges

Not Found:

- License file in the analyzed content
- Dedicated screenshots in the analyzed content
- Separate API request/response examples in the analyzed content

## Useful Entry Points

- [backend/main.py](backend/main.py)
- [backend/agents/supervisor.py](backend/agents/supervisor.py)
- [backend/agents/railradar.py](backend/agents/railradar.py)
- [backend/agents/prs.py](backend/agents/prs.py)
- [backend/agents/rag.py](backend/agents/rag.py)
- [frontend/src/App.jsx](frontend/src/App.jsx)
- [backend/database.py](backend/database.py)

## Demo Queries

- Check PNR 2145678903
- Watch PNR 2145678903
- Find trains from New Delhi to Mumbai Central today after 5 pm
- What are the cancellation charges for confirmed tickets?
