from DnDSessionEngine.core.config import initialise_directories, initialise_config
from DnDSessionEngine.core.logging import initialise_logging
from DnDSessionEngine.core.local_llm import initialise_llm
from DnDSessionEngine.core.gemini import initialise_gemini
from DnDSessionEngine.core.kanka import initialise_kanka
import logging

logger = logging.getLogger(__name__)


def startup():
    print("Starting Application...\n")

    try:
        initialise_logging()
        logger.info("Initialising Logging, Done!\n")

        logger.info("Initialising Directories...")
        initialise_directories()
        logger.info("Initialising Directories, Done!\n")

        logger.info("Initialising Config...")
        initialise_config()
        logger.info("Initialising Config, Done!\n")

        logger.info("Initialising Local Model...")
        llm_model = initialise_llm()
        logger.info("Initialising Local Model, Done!\n")

        logger.info("Initialising Gemini...")
        gemini_client = initialise_gemini()
        logger.info("Initialising Gemini, Done!\n")

        logger.info("Initialising Kanka...")
        initialise_kanka()
        logger.info("Initialising Kanka, Done!\n")

        startup_data = {"llm_model": llm_model, "gemini_client": gemini_client}
        logger.info("Setup Complete\n")
        return startup_data

    except Exception:
        print()
        logger.error("Failed to initialise application!")
        raise
