import re
import json
import logging

logger = logging.getLogger("Inspector")

SESSION_NAME_PATTERN = re.compile(r"^Session\s+(\d+)", re.IGNORECASE)
TEMPLATE_NAME_PATTERN = re.compile(r"template", re.IGNORECASE)
TAG_PATTERN = re.compile(r"\{\{([^}]+)\}\}")
BRACKET_TAG_PATTERN = re.compile(r"^\[(.*?)\]\s*(.*)$")
TEMPLATE_HEADING_PATTERN = re.compile(r"^\[(.*?)\]\s*(.*?)(?::)?(?:\s*\((.*?)\))?$")
KV_ITEM_PATTERN = re.compile(r"^(?:-\s*)?([^:]+?)\s*:\s*\((.*?)\)\s*$")
ENTITY_KV_PATTERN = re.compile(r"^(?:[-*•]\s*)?([^:]+?)\s*:\s*(.*)$")


def parse_entity_kv_item(line_text: str) -> dict | None:
    """Parses a bullet line into a key/value pair if it matches 'Key: Value' syntax."""
    clean_line = line_text.replace("\xa0", " ").strip()
    match = ENTITY_KV_PATTERN.match(clean_line)
    if not match:
        return None

    key = match.group(1).strip()
    val = match.group(2).strip()

    return {"key": key, "value": val}


def parse_kv_item(bullet_text: str) -> dict | None:
    # Replace non-breaking spaces (\xa0) with standard spaces
    clean_line = bullet_text.replace("\xa0", " ").strip()

    match = KV_ITEM_PATTERN.match(clean_line)
    if not match:
        return None

    item_heading = match.group(1).strip()
    raw_paren = match.group(2) or ""

    contract = parse_contract_parts(raw_paren)

    return {
        "heading": item_heading,
        "mode": contract["mode"],
        "type": contract["type"],
        "prompt": contract["prompt"],
    }


def parse_contract_parts(raw_paren: str) -> dict:
    """Splits '(Mode: Type: Prompt)' into mode, type, and prompt."""
    if not raw_paren:
        return {"mode": "Append", "type": "Paragraph", "prompt": ""}

    cleaned = raw_paren.strip()

    # Case 1: Standalone directive without colons like '(Don’t Change)'
    if ":" not in cleaned:
        return {"mode": cleaned, "type": "Immutable", "prompt": ""}

    # Case 2: Split by ':' into up to 3 pieces: [Mode, Type, Prompt]
    parts = [p.strip() for p in cleaned.split(":", 2)]

    mode = parts[0] if len(parts) > 0 and parts[0] else "Append"
    data_type = parts[1] if len(parts) > 1 and parts[1] else "Paragraph"
    prompt = parts[2] if len(parts) > 2 else ""

    return {"mode": mode, "type": data_type, "prompt": prompt}


def parse_template_sections(content: list) -> list:
    """Parses raw Google Docs elements from a template tab into blueprint sections."""
    sections = []
    current_sec = None

    for elem in content:
        p = elem.get("paragraph")
        if not p:
            continue

        style_type = p.get("paragraphStyle", {}).get("namedStyleType", "NORMAL_TEXT")
        is_bullet = "bullet" in p

        # Extract the plain text from the paragraph
        raw_text = "".join(pe.get("textRun", {}).get("content", "") for pe in p.get("elements", []))
        cleaned_text = raw_text.strip()
        if not cleaned_text:
            continue

        # Skip document title at the very top (e.g., "Character Name")
        if style_type in ["TITLE", "SUBTITLE"] and not sections:
            continue

        # ------------------------------------------------------------------
        # 1. HEADING: Starts a new section
        # ------------------------------------------------------------------
        if style_type.startswith("HEADING_"):
            if current_sec:
                sections.append(current_sec)

            tag = None
            heading_title = cleaned_text
            raw_paren = ""

            match = TEMPLATE_HEADING_PATTERN.match(cleaned_text)
            if match:
                tag = match.group(1).strip()
                heading_title = match.group(2).strip()
                raw_paren = match.group(3) or ""

            contract = parse_contract_parts(raw_paren)

            # Build the base section
            current_sec = {
                "heading": heading_title,
                "tag": tag,
                "style": style_type,
                "type": contract["type"],
                "mode": contract["mode"],
                "prompt": contract["prompt"],
            }

            # If it's a KeyValueList, initialize the 'values' container
            if contract["type"].lower() == "keyvaluelist":
                current_sec["values"] = []

        # ------------------------------------------------------------------
        # 2. BODY CONTENT: Collect items if we're inside a KeyValueList
        # ------------------------------------------------------------------
        else:
            if not current_sec:
                continue

            if current_sec.get("type", "").lower() == "keyvaluelist" and is_bullet:
                item_data = parse_kv_item(cleaned_text)
                if item_data:
                    current_sec["values"].append(item_data)

    # Don't forget the last section
    if current_sec:
        sections.append(current_sec)

    return sections


def parse_tab_sections(content: list) -> list:
    """Parses raw Google Docs elements into structured sections."""
    sections = []
    current_sec = None

    for elem in content:
        p = elem.get("paragraph")
        if not p:
            continue

        style_type = p.get("paragraphStyle", {}).get("namedStyleType", "NORMAL_TEXT")
        is_bullet = "bullet" in p

        # Extract text runs from paragraph
        raw_text = "".join(pe.get("textRun", {}).get("content", "") for pe in p.get("elements", []))
        cleaned_text = raw_text.strip()
        if not cleaned_text:
            continue

        # Check for heading triggers (only if not a bullet)
        if (style_type.startswith("HEADING_") or style_type in ["TITLE", "SUBTITLE"]) and not is_bullet:
            if current_sec:
                sections.append(current_sec)

            # If it's the document TITLE, store heading as "TITLE" and text as content
            if style_type == "TITLE":
                current_sec = {
                    "heading": "TITLE",
                    "tag": None,
                    "style": style_type,
                    "type": "paragraph",
                    "content": cleaned_text,
                }
                continue

            # Check for [tag] prefix: e.g. "[f2a] Personality"
            tag_match = BRACKET_TAG_PATTERN.match(cleaned_text)
            if tag_match:
                tag = tag_match.group(1).strip()
                heading_title = tag_match.group(2).strip()
            else:
                tag = None
                heading_title = cleaned_text

            current_sec = {
                "heading": heading_title,
                "tag": tag,
                "style": style_type,
                "type": "paragraph",
                "content": "",
            }
        else:
            # If body text appears before any heading, assign an initial Overview section
            if not current_sec:
                current_sec = {
                    "heading": "Overview",
                    "tag": None,
                    "style": "HEADING_1",
                    "type": "paragraph",
                    "content": "",
                }

            if is_bullet:
                # Details is the template's key-value section; narrative bullets may contain colons.
                is_details_section = current_sec["heading"].strip().rstrip(":").casefold() == "details"
                kv_item = parse_entity_kv_item(cleaned_text) if is_details_section else None
                if kv_item:
                    current_sec["type"] = "key_value_list"
                    if not isinstance(current_sec["content"], dict):
                        current_sec["content"] = {}
                    current_sec["content"][kv_item["key"]] = kv_item["value"]
                else:
                    current_sec["type"] = "bullet_list"
                    if not isinstance(current_sec["content"], list):
                        current_sec["content"] = [current_sec["content"]] if current_sec["content"] else []
                    current_sec["content"].append(cleaned_text)
            else:
                if isinstance(current_sec["content"], list):
                    current_sec["content"].append(cleaned_text)
                elif current_sec["content"]:
                    current_sec["content"] += "\n" + cleaned_text
                else:
                    current_sec["content"] = cleaned_text

    if current_sec:
        sections.append(current_sec)

    return sections


def extract_tab_info(tab_dict: dict) -> dict:
    """Extracts essential properties from a single Google Docs tab node."""
    props = tab_dict.get("tabProperties", {})
    title = props.get("title", "Untitled").strip()
    tab_id = props.get("tabId")

    doc_tab = tab_dict.get("documentTab", {})
    body = doc_tab.get("body", {})
    content = body.get("content", [])

    end_index = content[-1].get("endIndex", 1) if content else 1

    if "Template" in title:
        sections = parse_template_sections(content)
    else:
        sections = parse_tab_sections(content)

    return {"title": title, "tab_id": tab_id, "end_index": end_index, "sections": sections}


def parse_hierarchy(raw_tabs: list, doc_title: str, audio_file_name: str) -> dict:
    campaign_node = {}
    collections_node = {"items": {}}
    sessions_node = {"items": {}}
    other_tabs = {}

    entities = []

    for root_tab in raw_tabs:
        root_info = extract_tab_info(root_tab)
        root_title = root_info["title"]
        root_title_lower = root_title.lower()
        root_children = root_tab.get("childTabs", [])

        # ----------------------------------------------------------
        # 1. COLLECTIONS BRANCH (Categories -> Entities)
        # ----------------------------------------------------------
        if root_title_lower == "collections":
            collections_node = root_info
            collections_node["items"] = {}

            for cat_tab in root_children:
                cat_info = extract_tab_info(cat_tab)
                cat_title = cat_info["title"]
                cat_entities = cat_tab.get("childTabs", [])

                cat_info["items"] = {}
                for entity_tab in cat_entities:
                    ent_info = extract_tab_info(entity_tab)
                    if "Template" in ent_info["title"]:
                        cat_info["template"] = ent_info
                    else:
                        cat_info["items"][ent_info["title"]] = ent_info
                        entities.append(ent_info["title"])

                collections_node["items"][cat_title] = cat_info

        # ----------------------------------------------------------
        # 2. SESSIONS BRANCH (Sessions -> Session Tabs)
        # ----------------------------------------------------------
        elif root_title_lower == "sessions":
            sessions_node = root_info
            sessions_node["items"] = {}

            for session_tab in root_children:
                s_info = extract_tab_info(session_tab)
                sessions_node["items"][s_info["title"]] = s_info

        # ----------------------------------------------------------
        # 3. CAMPAIGN / WORLD INFO BRANCH
        # ----------------------------------------------------------
        elif root_title_lower == doc_title.lower() or not campaign_node:
            campaign_node = root_info
            campaign_node["items"] = {}

            for sub_tab in root_children:
                sub_info = extract_tab_info(sub_tab)
                campaign_node["items"][sub_info["title"]] = sub_info

        # ----------------------------------------------------------
        # 4. ANYTHING ELSE
        # ----------------------------------------------------------
        else:
            other_tabs[root_title] = root_info

    # Calculate session numbers cleanly from the sessions branch
    session_numbers = []
    for s_title in sessions_node["items"].keys():
        match = SESSION_NAME_PATTERN.match(s_title)
        if match:
            try:
                session_numbers.append(int(match.group(1)))
            except ValueError:
                pass

    session_numbers.sort()
    latest_num = 0
    match = re.search(r"\[Session\s+(\d+)\]", audio_file_name, re.IGNORECASE)
    if match:
        latest_num = int(match.group(1))
    else:
        latest_num = session_numbers[-1] if session_numbers else 0

    return {
        "title": doc_title,
        "campaign": campaign_node,
        "collections": collections_node,
        "sessions": sessions_node,
        "other": other_tabs,
        "entities_list": entities,
        "sessions_meta": {
            "all_sessions": session_numbers,
            "latest_session_num": latest_num,
            "next_session_num": latest_num + 1,
        },
    }


def run(docs_service, doc_id: str, audio_file_name: str) -> dict:
    """Entrypoint to fetch and parse document hierarchy directly."""
    logger.info(f"Fetching Google Docs document '{doc_id}' for audio file '{audio_file_name}'...")
    doc = docs_service.documents().get(documentId=doc_id, includeTabsContent=True).execute()

    doc_title = doc.get("title", "Untitled")
    raw_tabs = doc.get("tabs", [])
    logger.info(f"Fetched document '{doc_title}' with {len(raw_tabs)} top-level tab(s); parsing hierarchy...")

    result = parse_hierarchy(raw_tabs, doc_title, audio_file_name)
    result["doc_id"] = doc_id
    logger.info(
        f"Inspection complete for '{doc_title}': "
        f"{len(result['entities_list'])} entities, "
        f"{len(result['sessions']['items'])} sessions; "
        f"next session number is {result['sessions_meta']['next_session_num']}."
    )

    # TEMPORARAY DEBUG
    with open("/app/inspector_debug.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)

    return result
