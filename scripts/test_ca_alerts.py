import asyncio
import datetime as dt
from typing import List, Dict, Any
import sys
from pathlib import Path

# Ensure workspace root is on sys.path for imports
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ipaws_research.alert_retrieval import fetch_ipaws_openapi_alerts, _build_filter_string, FEMA_OPEN_API_URL
from ipaws_research.models import EmergencyAlert


async def main():
    end = dt.datetime.utcnow()
    start = end - dt.timedelta(days=7)

    print("=== Mapped EmergencyAlert results (CA, last 7 days) ===")
    mapped: List[EmergencyAlert] = await fetch_ipaws_openapi_alerts(
        start_date=start,
        end_date=end,
        state="CA",
    )
    print(f"Count: {len(mapped)}")
    for a in mapped[:3]:
        print(a.model_dump())

    print("\n=== Raw CA IpawsArchivedAlerts (last 7 days) ===")
    import requests
    flt = _build_filter_string(start_date=start, end_date=end, cap_categories=None, event_codes=None, geo_wkt=None, state="CA")
    params = {"$filter": flt, "$orderby": "sent desc", "$allrecords": "true"}
    r = requests.get(FEMA_OPEN_API_URL, params=params, timeout=60)
    r.raise_for_status()
    data = r.json()
    raw: List[Dict[str, Any]] = data.get("IpawsArchivedAlerts", [])
    print(f"Count: {len(raw)}")
    for item in raw[:3]:
        info = (item.get("info") or [])
        primary = info[0] if info else {}
        areas = primary.get("areas") or []
        descs = []
        for ar in areas:
            if isinstance(ar, dict) and ar.get("areaDesc"):
                descs.append(ar["areaDesc"])
        print({
            "id": item.get("id"),
            "sent": item.get("sent"),
            "areaDesc": descs[:2],
        })


if __name__ == "__main__":
    asyncio.run(main())
