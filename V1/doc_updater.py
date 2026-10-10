import re
import time
from googleapiclient.errors import HttpError


def execute_batch_update_with_retry(docs_service, doc_id, requests, max_retries=4, initial_backoff=15):
    """Executes a batchUpdate call with exponential backoff on 429 rate limit errors."""
    if not requests:
        return None
    backoff = initial_backoff
    for attempt in range(1, max_retries + 1):
        try:
            return docs_service.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()
        except HttpError as err:
            if err.resp.status in (429, 503) and attempt < max_retries:
                print(
                    f"[doc_updater] Docs API rate limit hit ({err.resp.status}). Pausing {backoff}s before retry {attempt}/{max_retries}..."
                )
                time.sleep(backoff)
                backoff *= 2
            else:
                raise err


def get_doc(docs_service, doc_id):
    """Fetches the full document tree with tab content."""
    return docs_service.documents().get(documentId=doc_id, includeTabsContent=True).execute()


def find_tab_by_id(tab_list, target_tab_id):
    for tab in tab_list:
        if tab.get("tabProperties", {}).get("tabId") == target_tab_id:
            return tab
        if "childTabs" in tab:
            found = find_tab_by_id(tab["childTabs"], target_tab_id)
            if found:
                return found
    return None


def find_tab_by_title(tab_list, title_to_match):
    for tab in tab_list:
        props = tab.get("tabProperties", {})
        if props.get("title", "").strip().lower() == title_to_match.strip().lower():
            return tab
        if "childTabs" in tab:
            found = find_tab_by_title(tab["childTabs"], title_to_match)
            if found:
                return found
    return None


def build_tab_url(doc_id, tab_id):
    return f"https://docs.google.com/document/d/{doc_id}/edit#tab={tab_id}"


def create_tab(docs_service, doc_id, title, parent_tab_id=None):
    props = {"title": title}
    if parent_tab_id:
        props["parentTabId"] = parent_tab_id

    req = {"addDocumentTab": {"tabProperties": props}}
    res = execute_batch_update_with_retry(docs_service, doc_id, [req])
    return res["replies"][0]["addDocumentTab"]["tabProperties"]["tabId"]


def parse_template_instruction(raw_text):
    """Parses a template line according to (Position: Format: Description)."""
    clean_text = raw_text.replace("’", "'").strip()
    match = re.search(r"^(.*?)\s*\(([^()]+)\)\s*$", clean_text)
    if not match:
        return clean_text, None, None, "", False

    label = match.group(1).strip()
    inner = match.group(2).strip()

    if inner.lower() in ["don't change", "dont change", "leave empty"]:
        return label, None, None, "", True

    parts = [p.strip() for p in inner.split(":", 2)]
    if len(parts) == 3:
        return label, parts[0], parts[1], parts[2], False
    elif len(parts) == 2:
        return label, parts[0], parts[1], "", False
    else:
        return label, None, None, inner, False


def extract_template_structure(template_tab):
    """
    Parses template tab into ordered structural blocks:
      - 'paragraph': line text, named style, bold flag
      - 'table': 2D grid of rows and cells with labels and instructions
    """
    body_content = template_tab.get("documentTab", {}).get("body", {}).get("content", [])
    blocks = []

    for elem in body_content:
        p = elem.get("paragraph")
        if p:
            raw_text = "".join(e.get("textRun", {}).get("content", "") for e in p.get("elements", []))
            named_style = p.get("paragraphStyle", {}).get("namedStyleType", "NORMAL_TEXT")

            is_bold = False
            for e in p.get("elements", []):
                run = e.get("textRun", {})
                if run.get("content", "").strip():
                    is_bold = run.get("textStyle", {}).get("bold", False)
                    break

            blocks.append(
                {"type": "paragraph", "raw_line": raw_text.rstrip("\r\n"), "style": named_style, "bold": is_bold}
            )
        elif "table" in elem:
            table = elem["table"]
            rows_data = []
            for row in table.get("tableRows", []):
                cell_row = []
                for cell in row.get("tableCells", []):
                    c_text = "".join(
                        "".join(
                            e.get("textRun", {}).get("content", "") for e in cp.get("paragraph", {}).get("elements", [])
                        )
                        for cp in cell.get("content", [])
                    ).strip()
                    cell_row.append(c_text)
                rows_data.append(cell_row)

            blocks.append(
                {
                    "type": "table",
                    "rows": rows_data,
                    "num_rows": len(rows_data),
                    "num_cols": len(rows_data[0]) if rows_data else 0,
                }
            )

    return blocks


def clone_template_to_tab(docs_service, doc_id, new_tab_id, template_tab, initial_fields, tabs_info, entity_title):
    """
    Compiles paragraphs and tables, assembling them into consolidated batchUpdate calls
    to prevent exceeding Google Docs API write quotas.
    """
    template_blocks = extract_template_structure(template_tab)
    first_replace_seen = False

    full_text = ""
    style_ops = []
    bullet_ops = []
    link_ops = []
    has_table_block = None

    for block in template_blocks:
        if block["type"] == "paragraph":
            raw_line = block["raw_line"]
            named_style = block["style"]
            is_bold = block["bold"]

            if not raw_line.strip():
                start = len(full_text)
                full_text += "\n"
                style_ops.append({"start": start, "end": len(full_text), "style": "NORMAL_TEXT", "bold": False})
                continue

            label, pos, fmt, desc, is_ignored = parse_template_instruction(raw_line)

            if is_ignored:
                clean_display = label if label else raw_line
                start = len(full_text)
                full_text += f"{clean_display}\n"
                style_ops.append({"start": start, "end": len(full_text), "style": named_style, "bold": is_bold})
                continue

            val = ""
            for k, v in initial_fields.items():
                k_clean = k.strip().lower()
                if (
                    (label and k_clean in label.lower())
                    or (desc and k_clean in desc.lower())
                    or (k_clean in raw_line.lower())
                ):
                    val = str(v).strip()
                    break

            if pos == "Replace":
                line_val = entity_title if not first_replace_seen else (val or desc)
                first_replace_seen = True
                start = len(full_text)
                full_text += f"{line_val}\n"
                style_ops.append(
                    {
                        "start": start,
                        "end": len(full_text),
                        "style": named_style if named_style != "NORMAL_TEXT" else "TITLE",
                        "bold": True,
                    }
                )
                continue

            if pos == "Inline":
                line_val = f"{label} {val}".strip() if val else label
                start = len(full_text)
                full_text += f"{line_val}\n"
                end = len(full_text)
                style_ops.append({"start": start, "end": end, "style": named_style, "bold": is_bold})

                if fmt in ("Link", "LinkList") and val:
                    for tab_name, meta in tabs_info.items():
                        if meta["tab_id"] != new_tab_id and tab_name.lower() in val.lower():
                            offset = line_val.find(tab_name)
                            if offset != -1:
                                link_ops.append(
                                    {
                                        "start": start + offset,
                                        "end": start + offset + len(tab_name),
                                        "url": build_tab_url(doc_id, meta["tab_id"]),
                                    }
                                )
                continue

            # Position: Block or Append
            start = len(full_text)
            full_text += f"{label}\n"
            header_end = len(full_text)
            style_ops.append({"start": start, "end": header_end, "style": named_style, "bold": True})

            if val:
                lines = [re.sub(r"^[-*•]\s*", "", l).strip() for l in val.split("\n") if l.strip()]
                val_text = "\n".join(lines) + "\n"
                val_start = len(full_text)
                full_text += val_text
                val_end = len(full_text)

                style_ops.append({"start": val_start, "end": val_end, "style": "NORMAL_TEXT", "bold": False})

                if fmt in ("BulletList", "LinkList"):
                    bullet_ops.append({"start": val_start, "end": val_end})

                if fmt in ("Link", "LinkList"):
                    for tab_name, meta in tabs_info.items():
                        if meta["tab_id"] != new_tab_id and tab_name.lower() in val_text.lower():
                            for m in re.finditer(re.escape(tab_name), val_text, re.IGNORECASE):
                                link_ops.append(
                                    {
                                        "start": val_start + m.start(),
                                        "end": val_start + m.end(),
                                        "url": build_tab_url(doc_id, meta["tab_id"]),
                                    }
                                )

        elif block["type"] == "table":
            has_table_block = block

    # Execute all paragraph text, styles, and bullets in ONE single batchUpdate call
    batch_reqs = []
    if full_text.strip():
        batch_reqs.append({"insertText": {"location": {"tabId": new_tab_id, "index": 1}, "text": full_text}})

        for op in style_ops:
            batch_reqs.append(
                {
                    "updateParagraphStyle": {
                        "range": {"tabId": new_tab_id, "startIndex": 1 + op["start"], "endIndex": 1 + op["end"]},
                        "paragraphStyle": {"namedStyleType": op["style"]},
                        "fields": "namedStyleType",
                    }
                }
            )
            if op["bold"]:
                batch_reqs.append(
                    {
                        "updateTextStyle": {
                            "range": {"tabId": new_tab_id, "startIndex": 1 + op["start"], "endIndex": 1 + op["end"]},
                            "textStyle": {"bold": True},
                            "fields": "bold",
                        }
                    }
                )

        for b_op in bullet_ops:
            batch_reqs.append(
                {
                    "createParagraphBullets": {
                        "range": {"tabId": new_tab_id, "startIndex": 1 + b_op["start"], "endIndex": 1 + b_op["end"]},
                        "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE",
                    }
                }
            )

        for l_op in link_ops:
            batch_reqs.append(
                {
                    "updateTextStyle": {
                        "range": {"tabId": new_tab_id, "startIndex": 1 + l_op["start"], "endIndex": 1 + l_op["end"]},
                        "textStyle": {"link": {"url": l_op["url"]}, "underline": True},
                        "fields": "link,underline",
                    }
                }
            )

        execute_batch_update_with_retry(docs_service, doc_id, batch_reqs)

    # Handle table insertion cleanly if present
    if has_table_block and has_table_block["num_rows"] > 0 and has_table_block["num_cols"] > 0:
        doc_state = get_doc(docs_service, doc_id)
        current_tab = find_tab_by_id(doc_state.get("tabs", []), new_tab_id)
        body_elems = current_tab.get("documentTab", {}).get("body", {}).get("content", [])
        last_idx = max(1, body_elems[-1].get("endIndex", 2) - 1)

        # 1 call: Insert table
        execute_batch_update_with_retry(
            docs_service,
            doc_id,
            [
                {
                    "insertTable": {
                        "rows": has_table_block["num_rows"],
                        "columns": has_table_block["num_cols"],
                        "location": {"tabId": new_tab_id, "index": last_idx},
                    }
                }
            ],
        )

        # Read back cell locations
        doc_state = get_doc(docs_service, doc_id)
        current_tab = find_tab_by_id(doc_state.get("tabs", []), new_tab_id)
        body_elems = current_tab.get("documentTab", {}).get("body", {}).get("content", [])
        new_table = [e["table"] for e in body_elems if "table" in e][-1]

        cell_ops = []
        for r_idx, row in enumerate(has_table_block["rows"]):
            tbl_row = new_table["tableRows"][r_idx]
            label_txt = row[0] if len(row) > 0 else ""
            instr_txt = row[1] if len(row) > 1 else ""

            c0_start = tbl_row["tableCells"][0]["content"][0]["startIndex"]
            cell_ops.append({"index": c0_start, "text": label_txt, "bold": True})

            val_txt = ""
            for k, v in initial_fields.items():
                k_clean = k.strip().lower()
                if (label_txt and k_clean in label_txt.lower()) or (instr_txt and k_clean in instr_txt.lower()):
                    val_txt = str(v).strip()
                    break

            display_val = val_txt if val_txt else ""
            if len(tbl_row["tableCells"]) > 1:
                c1_start = tbl_row["tableCells"][1]["content"][0]["startIndex"]
                cell_ops.append({"index": c1_start, "text": display_val, "bold": False})

        cell_ops.sort(key=lambda x: x["index"], reverse=True)
        tbl_insert_reqs = []
        for op in cell_ops:
            if op["text"]:
                tbl_insert_reqs.append(
                    {"insertText": {"location": {"tabId": new_tab_id, "index": op["index"]}, "text": op["text"]}}
                )
                if op["bold"]:
                    tbl_insert_reqs.append(
                        {
                            "updateTextStyle": {
                                "range": {
                                    "tabId": new_tab_id,
                                    "startIndex": op["index"],
                                    "endIndex": op["index"] + len(op["text"]),
                                },
                                "textStyle": {"bold": True},
                                "fields": "bold",
                            }
                        }
                    )

        # 1 call: Populate all cells
        execute_batch_update_with_retry(docs_service, doc_id, tbl_insert_reqs)


def append_under_label(docs_service, doc_id, tab_id, target_label_substring, content_text, tabs_info, as_bullets=True):
    """
    Locates a label inside an existing tab and appends content_text on a NEW line
    in a single consolidated batchUpdate call.
    """
    doc = get_doc(docs_service, doc_id)
    tab = find_tab_by_id(doc.get("tabs", []), tab_id)
    if not tab:
        return

    body_elements = tab.get("documentTab", {}).get("body", {}).get("content", [])
    insert_at = None

    for elem in body_elements:
        p = elem.get("paragraph")
        if not p:
            continue
        p_text = "".join(e.get("textRun", {}).get("content", "") for e in p.get("elements", []))
        if target_label_substring.lower() in p_text.lower():
            insert_at = elem.get("endIndex")
            break

    if insert_at is None:
        return

    lines = [re.sub(r"^[-*•]\s*", "", l).strip() for l in content_text.split("\n") if l.strip()]
    if not lines:
        return

    insertion_text = "\n".join(lines) + "\n"

    requests = [
        {"insertText": {"location": {"tabId": tab_id, "index": insert_at}, "text": insertion_text}},
        {
            "updateParagraphStyle": {
                "range": {"tabId": tab_id, "startIndex": insert_at, "endIndex": insert_at + len(insertion_text)},
                "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
                "fields": "namedStyleType",
            }
        },
        {
            "updateTextStyle": {
                "range": {"tabId": tab_id, "startIndex": insert_at, "endIndex": insert_at + len(insertion_text)},
                "textStyle": {"bold": False, "italic": False, "underline": False},
                "fields": "bold,italic,underline",
            }
        },
    ]

    if as_bullets:
        requests.append(
            {
                "createParagraphBullets": {
                    "range": {"tabId": tab_id, "startIndex": insert_at, "endIndex": insert_at + len(insertion_text)},
                    "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE",
                }
            }
        )

    for tab_name, meta in tabs_info.items():
        if meta["tab_id"] != tab_id and tab_name.lower() in insertion_text.lower():
            for m in re.finditer(re.escape(tab_name), insertion_text, re.IGNORECASE):
                requests.append(
                    {
                        "updateTextStyle": {
                            "range": {
                                "tabId": tab_id,
                                "startIndex": insert_at + m.start(),
                                "endIndex": insert_at + m.end(),
                            },
                            "textStyle": {"link": {"url": build_tab_url(doc_id, meta["tab_id"])}, "underline": True},
                            "fields": "link,underline",
                        }
                    }
                )

    execute_batch_update_with_retry(docs_service, doc_id, requests)


def apply_updates(docs_service, doc_id, extracted, tabs_info, templates_dict, available_sections, root_tab_id):
    """Master dispatcher handling session notes, next-session prep, and dynamic entity nesting."""
    doc = get_doc(docs_service, doc_id)
    doc_tabs = doc.get("tabs", [])

    # 1. Update Current Session Tab
    curr_sess = extracted.get("current_session", {})
    curr_tab_title = curr_sess.get("tab_title")
    curr_fields = curr_sess.get("fields", {})

    if curr_tab_title:
        target_tab = find_tab_by_title(doc_tabs, curr_tab_title)
        if target_tab:
            curr_tab_id = target_tab.get("tabProperties", {}).get("tabId")
            for field_label, field_val in curr_fields.items():
                if field_val:
                    is_bullet = True
                    for f in templates_dict.get("session", []):
                        if f["label"] and f["label"].lower() in field_label.lower():
                            is_bullet = f.get("format") in ("BulletList", "LinkList")
                            break
                    append_under_label(
                        docs_service, doc_id, curr_tab_id, field_label, str(field_val), tabs_info, as_bullets=is_bullet
                    )

    # 2. Setup Next Session Tab
    next_sess = extracted.get("next_session_setup", {})
    next_tab_title = next_sess.get("tab_title")
    recap_script = next_sess.get("previous_notes_summary")

    if next_tab_title and not find_tab_by_title(doc_tabs, next_tab_title):
        sessions_tab = find_tab_by_title(doc_tabs, "Sessions")
        sessions_section_id = sessions_tab.get("tabProperties", {}).get("tabId") if sessions_tab else root_tab_id

        new_sess_tab_id = create_tab(docs_service, doc_id, next_tab_title, parent_tab_id=sessions_section_id)
        tabs_info[next_tab_title] = {"tab_id": new_sess_tab_id, "parent_tab_id": sessions_section_id}

        sess_tmpl_tab = find_tab_by_title(doc_tabs, "Session Template")
        if sess_tmpl_tab:
            initial_fields = {
                "[dnv] Previous Notes Summary:": recap_script or "",
                "Previous Notes Summary": recap_script or "",
            }
            clone_template_to_tab(
                docs_service,
                doc_id,
                new_sess_tab_id,
                sess_tmpl_tab,
                initial_fields,
                tabs_info,
                entity_title=next_tab_title,
            )

    # 3. Create New Entities
    new_entities = extracted.get("new_entities", [])
    for entity in new_entities:
        ent_name = entity.get("name")
        ent_type = entity.get("type", "").lower()
        parent_sec = entity.get("parent_section")

        if ent_name and not find_tab_by_title(doc_tabs, ent_name):
            parent_tab_id = None
            if parent_sec:
                sec_tab = find_tab_by_title(doc_tabs, parent_sec)
                if sec_tab:
                    parent_tab_id = sec_tab.get("tabProperties", {}).get("tabId")
            if not parent_tab_id:
                parent_tab_id = root_tab_id

            new_tab_id = create_tab(docs_service, doc_id, ent_name, parent_tab_id=parent_tab_id)
            tabs_info[ent_name] = {"tab_id": new_tab_id, "parent_tab_id": parent_tab_id}

            tmpl_tab = find_tab_by_title(doc_tabs, f"{ent_type} template")
            if tmpl_tab:
                clone_template_to_tab(
                    docs_service,
                    doc_id,
                    new_tab_id,
                    tmpl_tab,
                    entity.get("fields", {}),
                    tabs_info,
                    entity_title=ent_name,
                )

    # 4. Apply Entity Updates
    for update in extracted.get("entity_updates", []):
        t_title = update.get("tab_title")
        t_label = update.get("append_to_label", "History")
        bullets = update.get("bullets", [])
        content = "\n".join(bullets) if bullets else update.get("content", "")

        if t_title and content:
            target_tab = find_tab_by_title(doc_tabs, t_title)
            if target_tab:
                t_id = target_tab.get("tabProperties", {}).get("tabId")
                append_under_label(docs_service, doc_id, t_id, t_label, content, tabs_info, as_bullets=True)
