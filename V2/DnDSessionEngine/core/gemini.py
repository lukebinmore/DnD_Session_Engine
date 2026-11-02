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
- Order events strictly chronologically, prefixing each entry with an audible timestamp using [HH:MM] or [MM:SS].
- Separate distinct meaningful beats into individual entries in the array. Keep connected actions together only when splitting them would lose their cause-and-effect relationship.
- Do not summarize a sequence as "the party explored," "they fought," or "they discussed it" when the audio contains specific actions or outcomes.
- For each beat, include who acted, what they did or said, who or what was affected, and the result or consequence whenever those details are audible.
- Preserve meaningful reactions, failed attempts, costs, risks, disagreements, changes of plan, and follow-up actions.
- Avoid filler and exact verbatim dialogue unless the wording itself is important, such as a name, promise, bargain, threat, password, oath, or revealing statement.

PLAYER CHARACTERS AND THE PARTY
- Track player-character actions individually when the character can be identified. Do not guess which character acted based only on the real-world player's voice.
- Use "the party" for collective actions, shared decisions, group reactions, or actions whose individual actor is unclear.
- Make shared party events and decisions explicit so they can be recorded in the campaign's group entity.
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
- Important NPC voice traits when clearly performed or described. For an NPC's first deliberate introduction, record the initial distinctive voice as canonical; do not replace it with a later lapse in accent or performance.

OUTPUT FORMAT
Return ONLY a valid JSON array of strings (e.g. ["[\HH:MM\] Event 1...", "[\HH:MM\] Event 2..."]).
Do not wrap the array in markdown backticks (no ```json). Do not add any introductory text, explanation, analysis, or conclusion outside the array. Be concise at the sentence level, but do not omit meaningful details for the sake of keeping the log short.
"""


def save_truth_log(truth_log, session_data):
    session_num = session_data["Session Number"]
    file_path = TRUTH_LOG_DIR / f"Session {session_num}.json"
    dump_to_file(truth_log, file_path, f"Session {session_num}.json")


def delay(attempt):
    if attempt <= GEMINI_RETRIES:
        logger.info(f"Pausing before next generation attempt. Delay: {DELAY * attempt} seconds! ")
        time.sleep(DELAY * attempt)


def run_model_generation(gemini_client, candidates, uploaded_file, prompt_text):
    logger.info(f"Generating truth log with Gemini with {len(candidates)} possible models...")
    config = types.GenerateContentConfig(
        system_instruction=TRUTH_LOG_SYSTEM_PROMPT, response_mime_type="application/json"
    )
    contents = [uploaded_file, prompt_text]

    for model_name in candidates:
        model_name = model_name.strip()
        logger.info(f"Attempting generation with model: {model_name}...")

        for attempt in range(1, GEMINI_RETRIES + 1):
            try:
                response_stream = gemini_client.models.generate_content_stream(
                    model=model_name, contents=contents, config=config
                )

                con.print("Receiving truth log: ", end="", style="highlight")
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
                truth_log = json.loads(raw_text)

                if isinstance(truth_log, list):
                    logger.info(f"Generation successful with {model_name} (attempt {attempt})!")
                    return truth_log

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

    raise RuntimeError("All candidate models and retries failed to generate a valid truth log!")


def build_prompt(session_data, manifest, prev_truth_log):
    logger.info("Building session prompt for Gemini...")
    context_text = f"""Session Context:
- Session Number: {session_data.get('Session Number')}
- Session Date: {session_data.get('Session Date')}

Campaign Manifest (Known Entities):
{json.dumps(manifest, indent=2)}

Previous Session Truth Log:
{json.dumps(prev_truth_log, indent=2) if prev_truth_log else "None (First session)"}

Task:
Listen to the attached audio session and generate the chronological Truth Log adhering strictly to the system instructions.
"""

    logger.info("Session prompt built successfully!")
    return context_text


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


def generate_truth_log(gemini_client, session_file, session_data, manifest, prev_truth_log):
    candidates = load_config("Gemini Models").split(",")

    try:
        uploaded_file = upload_file_to_gemini(gemini_client, session_file)
        prompt_text = build_prompt(session_data, manifest, prev_truth_log)
        curr_truth_log = run_model_generation(gemini_client, candidates, uploaded_file, prompt_text)
        save_truth_log(curr_truth_log, session_data)
        return curr_truth_log
    finally:
        if uploaded_file is not None:
            gemini_client.files.delete(name=uploaded_file.name)
            logger.info("Remote file cleaned up from Gemini!")


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
