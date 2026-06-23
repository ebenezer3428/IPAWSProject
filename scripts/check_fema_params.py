import requests
url = "https://www.fema.gov/api/open/v1/IpawsArchivedAlerts"
r = requests.get(url, params={"$filter": "contains(info/category, 'Met')", "$top": 1})
print(f"info/category contains 'Met': {r.status_code} {len(r.json().get('IpawsArchivedAlerts', []))}")
