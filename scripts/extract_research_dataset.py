import requests
import json
import pandas as pd
from datetime import datetime
import time

URL = "https://www.fema.gov/api/open/v1/IpawsArchivedAlerts"

HAZARDS = {
    "wildfire": ["Fire", "Wildfire"],
    "flood": ["Flood"],
    "evacuation": ["Evacuation"],
    "amber": ["Child Abduction", "AMBER"],
    "emergency": ["Local Area Emergency", "Law Enforcement Warning"]
}

TARGET_COUNTS = {
    "wildfire": 12,
    "flood": 12,
    "evacuation": 12,
    "amber": 3,
    "emergency": 9
}

GLOBAL_TARGET = 48

def fetch_hazards():
    results = []
    seen_texts = set()
    
    for hazard, keywords in HAZARDS.items():
        if len(results) >= GLOBAL_TARGET:
            break
            
        found_for_this_hazard = 0
        limit_for_this_hazard = TARGET_COUNTS.get(hazard, 10)
        
        for year in range(2025, 2020, -1):
            if len(results) >= GLOBAL_TARGET or found_for_this_hazard >= limit_for_this_hazard:
                break
            
            kw_filters = " or ".join([f"contains(info/event, '{kw}')" for kw in keywords])
            flt = f"sent ge '{year}-01-01T00:00:00Z' and sent le '{year}-12-31T23:59:59Z' and contains(info/area/areaDesc, 'CA') and ({kw_filters})"
            
            print(f"Fetching {hazard} for {year}... (Total so far: {len(results)})")
            try:
                r = requests.get(URL, params={"$filter": flt, "$top": 100, "$orderby": "sent desc"}, timeout=60)
                if r.status_code != 200:
                    continue
                
                data = r.json().get("IpawsArchivedAlerts", [])
                for item in data:
                    if len(results) >= GLOBAL_TARGET or found_for_this_hazard >= limit_for_this_hazard:
                        break
                    
                    info = item.get("info", [{}])[0]
                    if "en" not in info.get("language", "en-US").lower():
                        continue
                        
                    text = (info.get("headline", "") + "\n" + info.get("description", "")).strip()
                    if not text or len(text) < 50 or text in seen_texts:
                        continue
                        
                    seen_texts.add(text)
                    results.append({
                        "id": item.get("id"),
                        "date": item.get("sent"),
                        "hazard_type": hazard,
                        "event_type": info.get("event"),
                        "agency": info.get("senderName"),
                        "source_text": text
                    })
                    found_for_this_hazard += 1
                
                time.sleep(0.5)
            except Exception as e:
                print(f"  Error: {e}")
                
    return results[:GLOBAL_TARGET]

if __name__ == "__main__":
    alerts = fetch_hazards()
    print(f"\nFinal unique count: {len(alerts)}")
    
    # Save to outputs
    with open("outputs/ca_alerts.json", "w", encoding="utf-8") as f:
        json.dump(alerts, f, indent=2)
    
    df = pd.DataFrame(alerts)
    df.to_csv("outputs/ca_alerts.csv", index=False)
    print("Saved to outputs/ca_alerts.json and outputs/ca_alerts.csv")
