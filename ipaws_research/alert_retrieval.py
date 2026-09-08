import asyncio
import random
import hashlib
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import aiohttp

from ipaws_research.models import EmergencyAlert
from ipaws_research.utils import logger


FEMA_OPEN_API_URL = "https://www.fema.gov/api/open/v1/IpawsArchivedAlerts"
CALIFORNIA_SEARCH_WKT = "POLYGON((-124.48 32.53,-114.13 32.53,-114.13 42.01,-124.48 42.01,-124.48 32.53))"

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
    if c in {"safety", "security"}:
        return "public_safety"
    if c in {"health", "env", "cbrne"}:
        return "health"
    return ""


def _categorize_text(text: str) -> str:
    t = (text or "").lower()
    if any(w in t for w in ["heat", "storm", "flood", "wildfire", "hurricane", "tornado", "winter"]):
        return "weather"
    if any(w in t for w in ["evacuat", "shelter-in-place", "shelter in place", "curfew"]):
        return "evacuation"
    if any(w in t for w in ["law enforcement", "civil emergency", "hazardous materials", "hazmat", "police"]):
        return "public_safety"
    return "unknown"


def _cap_categories_for(category: str) -> Optional[List[str]]:
    if category == "weather":
        return ["Met"]
    if category == "public_safety":
        return ["Safety", "Security"]
    if category == "health":
        return ["Health", "Env", "CBRNE"]
    if category == "evacuation":
        return ["Geo", "Rescue", "Fire"]
    return None


def classify_study_category(
    cap_categories: List[str],
    response_types: List[str],
    source_text: str,
    event: str = "",
) -> str:
    category = next((_map_cap_category(value) for value in cap_categories if _map_cap_category(value)), "")
    if category:
        return category
    if any(value.casefold() in {"evacuate", "shelter"} for value in response_types) or any(
        value in source_text.lower() for value in ("evacuat", "shelter-in-place", "shelter in place")
    ):
        return "evacuation"
    return _categorize_text(event or source_text)


def _dedupe_alerts(alerts: List[EmergencyAlert]) -> List[EmergencyAlert]:
    seen: set[str] = set()
    out: List[EmergencyAlert] = []
    for a in alerts:
        key = a.research_id or a.alert_id
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

    if geo_wkt:
        wkt = geo_wkt.removeprefix("SRID=4326;")
        parts.append(f"geo.intersects(searchGeometry, geography'{wkt}')")

    return " and ".join(parts)


def _quarterly_windows(start_date: datetime, end_date: datetime) -> List[tuple[datetime, datetime]]:
    windows: List[tuple[datetime, datetime]] = []
    quarter_month = ((start_date.month - 1) // 3) * 3 + 1
    cursor = datetime(start_date.year, quarter_month, 1, tzinfo=start_date.tzinfo)
    while cursor <= end_date:
        if cursor.month == 10:
            next_quarter = datetime(cursor.year + 1, 1, 1, tzinfo=cursor.tzinfo)
        else:
            next_quarter = datetime(cursor.year, cursor.month + 3, 1, tzinfo=cursor.tzinfo)
        windows.append((max(start_date, cursor), min(end_date, next_quarter - timedelta(seconds=1))))
        cursor = next_quarter
    return list(reversed(windows))


def _monthly_windows(start_date: datetime, end_date: datetime) -> List[tuple[datetime, datetime]]:
    windows: List[tuple[datetime, datetime]] = []
    cursor = datetime(start_date.year, start_date.month, 1, tzinfo=start_date.tzinfo)
    while cursor <= end_date:
        if cursor.month == 12:
            next_month = datetime(cursor.year + 1, 1, 1, tzinfo=cursor.tzinfo)
        else:
            next_month = datetime(cursor.year, cursor.month + 1, 1, tzinfo=cursor.tzinfo)
        windows.append((max(start_date, cursor), min(end_date, next_month - timedelta(seconds=1))))
        cursor = next_month
    return list(reversed(windows))

def _parse_datetime(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def _english_info(item: Dict[str, Any]) -> Dict[str, Any]:
    info_blocks = [block for block in (item.get("info") or []) if isinstance(block, dict)]
    for block in info_blocks:
        language = str(block.get("language") or "").lower()
        if language == "en" or language.startswith("en-"):
            return block
    return info_blocks[0] if info_blocks else {}


def _named_values(values: Any) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for entry in values or []:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or entry.get("valueName") or "").strip()
        value = str(entry.get("value") or "").strip()
        if name and value:
            result[name] = value
    return result


def _areas(info: Dict[str, Any]) -> List[Dict[str, Any]]:
    values = info.get("areas") or info.get("area") or []
    return [area for area in values if isinstance(area, dict)]


def _is_california_item(item: Dict[str, Any]) -> bool:
    for block in (item.get("info") or []):
        if not isinstance(block, dict):
            continue
        for area in _areas(block):
            description = str(area.get("areaDesc") or "").lower()
            if "california" in description or description.startswith("ca-"):
                return True
            for geocode in area.get("geocode") or []:
                if not isinstance(geocode, dict):
                    continue
                name = str(geocode.get("name") or geocode.get("valueName") or "").upper()
                value = str(geocode.get("value") or "").upper()
                if (name == "SAME" and value.startswith("006")) or (name == "UGC" and value.startswith("CA")):
                    return True
    return False


def _source_text(info: Dict[str, Any]) -> str:
    parts: List[str] = []
    for key in ("event", "headline", "description", "instruction"):
        value = str(info.get(key) or "").strip()
        if value and value.casefold() not in {part.casefold() for part in parts}:
            parts.append(value)
    if not parts:
        parameters = _named_values(info.get("parameters") or info.get("parameter"))
        for key in ("CMAMlongtext", "CMAMtext"):
            if parameters.get(key):
                parts.append(parameters[key])
                break
    return "\n\n".join(parts)


def _research_id(item: Dict[str, Any]) -> str:
    identity = "\x1f".join(str(item.get(key) or "").strip() for key in ("sender", "identifier", "sent"))
    if not identity.replace("\x1f", ""):
        identity = str(item.get("id") or "")
    return f"IPAWS-{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:20].upper()}"


def _to_emergency_alert(item: Dict[str, Any], state: Optional[str]) -> EmergencyAlert:
    info = _english_info(item)
    cap_categories = [str(value) for value in (info.get("category") or [])]
    response_types = [str(value) for value in (info.get("responseType") or [])]
    event = str(info.get("event") or "")
    source_text = _source_text(info)
    category = classify_study_category(cap_categories, response_types, source_text, event)
    area_desc = ", ".join(dict.fromkeys(
        str(area.get("areaDesc") or "").strip() for area in _areas(info) if str(area.get("areaDesc") or "").strip()
    ))
    sent = _parse_datetime(item.get("sent"))
    research_id = _research_id(item)
    return EmergencyAlert(
        alert_id=research_id,
        source_text=source_text,
        category=category,
        urgency_level=str(info.get("urgency") or "").lower() or "unknown",
        certainty_level=str(info.get("certainty") or "").lower() or "unknown",
        severity_level=str(info.get("severity") or "").lower() or "unknown",
        timestamp=sent or datetime.now(timezone.utc),
        state=(state or "CA"),
        area=area_desc or (state or ""),
        research_id=research_id,
        openfema_id=str(item.get("id") or ""),
        identifier=str(item.get("identifier") or ""),
        sender=str(item.get("sender") or ""),
        language=str(info.get("language") or ""),
        sent=sent,
        effective=_parse_datetime(info.get("effective")) or sent,
        expires=_parse_datetime(info.get("expires")),
        status=str(item.get("status") or ""),
        message_type=str(item.get("msgType") or ""),
        scope=str(item.get("scope") or ""),
        event=event,
        cap_categories=cap_categories,
        response_types=response_types,
        event_codes=_named_values(info.get("eventCode")),
        raw_source_text=source_text,
        cleaned_source_text=source_text,
        original_message=str(item.get("originalMessage") or ""),
        raw_record=item,
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
    """Fetch and normalize paged records from FEMA's official OpenFEMA API."""
    alerts: List[EmergencyAlert] = []
    page_size = max(1, min(int(top), 1000))
    wanted_categories = {value.casefold() for value in (cap_categories or [])}
    wanted_event_codes = {value.casefold() for value in (event_codes or [])}
    effective_geo_wkt = geo_wkt or (CALIFORNIA_SEARCH_WKT if state and state.upper() == "CA" else None)
    max_pages = 2 if use_allrecords and effective_geo_wkt and (wanted_categories or wanted_event_codes) else (25 if use_allrecords else 1)
    windows = [(start_date, end_date)]
    if (start_date.year, start_date.month) != (end_date.year, end_date.month) and (wanted_categories or wanted_event_codes):
        windows = _monthly_windows(start_date, end_date)

    async with aiohttp.ClientSession() as session:
        semaphore = asyncio.Semaphore(12)

        async def fetch_window(window_start: datetime, window_end: datetime) -> List[EmergencyAlert]:
            window_alerts: List[EmergencyAlert] = []
            filter_str = _build_filter_string(window_start, window_end, geo_wkt=effective_geo_wkt, state=state)
            logger.info(f"OpenFEMA filter: {filter_str}")
            skip = 0
            for _ in range(max_pages):
                params = {
                    "$filter": filter_str,
                    "$orderby": "sent desc",
                    "$top": str(page_size),
                    "$skip": str(skip),
                }
                data = None
                for attempt in range(1, 3):
                    try:
                        async with semaphore:
                            async with session.get(FEMA_OPEN_API_URL, params=params, timeout=12) as resp:
                                if resp.status != 200:
                                    body = await resp.text()
                                    raise RuntimeError(f"OpenFEMA request failed ({resp.status}): {body[:300]}")
                                data = await resp.json()
                        break
                    except (asyncio.TimeoutError, aiohttp.ClientError, RuntimeError) as exc:
                        if attempt == 2:
                            logger.warning(
                                "Skipping unavailable OpenFEMA window %s through %s at offset %s: %s",
                                window_start.date(),
                                window_end.date(),
                                skip,
                                str(exc).strip() or type(exc).__name__,
                            )
                            return window_alerts
                        await asyncio.sleep(0.5 * attempt)
                if data is None:
                    return window_alerts
                items = [item for item in data.get("IpawsArchivedAlerts", []) if isinstance(item, dict)]
                for item in items:
                    if state and state.upper() == "CA" and not _is_california_item(item):
                        continue
                    info = _english_info(item)
                    item_categories = {str(value).casefold() for value in (info.get("category") or [])}
                    item_codes = {value.casefold() for value in _named_values(info.get("eventCode")).values()}
                    if wanted_categories and not wanted_categories.intersection(item_categories):
                        continue
                    if wanted_event_codes and not wanted_event_codes.intersection(item_codes):
                        continue
                    window_alerts.append(_to_emergency_alert(item, state))
                if len(items) < page_size or not use_allrecords:
                    break
                if limit and len(window_alerts) >= limit:
                    break
                skip += page_size
            return window_alerts

        if len(windows) > 2:
            window_results = await asyncio.gather(*(
                fetch_window(window_start, window_end)
                for window_start, window_end in windows
            ))
            alerts = [alert for result in window_results for alert in result]
        else:
            for window_start, window_end in windows:
                alerts.extend(await fetch_window(window_start, window_end))

    alerts = _dedupe_alerts(alerts)
    if shuffle:
        random.Random(seed).shuffle(alerts)
    if limit is not None:
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
