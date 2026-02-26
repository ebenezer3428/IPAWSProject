import asyncio
from datetime import datetime
from ipaws_research.models import EmergencyAlert
from ipaws_research.translations import translate_with_gpt4o
from ipaws_research.segmentation import segment_alert
from ipaws_research.evaluation import evaluate_segment_fairness
import os

os.environ["OFFLINE_MODE"] = os.environ.get("OFFLINE_MODE", "1")

async def main():
    test_alert = EmergencyAlert(
        alert_id="TEST001",
        source_text="Evacuate immediately due to wildfire. Life-threatening conditions.",
        category="weather",
        urgency_level="extreme",
        timestamp=datetime.now()
    )
    es_translation = await translate_with_gpt4o(test_alert.source_text, "es")
    segments = segment_alert(test_alert.source_text)
    score = await evaluate_segment_fairness(segments[0][0], es_translation['translation'], "es")
    print("Translation:", es_translation['translation'][:200])
    print("Score:", score.model_dump())

if __name__ == '__main__':
    asyncio.run(main())
