from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query, Header
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from collections import defaultdict
import base64
import binascii
import csv
import hashlib
import hmac
import io
import json
import math
import os
import re
import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from dotenv import load_dotenv
import secrets
import time
import pandas as pd
from statsmodels.formula.api import ols
from statsmodels.stats.anova import anova_lm

# Ensure .env variables (e.g., OPENAI_API_KEY) are loaded on startup
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from ipaws_research.translations import translate_with_gemini, translate_with_gpt4o, translate_with_llama3
from ipaws_research.segmentation import segment_alert
from ipaws_research.evaluation import evaluate_segment_fairness
from ipaws_research.workflow import create_research_workflow
from ipaws_research.alert_retrieval import fetch_ipaws_alerts, fetch_ipaws_openapi_alerts, extract_templates_from_api, save_templates
from ipaws_research.alert_retrieval import _cap_categories_for, _categorize_text, classify_study_category
from ipaws_research.alert_quality import (
    is_candidate_selectable,
    merge_review_state,
    review_candidate,
    validate_candidates,
)
from ipaws_research.corpus import (
    ResearchCorpus,
    add_corpus_translation,
    build_corpus_draft,
    corpus_missing_conditions,
    corpus_unapproved_conditions,
    freeze_corpus,
    get_frozen_translation,
    review_corpus_translation,
)
from ipaws_research.models import EmergencyAlert
from ipaws_research.stats import test_hypothesis_h1, test_hypothesis_h2, test_hypothesis_h3

app = FastAPI(title="IPAWS Fairness Research API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory state to expose latest results
CURRENT_STATE: Dict[str, object] = {}
SESSIONS: Dict[str, Dict[str, object]] = {}
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", "7200"))
SESSION_SECRET = os.getenv("SESSION_SECRET", "").strip() or secrets.token_urlsafe(48)
OUTPUTS_DIR = Path(__file__).resolve().parents[1] / "outputs"
FAIRNESS_METRIC_LABELS: Dict[str, str] = {
    "pf1_urgency_preservation": "Urgency preservation",
    "pf2_directive_clarity": "Directive clarity",
    "pf3_risk_severity": "Risk severity",
    "pf4_authority_attribution": "Authority attribution",
    "pf5_temporal_accuracy": "Temporal accuracy",
    "pf6_procedural_completeness": "Procedural completeness",
    "if1_respectful_tone": "Respectful tone",
    "if2_inclusion": "Inclusion",
    "if3_empathy_marker": "Empathy marker",
    "if4_linguistic_clarity": "Linguistic clarity",
    "if5_cultural_appropriateness": "Cultural appropriateness",
    "if6_trust_signal": "Trust signal",
}
FAIRNESS_METRIC_KEYS = list(FAIRNESS_METRIC_LABELS.keys())
DOWNLOADABLE_OUTPUTS: Dict[str, Dict[str, str]] = {
    "human_fairness_scores": {
        "label": "Human Fairness Scores",
        "filename": "human_fairness_scores.csv",
    },
    "composite_scores": {
        "label": "Composite Scores",
        "filename": "composite_scores.csv",
    },
    "translations": {
        "label": "Translations",
        "filename": "translations.csv",
    },
    "segments": {
        "label": "Segments",
        "filename": "segments.csv",
    },
    "statistical_results": {
        "label": "Statistical Results",
        "filename": "statistical_results.csv",
    },
}

# ---------------------------------------------------------------------------
# Durable storage (Google Cloud Storage) shared across features.
#
# Cloud Run instances are ephemeral, so anything written to the local disk does
# not survive restarts or new deployments. When ``SUBMISSIONS_GCS_BUCKET`` is
# set, feature data (human submissions, alert-pool selection) is stored as JSON
# objects in Cloud Storage so it persists until explicitly changed. Without the
# env var the code falls back to local files, keeping local development working.
# ---------------------------------------------------------------------------
_storage_logger = logging.getLogger("ipaws.storage")
GCS_BUCKET = os.getenv("SUBMISSIONS_GCS_BUCKET", "").strip()
_gcs_client = None
_gcs_client_error: Optional[str] = None


def _gcs_blob(object_name: str):
    """Return a Cloud Storage blob for ``object_name``, or ``None`` when the
    GCS backend is not configured/available (callers fall back to local files)."""
    global _gcs_client, _gcs_client_error
    if not GCS_BUCKET or _gcs_client_error is not None:
        return None
    try:
        if _gcs_client is None:
            from google.cloud import storage

            _gcs_client = storage.Client()
        return _gcs_client.bucket(GCS_BUCKET).blob(object_name)
    except Exception as exc:  # pragma: no cover - environment dependent
        _gcs_client_error = str(exc)
        _storage_logger.error("Cloud Storage backend unavailable: %s", exc)
        return None


# Alert pool: admin selects which alerts are used in evaluation
ALERT_POOL_FILE = OUTPUTS_DIR / ".alert_pool_selected.json"
ALERT_POOL_GCS_OBJECT = os.getenv("ALERT_POOL_GCS_OBJECT", "alert-pool/selected.json").strip()
ALERT_POOL_SELECTED: set = set()  # in-memory cache of selected alert IDs
# When no selection has been saved yet, default to the first 48 alerts so the
# admin pool and evaluator view stay consistent (matches the /alerts fallback).
DEFAULT_ALERT_POOL_IDS = [str(i) for i in range(48)]


def _load_alert_pool():
    """Load selected alert IDs from the durable store (GCS) or local disk.

    When nothing is stored yet, seed the default first-48 selection and persist
    it so the choice is durable and shown as checked in the admin pool."""
    global ALERT_POOL_SELECTED
    loaded: Optional[set] = None
    blob = _gcs_blob(ALERT_POOL_GCS_OBJECT)
    if blob is not None:
        try:
            if blob.exists():
                raw = blob.download_as_text()
                data = json.loads(raw) if raw.strip() else {}
                loaded = set(data.get("selected_ids", []))
        except Exception as exc:
            _storage_logger.error("Failed to load alert pool from Cloud Storage: %s", exc)
    if loaded is None and ALERT_POOL_FILE.exists():
        try:
            with open(ALERT_POOL_FILE, "r", encoding="utf-8") as f:
                loaded = set(json.load(f).get("selected_ids", []))
        except Exception:
            loaded = None
    if loaded:
        ALERT_POOL_SELECTED = loaded
        return
    # Nothing stored yet: seed the default selection and persist it.
    ALERT_POOL_SELECTED = set(DEFAULT_ALERT_POOL_IDS)
    _save_alert_pool()


def _save_alert_pool():
    """Persist selected alert IDs to the durable store (GCS) or local disk."""
    blob = _gcs_blob(ALERT_POOL_GCS_OBJECT)
    if blob is not None:
        try:
            blob.upload_from_string(
                json.dumps({"selected_ids": list(ALERT_POOL_SELECTED)}),
                content_type="application/json",
            )
            return
        except Exception as exc:
            _storage_logger.error("Failed to save alert pool to Cloud Storage: %s", exc)
    try:
        with open(ALERT_POOL_FILE, "w", encoding="utf-8") as f:
            json.dump({"selected_ids": list(ALERT_POOL_SELECTED)}, f)
    except Exception as e:
        print(f"Failed to save alert pool: {e}")


# Load on startup
_load_alert_pool()


# ---------------------------------------------------------------------------
# Alert template pool expansion.
#
# The bundled ``templates.json`` ships a fixed set of alerts (the original 70).
# Additional alerts fetched live from IPAWS are stored durably in Cloud Storage
# (or a local file for development) so the expanded pool survives Cloud Run
# restarts. They are always appended AFTER the bundled alerts so the original
# alert ids stay stable and previously saved selections remain valid.
# ---------------------------------------------------------------------------
ALERT_TEMPLATE_CATEGORIES = ["weather", "evacuation", "public_safety", "health"]
ALERT_POOL_ELIGIBLE_TARGETS = {category: 50 for category in ALERT_TEMPLATE_CATEGORIES}
ALERT_SELECTION_TARGETS = {
    "evacuation": 19,
    "weather": 14,
    "health": 8,
    "public_safety": 7,
}
ALERT_POOL_TARGET_TOTAL = int(os.getenv("ALERT_POOL_TARGET_TOTAL", "200"))
ALERT_TEMPLATES_GCS_OBJECT = os.getenv("ALERT_TEMPLATES_GCS_OBJECT", "alert-pool/templates_extra.json").strip()
ALERT_TEMPLATES_FILE = OUTPUTS_DIR / ".alert_templates_extra.json"
ALERT_CANDIDATES_GCS_OBJECT = os.getenv(
    "ALERT_CANDIDATES_GCS_OBJECT",
    "alert-pool/candidates-v1.json",
).strip()
ALERT_CANDIDATES_FILE = OUTPUTS_DIR / ".alert_candidates_v1.json"
RESEARCH_CORPUS_GCS_OBJECT = os.getenv(
    "RESEARCH_CORPUS_GCS_OBJECT",
    "research-corpus/manifest-v1.json",
).strip()
RESEARCH_CORPUS_FILE = OUTPUTS_DIR / ".research_corpus_v1.json"


def _empty_template_buckets() -> Dict[str, List[str]]:
    return {category: [] for category in ALERT_TEMPLATE_CATEGORIES}


def _load_all_alert_templates() -> Dict[str, List[str]]:
    """Load the bundled alert templates from templates.json (the original set)."""
    templates_file = Path(__file__).resolve().parents[1] / "ipaws_research" / "resources" / "templates.json"
    if templates_file.exists():
        try:
            with open(templates_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Failed to load templates: {e}")
    return {}


def _load_extra_templates() -> Dict[str, List[str]]:
    """Load live-fetched extra templates from the durable store (GCS) or disk."""
    buckets = _empty_template_buckets()
    blob = _gcs_blob(ALERT_TEMPLATES_GCS_OBJECT)
    raw: Optional[str] = None
    if blob is not None:
        try:
            if blob.exists():
                raw = blob.download_as_text()
        except Exception as exc:
            _storage_logger.error("Failed to load extra templates from Cloud Storage: %s", exc)
    if raw is None and ALERT_TEMPLATES_FILE.exists():
        try:
            raw = ALERT_TEMPLATES_FILE.read_text(encoding="utf-8")
        except Exception:
            raw = None
    if raw and raw.strip():
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                for category in ALERT_TEMPLATE_CATEGORIES:
                    items = data.get(category, [])
                    if isinstance(items, list):
                        buckets[category] = [str(t) for t in items if str(t).strip()]
        except Exception as exc:
            _storage_logger.error("Failed to parse extra templates: %s", exc)
    return buckets


def _save_extra_templates(buckets: Dict[str, List[str]]) -> None:
    """Persist live-fetched extra templates to the durable store (GCS) or disk."""
    payload = json.dumps(buckets, ensure_ascii=False, indent=2)
    blob = _gcs_blob(ALERT_TEMPLATES_GCS_OBJECT)
    if blob is not None:
        try:
            blob.upload_from_string(payload, content_type="application/json")
            return
        except Exception as exc:
            _storage_logger.error("Failed to save extra templates to Cloud Storage: %s", exc)
            raise HTTPException(status_code=500, detail="Failed to persist expanded alert pool")
    try:
        OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
        ALERT_TEMPLATES_FILE.write_text(payload, encoding="utf-8")
    except Exception as exc:
        print(f"Failed to save extra templates: {exc}")


def _load_alert_candidates() -> List[EmergencyAlert]:
    """Load structured official OpenFEMA records from durable storage."""
    raw: Optional[str] = None
    blob = _gcs_blob(ALERT_CANDIDATES_GCS_OBJECT)
    if blob is not None:
        try:
            if blob.exists():
                raw = blob.download_as_text()
        except Exception as exc:
            _storage_logger.error("Failed to load alert candidates from Cloud Storage: %s", exc)
    if raw is None and ALERT_CANDIDATES_FILE.exists():
        try:
            raw = ALERT_CANDIDATES_FILE.read_text(encoding="utf-8")
        except Exception as exc:
            _storage_logger.error("Failed to load local alert candidates: %s", exc)
    if not raw or not raw.strip():
        return []
    try:
        payload = json.loads(raw)
        records = payload.get("records", []) if isinstance(payload, dict) else payload
        return [EmergencyAlert.model_validate(record) for record in records if isinstance(record, dict)]
    except Exception as exc:
        _storage_logger.error("Failed to parse alert candidates: %s", exc)
        return []


def _save_alert_candidates(candidates: List[EmergencyAlert]) -> None:
    """Persist complete records without altering bundled legacy templates."""
    payload = json.dumps(
        {
            "schema_version": 1,
            "updated_at": datetime.utcnow().isoformat() + "Z",
            "records": [candidate.model_dump(mode="json") for candidate in candidates],
        },
        ensure_ascii=False,
        indent=2,
    )
    blob = _gcs_blob(ALERT_CANDIDATES_GCS_OBJECT)
    if blob is not None:
        try:
            blob.upload_from_string(payload, content_type="application/json")
            return
        except Exception as exc:
            _storage_logger.error("Failed to save alert candidates to Cloud Storage: %s", exc)
            raise HTTPException(status_code=500, detail="Failed to persist official alert candidates")
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    ALERT_CANDIDATES_FILE.write_text(payload, encoding="utf-8")


def _load_research_corpus() -> Optional[ResearchCorpus]:
    """Load the versioned research corpus from GCS or the local fallback."""
    raw: Optional[str] = None
    blob = _gcs_blob(RESEARCH_CORPUS_GCS_OBJECT)
    if blob is not None:
        try:
            if blob.exists():
                raw = blob.download_as_text()
        except Exception as exc:
            _storage_logger.error("Failed to load research corpus from Cloud Storage: %s", exc)
    if raw is None and RESEARCH_CORPUS_FILE.exists():
        try:
            raw = RESEARCH_CORPUS_FILE.read_text(encoding="utf-8")
        except Exception as exc:
            _storage_logger.error("Failed to load local research corpus: %s", exc)
    if not raw or not raw.strip():
        return None
    try:
        return ResearchCorpus.model_validate_json(raw)
    except Exception as exc:
        _storage_logger.error("Failed to parse research corpus: %s", exc)
        return None


def _save_research_corpus(corpus: ResearchCorpus) -> None:
    """Persist the exact corpus manifest without mutating candidate records."""
    payload = corpus.model_dump_json(indent=2)
    blob = _gcs_blob(RESEARCH_CORPUS_GCS_OBJECT)
    if blob is not None:
        try:
            blob.upload_from_string(payload, content_type="application/json")
            return
        except Exception as exc:
            _storage_logger.error("Failed to save research corpus to Cloud Storage: %s", exc)
            raise HTTPException(status_code=500, detail="Failed to persist research corpus")
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    RESEARCH_CORPUS_FILE.write_text(payload, encoding="utf-8")


def _build_alert_pool_response() -> AlertPoolResponse:
    """Build the pool from official candidates, with a legacy fallback."""
    candidates = _load_alert_candidates()
    if candidates:
        alerts = [AlertPoolItem(
            id=candidate.research_id or candidate.alert_id,
            text=candidate.source_text,
            category=candidate.category,
            selected=(candidate.research_id or candidate.alert_id) in ALERT_POOL_SELECTED,
            identifier=candidate.identifier,
            openfema_id=candidate.openfema_id,
            sender=candidate.sender,
            area=candidate.area,
            language=candidate.language,
            sent=candidate.sent.isoformat() if candidate.sent else "",
            effective=candidate.effective.isoformat() if candidate.effective else "",
            expires=candidate.expires.isoformat() if candidate.expires else "",
            urgency=candidate.urgency_level,
            severity=candidate.severity_level,
            certainty=candidate.certainty_level,
            message_type=candidate.message_type,
            event=candidate.event,
            source="openfema",
            quality_status=candidate.quality_status,
            quality_findings=[finding.model_dump() for finding in candidate.quality_findings],
            raw_text=candidate.raw_source_text,
            cleaned_text=candidate.cleaned_source_text or candidate.source_text,
            review_decision=candidate.review_decision,
            review_history=[event.model_dump(mode="json") for event in candidate.review_history],
            selectable=is_candidate_selectable(candidate),
        ) for candidate in candidates]
        counts = {category: 0 for category in ALERT_TEMPLATE_CATEGORIES}
        available_counts = {category: 0 for category in ALERT_TEMPLATE_CATEGORIES}
        for candidate in candidates:
            counts[candidate.category] = counts.get(candidate.category, 0) + 1
            if is_candidate_selectable(candidate):
                available_counts[candidate.category] = available_counts.get(candidate.category, 0) + 1
        status_counts = {status: 0 for status in ("eligible", "flagged", "excluded", "unreviewed")}
        finding_counts: Dict[str, int] = {}
        for candidate in candidates:
            status_counts[candidate.quality_status] = status_counts.get(candidate.quality_status, 0) + 1
            for finding in candidate.quality_findings:
                finding_counts[finding.code] = finding_counts.get(finding.code, 0) + 1
            status_counts["approved"] = sum(1 for candidate in candidates if candidate.review_decision == "approved" and is_candidate_selectable(candidate))
            status_counts["rejected"] = sum(1 for candidate in candidates if candidate.review_decision == "rejected")
        return AlertPoolResponse(
            total=len(alerts),
            selected=sum(1 for alert in alerts if alert.selected),
            counts=counts,
            source="openfema",
            quality_summary={**status_counts, "findings": finding_counts},
            available_counts=available_counts,
            target_counts=ALERT_SELECTION_TARGETS,
            pool_target_counts=ALERT_POOL_ELIGIBLE_TARGETS,
            alerts=alerts,
        )

    bundled = _load_all_alert_templates()
    extra = _load_extra_templates()
    alerts: List[AlertPoolItem] = []
    alert_id = 0

    for source in (bundled, extra):
        for category in ALERT_TEMPLATE_CATEGORIES:
            for text in source.get(category, []):
                alert_id_str = str(alert_id)
                alerts.append(AlertPoolItem(
                    id=alert_id_str,
                    text=text,
                    category=category,
                    selected=alert_id_str in ALERT_POOL_SELECTED,
                ))
                alert_id += 1

    return AlertPoolResponse(
        total=len(alerts),
        selected=len(ALERT_POOL_SELECTED),
        counts={category: sum(len(source.get(category, [])) for source in (bundled, extra)) for category in ALERT_TEMPLATE_CATEGORIES},
        source="legacy",
        alerts=alerts
    )


# Column order for the alert-pool CSV export (id + all extractable metadata).
ALERT_POOL_CSV_FIELDNAMES = [
    "id",
    "category",
    "selected",
    "source_format",
    "alert_type",
    "msg_type",
    "urgency",
    "severity",
    "certainty",
    "sent",
    "effective",
    "expires",
    "area",
    "sender",
    "language",
    "identifier",
    "char_count",
    "text",
]


def _cap_local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _extract_alert_metadata(text: str) -> Dict[str, str]:
    """Best-effort extraction of structured metadata from a raw alert string.

    Handles two shapes present in the pool: CAP (Common Alerting Protocol) XML
    documents, and free-form NWS/agency text. Missing fields are left blank."""
    meta = {key: "" for key in (
        "source_format", "alert_type", "msg_type", "urgency", "severity",
        "certainty", "sent", "effective", "expires", "area", "sender",
        "language", "identifier",
    )}
    raw = (text or "").strip()
    if not raw:
        return meta

    if raw.startswith("<alert") or "urn:oasis:names:tc:emergency:cap" in raw:
        meta["source_format"] = "CAP"
        try:
            root = ET.fromstring(raw)

            def first_text(name: str) -> str:
                for el in root.iter():
                    if _cap_local_name(el.tag) == name and (el.text or "").strip():
                        return el.text.strip()
                return ""

            meta["identifier"] = first_text("identifier")
            meta["sender"] = first_text("senderName") or first_text("sender")
            meta["msg_type"] = first_text("msgType")
            meta["sent"] = first_text("sent")
            meta["alert_type"] = first_text("event")
            meta["urgency"] = first_text("urgency")
            meta["severity"] = first_text("severity")
            meta["certainty"] = first_text("certainty")
            meta["effective"] = first_text("effective")
            meta["expires"] = first_text("expires")
            meta["language"] = first_text("language")
            areas = [
                (el.text or "").strip()
                for el in root.iter()
                if _cap_local_name(el.tag) == "areaDesc" and (el.text or "").strip()
            ]
            meta["area"] = "; ".join(dict.fromkeys(areas))
        except Exception:
            pass
        return meta

    # Free-form / NWS text.
    meta["source_format"] = "text"
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if lines:
        meta["alert_type"] = lines[0][:120]
        # Prefer the warning/order phrase before "issued" when present.
        m_type = re.match(r"^([A-Z][A-Za-z /]+?(?:Warning|Watch|Advisory|Order|Statement|Emergency|Message))\b", lines[0])
        if m_type:
            meta["alert_type"] = m_type.group(1).strip()
    m_sent = re.search(r"issued\s+([A-Za-z]+\s+\d+\s+at\s+\d+:\d+\s*[AP]M\s+[A-Z]{2,4})", raw)
    if m_sent:
        meta["sent"] = m_sent.group(1)
    m_exp = re.search(r"until\s+([A-Za-z]+\s+\d+\s+at\s+\d+:\d+\s*[AP]M\s+[A-Z]{2,4})", raw)
    if m_exp:
        meta["expires"] = m_exp.group(1)
    return meta


def _alert_pool_as_csv_text() -> str:
    """Serialize the full alert pool (with extracted metadata) to CSV."""
    pool = _build_alert_pool_response()
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=ALERT_POOL_CSV_FIELDNAMES)
    writer.writeheader()
    for item in pool.alerts:
        meta = _extract_alert_metadata(item.text)
        if item.source == "openfema":
            meta.update({
                "source_format": "OpenFEMA/CAP",
                "alert_type": item.event,
                "msg_type": item.message_type,
                "urgency": item.urgency,
                "severity": item.severity,
                "certainty": item.certainty,
                "sent": item.sent,
                "effective": item.effective,
                "expires": item.expires,
                "area": item.area,
                "sender": item.sender,
                "language": item.language,
                "identifier": item.identifier,
            })
        writer.writerow({
            "id": item.id,
            "category": item.category,
            "selected": "yes" if item.selected else "no",
            "source_format": meta["source_format"],
            "alert_type": meta["alert_type"],
            "msg_type": meta["msg_type"],
            "urgency": meta["urgency"],
            "severity": meta["severity"],
            "certainty": meta["certainty"],
            "sent": meta["sent"],
            "effective": meta["effective"],
            "expires": meta["expires"],
            "area": meta["area"],
            "sender": meta["sender"],
            "language": meta["language"],
            "identifier": meta["identifier"],
            "char_count": len(item.text or ""),
            "text": item.text,
        })
    return buffer.getvalue()


class TranslationRequest(BaseModel):
    source_text: str
    target_language: str = Field(pattern="^(es|hi)$")
    system: str = Field(default="gemini", pattern="^(gemini|gpt5.5|llama3)$")
    alert_id: Optional[str] = None
    corpus_id: Optional[str] = None

class TranslationResponse(BaseModel):
    translation: str
    metadata: Dict[str, Optional[str]]

class SegmentRequest(BaseModel):
    text: str
    language: str = Field(default="en", pattern="^(en|es|hi)$")

class SegmentItem(BaseModel):
    segment_text: str
    communicative_function: str

class SegmentResponse(BaseModel):
    segments: List[SegmentItem]

class EvaluationRequest(BaseModel):
    source_segment: str
    translated_segment: str
    language: str = Field(pattern="^(es|hi)$")
    context: Optional[str] = ""
    alert_id: Optional[str] = None
    corpus_id: Optional[str] = None
    system: str = Field(default="gemini", pattern="^(gemini|gpt5.5|llama3)$")

class EvaluationResponse(BaseModel):
    scores: Dict[str, int]
    rationale: Dict[str, str]

class HumanEvaluationRequest(BaseModel):
    source_segment: str
    translated_segment: str
    language: str = Field(pattern="^(es|hi)$")
    system: str = Field(default="gemini", pattern="^(gemini|gpt5.5|llama3)$")
    evaluator_id: Optional[str] = None
    alert_id: Optional[str] = None
    corpus_id: Optional[str] = None
    scores: Dict[str, int]
    rationale: Optional[Dict[str, str]] = Field(default_factory=dict)

class HumanEvaluationResponse(BaseModel):
    saved: bool
    path: str

class SubmissionUpdateRequest(BaseModel):
    scores: Dict[str, int]
    notes: Optional[str] = ""

class PipelineRequest(BaseModel):
    sample_size: int = 3
    target_languages: List[str] = ["es"]
    translation_systems: List[str] = ["gemini"]
    offline: bool = True

class PipelineResponse(BaseModel):
    alerts: int
    translations: int
    segments: int
    scores: int
    composite: int
    stats: int
    output_dir: str

class TemplatesBuildRequest(BaseModel):
    startDate: str
    endDate: str
    perCategory: int = 20

class TemplatesBuildResponse(BaseModel):
    counts: Dict[str, int]
    saved: bool

class GoogleLoginRequest(BaseModel):
    id_token: str

class LoginResponse(BaseModel):
    token: str
    role: str
    username: str
    email: str
    language: Optional[str] = None
    expires_at: str

class SessionStatusResponse(BaseModel):
    valid: bool
    role: str
    username: str
    email: str
    language: Optional[str] = None
    expires_at: str

class UserItem(BaseModel):
    email: str
    role: str
    language: Optional[str] = None
    is_default: bool = False

class UsersResponse(BaseModel):
    users: List[UserItem]

class UserUpsertRequest(BaseModel):
    email: str
    role: str = Field(pattern="^(admin|user)$")
    language: Optional[str] = Field(default=None, pattern="^(es|hi)$")

class AlertPoolItem(BaseModel):
    id: str
    text: str
    category: str
    selected: bool
    identifier: str = ""
    openfema_id: str = ""
    sender: str = ""
    area: str = ""
    language: str = ""
    sent: str = ""
    effective: str = ""
    expires: str = ""
    urgency: str = ""
    severity: str = ""
    certainty: str = ""
    message_type: str = ""
    event: str = ""
    source: str = "legacy"
    quality_status: str = "unreviewed"
    quality_findings: List[Dict[str, str]] = Field(default_factory=list)
    raw_text: str = ""
    cleaned_text: str = ""
    review_decision: str = "pending"
    review_history: List[Dict[str, Any]] = Field(default_factory=list)
    selectable: bool = False

class AlertPoolResponse(BaseModel):
    total: int
    selected: int
    counts: Dict[str, int] = Field(default_factory=dict)
    source: str = "legacy"
    quality_summary: Dict[str, Any] = Field(default_factory=dict)
    available_counts: Dict[str, int] = Field(default_factory=dict)
    target_counts: Dict[str, int] = Field(default_factory=lambda: dict(ALERT_SELECTION_TARGETS))
    pool_target_counts: Dict[str, int] = Field(default_factory=lambda: dict(ALERT_POOL_ELIGIBLE_TARGETS))
    alerts: List[AlertPoolItem]

class AlertPoolSelectionRequest(BaseModel):
    selected_ids: List[str]

class AlertReviewRequest(BaseModel):
    decision: str = Field(pattern="^(approved|rejected)$")
    reason: str = Field(min_length=3, max_length=1000)
    cleaned_text: str = Field(default="", max_length=20000)

class AlertPoolExpandRequest(BaseModel):
    targetTotal: int = ALERT_POOL_TARGET_TOTAL
    startDate: str = "2020-01-01"

class AlertPoolExpandResponse(BaseModel):
    added: int
    total: int
    counts: Dict[str, int]
    eligible_total: int
    eligible_counts: Dict[str, int]
    scanned_categories: List[str] = Field(default_factory=list)
    message: str

class ResearchCorpusPrepareRequest(BaseModel):
    systems: List[str] = Field(default_factory=lambda: ["gemini", "gpt5.5", "llama3"])
    languages: List[str] = Field(default_factory=lambda: ["es", "hi"])

class ResearchCorpusTranslateRequest(BaseModel):
    system: str = Field(pattern="^(gemini|gpt5.5|llama3)$")
    language: str = Field(pattern="^(es|hi)$")
    batch_size: int = Field(default=5, ge=1, le=10)
    regenerate_alert_id: Optional[str] = None

class ResearchCorpusTranslationReviewRequest(BaseModel):
    alert_id: str
    system: str = Field(pattern="^(gemini|gpt5.5|llama3)$")
    language: str = Field(pattern="^(es|hi)$")
    decision: str = Field(pattern="^(approved|rejected)$")
    reason: str = Field(min_length=3, max_length=1000)
    reviewed_text: str = Field(default="", max_length=30000)

# Simple dedupe by normalized source_text
def _normalize_text(text: str) -> str:
    import re
    t = (text or "").lower()
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"\s*([,.;:!?])\s*", r" \1 ", t)
    return re.sub(r"\s+", " ", t).strip()

def _dedupe_by_text(alerts: List[EmergencyAlert]) -> List[EmergencyAlert]:
    seen: set[str] = set()
    out: List[EmergencyAlert] = []
    for a in alerts:
        key = _normalize_text(a.source_text)
        if key in seen:
            continue
        seen.add(key)
        out.append(a)
    return out


# --- Google (Firebase) authentication allowlist ----------------------------
# Maps an authorized Google account email to its role and, for evaluators,
# the single language they are allowed to score in.
#   role:     "admin" | "user"
#   language: "es" | "hi" | None (None = no restriction, e.g. admins)
#
# The defaults below seed the allowlist on first run. Admins can add or remove
# users at runtime; the live allowlist is stored durably (GCS, with a local
# file fallback) so changes survive Cloud Run restarts.
DEFAULT_ACCESS_ALLOWLIST: Dict[str, Dict[str, Optional[str]]] = {
    "mishra@rmu.edu": {"role": "user", "language": "hi"},
    "njgst201@mail.rmu.edu": {"role": "user", "language": "es"},
    "sxnst181@mail.rmu.edu": {"role": "admin", "language": None},
    "efynnaikins2014@gmail.com": {"role": "admin", "language": None},
}
ACCESS_ALLOWLIST: Dict[str, Dict[str, Optional[str]]] = dict(DEFAULT_ACCESS_ALLOWLIST)
ACCESS_ALLOWLIST_GCS_OBJECT = os.getenv("ACCESS_ALLOWLIST_GCS_OBJECT", "access/allowlist.json").strip()
ACCESS_ALLOWLIST_FILE = OUTPUTS_DIR / ".access_allowlist.json"


def _normalize_allowlist(data: object) -> Dict[str, Dict[str, Optional[str]]]:
    """Coerce raw allowlist data into a validated {email: {role, language}} map."""
    out: Dict[str, Dict[str, Optional[str]]] = {}
    if isinstance(data, dict):
        for email, entry in data.items():
            if not isinstance(entry, dict):
                continue
            normalized_email = str(email).strip().lower()
            if not normalized_email:
                continue
            role = str(entry.get("role", "user")).strip().lower()
            if role not in ("admin", "user"):
                role = "user"
            language_raw = entry.get("language")
            language = str(language_raw).strip().lower() if language_raw else None
            if language not in ("es", "hi"):
                language = None
            out[normalized_email] = {"role": role, "language": language}
    return out


def _save_access_allowlist() -> None:
    """Persist the live allowlist to the durable store (GCS) or local disk."""
    payload = json.dumps(ACCESS_ALLOWLIST, ensure_ascii=False, indent=2)
    blob = _gcs_blob(ACCESS_ALLOWLIST_GCS_OBJECT)
    if blob is not None:
        try:
            blob.upload_from_string(payload, content_type="application/json")
            return
        except Exception as exc:
            _storage_logger.error("Failed to save access allowlist to Cloud Storage: %s", exc)
            raise HTTPException(status_code=500, detail="Failed to persist user list")
    try:
        OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
        ACCESS_ALLOWLIST_FILE.write_text(payload, encoding="utf-8")
    except Exception as exc:
        print(f"Failed to save access allowlist: {exc}")


def _load_access_allowlist() -> None:
    """Load the live allowlist from the durable store (GCS) or local disk.

    When nothing is stored yet, seed it from the built-in defaults and persist
    so the initial admins are always available."""
    global ACCESS_ALLOWLIST
    raw: Optional[str] = None
    blob = _gcs_blob(ACCESS_ALLOWLIST_GCS_OBJECT)
    if blob is not None:
        try:
            if blob.exists():
                raw = blob.download_as_text()
        except Exception as exc:
            _storage_logger.error("Failed to load access allowlist from Cloud Storage: %s", exc)
    if raw is None and ACCESS_ALLOWLIST_FILE.exists():
        try:
            raw = ACCESS_ALLOWLIST_FILE.read_text(encoding="utf-8")
        except Exception:
            raw = None
    if raw and raw.strip():
        try:
            loaded = _normalize_allowlist(json.loads(raw))
            if loaded:
                ACCESS_ALLOWLIST = loaded
                return
        except Exception as exc:
            _storage_logger.error("Failed to parse access allowlist: %s", exc)
    # Nothing stored yet: seed from defaults and persist.
    ACCESS_ALLOWLIST = dict(DEFAULT_ACCESS_ALLOWLIST)
    _save_access_allowlist()


# Load the live allowlist on startup (seeds defaults on first run).
_load_access_allowlist()

_firebase_app = None
_firebase_init_error: Optional[str] = None


def _ensure_firebase():
    """Lazily initialize the Firebase Admin SDK.

    Uses GOOGLE_APPLICATION_CREDENTIALS / FIREBASE_CREDENTIALS if a service
    account file is provided, otherwise falls back to Application Default
    Credentials (works automatically on Google Cloud Run).
    """
    global _firebase_app, _firebase_init_error
    if _firebase_app is not None:
        return _firebase_app
    if _firebase_init_error is not None:
        return None
    try:
        import firebase_admin
        from firebase_admin import credentials

        cred_path = (
            os.getenv("FIREBASE_CREDENTIALS")
            or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
            or ""
        ).strip()
        if firebase_admin._apps:
            _firebase_app = firebase_admin.get_app()
        elif cred_path and Path(cred_path).exists():
            _firebase_app = firebase_admin.initialize_app(
                credentials.Certificate(cred_path)
            )
        else:
            # Application Default Credentials (Cloud Run, gcloud auth, etc.)
            _firebase_app = firebase_admin.initialize_app()
        return _firebase_app
    except Exception as exc:  # pragma: no cover - environment dependent
        _firebase_init_error = str(exc)
        return None


def _verify_google_id_token(id_token: str) -> Dict[str, object]:
    """Verify a Firebase/Google ID token and return its decoded claims."""
    app = _ensure_firebase()
    if app is None:
        raise HTTPException(
            status_code=503,
            detail="Authentication is not configured on the server",
        )
    try:
        from firebase_admin import auth as firebase_auth

        return firebase_auth.verify_id_token(id_token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired Google sign-in token")

def _create_session(username: str, role: str, email: str = "", language: Optional[str] = None) -> Dict[str, object]:
    exp = time.time() + SESSION_TTL_SECONDS
    session = {
        "username": username,
        "role": role,
        "email": email,
        "language": language,
        "exp": exp,
    }
    payload = base64.urlsafe_b64encode(
        json.dumps(session, separators=(",", ":")).encode("utf-8")
    ).rstrip(b"=").decode("ascii")
    signature = hmac.new(
        SESSION_SECRET.encode("utf-8"),
        payload.encode("ascii"),
        hashlib.sha256,
    ).digest()
    token = f"{payload}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode('ascii')}"
    return {
        "token": token,
        "username": username,
        "role": role,
        "email": email,
        "language": language,
        "expires_at": datetime.utcfromtimestamp(exp).isoformat(),
    }

def _get_valid_session(token: str) -> Optional[Dict[str, object]]:
    sess = SESSIONS.get(token)
    if not sess:
        try:
            payload, encoded_signature = token.split(".", 1)
            expected_signature = hmac.new(
                SESSION_SECRET.encode("utf-8"),
                payload.encode("ascii"),
                hashlib.sha256,
            ).digest()
            padding = "=" * (-len(encoded_signature) % 4)
            supplied_signature = base64.urlsafe_b64decode(encoded_signature + padding)
            if not hmac.compare_digest(expected_signature, supplied_signature):
                return None
            payload_padding = "=" * (-len(payload) % 4)
            decoded = json.loads(base64.urlsafe_b64decode(payload + payload_padding))
            if not isinstance(decoded, dict):
                return None
            sess = decoded
        except (ValueError, TypeError, json.JSONDecodeError, binascii.Error):
            return None
    exp = float(sess.get("exp", 0) or 0)
    if exp <= time.time():
        SESSIONS.pop(token, None)
        return None
    return sess

def _require_session(authorization: Optional[str]) -> Dict[str, object]:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing session token")
    sess = _get_valid_session(token)
    if not sess:
        raise HTTPException(status_code=401, detail="Session is invalid or expired")
    return sess

def _require_session_role(authorization: Optional[str], role: str) -> Dict[str, object]:
    sess = _require_session(authorization)
    if str(sess.get("role", "")).lower() != role.lower():
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return sess

def _safe_mean(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0

def _read_csv_rows(csv_path: Path) -> List[Dict[str, str]]:
    if not csv_path.exists():
        return []
    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))

def _to_float(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None

def _extract_notes(raw: str) -> str:
    if not raw:
        return ""
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return str(parsed.get("notes", "") or "")
    except Exception:
        pass
    return raw

# ---------------------------------------------------------------------------
# Human submission management (review / edit / delete)
# ---------------------------------------------------------------------------
SUBMISSIONS_FIELDNAMES = [
    "timestamp",
    "evaluator_id",
    "evaluator_name",
    "alert_id",
    "corpus_id",
    "source_hash",
    "translation_hash",
    "language",
    "system",
    "source_segment",
    "translated_segment",
    *FAIRNESS_METRIC_KEYS,
    "rationale",
]


def _submissions_csv_path() -> Path:
    return OUTPUTS_DIR / "human_fairness_scores.csv"


def _session_owns_submission(sess: Dict[str, object], row: Dict[str, str]) -> bool:
    """A submission belongs to a user when its recorded identity matches the
    signed-in account's email or username (case-insensitive)."""
    email = str(sess.get("email") or "").strip().lower()
    name = str(sess.get("username") or "").strip().lower()
    row_id = str(row.get("evaluator_id") or "").strip().lower()
    row_name = str(row.get("evaluator_name") or "").strip().lower()
    if email and row_id == email:
        return True
    if name and (row_id == name or row_name == name):
        return True
    return False


def _submission_to_dict(row: Dict[str, str]) -> Dict[str, Any]:
    scores: Dict[str, Optional[int]] = {}
    for key in FAIRNESS_METRIC_KEYS:
        value = _to_float(row.get(key))
        scores[key] = int(value) if value is not None else None
    timestamp = (row.get("timestamp") or "").strip()
    return {
        "id": timestamp,
        "timestamp": timestamp,
        "evaluator_id": (row.get("evaluator_id") or "").strip(),
        "evaluator_name": (row.get("evaluator_name") or "").strip(),
        "alert_id": (row.get("alert_id") or "").strip(),
        "corpus_id": (row.get("corpus_id") or "").strip(),
        "source_hash": (row.get("source_hash") or "").strip(),
        "translation_hash": (row.get("translation_hash") or "").strip(),
        "language": (row.get("language") or "").strip(),
        "system": (row.get("system") or "").strip(),
        "source_segment": (row.get("source_segment") or "").strip(),
        "translated_segment": (row.get("translated_segment") or "").strip(),
        "scores": scores,
        "notes": _extract_notes((row.get("rationale") or "").strip()),
    }


def _write_submissions(csv_path: Path, rows: List[Dict[str, str]]) -> None:
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SUBMISSIONS_FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in SUBMISSIONS_FIELDNAMES})


# ---------------------------------------------------------------------------
# Durable submission storage (Google Cloud Storage)
#
# Cloud Run instances are ephemeral, so submissions written to the local CSV do
# not survive restarts or new deployments. When ``SUBMISSIONS_GCS_BUCKET`` is
# set the submission rows are stored as a single JSON object in Cloud Storage
# (source of truth) so records persist until explicitly deleted. Without the
# env var the code falls back to the local CSV, which keeps local development
# working unchanged.
# ---------------------------------------------------------------------------
_submissions_logger = logging.getLogger("ipaws.submissions")
SUBMISSIONS_GCS_BUCKET = GCS_BUCKET
SUBMISSIONS_GCS_OBJECT = os.getenv("SUBMISSIONS_GCS_OBJECT", "submissions/human_fairness_scores.json").strip()


def _submissions_gcs_blob():
    """Return the Cloud Storage blob holding submissions, or ``None`` when the
    GCS backend is not configured/available (falls back to local CSV)."""
    return _gcs_blob(SUBMISSIONS_GCS_OBJECT)


def _normalize_submission_row(row: Dict[str, Any]) -> Dict[str, str]:
    normalized: Dict[str, str] = {}
    for key in SUBMISSIONS_FIELDNAMES:
        value = row.get(key)
        normalized[key] = "" if value is None else str(value)
    return normalized


def _load_submission_rows() -> List[Dict[str, str]]:
    """Load all submission rows from the durable store (GCS) or local CSV."""
    blob = _submissions_gcs_blob()
    if blob is None:
        return _read_csv_rows(_submissions_csv_path())
    try:
        if blob.exists():
            raw = blob.download_as_text()
            data = json.loads(raw) if raw.strip() else []
            if isinstance(data, list):
                return [_normalize_submission_row(r) for r in data if isinstance(r, dict)]
            return []
        # Blob does not exist yet: seed it once from any CSV shipped in the
        # image so pre-existing records are preserved, then treat GCS as
        # authoritative from here on.
        seed_rows = [_normalize_submission_row(r) for r in _read_csv_rows(_submissions_csv_path())]
        _save_submission_rows(seed_rows)
        return seed_rows
    except Exception as exc:
        _submissions_logger.error("Failed to load submissions from Cloud Storage: %s", exc)
        return _read_csv_rows(_submissions_csv_path())


def _save_submission_rows(rows: List[Dict[str, Any]]) -> None:
    """Persist the full set of submission rows to the durable store."""
    normalized = [_normalize_submission_row(r) for r in rows]
    blob = _submissions_gcs_blob()
    if blob is None:
        _write_submissions(_submissions_csv_path(), normalized)
        return
    try:
        blob.upload_from_string(
            json.dumps(normalized, ensure_ascii=False, indent=2),
            content_type="application/json",
        )
    except Exception as exc:
        _submissions_logger.error("Failed to save submissions to Cloud Storage: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to persist submissions")


def _append_submission_row(row: Dict[str, Any]) -> None:
    rows = _load_submission_rows()
    rows.append(_normalize_submission_row(row))
    _save_submission_rows(rows)



def _build_normal_distribution(values: List[float], bucket_count: int = 8) -> Dict[str, Any]:
    if not values:
        return {
            "mean": 0.0,
            "stddev": 0.0,
            "count": 0,
            "bins": [],
        }

    mean_value = _safe_mean(values)
    if len(values) > 1:
        variance = sum((value - mean_value) ** 2 for value in values) / (len(values) - 1)
        stddev = math.sqrt(max(variance, 0.0))
    else:
        stddev = 0.0

    data_min = min(values)
    data_max = max(values)
    if math.isclose(data_min, data_max):
        data_min -= 1.0
        data_max += 1.0

    bucket_count = max(5, min(bucket_count, 12))
    width = (data_max - data_min) / bucket_count if bucket_count else 1.0
    bins: List[Dict[str, Any]] = []
    counts = [0 for _ in range(bucket_count)]

    for value in values:
        if width <= 0:
            idx = 0
        else:
            idx = int((value - data_min) / width)
            if idx == bucket_count:
                idx -= 1
        counts[max(0, min(idx, bucket_count - 1))] += 1

    for idx in range(bucket_count):
        start = data_min + idx * width
        end = start + width
        midpoint = start + (width / 2)
        if stddev > 0 and width > 0:
            pdf = (1 / (stddev * math.sqrt(2 * math.pi))) * math.exp(-0.5 * ((midpoint - mean_value) / stddev) ** 2)
            normal_count = pdf * len(values) * width
        else:
            normal_count = float(len(values)) if idx == bucket_count // 2 else 0.0
        bins.append({
            "label": f"{start:.1f}-{end:.1f}",
            "start": round(start, 2),
            "end": round(end, 2),
            "midpoint": round(midpoint, 2),
            "count": counts[idx],
            "normal_count": round(normal_count, 2),
        })

    return {
        "mean": round(mean_value, 2),
        "stddev": round(stddev, 2),
        "count": len(values),
        "bins": bins,
    }

def _compute_two_way_anova(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    if len(rows) < 3:
        return {
            "dependent_variable": "ofs",
            "factors": ["language", "system"],
            "rows": [],
            "insights": [],
        }

    df = pd.DataFrame(rows)
    if df.empty or df["language"].nunique() < 2 or df["system"].nunique() < 2:
        return {
            "dependent_variable": "ofs",
            "factors": ["language", "system"],
            "rows": [],
            "insights": ["Insufficient factor diversity for two-way ANOVA."],
        }

    # Sparse submission-derived data can leave empty language×system cells,
    # producing a rank-deficient design that makes statsmodels raise on NaN/inf.
    # Treat any such numerical failure as "not enough data" rather than a 500.
    try:
        model = ols("ofs ~ C(language) + C(system) + C(language):C(system)", data=df).fit()
        anova_df = anova_lm(model, typ=2).reset_index().rename(columns={"index": "source"})
    except Exception as exc:
        logging.getLogger("ipaws.analytics").warning("Two-way ANOVA skipped: %s", exc)
        return {
            "dependent_variable": "ofs",
            "factors": ["language", "system"],
            "rows": [],
            "insights": ["Not enough balanced data across language and system for a two-way ANOVA yet."],
        }
    total_sum_sq = float(anova_df["sum_sq"].sum()) if "sum_sq" in anova_df else 0.0
    residual_sum_sq = float(anova_df.loc[anova_df["source"] == "Residual", "sum_sq"].iloc[0]) if (anova_df["source"] == "Residual").any() else 0.0

    label_map = {
        "C(language)": "Language",
        "C(system)": "System",
        "C(language):C(system)": "Language × System",
        "Residual": "Residual",
    }

    results: List[Dict[str, Any]] = []
    insights: List[str] = []
    for _, row in anova_df.iterrows():
        source = str(row.get("source", ""))
        sum_sq = float(row.get("sum_sq", 0.0) or 0.0)
        df_value = float(row.get("df", 0.0) or 0.0)
        f_value = row.get("F")
        p_value = row.get("PR(>F)")
        mean_sq = (sum_sq / df_value) if df_value and source != "Residual" else None
        partial_eta_sq = None
        if source != "Residual" and (sum_sq + residual_sum_sq) > 0:
            partial_eta_sq = sum_sq / (sum_sq + residual_sum_sq)

        is_significant = source != "Residual" and p_value is not None and not pd.isna(p_value) and float(p_value) < 0.05
        if is_significant:
            insights.append(f"{label_map.get(source, source)} has a statistically significant effect on OFS (p={float(p_value):.4f}).")

        results.append({
            "source": source,
            "label": label_map.get(source, source),
            "df": round(df_value, 2),
            "sum_sq": round(sum_sq, 4),
            "mean_sq": round(mean_sq, 4) if mean_sq is not None else None,
            "f_value": round(float(f_value), 4) if f_value is not None and not pd.isna(f_value) else None,
            "p_value": round(float(p_value), 6) if p_value is not None and not pd.isna(p_value) else None,
            "significant": bool(is_significant),
            "effect_size": round(float(partial_eta_sq), 4) if partial_eta_sq is not None else None,
            "variance_share": round((sum_sq / total_sum_sq) * 100, 2) if total_sum_sq > 0 else 0.0,
        })

    if not insights:
        insights.append("No ANOVA factor crossed the 0.05 significance threshold with the current composite dataset.")

    return {
        "dependent_variable": "ofs",
        "factors": ["language", "system"],
        "rows": results,
        "insights": insights,
    }

def _submissions_as_csv_text() -> str:
    """Serialize the durable human-fairness submissions (GCS or local) to CSV.

    Live submissions are stored durably as JSON in Cloud Storage, so the CSV
    must be generated on the fly instead of reading a stale/missing local file."""
    rows = _load_submission_rows()
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=SUBMISSIONS_FIELDNAMES)
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row.get(key, "") for key in SUBMISSIONS_FIELDNAMES})
    return buffer.getvalue()


# Column order for the composite-scores CSV, kept identical to the pipeline
# export so downstream consumers see the same schema.
COMPOSITE_FIELDNAMES = [
    "alert_id",
    "language",
    "system",
    "pfi",
    "ifi",
    "ofs",
    "segments_count",
    "export_timestamp",
]

# Procedural- and interactional-fairness metric keys derived from the shared
# metric label map so the composite formula stays in sync with the rubric.
PF_METRIC_KEYS = [key for key in FAIRNESS_METRIC_KEYS if key.startswith("pf")]
IF_METRIC_KEYS = [key for key in FAIRNESS_METRIC_KEYS if key.startswith("if")]


def _submission_segment_ids(rows: List[Dict[str, str]]) -> Dict[str, str]:
    """Map each source to its official ID, with legacy synthetic ID fallback."""
    ids: Dict[str, str] = {}
    for row in rows:
        source = (row.get("source_segment") or "").strip()
        if source not in ids:
            ids[source] = (row.get("alert_id") or "").strip() or f"SEG-{len(ids):04d}"
    return ids


def _composite_rows_from_submissions() -> List[Dict[str, Any]]:
    """Compute composite fairness scores live from human submissions.

    Mirrors the research pipeline's aggregation: each submission is a
    segment-level evaluation whose procedural (``pfi``) and interactional
    (``ifi``) indices are the mean of the pf*/if* rubric items. Because
    legacy submissions without an ``alert_id`` use a stable synthetic ID. Repeated
    evaluations of the same source segment are grouped and averaged, and the
    overall fairness score is ``ofs = (pfi + ifi) / 2``."""
    rows = _load_submission_rows()
    segment_ids = _submission_segment_ids(rows)

    grouped: Dict[tuple, List[Dict[str, float]]] = defaultdict(list)
    for row in rows:
        source = (row.get("source_segment") or "").strip()
        language = (row.get("language") or "unknown").strip() or "unknown"
        system = (row.get("system") or "unknown").strip() or "unknown"
        pf_vals = [v for v in (_to_float(row.get(k)) for k in PF_METRIC_KEYS) if v is not None]
        if_vals = [v for v in (_to_float(row.get(k)) for k in IF_METRIC_KEYS) if v is not None]
        if not pf_vals and not if_vals:
            continue
        grouped[(segment_ids[source], language, system)].append({
            "pfi": _safe_mean(pf_vals),
            "ifi": _safe_mean(if_vals),
        })

    composite: List[Dict[str, Any]] = []
    for (alert_id, language, system), items in grouped.items():
        pfi = _safe_mean([item["pfi"] for item in items])
        ifi = _safe_mean([item["ifi"] for item in items])
        composite.append({
            "alert_id": alert_id,
            "language": language,
            "system": system,
            "pfi": round(pfi, 6),
            "ifi": round(ifi, 6),
            "ofs": round((pfi + ifi) / 2.0, 6),
            "segments_count": len(items),
        })
    composite.sort(key=lambda r: (r["alert_id"], r["language"], r["system"]))
    return composite


def _composite_as_csv_text() -> str:
    """Serialize submission-derived composite scores to CSV on the fly."""
    rows = _composite_rows_from_submissions()
    ts = datetime.utcnow().isoformat()
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=COMPOSITE_FIELDNAMES)
    writer.writeheader()
    for row in rows:
        writer.writerow({
            "alert_id": row["alert_id"],
            "language": row["language"],
            "system": row["system"],
            "pfi": row["pfi"],
            "ifi": row["ifi"],
            "ofs": row["ofs"],
            "segments_count": row["segments_count"],
            "export_timestamp": ts,
        })
    return buffer.getvalue()


# Column order for the statistical-results CSV, matching the pipeline export.
STATISTICAL_FIELDNAMES = [
    "name",
    "test",
    "statistic",
    "p_value",
    "effect_size",
    "export_timestamp",
]


def _statistical_rows_from_submissions() -> List[Dict[str, Any]]:
    """Run hypotheses H1-H3 live on submission-derived composite scores.

    H1/H2 compare procedural/interactional fairness across translation systems,
    H3 compares overall fairness between Spanish and Hindi. Each test may be
    undefined until enough balanced data exists (e.g. a single system or
    language), in which case a blank row is emitted rather than failing."""
    df = pd.DataFrame(_composite_rows_from_submissions())
    hypotheses = [
        ("H1", test_hypothesis_h1),
        ("H2", test_hypothesis_h2),
        ("H3", test_hypothesis_h3),
    ]
    results: List[Dict[str, Any]] = []
    for name, test_fn in hypotheses:
        row = {"name": name, "test": "", "statistic": None, "p_value": None, "effect_size": None}
        if not df.empty:
            try:
                res = test_fn(df)
                row.update({
                    "test": res.get("test", ""),
                    "statistic": res.get("statistic"),
                    "p_value": res.get("p_value"),
                    "effect_size": res.get("effect_size"),
                })
            except Exception as exc:
                logging.getLogger("ipaws.analytics").warning("Hypothesis %s skipped: %s", name, exc)
        results.append(row)
    return results


def _statistical_as_csv_text() -> str:
    """Serialize submission-derived statistical results to CSV on the fly."""
    rows = _statistical_rows_from_submissions()
    ts = datetime.utcnow().isoformat()
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=STATISTICAL_FIELDNAMES)
    writer.writeheader()
    for row in rows:
        writer.writerow({
            "name": row["name"],
            "test": row.get("test", ""),
            "statistic": "" if row.get("statistic") is None else row["statistic"],
            "p_value": "" if row.get("p_value") is None else row["p_value"],
            "effect_size": "" if row.get("effect_size") is None else row["effect_size"],
            "export_timestamp": ts,
        })
    return buffer.getvalue()


# Column order for the translations CSV, matching the pipeline export schema.
TRANSLATIONS_FIELDNAMES = [
    "alert_id",
    "system",
    "target_language",
    "translation_text",
    "meta_model",
    "meta_timestamp",
    "meta_tokens",
    "export_timestamp",
]


def _translation_rows_from_submissions() -> List[Dict[str, Any]]:
    """Derive translation records from human submissions.

    Each submission pairs a source segment with its translated segment for a
    given system/language, which is exactly one translation record. Identical
    (segment, system, language, translation) tuples are de-duplicated."""
    rows = _load_submission_rows()
    segment_ids = _submission_segment_ids(rows)
    seen: set = set()
    out: List[Dict[str, Any]] = []
    for row in rows:
        source = (row.get("source_segment") or "").strip()
        translated = (row.get("translated_segment") or "").strip()
        if not translated:
            continue
        language = (row.get("language") or "unknown").strip() or "unknown"
        system = (row.get("system") or "unknown").strip() or "unknown"
        alert_id = segment_ids.get(source, "SEG-0000")
        key = (alert_id, system, language, translated)
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "alert_id": alert_id,
            "system": system,
            "target_language": language,
            "translation_text": translated,
            "meta_model": "human_submission",
            "meta_timestamp": (row.get("timestamp") or "").strip(),
            "meta_tokens": "",
        })
    out.sort(key=lambda r: (r["alert_id"], r["target_language"], r["system"]))
    return out


def _translations_as_csv_text() -> str:
    """Serialize submission-derived translations to CSV on the fly."""
    rows = _translation_rows_from_submissions()
    ts = datetime.utcnow().isoformat()
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=TRANSLATIONS_FIELDNAMES)
    writer.writeheader()
    for row in rows:
        row_out = dict(row)
        row_out["export_timestamp"] = ts
        writer.writerow(row_out)
    return buffer.getvalue()


# Column order for the segments CSV, matching the pipeline export schema.
SEGMENTS_FIELDNAMES = [
    "alert_id",
    "segment_index",
    "segment_text",
    "communicative_function",
    "language",
    "export_timestamp",
]


def _segment_rows_from_submissions() -> List[Dict[str, Any]]:
    """Derive source segments from human submissions.

    Each unique source segment becomes one segment record. Submissions do not
    capture the communicative function, so it is reported as ``unknown``; the
    source text is English, matching the pipeline's ``en`` segments."""
    rows = _load_submission_rows()
    segment_ids = _submission_segment_ids(rows)
    seen: set = set()
    out: List[Dict[str, Any]] = []
    for row in rows:
        source = (row.get("source_segment") or "").strip()
        if not source:
            continue
        alert_id = segment_ids[source]
        if alert_id in seen:
            continue
        seen.add(alert_id)
        out.append({
            "alert_id": alert_id,
            "segment_index": 0,
            "segment_text": source,
            "communicative_function": "unknown",
            "language": "en",
        })
    out.sort(key=lambda r: r["alert_id"])
    return out


def _segments_as_csv_text() -> str:
    """Serialize submission-derived segments to CSV on the fly."""
    rows = _segment_rows_from_submissions()
    ts = datetime.utcnow().isoformat()
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=SEGMENTS_FIELDNAMES)
    writer.writeheader()
    for row in rows:
        row_out = dict(row)
        row_out["export_timestamp"] = ts
        writer.writerow(row_out)
    return buffer.getvalue()


def _available_downloads() -> List[Dict[str, str]]:
    downloads: List[Dict[str, str]] = []
    # Every downloadable dataset is generated on demand from the durable
    # submission store (GCS/local JSON), so they are always available even when
    # no local CSV file exists on the ephemeral Cloud Run filesystem.
    for key, meta in DOWNLOADABLE_OUTPUTS.items():
        downloads.append({
            "key": key,
            "label": meta["label"],
            "filename": meta["filename"],
            "url": f"/admin/download/{key}",
        })
    return downloads

def _analyze_human_scores() -> Dict[str, Any]:
    rows = _load_submission_rows()
    parsed_rows: List[Dict[str, Any]] = []

    for row in rows:
        metric_values: Dict[str, float] = {}
        for key in FAIRNESS_METRIC_KEYS:
            value = _to_float(row.get(key))
            if value is not None:
                metric_values[key] = value
        metric_list = list(metric_values.values())
        avg_score = _safe_mean(metric_list)
        timestamp = (row.get("timestamp") or "").strip()
        parsed_rows.append({
            "timestamp": timestamp,
            "date": timestamp.split("T", 1)[0] if timestamp else "Unknown",
            "language": (row.get("language") or "unknown").strip() or "unknown",
            "system": (row.get("system") or "unknown").strip() or "unknown",
            "evaluator_id": (row.get("evaluator_id") or "").strip() or "Anonymous",
            "evaluator_name": (row.get("evaluator_name") or "").strip(),
            "source_segment": (row.get("source_segment") or "").strip(),
            "translated_segment": (row.get("translated_segment") or "").strip(),
            "notes": _extract_notes((row.get("rationale") or "").strip()),
            "metrics": metric_values,
            "average_score": avg_score,
            "average_score_pct": round((avg_score / 2) * 100, 1) if metric_list else 0.0,
        })

    metric_summary: List[Dict[str, Any]] = []
    for key in FAIRNESS_METRIC_KEYS:
        values = [float(r["metrics"][key]) for r in parsed_rows if key in r["metrics"]]
        avg_value = _safe_mean(values)
        metric_summary.append({
            "key": key,
            "label": FAIRNESS_METRIC_LABELS[key],
            "average": round(avg_value, 2),
            "average_pct": round((avg_value / 2) * 100, 1) if values else 0.0,
        })

    language_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    system_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    evaluator_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    day_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in parsed_rows:
        language_groups[row["language"]].append(row)
        system_groups[row["system"]].append(row)
        evaluator_groups[row["evaluator_id"]].append(row)
        day_groups[row["date"]].append(row)

    languages = [
        {
            "language": language,
            "count": len(items),
            "average_score": round(_safe_mean([float(i["average_score"]) for i in items]), 2),
            "average_score_pct": round(_safe_mean([float(i["average_score_pct"]) for i in items]), 1),
        }
        for language, items in language_groups.items()
    ]
    languages.sort(key=lambda item: (-item["count"], item["language"]))

    systems = [
        {
            "system": system,
            "count": len(items),
            "average_score": round(_safe_mean([float(i["average_score"]) for i in items]), 2),
            "average_score_pct": round(_safe_mean([float(i["average_score_pct"]) for i in items]), 1),
        }
        for system, items in system_groups.items()
    ]
    systems.sort(key=lambda item: (-item["count"], item["system"]))

    evaluators = [
        {
            "evaluator_id": evaluator,
            "evaluator_name": next((str(i["evaluator_name"]) for i in items if i.get("evaluator_name")), ""),
            "count": len(items),
            "languages": sorted({str(i["language"]) for i in items}),
            "average_score": round(_safe_mean([float(i["average_score"]) for i in items]), 2),
            "average_score_pct": round(_safe_mean([float(i["average_score_pct"]) for i in items]), 1),
        }
        for evaluator, items in evaluator_groups.items()
    ]
    evaluators.sort(key=lambda item: (-item["count"], item["evaluator_id"]))

    submissions_by_day = [
        {
            "date": day,
            "count": len(items),
            "average_score_pct": round(_safe_mean([float(i["average_score_pct"]) for i in items]), 1),
        }
        for day, items in day_groups.items()
    ]
    submissions_by_day.sort(key=lambda item: item["date"])

    recent_submissions = [
        {
            "timestamp": row["timestamp"],
            "evaluator_id": row["evaluator_id"],
            "evaluator_name": row["evaluator_name"],
            "language": row["language"],
            "system": row["system"],
            "average_score_pct": row["average_score_pct"],
            "source_preview": row["source_segment"][:120],
            "notes": row["notes"][:140],
        }
        for row in sorted(parsed_rows, key=lambda item: item["timestamp"], reverse=True)[:10]
    ]

    average_scores = [float(r["average_score"]) for r in parsed_rows]
    return {
        "path": (
            f"gs://{SUBMISSIONS_GCS_BUCKET}/{SUBMISSIONS_GCS_OBJECT}"
            if SUBMISSIONS_GCS_BUCKET
            else str(_submissions_csv_path())
        ),
        "total_submissions": len(parsed_rows),
        "unique_messages": len({str(r["source_segment"]) for r in parsed_rows if r.get("source_segment")}),
        "named_evaluators": len({str(r["evaluator_id"]) for r in parsed_rows if r.get("evaluator_id") and r["evaluator_id"] != "Anonymous"}),
        "average_score": round(_safe_mean(average_scores), 2),
        "average_score_pct": round((_safe_mean(average_scores) / 2) * 100, 1) if average_scores else 0.0,
        "languages": languages,
        "systems": systems,
        "metrics": metric_summary,
        "evaluators": evaluators,
        "submissions_by_day": submissions_by_day,
        "recent_submissions": recent_submissions,
        "normal_distribution": _build_normal_distribution([float(r["average_score_pct"]) for r in parsed_rows]),
    }

def _analyze_composite_scores() -> Dict[str, Any]:
    # Composite scores are computed live from the human submissions rather than
    # a stale CSV in the outputs folder, so the dashboard and the CSV download
    # always reflect the same current data.
    source_rows = _composite_rows_from_submissions()
    parsed_rows: List[Dict[str, Any]] = []

    for row in source_rows:
        parsed_rows.append({
            "language": (row.get("language") or "unknown") or "unknown",
            "system": (row.get("system") or "unknown") or "unknown",
            "pfi": float(row.get("pfi") or 0.0),
            "ifi": float(row.get("ifi") or 0.0),
            "ofs": float(row.get("ofs") or 0.0),
            "segments_count": float(row.get("segments_count") or 0.0),
        })

    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in parsed_rows:
        grouped[f"{row['language']}::{row['system']}"] .append(row)

    by_language_system: List[Dict[str, Any]] = []
    for key, items in grouped.items():
        language, system = key.split("::", 1)
        by_language_system.append({
            "language": language,
            "system": system,
            "count": len(items),
            "avg_pfi": round(_safe_mean([float(i["pfi"]) for i in items]), 3),
            "avg_ifi": round(_safe_mean([float(i["ifi"]) for i in items]), 3),
            "avg_ofs": round(_safe_mean([float(i["ofs"]) for i in items]), 3),
            "avg_segments": round(_safe_mean([float(i["segments_count"]) for i in items]), 1),
        })
    by_language_system.sort(key=lambda item: (item["language"], item["system"]))

    by_language: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in by_language_system:
        by_language[str(row["language"])].append(row)

    best_by_language = []
    for language, items in by_language.items():
        best = max(items, key=lambda item: float(item["avg_ofs"]))
        best_by_language.append({
            "language": language,
            "system": best["system"],
            "avg_ofs": best["avg_ofs"],
            "avg_pfi": best["avg_pfi"],
            "avg_ifi": best["avg_ifi"],
        })
    best_by_language.sort(key=lambda item: item["language"])

    by_system: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in parsed_rows:
        by_system[str(row["system"])].append(row)

    system_rankings = [
        {
            "system": system,
            "count": len(items),
            "avg_ofs": round(_safe_mean([float(i["ofs"]) for i in items]), 3),
            "avg_pfi": round(_safe_mean([float(i["pfi"]) for i in items]), 3),
            "avg_ifi": round(_safe_mean([float(i["ifi"]) for i in items]), 3),
        }
        for system, items in by_system.items()
    ]
    system_rankings.sort(key=lambda item: (-item["avg_ofs"], item["system"]))

    return {
        "path": "computed_from_submissions",
        "total_records": len(parsed_rows),
        "by_language_system": by_language_system,
        "best_by_language": best_by_language,
        "system_rankings": system_rankings,
        "two_way_anova": _compute_two_way_anova(parsed_rows),
    }

@app.get("/health")
async def health():
    return {"status": "ok", "time": datetime.utcnow().isoformat()}

@app.get("/config")
async def config():
    return {
        "OFFLINE_MODE": os.getenv("OFFLINE_MODE", ""),
        "OPENAI_MODEL": os.getenv("OPENAI_MODEL", ""),
        "GOOGLE_CLOUD_PROJECT": os.getenv("GOOGLE_CLOUD_PROJECT", ""),
        "GCP_PROJECT_ID": os.getenv("GCP_PROJECT_ID", ""),
        "REPLICATE_LLAMA3_MODEL": os.getenv("REPLICATE_LLAMA3_MODEL", "meta/meta-llama-3-8b-instruct"),
    }

@app.post("/auth/google", response_model=LoginResponse)
async def auth_google(req: GoogleLoginRequest):
    """Sign in with a Google (Firebase) ID token.

    The token is verified server-side, then the account's email is checked
    against the allowlist to assign role and (for evaluators) language.
    """
    if not req.id_token:
        raise HTTPException(status_code=400, detail="Missing Google sign-in token")
    claims = _verify_google_id_token(req.id_token)
    email = str(claims.get("email", "")).strip().lower()
    if not email:
        raise HTTPException(status_code=401, detail="Google account has no email")
    if not claims.get("email_verified", False):
        raise HTTPException(status_code=403, detail="Google email is not verified")
    entry = ACCESS_ALLOWLIST.get(email)
    if not entry:
        raise HTTPException(status_code=403, detail="This account is not authorized to access the app")
    display_name = str(claims.get("name") or email)
    session = _create_session(
        username=display_name,
        role=str(entry["role"]),
        email=email,
        language=entry.get("language"),
    )
    return LoginResponse(**session)

@app.get("/auth/session", response_model=SessionStatusResponse)
async def auth_session(authorization: Optional[str] = Header(default=None)):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing session token")
    sess = _get_valid_session(token)
    if not sess:
        raise HTTPException(status_code=401, detail="Session is invalid or expired")
    exp = float(sess.get("exp", 0) or 0)
    return SessionStatusResponse(
        valid=True,
        role=str(sess.get("role", "user")),
        username=str(sess.get("username", "")),
        email=str(sess.get("email", "")),
        language=sess.get("language"),
        expires_at=datetime.utcfromtimestamp(exp).isoformat(),
    )

def _allowlist_to_items() -> List[UserItem]:
    items: List[UserItem] = []
    for email, entry in sorted(ACCESS_ALLOWLIST.items()):
        items.append(UserItem(
            email=email,
            role=str(entry.get("role", "user")),
            language=entry.get("language"),
            is_default=email in DEFAULT_ACCESS_ALLOWLIST,
        ))
    return items


@app.get("/admin/users", response_model=UsersResponse)
async def admin_list_users(authorization: Optional[str] = Header(default=None)):
    """List all authorized users (admin only)."""
    _require_session_role(authorization, "admin")
    return UsersResponse(users=_allowlist_to_items())


@app.post("/admin/users", response_model=UsersResponse)
async def admin_upsert_user(
    request: UserUpsertRequest,
    authorization: Optional[str] = Header(default=None),
):
    """Add a new authorized user or update an existing one (admin only)."""
    _require_session_role(authorization, "admin")
    email = request.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="A valid email address is required")
    # Evaluators (role "user") must be locked to a single language; admins are
    # never language-restricted.
    language = request.language if request.role == "user" else None
    if request.role == "user" and language not in ("es", "hi"):
        raise HTTPException(status_code=400, detail="Evaluators require a language (Spanish or Hindi)")
    ACCESS_ALLOWLIST[email] = {"role": request.role, "language": language}
    _save_access_allowlist()
    return UsersResponse(users=_allowlist_to_items())


@app.delete("/admin/users/{email}", response_model=UsersResponse)
async def admin_delete_user(email: str, authorization: Optional[str] = Header(default=None)):
    """Remove an authorized user (admin only)."""
    sess = _require_session_role(authorization, "admin")
    target = (email or "").strip().lower()
    if target not in ACCESS_ALLOWLIST:
        raise HTTPException(status_code=404, detail="User is not in the allowlist")
    requester = str(sess.get("email") or "").strip().lower()
    if target == requester:
        raise HTTPException(status_code=400, detail="You cannot remove your own account")
    # Never allow the last admin to be removed, or the app could be locked out.
    remaining_admins = [
        e for e, entry in ACCESS_ALLOWLIST.items()
        if str(entry.get("role")) == "admin" and e != target
    ]
    if str(ACCESS_ALLOWLIST[target].get("role")) == "admin" and not remaining_admins:
        raise HTTPException(status_code=400, detail="Cannot remove the last remaining admin")
    ACCESS_ALLOWLIST.pop(target, None)
    _save_access_allowlist()
    return UsersResponse(users=_allowlist_to_items())

@app.get("/admin/analysis")
async def admin_analysis(authorization: Optional[str] = Header(default=None)):
    sess = _require_session_role(authorization, "admin")
    return {
        "generated_at": datetime.utcnow().isoformat(),
        "viewer": {
            "username": str(sess.get("username", "")),
            "role": str(sess.get("role", "admin")),
        },
        "downloads": _available_downloads(),
        "human": _analyze_human_scores(),
        "composite": _analyze_composite_scores(),
    }

@app.get("/admin/download/{dataset_key}")
async def admin_download_csv(dataset_key: str, authorization: Optional[str] = Header(default=None)):
    _require_session_role(authorization, "admin")
    meta = DOWNLOADABLE_OUTPUTS.get(dataset_key)
    if not meta:
        raise HTTPException(status_code=404, detail="Requested dataset is not available")
    # Every dataset is generated live from the durable submission store so the
    # download always reflects current data rather than a stale/missing bundled
    # CSV on the ephemeral Cloud Run filesystem.
    live_generators = {
        "human_fairness_scores": _submissions_as_csv_text,
        "composite_scores": _composite_as_csv_text,
        "statistical_results": _statistical_as_csv_text,
        "translations": _translations_as_csv_text,
        "segments": _segments_as_csv_text,
    }
    generator = live_generators.get(dataset_key)
    if generator is not None:
        csv_text = generator()
        return Response(
            content=csv_text,
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{meta["filename"]}"'},
        )
    csv_path = OUTPUTS_DIR / meta["filename"]
    if not csv_path.exists():
        raise HTTPException(status_code=404, detail="Requested CSV file does not exist")
    return FileResponse(str(csv_path), media_type="text/csv", filename=meta["filename"])

@app.get("/admin/alert-pool", response_model=AlertPoolResponse)
async def admin_alert_pool(authorization: Optional[str] = Header(default=None)):
    """Return all 70 alert pool items with selection status (admin only)."""
    _require_session_role(authorization, "admin")
    return _build_alert_pool_response()


def _corpus_summary(corpus: Optional[ResearchCorpus]) -> Dict[str, Any]:
    if corpus is None:
        return {"status": "not_prepared", "missing_count": 0}
    missing = corpus_missing_conditions(corpus)
    unapproved = corpus_unapproved_conditions(corpus)
    missing_by_condition = {
        f"{system}:{language}": sum(
            item.endswith(f":{system}:{language}") for item in missing
        )
        for system in corpus.systems
        for language in corpus.languages
    }
    pending_approval_count = sum(
        item.review_decision == "pending" for item in corpus.translations
    )
    return {
        "corpus_id": corpus.corpus_id,
        "status": corpus.status,
        "created_at": corpus.created_at.isoformat(),
        "created_by": corpus.created_by,
        "frozen_at": corpus.frozen_at.isoformat() if corpus.frozen_at else None,
        "frozen_by": corpus.frozen_by,
        "selection_hash": corpus.selection_hash,
        "systems": corpus.systems,
        "languages": corpus.languages,
        "source_count": len(corpus.sources),
        "translation_count": len(corpus.translations),
        "missing_count": len(missing),
        "missing_by_condition": missing_by_condition,
        "approved_count": sum(
            item.review_decision == "approved" and key not in unapproved
            for item in corpus.translations
            for key in [f"{item.alert_id}:{item.system}:{item.language}"]
        ),
        "rejected_count": sum(item.review_decision == "rejected" for item in corpus.translations),
        "unapproved_count": len(unapproved),
        "pending_approval_count": pending_approval_count,
        "review_blocker_count": len(unapproved) - pending_approval_count,
        "translations": [{
            "alert_id": item.alert_id,
            "system": item.system,
            "language": item.language,
            "source_text": next(
                (source.source_text for source in corpus.sources if source.alert_id == item.alert_id),
                "",
            ),
            "generated_translation_text": item.generated_translation_text,
            "translation_text": item.translation_text,
            "review_decision": item.review_decision,
            "metadata": item.metadata,
            "review_history": [event.model_dump(mode="json") for event in item.review_history],
        } for item in corpus.translations],
    }


def _require_frozen_artifact(
    alert_id: Optional[str],
    corpus_id: Optional[str],
    source_text: str,
    translated_text: str,
    system: str,
    language: str,
):
    corpus = _load_research_corpus()
    if corpus is None or corpus.status != "frozen":
        raise HTTPException(status_code=409, detail="Freeze the research corpus before scoring")
    if not alert_id or not corpus_id or corpus_id != corpus.corpus_id:
        raise HTTPException(status_code=409, detail="A valid frozen corpus ID and alert ID are required")
    source = next((item for item in corpus.sources if item.alert_id == alert_id), None)
    if source is None or source.source_text != source_text:
        raise HTTPException(status_code=409, detail="Scoring source text does not match the frozen corpus")
    try:
        artifact = get_frozen_translation(corpus, alert_id, system, language)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if artifact.translation_text != translated_text:
        raise HTTPException(status_code=409, detail="Scoring translation does not match the frozen corpus")
    return corpus, source, artifact


async def _translate_corpus_source(source_text: str, system: str, language: str) -> Dict[str, Any]:
    if system == "gemini":
        return await translate_with_gemini(source_text, language)
    if system == "gpt5.5":
        return await translate_with_gpt4o(source_text, language, model="gpt5.5")
    return await translate_with_llama3(source_text, language)


@app.get("/admin/research-corpus")
async def admin_research_corpus(authorization: Optional[str] = Header(default=None)):
    _require_session_role(authorization, "admin")
    return _corpus_summary(_load_research_corpus())


@app.post("/admin/research-corpus/prepare")
async def admin_prepare_research_corpus(
    request: ResearchCorpusPrepareRequest,
    authorization: Optional[str] = Header(default=None),
):
    session = _require_session_role(authorization, "admin")
    existing = _load_research_corpus()
    if existing and existing.status == "frozen":
        raise HTTPException(status_code=409, detail="The research corpus is frozen and cannot be replaced")
    systems = sorted(set(request.systems))
    languages = sorted(set(request.languages))
    if not systems or not set(systems).issubset({"gemini", "gpt5.5", "llama3"}):
        raise HTTPException(status_code=400, detail="At least one supported translation system is required")
    if not languages or not set(languages).issubset({"es", "hi"}):
        raise HTTPException(status_code=400, detail="At least one supported language is required")
    candidates = _load_alert_candidates()
    selected_ids = sorted(ALERT_POOL_SELECTED)
    _validate_alert_selection(selected_ids, candidates)
    creator = str(session.get("email") or session.get("username") or "").strip()
    corpus = build_corpus_draft(candidates, selected_ids, systems, languages, creator)
    _save_research_corpus(corpus)
    return _corpus_summary(corpus)


@app.post("/admin/research-corpus/translate")
async def admin_translate_research_corpus(
    request: ResearchCorpusTranslateRequest,
    authorization: Optional[str] = Header(default=None),
):
    _require_session_role(authorization, "admin")
    corpus = _load_research_corpus()
    if corpus is None:
        raise HTTPException(status_code=409, detail="Prepare the research corpus before generating translations")
    if corpus.status != "draft":
        raise HTTPException(status_code=409, detail="Frozen corpus translations cannot be changed")
    if request.system not in corpus.systems or request.language not in corpus.languages:
        raise HTTPException(status_code=400, detail="Translation condition is not declared by this corpus")
    present = {
        (item.alert_id, item.system, item.language)
        for item in corpus.translations
    }
    if request.regenerate_alert_id:
        pending = [
            source for source in corpus.sources
            if source.alert_id == request.regenerate_alert_id
        ]
        if not pending:
            raise HTTPException(status_code=404, detail="Translation source was not found")
    else:
        pending = [
            source for source in corpus.sources
            if (source.alert_id, request.system, request.language) not in present
        ][:request.batch_size]
    generated = 0
    for source in pending:
        try:
            result = await _translate_corpus_source(
                source.source_text,
                request.system,
                request.language,
            )
            corpus = add_corpus_translation(
                corpus,
                source.alert_id,
                request.system,
                request.language,
                str(result.get("translation") or ""),
                dict(result.get("metadata") or {}),
            )
            corpus = review_corpus_translation(
                corpus,
                source.alert_id,
                request.system,
                request.language,
                "approved",
                "system:auto-approval",
                "Automatically approved after successful generation.",
            )
            _save_research_corpus(corpus)
            generated += 1
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Translation preparation stopped after {generated} saved artifacts: {exc}",
            )
    return {**_corpus_summary(corpus), "generated": generated}


@app.post("/admin/research-corpus/review-translation")
async def admin_review_research_corpus_translation(
    request: ResearchCorpusTranslationReviewRequest,
    authorization: Optional[str] = Header(default=None),
):
    session = _require_session_role(authorization, "admin")
    corpus = _load_research_corpus()
    if corpus is None:
        raise HTTPException(status_code=409, detail="Prepare the research corpus before reviewing translations")
    reviewer = str(session.get("email") or session.get("username") or "").strip()
    try:
        corpus = review_corpus_translation(
            corpus,
            request.alert_id,
            request.system,
            request.language,
            request.decision,
            reviewer,
            request.reason,
            request.reviewed_text,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    _save_research_corpus(corpus)
    return _corpus_summary(corpus)


@app.post("/admin/research-corpus/freeze")
async def admin_freeze_research_corpus(authorization: Optional[str] = Header(default=None)):
    session = _require_session_role(authorization, "admin")
    corpus = _load_research_corpus()
    if corpus is None:
        raise HTTPException(status_code=409, detail="Prepare the research corpus before freezing it")
    freezer = str(session.get("email") or session.get("username") or "").strip()
    candidates = _load_alert_candidates()
    selected_ids = sorted(ALERT_POOL_SELECTED)
    _validate_alert_selection(selected_ids, candidates)
    current = build_corpus_draft(
        candidates,
        selected_ids,
        corpus.systems,
        corpus.languages,
        freezer,
    )
    if current.selection_hash != corpus.selection_hash:
        raise HTTPException(
            status_code=409,
            detail="Selected alerts or source text changed after preparation; prepare the corpus again",
        )
    for item in list(corpus.translations):
        if item.review_decision == "pending":
            corpus = review_corpus_translation(
                corpus,
                item.alert_id,
                item.system,
                item.language,
                "approved",
                "system:auto-approval",
                "Automatically approved during corpus freeze.",
            )
    try:
        corpus = freeze_corpus(corpus, freezer)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    _save_research_corpus(corpus)
    return _corpus_summary(corpus)


def _validate_alert_selection(selected_ids: List[str], candidates: List[EmergencyAlert]) -> Dict[str, int]:
    if len(selected_ids) != 48 or len(set(selected_ids)) != 48:
        raise HTTPException(status_code=400, detail="Selection must contain exactly 48 unique alert IDs")
    by_id = {candidate.research_id or candidate.alert_id: candidate for candidate in candidates}
    missing = [selected_id for selected_id in selected_ids if selected_id not in by_id]
    if missing:
        raise HTTPException(status_code=400, detail=f"Selection contains unknown alert IDs: {', '.join(missing[:5])}")
    unavailable = [
        selected_id for selected_id in selected_ids
        if not is_candidate_selectable(by_id[selected_id])
    ]
    if unavailable:
        raise HTTPException(
            status_code=400,
            detail=f"Selection contains alerts that are not eligible: {', '.join(unavailable[:5])}",
        )
    counts = {category: 0 for category in ALERT_SELECTION_TARGETS}
    for selected_id in selected_ids:
        category = by_id[selected_id].category
        counts[category] = counts.get(category, 0) + 1
    if counts != ALERT_SELECTION_TARGETS:
        raise HTTPException(
            status_code=400,
            detail=f"Selection must match category targets {ALERT_SELECTION_TARGETS}; received {counts}",
        )
    return counts


@app.post("/admin/alert-pool/{research_id}/review")
async def admin_alert_pool_review(
    research_id: str,
    request: AlertReviewRequest,
    authorization: Optional[str] = Header(default=None),
):
    """Approve or reject a warning-only record with a durable audit event."""
    session = _require_session_role(authorization, "admin")
    candidates = _load_alert_candidates()
    index = next((
        index for index, candidate in enumerate(candidates)
        if (candidate.research_id or candidate.alert_id) == research_id
    ), None)
    if index is None:
        raise HTTPException(status_code=404, detail="Alert candidate not found")
    reviewer_id = str(session.get("email") or session.get("username") or "").strip()
    try:
        reviewed = review_candidate(
            candidates[index],
            decision=request.decision,
            reviewer_id=reviewer_id,
            reason=request.reason,
            cleaned_text=request.cleaned_text,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    candidates[index] = reviewed
    _save_alert_candidates(candidates)

    global ALERT_POOL_SELECTED
    if research_id in ALERT_POOL_SELECTED and not is_candidate_selectable(reviewed):
        ALERT_POOL_SELECTED.discard(research_id)
        _save_alert_pool()
    return {
        "success": True,
        "research_id": research_id,
        "review_decision": reviewed.review_decision,
        "selectable": is_candidate_selectable(reviewed),
        "review_history": [event.model_dump(mode="json") for event in reviewed.review_history],
    }


@app.post("/admin/alert-pool/select")
async def admin_alert_pool_select(
    request: AlertPoolSelectionRequest,
    authorization: Optional[str] = Header(default=None)
):
    """Admin selects which alerts appear in evaluation (admin only)."""
    _require_session_role(authorization, "admin")
    global ALERT_POOL_SELECTED
    corpus = _load_research_corpus()
    if corpus and corpus.status == "frozen":
        raise HTTPException(status_code=409, detail="Alert selection is locked by the frozen research corpus")
    
    candidates = _load_alert_candidates()
    if not candidates:
        raise HTTPException(status_code=409, detail="Fetch and validate official OpenFEMA candidates before selecting a corpus")
    category_counts = _validate_alert_selection(request.selected_ids, candidates)
    ALERT_POOL_SELECTED = set(request.selected_ids)
    _save_alert_pool()
    
    return {
        "success": True,
        "total_selected": len(ALERT_POOL_SELECTED),
        "category_counts": category_counts,
        "message": "Alert pool selection updated successfully"
    }

@app.post("/admin/alert-pool/expand", response_model=AlertPoolExpandResponse)
async def admin_alert_pool_expand(
    request: AlertPoolExpandRequest,
    authorization: Optional[str] = Header(default=None),
):
    """Fetch and upsert structured California alerts from official OpenFEMA."""
    _require_session_role(authorization, "admin")
    target = max(1, int(request.targetTotal))
    if target != sum(ALERT_POOL_ELIGIBLE_TARGETS.values()):
        raise HTTPException(status_code=400, detail="The official candidate pool target must be 200 eligible alerts")
    try:
        start = datetime.fromisoformat(request.startDate)
    except ValueError:
        raise HTTPException(status_code=400, detail="startDate must use ISO format, for example 2020-01-01")
    end = datetime.utcnow()
    existing = {}
    for candidate in _load_alert_candidates():
        candidate = candidate.model_copy(update={
            "category": classify_study_category(
                candidate.cap_categories,
                candidate.response_types,
                candidate.raw_source_text or candidate.source_text,
                candidate.event,
            ),
            "effective": candidate.effective or candidate.sent,
        })
        existing[candidate.research_id or candidate.alert_id] = candidate
    before = len(existing)

    def merge_fetched(records: List[EmergencyAlert]) -> None:
        for candidate in records:
            candidate_id = candidate.research_id or candidate.alert_id
            if candidate_id in existing:
                candidate = merge_review_state(existing[candidate_id], candidate)
            existing[candidate_id] = candidate

    candidates = validate_candidates(existing.values())
    fetched_total = 0
    try:
        missing_categories = [
            category for category, category_target in ALERT_POOL_ELIGIBLE_TARGETS.items()
            if sum(
                1 for candidate in candidates
                if candidate.category == category and is_candidate_selectable(candidate)
            ) < category_target
        ]
        if missing_categories:
            cap_categories = list(dict.fromkeys(
                cap_category
                for category in missing_categories
                for cap_category in (_cap_categories_for(category) or [])
            ))
            category_records = await fetch_ipaws_openapi_alerts(
                start,
                end,
                top=500,
                state="CA",
                shuffle=False,
                limit=4000,
                cap_categories=cap_categories,
            )
            fetched_total = len(category_records)
            merge_fetched(category_records)
            candidates = validate_candidates(existing.values())
    except Exception as exc:
        detail = str(exc).strip() or type(exc).__name__
        raise HTTPException(status_code=502, detail=f"Failed to fetch live alerts: {detail}")

    candidates.sort(key=lambda candidate: candidate.timestamp, reverse=True)
    _save_alert_candidates(candidates)

    counts = {category: 0 for category in ALERT_TEMPLATE_CATEGORIES}
    eligible_counts = {category: 0 for category in ALERT_TEMPLATE_CATEGORIES}
    for candidate in candidates:
        counts[candidate.category] = counts.get(candidate.category, 0) + 1
        if is_candidate_selectable(candidate):
            eligible_counts[candidate.category] = eligible_counts.get(candidate.category, 0) + 1
    added = len(existing) - before
    scanned_labels = ", ".join(category.replace("_", " ").title() for category in missing_categories)
    message = (
        f"Scanned only categories below 50 eligible ({scanned_labels or 'none'}). "
        f"Fetched {fetched_total} category-matched records; added {added}. "
        f"Official pool now has {sum(eligible_counts.values())} eligible and {len(candidates)} total records."
    )
    shortfalls = {
        category: category_target - eligible_counts.get(category, 0)
        for category, category_target in ALERT_POOL_ELIGIBLE_TARGETS.items()
        if eligible_counts.get(category, 0) < category_target
    }
    if shortfalls:
        message += f" Eligible category shortfalls remain: {shortfalls}."
    return AlertPoolExpandResponse(
        added=added,
        total=len(candidates),
        counts=counts,
        eligible_total=sum(eligible_counts.values()),
        eligible_counts=eligible_counts,
        scanned_categories=missing_categories,
        message=message,
    )

@app.get("/admin/alert-pool/download")
async def admin_alert_pool_download(authorization: Optional[str] = Header(default=None)):
    """Download the full alert pool as CSV, including extracted metadata."""
    _require_session_role(authorization, "admin")
    csv_text = _alert_pool_as_csv_text()
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="alert_pool.csv"'},
    )

@app.get("/alerts", response_model=List[dict])
async def alerts(
    category: Optional[str] = None,
    count: int = 10,
    state: str = "CA",
    source: Optional[str] = None,
    startDate: Optional[str] = None,
    endDate: Optional[str] = None,
    eventCode: Optional[List[str]] = Query(default=None),
    capCategories: Optional[List[str]] = Query(default=None),
    daysBack: Optional[int] = None,
    wkt: Optional[str] = None,
    bbox: Optional[str] = None,  # minLon,minLat,maxLon,maxLat
):
    """Return alerts. Default returns the selected 48 alerts from admin pool."""
    
    # Check if we should return the research dataset (default)
    is_default = (not category and not startDate and not endDate and not daysBack)
    
    if is_default or source == "research":
        corpus = _load_research_corpus()
        if corpus and corpus.status == "frozen":
            return [{
                "alert_id": item.alert_id,
                "source_text": item.source_text,
                "source_hash": item.source_hash,
                "corpus_id": corpus.corpus_id,
                "corpus_status": corpus.status,
                "category": item.category,
                "hazard_type": item.category.replace("_", " ").title(),
                "event_type": item.event,
                "timestamp": item.sent.isoformat() if item.sent else "",
                "agency": item.sender,
                "identifier": item.identifier,
                "openfema_id": item.openfema_id,
                "area": item.area,
                "language": item.language,
                "urgency": item.urgency,
                "severity": item.severity,
                "certainty": item.certainty,
                "message_type": item.message_type,
            } for item in corpus.sources]
        candidates = _load_alert_candidates()
        if candidates:
            selected = [
                candidate for candidate in candidates
                if (candidate.research_id or candidate.alert_id) in ALERT_POOL_SELECTED
                and is_candidate_selectable(candidate)
            ]
            return [{
                "alert_id": candidate.research_id or candidate.alert_id,
                "source_text": candidate.cleaned_source_text or candidate.source_text,
                "category": candidate.category,
                "hazard_type": candidate.category.replace("_", " ").title(),
                "event_type": candidate.event,
                "timestamp": candidate.sent.isoformat() if candidate.sent else candidate.timestamp.isoformat(),
                "agency": candidate.sender,
                "identifier": candidate.identifier,
                "openfema_id": candidate.openfema_id,
                "area": candidate.area,
                "language": candidate.language,
                "urgency": candidate.urgency_level,
                "severity": candidate.severity_level,
                "certainty": candidate.certainty_level,
                "message_type": candidate.message_type,
            } for candidate in selected]

        # Load alert templates
        templates = _load_all_alert_templates()
        
        # Build all alerts with their IDs
        all_alerts = []
        alert_id = 0
        for cat in ["weather", "evacuation", "public_safety", "health"]:
            for text in templates.get(cat, []):
                all_alerts.append({
                    "alert_id": str(alert_id),
                    "source_text": text,
                    "category": cat,
                    "hazard_type": cat.replace("_", " ").title(),
                    "event_type": cat.replace("_", " ").title(),
                    "timestamp": "2020-2026",
                    "agency": "FEMA/IPAWS"
                })
                alert_id += 1
        
        # If selection pool exists and has alerts, use it; otherwise default to first 48
        if ALERT_POOL_SELECTED and len(ALERT_POOL_SELECTED) == 48:
            selected_indices = set(int(idx) for idx in ALERT_POOL_SELECTED)
            results = [a for a in all_alerts if int(a["alert_id"]) in selected_indices]
        else:
            results = all_alerts[:48]
        
        return results

    if source == "latest" and CURRENT_STATE.get("alerts"):
        alerts_list = CURRENT_STATE["alerts"]  # type: ignore
        # Coerce to models if necessary
        out: List[EmergencyAlert] = []
        for a in alerts_list:  # type: ignore
            if isinstance(a, EmergencyAlert):
                out.append(a)
            else:
                out.append(EmergencyAlert(**a))
        return _dedupe_by_text(out)
    if startDate and endDate:
        try:
            sd = datetime.fromisoformat(startDate)
            ed = datetime.fromisoformat(endDate)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid startDate/endDate format; use ISO date e.g., 2024-01-01")
        # Parse bbox to WKT if provided
        geo_wkt: Optional[str] = wkt
        if not geo_wkt and bbox:
            try:
                parts = [float(p) for p in bbox.split(',')]
                if len(parts) != 4:
                    raise ValueError("bbox must have 4 comma-separated numbers: minLon,minLat,maxLon,maxLat")
                minlon, minlat, maxlon, maxlat = parts
                # Construct rectangle polygon (closed ring)
                geo_wkt = f"POLYGON(({minlon} {maxlat},{maxlon} {maxlat},{maxlon} {minlat},{minlon} {minlat},{minlon} {maxlat}))"
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Invalid bbox: {e}")
        # Optional filters: repeated eventCode and capCategories are supported
        results = await fetch_ipaws_openapi_alerts(sd, ed, state=state, event_codes=eventCode, cap_categories=capCategories, geo_wkt=geo_wkt)
        return _dedupe_by_text(results)
    if category:
        # Allow constraining category sampling by eventCode and/or capCategories when provided
        # If filters are present and daysBack not provided, widen window to 365 days
        effective_days_back = daysBack if daysBack is not None else (365 if (eventCode or capCategories) else 90)
        # Parse bbox to WKT if provided
        geo_wkt: Optional[str] = wkt
        if not geo_wkt and bbox:
            try:
                parts = [float(p) for p in bbox.split(',')]
                if len(parts) != 4:
                    raise ValueError("bbox must have 4 comma-separated numbers: minLon,minLat,maxLon,maxLat")
                minlon, minlat, maxlon, maxlat = parts
                geo_wkt = f"POLYGON(({minlon} {maxlat},{maxlon} {maxlat},{maxlon} {minlat},{minlon} {minlat},{minlon} {maxlat}))"
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Invalid bbox: {e}")
        fresh = await fetch_ipaws_alerts(
            category=category,
            count=count,
            state=state,
            days_back=effective_days_back,
            cap_categories_override=capCategories,
            event_codes=eventCode,
            geo_wkt=geo_wkt,
        )
        return _dedupe_by_text(fresh)

    research_file = OUTPUTS_DIR / "ca_alerts.json"
    if research_file.exists():
        with open(research_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            results = []
            amber_count = 0
            for item in data:
                src_text = item.get("source_text", "")
                if not src_text or len(src_text) < 50:
                    continue
                is_amber = "AMBER Alert" in src_text
                if is_amber:
                    if amber_count >= 3:
                        continue
                    amber_count += 1
                results.append({
                    "alert_id": item.get("id"),
                    "source_text": src_text,
                    "category": item.get("hazard_type"),
                    "event": item.get("event_type"),
                    "timestamp": item.get("date"),
                    "agency": item.get("agency")
                })
            return results[:48]
    
    # Fallback if no file exists
    return []

# --- Frontend static serving (production) ---
# Serve built web UI (Vite) when available under / (index) and /assets
FRONTEND_DIST = Path(__file__).resolve().parents[1] / "web" / "dist"
if FRONTEND_DIST.exists():
    assets_dir = FRONTEND_DIST / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/")
    async def frontend_index():
        return FileResponse(str(FRONTEND_DIST / "index.html"))

    # SPA fallback: serve index.html for unknown non-API paths
    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        # Avoid intercepting API routes
        api_prefixes = {"health", "config", "auth", "admin", "alerts", "segment", "translate", "evaluate", "templates", "pipeline"}
        if any(full_path.split("/")[0] == p for p in api_prefixes):
            raise HTTPException(status_code=404, detail="Not Found")
        return FileResponse(str(FRONTEND_DIST / "index.html"))

@app.post("/translate", response_model=TranslationResponse)
async def translate(req: TranslationRequest):
    try:
        if req.alert_id or req.corpus_id:
            corpus = _load_research_corpus()
            if corpus is None or corpus.status != "frozen":
                raise HTTPException(status_code=409, detail="Research corpus is not frozen")
            if not req.alert_id or req.corpus_id != corpus.corpus_id:
                raise HTTPException(status_code=409, detail="A valid frozen corpus ID and alert ID are required")
            source = next((item for item in corpus.sources if item.alert_id == req.alert_id), None)
            if source is None or source.source_text != req.source_text:
                raise HTTPException(status_code=409, detail="Translation source does not match the frozen corpus")
            artifact = get_frozen_translation(corpus, req.alert_id, req.system, req.target_language)
            return TranslationResponse(
                translation=artifact.translation_text,
                metadata={
                    **{key: str(value) for key, value in artifact.metadata.items()},
                    "corpus_id": corpus.corpus_id,
                    "source_hash": artifact.source_hash,
                    "translation_hash": artifact.translation_hash,
                    "frozen": "true",
                },
            )
        if req.system == "gemini":
            res = await translate_with_gemini(req.source_text, req.target_language)
        elif req.system == "gpt5.5":
            res = await translate_with_gpt4o(req.source_text, req.target_language, model="gpt5.5")
        else:
            res = await translate_with_llama3(req.source_text, req.target_language)
        return TranslationResponse(translation=res["translation"], metadata=res["metadata"])
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/segment", response_model=SegmentResponse)
async def segment(req: SegmentRequest):
    segs = segment_alert(req.text, language=req.language)
    return SegmentResponse(segments=[SegmentItem(segment_text=s, communicative_function=f) for s, f in segs])

@app.post("/evaluate", response_model=EvaluationResponse)
async def evaluate(req: EvaluationRequest):
    _require_frozen_artifact(
        req.alert_id,
        req.corpus_id,
        req.source_segment,
        req.translated_segment,
        req.system,
        req.language,
    )
    ev = await evaluate_segment_fairness(req.source_segment, req.translated_segment, req.language, context=req.context or "")
    scores = {
        "pf1_urgency_preservation": ev.pf1_urgency_preservation,
        "pf2_directive_clarity": ev.pf2_directive_clarity,
        "pf3_risk_severity": ev.pf3_risk_severity,
        "pf4_authority_attribution": ev.pf4_authority_attribution,
        "pf5_temporal_accuracy": ev.pf5_temporal_accuracy,
        "pf6_procedural_completeness": ev.pf6_procedural_completeness,
        "if1_respectful_tone": ev.if1_respectful_tone,
        "if2_inclusion": ev.if2_inclusion,
        "if3_empathy_marker": ev.if3_empathy_marker,
        "if4_linguistic_clarity": ev.if4_linguistic_clarity,
        "if5_cultural_appropriateness": ev.if5_cultural_appropriateness,
        "if6_trust_signal": ev.if6_trust_signal,
    }
    return EvaluationResponse(scores=scores, rationale=ev.rationale)

@app.post("/evaluate/human", response_model=HumanEvaluationResponse)
async def evaluate_human(req: HumanEvaluationRequest, authorization: Optional[str] = Header(default=None)):
    # Require an authenticated session; the evaluator identity is taken from the
    # signed-in user (authoritative) so submissions can be attributed reliably.
    sess = _require_session(authorization)
    evaluator_email = str(sess.get("email") or "").strip()
    evaluator_name = str(sess.get("username") or "").strip()
    evaluator_id = evaluator_email or evaluator_name or "Anonymous"
    corpus, source, artifact = _require_frozen_artifact(
        req.alert_id,
        req.corpus_id,
        req.source_segment,
        req.translated_segment,
        req.system,
        req.language,
    )
    allowed_keys = FAIRNESS_METRIC_KEYS
    # basic validation
    for k, v in req.scores.items():
        if k not in allowed_keys:
            raise HTTPException(status_code=400, detail=f"Invalid score key: {k}")
        if v not in (0, 1, 2):
            raise HTTPException(status_code=400, detail=f"Invalid score value for {k}: {v}")
    # Persist to the durable submissions store (Cloud Storage in production,
    # local CSV in development). Each submission is keyed by its timestamp.
    row = {
        "timestamp": datetime.utcnow().isoformat(),
        "evaluator_id": evaluator_id,
        "evaluator_name": evaluator_name,
        "language": req.language,
        "system": req.system,
        "alert_id": source.alert_id,
        "corpus_id": corpus.corpus_id,
        "source_hash": source.source_hash,
        "translation_hash": artifact.translation_hash,
        "source_segment": req.source_segment,
        "translated_segment": req.translated_segment,
        "rationale": json.dumps(req.rationale or {}, ensure_ascii=False),
    }
    for key in allowed_keys:
        row[key] = req.scores.get(key, "")

    _append_submission_row(row)
    storage_target = (
        f"gs://{SUBMISSIONS_GCS_BUCKET}/{SUBMISSIONS_GCS_OBJECT}"
        if SUBMISSIONS_GCS_BUCKET
        else str(_submissions_csv_path())
    )
    return HumanEvaluationResponse(saved=True, path=storage_target)

@app.get("/submissions")
async def list_submissions(authorization: Optional[str] = Header(default=None)):
    """List human-evaluation submissions. Regular users see only their own;
    admins see every submission."""
    sess = _require_session(authorization)
    is_admin = str(sess.get("role", "")).lower() == "admin"
    rows = _load_submission_rows()
    submissions: List[Dict[str, Any]] = []
    for row in rows:
        if not is_admin and not _session_owns_submission(sess, row):
            continue
        submissions.append(_submission_to_dict(row))
    submissions.sort(key=lambda item: item.get("timestamp", ""), reverse=True)
    return {"submissions": submissions, "is_admin": is_admin}

@app.put("/submissions/{submission_id}")
async def update_submission(submission_id: str, req: SubmissionUpdateRequest, authorization: Optional[str] = Header(default=None)):
    """Edit a submission's scores and notes. Users may only edit their own."""
    sess = _require_session(authorization)
    is_admin = str(sess.get("role", "")).lower() == "admin"
    for key, value in req.scores.items():
        if key not in FAIRNESS_METRIC_KEYS:
            raise HTTPException(status_code=400, detail=f"Invalid score key: {key}")
        if value not in (0, 1, 2):
            raise HTTPException(status_code=400, detail=f"Invalid score value for {key}: {value}")
    rows = _load_submission_rows()
    updated_row: Optional[Dict[str, str]] = None
    for row in rows:
        if (row.get("timestamp") or "").strip() != submission_id:
            continue
        if not is_admin and not _session_owns_submission(sess, row):
            raise HTTPException(status_code=403, detail="You can only edit your own submissions")
        for key in FAIRNESS_METRIC_KEYS:
            if key in req.scores:
                row[key] = str(req.scores[key])
        row["rationale"] = json.dumps({"notes": (req.notes or "").strip()}, ensure_ascii=False)
        updated_row = row
        break
    if updated_row is None:
        raise HTTPException(status_code=404, detail="Submission not found")
    _save_submission_rows(rows)
    return {"updated": True, "submission": _submission_to_dict(updated_row)}

@app.delete("/submissions/{submission_id}")
async def delete_submission(submission_id: str, authorization: Optional[str] = Header(default=None)):
    """Delete a submission. Users may only delete their own; admins may delete any."""
    sess = _require_session(authorization)
    is_admin = str(sess.get("role", "")).lower() == "admin"
    rows = _load_submission_rows()
    kept: List[Dict[str, str]] = []
    removed = False
    for row in rows:
        if (row.get("timestamp") or "").strip() == submission_id:
            if not is_admin and not _session_owns_submission(sess, row):
                raise HTTPException(status_code=403, detail="You can only delete your own submissions")
            removed = True
            continue
        kept.append(row)
    if not removed:
        raise HTTPException(status_code=404, detail="Submission not found")
    _save_submission_rows(kept)
    return {"deleted": True}

@app.post("/pipeline/run", response_model=PipelineResponse)
async def run_pipeline(req: PipelineRequest):
    if req.offline:
        os.environ["OFFLINE_MODE"] = "1"
    else:
        # Ensure online mode
        if os.getenv("OFFLINE_MODE"):
            os.environ.pop("OFFLINE_MODE", None)
    app_graph = create_research_workflow()
    state = {
        "sample_size": req.sample_size,
        "target_languages": req.target_languages,
        "translation_systems": req.translation_systems,
        "alerts": [],
        "translations": [],
        "segments": [],
        "scores": [],
        "composite_scores": [],
        "statistical_results": [],
        "current_step": "",
        "errors": [],
        "progress": {},
        "output_dir": str((__import__('pathlib').Path(__file__).resolve().parents[1] / 'outputs')),
    }
    result = await app_graph.ainvoke(state)
    # Save to in-memory state for subsequent GET /alerts
    CURRENT_STATE.update(result)
    return PipelineResponse(
        alerts=len(result.get("alerts", [])),
        translations=len(result.get("translations", [])),
        segments=len(result.get("segments", [])),
        scores=len(result.get("scores", [])),
        composite=len(result.get("composite_scores", [])),
        stats=len(result.get("statistical_results", [])),
        output_dir=result.get("output_dir", "outputs"),
    )

@app.post("/templates/build", response_model=TemplatesBuildResponse)
async def templates_build(req: TemplatesBuildRequest):
    try:
        sd = datetime.fromisoformat(req.startDate)
        ed = datetime.fromisoformat(req.endDate)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid startDate/endDate format; use ISO date e.g., 2024-01-01")
    templates = await extract_templates_from_api(sd, ed, per_category=req.perCategory)
    save_templates(templates)
    counts = {k: len(v) for k, v in templates.items()}
    return TemplatesBuildResponse(counts=counts, saved=True)
