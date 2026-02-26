# IPAWS Research UI (Vite + React)

A lightweight frontend for your FastAPI backend.

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

Vite proxy in `vite.config.js` forwards `/health`, `/alerts`, `/segment`, `/translate`, `/evaluate`, `/templates`, `/config` to `http://localhost:8000`.

## Features

- Health: Calls `/health` and displays server status
- Alerts: Lists recent CA alerts via `/alerts?daysBack=7&state=CA`
- Translate: Form to POST `/translate` (choose language and system)
- Evaluate: Form to POST `/evaluate` and show scores + rationale
- Human Eval: Manual scoring form that POSTs `/evaluate/human` and saves to outputs/human_fairness_scores.csv
 - Batch Eval: Load alerts, segment selected alert, choose target language (es/hi), auto-translate/evaluate each segment, and save human scores per segment

## Notes

- Ensure `.env` contains `OPENAI_API_KEY` and `OFFLINE_MODE="0"` for online translation/evaluation.
- If you change backend port, update `server.proxy` in `vite.config.js`.

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

Alternative without local project alias:

```powershell
firebase deploy --only hosting --project <YOUR_FIREBASE_PROJECT_ID>
```
