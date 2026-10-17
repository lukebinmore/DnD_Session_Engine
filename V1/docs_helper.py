import logging

logger = logging.getLogger("DocsHelper")


def build_clear_tab_request(tab_id: str, end_index: int) -> list:
    """Builds a request to wipe all content from a tab if it has existing text."""
    # A completely blank tab has end_index <= 2 (just index 0 and a trailing newline \n)
    if end_index and end_index > 2:
        content_range = {"tabId": tab_id, "startIndex": 1, "endIndex": end_index - 1}
        return [
            {"deleteParagraphBullets": {"range": content_range}},
            {"deleteContentRange": {"range": content_range}},
        ]
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
        tag = (sec.get("tag") or "").strip()
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
            if tag:
                heading = f"[{tag}] {heading}"
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
                bullet_ranges.append({"start": list_start, "end": list_end - 1})

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
                bullet_ranges.append({"start": list_start, "end": list_end - 1})

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
    requests.append({"deleteParagraphBullets": {"range": {"tabId": tab_id, "startIndex": 1, "endIndex": current_idx}}})

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


def _extract_document_text(value):
    if isinstance(value, list):
        return "".join(_extract_document_text(item) for item in value)
    if isinstance(value, dict):
        text_run = value.get("textRun")
        if isinstance(text_run, dict):
            return text_run.get("content", "")
        return "".join(_extract_document_text(item) for item in value.values())
    return ""


def _iter_document_tabs(tabs):
    for tab in tabs or []:
        properties = tab.get("tabProperties", {})
        document_tab = tab.get("documentTab", {})
        body = document_tab.get("body", {})
        yield {
            "tab_id": properties.get("tabId"),
            "title": properties.get("title", ""),
            "parent_tab_id": properties.get("parentTabId"),
            "text": _extract_document_text(body.get("content", [])),
        }
        yield from _iter_document_tabs(tab.get("childTabs", []))


def _is_ambiguous_transport_error(error):
    if isinstance(error, OSError):
        return True
    response = getattr(error, "resp", None)
    return getattr(response, "status", None) in {408, 500, 502, 503, 504}


def _reconcile_batch(docs_service, doc_id, requests):
    document = docs_service.documents().get(documentId=doc_id, includeTabsContent=True).execute()
    tabs = list(_iter_document_tabs(document.get("tabs", [])))
    tabs_by_id = {tab["tab_id"]: tab for tab in tabs if tab.get("tab_id")}
    tabs_by_title = {}
    for tab in tabs:
        tabs_by_title.setdefault(tab.get("title", "").casefold(), []).append(tab)

    checks = []
    add_requests = []
    for request in requests:
        insert = request.get("insertText")
        if insert:
            location = insert.get("location", {})
            tab = tabs_by_id.get(location.get("tabId"))
            expected_text = insert.get("text", "")
            checks.append(bool(tab and tab["text"].startswith(expected_text)))

        add_tab = request.get("addDocumentTab")
        if add_tab:
            properties = add_tab.get("tabProperties", {})
            title = str(properties.get("title", ""))
            parent_tab_id = properties.get("parentTabId")
            matching_tabs = [
                tab
                for tab in tabs_by_title.get(title.casefold(), [])
                if parent_tab_id is None or tab.get("parent_tab_id") == parent_tab_id
            ]
            checks.append(bool(matching_tabs))
            add_requests.append((properties, matching_tabs))

    if not checks:
        return "unknown", None
    if all(checks):
        replies = [
            {
                "addDocumentTab": {
                    "tabProperties": {
                        **properties,
                        "tabId": matching_tabs[0].get("tab_id"),
                    }
                }
            }
            for properties, matching_tabs in add_requests
        ]
        return "applied", {"replies": replies}
    if not any(checks):
        return "not_applied", None
    return "mixed", None


def _execute_batch_request(docs_service, doc_id, requests):
    return docs_service.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()


def execute_batch(docs_service, doc_id: str, requests: list):
    """Executes a list of Google Docs API requests in a single atomic batchUpdate.
    If any request in the batch fails, the entire transaction rolls back.
    """
    if not requests:
        logger.debug("Skipping empty Google Docs batch for document '%s'.", doc_id)
        return None

    logger.info("Submitting %s Google Docs request(s) for document '%s'.", len(requests), doc_id)
    try:
        response = _execute_batch_request(docs_service, doc_id, requests)
    except Exception as error:
        if not _is_ambiguous_transport_error(error):
            logger.exception("Google Docs batch update failed for document '%s'.", doc_id)
            raise

        logger.warning(
            "Google Docs batch response was lost for document '%s'; checking whether the batch applied.",
            doc_id,
        )
        try:
            state, reconciled_response = _reconcile_batch(docs_service, doc_id, requests)
        except Exception as reconcile_error:
            raise RuntimeError(
                f"Google Docs batch outcome is unknown for document '{doc_id}'; "
                "could not re-fetch the document to verify it."
            ) from reconcile_error

        if state == "applied":
            logger.warning("Google Docs batch was applied despite the lost response; continuing.")
            response = reconciled_response
        elif state == "not_applied":
            logger.warning("Google Docs batch was not applied; retrying it once.")
            try:
                response = _execute_batch_request(docs_service, doc_id, requests)
            except Exception as retry_error:
                if not _is_ambiguous_transport_error(retry_error):
                    logger.exception("Google Docs batch retry failed for document '%s'.", doc_id)
                    raise
                retry_state, retry_response = _reconcile_batch(docs_service, doc_id, requests)
                if retry_state != "applied":
                    raise RuntimeError(
                        f"Google Docs batch outcome remains {retry_state} after one retry for document '{doc_id}'."
                    ) from retry_error
                logger.warning("Google Docs batch retry was applied despite the lost response; continuing.")
                response = retry_response
        else:
            raise RuntimeError(
                f"Google Docs batch outcome is mixed for document '{doc_id}'; "
                "not retrying to avoid duplicate text or tabs."
            ) from error

    reply_count = len(response.get("replies", [])) if isinstance(response, dict) else 0
    logger.info(
        "Google Docs batch update succeeded for document '%s' (%s reply/replies).",
        doc_id,
        reply_count,
    )
    return response
