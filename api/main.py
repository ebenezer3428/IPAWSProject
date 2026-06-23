from fastapi import FastAPI, HTTPException, Query, Header
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
from collections import defaultdict
import csv
import json
import math
import os
from pathlib import Path
from dotenv import load_dotenv
import secrets
import time
import hmac
import pandas as pd
from statsmodels.formula.api import ols
from statsmodels.stats.anova import anova_lm

# Ensure .env variables (e.g., OPENAI_API_KEY) are loaded on startup
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from ipaws_research.translations import translate_with_gpt4o, translate_with_google_nmt, translate_with_llama3
from ipaws_research.segmentation import segment_alert
from ipaws_research.evaluation import evaluate_segment_fairness
from ipaws_research.workflow import create_research_workflow
from ipaws_research.alert_retrieval import fetch_ipaws_alerts, fetch_ipaws_openapi_alerts, extract_templates_from_api, save_templates
from ipaws_research.models import EmergencyAlert

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
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", "28800"))  # 8 hours default
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

class TranslationRequest(BaseModel):
    source_text: str
    target_language: str = Field(pattern="^(es|hi)$")
    system: str = Field(default="gpt4o", pattern="^(gpt4o|gpt5.5|google_nmt|llama3)$")

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

class EvaluationResponse(BaseModel):
    scores: Dict[str, int]
    rationale: Dict[str, str]

class HumanEvaluationRequest(BaseModel):
    source_segment: str
    translated_segment: str
    language: str = Field(pattern="^(es|hi)$")
    evaluator_id: Optional[str] = None
    scores: Dict[str, int]
    rationale: Optional[Dict[str, str]] = Field(default_factory=dict)

class HumanEvaluationResponse(BaseModel):
    saved: bool
    path: str

class PipelineRequest(BaseModel):
    sample_size: int = 3
    target_languages: List[str] = ["es"]
    translation_systems: List[str] = ["gpt4o"]
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

class LoginRequest(BaseModel):
    username: str
    password: str
    role: str = Field(default="user", pattern="^(user|admin)$")

class LoginResponse(BaseModel):
    token: str
    role: str
    username: str
    expires_at: str

class SessionStatusResponse(BaseModel):
    valid: bool
    role: str
    username: str
    expires_at: str

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

def _password_for_role(role: str) -> str:
    if role == "admin":
        return os.getenv("APP_ADMIN_PASSWORD") or os.getenv("ADMIN_PASSWORD") or ""
    return (
        os.getenv("APP_USER_PASSWORD")
        or os.getenv("USER_PASSWORD")
        or os.getenv("APP_ADMIN_PASSWORD")
        or os.getenv("ADMIN_PASSWORD")
        or ""
    )

def _create_session(username: str, role: str) -> Dict[str, object]:
    token = secrets.token_urlsafe(32)
    exp = time.time() + SESSION_TTL_SECONDS
    SESSIONS[token] = {
        "username": username,
        "role": role,
        "exp": exp,
    }
    return {
        "token": token,
        "username": username,
        "role": role,
        "expires_at": datetime.utcfromtimestamp(exp).isoformat(),
    }

def _get_valid_session(token: str) -> Optional[Dict[str, object]]:
    sess = SESSIONS.get(token)
    if not sess:
        return None
    exp = float(sess.get("exp", 0) or 0)
    if exp <= time.time():
        SESSIONS.pop(token, None)
        return None
    return sess

def _require_session_role(authorization: Optional[str], role: str) -> Dict[str, object]:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing session token")
    sess = _get_valid_session(token)
    if not sess:
        raise HTTPException(status_code=401, detail="Session is invalid or expired")
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

    model = ols("ofs ~ C(language) + C(system) + C(language):C(system)", data=df).fit()
    anova_df = anova_lm(model, typ=2).reset_index().rename(columns={"index": "source"})
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

def _available_downloads() -> List[Dict[str, str]]:
    downloads: List[Dict[str, str]] = []
    for key, meta in DOWNLOADABLE_OUTPUTS.items():
        filename = meta["filename"]
        csv_path = OUTPUTS_DIR / filename
        if csv_path.exists():
            downloads.append({
                "key": key,
                "label": meta["label"],
                "filename": filename,
                "url": f"/admin/download/{key}",
            })
    return downloads

def _analyze_human_scores() -> Dict[str, Any]:
    csv_path = OUTPUTS_DIR / "human_fairness_scores.csv"
    rows = _read_csv_rows(csv_path)
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
            "evaluator_id": (row.get("evaluator_id") or "").strip() or "Anonymous",
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
    evaluator_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    day_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in parsed_rows:
        language_groups[row["language"]].append(row)
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

    evaluators = [
        {
            "evaluator_id": evaluator,
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
            "language": row["language"],
            "average_score_pct": row["average_score_pct"],
            "source_preview": row["source_segment"][:120],
            "notes": row["notes"][:140],
        }
        for row in sorted(parsed_rows, key=lambda item: item["timestamp"], reverse=True)[:10]
    ]

    average_scores = [float(r["average_score"]) for r in parsed_rows]
    return {
        "path": str(csv_path),
        "total_submissions": len(parsed_rows),
        "unique_messages": len({str(r["source_segment"]) for r in parsed_rows if r.get("source_segment")}),
        "named_evaluators": len({str(r["evaluator_id"]) for r in parsed_rows if r.get("evaluator_id") and r["evaluator_id"] != "Anonymous"}),
        "average_score": round(_safe_mean(average_scores), 2),
        "average_score_pct": round((_safe_mean(average_scores) / 2) * 100, 1) if average_scores else 0.0,
        "languages": languages,
        "metrics": metric_summary,
        "evaluators": evaluators,
        "submissions_by_day": submissions_by_day,
        "recent_submissions": recent_submissions,
        "normal_distribution": _build_normal_distribution([float(r["average_score_pct"]) for r in parsed_rows]),
    }

def _analyze_composite_scores() -> Dict[str, Any]:
    csv_path = OUTPUTS_DIR / "composite_scores.csv"
    rows = _read_csv_rows(csv_path)
    parsed_rows: List[Dict[str, Any]] = []

    for row in rows:
        pfi = _to_float(row.get("pfi"))
        ifi = _to_float(row.get("ifi"))
        ofs = _to_float(row.get("ofs"))
        segments = _to_float(row.get("segments_count"))
        parsed_rows.append({
            "language": (row.get("language") or "unknown").strip() or "unknown",
            "system": (row.get("system") or "unknown").strip() or "unknown",
            "pfi": pfi if pfi is not None else 0.0,
            "ifi": ifi if ifi is not None else 0.0,
            "ofs": ofs if ofs is not None else 0.0,
            "segments_count": segments if segments is not None else 0.0,
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
        "path": str(csv_path),
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

@app.post("/auth/login", response_model=LoginResponse)
async def auth_login(req: LoginRequest):
    username = (req.username or "").strip()
    if not username:
        raise HTTPException(status_code=400, detail="Username is required")
    expected_password = _password_for_role(req.role)
    if not expected_password:
        raise HTTPException(status_code=503, detail="Authentication is not configured on the server")
    if not hmac.compare_digest(req.password, expected_password):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    session = _create_session(username=username, role=req.role)
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
        expires_at=datetime.utcfromtimestamp(exp).isoformat(),
    )

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
    csv_path = OUTPUTS_DIR / meta["filename"]
    if not csv_path.exists():
        raise HTTPException(status_code=404, detail="Requested CSV file does not exist")
    return FileResponse(str(csv_path), media_type="text/csv", filename=meta["filename"])

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
    """Return alerts. Default returns the fixed 48 CA alerts across hazards."""
    
    # Check if we should return the research dataset (default)
    is_default = (not category and not startDate and not endDate and not daysBack)
    
    if is_default or source == "research":
        research_file = OUTPUTS_DIR / "ca_alerts.json"
        if research_file.exists():
            with open(research_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                # Map to frontend expected format
                results = []
                amber_count = 0
                for item in data:
                    src_text = item.get("source_text", "")
                    # Filter out short or empty alerts
                    if not src_text or len(src_text) < 50:
                        continue
                        
                    # Limit Amber alerts to at most 3
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

    if source == "latest" and CURRENT_STATE.get("alerts"):
        alerts = CURRENT_STATE["alerts"]  # type: ignore
        # Coerce to models if necessary
        out: List[EmergencyAlert] = []
        for a in alerts:  # type: ignore
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
        if req.system in ("gpt4o", "gpt5.5"):
            res = await translate_with_gpt4o(req.source_text, req.target_language, model=req.system)
        elif req.system == "google_nmt":
            res = await translate_with_google_nmt(req.source_text, req.target_language)
        else:
            res = await translate_with_llama3(req.source_text, req.target_language)
        return TranslationResponse(translation=res["translation"], metadata=res["metadata"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/segment", response_model=SegmentResponse)
async def segment(req: SegmentRequest):
    segs = segment_alert(req.text, language=req.language)
    return SegmentResponse(segments=[SegmentItem(segment_text=s, communicative_function=f) for s, f in segs])

@app.post("/evaluate", response_model=EvaluationResponse)
async def evaluate(req: EvaluationRequest):
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
async def evaluate_human(req: HumanEvaluationRequest):
    allowed_keys = FAIRNESS_METRIC_KEYS
    # basic validation
    for k, v in req.scores.items():
        if k not in allowed_keys:
            raise HTTPException(status_code=400, detail=f"Invalid score key: {k}")
        if v not in (0, 1, 2):
            raise HTTPException(status_code=400, detail=f"Invalid score value for {k}: {v}")
    # persist to outputs/human_fairness_scores.csv
    from datetime import datetime
    from pathlib import Path
    import csv, json
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = OUTPUTS_DIR / "human_fairness_scores.csv"
    fieldnames = [
        "timestamp",
        "evaluator_id",
        "language",
        "source_segment",
        "translated_segment",
        *allowed_keys,
        "rationale",
    ]
    write_header = not csv_path.exists() or csv_path.stat().st_size == 0
    with open(csv_path, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            w.writeheader()
        row = {
            "timestamp": datetime.utcnow().isoformat(),
            "evaluator_id": req.evaluator_id or "",
            "language": req.language,
            "source_segment": req.source_segment,
            "translated_segment": req.translated_segment,
            "rationale": json.dumps(req.rationale or {}, ensure_ascii=False),
        }
        for key in allowed_keys:
            row[key] = req.scores.get(key, "")
        w.writerow(row)
    return HumanEvaluationResponse(saved=True, path=str(csv_path))

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
