import json
import logging
import uuid
import gemini_helper
import docs_helper

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
5. chronological_history: A polished, verbose, readable narrative timeline of what occurred during the session as chronological bullet points.

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


def get_sections_map(sections_list: list) -> dict:
    """Indexes a tab's section list by lowercase heading title for quick lookup."""
    sec_map = {}
    for s in sections_list:
        heading_key = s.get("heading", "").strip().lower()
        sec_map[heading_key] = s.get("content", "")
    return sec_map


def build_current_session_payload(doc_meta, current_num, session_data):
    """Extracts preserved prep from Session N (including any manual date/subtitle),
    and combines it with fresh retrospective notes and title.
    """
    tab_title = f"Session {current_num}"
    sessions_coll = doc_meta.get("sessions", {})

    existing_item = sessions_coll.get("items", {}).get(tab_title, {})
    if not existing_item:
        for title_key, item in sessions_coll.get("items", {}).items():
            if title_key.startswith(f"Session {current_num}"):
                existing_item = item
                break

    if not existing_item:
        raise ValueError(f"Cannot close out '{tab_title}': tab not found in doc_meta['sessions']['items'].")

    tab_id = existing_item.get("tab_id")
    end_index = existing_item.get("end_index", 1)

    if not tab_id:
        raise ValueError(f"Cannot close out '{tab_title}': tabId not found in doc_meta.")

    # 1. Pull preserved prep fields
    sections_map = get_sections_map(existing_item.get("sections", []))
    preserved_date = sections_map.get("date", "")
    preserved_ai_ideas = sections_map.get("ai ideas for session", [])
    preserved_plot = sections_map.get("general plot for session", "")
    preserved_recap = sections_map.get("previous notes summary", "")

    if isinstance(preserved_ai_ideas, str) and preserved_ai_ideas:
        preserved_ai_ideas = [line.strip("- ").strip() for line in preserved_ai_ideas.split("\n") if line.strip()]

    # 2. Build full retrospective title
    session_name = session_data.get("session_name", "").strip()
    full_title = f"Session {current_num}: {session_name}" if session_name else f"Session {current_num}"

    # 3. Assemble sections with TITLE, preserved SUBTITLE, and HEADING_1
    sections = [
        {
            "heading": "TITLE",
            "style": "TITLE",
            "type": "paragraph",
            "content": full_title,
        },
        {
            "heading": "Date",
            "style": "HEADING_1",
            "type": "paragraph",
            "content": preserved_date,
        },
        {
            "heading": "AI Ideas for Session",
            "style": "HEADING_1",
            "type": "bullet_list",
            "content": preserved_ai_ideas,
        },
        {
            "heading": "General Plot for Session",
            "style": "HEADING_1",
            "type": "bullet_list",
            "content": preserved_plot,
        },
        {
            "heading": "Previous Notes Summary",
            "style": "HEADING_1",
            "type": "paragraph",
            "content": preserved_recap,
        },
        {
            "heading": "Session Notes",
            "style": "HEADING_1",
            "type": "bullet_list",
            "content": session_data.get("session_notes", []),
        },
        {
            "heading": "Chronological History",
            "style": "HEADING_1",
            "type": "bullet_list",
            "content": session_data.get("chronological_history", []),
        },
    ]

    return tab_id, end_index, sections


def build_next_session_payload(next_num, session_data):
    """Builds the prep payload for Session N+1 with a simple title,
    an empty slot ready for your manual date entry,
    fresh prep ideas, blank plot, and fresh recap.
    """
    new_tab_id = f"t.session_{next_num}_{uuid.uuid4().hex[:6]}"
    tab_title = f"Session {next_num}"

    sections = [
        {
            "heading": "TITLE",
            "style": "TITLE",
            "type": "paragraph",
            "content": tab_title,
        },
        {
            "heading": "Date",
            "style": "HEADING_1",
            "type": "paragraph",
            "content": "",
        },
        {
            "heading": "AI Ideas for Session",
            "style": "HEADING_1",
            "type": "bullet_list",
            "content": session_data.get("ai_ideas_for_session", []),
        },
        {
            "heading": "General Plot for Session",
            "style": "HEADING_1",
            "type": "bullet_list",
            "content": "",
        },
        {
            "heading": "Previous Notes Summary",
            "style": "HEADING_1",
            "type": "paragraph",
            "content": session_data.get("previous_notes_summary", ""),
        },
    ]

    return new_tab_id, tab_title, sections


def run(gemini_client, truth_log, doc_meta, docs_service=None, doc_id=None, **kwargs):
    """Synthesizes notes and executes an atomic batch update in Google Docs:
    1. Wipes and writes retrospective notes for Session N.
    2. Spawns Session N+1 under the Sessions folder tab.
    3. Populates prep sections in Session N+1.
    """
    sessions_node = doc_meta.get("sessions", {})

    # 1. Determine active and upcoming session numbers
    current_num = doc_meta.get("sessions_meta", {}).get("latest_session_num", 1)
    next_num = doc_meta.get("sessions_meta", {}).get("next_session_num", 2)

    # 2. Extract recap/summary context from the current session tab
    tab_title = f"Session {current_num}"
    current_session = sessions_node.get("items", {}).get(tab_title)

    if not current_session:
        for k, v in sessions_node.get("items", {}).items():
            if k.startswith(f"Session {current_num}"):
                current_session = v
                break

    sections_map = get_sections_map(current_session.get("sections", [])) if current_session else {}

    current_summary_context = sections_map.get("previous notes summary") or sections_map.get("session notes") or ""
    if isinstance(current_summary_context, list):
        current_summary_context = "\n".join(f"- {item}" for item in current_summary_context)

    # 3. Synthesize fresh session content via Gemini
    session_data = synthesize_session_content(
        gemini_client=gemini_client,
        truth_log=truth_log,
        previous_summary=current_summary_context,
    )

    # 4. Build section data structures for both tabs
    current_tab_id, current_end_idx, current_sections = build_current_session_payload(
        doc_meta=doc_meta,
        current_num=current_num,
        session_data=session_data,
    )

    next_tab_id, next_tab_title, next_sections = build_next_session_payload(
        next_num=next_num,
        session_data=session_data,
    )

    # 5. Build API requests using docs_helper
    # --- BATCH 1: Update Session N + Add Tab for Session N+1 ---
    batch1_requests = []

    # 1. Clear & rewrite Session N
    batch1_requests.extend(
        docs_helper.build_clear_tab_request(
            tab_id=current_tab_id,
            end_index=current_end_idx,
        )
    )
    batch1_requests.extend(
        docs_helper.build_tab_content_requests(
            tab_id=current_tab_id,
            sections=current_sections,
        )
    )

    # 2. Add Session N+1 tab under parent folder
    parent_tab_id = sessions_node.get("tab_id")
    batch1_requests.append(
        docs_helper.build_add_tab_request(
            title=next_tab_title,
            parent_tab_id=parent_tab_id,
        )
    )

    if docs_service and doc_id:
        response1 = docs_helper.execute_batch(
            docs_service=docs_service,
            doc_id=doc_id,
            requests=batch1_requests,
        )

        # Extract the server-generated tabId from the addDocumentTab response
        replies = response1.get("replies", [])
        add_tab_reply = next(
            (r["addDocumentTab"] for r in replies if "addDocumentTab" in r),
            None,
        )

        # tabId is nested inside tabProperties
        tab_props = add_tab_reply.get("tabProperties", {}) if add_tab_reply else {}
        new_server_tab_id = tab_props.get("tabId")

        if not new_server_tab_id:
            raise RuntimeError(
                f"Failed to retrieve server tabId for '{next_tab_title}' from batchUpdate response. "
                f"Full reply: {add_tab_reply}"
            )

        # --- BATCH 2: Populate Session N+1 Content ---
        batch2_requests = docs_helper.build_tab_content_requests(
            tab_id=new_server_tab_id,
            sections=next_sections,
        )

        docs_helper.execute_batch(
            docs_service=docs_service,
            doc_id=doc_id,
            requests=batch2_requests,
        )
    else:
        logger.warning("docs_service or doc_id missing; skipped Google Docs update.")

    # Placed at the very end of session_creator.run():
    return {
        "tab_title": f"{tab_title} & {next_tab_title}",
        "current_session_num": current_num,
        "next_session_num": next_num,
        "data": session_data,
    }
