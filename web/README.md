# IPAWS Research UI (Vite + React)

A lightweight frontend for your FastAPI backend.

Full backend + frontend architecture documentation: `../docs/ARCHITECTURE.md`.

## Dev Setup

1. Start the backend API:

```powershell
C:/Users/miniv/IPAWSProject/.venv/Scripts/python.exe -m uvicorn --app-dir C:/Users/miniv/IPAWSProject api.main:app --host 0.0.0.0 --port 8000
```

2. Start the frontend:

```powershell
Push-Location C:\Users\miniv\IPAWSProject\web
"C:\Program Files\nodejs\npm.cmd" install
"C:\Program Files\nodejs\npm.cmd" run dev
```

Vite proxy in `vite.config.js` forwards `/health`, `/config`, `/auth`, `/admin`, `/alerts`, `/segment`, `/translate`, `/evaluate`, `/templates`, and `/pipeline` to `http://localhost:8000`.

Authentication routes used by the UI:

- `/auth/login`
- `/auth/session`

## Features

- Login: Role-based login (`User` / `Admin`) with backend session validation
- Admin Analytics: Admin-only BI dashboard for submitted human scores and composite export analysis
- Health: Calls `/health` and displays server status
- Alerts: Lists recent CA alerts via `/alerts?daysBack=7&state=CA`
- Translate: Form to POST `/translate` (choose language and system)
- Evaluate: Form to POST `/evaluate` and show scores + rationale
- Human Eval: Manual scoring form that POSTs `/evaluate/human` and saves to outputs/human_fairness_scores.csv
- Batch Eval: Message navigation with `Back`/`Next`, auto-translation on selection change, compare mode toggle, loading indicators, collapsible alerts pane
- Whole Eval: Sidebar control pane (metadata + load controls), message navigation with `Back`/`Next`, compare mode toggle, loading indicators, collapsible alerts pane

The admin dashboard currently includes:

- KPI cards and evaluator activity tables
- submission trend and language coverage charts
- fairness metric performance summaries
- composite OFS comparison by language and system
- normal distribution curve for submitted average scores
- two-way ANOVA results for OFS by `language × system`

## Using Admin Analytics

1. Sign in with role `Admin`.
2. Open the `Admin Analytics` tab from the left sidebar.
3. Use `Refresh` to reload the latest aggregated data from the backend.

The page includes an embedded guide that explains:

- what each chart and table represents
- which output files supply the data
- how to interpret the normal distribution curve
- how to read the ANOVA table, `p-value`, and effect size

## Notes

- Ensure `.env` contains `OPENAI_API_KEY` and `OFFLINE_MODE="0"` for online translation/evaluation.
- If you change backend port, update `server.proxy` in `vite.config.js`.
- Backend auth env vars should be configured in API runtime:
	- `APP_ADMIN_PASSWORD` (required)
	- `APP_USER_PASSWORD` (optional)
	- `SESSION_TTL_SECONDS` (optional)
- The app shell now uses the full available width, with a sticky left navigation rail for the analysis-heavy views.

## Deploy live with Firebase Hosting

This follows the Firebase Hosting quickstart flow (`install CLI` -> `init` -> `deploy`) for this Vite app.

1. Install Firebase CLI (if needed):

```powershell
npm install -g firebase-tools
```

2. In `web/`, set production API URL for the frontend:

```powershell
Copy-Item .env.example .env
# Edit .env and set VITE_API_BASE_URL to your live backend URL
```

3. Build and verify the static bundle:

```powershell
Push-Location C:\Users\miniv\IPAWSProject\web
"C:\Program Files\nodejs\npm.cmd" install
"C:\Program Files\nodejs\npm.cmd" run build
```

4. Authenticate and connect to your Firebase project:

```powershell
firebase login
firebase use --add
```

5. Deploy hosting:

```powershell
firebase deploy --only hosting
```

If you rely on the GitHub Action to publish the site, push a trivial commit to
`main` (for example, updating documentation) and the `Deploy Web to Firebase
Hosting` workflow will rebuild with the latest `.env.production` values and
promote the bundle automatically.

Alternative without local project alias:

```powershell
firebase deploy --only hosting --project <YOUR_FIREBASE_PROJECT_ID>
```
