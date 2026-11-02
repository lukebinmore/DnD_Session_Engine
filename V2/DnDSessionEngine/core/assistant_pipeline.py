from DnDSessionEngine.core.theme import con
from DnDSessionEngine.core.config import ENTITIES_DIR
from DnDSessionEngine.core.file_manager import read_json_file
from DnDSessionEngine.core.local_llm import run_local_generation
from DnDSessionEngine.core.kanka import get_kanka_data
from pathlib import Path
import json
import re
import logging

logger = logging.getLogger(__name__)

ASSISTANT_SYSTEM_PROMPT = """You are an experienced tabletop co-DM assisting during a live game session.
Your role is to give natural, immediate, and helpful answers about the campaign world using the provided notes.

Rules:
- Speak naturally and informatively, as if briefing the DM at the table.
- Speak about characters, places, and lore as real campaign elements, never as data structures, templates, or files.
- Use natural inference: full names, titles, and roles are found directly inside character names and descriptions (e.g. "Greg Flaggen" is Greg with the last name Flaggen).
- Never discuss the underlying data files, IDs, manifests, or JSON structure. Never say "according to the entity data" or "the context does not include".
- If counting or listing, state the number and names directly.
- If a character or place is asked about, provide a relavent description based on the information available.
- If something is completely unknown, simply give what is known or say in one short sentence that the details haven't been written yet.

Examples of desired tone:
Q: How many factions are there?
A: There are two main factions: the Iron Syndicate and the Silver Dawn.

Q: Who is Varis?
A: Varis is an elven scout allied with the party, currently tracking movements near the old ruins.
"""

TRIAGE_PROMPT = """You are a campaign index router.
Analyze the user's query against the provided manifest index and return ONLY a JSON array containing the integer entity_ids whose detailed files are strictly required to answer the query.

Rules:
- For specific entities mentioned or referred to, return their IDs (maximum 3).
- For broad questions (e.g. counting total characters or locations, listing all factions, or queries that can be answered using the information in the manifest), return [] because no individual deep files need loading.
- If the query asks for information that isn't identifyable from the manifest, return all of the journal entity_id's.
- Output ONLY the raw JSON array. Do NOT include markdown code blocks, reasoning, or commentary.
Example: [10108738, 10108739] or []"""


def run_prompt(model_ob, query, matching_ids, manifest):
    prompt = build_assistant_prompt(query, matching_ids, manifest)
    run_local_generation(model_ob, prompt, temperature=0.3, system_prompt=ASSISTANT_SYSTEM_PROMPT, output=True)
    print()


def build_assistant_prompt(query, matching_ids, manifest):
    manifest_index = build_manifest_index(manifest)
    entity_context = build_entity_contexts(matching_ids)

    return f"Campaign Overview:\n{manifest_index}\n\nDetailed Entity Context:\n{entity_context}\n\nQuestion:\n{query}"


def build_entity_contexts(entity_ids):
    if not entity_ids:
        return "No speicific entity files requested."

    context_blocks = []
    entities_dir = Path(ENTITIES_DIR)

    for eid in entity_ids:
        file_path = entities_dir / f"{eid}.json"
        if not file_path.exists():
            logger.warning(f"Entity file not found: {eid}")
            continue

        try:
            data = read_json_file(file_path)
            context_blocks.append(f"--- Record: {data.get('name')} ---\n" f"{json.dumps(data, indent=2)}\n")
        except Exception as e:
            logger.warning(f"Failed to read entity file {eid}: {e}")

    return "\n".join(context_blocks) if context_blocks else "No entity files could be loaded."


def run_triage(model_ob, query, manifest):
    prompt = build_triage_prompt(query, manifest)
    raw_result = run_local_generation(model_ob, prompt, system_prompt=TRIAGE_PROMPT)
    match = re.search(r"\[.*?\]", raw_result, re.DOTALL)
    if not match:
        logger.warning(f"Triage did not return a valid list: {raw_result}")
        return None

    try:
        parsed = json.loads(match.group(0))
        if isinstance(parsed, list):
            return [int(x) for x in parsed if str(x).isdigit()]
    except Exception as e:
        logger.warning(f"Failed to parse triage json array: {e}")
        return None

    return []


def build_triage_prompt(query, manifest):
    manifest_index = build_manifest_index(manifest)
    prompt = f"Query context:\n\nManifest Index:\n{manifest_index}\n\nQuery:\n'{query}'"
    return prompt


def build_manifest_index(manifest):
    entries = manifest.get("entities", [])
    index_lines = []

    for ent in entries:
        ent_id = ent.get("entity_id")
        module = ent.get("module")
        name = ent.get("name", "").strip()
        summary = ent.get("summary") or ""

        if not name:
            continue

        clean_summary = summary.replace("\n", " ").strip()
        index_lines.append(f"- ID: {ent_id} | Module: {module} | Name: {name} | Summary: {clean_summary}")

    manifest_index = "\n".join(index_lines)
    return manifest_index


def run_assistant_pipeline(data):
    llm_model = data.get("llm_model")

    con.rule("AI Campaign Assistant Setup", style="rule.header")
    con.rule("Kanka Data Retrieval", style="rule.section")
    manifest = get_kanka_data()

    con.clear()
    con.rule("AI Campaign Assistant", style="rule.header")
    while True:
        con.rule("New Query", style="rule.section")
        con.print("What is your question?: (Blank to exit) ", end="", style="menu.key")
        user_query = input()
        if not user_query:
            break

        con.rule("AI Response", style="rule.dim")
        matched_ids = run_triage(llm_model, user_query, manifest)
        if matched_ids is None:
            continue
        run_prompt(llm_model, user_query, matched_ids, manifest)
