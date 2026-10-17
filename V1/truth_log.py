import os
import hashlib
import json
import tempfile
import time
import logging
import io
import mimetypes
import gemini_helper
from googleapiclient.http import MediaIoBaseDownload

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


def get_audio_mime_type(filename):
    """Resolves correct audio MIME types, prioritizing known container formats."""
    ext = os.path.splitext(filename)[1].lower()
    if ext in AUDIO_MIME_MAP:
        return AUDIO_MIME_MAP[ext]
    mime, _ = mimetypes.guess_type(filename)
    return mime or "audio/mp4"


TRUTH_LOG_SYSTEM_PROMPT = """You are an objective, meticulous scribe for a Dungeons & Dragons campaign.

Listen to the session audio and produce a high-recall, chronological Truth Log. Preserve every meaningful in-game event and concrete detail that can be reliably heard. This log will be used by later steps to update session notes and campaign entities, so do not compress away facts those steps may need.

SCOPE AND ACCURACY
- Include in-game events, decisions, dialogue substance, discoveries, consequences, and relevant game outcomes.
- Exclude unrelated out-of-character chatter, food, interruptions, and table logistics.
- If an out-of-character clarification corrects or establishes what happened in the game, record the corrected in-game fact.
- Never invent, infer hidden thoughts, or embellish. Distinguish what a character says from what is confirmed to be true.
- If a name, speaker, quantity, or outcome is unclear, say it is unclear rather than guessing.
- Use the exact spelling of known campaign entities when the match is clear. Otherwise, record the name as heard and do not force a match.

CHRONOLOGY AND DETAIL
- Write timestamped bullet points in chronological order, using [HH:MM] or [MM:SS].
- Use a separate bullet for each distinct meaningful beat. Keep connected actions together only when splitting them would lose their cause-and-effect relationship.
- Do not summarize a sequence as “the party explored,” “they fought,” or “they discussed it” when the audio contains specific actions or outcomes.
- For each beat, include who acted, what they did or said, who or what was affected, and the result or consequence whenever those details are audible.
- Preserve meaningful reactions, failed attempts, costs, risks, disagreements, changes of plan, and follow-up actions.
- Avoid filler and exact verbatim dialogue unless the wording itself is important, such as a name, promise, bargain, threat, password, oath, or revealing statement.

PLAYER CHARACTERS AND THE PARTY
- Track player-character actions individually when the character can be identified. Do not guess which character acted based only on the real-world player’s voice.
- Use “the party” for collective actions, shared decisions, group reactions, or actions whose individual actor is unclear.
- Make shared party events and decisions explicit so they can be recorded in the campaign’s group entity.
- Preserve important interactions between characters, NPCs, and the party, including agreements, conflicts, assistance, trust, suspicion, and changes in relationships.
- Record observable character behavior and explicit statements relevant to goals, ideals, flaws, or changes in outlook. Do not diagnose personality or infer motivation.
- Use character names consistently. Avoid ambiguous pronouns when naming the character would make the event clearer.

CAPTURE WHEN PRESENT
- Names and descriptions of people, places, groups, shops, deities, objects, clues, and destinations.
- Exploration, routes taken, locations entered or left, discoveries, environmental details, and meaningful sensory descriptions.
- Conversations: who spoke, the substance of important statements, questions, answers, negotiations, promises, threats, secrets, and reactions.
- Combat: meaningful movement, attacks, spells, abilities, assistance, targets, hits or misses, damage, healing, conditions, resource use, changes in advantage, and the final outcome. Include dice or rule details only when they explain a meaningful result.
- Exact quantities of currency, items, supplies, rewards, purchases, losses, and transfers; identify who gave, received, found, or used them.
- Changes to status, injuries, curses, affiliations, leadership, ownership, relationships, goals, plans, and unresolved threats.
- Important NPC voice traits when clearly performed or described. For an NPC’s first deliberate introduction, record the initial distinctive voice as canonical; do not replace it with a later lapse in accent or performance.

OUTPUT
Return only the chronological bullet-point Truth Log. Be concise at the sentence level, but do not omit meaningful details for the sake of keeping the log short. Do not add an introduction, summary, analysis, or facts that were not supported by the audio.
"""


def download_audio_from_drive(drive_service, file_id, dest_path):
    """Streams the audio file from Google Drive to a local temporary file."""
    request = drive_service.files().get_media(fileId=file_id)
    with io.FileIO(dest_path, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, request, chunksize=1024 * 1024 * 10)
        done = False
        while not done:
            status, done = downloader.next_chunk()
            if status is not None:
                progress_percent = status.progress() * 100
                logger.info(f"Google Drive download progress: {progress_percent:.1f}%.")


def run(
    drive_service,
    gemini_client,
    audio_file_id,
    audio_file_name,
    known_tabs=None,
    previous_summary=None,
    session_num=None,
    cache_dir="/app/truth_logs",
    **kwargs,
):
    """
    Ingests session audio and returns the chronological play-by-play Truth Log.
    Uses model from environment variable/caller, falling back dynamically if busy.
    """
    known_tabs = known_tabs or []
    previous_summary = previous_summary or ""

    # 1. Local Cache Check: Skip download and API call if already processed
    os.makedirs(cache_dir, exist_ok=True)
    cache_context = json.dumps(
        {
            "version": 2,
            "session_num": session_num,
            "known_tabs": known_tabs,
            "previous_summary": previous_summary,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    cache_key = hashlib.sha256(cache_context.encode("utf-8")).hexdigest()[:12]
    cache_file = os.path.join(
        cache_dir,
        f"{os.path.splitext(audio_file_name)[0]}_truth_{cache_key}.txt",
    )
    if os.path.exists(cache_file):
        logger.info(f"Using cached truth log for '{audio_file_name}'.")
        with open(cache_file, "r", encoding="utf-8") as f:
            return f.read().strip()

    ext = os.path.splitext(audio_file_name)[1] or ".m4a"
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp_file:
        tmp_audio_path = tmp_file.name

    gemini_file = None
    try:
        # 2. Download audio file from Drive in 10MB chunks
        logger.info(f"Downloading audio file '{audio_file_name}' from Google Drive...")
        download_audio_from_drive(drive_service, audio_file_id, tmp_audio_path)
        logger.info(f"Downloaded audio file '{audio_file_name}'.")

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
        processing_started_at = time.monotonic()
        if gemini_file.state.name == "PROCESSING":
            logger.info(f"Gemini is processing '{audio_file_name}'; polling every 10 seconds...")
        while gemini_file.state.name == "PROCESSING":
            time.sleep(10)
            gemini_file = gemini_client.files.get(name=gemini_file.name)
            elapsed_seconds = time.monotonic() - processing_started_at
            logger.info(f"Gemini upload poll for '{audio_file_name}': state={gemini_file.state.name}.")

        if gemini_file.state.name != "ACTIVE":
            raise RuntimeError(f"Audio file upload failed with state: {gemini_file.state.name}")

        # 5. Build dynamic prompt with known tab entities from Stage 1
        known_entities_str = ", ".join(known_tabs) if known_tabs else "None provided yet."
        user_prompt = f"""Process this session audio file ('{audio_file_name}') into the chronological Play-by-Play Truth Log.

Current session number: {session_num if session_num is not None else 'Unknown'}

Previous Session Notes (historical context only; do not report these as current events unless they happen again in the audio):
{previous_summary or 'No previous session notes available.'}

Known Campaign Entities (use exact spelling where applicable):
{known_entities_str}

Use the previous notes only to resolve references and understand ongoing context. The Truth Log must describe
events from this recording only. Capture initial vocal characterizations under [Voice: ...] rules, ignoring
subsequent accent drops."""

        # 6. Execute generation with dynamic retry and fallback
        logger.info(f"Generating truth log for '{audio_file_name}'...")
        response = gemini_helper.generate_with_fallback(
            gemini_client=gemini_client,
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
        logger.info(f"Generated and cached truth log for '{audio_file_name}' " f"({len(truth_log_text)} characters).")

        return truth_log_text

    finally:
        # Cleanup temporary local audio file
        if os.path.exists(tmp_audio_path):
            try:
                os.remove(tmp_audio_path)
            except OSError as e:
                logger.warning(f"Could not remove temporary audio file: {e}\n")
                pass

        # Cleanup remote Gemini audio upload to prevent storage accumulation
        if gemini_file:
            try:
                gemini_client.files.delete(name=gemini_file.name)
            except Exception as e:
                logger.warning(f"Could not delete Gemini upload '{gemini_file.name}': {e}\n")
