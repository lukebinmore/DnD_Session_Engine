from DnDSessionEngine.core.config import load_config
from google import genai
import logging

logger = logging.getLogger(__name__)


def initialise_gemini():
    logger.info("Verifying Gemini API key...")
    gemini_api_key = load_config("Gemini API Key")
    try:
        client = genai.Client(api_key=gemini_api_key)
        _ = next(iter(client.models.list()))
        logger.info("Gemini API key verified successfully!")
        return client
    except Exception as e:
        logger.error(f"Failed to create Gemini AI client!")
        raise e
