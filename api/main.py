from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional, Dict
from datetime import datetime
import os
from pathlib import Path
from dotenv import load_dotenv

# Ensure .env variables (e.g., OPENAI_API_KEY) are loaded on startup
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from ipaws_research.translations import translate_with_gpt4o, translate_with_google_nmt, translate_with_nllb200
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

class TranslationRequest(BaseModel):
    source_text: str
    target_language: str = Field(pattern="^(es|hi)$")
    system: str = Field(default="gpt4o", pattern="^(gpt4o|google_nmt|nllb200)$")

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

@app.get("/health")
async def health():
    return {"status": "ok", "time": datetime.utcnow().isoformat()}

@app.get("/config")
async def config():
    return {
        "OFFLINE_MODE": os.getenv("OFFLINE_MODE", ""),
        "OPENAI_MODEL": os.getenv("OPENAI_MODEL", ""),
    }

@app.get("/alerts", response_model=List[EmergencyAlert])
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
    """Return alerts. If source is 'latest' and available, returns alerts from the latest pipeline run; otherwise fetch fresh.
    If category is None, returns stratified sample per dissertation plan.
    """
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
    # Stratified sampling
    category_counts = {
        'weather': 15,
        'evacuation': 12,
        'public_safety': 10,
        'health': 8
    }
    out: List[EmergencyAlert] = []
    for cat, c in category_counts.items():
        out.extend(await fetch_ipaws_alerts(cat, c, state=state))
    return _dedupe_by_text(out)

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
        api_prefixes = {"health", "config", "alerts", "segment", "translate", "evaluate", "templates", "pipeline"}
        if any(full_path.split("/")[0] == p for p in api_prefixes):
            raise HTTPException(status_code=404, detail="Not Found")
        return FileResponse(str(FRONTEND_DIST / "index.html"))

@app.post("/translate", response_model=TranslationResponse)
async def translate(req: TranslationRequest):
    try:
        if req.system == "gpt4o":
            res = await translate_with_gpt4o(req.source_text, req.target_language)
        elif req.system == "google_nmt":
            res = await translate_with_google_nmt(req.source_text, req.target_language)
        else:
            res = await translate_with_nllb200(req.source_text, req.target_language)
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
    allowed_keys = [
        "pf1_urgency_preservation",
        "pf2_directive_clarity",
        "pf3_risk_severity",
        "pf4_authority_attribution",
        "pf5_temporal_accuracy",
        "pf6_procedural_completeness",
        "if1_respectful_tone",
        "if2_inclusion",
        "if3_empathy_marker",
        "if4_linguistic_clarity",
        "if5_cultural_appropriateness",
        "if6_trust_signal",
    ]
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
    out_dir = Path(__file__).resolve().parents[1] / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "human_fairness_scores.csv"
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
