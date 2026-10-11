import re
import logging

logger = logging.getLogger("Inspector")

TEMPLATE_PATTERNS = {
    "session": re.compile(r"^(?:_)?(?:template[\s_-]*)?session(?:[\s_-]*template)?$", re.IGNORECASE),
    "character": re.compile(r"^(?:_)?(?:template[\s_-]*)?(?:character|npc)(?:[\s_-]*template)?$", re.IGNORECASE),
    "player": re.compile(r"^(?:_)?(?:template[\s_-]*)?player(?:[\s_-]*template)?$", re.IGNORECASE),
    "location": re.compile(r"^(?:_)?(?:template[\s_-]*)?location(?:[\s_-]*template)?$", re.IGNORECASE),
    "group": re.compile(r"^(?:_)?(?:template[\s_-]*)?(?:group|faction)(?:[\s_-]*template)?$", re.IGNORECASE),
}

SESSION_NAME_PATTERN = re.compile(r"^session\s+(\d+)", re.IGNORECASE)


def extract_plain_text(content_elements):
    """Recursively extracts plain text from structural elements of a tab."""
    text_pieces = []
    for element in content_elements:
        if "paragraph" in element:
            for pe in element["paragraph"].get("elements", []):
                if "textRun" in pe:
                    text_pieces.append(pe["textRun"].get("content", ""))
        elif "table" in element:
            for row in element["table"].get("tableRows", []):
                for cell in row.get("tableCells", []):
                    text_pieces.append(extract_plain_text(cell.get("content", [])))
    return "".join(text_pieces)


def run(docs_service, doc_id):
    """
    Fetches and inspects the Google Doc hierarchy including all nested tabs.
    Returns structured campaign metadata for downstream pipeline stages.
    """
    logger.info(f"Inspecting document structure (Doc ID: {doc_id})...")

    doc = docs_service.documents().get(documentId=doc_id, includeTabsContent=True).execute()

    doc_title = doc.get("title", "Untitled")
    raw_tabs = doc.get("tabs", [])

    collected_tabs = []

    def collect(node_list, parent_name=None, depth=0):
        for node in node_list:
            props = node.get("tabProperties", {})
            title = props.get("title", "Untitled").strip()
            tab_id = props.get("tabId")

            doc_tab = node.get("documentTab", {})
            body = doc_tab.get("body", {})
            content = body.get("content", [])
            text = extract_plain_text(content)

            collected_tabs.append(
                {
                    "title": title,
                    "tab_id": tab_id,
                    "parent": parent_name,
                    "depth": depth,
                    "text": text,
                    "text_length": len(text),
                    "raw_content": content,
                }
            )

            children_in_node = node.get("childTabs", [])
            children_in_props = props.get("childTabs", [])
            sub_tabs = children_in_node or children_in_props

            if sub_tabs:
                collect(sub_tabs, parent_name=title, depth=depth + 1)

    collect(raw_tabs)

    tabs_info = {}
    templates = {}
    session_numbers = []

    for item in collected_tabs:
        title = item["title"]
        tabs_info[title] = {
            "tab_id": item["tab_id"],
            "parent": item["parent"],
            "depth": item["depth"],
            "text_length": item["text_length"],
            "full_text": item["text"].strip(),
        }

        # Match template tabs
        for tmpl_type, pattern in TEMPLATE_PATTERNS.items():
            if pattern.search(title):
                templates[tmpl_type] = {
                    "tab_id": item["tab_id"],
                    "title": title,
                    "parent": item["parent"],
                    "content": item["raw_content"],
                }

        # Track session numbers
        session_match = SESSION_NAME_PATTERN.match(title)
        if session_match:
            try:
                num = int(session_match.group(1))
                session_numbers.append(num)
            except ValueError:
                pass

    session_numbers.sort()
    latest_session_num = session_numbers[-1] if session_numbers else 0
    next_session_num = latest_session_num + 1

    # Concise operational log summary
    tmpl_list = ", ".join(templates.keys()) if templates else "none"
    logger.info(
        f"Document '{doc_title}' parsed: {len(tabs_info)} tabs, "
        f"templates found: [{tmpl_list}], "
        f"sessions: {len(session_numbers)} (Next: Session {next_session_num})"
    )

    return {
        "title": doc_title,
        "doc_id": doc_id,
        "all_session_numbers": session_numbers,
        "latest_session_num": latest_session_num,
        "next_session_num": next_session_num,
        "templates": templates,
        "tabs_info": tabs_info,
    }
