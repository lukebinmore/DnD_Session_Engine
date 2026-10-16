import copy
import json
import logging
import re

import docs_helper
import gemini_helper

logger = logging.getLogger("EntityProcessor")

ENTITY_PLAN_PROMPT = """You maintain a D&D campaign's collection of entity records.

For this collection, use the supplied template, existing entity data, and session Truth Log to produce one
combined plan: updates to existing entities and new entities that deserve their own tab.

Only use facts supported by the Truth Log. Never invent details, infer hidden thoughts, or transfer facts
between entities. Keep each entity independent and use exact existing titles when referring to existing tabs.

EXISTING ENTITY UPDATES
- Return updates only when the Truth Log provides a meaningful, supported change or new fact.
- Follow each template section's prompt and mode. For a Block section, follow each nested field's mode.
- Immutable or Don't Change: never update.
- Static: leave existing values unchanged.
- Overwrite: return a complete replacement only when the Truth Log clearly changes the value.
- Append: return only genuinely new information; do not repeat existing information.
- For append-only section content, add the session number to each new entry when the template asks for it.

NEW ENTITY TABS
- Identify clearly named, distinct, reusable entities introduced or materially established in this session.
- Create a new entity when it has enough supported information to make a useful campaign record, not for a
  generic passing mention. A specifically named location discovered within another location can qualify.
- Do not return anything already listed among the existing entity titles for this collection.
- Use the template to structure each new entity. For KeyValueList sections, return an object using the
  template's exact field names. For BulletList sections, return a list of strings. For Paragraph sections,
  return a string. Leave unsupported values empty. Do not populate Immutable or Don't Change sections.
- Static fields may be populated for a new entity when the Truth Log directly supports them.
- Do not include a new-entity fact as an update to an existing entity unless it independently changes that
  existing entity's record (for example, a newly discovered sub-location can be both listed on its parent
  and receive its own page).

Return strictly valid JSON with this exact shape:
{
  "updates": [
    {
      "entity_title": "exact existing entity title",
      "section_updates": [
        {
          "section_tag": "template section tag, or null when absent",
          "section_heading": "template section heading",
          "field_name": "nested key-value field name, or null",
          "content": "replacement/addition, or a list for bullet-list content"
        }
      ]
    }
  ],
  "new_entities": [
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

Use empty arrays when there are no updates or no new entities. Do not include unchanged or disallowed fields.
"""


def _normalize_heading(value):
    return re.sub(r"\s+", " ", str(value or "").strip().rstrip(":")).casefold()


def _same_tag_or_heading(left, right):
    left_tag = str(left.get("tag") or left.get("section_tag") or "").strip()
    right_tag = str(right.get("tag") or right.get("section_tag") or "").strip()
    if left_tag and right_tag:
        return left_tag == right_tag
    return _normalize_heading(left.get("heading") or left.get("section_heading")) == _normalize_heading(
        right.get("heading") or right.get("section_heading")
    )


def _has_content(value):
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    return value is not None


def _normalize_content(value, data_type):
    normalized_type = str(data_type or "").replace("_", "").casefold()
    if normalized_type == "bulletlist":
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str):
            return [line.strip("- *\t").strip() for line in value.splitlines() if line.strip()]
        return []

    if isinstance(value, list):
        return "\n".join(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, str):
        return value.strip()
    return str(value).strip() if value is not None else ""


def _append_content(existing, addition):
    if isinstance(addition, list):
        additions = [str(item).strip() for item in addition if str(item).strip()]
    elif isinstance(addition, str):
        additions = [line.strip("- *\t").strip() for line in addition.splitlines() if line.strip()]
        if not additions and addition.strip():
            additions = [addition.strip()]
    else:
        additions = [str(addition).strip()] if addition is not None else []

    if isinstance(existing, list):
        result = list(existing)
        existing_values = {str(item).strip().casefold() for item in result}
        for item in additions:
            if item.casefold() not in existing_values:
                result.append(item)
                existing_values.add(item.casefold())
        return result

    existing_text = str(existing or "")
    result = [line for line in existing_text.splitlines() if line.strip()]
    existing_values = {line.strip().casefold() for line in result}
    for item in additions:
        if item.casefold() not in existing_values:
            result.append(item)
            existing_values.add(item.casefold())
    return "\n".join(result)


def _apply_mode(existing, generated, mode, data_type):
    normalized_mode = str(mode or "").replace("’", "'").strip().casefold()
    if normalized_mode in {"static", "immutable", "don't change"}:
        return existing, False

    generated = _normalize_content(generated, data_type)
    if not _has_content(generated):
        return existing, False

    if normalized_mode == "overwrite":
        return generated, generated != existing
    if normalized_mode == "append":
        updated = _append_content(existing, generated)
        return updated, updated != existing

    logger.warning("Ignoring unsupported template update mode '%s'.", mode)
    return existing, False


def _template_payload(category):
    template = category.get("template", {})
    return [
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


def _category_payload(category, truth_log):
    entities = category.get("items", {})
    return {
        "category": category.get("title", "Untitled"),
        "truth_log": truth_log,
        "template": _template_payload(category),
        "entities": [
            {
                "title": entity.get("title", title),
                "sections": [
                    {
                        "heading": section.get("heading"),
                        "tag": section.get("tag"),
                        "type": section.get("type"),
                        "content": section.get("content"),
                    }
                    for section in entity.get("sections", [])
                ],
            }
            for title, entity in entities.items()
        ],
    }


def _request_category_plan(gemini_client, payload):
    category_title = payload["category"]
    user_content = (
        "Produce one combined plan for existing entity updates and new entity tabs in this collection. "
        "Use only the supplied Truth Log and follow the supplied template.\n\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )
    logger.info(
        f"Planning updates and new entities for collection '{category_title}' "
        f"({len(payload['entities'])} existing entity/entities)."
    )
    response = gemini_helper.generate_with_fallback(
        gemini_client=gemini_client,
        contents=user_content,
        config={
            "system_instruction": ENTITY_PLAN_PROMPT,
            "response_mime_type": "application/json",
            "temperature": 0.2,
        },
    )

    try:
        result = json.loads(response.text)
    except (TypeError, json.JSONDecodeError) as e:
        raise ValueError(f"Gemini returned invalid JSON for collection '{category_title}'.") from e

    if not isinstance(result, dict):
        raise ValueError(f"Gemini response for collection '{category_title}' must be a JSON object.")
    updates = result.get("updates")
    new_entities = result.get("new_entities")
    if not isinstance(updates, list) or not isinstance(new_entities, list):
        raise ValueError(
            f"Gemini response for collection '{category_title}' must contain updates and new_entities lists."
        )

    logger.info(
        f"Collection '{category_title}' plan contains {len(updates)} update(s) and "
        f"{len(new_entities)} proposed new entity/entities."
    )
    return updates, new_entities


def _find_template_section(template_sections, update):
    return next(
        (section for section in template_sections if _same_tag_or_heading(section, update)),
        None,
    )


def _apply_entity_updates(entity, template_sections, section_updates):
    updated_entity = copy.deepcopy(entity)
    sections = updated_entity.get("sections", [])
    changed = False

    for update in section_updates:
        if not isinstance(update, dict):
            logger.warning("Ignoring malformed section update for entity '%s'.", entity.get("title"))
            continue

        template_section = _find_template_section(template_sections, update)
        if not template_section:
            logger.warning("Ignoring update for an unknown template section on '%s'.", entity.get("title"))
            continue

        entity_section = next(
            (section for section in sections if _same_tag_or_heading(section, template_section)),
            None,
        )
        if not entity_section:
            logger.warning(
                "Ignoring update for missing section '%s' on '%s'.",
                template_section.get("heading"),
                entity.get("title"),
            )
            continue

        section_type = str(template_section.get("type") or "").replace("_", "").casefold()
        if section_type == "keyvaluelist":
            field_name = _normalize_heading(update.get("field_name"))
            template_value = next(
                (
                    value
                    for value in template_section.get("values", [])
                    if _normalize_heading(value.get("heading")) == field_name
                ),
                None,
            )
            if not field_name or not template_value:
                logger.warning("Ignoring unknown key-value field on entity '%s'.", entity.get("title"))
                continue

            value_mode = template_value.get("mode")
            value_type = template_value.get("type")
            normalized_mode = str(value_mode or "").replace("’", "'").strip().casefold()
            if normalized_mode in {"static", "immutable", "don't change"}:
                continue

            content = entity_section.get("content")
            if not isinstance(content, dict):
                logger.warning(
                    "Key-value section '%s' on '%s' is not a dictionary.",
                    template_section.get("heading"),
                    entity.get("title"),
                )
                continue

            actual_field = next(
                (key for key in content if _normalize_heading(key) == field_name),
                template_value.get("heading"),
            )
            new_value, did_change = _apply_mode(
                content.get(actual_field, ""),
                update.get("content"),
                value_mode,
                value_type,
            )
            if did_change:
                content[actual_field] = new_value
                changed = True
            continue

        field_mode = template_section.get("mode")
        normalized_mode = str(field_mode or "").replace("’", "'").strip().casefold()
        if normalized_mode in {"static", "immutable", "don't change"}:
            continue
        if normalized_mode == "block":
            logger.warning("Block section '%s' has no key-value fields; skipping update.", template_section.get("heading"))
            continue

        new_content, did_change = _apply_mode(
            entity_section.get("content"),
            update.get("content"),
            field_mode,
            template_section.get("type"),
        )
        if did_change:
            entity_section["content"] = new_content
            changed = True

    return updated_entity if changed else None


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


def _created_section_content(template_section, generated_section):
    section_type = _doc_section_type(template_section.get("type"))
    mode = str(template_section.get("mode") or "").replace("’", "'").strip().casefold()
    generated_content = generated_section.get("content") if generated_section else None

    if mode in {"immutable", "don't change"}:
        return {} if section_type == "key_value_list" else ([] if section_type == "bullet_list" else "")
    if section_type == "key_value_list":
        generated_values = generated_content if isinstance(generated_content, dict) else {}
        normalized_values = {}
        for value in template_section.get("values", []):
            field_name = value.get("heading", "")
            value_mode = str(value.get("mode") or "").replace("’", "'").strip().casefold()
            if value_mode in {"immutable", "don't change"}:
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


def _build_new_entity_sections(entity_data, template_sections):
    title = str(entity_data.get("title", "")).strip()
    generated_sections = entity_data.get("sections", [])
    if not isinstance(generated_sections, list):
        generated_sections = []

    sections = [{"heading": "TITLE", "style": "TITLE", "type": "paragraph", "content": title}]
    for template_section in template_sections:
        generated_section = next(
            (
                section
                for section in generated_sections
                if isinstance(section, dict) and _same_tag_or_heading(section, template_section)
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
                "content": _created_section_content(template_section, generated_section),
            }
        )
    return sections


def run(gemini_client, truth_log, doc_meta, docs_service=None, doc_id=None, **kwargs):
    """Plans, updates, and creates collection entities from one Gemini call per category."""
    collections = doc_meta.get("collections", {}).get("items", {})
    categories_processed = 0
    pending_updates = []
    pending_creations = []

    logger.info(f"Processing {len(collections)} entity collection categor(ies).")

    for category in collections.values():
        category_title = category.get("title", "Untitled")
        template = category.get("template")
        if not template:
            logger.warning(f"Skipping collection '{category_title}': no template tab was found.")
            continue

        entities = category.get("items", {})
        template_sections = template.get("sections", [])
        payload = _category_payload(category, truth_log)
        category_updates, category_creations = _request_category_plan(gemini_client, payload)
        categories_processed += 1

        entities_by_title = {
            str(entity.get("title", title)).strip().casefold(): entity
            for title, entity in entities.items()
        }
        for entity_update in category_updates:
            if not isinstance(entity_update, dict):
                logger.warning("Ignoring malformed update in collection '%s'.", category_title)
                continue

            entity_title = str(entity_update.get("entity_title", "")).strip()
            entity = entities_by_title.get(entity_title.casefold())
            if not entity:
                logger.warning("Ignoring update for unknown entity '%s' in '%s'.", entity_title, category_title)
                continue

            section_updates = entity_update.get("section_updates", [])
            if not isinstance(section_updates, list):
                logger.warning("Ignoring malformed section updates for entity '%s'.", entity_title)
                continue

            updated_entity = _apply_entity_updates(entity, template_sections, section_updates)
            if updated_entity:
                pending_updates.append((category_title, entity_title, updated_entity))

        existing_titles = set(entities_by_title)
        parent_tab_id = category.get("tab_id")
        for entity_data in category_creations:
            if not isinstance(entity_data, dict):
                logger.warning("Ignoring malformed new entity in collection '%s'.", category_title)
                continue

            entity_title = str(entity_data.get("title", "")).strip()
            normalized_title = entity_title.casefold()
            if not entity_title:
                logger.warning("Ignoring a new entity without a title in '%s'.", category_title)
                continue
            if normalized_title in existing_titles:
                logger.info("Skipping existing entity '%s' in '%s'.", entity_title, category_title)
                continue
            if not parent_tab_id:
                logger.warning("Cannot create '%s': collection '%s' has no tabId.", entity_title, category_title)
                continue

            existing_titles.add(normalized_title)
            pending_creations.append(
                {
                    "category": category_title,
                    "parent_tab_id": parent_tab_id,
                    "title": entity_title,
                    "sections": _build_new_entity_sections(entity_data, template_sections),
                }
            )

    update_requests = []
    for category_title, entity_title, entity in pending_updates:
        tab_id = entity.get("tab_id")
        if not tab_id:
            raise ValueError(f"Cannot update entity '{entity_title}' in '{category_title}': tabId is missing.")

        update_requests.extend(
            docs_helper.build_clear_tab_request(tab_id=tab_id, end_index=entity.get("end_index", 1))
        )
        update_requests.extend(
            docs_helper.build_tab_content_requests(tab_id=tab_id, sections=entity.get("sections", []))
        )

    add_requests = [
        docs_helper.build_add_tab_request(entity["title"], entity["parent_tab_id"])
        for entity in pending_creations
    ]
    first_batch_requests = update_requests + add_requests
    created_entities = []
    entities_updated = 0

    if not first_batch_requests:
        logger.info("No entity updates or new entity pages were needed.")
    elif not docs_service or not doc_id:
        logger.warning("Entity changes were found, but docs_service or doc_id is missing; skipped Docs updates.")
    else:
        logger.info(
            f"Submitting one Google Docs batch with {len(update_requests)} update request(s) "
            f"and {len(add_requests)} new tab(s)."
        )
        response = docs_helper.execute_batch(docs_service=docs_service, doc_id=doc_id, requests=first_batch_requests)
        entities_updated = len(pending_updates)

        if pending_creations:
            replies = response.get("replies", []) if isinstance(response, dict) else []
            add_tab_replies = [reply["addDocumentTab"] for reply in replies if "addDocumentTab" in reply]
            if len(add_tab_replies) != len(pending_creations):
                raise RuntimeError(
                    f"Google Docs returned {len(add_tab_replies)} tab creation replies for "
                    f"{len(pending_creations)} new entity tab(s)."
                )

            content_requests = []
            for entity, add_tab_reply in zip(pending_creations, add_tab_replies):
                tab_id = add_tab_reply.get("tabProperties", {}).get("tabId")
                if not tab_id:
                    raise RuntimeError(f"Failed to retrieve the new tabId for entity '{entity['title']}'.")
                content_requests.extend(
                    docs_helper.build_tab_content_requests(tab_id=tab_id, sections=entity["sections"])
                )
                created_entities.append({"category": entity["category"], "title": entity["title"]})

            if content_requests:
                logger.info(f"Populating {len(created_entities)} new entity tab(s) in one Google Docs batch.")
                docs_helper.execute_batch(docs_service=docs_service, doc_id=doc_id, requests=content_requests)

    logger.info(
        f"Entity processing complete: {entities_updated} updated, {len(created_entities)} created "
        f"across {categories_processed} category/categories."
    )
    return {
        "categories_processed": categories_processed,
        "entities_updated": entities_updated,
        "entities_created": len(created_entities),
        "updated_entities": [
            {"category": category, "title": title} for category, title, _ in pending_updates
        ] if entities_updated else [],
        "created_entities": created_entities,
    }