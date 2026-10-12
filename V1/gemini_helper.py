import os
import time
import logging
from google.genai.errors import ServerError, APIError

logger = logging.getLogger("GeminiHelper")

MODEL_CANDIDATE_ORDER = ["gemini-3.1-pro-preview", "gemini-3.8-flash"]
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "").strip()


def generate_with_fallback(
    gemini_client,
    contents,
    config,
    max_retries_per_model=3,
    initial_delay=8,
):
    """
    Executes generate_content with exponential backoff on transient errors
    and falls back through the model ladder if a model remains unavailable.
    """
    candidates = []
    if GEMINI_MODEL:
        logger.info(GEMINI_MODEL)
        candidates.append(GEMINI_MODEL)
    for model in MODEL_CANDIDATE_ORDER:
        if model not in candidates:
            candidates.append(model)

    last_error = None

    for model in candidates:
        logger.info(f"Attempting Gemini generation with model: '{model}'...")
        delay = initial_delay

        for attempt in range(1, max_retries_per_model + 1):
            try:
                response = gemini_client.models.generate_content(
                    model=model,
                    contents=contents,
                    config=config,
                )
                logger.info(f"Generation successful with model: '{model}'.")
                return response

            except (ServerError, APIError) as e:
                err_str = str(e)
                last_error = e
                is_transient = any(code in err_str for code in ["503", "UNAVAILABLE", "429"])

                if is_transient and attempt < max_retries_per_model:
                    logger.warning(
                        f"Model '{model}' busy (attempt {attempt}/{max_retries_per_model}). " f"Retrying in {delay}s..."
                    )
                    time.sleep(delay)
                    delay *= 2
                elif is_transient:
                    logger.warning(f"Exhausted retries on '{model}'. Trying next candidate...")
                else:
                    logger.warning(f"Skipping '{model}' due to non-transient error: {err_str}")
                    break

    raise RuntimeError(f"All model candidates failed generation. Last error: {last_error}")
