import os
import pandas as pd
from datetime import datetime
from ipaws_research.models import EmergencyAlert, TranslatedAlert, AlertSegment, FairnessScore, CompositeScores, StatisticalResults


def export_results_to_csv(state: dict, output_dir: str):
    os.makedirs(output_dir, exist_ok=True)
    ts = datetime.utcnow().isoformat()

    def _df_alerts(alerts):
        return pd.DataFrame([a.dict() for a in alerts])
    def _df_translations(trans):
        rows = []
        for t in trans:
            d = t.dict()
            md = d.pop('metadata', {})
            d.update({f"meta_{k}": v for k,v in md.items()})
            rows.append(d)
        return pd.DataFrame(rows)
    def _df_segments(segs):
        return pd.DataFrame([s.dict() for s in segs])
    def _df_scores(scores):
        return pd.DataFrame([s.dict() for s in scores])
    def _df_composite(comp):
        return pd.DataFrame([c.dict() for c in comp])
    def _df_stats(stats):
        rows = []
        for s in stats:
            d = s.dict()
            det = d.pop('details', {})
            d.update({f"detail_{k}": v for k,v in det.items()})
            rows.append(d)
        return pd.DataFrame(rows)

    exports = [
        ("alerts.csv", _df_alerts(state.get("alerts", []))),
        ("translations.csv", _df_translations(state.get("translations", []))),
        ("segments.csv", _df_segments(state.get("segments", []))),
        ("fairness_scores.csv", _df_scores(state.get("scores", []))),
        ("composite_scores.csv", _df_composite(state.get("composite_scores", []))),
        ("statistical_results.csv", _df_stats(state.get("statistical_results", []))),
    ]

    for name, df in exports:
        if df is None or df.empty:
            continue
        df["export_timestamp"] = ts
        df.to_csv(os.path.join(output_dir, name), index=False, encoding="utf-8")
