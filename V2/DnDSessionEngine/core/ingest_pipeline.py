from DnDSessionEngine.core.theme import con
from DnDSessionEngine.core.kanka import get_kanka_data, kanka_post, build_manifest_index
from DnDSessionEngine.core.kanka_config import KANKA_TEMPLATES
from DnDSessionEngine.core.file_manager import prompt_for_file, read_json_file, dump_to_file
from DnDSessionEngine.core.config import TRUTH_LOG_DIR, ENTITIES_DIR
from DnDSessionEngine.core.helpers import build_table
from DnDSessionEngine.core.gemini import upload_file_to_gemini, run_gemini_generation
from pathlib import Path
from datetime import datetime
import json
import logging

import traceback
from rich.pretty import pprint

logger = logging.getLogger(__name__)

modules_to_use = " | ".join([key for key in KANKA_TEMPLATES.keys()])

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

JOURNAL_SYSTEM_PROMPT = """You are a campaign chronicler and tabletop co-DM assistant.
Your task is to analyze the provided campaign manifest, current session truth log, and previous session truth log to generate a structured journal entry consisting of a thematic title and a cohesive narrative recap.

### Guidelines:
1. Ground all narrative events strictly in the current session truth log, using the previous session truth log only for context or resolving continuing plot threads.
2. Cross-reference the campaign manifest to ensure exact canonical names, titles, affiliations, and locations are maintained throughout.
3. Write the summary in past-tense narrative prose spanning 2 to 3 cohesive paragraphs. Focus on party actions, major discoveries, combat encounters, social developments, and quest milestones.
4. Each paragraph in the summary must be wrapped in <p></p> tags.
5. Do NOT mention out-of-character mechanics, dice rolls, checks, saving throws, damage numbers, logs, manifests, or game metadata.
6. Generate a punchy, evocative, episode-style title (2 to 6 words) reflecting the session's central revelation, conflict, or turning point. Avoid generic titles like "The Adventure Continues" or "Session Recap".
7. Return ONLY a valid JSON object matching the exact schema below, with no markdown code fences (no ```json), introductory filler, or commentary.

### SPECIAL RULES:
1. Whenever mentioning any known entity in any text/entry field, you must link it using the exact syntax `[entity:entity_id|display_text]` (e.g., `[entity:12345|Greg's]` or `[entity:12345|the Captain]`), resolving `entity_id` against the Manifest and using whatever natural word, possessive, or phrasing you would have otherwise written for `display_text`.

### JSON Schema:
{
  "name": "Short Thematic Title Here",
  "summary": "<p>First paragraph detailing opening movements and rising action...</p><p>Second paragraph detailing major conflicts, investigations, or discoveries...</p><p>Final paragraph detailing session resolution, lingering cliffhangers, or immediate aftermath...</p>"
}
"""

ENTITY_LIST_SYSTEM_PROMPT = """You are an expert tabletop RPG campaign archivist and entity resolution engine.
Your task is to analyze a chronological session Truth Log against an existing Campaign Manifest to identify:
1. "new": Brand-new entities that must be created in the campaign tracker.
2. "updates": Existing manifest entities that received narrative progression, status changes, location moves, new aliases/nicknames or whose true identity/name was revealed.

### INPUT DATA DEFINITIONS:
- Manifest: A directory of known entities containing ID, Type/Module, Canonical Name, Aliases, and a brief Summary/Descriptor.
- Truth Log: Chronological bullet points of events, dialogue, discoveries, and actions from the session.

### RESOLUTION RULES:
1. CROSS-REFERENCE SUMMARIES & ALIASES FIRST:
   - Before declaring an entity "new", check existing manifest names, aliases, and summaries.
   - If an unnamed character or entity appears in the Truth Log (e.g., "a dwarf with a scarred left eye", "the hooded informant"), compare their distinctive physical traits, gear, or affiliations against the manifest summaries.
   - If a strong, unique match exists, treat it as an existing entity under "updates", NOT a new one. Do not merge on generic traits alone (e.g., being a "human guard" is not enough).

2. "new" ENTITIES:
   - Must be entities appearing in the campaign for the first time with no prior match in the manifest.
   - If a notable entity lacks a formal name, assign a concise, distinct title (e.g., "Scarred Silver Knight", "The Whispering Skull").
   - Names must be concise proper nouns without parenthetical notes or narrative fluff (e.g., write "Enchanted Bone Dagger", NEVER "The bone dagger found under the floorboards").
   - Deduplicate locations: do not create sub-entries for generic streets, alleyways, or doorways if the overarching settlement or establishment is present. Only include these if a location or entity seems notable.
   - Ignore mundane background props, common coins, and nameless background mobs.

3. "updates" ENTITIES (PROGRESSION & RENAMES):
   - Must be an existing entity from the manifest that experienced significant plot development, combat, dialogue, movement, injury, or discovery or general information updates.
   - Passive background mentions do not warrant an update.
   - Reference existing entities STRICTLY by their integer `entity_id` from the manifest, not ids. Never invent IDs.
   - IDENTITY REVEALS / RENAMES: If an existing entity previously tracked under a placeholder or descriptor (e.g., "Shadowy Figure") has their true name revealed (e.g., "Master Vidal"), add their ID to the updates list.

### OUTPUT FORMAT:
Return ONLY a valid JSON object matching the schema below. Do not wrap in markdown code fences (no ```json), and do not include reasoning, explanations, or conversational filler.

{
  "new": [
    {
      "name": "Exact Canonical Name or Concise Descriptor",
      "type": "#KEYS#",
    }
  ],
  "updates": [12301240, Another entity_id]
}""".replace("#KEYS#", modules_to_use)

UPDATES_SYSTEM_PROMPT = """You are an expert tabletop RPG campaign archivist and entity updater.
Your task is to analyze a session Truth Log and update target entities according to strict module templates.

### INPUT DATA DEFINITIONS:
1. Entities to update: A collection of existing entity records to evaluate.
2. Templates: Schema definitions specifying field types, required flags ("required: yes/no"), and action rules for each entity module.
3. Manifest: A lookup directory (entity_id, id, name, type) used to resolve entity names to their integer IDs for relational fields and entity tagging.
4. Truth Log: Chronological bullet points of events, actions, and discoveries from the current session.

### TARGET EVALUATION & PLAYER CHARACTERS:
- TREAT ALL ENTITIES EQUALLY: Entities with type "Player" (player characters) MUST be updated with the exact same rigor as NPCs and locations. When players experience events, change statuses, enter locations, reveal traits, or acquire titles/items in the Truth Log, update their respective fields immediately.

### FIELD ACTION SEMANTICS:
Only apply changes to fields explicitly defined in the corresponding module template:
- "required: yes": If a field is flagged as required in the template and is currently missing, null, or empty, you MUST populate it using details from the Truth Log or logical inference based on the session's context.
- "default": Fill any blanks, or update the field if the Truth Log provides new, clarifying, or expanded canonical information. Otherwise, omit.
- "fill if empty": Supply a value ONLY if the field is currently missing, null, or empty, and the Truth Log provides the information.
- "append": Preserve all existing elements in the array and append any new, distinct items identified in the Truth Log (e.g. integer IDs mapped from the Manifest). Never duplicate existing values.

### DELTA RULES:
1. OUTPUT MINIMAL DELTAS ONLY: For each updated entity, include `entity_id`, `id`, `module`, and ONLY the specific fields being modified, populated, or appended.
2. EXCLUDE UNCHANGED FIELDS: Do not echo unchanged fields or static attributes. If an existing field did not change, omit it from that entity's object.
3. EXCLUDE UNMODIFIED ENTITIES: If an entity was evaluated but required zero field additions or changes, omit that entity entirely from the output dictionary.
4. TUPLE PAIRS: Fields marked as "array of string tuple pairs" must be output as arrays of 2-item arrays: [["Key", "Value"], ...].
5. RELATIONAL IDS: Relational fields (e.g., location_id, locations, families) must contain strictly module-specific integer `id` values mapped via the Manifest (NOT `entity_id`) unless explicitly stated in the template description. Never use string names.

### SPECIAL RULES:
1. Whenever mentioning any known entity in any text/entry field, you must link it using the exact syntax `[entity:entity_id]` (e.g., `[entity:12345]'s` or `[entity:12345]`), resolving `entity_id` against the Manifest. Do not include a custom display name in the tag.

### OUTPUT FORMAT:
Return ONLY a valid JSON object of sparse delta objects using the entity_id as the top-level string key. Do not wrap in markdown code fences (no ```json), and include no conversational text or preamble.

{
  "10108758": {
    "entity_id": 10108758,
    "id": 2626920,
    "module": "characters",
    "status_id": 3
  },
  "10108739": {
    "entity_id": 10108739,
    "id": 1845102,
    "module": "characters",
    "location_id": 54102,
    "title": "Former Guard Captain"
  }
}
"""

POSTS_SYSTEM_PROMPT = """You are a campaign archivist tracking updates for tabletop roleplaying entities in Kanka.
Your task is to analyze the provided session truth log and generate log posts for eligible entities that experienced notable events, actions, changes, or revelations during the current session.

### Input Data Available:
1. **Truth Log**: The factual record of what transpired during the current session.
2. **Manifest**: Master reference list of campaign entities (containing IDs, canonical names, types, and descriptions).
3. **Existing Posts**: Previously logged posts for candidate entities (structured by entity_id: list of prior post titles/entries).
4. **Target entity_ids**: The explicit list of candidate entity_ids to evaluate for post creation.

### Strict Generation & Filtering Rules:
1. **Target Boundary**: You may ONLY evaluate and generate posts for entity IDs explicitly provided in the candidate list. Never invent or include an entity_id not present in that list.
2. **Cardinality Limit**: Output at most ONE post per candidate entity. If an entity experienced multiple events, consolidate them into a single coherent entry, using <p></p> tags to seperate paragraphs.
3. **No Duplicate or Redundant Posts**:
   - Inspect the entity's prior entries in `Existing Posts`.
   - Do NOT create a post if the events from this session are already described or recorded in existing posts for that entity.
4. **Significance Threshold (Worthwhile Check)**:
   - Generate a post ONLY if the entity was directly involved in meaningful, noteworthy, or state-changing events during this session (e.g., plot revelations, combat encounters, dialogues of consequence, status/location changes, or acquired knowledge).
   - Skip entities that only had passive, trivial, background, or passing mentions (e.g., walking past an NPC, generic merchant transactions, or ambient environment mentions).
   - If an entity had no meaningful action or development, generate nothing for it.
5. **Prose & Style**:
   - `name`: A concise, informative title capturing the core event or encounter (e.g., "Ambush at the Crossroads", "Interrogation by the Guard Captain", "Discovery of the Ruined Archive"). Do not prefix with dates or session numbers unless necessary.
   - `entry`: Write in past-tense, matter-of-fact narrative prose summarizing the entity's experiences, actions, and observations during the session. Keep it structured in plain text or simple paragraph HTML tags (`<p>...</p>`). Do NOT attempt to format entity links or brackets here—output plain canonical names.

### SPECIAL RULES:
1. Whenever mentioning any known entity in any text/entry field, you must link it using the exact syntax `[entity:entity_id]` (e.g., `[entity:12345]'s` or `[entity:12345]`), resolving `entity_id` against the Manifest. Do not include a custom display name in the tag.

### Output Format:
Return ONLY a valid JSON array of objects conforming exactly to this structure:
```json
[
  {
    "entity_id": 123456,
    "name": "Brief Descriptive Title",
    "entry": "<p>A concise, objective record of the events and experiences this entity had during the session.</p>"
  }
]
"""


def post_posts(posts):
    logger.info(f"Uploading {len(posts)} posts to Kanka...")
    for post in posts:
        eid = post.get("entity_id")
        post["settings"] = {"collapsed": 1}
        kanka_post(f"entities/{eid}/posts", post)
    logger.info(f"Posts uploaded {len(posts)} to Kanka successfully!")


def generate_posts(gemini_client, entities, truth_log, manifest):
    logger.info("Generating entity posts using Gemini...")
    truth_log = "\n".join(truth_log)
    manifest = build_manifest_index(manifest)
    existing_posts = json.dumps(build_posts_map(entities), indent=2)
    prompt = f"Entities to generate posts for:\n{entities}, Existing entity posts:\n{existing_posts}\n\nManifest:\n{manifest}\n\nTruth Log:\n{truth_log}"
    response = run_gemini_generation(gemini_client, prompt, POSTS_SYSTEM_PROMPT)
    logger.info("Entity posts generated using Gemini successfully!")
    return response


def post_updates(entities, aliases):
    logger.info("Uploading updates and aliases to Kanka...")

    logger.info(f"Uploading {len(entities)} updates to Kanka...")
    for eid, value in entities.items():
        id = value.get("id")
        module = value.pop("module")
        kanka_post(f"{module}/{id}", value, mode="PATCH")
    logger.info(f"{len(entities)} updates uploaded to Kanka successfully!")

    logger.info(f"Uploading {len(aliases)} aliases to Kanka...")
    for a in aliases:
        eid = a.get("entity_id")
        name = a.get("name")
        payload = {"name": name, "type_id": 3}
        kanka_post(f"entities/{eid}/entity_assets", payload)
    logger.info(f"{len(aliases)} aliases uploaded to Kanka successfully!")

    logger.info("Updates and aliases uploaded to Kanka successfully!")


def process_updates(entities, manifest):
    logger.info("Processing entity update results...")

    logger.info("Extracting short hand entity data into appropriate fields...")
    for eid, value in entities.items():
        if value.get("personality"):
            value["personality_name"] = [k for k, v in value["personality"]]
            value["personality_entry"] = [v for k, v in value["personality"]]
            del value["personality"]
        if value.get("appearance"):
            value["appearance_name"] = [k for k, v in value["appearance"]]
            value["appearance_entry"] = [v for k, v in value["appearance"]]
            del value["appearance"]
    logger.info("Short hand entity data extracted into appropriate fields successfully!")

    logger.info("Extracting aliases from entities...")
    aliases = []
    for eid, value in entities.items():
        existing_aliases = manifest.get(eid, {}).get("aliases", [])
        if value.get("aliases"):
            for a in value.get("aliases"):
                if a in existing_aliases:
                    continue
                aliases.append({"entity_id": eid, "name": a})
            del value["aliases"]
    logger.info("Aliases extracted from entities successfully!")

    logger.info("Updating manifest with updates...")
    for eid, value in entities.items():
        if eid in manifest:
            manifest[eid].update(value)
    logger.info("Manifest updated with updates successfully!")

    logger.info("Entity update result processed successfully!")
    return entities, aliases


def build_posts_map(entities):
    logger.info("Loading full entity posts list from campaign map...")
    flat_entities = []
    for eid in entities:
        path = ENTITIES_DIR / f"{eid}.json"
        flat_entities.append(read_json_file(path))

    posts_map = {}
    for entity in flat_entities:
        eid = entity.get("entity_id")
        module = entity.get("module")
        posts = entity.get("posts")
        if not posts:
            continue
        if not posts_map.get(module):
            posts_map[module] = []
        posts_map[module].append({"entity_id": eid, "posts": posts})

    logger.info("Full entity posts list loaded successfully!")
    return posts_map


def build_entities_map(entities):
    logger.info("Loading full entity records from campaign data...")
    flat_entities = []
    for entity in entities:
        path = ENTITIES_DIR / f"{entity}.json"
        flat_entities.append(read_json_file(path))

    entities_map = {}
    for entity in flat_entities:
        module = entity.get("module")

        if entity.get("posts"):
            del entity["posts"]

        if not entities_map.get(module):
            entities_map[module] = [entity]
            continue
        entities_map[module].append(entity)

    logger.info("Full entity records loaded successfully!")
    return entities_map


def generate_updates(gemini_client, entities, truth_log, manifest):
    logger.info("Generating entity updates using Gemini...")
    truth_log = "\n".join(truth_log)
    manifest = build_manifest_index(manifest)
    entities = json.dumps(build_entities_map(entities), indent=2)
    templates_str = json.dumps(KANKA_TEMPLATES, indent=2)
    prompt = f"Entities to update:\n{entities}\n\nTemplates:\n{templates_str}\n\nManifest:\n{manifest}\n\nTruth Log:\n{truth_log}"
    response = run_gemini_generation(gemini_client, prompt, UPDATES_SYSTEM_PROMPT)
    logger.info("Entity updates generated using Gemini successfully!")
    return response


def build_entity_list(results, new_entities):
    logger.info("Building full list of entities requiring updates...")
    update_entities = results.get("updates", [])
    all_entities = []

    if update_entities and isinstance(update_entities, list):
        all_entities.extend(update_entities)

    if new_entities and isinstance(new_entities, list):
        all_entities.extend(new_entities)

    logger.info(f"List built! {len(all_entities)} queue for updates!")
    logger.info("Full list of entities requiring updates built successfully!")
    return all_entities


def post_new_entities(data):
    new_entities = data.get("new", [])
    entity_ids = []
    logger.info("Posting new entities to Kanka...")
    for entity in new_entities:
        name = entity.get("name")
        module = entity.get("type")
        if not name or not module:
            continue
        payload = {"name": name}
        response = kanka_post(module, payload)
        id = response.get("entity_id")
        entity_ids.append(id) if id else None
    logger.info("Posted new entities to Kanka successfully!")
    return entity_ids


def get_session_entities(gemini_client, manifest, truth_log):
    logger.info("Identifying new and existing entity updates...")
    manifest = build_manifest_index(manifest)
    truth_text = "\n".join(truth_log)
    prompt = f"Manifest:\n{manifest}\n\nTruth Log:\n{truth_text}"
    response = run_gemini_generation(gemini_client, prompt, ENTITY_LIST_SYSTEM_PROMPT)
    new_entities = response.get("new", [])
    update_entities = response.get("updates", [])
    logger.info(f"Result: {len(new_entities)} New Entities, {len(update_entities)} Existing Entities")
    logger.info("New and existing entity updates identified successfully!")
    return response


def upload_journal(payloads, curr_journal, replace):
    mode = "PUT" if replace else "POST"
    logger.info(f"Uploading journal to Kanka via {mode}...")
    journal_payload = payloads.get("journal")
    post_payload = payloads.get("post")

    if replace:
        journal_id = curr_journal["id"]
        journal_entity_id = curr_journal["entity_id"]
        post_id = curr_journal["posts"][0]["id"]

        kanka_post(f"journals/{journal_id}", journal_payload, mode="PUT")
        kanka_post(f"entities/{journal_entity_id}/posts/{post_id}", data=post_payload, mode="PUT")
    else:
        journal = kanka_post("journals", journal_payload)
        post_payload["entity_id"] = journal["entity_id"]

        kanka_post(f"entities/{journal["entity_id"]}/posts", data=post_payload)

    logger.info(f"Journal uploaded to Kanka via {mode} Successfully!")


def convert_to_paragraph(data):
    if not data:
        return ""

    else:
        data = [f"<p>{a}</p>" for a in data]
    return "".join(data)


def generate_journal(gemini_client, session_data, curr_truth, prev_truth, manifest):
    logger.info("Generating journal payload for Kanka...")

    logger.info("Building journal payload prompt for gemini...")
    manifest = json.dumps(manifest, indent=2)
    curr_truth_text = "\n".join(curr_truth if curr_truth else [])
    curr_truth_html = convert_to_paragraph(curr_truth)
    prev_truth_text = "\n".join(prev_truth if prev_truth else [])
    prompt = f"Summary Context:\n{manifest}\n\nTruth Log:\n{curr_truth_text}\n\nPrevious Truth Log:\n{prev_truth_text}"
    logger.info("Journal prompt for gemini built successfully!")

    logger.info("Generating session summary and name using gemini...")
    response = run_gemini_generation(gemini_client, prompt, JOURNAL_SYSTEM_PROMPT)
    summary = response.get("summary", None)
    post_name = response.get("name", None)
    logger.info("Built session summary and name using gemini successfully!")

    logger.info("Building Kanka entity payloads for session and post...")
    journal_payload = {
        "name": f"Session {session_data["Session Number"]}",
        "entry": summary,
        "type": "Session Log",
        "date": session_data["Session Date"],
    }
    post_payload = {
        "name": post_name,
        "entry": curr_truth_html,
        "entity_id": "",
    }
    logger.info("Kanka payloads built successfully!")

    logger.info("Journal generated for Kanka successfully!")
    return {"journal": journal_payload, "post": post_payload}


def generate_truth_log(gemini_client, session_file, session_data, manifest, prev_truth_log):
    truth_log_file_name = f"Session {session_data["Session Number"]}.json"
    truth_log_path = TRUTH_LOG_DIR / truth_log_file_name
    try:
        uploaded_file = upload_file_to_gemini(gemini_client, session_file)
        prompt_text = build_truth_log_prompt(session_data, manifest, prev_truth_log)
        curr_truth_log = run_gemini_generation(gemini_client, prompt_text, TRUTH_LOG_SYSTEM_PROMPT, uploaded_file)
        dump_to_file(curr_truth_log, truth_log_path, truth_log_file_name)
        return curr_truth_log
    finally:
        if uploaded_file is not None:
            gemini_client.files.delete(name=uploaded_file.name)
            logger.info("Remote file cleaned up from Gemini!")


def build_truth_log_prompt(session_data, manifest, prev_truth_log):
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


def get_existing_journal(session_data, manifest):
    session_name = f"Session {session_data["Session Number"]}"
    logger.info(f"Searching for {session_name} journal entry...")

    for eid, value in manifest.items():
        if value.get("module") == "journals" and value.get("name") == session_name:
            logger.info(f"{session_name} journal entry found!")
            file_path = ENTITIES_DIR / f"{eid}.json"
            return read_json_file(file_path, "Existing journal")

    logger.info(f"{session_name} journal entry not found!")
    return None


def get_truth_log(session_data, title, current=False):
    logger.info(f"Retrieving {title.lower()}...")
    session_num = session_data.get("Session Number")
    if not current:
        session_num += -1
    file_name = f"Session {session_num}.json"
    file_path = TRUTH_LOG_DIR / file_name
    prev_truth_log = read_json_file(file_path, title)
    return prev_truth_log


def get_session_data():
    logger.info("Collecting current session data...")
    session_data = {}
    while True:
        con.print("Please provide the following information for this session:")
        try:
            con.print(" - Session Number: ", end="", style="menu.key")
            session_num = int(input())
            if session_num < 0 or session_num > len(list(Path(TRUTH_LOG_DIR).glob("*"))) + 1:
                raise Exception()

            con.print(" - Session Date: (E.G 05/11/2026) ", end="", style="menu.key")
            session_date = datetime.strptime(input(), "%d/%m/%y").date()

            session_data = {"Session Number": session_num, "Session Date": session_date}

            build_table(session_data, ["Key", "Value"], "Current Session Settings")
            con.print("Is this information correct? (Blank for yes) ", end="", style="menu.key")
            response = input()
            if not response:
                break

        except Exception as e:
            print(e)
            con.print("Invalid data entered. Please try again", style="warning")
            input("Press enter to continue ")

    logger.info("Current session data collected successfully!")
    return session_data


def run_ingest_pipeline(data):
    gemini_client = data.get("gemini_client")
    con.rule("Session Ingest", style="rule.header")

    try:
        con.rule("Data Retriveal", style="rule.section")
        manifest = get_kanka_data()
        session_data = get_session_data()
        prev_truth_log = get_truth_log(session_data, "Previous session truth log")
        curr_truth_log = get_truth_log(session_data, "Existing session truth log", True)

        use_existing = False
        if curr_truth_log:
            con.print("Would you like to use the existing truth log?: (Blank for yes) ", end="", style="menu.key")
            if not input():
                use_existing = True

        if not use_existing:
            session_file = prompt_for_file()

            con.rule("Truth Log Generation", style="rule.section")
            curr_truth_log = generate_truth_log(gemini_client, session_file, session_data, manifest, prev_truth_log)

        con.rule("Entity Identification", style="rule.section")
        results = get_session_entities(gemini_client, manifest, curr_truth_log)
        new_entities = []
        if results.get("new"):
            new_entities = post_new_entities(results)
            manifest = get_kanka_data()
        entities_to_update = build_entity_list(results, new_entities)

        con.rule("Entity Update Generation", style="rule.section")
        updates_raw = generate_updates(gemini_client, entities_to_update, curr_truth_log, manifest)
        if updates_raw:
            updates, aliases = process_updates(updates_raw, manifest)
            post_updates(updates, aliases)
        else:
            logger.info("No updates to process!")

        con.rule("Post Generation", style="rule.section")
        posts = generate_posts(gemini_client, entities_to_update, curr_truth_log, manifest)
        if posts:
            post_posts(posts)
        else:
            logger.info("No posts to process!")

        con.rule("Journal Generation", style="rule.section")
        curr_journal = get_existing_journal(session_data, manifest)

        use_existing = False
        if curr_journal:
            con.print("Would you like to use the existing journal entry?: (Blank for yes) ", end="", style="menu.key")
            if not input():
                use_existing = True

        if not use_existing:
            journal_payloads = generate_journal(gemini_client, session_data, curr_truth_log, prev_truth_log, manifest)
            curr_journal = upload_journal(journal_payloads, curr_journal, True if curr_journal else False)

    except Exception as e:
        logger.error(f"Failed to complete ingest pipeline: {e}")
        print(traceback.format_exc())
