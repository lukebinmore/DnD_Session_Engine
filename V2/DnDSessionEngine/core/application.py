from DnDSessionEngine.core.startup import startup
from rich.console import Console
import logging

logger = logging.getLogger(__name__)
console = Console()


def run():
    try:
        console.rule("Initial Setup")
        startup_data = startup()
        gemini_client = startup_data["gemini_client"]
        llm_model = startup_data["llm_model"]

    except Exception as e:
        print()
        logger.critical(f"Program execution cancelled. Critical Error: {e}")
        input("Press any key to continue")
