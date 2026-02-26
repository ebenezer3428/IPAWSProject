import random
from typing import List, Optional
from datetime import datetime, timedelta
from pathlib import Path
import json
import aiohttp

from ipaws_research.models import EmergencyAlert
from ipaws_research.utils import logger


FEMA_OPEN_API_URL = "https://www.fema.gov/api/open/v1/IpawsArchivedAlerts"

RESOURCES_DIR = Path(__file__).resolve().parents[0] / "resources"
TEMPLATES_PATH = RESOURCES_DIR / "templates.json"

TEMPLATES = {
    "weather": [
        "Evacuate immediately due to wildfire approaching the area. Life-threatening conditions expected.",
        "Extreme heat alert: Stay hydrated and seek cooling centers now. Risk of heatstroke is severe.",
        "Flood warning: Move to higher ground now. Do not attempt to drive through flood waters."
    ],
    "evacuation": [
        "Mandatory evacuation for Zone A effective immediately. Follow instructions from local authorities.",
        "Shelter-in-place order for affected neighborhoods until 6pm due to hazardous materials incident.",
        "Voluntary evacuation advised for coastal areas before tonight due to incoming storm surge."
    ],
    "public_safety": [
        "Law enforcement advisory: Avoid downtown area due to ongoing operations. Follow official guidance.",
        "Civil emergency message: Hazardous materials spill near River Road. Stay indoors and close windows.",
        "Curfew in effect from 9pm to 6am for public safety."
    ],
    "health": [
        "Public health alert: Air quality is dangerous due to smoke. Limit outdoor activity.",
        "Environmental hazard: Chemical odor reported. Authorities investigating. Avoid the area.",
        "Boil water notice until further notice. Use bottled water if available."
    ]
}


def load_templates() -> dict:
    try:
        if TEMPLATES_PATH.exists():
            with open(TEMPLATES_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                for k in ["weather", "evacuation", "public_safety", "health"]:
                    data.setdefault(k, [])
                return data
    except Exception as e:
        logger.warning(f"Failed to load templates.json: {e}")
    return TEMPLATES


def save_templates(templates: dict) -> None:
    try:
        RESOURCES_DIR.mkdir(parents=True, exist_ok=True)
        with open(TEMPLATES_PATH, "w", encoding="utf-8") as f:
            json.dump(templates, f, ensure_ascii=False, indent=2)
        logger.info(f"Saved templates to {TEMPLATES_PATH}")
    except Exception as e:
        logger.warning(f"Failed to save templates: {e}")


def _map_cap_category(cat: str) -> str:
    c = cat.lower()
    if c == "met":
        return "weather"
    if c in {"Safety", "Security", "Rescue", "Fire"}:
        return "Safety"
    if c in {"Health", "Env", "CBRNE"}:
        return "health"
    return "health"


def _categorize_text(text: str) -> str:
    t = (text or "").lower()
    if any(w in t for w in ["heat", "storm", "flood", "wildfire", "hurricane", "tornado", "winter"]):
        return "weather"
    if any(w in t for w in ["evacuat", "shelter-in-place", "shelter in place", "shelter", "curfew"]):
        return "evacuation"
    if any(w in t for w in ["law enforcement", "civil emergency", "hazardous materials", "hazmat", "police"]):
        return "public_safety"
    return "health"


def _cap_categories_for(category: str) -> Optional[List[str]]:
    if category == "weather":
        return ["Met"]
    if category == "public_safety":
        return ["Safety", "Security", "Rescue", "Fire"]
    if category == "health":
        return ["Health", "Env", "CBRNE"]
    return None


def _dedupe_alerts(alerts: List[EmergencyAlert]) -> List[EmergencyAlert]:
    seen: set[str] = set()
    out: List[EmergencyAlert] = []
    for a in alerts:
        key = (a.source_text or "").strip().lower() or a.alert_id
        if key in seen:
            continue
        seen.add(key)
        out.append(a)
    return out


def _build_filter_string(
    start_date: datetime,
    end_date: datetime,
    cap_categories: Optional[List[str]] = None,
    event_codes: Optional[List[str]] = None,
    geo_wkt: Optional[str] = None,
    state: Optional[str] = "CA",
) -> str:
    start_str = start_date.strftime('%Y-%m-%dT00:00:00Z')
    end_str = end_date.strftime('%Y-%m-%dT23:59:59Z')
    parts: List[str] = [f"sent ge '{start_str}' and sent le '{end_str}'"]

    # Area Desc: California-only (correct OData path: info/area/areaDesc)
    if state and state.upper() == "CA":
        parts.append("contains(info/area/areaDesc, 'CA')")

    # Optional geospatial intersects
    if geo_wkt:
        wkt = geo_wkt if geo_wkt.startswith("SRID=4326;") else f"SRID=4326;{geo_wkt}"
        parts.append(f"geo.intersects(searchGeometry, geography'{wkt}')")

    return " and ".join(parts)

def _to_emergency_alert(item: dict, state: Optional[str]) -> EmergencyAlert:
    info = (item.get("info") or [])
    headline = ""
    description = ""
    urgency = ""
    certainty = ""
    severity = ""
    category = ""
    area_desc = ""
    if info:
        first = info[0]
        headline = first.get("headline") or ""
        description = first.get("description") or ""
        urgency = first.get("urgency") or ""
        certainty = first.get("certainty") or ""
        severity = first.get("severity") or ""
        areas = first.get("area") or []
        if isinstance(areas, list) and areas:
            try:
                descs = [str(a.get("areaDesc") or "") for a in areas if isinstance(a, dict)]
                area_desc = ", ".join([d for d in descs if d])
            except Exception:
                area_desc = ""
        cats = first.get("category") or []
        if isinstance(cats, list) and cats:
            category = _map_cap_category(str(cats[0]))
        else:
            event = first.get("event") or ""
            category = _categorize_text(event or (headline + " " + description))

    source_text = (headline + "\n" + description).strip() or (item.get("originalMessage") or "")
    sent = item.get("sent") or datetime.utcnow().isoformat() + "Z"
    try:
        ts = datetime.fromisoformat(sent.replace('Z', '+00:00')) if isinstance(sent, str) else datetime.utcnow()
    except Exception:
        ts = datetime.utcnow()
    return EmergencyAlert(
        alert_id=str(item.get("id", "")),
        source_text=source_text,
        category=category,
        urgency_level=(urgency or "").lower() or "moderate",
        certainty_level=(certainty or "").lower() or "unknown",
        severity_level=(severity or "").lower() or "unknown",
        timestamp=ts,
        state=(state or "CA"),
        area=area_desc or (state or ""),
    )


async def fetch_ipaws_openapi_alerts(
    start_date: datetime,
    end_date: datetime,
    top: int = 1000,
    state: Optional[str] = "CA",
    use_allrecords: bool = True,
    shuffle: bool = True,
    limit: Optional[int] = None,
    seed: Optional[int] = None,
    cap_categories: Optional[List[str]] = None,
    event_codes: Optional[List[str]] = None,
    geo_wkt: Optional[str] = None,
) -> List[EmergencyAlert]:
    """Fetch alerts from FEMA Open API using a simplified CA-only filter.

    Ignores event/category filters and uses a single request with `$top=1000`.
    """
    alerts: List[EmergencyAlert] = []
    try:
        async with aiohttp.ClientSession() as session:
            # Use simplified filter: CA area only
            filter_str = "contains(info/area/areaDesc, 'CA')"
            params = {
                '$filter': filter_str,
                '$orderby': 'sent desc',
                '$top': '1000',
            }
            logger.info(f"OpenFEMA filter: {filter_str}")
            async with session.get(FEMA_OPEN_API_URL, params=params, timeout=60) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    items = data.get('IpawsArchivedAlerts', [])
                    alerts = [_to_emergency_alert(it, state) for it in items]
                else:
                    logger.warning(f"OpenFEMA status {resp.status}")
    except Exception as e:
        logger.warning(f"FEMA Open API fetch failed: {e}")

    alerts = _dedupe_alerts(alerts)
    if limit:
        alerts = alerts[:limit]
    logger.info(f"Returning {len(alerts)} alerts after processing")
    return alerts


async def fetch_ipaws_alerts(
    category: str,
    count: int,
    state: str = "CA",
    days_back: int = 90,
    cap_categories_override: Optional[List[str]] = None,
    event_codes: Optional[List[str]] = None,
    geo_wkt: Optional[str] = None,
) -> List[EmergencyAlert]:
    """Fetch alerts and sample by simplified category using OData filters."""
    end = datetime.utcnow()
    start = end - timedelta(days=days_back)
    cap_filter = cap_categories_override if cap_categories_override else _cap_categories_for(category)
    candidates = await fetch_ipaws_openapi_alerts(
        start,
        end,
        top=1000,
        state=state,
        use_allrecords=True,
        shuffle=True,
        cap_categories=cap_filter,
        event_codes=event_codes,
        geo_wkt=geo_wkt,
    )
    pool = [a for a in candidates if a.category == category]
    pool = _dedupe_alerts(pool)
    random.shuffle(pool)
    return pool[:count]


async def extract_templates_from_api(start_date: datetime, end_date: datetime, per_category: int = 20) -> dict:
    alerts = await fetch_ipaws_openapi_alerts(start_date, end_date, top=1000, state="CA")
    buckets = {"weather": [], "evacuation": [], "public_safety": [], "health": []}
    seen = set()
    for a in alerts:
        text = (a.source_text or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        cat = _categorize_text(text)
        if len(buckets[cat]) < per_category:
            buckets[cat].append(text)
        if all(len(buckets[k]) >= per_category for k in buckets):
            break
    return buckets
