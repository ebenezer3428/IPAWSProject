import asyncio
import sys
from pathlib import Path
from datetime import datetime

# Ensure project root is on sys.path for imports
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from ipaws_research.alert_retrieval import extract_templates_from_api, save_templates

async def main():
    if len(sys.argv) < 3:
        print("Usage: python scripts/update_templates.py <startDate> <endDate> [perCategory]")
        print("Example: python scripts/update_templates.py 2025-12-01 2025-12-14 20")
        return
    start = datetime.fromisoformat(sys.argv[1])
    end = datetime.fromisoformat(sys.argv[2])
    per = int(sys.argv[3]) if len(sys.argv) > 3 else 20
    templates = await extract_templates_from_api(start, end, per_category=per)
    save_templates(templates)
    print("Template counts:", {k: len(v) for k, v in templates.items()})

if __name__ == '__main__':
    asyncio.run(main())
