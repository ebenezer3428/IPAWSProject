import asyncio
from datetime import datetime
from ipaws_research.models import EmergencyAlert
from ipaws_research.translations import translate_with_gpt4o
from ipaws_research.segmentation import segment_alert
from ipaws_research.evaluation import evaluate_segment_fairness
from ipaws_research.workflow import create_research_workflow

async def test_single_alert():
    test_alert = EmergencyAlert(
        alert_id="TEST001",
        source_text="Evacuate immediately due to wildfire. Life-threatening conditions.",
        category="weather",
        urgency_level="extreme",
        timestamp=datetime.now()
    )
    es_translation = await translate_with_gpt4o(test_alert.source_text, "es")
    hi_translation = await translate_with_gpt4o(test_alert.source_text, "hi")
    segments = segment_alert(test_alert.source_text)
    score = await evaluate_segment_fairness(segments[0][0], es_translation['translation'], "es")
    print(f"Test completed: {score}")

async def test_full_pipeline_small():
    app = create_research_workflow()
    result = await app.ainvoke({
        "sample_size": 3,
        "target_languages": ["es"],
        "translation_systems": ["gpt4o"],
        "alerts": [],
        "translations": [],
        "segments": [],
        "scores": [],
        "composite_scores": [],
        "statistical_results": [],
        "current_step": "",
        "errors": [],
        "progress": {},
    })
    print(f"Small test completed: {len(result['alerts'])} alerts processed")

if __name__ == "__main__":
    asyncio.run(test_single_alert())
