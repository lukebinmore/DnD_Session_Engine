import re


def get_tab_body(docs_service, doc_id, tab_id):
    """Fetches the content body of a specific tab."""
    doc = docs_service.documents().get(documentId=doc_id, includeTabsContent=True).execute()

    def find(tab_list):
        for tab in tab_list:
            if tab.get("tabProperties", {}).get("tabId") == tab_id:
                return tab.get("documentTab", {}).get("body", {}).get("content", [])
            if "childTabs" in tab:
                res = find(tab["childTabs"])
                if res:
                    return res
        return []

    return find(doc.get("tabs", []))


def build_tab_url(doc_id, tab_id):
    return f"https://docs.google.com/document/d/{doc_id}/edit#tab={tab_id}"


def create_tab(docs_service, doc_id, title, parent_tab_id=None):
    """Issues an AddDocumentTabRequest to create a new tab, nested under parent_tab_id."""
    props = {"title": title}
    if parent_tab_id:
        props["parentTabId"] = parent_tab_id

    req = {"addDocumentTab": {"tabProperties": props}}
    res = docs_service.documents().batchUpdate(documentId=doc_id, body={"requests": [req]}).execute()

    new_tab_id = res["replies"][0]["addDocumentTab"]["tabProperties"]["tabId"]
    return new_tab_id


def apply_template_content(docs_service, doc_id, tab_id, template_fields, field_values, doc_url_id, tabs_info):
    """
    Writes template lines into a newly created tab, replacing instructions
    with extracted data and converting tab references into internal hyperlinks.
    """
    text_buffer = ""
    link_ranges = []

    for item in template_fields:
        label = item["label"]

        # Check if field_values matches this label
        val = ""
        for k, v in field_values.items():
            if k.lower() in label.lower() or label.lower() in k.lower():
                val = v
                break

        line_to_write = label
        if val:
            if "\n" in str(val):
                line_to_write = f"{label}\n{val}"
            else:
                line_to_write = f"{label} {val}"

        start_idx = len(text_buffer)
        text_buffer += line_to_write + "\n\n"

        # If this field specifies links, convert matching tab names to internal URLs
        if item.get("requires_link") and val:
            for tab_name, meta in tabs_info.items():
                if tab_name.lower() in str(val).lower():
                    target_url = build_tab_url(doc_url_id, meta["tab_id"])
                    val_offset = line_to_write.find(tab_name)
                    if val_offset != -1:
                        link_start = start_idx + val_offset
                        link_end = link_start + len(tab_name)
                        link_ranges.append((link_start, link_end, target_url))

    requests = [{"insertText": {"location": {"tabId": tab_id, "index": 1}, "text": text_buffer}}]

    for l_start, l_end, url in link_ranges:
        requests.append(
            {
                "updateTextStyle": {
                    "range": {"tabId": tab_id, "startIndex": 1 + l_start, "endIndex": 1 + l_end},
                    "textStyle": {"link": {"url": url}, "underline": True},
                    "fields": "link,underline",
                }
            }
        )

    docs_service.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()


def append_to_tab_field(docs_service, doc_id, tab_id, target_label, content_to_append):
    """Finds a label inside an existing tab and appends content underneath it."""
    body_elements = get_tab_body(docs_service, doc_id, tab_id)
    target_index = None

    for elem in body_elements:
        p = elem.get("paragraph")
        if not p:
            continue
        text = "".join(e.get("textRun", {}).get("content", "") for e in p.get("elements", []))
        if target_label.lower() in text.lower():
            target_index = elem.get("endIndex", 1) - 1
            break

    if target_index is not None:
        req = {"insertText": {"location": {"tabId": tab_id, "index": target_index}, "text": f"\n{content_to_append}"}}
        docs_service.documents().batchUpdate(documentId=doc_id, body={"requests": [req]}).execute()


def apply_updates(docs_service, doc_id, extracted, tabs_info, templates_dict, available_sections, root_tab_id):
    """Master dispatcher handling session notes, next-session prep, and dynamic entity nesting."""
    # 1. Update Current Session Tab
    curr_sess = extracted.get("current_session", {})
    curr_tab_title = curr_sess.get("tab_title")
    curr_fields = curr_sess.get("fields", {})

    if curr_tab_title and curr_tab_title in tabs_info:
        curr_tab_id = tabs_info[curr_tab_title]["tab_id"]
        sess_template = templates_dict.get("session", [])
        for item in sess_template:
            label = item["label"]
            for f_key, f_val in curr_fields.items():
                if f_key.lower() in label.lower() or label.lower() in f_key.lower():
                    append_to_tab_field(docs_service, doc_id, curr_tab_id, label, str(f_val))

    # 2. Setup Next Session Tab (nested under 'Sessions' section tab if it exists, else root)
    next_sess = extracted.get("next_session_setup", {})
    next_tab_title = next_sess.get("tab_title")
    recap_script = next_sess.get("previous_notes_summary")

    if next_tab_title and next_tab_title not in tabs_info:
        sessions_section_id = tabs_info.get("Sessions", {}).get("tab_id") or root_tab_id
        new_sess_tab_id = create_tab(docs_service, doc_id, next_tab_title, parent_tab_id=sessions_section_id)
        tabs_info[next_tab_title] = {"tab_id": new_sess_tab_id, "parent_tab_id": sessions_section_id}

        sess_template = templates_dict.get("session", [])
        initial_fields = {"previous notes summary": recap_script or ""}
        apply_template_content(docs_service, doc_id, new_sess_tab_id, sess_template, initial_fields, doc_id, tabs_info)

    # 3. Create New Entities (nested under their matching parent section tab)
    new_entities = extracted.get("new_entities", [])
    for entity in new_entities:
        ent_name = entity.get("name")
        ent_type = entity.get("type", "").lower()
        parent_sec = entity.get("parent_section")

        if ent_name and ent_name not in tabs_info:
            parent_tab_id = None
            if parent_sec and parent_sec in tabs_info:
                parent_tab_id = tabs_info[parent_sec]["tab_id"]
            elif root_tab_id:
                parent_tab_id = root_tab_id

            new_tab_id = create_tab(docs_service, doc_id, ent_name, parent_tab_id=parent_tab_id)
            tabs_info[ent_name] = {"tab_id": new_tab_id, "parent_tab_id": parent_tab_id}

            tmpl = templates_dict.get(ent_type, [])
            apply_template_content(docs_service, doc_id, new_tab_id, tmpl, entity.get("fields", {}), doc_id, tabs_info)

    # 4. Apply Entity Updates
    for update in extracted.get("entity_updates", []):
        t_title = update.get("tab_title")
        t_label = update.get("append_to_label", "History")
        t_content = update.get("content")
        if t_title in tabs_info and t_content:
            target_tab_id = tabs_info[t_title]["tab_id"]
            append_to_tab_field(docs_service, doc_id, target_tab_id, t_label, t_content)
