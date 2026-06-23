import asyncio
import os
from ipaws_research.workflow import create_research_workflow

async def main():
    os.environ["OFFLINE_MODE"] = os.environ.get("OFFLINE_MODE", "1")
    app = create_research_workflow()
    state = {
        "sample_size": 45,
        "target_languages": ["es","hi"],
        "translation_systems": ["gpt4o","google_nmt","llama3"],
        "alerts": [],
        "translations": [],
        "segments": [],
        "scores": [],
        "composite_scores": [],
        "statistical_results": [],
        "current_step": "",
        "errors": [],
        "progress": {},
        "output_dir": str((__import__('pathlib').Path(__file__).resolve().parents[1] / 'outputs')),
    }
    result = await app.ainvoke(state)
    print("Alerts:", len(result.get("alerts", [])))
    print("Translations:", len(result.get("translations", [])))
    print("Segments:", len(result.get("segments", [])))
    print("Scores:", len(result.get("scores", [])))
    print("Composite:", len(result.get("composite_scores", [])))
    print("Stats:", len(result.get("statistical_results", [])))
    print("Outputs saved to:", result.get("output_dir"))

if __name__ == "__main__":
    asyncio.run(main())
