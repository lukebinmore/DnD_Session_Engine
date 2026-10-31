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
        logger.info("Initialising Directories...")
        initialise_directories()
        logger.info("Initialising Directories, Done!")

        con.rule("Config", style="rule.section")
        logger.info("Initialising Config...")
        initialise_config()
        logger.info("Initialising Config, Done!")

        con.rule("Local Model", style="rule.section")
        logger.info("Initialising Local Model...")
        llm_model = initialise_llm()
        logger.info("Initialising Local Model, Done!")

        con.rule("Gemini", style="rule.section")
        logger.info("Initialising Gemini...")
        gemini_client = initialise_gemini()
        logger.info("Initialising Gemini, Done!")

        con.rule("Kanka", style="rule.section")
        logger.info("Initialising Kanka...")
        campaign_data = initialise_kanka()
        logger.info("Initialising Kanka, Done!")

        startup_data = {"llm_model": llm_model, "gemini_client": gemini_client, "campaign_data": campaign_data}
        logger.info("Setup Complete")
        return startup_data

    except Exception:
        print()
        logger.error("Failed to initialise application!")
        raise
