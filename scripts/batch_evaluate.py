import requests
import json

API = "http://localhost:8000"

def get_alerts(days_back=7, state="CA", limit=3):
    r = requests.get(f"{API}/alerts", params={"daysBack": days_back, "state": state}, timeout=60)
    r.raise_for_status()
    alerts = r.json()
    return alerts[:limit]

def segment(text: str, language: str = "en"):
    r = requests.post(f"{API}/segment", json={"text": text, "language": language}, timeout=60)
    r.raise_for_status()
    return r.json()["segments"]

def translate(text: str, target_language: str = "es", system: str = "gpt4o"):
    r = requests.post(f"{API}/translate", json={"source_text": text, "target_language": target_language, "system": system}, timeout=90)
    r.raise_for_status()
    return r.json()["translation"]

def evaluate(source_segment: str, translated_segment: str, language: str = "es", context: str = ""):
    r = requests.post(
        f"{API}/evaluate",
        json={
            "source_segment": source_segment,
            "translated_segment": translated_segment,
            "language": language,
            "context": context,
        },
        timeout=120,
    )
    r.raise_for_status()
    return r.json()

def main():
    alerts = get_alerts(days_back=7, state="CA", limit=3)
    total_segments = 0
    evaluations = []
    for idx, a in enumerate(alerts, 1):
        text = a.get("source_text", "")
        if not text:
            continue
        segs = segment(text, language="en")
        for s in segs[:3]:  # cap per-alert to keep runtime reasonable
            seg_text = s["segment_text"]
            try:
                tr = translate(seg_text, target_language="es", system="gpt4o")
                ev = evaluate(seg_text, tr, language="es", context="")
                evaluations.append({
                    "alert_id": a.get("alert_id"),
                    "segment": seg_text,
                    "translation": tr,
                    "scores": ev.get("scores", {}),
                })
                total_segments += 1
            except Exception as e:
                print(f"Failed on segment: {e}")
    print(json.dumps({
        "alerts": len(alerts),
        "segments_evaluated": total_segments,
        "samples": evaluations[:5],
    }, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
