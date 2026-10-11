import re
import logging

logger = logging.getLogger("Inspector")

# Patterns for recognizing document semantics
SESSION_NAME_PATTERN = re.compile(r"^session\s+(\d+)", re.IGNORECASE)
TEMPLATE_NAME_PATTERN = re.compile(r"(?:^_?template\b|\btemplate$)", re.IGNORECASE)

# Patterns for parsing tagged entity sections and field metadata
TAGGED_SECTION_PATTERN = re.compile(r"(\[[a-zA-Z0-9]{3}\])\s*([^:\n\r(]+):?")
INSTRUCTION_PATTERN = re.compile(r"\(([^)]+)\)")
KEY_VALUE_LINE_PATTERN = re.compile(r"^[•\-*]?\s*([^:\n\r]+):\s*(.*)$")

# Fallback keywords for detecting session headings when styles aren't set to HEADING_1/2
SESSION_HEADING_KEYWORDS = [
    "ai ideas for session",
    "general plot for session",
    "previous notes summary",
    "session notes",
    "chronological history",
]


def extract_plain_text(content_elements):
    """Recursively extracts plain text from structural elements of a Google Doc tab."""
    text_pieces = []
    for element in content_elements:
        if "paragraph" in element:
            for pe in element["paragraph"].get("elements", []):
                if "textRun" in pe:
                    text_pieces.append(pe["textRun"].get("content", ""))
    return "".join(text_pieces)


def parse_mutability_mode(instruction_str):
    """Extracts mutability mode (Static, Overwrite, Append, Don't Change)."""
    inst_lower = instruction_str.lower()
    if "don't change" in inst_lower or "dont change" in inst_lower:
        return "dont_change"
    if "overwrite" in inst_lower:
        return "overwrite"
    if "append" in inst_lower or "union" in inst_lower:
        return "append"
    return "static"


def parse_template_sections(content_elements):
    """
    Parses sections and field blueprints from any entity template tab.
    Detects tagged headings like [0j9] Physical Appearance: (Static: Paragraph).
    """
    sections = []
    current_section = None

    for element in content_elements:
        raw_text = extract_plain_text([element]).strip()
        if not raw_text:
            continue

        tag_match = TAGGED_SECTION_PATTERN.search(raw_text)
        if tag_match:
            if current_section:
                sections.append(current_section)

            tag = tag_match.group(1)
            name = tag_match.group(2).strip()

            inst_match = INSTRUCTION_PATTERN.search(raw_text)
            instruction = inst_match.group(1).strip() if inst_match else ""
            inst_lower = instruction.lower()

            if "keyvaluelist" in inst_lower:
                elem_type = "key_value_list"
            elif "bulletlist" in inst_lower:
                elem_type = "bullet_list"
            else:
                elem_type = "paragraph"

            mutability = parse_mutability_mode(instruction)

            current_section = {
                "tag": tag,
                "key": name,
                "instruction": instruction,
                "type": elem_type,
                "mutability": mutability,
            }

            if elem_type == "key_value_list":
                current_section["fields"] = {}
        else:
            if current_section and current_section["type"] == "key_value_list":
                kv_match = KEY_VALUE_LINE_PATTERN.match(raw_text)
                if kv_match:
                    field_key = kv_match.group(1).strip()
                    raw_val = kv_match.group(2).strip()
                    sub_inst_match = INSTRUCTION_PATTERN.search(raw_val)
                    field_inst = sub_inst_match.group(1).strip() if sub_inst_match else raw_val
                    current_section["fields"][field_key] = {
                        "instruction": field_inst,
                        "mutability": parse_mutability_mode(field_inst),
                    }

    if current_section:
        sections.append(current_section)

    return sections


def is_session_heading(raw_text, named_style):
    """Matches session section headings via keywords or heading styles."""
    stripped = raw_text.strip().rstrip(":")
    stripped_lower = stripped.lower()

    for keyword in SESSION_HEADING_KEYWORDS:
        if stripped_lower == keyword or stripped_lower.startswith(keyword):
            return stripped

    if named_style and named_style.startswith("HEADING_"):
        if len(stripped.splitlines()) == 1 and len(stripped) < 80:
            return stripped

    return None


def parse_session_sections(content_elements):
    """Parses untagged session tabs into structured heading-content pairs."""
    sections = []
    header_lines = []
    current_section = None

    for element in content_elements:
        if "paragraph" not in element:
            continue

        paragraph = element["paragraph"]
        named_style = paragraph.get("paragraphStyle", {}).get("namedStyleType", "NORMAL_TEXT")
        raw_text = extract_plain_text([element])
        stripped = raw_text.strip()

        if not stripped:
            continue

        detected_heading = is_session_heading(stripped, named_style)

        if detected_heading:
            if current_section:
                current_section["content"] = "\n".join(current_section["_lines"]).strip()
                del current_section["_lines"]
                sections.append(current_section)

            current_section = {
                "tag": None,
                "key": detected_heading,
                "type": "bullet_list" if "bullet" in paragraph else "paragraph",
                "_lines": [],
            }
        else:
            if current_section:
                current_section["_lines"].append(stripped)
                if "bullet" in paragraph and current_section["type"] != "bullet_list":
                    current_section["type"] = "bullet_list"
            else:
                header_lines.append(stripped)

    if current_section:
        current_section["content"] = "\n".join(current_section["_lines"]).strip()
        del current_section["_lines"]
        sections.append(current_section)

    return header_lines, sections


def parse_entity_sections(content_elements):
    """Parses active tagged entity tabs into structured sections and key-value fields."""
    sections = []
    header_lines = []
    current_section = None

    for element in content_elements:
        raw_text = extract_plain_text([element])
        stripped = raw_text.strip()
        if not stripped:
            continue

        tag_match = TAGGED_SECTION_PATTERN.search(raw_text)
        if tag_match:
            if current_section:
                if current_section["type"] != "key_value_list":
                    current_section["content"] = "\n".join(current_section["_lines"]).strip()
                del current_section["_lines"]
                sections.append(current_section)

            tag = tag_match.group(1)
            name = tag_match.group(2).strip()

            current_section = {
                "tag": tag,
                "key": name,
                "type": "paragraph",
                "_lines": [],
            }

            remainder = raw_text[tag_match.end() :].strip()
            if remainder:
                current_section["_lines"].append(remainder)
        else:
            if current_section:
                kv_match = KEY_VALUE_LINE_PATTERN.match(stripped)
                if kv_match and (current_section["type"] == "key_value_list" or len(current_section["_lines"]) == 0):
                    current_section["type"] = "key_value_list"
                    if "fields" not in current_section:
                        current_section["fields"] = {}
                    current_section["fields"][kv_match.group(1).strip()] = kv_match.group(2).strip()
                else:
                    current_section["_lines"].append(stripped)
                    if "bullet" in element.get("paragraph", {}) and current_section["type"] != "key_value_list":
                        current_section["type"] = "bullet_list"
            else:
                header_lines.append(stripped)

    if current_section:
        if current_section["type"] != "key_value_list":
            current_section["content"] = "\n".join(current_section["_lines"]).strip()
        del current_section["_lines"]
        sections.append(current_section)

    return header_lines, sections


def run(docs_service, doc_id):
    """
    Inspects the Google Doc hierarchy dynamically.
    Automatically detects category folders and entity schemas without hardcoded lists.
    """
    logger.info(f"Inspecting document structure (Doc ID: {doc_id})...")

    # Fetch document with all nested tab content
    doc = docs_service.documents().get(documentId=doc_id, includeTabsContent=True).execute()

    doc_title = doc.get("title", "Untitled")
    raw_tabs = doc.get("tabs", [])
    flat_tabs = []

    # 1. Traverse document tab tree into a flat, depth-aware list
    def collect(node_list, parent_name=None, depth=0):
        for node in node_list:
            props = node.get("tabProperties", {})
            title = props.get("title", "Untitled").strip()
            tab_id = props.get("tabId")

            doc_tab = node.get("documentTab", {})
            body = doc_tab.get("body", {})
            content = body.get("content", [])
            text = extract_plain_text(content)

            flat_tabs.append(
                {
                    "title": title,
                    "tab_id": tab_id,
                    "parent": parent_name,
                    "depth": depth,
                    "text": text,
                    "content": content,
                }
            )

            children = node.get("childTabs", []) or props.get("childTabs", [])
            if children:
                collect(children, parent_name=title, depth=depth + 1)

    collect(raw_tabs)

    # 2. Group tabs by their parent tab name
    children_by_parent = {}
    for tab in flat_tabs:
        parent = tab["parent"]
        if parent:
            children_by_parent.setdefault(parent, []).append(tab)

    collections = {}
    other_tabs = {}
    session_numbers = []

    # 3. Dynamic Collection Discovery: Detect collections from parent folders
    for tab in flat_tabs:
        title = tab["title"]
        tab_id = tab["tab_id"]
        children = children_by_parent.get(title, [])

        # Sessions container detection
        if title.lower() == "sessions" or any(SESSION_NAME_PATTERN.match(c["title"]) for c in children):
            collections["sessions"] = {
                "folder_title": title,
                "folder_tab_id": tab_id,
                "template": None,  # Sessions are created programmatically
                "items": {},
            }
            continue

        # Dynamic Entity Category detection: has children (including an optional template child)
        if children:
            category_key = title.lower().strip()
            collections[category_key] = {
                "folder_title": title,
                "folder_tab_id": tab_id,
                "template": None,
                "items": {},
            }

    # Map folder names (lowercase) to their collection keys
    parent_to_category = {coll["folder_title"].lower(): cat_key for cat_key, coll in collections.items()}

    # 4. Categorize tabs and extract schemas
    for tab in flat_tabs:
        title = tab["title"]
        parent = tab["parent"]
        assigned_coll = parent_to_category.get(parent.lower()) if parent else None

        if assigned_coll:
            # Check if this child tab is a Template for the collection
            if TEMPLATE_NAME_PATTERN.search(title):
                parsed_template_sections = parse_template_sections(tab["content"])
                collections[assigned_coll]["template"] = {
                    "title": title,
                    "tab_id": tab["tab_id"],
                    "sections": parsed_template_sections,
                }
            elif assigned_coll == "sessions":
                header_lines, item_sections = parse_session_sections(tab["content"])
                sections_by_key = {s["key"].lower(): s["content"] for s in item_sections}

                collections[assigned_coll]["items"][title] = {
                    "title": title,
                    "tab_id": tab["tab_id"],
                    "depth": tab["depth"],
                    "header_summary": "\n".join(header_lines) if header_lines else "",
                    "full_text": tab["text"].strip(),
                    "sections": item_sections,
                    "sections_by_key": sections_by_key,
                }

                sm = SESSION_NAME_PATTERN.match(title)
                if sm:
                    try:
                        session_numbers.append(int(sm.group(1)))
                    except ValueError:
                        pass
            else:
                # Active entity instance tab (e.g. "Captain Karr", "The Hole", "Goblin")
                header_lines, item_sections = parse_entity_sections(tab["content"])
                collections[assigned_coll]["items"][title] = {
                    "title": title,
                    "tab_id": tab["tab_id"],
                    "depth": tab["depth"],
                    "header_summary": "\n".join(header_lines) if header_lines else "",
                    "full_text": tab["text"].strip(),
                    "sections": item_sections,
                }
        else:
            # Check if this tab is a category folder header itself
            is_folder = any(c["folder_tab_id"] == tab["tab_id"] for c in collections.values())
            if not is_folder:
                other_tabs[title] = {
                    "title": title,
                    "tab_id": tab["tab_id"],
                    "parent": parent,
                    "depth": tab["depth"],
                    "full_text": tab["text"].strip(),
                }

    # 5. Session numbering calculation
    session_numbers.sort()
    latest_session_num = session_numbers[-1] if session_numbers else 0
    next_session_num = latest_session_num + 1

    # 6. Flat list of all active entity and session tab titles
    all_tab_titles = list(other_tabs.keys())
    for coll_data in collections.values():
        all_tab_titles.extend(coll_data["items"].keys())

    return {
        "title": doc_title,
        "doc_id": doc_id,
        "all_tab_titles": all_tab_titles,
        "sessions_meta": {
            "all_sessions": session_numbers,
            "latest_session_num": latest_session_num,
            "next_session_num": next_session_num,
        },
        "collections": collections,
        "other_tabs": other_tabs,
    }
