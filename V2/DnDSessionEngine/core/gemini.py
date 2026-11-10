from DnDSessionEngine.core.theme import con
from DnDSessionEngine.core.config import load_config, GEMINI_RETRIES, TRUTH_LOG_DIR
from DnDSessionEngine.core.file_manager import dump_to_file
from rich.live import Live
from google.genai import types, Client
from google.genai.errors import APIError
import mimetypes
import time
import json
import logging

logger = logging.getLogger(__name__)

DELAY = 10


def delay(attempt):
    if attempt < GEMINI_RETRIES:
        live = Live(console=con)
        delay = DELAY
        for _ in range(1, DELAY + 1):
            live.update(f"[warning]Pausing for {delay} seconds before next generation attempt...[/]")
            time.sleep(1)
            delay += -1


def run_gemini_generation(gemini_client, prompt, system_prompt=None, uploaded_file=None):
    candidates = load_config("Gemini Models").split(",")
    logger.info(f"Generating response with Gemini with {len(candidates)} possible models...")

    config = types.GenerateContentConfig(system_instruction=system_prompt, response_mime_type="application/json")

    contents = [prompt]
    contents.append(uploaded_file) if uploaded_file else None

    for model_name in candidates:
        model_name = model_name.strip()
        logger.info(f"Attempting generation with model: {model_name}...")

        for attempt in range(1, GEMINI_RETRIES + 1):
            try:
                response_stream = gemini_client.models.generate_content_stream(
                    model=model_name, contents=contents, config=config
                )

                con.print("Receiving response : ", end="", style="highlight")
                chunks = []
                with Live(
                    "[highlight]Receiving stream from Gemini...[/] [success](Waiting for first chunk)[/]",
                    console=con,
                    refresh_per_second=8,
                    transient=False,
                ) as live:
                    for chunk in response_stream:
                        if chunk.text:
                            chunks.append(chunk.text)
                            live.update(
                                f"[highlight]Receiving stream from Gemini...[/] [success]({len(chunks)} chunks collected)[/]"
                            )

                    live.update(f"[highlight]Receiving stream from Gemini, Done![/] [success](All chunks collected)[/]")

                raw_text = "".join(chunks).strip()
                response_json = json.loads(raw_text)

                if isinstance(response_json, list) or isinstance(response_json, dict):
                    logger.info(f"Generation successful with {model_name} (attempt {attempt})!")
                    return response_json

                logger.warning(f"Model {model_name} returned valid JSON, but not a list. Retrying...")
            except APIError as e:
                if getattr(e, "code", None) == 429 or "RESOURCE_EXHAUSTED" in str(e):
                    logger.warning(f"Rate limit hit for {model_name}. Skipping to next candidate!")
                    break
                logger.warning(f"API error on attempt {attempt} for {model_name}: {e}")
                delay(attempt)

            except json.JSONDecodeError as e:
                logger.warning(f"Invalid JSON returned on attempt {attempt} for {model_name}: {e}")
                delay(attempt)

            except Exception as e:
                logger.warning(f"Unexpected error on attempt {attempt} for {model_name}: {e}")
                delay(attempt)

    raise RuntimeError("All candidate models and retries failed to generate a valid response!")


def upload_file_to_gemini(gemini_client, session_file):
    logger.info(f"Uploading {session_file["name"]} to Gemini...")
    mime_type, _ = mimetypes.guess_type(session_file["path"])
    if not mime_type:
        if str(session_file["path"]).lower().endswith(".m4a"):
            mime_type = "audio/mp4"
        else:
            mime_type = "application/octet-stream"

    uploaded_file = None
    uploaded_file = gemini_client.files.upload(file=session_file["path"], config={"mime_type": mime_type})

    while uploaded_file.state.name == "PROCESSING":
        con.print("Waiting for file to upload...", style="warning")
        time.sleep(3)
        uploaded_file = gemini_client.files.get(name=uploaded_file.name)

    if uploaded_file.state.name != "ACTIVE":
        raise RuntimeError(f"File upload failed with state: {uploaded_file.state.name}")

    logger.info("File uploaded to Gemini successfully! Ready for truth log generation!")
    return uploaded_file


def initialise_gemini():
    logger.info("Initialising Gemini...")
    gemini_api_key = load_config("Gemini API Key")
    try:
        client = Client(api_key=gemini_api_key)
        _ = next(iter(client.models.list()))
        logger.info("Initialising Gemini, Done!")
        return client
    except Exception as e:
        logger.error(f"Failed to create Gemini AI client!")
        raise e
