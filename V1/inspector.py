import os
import re
import json
import logging

logger = logging.getLogger("Inspector")

DEBUG_DUMP_PATH = "/app/inspector_debug.json" if os.path.exists("/app") else "./inspector_debug.json"

# Naming patterns for template tabs
TEMPLATE_PATTERNS = {
    "session": re.compile(r"^(?:_)?(?:template[_-])?session(?:[_-]template)?$", re.IGNORECASE),
    "npc": re.compile(r"^(?:_)?(?:template[_-])?npc(?:[_-]template)?$", re.IGNORECASE),
    "location": re.compile(r"^(?:_)?(?:template[_-])?location(?:[_-]template)?$", re.IGNORECASE),
    "faction": re.compile(r"^(?:_)?(?:template[_-])?faction(?:[_-]template)?$", re.IGNORECASE),
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


def save_debug_dump(data, filepath):
    """Writes a clean summary dump of discovered tabs and templates."""
    try:
        clean_dump = {
            "title": data.get("title"),
            "doc_id": data.get("doc_id"),
            "latest_session_num": data.get("latest_session_num"),
            "next_session_num": data.get("next_session_num"),
            "templates_found": list(data.get("templates", {}).keys()),
            "tabs_info": data.get("tabs_info", {}),
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(clean_dump, f, indent=2, ensure_ascii=False)

        logger.info(f"Debug JSON snapshot saved to: {filepath}")
    except Exception as e:
        logger.warning(f"Failed to write inspector debug file: {e}")


def run(docs_service, doc_id):
    """
    Fetches and inspects the Google Doc hierarchy including all nested tabs.
    """
    logger.info(f"Inspecting document structure (Doc ID: {doc_id})...")

    doc = docs_service.documents().get(documentId=doc_id, includeTabsContent=True).execute()

    doc_title = doc.get("title", "Untitled")
    raw_tabs = doc.get("tabs", [])

    collected_tabs = []

    def collect(node_list, parent_name=None):
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
                    "text_length": len(text),
                    "snippet": text[:200].strip() if text else "",
                }
            )

            # Check both locations where child tabs can be placed
            children_in_node = node.get("childTabs", [])
            children_in_props = props.get("childTabs", [])
            sub_tabs = children_in_node or children_in_props

            if sub_tabs:
                collect(sub_tabs, parent_name=title)

    collect(raw_tabs)

    tabs_info = {}
    templates = {}
    session_numbers = []

    for item in collected_tabs:
        title = item["title"]
        tabs_info[title] = {
            "tab_id": item["tab_id"],
            "parent": item["parent"],
            "text_length": item["text_length"],
            "snippet": item["snippet"],
        }

        logger.info(f"-> Discovered: '{title}' (ID: {item['tab_id']}, Parent: {item['parent']})")

        # Check for template tabs
        for tmpl_type, pattern in TEMPLATE_PATTERNS.items():
            if pattern.search(title):
                templates[tmpl_type] = {"tab_id": item["tab_id"], "title": title, "parent": item["parent"]}
                logger.info(f"   [MATCH] Template found: {tmpl_type.upper()} -> '{title}'")

        # Check for existing sessions
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

    doc_metadata = {
        "title": doc_title,
        "doc_id": doc_id,
        "latest_session_num": latest_session_num,
        "next_session_num": next_session_num,
        "templates": templates,
        "tabs_info": tabs_info,
    }

    save_debug_dump(doc_metadata, DEBUG_DUMP_PATH)
    return doc_metadata
