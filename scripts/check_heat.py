import requests
url = "https://www.fema.gov/api/open/v1/IpawsArchivedAlerts"
flt = "sent ge '2024-08-01T00:00:00Z' and sent le '2024-08-07T23:59:59Z' and contains(info/event, 'Heat')"
try:
    r = requests.get(url, params={"$filter": flt, "$top": 5}, timeout=60)
    for item in r.json().get('IpawsArchivedAlerts', []):
        info = item.get('info', [{}])[0]
        area = info.get('area', [{}])[0] if info.get('area') else {}
        print(f"Event: {info.get('event')}, Area: {area.get('areaDesc')}")
except Exception as e:
    print(f"Error: {e}")
