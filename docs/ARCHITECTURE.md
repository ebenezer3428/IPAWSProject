# IPAWS Application Architecture & Functionality

This document describes the full architecture and runtime behavior of the IPAWS application stack, including backend (FastAPI + research pipeline) and frontend (React + Vite).

## 1) System Overview

The application has two primary layers:

- **Backend API**: FastAPI service in `api/main.py`, exposing endpoints for alert retrieval, translation, segmentation, fairness evaluation, human scoring, template generation, and authentication.
- **Frontend UI**: React SPA in `web/src/App.jsx`, providing workflows for Health, Alerts, Single Eval, Human Eval, Batch Eval, and Whole Eval.

Supporting layer:

- **Research Core** (`ipaws_research/*`): domain modules for translation engines, segmentation, fairness scoring, statistics, visualization, and pipeline orchestration via LangGraph.

## 2) Repository Architecture

### Backend/API

- `api/main.py`
  - FastAPI app bootstrapping
  - CORS middleware
  - request/response models
  - authentication/session endpoints
  - IPAWS functional endpoints
  - optional static frontend serving when `web/dist` exists

### Research Core

- `ipaws_research/workflow.py`
  - LangGraph state machine orchestration (`retrieve_alerts -> translate -> segment -> evaluate -> aggregate -> analyze -> report`)
- `ipaws_research/agents.py`
  - pipeline node implementations
- `ipaws_research/alert_retrieval.py`
  - FEMA Open API retrieval and normalization
- `ipaws_research/translations.py`
  - GPT-4o, Google NMT, NLLB-200, offline fallback
- `ipaws_research/segmentation.py`
  - segment extraction + communicative function labeling
- `ipaws_research/evaluation.py`
  - fairness scoring logic
- `ipaws_research/stats.py`
  - hypothesis testing
- `ipaws_research/visualization.py`
  - chart artifact generation
- `ipaws_research/export.py`
  - CSV export

### Frontend

- `web/src/App.jsx`
  - all major screens/components
  - login/session gate
  - role-based tab visibility
  - translation/evaluation UX for batch + whole flows
- `web/src/App.css`
  - layout, nav, pane, spinner, sticky action styles

## 3) Backend Architecture

## 3.1 API Boot and Runtime

- Loads environment from project `.env` via `python-dotenv`.
- Enables permissive CORS (`allow_origins=["*"]`) for browser clients.
- Uses in-memory stores for:
  - `CURRENT_STATE`: latest pipeline output snapshot
  - `SESSIONS`: auth tokens with expiry

## 3.2 Authentication & Session Model

### Endpoints

- `POST /auth/login`
  - Input: `username`, `password`, `role` (`user`|`admin`)
  - Validates password from env vars:
    - admin: `APP_ADMIN_PASSWORD` (or `ADMIN_PASSWORD` fallback)
    - user: `APP_USER_PASSWORD` (falls back to admin password if unset)
  - Creates session token + expiry
  - Returns: token + role + username + expiry

- `GET /auth/session`
  - Requires `Authorization: Bearer <token>`
  - Validates token existence and TTL
  - Returns session status and identity

### Session behavior

- Default TTL: `SESSION_TTL_SECONDS=28800` (8 hours)
- Expired tokens are removed lazily when validated.
- Session storage is in-process memory (not durable across service restarts/revisions).

## 3.3 Functional Endpoints

- `GET /health` — service health and server time
- `GET /config` — selected runtime config visibility
- `GET /alerts` — stratified/sample retrieval from FEMA Open API with filters
- `POST /translate` — translation by selected system (`gpt4o`, `google_nmt`, `nllb200`)
- `POST /segment` — source segmentation
- `POST /evaluate` — automated fairness scoring
- `POST /evaluate/human` — persists human scores to CSV
- `POST /pipeline/run` — end-to-end research workflow execution
- `POST /templates/build` — template extraction and save

## 3.4 Data Persistence

- Main outputs in `/outputs`:
  - fairness/human scores, segment outputs, composite/statistical results
- Human evaluation appends rows to `outputs/human_fairness_scores.csv`.
- Session and current-state caches are in memory (non-persistent).

## 4) Frontend Architecture

## 4.1 Shell and Navigation

- SPA rendered by `App.jsx`.
- Header contains theme toggle + logout.
- Left navigation tabs are role-aware:
  - **Admin**: all tabs
  - **User**: subset excluding admin-only page(s) (currently hides Human Eval tab)

## 4.2 Login Gate

Before app content is shown:

1. Login form submits to `POST /auth/login`.
2. On success, session token is stored in `sessionStorage`.
3. App validates token via `GET /auth/session` on startup.
4. If invalid or expired, user is returned to login screen.

Wrong password = login failure, app pages remain inaccessible.

## 4.3 Major UI Functional Areas

- **Health**: backend reachability + timestamp
- **Alerts**: sortable/filterable table + visual distributions
- **Single Eval**: direct translation/evaluation for one message
- **Human Eval**: manual scoring and rationale capture
- **Batch Eval**:
  - alert iteration with Back/Next
  - optional segmentation mode
  - compare mode for source vs translation panes
  - loading indicators and context strip
- **Whole Eval**:
  - side pane for metadata/load controls
  - main pane for translation/evaluation workflow
  - compare mode + loading indicators

## 4.4 UX Behavior Patterns

- Role-based access and nav filtering
- Collapsible panes for space savings
- Bottom navigation for message traversal
- Auto-selection and synchronization between list selection and active item
- Inline loading spinners for alerts/segmenting/translation states

## 5) End-to-End Flows

## 5.1 Authentication Flow

1. User submits role + username + password.
2. Backend validates password against role config.
3. Backend returns token with expiry.
4. Frontend stores token in session storage.
5. Frontend validates token on app load.

## 5.2 Translation/Evaluation Flow (Batch/Whole)

1. User loads alerts (`/alerts`).
2. Active message selected from table.
3. Translation requested (`/translate`).
4. Optional fairness scoring requested (`/evaluate`).
5. Optional human scoring saved (`/evaluate/human`).

## 5.3 Pipeline Flow

1. User/automation calls `/pipeline/run`.
2. LangGraph executes agents in sequence.
3. Scores/composites/stats/charts generated.
4. Results exported to `/outputs`.

## 6) Deployment Architecture

## 6.1 Frontend

- Built by Vite (`web/dist`).
- Deployed to Firebase Hosting.
- Uses `VITE_API_BASE_URL` for backend target in production.

## 6.2 Backend

- Deployed on Cloud Run (`ipaws-api`).
- Runtime env vars control auth, model, and behavior:
  - `APP_ADMIN_PASSWORD`
  - `APP_USER_PASSWORD` (optional)
  - `SESSION_TTL_SECONDS`
  - `OPENAI_API_KEY`
  - `OPENAI_MODEL`
  - `OFFLINE_MODE`

## 7) Security Notes

- Authentication is now backend-enforced (not frontend-only).
- Session tokens are bearer tokens stored in browser session storage.
- In-memory sessions are reset on service restarts/revisions.
- For higher assurance in production, consider:
  - external session store (Redis/Firestore)
  - hashed password management
  - HTTPS-only secure cookies instead of JS-readable tokens
  - rate limiting and login attempt throttling

## 8) Operational Notes / Current Constraints

- Some state is process-local (sessions/current pipeline state).
- A new backend revision invalidates existing in-memory sessions.
- CORS currently allows all origins.
- UI is implemented in a single large `App.jsx` file; future maintainability can improve by component splitting.

## 9) Recommended Next Improvements

- Split frontend into route-level/page-level components.
- Move auth/session management to dedicated hooks/context.
- Add backend session persistence and token revocation support.
- Add role-based authorization on backend endpoints (not just frontend tab filtering).
- Add API integration tests for auth + translation/evaluation flows.
