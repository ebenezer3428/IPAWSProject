import asyncio
from typing import Dict, List
from ipaws_research.models import EmergencyAlert, TranslatedAlert, AlertSegment, FairnessScore, CompositeScores, StatisticalResults
from ipaws_research.alert_retrieval import fetch_ipaws_alerts
from ipaws_research.translations import translate_with_gpt4o, translate_with_google_nmt, translate_with_llama3
from ipaws_research.segmentation import segment_alert
from ipaws_research.evaluation import evaluate_segment_fairness
from ipaws_research.stats import test_hypothesis_h1, test_hypothesis_h2, test_hypothesis_h3
from ipaws_research.visualization import create_fairness_boxplots, create_fairness_heatmap, create_distribution_plots
from ipaws_research.export import export_results_to_csv
from ipaws_research.utils import logger
import pandas as pd
import numpy as np

async def retrieve_alerts_agent(state: Dict) -> Dict:
    logger.info("Retrieving alerts via stratified sampling...")
    category_counts = { 'weather': 15, 'evacuation': 12, 'public_safety': 10, 'health': 8 }
    alerts: List[EmergencyAlert] = []
    for category, count in category_counts.items():
        cat_alerts = await fetch_ipaws_alerts(category, count)
        alerts.extend(cat_alerts)
    # Shuffle for bias mitigation
    alerts = list(alerts)
    state["alerts"] = alerts
    state.setdefault("progress", {})["alerts_retrieved"] = len(alerts)
    return state

async def translation_agent(state: Dict) -> Dict:
    logger.info("Translating alerts across systems and languages...")
    alerts: List[EmergencyAlert] = state.get("alerts", [])
    systems = state.get("translation_systems", ["gpt4o","google_nmt","nllb200"])
    langs = state.get("target_languages", ["es","hi"])  
    translations: List[TranslatedAlert] = []

    async def translate_one(alert: EmergencyAlert, system: str, lang: str) -> TranslatedAlert:
        if system == "gpt4o":
            res = await translate_with_gpt4o(alert.source_text, lang)
        elif system == "google_nmt":
            res = await translate_with_google_nmt(alert.source_text, lang)
        else:
            res = await translate_with_llama3(alert.source_text, lang)
        return TranslatedAlert(
            alert_id=alert.alert_id,
            system=system,
            target_language=lang,
            translation_text=res["translation"],
            metadata=res["metadata"],
        )

    tasks = [translate_one(a, s, l) for a in alerts for s in systems for l in langs]
    results = await asyncio.gather(*tasks)
    translations.extend(results)

    state["translations"] = translations
    state.setdefault("progress", {})["translations_generated"] = len(translations)
    return state

async def segmentation_agent(state: Dict) -> Dict:
    logger.info("Segmenting source alerts and translations...")
    alerts: List[EmergencyAlert] = state.get("alerts", [])
    translations: List[TranslatedAlert] = state.get("translations", [])
    segments: List[AlertSegment] = []

    # Segment source alerts
    for alert in alerts:
        src_segments = segment_alert(alert.source_text, language="en")
        for idx, (text, func) in enumerate(src_segments):
            segments.append(AlertSegment(
                alert_id=alert.alert_id,
                segment_index=idx,
                segment_text=text,
                communicative_function=func,
                language="en"
            ))
    # Optionally also segment translations (alignment by index may be imperfect)
    # Here, we store translation segments if needed later (not required for scoring structure)

    state["segments"] = segments
    state.setdefault("progress", {})["segments_created"] = len(segments)
    return state

async def evaluation_agent(state: Dict) -> Dict:
    logger.info("Evaluating fairness per segment across translations...")
    segments: List[AlertSegment] = [s for s in state.get("segments", []) if s.language == "en"]
    translations: List[TranslatedAlert] = state.get("translations", [])

    # Group translations by (alert_id, system, language)
    trans_map = {}
    for t in translations:
        trans_map.setdefault((t.alert_id, t.system, t.target_language), t.translation_text)

    scores: List[FairnessScore] = []
    # For each alert and system/lang, evaluate each segment fairness using full translation text as approximated context.
    for seg in segments:
        for key, full_text in trans_map.items():
            aid, system, lang = key
            if aid != seg.alert_id:
                continue
            # Use the segment text as source; for translated segment heuristics, use full translation (approximation)
            ev = await evaluate_segment_fairness(seg.segment_text, full_text, lang)
            scores.append(FairnessScore(
                alert_id=seg.alert_id,
                system=system,
                language=lang,
                segment_index=seg.segment_index,
                pf1_urgency_preservation=ev.pf1_urgency_preservation,
                pf2_directive_clarity=ev.pf2_directive_clarity,
                pf3_risk_severity=ev.pf3_risk_severity,
                pf4_authority_attribution=ev.pf4_authority_attribution,
                pf5_temporal_accuracy=ev.pf5_temporal_accuracy,
                pf6_procedural_completeness=ev.pf6_procedural_completeness,
                if1_respectful_tone=ev.if1_respectful_tone,
                if2_inclusion=ev.if2_inclusion,
                if3_empathy_marker=ev.if3_empathy_marker,
                if4_linguistic_clarity=ev.if4_linguistic_clarity,
                if5_cultural_appropriateness=ev.if5_cultural_appropriateness,
                if6_trust_signal=ev.if6_trust_signal,
                rationale=ev.rationale,
            ))

    state["scores"] = scores
    state.setdefault("progress", {})["scores_generated"] = len(scores)
    return state

async def aggregation_agent(state: Dict) -> Dict:
    logger.info("Aggregating segment-level scores into composite indices...")
    scores: List[FairnessScore] = state.get("scores", [])
    rows = []
    for s in scores:
        rows.append({
            "alert_id": s.alert_id,
            "language": s.language,
            "system": s.system,
            "segment_index": s.segment_index,
            "pfi": np.mean([
                s.pf1_urgency_preservation, s.pf2_directive_clarity, s.pf3_risk_severity,
                s.pf4_authority_attribution, s.pf5_temporal_accuracy, s.pf6_procedural_completeness
            ]),
            "ifi": np.mean([
                s.if1_respectful_tone, s.if2_inclusion, s.if3_empathy_marker,
                s.if4_linguistic_clarity, s.if5_cultural_appropriateness, s.if6_trust_signal
            ]),
        })
    df = pd.DataFrame(rows)
    comp: List[CompositeScores] = []
    for (aid, lang, sys), g in df.groupby(["alert_id","language","system"]):
        pfi = float(g["pfi"].mean())
        ifi = float(g["ifi"].mean())
        ofs = float((g["pfi"].mean() + g["ifi"].mean()) / 2.0)
        comp.append(CompositeScores(alert_id=aid, language=lang, system=sys, pfi=pfi, ifi=ifi, ofs=ofs, segments_count=len(g)))
    state["composite_scores"] = comp
    state.setdefault("progress", {})["alerts_aggregated"] = len(comp)
    return state

async def statistical_analysis_agent(state: Dict) -> Dict:
    logger.info("Running statistical tests H1-H3...")
    comp: List[CompositeScores] = state.get("composite_scores", [])
    df = pd.DataFrame([c.dict() for c in comp])
    results: List[StatisticalResults] = []
    if not df.empty:
        h1 = test_hypothesis_h1(df)
        h2 = test_hypothesis_h2(df)
        h3 = test_hypothesis_h3(df)
        results.extend([
            StatisticalResults(name="H1", **h1),
            StatisticalResults(name="H2", **h2),
            StatisticalResults(name="H3", **h3),
        ])
    state["statistical_results"] = results
    return state

async def report_generation_agent(state: Dict) -> Dict:
    logger.info("Generating visualizations and exporting CSV results...")
    output_dir = state.get("output_dir", str((__import__('pathlib').Path(__file__).resolve().parents[1] / 'outputs')))
    # Build dataframes
    scores_df = pd.DataFrame([s.dict() for s in state.get("scores", [])])
    comp_df = pd.DataFrame([c.dict() for c in state.get("composite_scores", [])])
    if not comp_df.empty:
        create_fairness_boxplots(comp_df, output_dir)
    if not scores_df.empty:
        create_fairness_heatmap(scores_df, output_dir)
        create_distribution_plots(scores_df, output_dir)
    export_results_to_csv(state, output_dir)
    logger.info(f"Report artifacts saved to {output_dir}")
    return state
