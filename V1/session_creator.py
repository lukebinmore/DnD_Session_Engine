import json
import logging
import gemini_helper

logger = logging.getLogger("SessionCreator")

SESSION_PROMPT = """You are an expert tabletop scribe and DM assistant for a D&D campaign.

You will receive:
1. A Chronological Play-by-Play Truth Log for the session that just concluded.
2. Context from previous sessions (if available).

Your goal is to synthesize this into structured session notes across 5 specific sections:

1. session_name: A name that suits the theme of the session.
2. ai_ideas_for_session: 3-5 concrete DM prep hooks, lingering questions, complications for the next game or ideas for the next sessions plot.
3. previous_notes_summary: A 1-2 paragraph cinematic recap of the session.
4. session_notes: High-level narrative bullet points highlighting major plot beats, key NPC encounters, and critical party decisions.
5. chronological_history: A polished, readable narrative timeline of what occurred during the session as chronological bullet points.

Return strictly a JSON object with this exact shape:
{
  "session_name": "string",
  "ai_ideas_for_session": ["string", "string"],
  "previous_notes_summary": "string",
  "session_notes": ["string", "string"],
  "chronological_history": ["string", "string"]
}
"""


def synthesize_session_content(gemini_client, truth_log, previous_summary=None):
    """Calls Gemini to convert the Truth Log into a structured dictionary of session sections."""
    user_content = f"""PRIOR CAMPAIGN CONTEXT (Reference Only):
{previous_summary or 'No prior session context available (e.g. Campaign start or Session 1).'}

CURRENT SESSION TRUTH LOG (Active Session):
{truth_log}
"""

    logger.info("Synthesizing session content with Gemini...")
    response = gemini_helper.generate_with_fallback(
        gemini_client=gemini_client,
        contents=user_content,
        config={
            "system_instruction": SESSION_PROMPT,
            "response_mime_type": "application/json",
            "temperature": 0.2,
        },
    )

    # Parse and return as a standard Python dictionary
    data = json.loads(response.text)
    data["general_plot_for_session"] = ""
    return data


def run(
    gemini_client,
    truth_log,
    doc_meta,
    docs_service=None,
    doc_id=None,
    debug_path="/app/session_synthesized_debug.json",
    **kwargs,
):
    """Test harness entrypoint: pulls prior context, synthesizes session notes,

    dumps JSON for inspection, and returns session metadata.
    """
    # 1. Extract previous session recap from doc_meta
    sessions_meta = doc_meta.get("sessions_meta", {})
    latest_session_num = sessions_meta.get("latest_session_num")
    next_session_num = (latest_session_num or 0) + 1
    new_tab_title = f"Session {next_session_num}"

    previous_summary = ""
    if latest_session_num:
        prev_title = f"Session {latest_session_num}"
        sessions_coll = doc_meta.get("collections", {}).get("sessions", {})
        prev_session = sessions_coll.get("items", {}).get(prev_title, {})
        sections_by_key = prev_session.get("sections_by_key", {})
        previous_summary = sections_by_key.get("previous notes summary") or sections_by_key.get("session notes") or ""
        logger.info(f"Found prior context from '{prev_title}' ({len(previous_summary)} chars).")
    else:
        logger.info("No previous session tab detected. Running as initial session.")

    # 2. Synthesize with Gemini
    session_data = synthesize_session_content(
        gemini_client=gemini_client,
        truth_log=truth_log,
        previous_summary=previous_summary,
    )

    # 3. Save JSON for manual verification
    with open(debug_path, "w", encoding="utf-8") as f:
        json.dump(session_data, f, indent=2, ensure_ascii=False)
    logger.info(f"Synthesized session data saved to {debug_path}")

    # Return expected metadata for pipeline log statement
    return {
        "tab_title": new_tab_title,
        "session_num": next_session_num,
        "data": session_data,
    }
