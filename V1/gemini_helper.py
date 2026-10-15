import logging
import os
import time

from google.genai.errors import ServerError, APIError

logger = logging.getLogger("GeminiHelper")


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
    candidates = os.environ.get("GEMINI_MODEL", "").strip().split(",")
    logger.info(
        f"Starting Gemini generation with {len(candidates)} model candidate(s), "
        f"up to {max_retries_per_model} attempt(s) each."
    )

    last_error = None

    for model in candidates:
        delay = initial_delay
        logger.info(f"Trying Gemini model '{model}'.")

        for attempt in range(1, max_retries_per_model + 1):
            try:
                response = gemini_client.models.generate_content(
                    model=model,
                    contents=contents,
                    config=config,
                )
                logger.info(
                    f"Gemini generation succeeded with model '{model}' "
                    f"on attempt {attempt}/{max_retries_per_model}."
                )
                return response

            except (ServerError, APIError) as e:
                err_str = str(e)
                last_error = e
                is_transient = any(code in err_str for code in ["503", "UNAVAILABLE", "429"])

                if is_transient and attempt < max_retries_per_model:
                    logger.warning(
                        f"Transient Gemini error from model '{model}' on attempt "
                        f"{attempt}/{max_retries_per_model}; retrying in {delay}s."
                    )
                    time.sleep(delay)
                    delay *= 2
                elif is_transient:
                    logger.warning(
                        f"Transient Gemini errors exhausted retries for model '{model}'; "
                        "trying the next model."
                    )
                    continue
                else:
                    logger.warning(
                        f"Gemini generation failed for model '{model}' with non-retryable "
                        f"{type(e).__name__}; trying the next model."
                    )
                    break

    logger.error(f"Gemini generation failed for all {len(candidates)} model candidate(s).")
    raise RuntimeError(f"All model candidates failed generation. Last error: {last_error}\n")
