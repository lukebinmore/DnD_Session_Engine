import logging

logger = logging.getLogger("DocsHelper")


def build_clear_tab_request(tab_id: str, end_index: int) -> list:
    """Builds a request to wipe all content from a tab if it has existing text."""
    # A completely blank tab has end_index <= 2 (just index 0 and a trailing newline \n)
    if end_index and end_index > 2:
        return [{"deleteContentRange": {"range": {"tabId": tab_id, "startIndex": 1, "endIndex": end_index - 1}}}]
    return []


def build_tab_content_requests(tab_id: str, sections: list) -> list:
    """Builds insertion, heading style, and bullet list requests for a tab.
    Does NOT execute the API call; returns list[dict].
    """
    full_text = ""
    style_ranges = []  # [{"start": int, "end": int, "style": str}]
    bullet_ranges = []  # [{"start": int, "end": int}]

    current_idx = 1  # Google Docs body index starts at 1

    for sec in sections:
        heading = (sec.get("heading") or "").strip()
        style = sec.get("style", "HEADING_1").upper()
        sec_type = sec.get("type", "paragraph")
        content = sec.get("content")

        # -------------------------------------------------------------
        # 1. SPECIAL CASE: Document Title
        # -------------------------------------------------------------
        if style == "TITLE":
            # The title text is in content (e.g. "Session 1"), falling back to heading
            title_text = str(content).strip() if content else (heading if heading != "TITLE" else "")
            if title_text:
                line = f"{title_text}\n"
                start = current_idx
                end = current_idx + len(line)
                style_ranges.append({"start": start, "end": end, "style": "TITLE"})
                full_text += line
                current_idx = end
            continue

        # -------------------------------------------------------------
        # 2. Standard Heading line (HEADING_1, etc.)
        # -------------------------------------------------------------
        if heading:
            line = f"{heading}\n"
            start = current_idx
            end = current_idx + len(line)
            style_ranges.append({"start": start, "end": end, "style": style})
            full_text += line
            current_idx = end

        # -------------------------------------------------------------
        # 3. Body Content
        # -------------------------------------------------------------
        if sec_type == "key_value_list":
            if isinstance(content, dict):
                items = [f"{k}: {v}".strip() for k, v in content.items()]
            else:
                items = []

            if items:
                list_start = current_idx
                for item in items:
                    item_line = f"{item}\n"
                    full_text += item_line
                    current_idx += len(item_line)
                list_end = current_idx

                style_ranges.append({"start": list_start, "end": list_end, "style": "NORMAL_TEXT"})
                bullet_ranges.append({"start": list_start, "end": list_end})

        elif sec_type == "bullet_list":
            if isinstance(content, str):
                items = [line.strip("- ").strip() for line in content.split("\n") if line.strip()]
            elif isinstance(content, list):
                items = [str(item).strip() for item in content if str(item).strip()]
            else:
                items = []

            if items:
                list_start = current_idx
                for item in items:
                    item_line = f"{item}\n"
                    full_text += item_line
                    current_idx += len(item_line)
                list_end = current_idx

                style_ranges.append({"start": list_start, "end": list_end, "style": "NORMAL_TEXT"})
                bullet_ranges.append({"start": list_start, "end": list_end})

        elif sec_type == "paragraph":
            text_str = str(content).strip() if content else ""
            if text_str:
                para_line = f"{text_str}\n"
                start = current_idx
                end = current_idx + len(para_line)
                style_ranges.append({"start": start, "end": end, "style": "NORMAL_TEXT"})
                full_text += para_line
                current_idx = end

    if not full_text:
        return []

    # 4. Assemble API operations in order
    requests = []

    # A: Insert all text at index 1
    requests.append({"insertText": {"location": {"tabId": tab_id, "index": 1}, "text": full_text}})

    total_doc_end = 1 + len(full_text)

    # B: Apply styles (TITLE, HEADING_1, NORMAL_TEXT)
    for r in style_ranges:
        end_idx = min(r["end"], total_doc_end - 1)
        if end_idx > r["start"]:
            requests.append(
                {
                    "updateParagraphStyle": {
                        "range": {"tabId": tab_id, "startIndex": r["start"], "endIndex": r["end"]},
                        "paragraphStyle": {"namedStyleType": r["style"]},
                        "fields": "namedStyleType",
                    }
                }
            )

    # C: Apply bullet points
    for br in bullet_ranges:
        requests.append(
            {
                "createParagraphBullets": {
                    "range": {"tabId": tab_id, "startIndex": br["start"], "endIndex": br["end"]},
                    "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE",
                }
            }
        )

    return requests


def build_add_tab_request(title: str, parent_tab_id: str = None) -> dict:
    """Builds a request to create a new tab in the document.
    Google Docs generates the tabId on the server.
    """
    tab_props = {"title": title}
    if parent_tab_id:
        tab_props["parentTabId"] = parent_tab_id

    return {"addDocumentTab": {"tabProperties": tab_props}}


def execute_batch(docs_service, doc_id: str, requests: list):
    """Executes a list of Google Docs API requests in a single atomic batchUpdate.
    If any request in the batch fails, the entire transaction rolls back.
    """
    if not requests:
        return None

    return docs_service.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()
