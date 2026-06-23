import json, pathlib

path = pathlib.Path(__file__).parent.parent / "ipaws_research/resources/templates.json"
data = json.loads(path.read_text(encoding="utf-8"))

# AMBER alerts to KEEP (exactly 3)
KEEP_AMBER = [
    "ON AUGUST 21 2025 AT 0130 AM JADEN HERNANDEZ",
    "ON AUGUST 5, 2025, AT 1:00 PM, TYSHAWN TUCKER",
    "ON JANUARY 28, 2026, AT 1:30 PM SOFIA AND ROMEO ORDONEZ",
]

amber_used = set()  # deduplicate same incident across categories

def is_amber(s):
    return "AMBER Alert" in (s or "")

def keep_amber(s):
    for k in KEEP_AMBER:
        if k in s:
            if k in amber_used:
                return False  # already kept this incident in another category
            amber_used.add(k)
            return True
    return False

# ── evacuation: remove 3 too-short entries ───────────────────────────────────
SHORT_EVAC = {
    "Evacuation Immediate",
    "Yolo OES GO NOW - Evacuate immediately!",
    "SMAlert | New Santa Monica Evacuation Order",
}
data["evacuation"] = [s for s in data["evacuation"] if s.strip() not in SHORT_EVAC]

# ── public_safety: remove bare stub + excess AMBER ───────────────────────────
def keep_ps(s):
    if s.strip() == "Civil Emergency Message":
        return False
    if is_amber(s) and not keep_amber(s):
        return False
    return True

data["public_safety"] = [s for s in data["public_safety"] if keep_ps(s)]

# ── health: remove short/garbage/duplicates/excess AMBER ─────────────────────
REMOVE_HEALTH_EXACT = {
    "Ebony Alert",
    "Silver Alert",
    "Endangered Missing Advisory",
    "Emergency Alert System Test\nThis is a test of the Emergency Alert System. This is only a test",
    "Emergency Alert System Test\nbnmb n,h,vmn,nbm,bjm",
}

MO_PREFIXES = (
    "UPDATE KANSAS CITY MO",
    "KANSAS CITY, MO SILVER",
    "JEFFERSON CITY BLUE",
    "COLUMBIA I-70 WESTBOUND BLUE",
    "ROCKPORT MO-",
)

def is_mo_bulletin(s):
    return any((s or "").strip().startswith(p) for p in MO_PREFIXES)

eas_seen = False

def keep_health(s):
    global eas_seen
    stripped = s.strip()
    if stripped in REMOVE_HEALTH_EXACT:
        return False
    if is_mo_bulletin(stripped):
        return False
    if is_amber(s) and not keep_amber(s):
        return False
    # deduplicate EAS test — keep only the first full copy
    if stripped.startswith("Emergency Alert System Test\nThis is a required monthly test"):
        if eas_seen:
            return False
        eas_seen = True
    return True

data["health"] = [s for s in data["health"] if keep_health(s)]

# ── report ────────────────────────────────────────────────────────────────────
total = sum(len(v) for v in data.values())
for k, v in data.items():
    amber_count = sum(1 for s in v if is_amber(s))
    print(f"  {k:15s}: {len(v):2d} entries  ({amber_count} AMBER)")
print(f"  {'TOTAL':15s}: {total}")

# ── write back ────────────────────────────────────────────────────────────────
path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
print("templates.json updated.")
