"""
Fetch REAL alerts from the FEMA IPAWS Open API (2020-2026, California only).
No hardcoded templates - every alert comes from the live API.
Adds unique, substantive alerts to templates.json up to TARGET_TOTAL.
"""
import json
import pathlib
import hashlib
import re
import requests
from datetime import datetime

FEMA_URL = "https://www.fema.gov/api/open/v1/IpawsArchivedAlerts"
TEMPLATES_PATH = pathlib.Path(__file__).parent.parent / "ipaws_research/resources/templates.json"
TARGET_TOTAL = 70
MIN_LENGTH = 150


def _categorize(text: str) -> str:
    low = (text or "").lower()
    if any(w in low for w in ["heat warning", "heat advisory", "flood warning", "flood advisory",
                               "tornado warning", "winter storm", "freeze warning", "frost advisory",
                               "high wind", "severe thunderstorm", "dense fog", "hurricane",
                               "dust storm", "rip current", "coastal flood", "ice storm",
                               "fire weather", "red flag warning", "blizzard"]):
        return "weather"
    if any(w in low for w in ["evacuat", "shelter-in-place", "shelter in place",
                               "leave now", "leave immediately", "mandatory evacuation",
                               "evacuation order", "evacuation warning"]):
        return "evacuation"
    if any(w in low for w in ["amber alert", "law enforcement", "civil emergency",
                               "hazardous material", "hazmat", "boil water",
                               "power outage", "road closure", "seismic", "missing person"]):
        return "public_safety"
    return "health"


def _extract_text(item: dict) -> str:
    """Pull the most useful English text from an IPAWS item."""
    info_list = item.get("info") or []
    for info in info_list:
        lang = (info.get("language") or "").lower()
        if lang and not lang.startswith("en"):
            continue
        parts = []
        event = (info.get("event") or "").strip()
        headline = (info.get("headline") or "").strip()
        description = (info.get("description") or "").strip()
        instruction = (info.get("instruction") or "").strip()
        # Build readable text
        if event and headline and headline.lower() != event.lower():
            parts.append(event)
        if headline:
            parts.append(headline)
        if description:
            parts.append(description)
        if instruction:
            parts.append(instruction)
        text = "\n\n".join(p for p in parts if p)
        if text:
            return text.strip()
        # Fallback: CMAMlongtext
        for param in (info.get("parameter") or []):
            if param.get("valueName") == "CMAMlongtext":
                val = (param.get("value") or "").strip()
                if val:
                    return (event + "\n" + val).strip() if event else val
    # Last resort: originalMessage
    orig = (item.get("originalMessage") or "").strip()
    if orig:
        # Lightweight CAP XML parsing fallback.
        event_match = re.search(r"<event>(.*?)</event>", orig, flags=re.IGNORECASE | re.DOTALL)
        headline_match = re.search(r"<headline>(.*?)</headline>", orig, flags=re.IGNORECASE | re.DOTALL)
        description_match = re.search(r"<description>(.*?)</description>", orig, flags=re.IGNORECASE | re.DOTALL)
        instruction_match = re.search(r"<instruction>(.*?)</instruction>", orig, flags=re.IGNORECASE | re.DOTALL)
        cmam_match = re.search(
            r"<valueName>CMAMlongtext</valueName>\s*<value>(.*?)</value>",
            orig,
            flags=re.IGNORECASE | re.DOTALL,
        )
        pieces = []
        for m in [event_match, headline_match, description_match, instruction_match, cmam_match]:
            if m:
                cleaned = re.sub(r"<[^>]+>", " ", m.group(1))
                cleaned = re.sub(r"\s+", " ", cleaned).strip()
                if cleaned:
                    pieces.append(cleaned)
        if pieces:
            return "\n\n".join(dict.fromkeys(pieces))
    return orig


def _is_useful(text: str) -> bool:
    if len(text) < MIN_LENGTH:
        return False
    t = text.strip()
    if t.startswith("<alert") or t.startswith("<?xml"):
        return False
    low = t.lower()
    skip_phrases = [
        "this is only a test", "this is a test of the", "no action is required",
        "there is no emergency", "bnmb", "this concludes this test",
    ]
    if any(p in low for p in skip_phrases):
        return False
    # Skip one-liner vehicle bulletins (Missouri-style missing person)
    if re.match(r"^[A-Z ,]+ (MO|KS|TX|IL) .{0,60}(PLATE|TAG)", t):
        return False
    return True


def _parse_year(sent_value: str) -> int:
    text = (sent_value or "").strip()
    if not text:
        return 0
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).year
    except Exception:
        m = re.match(r"^(\d{4})-", text)
        return int(m.group(1)) if m else 0


def _is_california_item(item: dict) -> bool:
    info_list = item.get("info") or []
    for info in info_list:
        for area in (info.get("area") or []):
            desc = str(area.get("areaDesc") or "").lower()
            if "california" in desc or re.search(r"\bca\b", desc):
                return True

    # Fallback for records where only originalMessage XML is present.
    orig = str(item.get("originalMessage") or "").lower()
    if "california" in orig:
        return True
    if re.search(r"\bca[-,\s]\w+", orig):
        return True
    # SAME code for California starts with 006.
    if re.search(r"<valuename>same</valuename>\s*<value>006\d+", orig):
        return True

    return False


def fetch_all_years(need: int) -> list:
    """OpenFEMA-friendly fetch: small pages, order by sent desc, filter locally."""
    import time

    results = []
    useful_count = 0
    page_size = 10
    skip = 0
    max_pages = 220

    for page in range(max_pages):
        params = {
            "$orderby": "sent desc",
            "$top": str(page_size),
            "$skip": str(skip),
        }
        try:
            resp = requests.get(FEMA_URL, params=params, timeout=15)
            resp.raise_for_status()
            items = resp.json().get("IpawsArchivedAlerts", [])
        except Exception as e:
            print(f"  Page {page + 1}: request failed at skip={skip} - {e}")
            break

        if not items:
            print(f"  Page {page + 1}: no items at skip={skip}, stopping.")
            break

        page_added = 0
        oldest_year_in_page = 9999
        for item in items:
            year = _parse_year(str(item.get("sent") or ""))
            if year and year < oldest_year_in_page:
                oldest_year_in_page = year
            if year < 2020 or year > 2026:
                continue
            if not _is_california_item(item):
                continue
            results.append(item)
            page_added += 1
            text = _extract_text(item)
            if _is_useful(text):
                useful_count += 1

        print(
            f"  Page {page + 1:03d} (skip={skip}): got {len(items)} raw, kept {page_added} CA alerts, useful so far {useful_count}"
        )

        if useful_count >= need + 30:
            print(f"  Collected enough useful candidates ({useful_count}), stopping early.")
            break

        # Because results are sorted newest to oldest, once pages are older than 2020 we can stop.
        if oldest_year_in_page < 2020:
            print("  Reached alerts older than 2020, stopping.")
            break

        skip += page_size
        time.sleep(0.12)

    return results


def main():
    data = json.loads(TEMPLATES_PATH.read_text(encoding="utf-8"))
    seen = set()
    for cat_texts in data.values():
        for t in cat_texts:
            seen.add(hashlib.md5(t.strip().lower().encode()).hexdigest())

    current = sum(len(v) for v in data.values())
    need = max(0, TARGET_TOTAL - current)
    print(f"Current: {current} alerts. Need {need} more to reach {TARGET_TOTAL}.")
    if need == 0:
        print("Already at target."); return

    print("Fetching real FEMA/IPAWS alerts (2020-2026, CA only)...")
    raw_items = fetch_all_years(need)
    print(f"Total raw items fetched: {len(raw_items)}")

    buckets: dict = {"weather": [], "evacuation": [], "public_safety": [], "health": []}
    for item in raw_items:
        text = _extract_text(item)
        if not _is_useful(text):
            continue
        key = hashlib.md5(text.strip().lower().encode()).hexdigest()
        if key in seen:
            continue
        seen.add(key)
        buckets[_categorize(text)].append(text)

    total_new = sum(len(v) for v in buckets.values())
    print(f"Unique usable new alerts found: {total_new}")
    if not total_new:
        print("Nothing new to add."); return

    # Select proportionally, up to `need`
    import random
    per_cat = max(1, need // 4)
    selected: list = []
    for cat in ["weather", "evacuation", "public_safety", "health"]:
        random.shuffle(buckets[cat])
        selected.extend((cat, t) for t in buckets[cat][:per_cat])
    # Top up from any category if still short
    all_remaining = [(c, t) for c in buckets for t in buckets[c] if (c, t) not in selected]
    random.shuffle(all_remaining)
    selected += all_remaining[:max(0, need - len(selected))]
    selected = selected[:need]

    for cat, text in selected:
        data[cat].append(text)

    final = sum(len(v) for v in data.values())
    print()
    for k, v in data.items():
        print(f"  {k:15s}: {len(v):2d} entries")
    print(f"  {'TOTAL':15s}: {final}  (+{final - current} real alerts added)")

    TEMPLATES_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\ntemplates.json updated with real FEMA/IPAWS alerts.")


main()
