import json
import logging
import re
import gemini_helper
import docs_helper

logger = logging.getLogger("SessionCreator")
SESSION_TITLE_PATTERN = re.compile(r"^Session\s+(\d+)\b", re.IGNORECASE)

SESSION_PROMPT = """You are an expert tabletop scribe and DM assistant for a D&D campaign.

You will receive:
1. A Chronological Play-by-Play Truth Log for the session that just concluded.
2. Context from previous sessions (if available).

Your goal is to synthesize this into structured session notes across 5 specific sections:

1. session_name: A name that suits the theme of the session.
2. ai_ideas_for_session: 3-5 concrete DM prep hooks, lingering questions, complications for the next game or ideas for the next sessions plot.
3. previous_notes_summary: A 1-2 paragraph cinematic recap of the session.
4. session_notes: A compact, cumulative campaign-state summary for continuity in future sessions.
5. chronological_history: A polished, verbose, readable narrative timeline of what occurred during the session as chronological bullet points.

For session_notes, carry forward relevant facts from the prior session notes and update them using only this
session's Truth Log. Preserve ongoing locations, party goals and whereabouts, important relationships, active
threats, unresolved mysteries, and other state needed for continuity. Update or remove facts that this session
changes or resolves. Keep it bounded to roughly 500 words; this is a current-state reference, not a second
chronological history. Do not present prior events as if they happened in the current session.

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
    logger.info("Session content synthesized and parsed successfully.")
    return data


def get_sections_map(sections_list: list) -> dict:
    """Indexes a tab's section list by lowercase heading title for quick lookup."""
    sec_map = {}
    for s in sections_list:
        heading_key = s.get("heading", "").strip().lower()
        sec_map[heading_key] = s.get("content", "")
    return sec_map


def _summary_text(content):
    if isinstance(content, list):
        return "\n".join(f"- {item}" for item in content if str(item).strip())
    if isinstance(content, dict):
        return "\n".join(f"- {key}: {value}" for key, value in content.items() if str(value).strip())
    return str(content or "").strip()


def get_previous_session_summary(doc_meta, current_num):
    """Returns Session Notes from the closest existing session before current_num."""
    sessions_node = doc_meta.get("sessions", {})
    earlier_numbers = []
    for title in sessions_node.get("items", {}):
        match = SESSION_TITLE_PATTERN.match(title)
        if match:
            number = int(match.group(1))
            if number < current_num:
                earlier_numbers.append(number)

    if not earlier_numbers:
        return ""

    previous_num = max(earlier_numbers)
    _, previous_session = find_session_item(sessions_node, previous_num)
    previous_sections = get_sections_map(previous_session.get("sections", [])) if previous_session else {}
    summary = previous_sections.get("session notes") or previous_sections.get("previous notes summary", "")
    return _summary_text(summary)


def find_session_item(sessions_node, session_num):
    """Finds a session tab by its numeric prefix, avoiding partial matches like 1/10."""
    for title, item in sessions_node.get("items", {}).items():
        match = SESSION_TITLE_PATTERN.match(title)
        if match and int(match.group(1)) == session_num:
            return title, item
    return None, None


def build_session_payload(title, existing_item=None, content_overrides=None, include_retrospective=False):
    """Builds the standard session sections, preserving existing content unless overridden."""
    existing_sections = get_sections_map((existing_item or {}).get("sections", []))
    content = {
        "date": existing_sections.get("date", ""),
        "ai_ideas": existing_sections.get("ai ideas for session", []),
        "general_plot": existing_sections.get("general plot for session", ""),
        "previous_summary": existing_sections.get("previous notes summary", ""),
        "session_notes": existing_sections.get("session notes", []),
        "chronological_history": existing_sections.get("chronological history", []),
    }
    content.update(content_overrides or {})

    sections = [
        {"heading": "TITLE", "style": "TITLE", "type": "paragraph", "content": title},
        {"heading": "Date", "style": "HEADING_1", "type": "paragraph", "content": content["date"]},
        {
            "heading": "AI Ideas for Session",
            "style": "HEADING_1",
            "type": "bullet_list",
            "content": content["ai_ideas"],
        },
        {
            "heading": "General Plot for Session",
            "style": "HEADING_1",
            "type": "bullet_list",
            "content": content["general_plot"],
        },
        {
            "heading": "Previous Notes Summary",
            "style": "HEADING_1",
            "type": "paragraph",
            "content": content["previous_summary"],
        },
    ]

    if include_retrospective:
        sections.extend(
            [
                {
                    "heading": "Session Notes",
                    "style": "HEADING_1",
                    "type": "bullet_list",
                    "content": content["session_notes"],
                },
                {
                    "heading": "Chronological History",
                    "style": "HEADING_1",
                    "type": "bullet_list",
                    "content": content["chronological_history"],
                },
            ]
        )

    return sections


def build_current_session_payload(doc_meta, current_num, session_data):
    """Builds the completed-session payload while retaining existing prep fields."""
    tab_title, existing_item = find_session_item(doc_meta.get("sessions", {}), current_num)
    if not existing_item:
        raise ValueError(f"Cannot close out 'Session {current_num}': tab not found in doc_meta['sessions']['items'].")

    tab_id = existing_item.get("tab_id")
    if not tab_id:
        raise ValueError(f"Cannot close out '{tab_title}': tabId not found in doc_meta.")

    session_name = session_data.get("session_name", "").strip()
    title = f"Session {current_num}: {session_name}" if session_name else f"Session {current_num}"
    sections = build_session_payload(
        title=title,
        existing_item=existing_item,
        content_overrides={
            "session_notes": session_data.get("session_notes", []),
            "chronological_history": session_data.get("chronological_history", []),
        },
        include_retrospective=True,
    )

    return tab_id, existing_item.get("end_index", 1), sections


def build_next_session_payload(doc_meta, next_num, session_data):
    """Builds prep for the next session, reusing its tab and preserving manual fields if present."""
    tab_title, existing_item = find_session_item(doc_meta.get("sessions", {}), next_num)
    tab_title = tab_title or f"Session {next_num}"
    existing_sections = get_sections_map((existing_item or {}).get("sections", []))

    tab_id = existing_item.get("tab_id") if existing_item else None
    if existing_item and not tab_id:
        raise ValueError(f"Cannot update '{tab_title}': tabId not found in doc_meta.")

    title = existing_sections.get("title") or tab_title
    sections = build_session_payload(
        title=title,
        existing_item=existing_item,
        content_overrides={
            "ai_ideas": session_data.get("ai_ideas_for_session", []),
            "previous_summary": session_data.get("previous_notes_summary", ""),
        },
        include_retrospective=bool(
            existing_sections.get("session notes") or existing_sections.get("chronological history")
        ),
    )

    end_index = existing_item.get("end_index", 1) if existing_item else None
    return tab_id, end_index, tab_title, sections


def run(gemini_client, truth_log, doc_meta, docs_service=None, doc_id=None, previous_summary=None, **kwargs):
    """Synthesizes notes and executes an atomic batch update in Google Docs:
    1. Wipes and writes retrospective notes for Session N.
    2. Updates Session N+1 if it exists, otherwise creates it.
    """
    sessions_node = doc_meta.get("sessions", {})

    # 1. Determine active and upcoming session numbers
    current_num = doc_meta.get("sessions_meta", {}).get("latest_session_num", 1)
    next_num = doc_meta.get("sessions_meta", {}).get("next_session_num", 2)
    current_tab_title, _ = find_session_item(sessions_node, current_num)
    current_tab_title = current_tab_title or f"Session {current_num}"
    logger.info(
        "Preparing session update: Session %s is current; Session %s is next.",
        current_num,
        next_num,
    )

    # 2. Use the previous session's rolling notes as continuity context.
    if previous_summary is None:
        previous_summary = get_previous_session_summary(doc_meta, current_num)
    logger.info(
        "Using %s characters of previous-session context for Session %s.",
        len(previous_summary),
        current_num,
    )

    # 3. Synthesize fresh session content via Gemini
    session_data = synthesize_session_content(
        gemini_client=gemini_client,
        truth_log=truth_log,
        previous_summary=previous_summary,
    )

    # 4. Build section data structures for both tabs
    current_tab_id, current_end_idx, current_sections = build_current_session_payload(
        doc_meta=doc_meta,
        current_num=current_num,
        session_data=session_data,
    )

    next_tab_id, next_end_idx, next_tab_title, next_sections = build_next_session_payload(
        doc_meta=doc_meta,
        next_num=next_num,
        session_data=session_data,
    )
    if next_tab_id:
        logger.info("Found next session tab '%s'; it will be updated.", next_tab_title)
    else:
        logger.info("Next session tab '%s' does not exist; it will be created.", next_tab_title)

    # 5. Build API requests using docs_helper
    # --- BATCH 1: Update Session N and update or add Session N+1 ---
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

    if next_tab_id:
        batch1_requests.extend(
            docs_helper.build_clear_tab_request(
                tab_id=next_tab_id,
                end_index=next_end_idx,
            )
        )
        batch1_requests.extend(
            docs_helper.build_tab_content_requests(
                tab_id=next_tab_id,
                sections=next_sections,
            )
        )
    else:
        parent_tab_id = sessions_node.get("tab_id")
        batch1_requests.append(
            docs_helper.build_add_tab_request(
                title=next_tab_title,
                parent_tab_id=parent_tab_id,
            )
        )

    if docs_service and doc_id:
        logger.info("Submitting %s Google Docs request(s) for the session update.", len(batch1_requests))
        response = docs_helper.execute_batch(
            docs_service=docs_service,
            doc_id=doc_id,
            requests=batch1_requests,
        )

        if not next_tab_id:
            # Google Docs assigns the tabId when the tab is created.
            replies = response.get("replies", [])
            add_tab_reply = next(
                (r["addDocumentTab"] for r in replies if "addDocumentTab" in r),
                None,
            )
            tab_props = add_tab_reply.get("tabProperties", {}) if add_tab_reply else {}
            new_server_tab_id = tab_props.get("tabId")

            if not new_server_tab_id:
                raise RuntimeError(
                    f"Failed to retrieve server tabId for '{next_tab_title}' from batchUpdate response. "
                    f"Full reply: {add_tab_reply}"
                )
            logger.info("Created next-session tab '%s'; writing its content.", next_tab_title)

            batch2_requests = docs_helper.build_tab_content_requests(
                tab_id=new_server_tab_id,
                sections=next_sections,
            )
            docs_helper.execute_batch(
                docs_service=docs_service,
                doc_id=doc_id,
                requests=batch2_requests,
            )
        logger.info(
            "Google Docs update complete for Session %s and '%s'.",
            current_num,
            next_tab_title,
        )
    else:
        logger.warning("docs_service or doc_id missing; skipped Google Docs update.")

    # Placed at the very end of session_creator.run():
    return {
        "tab_title": f"{current_tab_title} & {next_tab_title}",
        "current_session_num": current_num,
        "next_session_num": next_num,
        "data": session_data,
    }
