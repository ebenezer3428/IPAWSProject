import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ipaws_research.evaluation import evaluate_segment_fairness

async def main():
    src = "Evacuate immediately due to wildfire approaching the area."
    trn = "Evacue inmediatamente debido a un incendio forestal acercandose al area."
    ev = await evaluate_segment_fairness(src, trn, language="es", context="")
    print(ev.model_dump())

if __name__ == "__main__":
    asyncio.run(main())
