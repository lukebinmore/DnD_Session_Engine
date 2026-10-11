import os
import tempfile
import time
import logging
import io
import mimetypes
from googleapiclient.http import MediaIoBaseDownload
from google.genai.errors import ServerError, APIError

logger = logging.getLogger("TruthLog")

# Mapping file extensions directly to valid MIME types
AUDIO_MIME_MAP = {
    ".m4a": "audio/mp4",
    ".mp3": "audio/mp3",
    ".wav": "audio/wav",
    ".aac": "audio/aac",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
}

# Preferred model ladder for multimodal audio tasks
MODEL_CANDIDATE_ORDER = [
    "gemini-3.1-pro-preview",
]


def get_audio_mime_type(filename):
    """Resolves correct audio MIME types, prioritizing known container formats."""
    ext = os.path.splitext(filename)[1].lower()
    if ext in AUDIO_MIME_MAP:
        return AUDIO_MIME_MAP[ext]
    mime, _ = mimetypes.guess_type(filename)
    return mime or "audio/mp4"


TRUTH_LOG_SYSTEM_PROMPT = """You are a meticulous, objective scribe for a Dungeons & Dragons tabletop campaign.
Your task is to listen to the session audio and extract an exhaustive, chronological Play-by-Play Truth Log.

Rules:
1. Strip all out-of-character (OOC) talk, meta table banter, snack talk, rule discussions, and dice rolling mechanics.
2. Format output strictly as chronological bullet points prefixed with timestamp [HH:MM] or [MM:SS].
3. Capture vocal traits for NPCs/characters:
   - For every NPC who speaks, document their vocal intent inline using `[Voice: accent, pitch, tone, pace, distinctive mannerisms or speech quirks]`.
   - Canonical First-Impression Rule: The DM may introduce an NPC with a distinct accent, cadence, or pitch, but later slip back into their natural speaking voice as the scene progresses. Always treat the initial, deliberate vocal performance upon character introduction as the true canonical voice. Do not overwrite or dilute this description if the DM later drops the accent.
4. Capture every concrete factual beat:
   - Full names of characters, locations, factions, shops, deities, or artifacts.
   - Distinct physical or sensory descriptions spoken by the DM.
   - Exact quantities of gold, items found, given, lost, or bought.
   - Deals agreed to, alliances made, betrayals, secrets learned, or oaths sworn.
   - Combat outcomes, injuries, arrests, deaths, or persistent magical effects.
5. Spell known entities consistently with the provided list of known campaign tabs whenever possible.
6. Keep lines concise, factual, and declarative. Never invent, extrapolate, or embellish beyond what was actually spoken in the recording.
"""


def download_audio_from_drive(drive_service, file_id, dest_path):
    """Streams the audio file from Google Drive to a local temporary file."""
    logger.info(f"Downloading audio file from Google Drive (ID: {file_id})...")
    request = drive_service.files().get_media(fileId=file_id)
    with io.FileIO(dest_path, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, request, chunksize=1024 * 1024 * 10)
        done = False
        while not done:
            status, done = downloader.next_chunk()
            if status:
                logger.info(f"Download progress: {int(status.progress() * 100)}%")
    logger.info(f"Audio downloaded to: {dest_path}")


def generate_with_dynamic_fallback(
    gemini_client,
    preferred_model,
    contents,
    config,
    max_retries_per_model=3,
    initial_delay=8,
):
    """
    Attempts generation with preferred model using exponential backoff.
    If it hits 503 capacity spikes, 429 rate limits, or 404 deprecations,
    cascades through the candidate model ladder until generation succeeds.
    """
    # 1. Build prioritized list of models
    candidates = []
    if preferred_model:
        candidates.append(preferred_model)
    for model in MODEL_CANDIDATE_ORDER:
        if model not in candidates:
            candidates.append(model)

    last_error = None

    # 2. Outer loop: Iterate through models in the ladder
    for model in candidates:
        logger.info(f"Attempting audio generation with model: '{model}'...")
        delay = initial_delay

        # 3. Inner loop: Retries for the current model
        for attempt in range(1, max_retries_per_model + 1):
            try:
                response = gemini_client.models.generate_content(
                    model=model,
                    contents=contents,
                    config=config,
                )
                logger.info(f"Successfully generated Truth Log using model: '{model}'")
                return response

            except (ServerError, APIError) as e:
                err_str = str(e)
                last_error = e

                # Check if this is a transient server spike or rate limit
                is_transient = any(code in err_str for code in ["503", "UNAVAILABLE", "429"])

                if is_transient and attempt < max_retries_per_model:
                    logger.warning(
                        f"Model '{model}' busy (attempt {attempt}/{max_retries_per_model}). " f"Retrying in {delay}s..."
                    )
                    time.sleep(delay)
                    delay *= 2  # Exponential backoff (8s -> 16s -> ...)
                elif is_transient:
                    logger.warning(
                        f"Exhausted all {max_retries_per_model} retries on '{model}' due to demand. "
                        f"Switching to next candidate model..."
                    )
                else:
                    # Non-transient error (404 deprecated, 400 bad request) -> skip immediately
                    logger.warning(f"Skipping model '{model}' due to non-transient error: {err_str}")
                    break

    raise RuntimeError(f"All model candidates failed generation. Last error: {last_error}")


def run(
    drive_service,
    gemini_client,
    audio_file_id,
    audio_file_name,
    known_tabs=None,
    model_name=None,
    cache_dir="/app/truth_logs",
    **kwargs,
):
    """
    Ingests session audio and returns the chronological play-by-play Truth Log.
    Uses model from environment variable/caller, falling back dynamically if busy.
    """
    known_tabs = known_tabs or []
    preferred_model = model_name

    # 1. Local Cache Check: Skip download and API call if already processed
    os.makedirs(cache_dir, exist_ok=True)
    cache_file = os.path.join(cache_dir, f"{os.path.splitext(audio_file_name)[0]}_truth.txt")
    if os.path.exists(cache_file):
        logger.info(f"Loading cached Truth Log from {cache_file}")
        with open(cache_file, "r", encoding="utf-8") as f:
            return f.read().strip()

    ext = os.path.splitext(audio_file_name)[1] or ".m4a"
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp_file:
        tmp_audio_path = tmp_file.name

    gemini_file = None
    try:
        # 2. Download audio file from Drive in 10MB chunks
        download_audio_from_drive(drive_service, audio_file_id, tmp_audio_path)

        # 3. Upload to Gemini File API using explicit MIME detection
        mime_type = get_audio_mime_type(audio_file_name)
        logger.info(f"Uploading audio to Gemini File API ({audio_file_name}) [MIME: {mime_type}]...")
        gemini_file = gemini_client.files.upload(
            file=tmp_audio_path,
            config={
                "display_name": audio_file_name,
                "mime_type": mime_type,
            },
        )

        # 4. Poll until the Gemini servers finish processing the file
        while gemini_file.state.name == "PROCESSING":
            logger.info("Audio is processing on Gemini servers, waiting 10s...")
            time.sleep(10)
            gemini_file = gemini_client.files.get(name=gemini_file.name)

        if gemini_file.state.name != "ACTIVE":
            raise RuntimeError(f"Audio file upload failed with state: {gemini_file.state.name}")

        logger.info("Audio ready for multimodal generation.")

        # 5. Build dynamic prompt with known tab entities from Stage 1
        known_entities_str = ", ".join(known_tabs) if known_tabs else "None provided yet."
        user_prompt = f"""Process this session audio file ('{audio_file_name}') into the chronological Play-by-Play Truth Log.

Known Campaign Entities (use exact spelling where applicable):
{known_entities_str}

Capture initial vocal characterizations under [Voice: ...] rules, ignoring subsequent accent drops."""

        # 6. Execute generation with dynamic retry and fallback
        response = generate_with_dynamic_fallback(
            gemini_client=gemini_client,
            preferred_model=preferred_model,
            contents=[gemini_file, user_prompt],
            config={
                "system_instruction": TRUTH_LOG_SYSTEM_PROMPT,
                "temperature": 0.2,
            },
        )

        truth_log_text = response.text.strip()

        # 7. Write to cache file on disk
        with open(cache_file, "w", encoding="utf-8") as f:
            f.write(truth_log_text)
        logger.info(f"Truth Log written to {cache_file}")

        return truth_log_text

    finally:
        # Cleanup temporary local audio file
        if os.path.exists(tmp_audio_path):
            try:
                os.remove(tmp_audio_path)
            except OSError:
                pass

        # Cleanup remote Gemini audio upload to prevent storage accumulation
        if gemini_file:
            try:
                gemini_client.files.delete(name=gemini_file.name)
                logger.info(f"Cleaned up remote Gemini file: {gemini_file.name}")
            except Exception as e:
                logger.warning(f"Could not delete remote Gemini file: {e}")
