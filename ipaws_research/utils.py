import logging
from pathlib import Path
from dotenv import load_dotenv

LOG_PATH = Path(__file__).resolve().parents[1] / "logs" / "research.log"
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

# Load environment variables from project .env early
PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler()]
)

logger = logging.getLogger("ipaws_research")
