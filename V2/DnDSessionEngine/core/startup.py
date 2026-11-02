from DnDSessionEngine.core.theme import con
from DnDSessionEngine.core.config import initialise_directories, initialise_config
from DnDSessionEngine.core.logging import initialise_logging
from DnDSessionEngine.core.local_llm import initialise_llm
from DnDSessionEngine.core.gemini import initialise_gemini
from DnDSessionEngine.core.kanka import initialise_kanka
import logging

logger = logging.getLogger(__name__)


def startup():
    try:
        initialise_logging()
        logger.info("Initialising Logging, Done!")

        con.rule("Directories", style="rule.section")
        initialise_directories()

        con.rule("Config", style="rule.section")
        initialise_config()

        con.rule("Local Model", style="rule.section")
        llm_model = initialise_llm()

        con.rule("Gemini", style="rule.section")
        gemini_client = initialise_gemini()

        con.rule("Kanka", style="rule.section")
        initialise_kanka()

        startup_data = {"llm_model": llm_model, "gemini_client": gemini_client}
        logger.info("Setup Complete")
        return startup_data

    except Exception:
        print()
        logger.error("Failed to initialise application!")
        raise
