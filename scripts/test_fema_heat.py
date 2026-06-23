import requests

def test_heat():
    url = "https://www.fema.gov/api/open/v1/IpawsArchivedAlerts"
    # List distinct events in CA since 2024 (recent only for speed)
    params = {
        "$filter": "contains(info/area/areaDesc, 'CA') and sent ge '2024-01-01T00:00:00.000Z'",
        "$top": 100,
        "$select": "info"
    }
    
    try:
        print("Querying FEMA...")
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        data = r.json().get("IpawsArchivedAlerts", [])
        events = set()
        for i in data:
            if i.get("info"):
                events.add(i["info"][0].get("event"))
        print(f"Discovered events: {sorted(list(events))}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_heat()
