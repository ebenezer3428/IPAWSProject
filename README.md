# IPAWS Emergency Alert Translation Fairness Research

Automated LangGraph pipeline to translate IPAWS alerts (English → Spanish/Hindi) across GPT-4o, Google NMT, Meta Llama 3, and Google Gemini (the latter two via Replicate), segment texts, evaluate fairness (12 metrics), aggregate scores, run statistical tests (H1–H3), generate visualizations, and export results.

## Quick Start

1. Create and activate a Python 3.10+ environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
python -m spacy download en_core_web_sm
python -m spacy download es_core_news_sm
python -m spacy download xx_sent_ud_sm
```

3. Set environment variables:
- `OPENAI_API_KEY` for GPT-4o
- Google credentials via `GOOGLE_APPLICATION_CREDENTIALS`

4. Run a small smoke test:

```bash
python -m pytest -q || python test_pipeline.py
```

Logs are written to `logs/research.log`; outputs to `outputs/`.

## GitHub Actions: Firebase Hosting Auto-Deploy

This repo includes a workflow at `.github/workflows/firebase-hosting-deploy.yml` that builds `web/` and deploys to Firebase Hosting live channel on pushes to `main`.

Add these repository secrets before first run:

- `FIREBASE_SERVICE_ACCOUNT`: JSON key for a Firebase Admin service account with Hosting deploy permissions
- `FIREBASE_PROJECT_ID`: your Firebase project ID
- `VITE_API_BASE_URL`: public backend base URL used by the deployed frontend

Google Sign-In (Firebase Auth) reads the web app config from `web/.env.production`,
which is committed to the repo. The Firebase web `apiKey` is a public client
identifier (not a secret), so no additional GitHub secrets are required for auth.
If you rotate the Firebase project, regenerate those values from the Firebase
Console → Project settings → General → "Your apps" → SDK setup and configuration.

You can also trigger deployment manually from the Actions tab via `workflow_dispatch`.

### Manual Firebase Hosting deploy

If CI is unavailable, the frontend can be deployed manually with the included script (uses a gcloud access token against the Hosting REST API):

```powershell
cd web; npm run build; cd ..
powershell -ExecutionPolicy Bypass -File scripts\deploy_hosting.ps1
```

### PR Preview Deploys

This repo also includes `.github/workflows/firebase-hosting-preview.yml`.
For each pull request (`opened`, `synchronize`, `reopened`), it builds `web/` and deploys a temporary Firebase Hosting preview channel:

- Channel format: `pr-<pull_request_number>`
- Expiration: `7d`

When the pull request is closed, the workflow deletes that PR preview channel immediately.

It uses the same repository secrets listed above and posts the preview URL back to the PR.
