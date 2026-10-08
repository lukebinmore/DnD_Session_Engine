"""
doc_updater.py - Pluggable Google Docs Formatting Engine
Modify this file anytime without rebuilding the Docker container.
Changes take effect on the next scan automatically.
"""

def apply_updates(docs_service, doc_id, extracted_data):
    """
    Applies the structured JSON output from Gemini to the Google Doc.
    Handles session tabs, recaps, DM notes, and entity updates.
    """
    current_tab = extracted_data.get("current_session_tab", "Session Notes")
    next_tab = extracted_data.get("next_session_tab", "")
    notes = extracted_data.get("current_session_detailed_notes", [])
    recap = extracted_data.get("next_session_recap_paragraph", "")
    bullets = extracted_data.get("next_session_dm_bullets", [])
    new_entities = extracted_data.get("new_entities", [])
    updates_to_existing = extracted_data.get("updates_to_existing", [])

    # Fetch document metadata including all tabs
    doc = docs_service.documents().get(documentId=doc_id, includeTabsContent=True).execute()
    existing_tabs = {
        t.get("tabProperties", {}).get("title", "").strip().lower(): t.get("tabProperties", {}).get("tabId")
        for t in doc.get("tabs", [])
    }

    requests = []

    # 1. Structure the Current Session Log
    log_content = f"=== {current_tab} ===\n\n"
    if recap:
        log_content += f"SESSION RECAP (READ-ALOUD):\n{recap}\n\n"
    if bullets:
        log_content += "DM TRACKING NOTES & HOOKS:\n" + "\n".join(f"• {b}" for b in bullets) + "\n\n"
    if notes:
        log_content += "CHRONOLOGICAL LOG:\n" + "\n".join(f"• {n}" for n in notes) + "\n\n"

    # Prepend to the document body
    requests.append({
        "insertText": {
            "location": {"index": 1},
            "text": log_content
        }
    })

    # 2. Append Lore to Existing Entities (if matching headings or tabs exist)
    for update in updates_to_existing:
        target_tab = update.get("tab_name", "")
        heading = update.get("target_heading", "")
        new_lore = update.get("new_notes", "")
        if new_lore:
            requests.append({
                "insertText": {
                    "location": {"index": 1},
                    "text": f"\n[{target_tab} - {heading}]\n{new_lore}\n"
                }
            })

    # Execute all batch updates
    if requests:
        docs_service.documents().batchUpdate(
            documentId=doc_id,
            body={"requests": requests}
        ).execute()

    print(f"Successfully applied updates to Google Doc.")