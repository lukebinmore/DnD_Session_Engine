import json
import logging
import re

import docs_helper
import gemini_helper

logger = logging.getLogger("EntityCreator")

ENTITY_CREATION_PROMPT = """You are identifying and creating new D&D campaign entity records from a session Truth Log.

The input contains collection categories, their templates, existing entity names, and the Truth Log.
For each category, identify only clearly new entities supported by the Truth Log. Do not return entities
already listed for that category. Ignore passing mentions that have no meaningful, reusable information.
Never invent details or transfer facts between entities.

Use every template section and its prompt to structure each new entity. For a KeyValueList section, return
a content object using the template's field names. For BulletList sections, return a list of strings. For
Paragraph sections, return a string. Leave unsupported values blank or empty. Do not populate Immutable or
Don't Change sections. Static values may be populated for a new entity when directly supported by the log.

Return strictly valid JSON with this exact shape:
{
  "entities": [
	{
	  "title": "new entity title",
	  "sections": [
		{
		  "section_tag": "template section tag, or null when absent",
		  "section_heading": "template section heading",
		  "content": "string, list of strings, or object for key-value sections"
		}
	  ]
	}
  ]
}

Return an empty entities list when the Truth Log contains no new entities for these categories.
"""


def _normalize_heading(value):
    return re.sub(r"\s+", " ", str(value or "").strip().rstrip(":")).casefold()


def _same_template_section(left, right):
    left_tag = str(left.get("tag") or left.get("section_tag") or "").strip()
    right_tag = str(right.get("tag") or right.get("section_tag") or "").strip()
    if left_tag and right_tag:
        return left_tag == right_tag
    return _normalize_heading(left.get("heading") or left.get("section_heading")) == _normalize_heading(
        right.get("heading") or right.get("section_heading")
    )


def _doc_section_type(template_type):
    normalized_type = str(template_type or "").replace("_", "").casefold()
    if normalized_type == "keyvaluelist":
        return "key_value_list"
    if normalized_type == "bulletlist":
        return "bullet_list"
    return "paragraph"


def _as_text(value):
    if isinstance(value, list):
        return "\n".join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip() if value is not None else ""


def _normalize_section_content(template_section, generated_section):
    section_type = _doc_section_type(template_section.get("type"))
    mode = str(template_section.get("mode") or "").replace("’", "'").strip().casefold()
    if mode in {"immutable", "don't change"}:
        return {} if section_type == "key_value_list" else ([] if section_type == "bullet_list" else "")

    generated_content = generated_section.get("content") if generated_section else None
    if section_type == "key_value_list":
        generated_values = generated_content if isinstance(generated_content, dict) else {}
        normalized_values = {}
        for value in template_section.get("values", []):
            field_name = value.get("heading", "")
            if str(value.get("mode", "")).replace("’", "'").strip().casefold() in {"immutable", "don't change"}:
                normalized_values[field_name] = ""
                continue

            generated_field = next(
                (key for key in generated_values if _normalize_heading(key) == _normalize_heading(field_name)),
                None,
            )
            normalized_values[field_name] = _as_text(generated_values.get(generated_field)) if generated_field else ""
        return normalized_values

    if section_type == "bullet_list":
        if isinstance(generated_content, list):
            return [str(item).strip() for item in generated_content if str(item).strip()]
        if isinstance(generated_content, str):
            return [line.strip("- *\t").strip() for line in generated_content.splitlines() if line.strip()]
        return []

    return _as_text(generated_content)


def _build_entity_sections(entity_data, template_sections):
    title = str(entity_data.get("title", "")).strip()
    generated_sections = entity_data.get("sections", [])
    if not isinstance(generated_sections, list):
        generated_sections = []

    sections = [
        {
            "heading": "TITLE",
            "style": "TITLE",
            "type": "paragraph",
            "content": title,
        }
    ]

    for template_section in template_sections:
        generated_section = next(
            (
                section
                for section in generated_sections
                if isinstance(section, dict) and _same_template_section(template_section, section)
            ),
            None,
        )
        heading = str(template_section.get("heading", "")).strip().rstrip(":")
        sections.append(
            {
                "heading": f"{heading}:",
                "tag": template_section.get("tag"),
                "style": template_section.get("style", "HEADING_1"),
                "type": _doc_section_type(template_section.get("type")),
                "content": _normalize_section_content(template_section, generated_section),
            }
        )

    return sections


def _build_category_payload(category, truth_log):
    template = category.get("template", {})
    template_sections = [
        {
            "heading": section.get("heading"),
            "tag": section.get("tag"),
            "style": section.get("style", "HEADING_1"),
            "type": section.get("type"),
            "mode": section.get("mode"),
            "prompt": section.get("prompt", ""),
            "values": [
                {
                    "heading": value.get("heading"),
                    "mode": value.get("mode"),
                    "type": value.get("type"),
                    "prompt": value.get("prompt", ""),
                }
                for value in section.get("values", [])
            ],
        }
        for section in template.get("sections", [])
    ]
    return {
        "category": category.get("title", "Untitled"),
        "truth_log": truth_log,
        "existing_entity_titles": list(category.get("items", {}).keys()),
        "template": template_sections,
    }


def _request_category_entities(gemini_client, category_payload):
    user_content = (
        "Identify new entities for this collection using its template and the session Truth Log. "
        "Do not return any existing entity titles.\n\n"
        f"{json.dumps(category_payload, ensure_ascii=False, indent=2)}"
    )
    logger.info(
        f"Requesting new entities for collection '{category_payload['category']}' "
        f"(excluding {len(category_payload['existing_entity_titles'])} existing entity/entities)."
    )
    response = gemini_helper.generate_with_fallback(
        gemini_client=gemini_client,
        contents=user_content,
        config={
            "system_instruction": ENTITY_CREATION_PROMPT,
            "response_mime_type": "application/json",
            "temperature": 0.2,
        },
    )

    try:
        result = json.loads(response.text)
    except (TypeError, json.JSONDecodeError) as e:
        raise ValueError(f"Gemini returned invalid JSON for collection '{category_payload['category']}'.") from e

    entities = result.get("entities") if isinstance(result, dict) else None
    if not isinstance(entities, list):
        raise ValueError(f"Gemini response for collection '{category_payload['category']}' has no entities list.")

    logger.info(f"Gemini proposed {len(entities)} new entity/entities for collection '{category_payload['category']}'.")
    return entities


def run(gemini_client, truth_log, doc_meta, docs_service=None, doc_id=None, **kwargs):
    """Creates new entity tabs from the session Truth Log, grouped by collection category."""
    collections = doc_meta.get("collections", {}).get("items", {})
    proposed_entities = []
    category_count = 0

    logger.info(f"Scanning {len(collections)} collection categor(ies) for new entities.")

    for category in collections.values():
        category_title = category.get("title", "Untitled")
        template = category.get("template")
        parent_tab_id = category.get("tab_id")

        if not template:
            logger.warning(f"Skipping collection '{category_title}': no template tab was found.")
            continue
        if not parent_tab_id:
            logger.warning(f"Skipping collection '{category_title}': category tabId is missing.")
            continue

        category_payload = _build_category_payload(category, truth_log)
        category_entities = _request_category_entities(gemini_client, category_payload)
        category_count += 1

        existing_titles = {str(title).strip().casefold() for title in category.get("items", {})}
        for entity_data in category_entities:
            if not isinstance(entity_data, dict):
                logger.warning(f"Ignoring malformed entity response in collection '{category_title}'.")
                continue

            entity_title = str(entity_data.get("title", "")).strip()
            normalized_title = entity_title.casefold()
            if not entity_title:
                logger.warning(f"Ignoring an entity without a title in collection '{category_title}'.")
                continue
            if normalized_title in existing_titles:
                logger.info(f"Skipping existing entity '{entity_title}' in collection '{category_title}'.")
                continue
            existing_titles.add(normalized_title)

            sections = _build_entity_sections(entity_data, template.get("sections", []))
            proposed_entities.append(
                {
                    "category": category_title,
                    "parent_tab_id": parent_tab_id,
                    "title": entity_title,
                    "sections": sections,
                }
            )

    if not proposed_entities:
        logger.info("No new entities were found; no Google Docs update is needed.")
        return {"categories_processed": category_count, "entities_created": 0, "created_entities": []}

    if not docs_service or not doc_id:
        logger.warning("New entities were identified, but docs_service or doc_id is missing; skipped tab creation.")
        return {"categories_processed": category_count, "entities_created": 0, "created_entities": []}

    add_requests = [
        docs_helper.build_add_tab_request(entity["title"], entity["parent_tab_id"]) for entity in proposed_entities
    ]
    logger.info(f"Creating {len(proposed_entities)} entity tab(s) in one Google Docs batch.")
    response = docs_helper.execute_batch(docs_service=docs_service, doc_id=doc_id, requests=add_requests)
    replies = response.get("replies", []) if isinstance(response, dict) else []
    if len(replies) != len(proposed_entities):
        raise RuntimeError(
            f"Google Docs returned {len(replies)} replies for {len(proposed_entities)} entity tab creation request(s)."
        )

    content_requests = []
    created_entities = []
    for entity, reply in zip(proposed_entities, replies):
        add_tab_reply = reply.get("addDocumentTab", {}) if isinstance(reply, dict) else {}
        tab_id = add_tab_reply.get("tabProperties", {}).get("tabId")
        if not tab_id:
            raise RuntimeError(f"Failed to retrieve the new tabId for entity '{entity['title']}'.")

        content_requests.extend(docs_helper.build_tab_content_requests(tab_id, entity["sections"]))
        created_entities.append({"category": entity["category"], "title": entity["title"]})

    if content_requests:
        logger.info(f"Populating {len(created_entities)} new entity tab(s) in one Google Docs batch.")
        docs_helper.execute_batch(docs_service=docs_service, doc_id=doc_id, requests=content_requests)

    logger.info(f"Created and populated {len(created_entities)} new entity tab(s).")
    return {
        "categories_processed": category_count,
        "entities_created": len(created_entities),
        "created_entities": created_entities,
    }
