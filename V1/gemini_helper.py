import os
import time
from google.genai.errors import ServerError, APIError
import logging

logger = logging.getLogger("Inspector")


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

    last_error = None

    for model in candidates:
        delay = initial_delay

        for attempt in range(1, max_retries_per_model + 1):
            try:
                response = gemini_client.models.generate_content(
                    model=model,
                    contents=contents,
                    config=config,
                )
                return response

            except (ServerError, APIError) as e:
                err_str = str(e)
                last_error = e
                is_transient = any(code in err_str for code in ["503", "UNAVAILABLE", "429"])

                if is_transient and attempt < max_retries_per_model:
                    time.sleep(delay)
                    delay *= 2
                elif is_transient:
                    continue
                else:
                    break

    raise RuntimeError(f"All model candidates failed generation. Last error: {last_error}")
