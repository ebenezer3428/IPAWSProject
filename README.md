# IPAWS Emergency Alert Translation Fairness Research

Architecture and full application documentation: `docs/ARCHITECTURE.md`.

Automated LangGraph pipeline to translate IPAWS alerts (English → Spanish/Hindi) across GPT-4o, Google NMT, and Meta NLLB-200, segment texts, evaluate fairness (12 metrics), aggregate scores, run statistical tests (H1–H3), generate visualizations, and export results.

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
- `APP_ADMIN_PASSWORD` for admin login (required for auth)
- `APP_USER_PASSWORD` for user login (optional; falls back to admin password if not set)
- `SESSION_TTL_SECONDS` optional session lifetime override (default 28800 = 8h)

4. Run a small smoke test:

```bash
python -m pytest -q || python test_pipeline.py
```

Logs are written to `logs/research.log`; outputs to `outputs/`.

## Authentication (Backend-Enforced)

The app now uses backend-validated authentication:

- `POST /auth/login` validates username/password/role and returns a session token
- `GET /auth/session` validates token/session status

Frontend access is blocked until session validation passes. Wrong passwords do not expose app pages.

## GitHub Actions: Firebase Hosting Auto-Deploy

This repo includes a workflow at `.github/workflows/firebase-hosting-deploy.yml` that builds `web/` and deploys to Firebase Hosting live channel on pushes to `main`.

Add these repository secrets before first run:

- `FIREBASE_SERVICE_ACCOUNT`: JSON key for a Firebase Admin service account with Hosting deploy permissions
- `FIREBASE_PROJECT_ID`: your Firebase project ID
- `VITE_API_BASE_URL`: public backend base URL used by the deployed frontend

You can also trigger deployment manually from the Actions tab via `workflow_dispatch`.

### PR Preview Deploys

This repo also includes `.github/workflows/firebase-hosting-preview.yml`.
For each pull request (`opened`, `synchronize`, `reopened`), it builds `web/` and deploys a temporary Firebase Hosting preview channel:

- Channel format: `pr-<pull_request_number>`
- Expiration: `7d`

When the pull request is closed, the workflow deletes that PR preview channel immediately.

It uses the same repository secrets listed above and posts the preview URL back to the PR.
