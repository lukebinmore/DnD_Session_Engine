import copy
import json
import logging
import re

import docs_helper
import gemini_helper

logger = logging.getLogger("EntityUpdater")

ENTITY_UPDATE_PROMPT = """You are updating a D&D campaign's existing entity records from a new session Truth Log.

Use only facts supported by the Truth Log. Do not infer, invent, or rewrite facts just to improve prose.
Each entity is independent. Never move facts between entities. Return only updates that are supported by
the Truth Log and follow the supplied template modes and prompts.

Mode rules:
- Immutable or Don't Change: never update the section.
- Static: leave the existing value unchanged.
- Overwrite: return the complete replacement value only when the Truth Log provides a clear update.
- Append: return only new information, not a copy of the existing content.
- Block: apply the mode of each nested value; only return changed nested values.

Return strictly valid JSON with this exact shape:
{
  "updates": [
	{
	  "entity_title": "exact entity title",
	  "section_updates": [
		{
		  "section_tag": "template section tag, or null when absent",
		  "section_heading": "template section heading",
		  "field_name": "nested key-value field name, or null",
		  "content": "replacement/addition, or a list for bullet-list content"
		}
	  ]
	}
  ]
}

Return an empty updates list when there are no supported changes. Do not include unchanged or disallowed fields.
"""


def _normalize_heading(value):
    return re.sub(r"\s+", " ", str(value or "").strip().rstrip(":")).casefold()


def _same_tag_or_heading(left, right):
    left_tag = str(left.get("tag") or "").strip()
    right_tag = str(right.get("tag") or "").strip()
    if left_tag and right_tag:
        return left_tag == right_tag
    return _normalize_heading(left.get("heading")) == _normalize_heading(right.get("heading"))


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

    existing_text = "\n".join(str(item) for item in existing) if isinstance(existing, list) else str(existing or "")
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


def _prepare_category_payload(category, truth_log):
    template = category.get("template", {})
    template_sections = []
    for section in template.get("sections", []):
        template_sections.append(
            {
                "heading": section.get("heading"),
                "tag": section.get("tag"),
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
        )

    entities = []
    for title, entity in category.get("items", {}).items():
        entities.append(
            {
                "title": title,
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
        )

    return {
        "category": category.get("title", "Untitled"),
        "truth_log": truth_log,
        "template": template_sections,
        "entities": entities,
    }


def _request_category_updates(gemini_client, category_payload):
    user_content = (
        "Use the following collection template, existing entity data, and session Truth Log "
        "to identify allowed updates.\n\n"
        f"{json.dumps(category_payload, ensure_ascii=False, indent=2)}"
    )
    logger.info(
        f"Requesting entity updates for collection '{category_payload['category']}' "
        f"({len(category_payload['entities'])} entities)."
    )
    response = gemini_helper.generate_with_fallback(
        gemini_client=gemini_client,
        contents=user_content,
        config={
            "system_instruction": ENTITY_UPDATE_PROMPT,
            "response_mime_type": "application/json",
            "temperature": 0.2,
        },
    )

    try:
        result = json.loads(response.text)
    except (TypeError, json.JSONDecodeError) as e:
        raise ValueError(f"Gemini returned invalid JSON for collection '{category_payload['category']}'.") from e

    updates = result.get("updates") if isinstance(result, dict) else None
    if not isinstance(updates, list):
        raise ValueError(f"Gemini response for collection '{category_payload['category']}' has no updates list.")

    logger.info(
        f"Gemini returned updates for {len(updates)} entity/entities in collection "
        f"'{category_payload['category']}'."
    )
    return updates


def _find_template_section(template_sections, update):
    update_identity = {"tag": update.get("section_tag"), "heading": update.get("section_heading")}
    return next((section for section in template_sections if _same_tag_or_heading(section, update_identity)), None)


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
            current_value = content.get(actual_field, "")
            new_value, did_change = _apply_mode(
                current_value,
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
            logger.warning(
                "Block section '%s' has no key-value fields; skipping update.", template_section.get("heading")
            )
            continue

        current_content = entity_section.get("content")
        new_content, did_change = _apply_mode(
            current_content,
            update.get("content"),
            field_mode,
            template_section.get("type"),
        )
        if did_change:
            entity_section["content"] = new_content
            changed = True

    return updated_entity if changed else None


def run(gemini_client, truth_log, doc_meta, docs_service=None, doc_id=None, **kwargs):
    """Updates existing collection entities from the session Truth Log."""
    collections = doc_meta.get("collections", {}).get("items", {})
    categories_processed = 0
    pending_entities = []

    logger.info(f"Starting entity updates across {len(collections)} collection categor(ies).")

    for category in collections.values():
        category_title = category.get("title", "Untitled")
        template = category.get("template")
        entities = category.get("items", {})

        if not entities:
            logger.info(f"Skipping collection '{category_title}': no existing entity tabs.")
            continue
        if not template:
            logger.warning(f"Skipping collection '{category_title}': no template tab was found.")
            continue

        category_payload = _prepare_category_payload(category, truth_log)
        category_updates = _request_category_updates(gemini_client, category_payload)
        categories_processed += 1
        template_sections = template.get("sections", [])
        entities_by_title = {entity.get("title", title): entity for title, entity in entities.items()}

        for entity_update in category_updates:
            if not isinstance(entity_update, dict):
                logger.warning("Ignoring malformed entity update in collection '%s'.", category_title)
                continue

            entity_title = entity_update.get("entity_title")
            entity = entities_by_title.get(entity_title)
            if not entity:
                logger.warning(
                    "Ignoring update for unknown entity '%s' in collection '%s'.",
                    entity_title,
                    category_title,
                )
                continue

            section_updates = entity_update.get("section_updates", [])
            if not isinstance(section_updates, list):
                logger.warning("Ignoring malformed section updates for entity '%s'.", entity_title)
                continue

            updated_entity = _apply_entity_updates(entity, template_sections, section_updates)
            if updated_entity:
                pending_entities.append((category_title, entity_title, updated_entity))

    docs_requests = []
    for category_title, entity_title, entity in pending_entities:
        tab_id = entity.get("tab_id")
        if not tab_id:
            raise ValueError(f"Cannot update entity '{entity_title}' in '{category_title}': tabId is missing.")

        docs_requests.extend(
            docs_helper.build_clear_tab_request(
                tab_id=tab_id,
                end_index=entity.get("end_index", 1),
            )
        )
        docs_requests.extend(
            docs_helper.build_tab_content_requests(
                tab_id=tab_id,
                sections=entity.get("sections", []),
            )
        )

    if not docs_requests:
        logger.info("No entity changes were found; no Google Docs update is needed.")
    elif docs_service and doc_id:
        logger.info(
            f"Submitting one Google Docs batch for {len(pending_entities)} updated entity tab(s) "
            f"across {categories_processed} collection categor(ies)."
        )
        docs_helper.execute_batch(docs_service=docs_service, doc_id=doc_id, requests=docs_requests)
    else:
        logger.warning("Entity changes were found, but docs_service or doc_id is missing; skipped Google Docs update.")

    return {
        "categories_processed": categories_processed,
        "entities_updated": len(pending_entities),
        "updated_entities": [
            {"category": category_title, "title": entity_title} for category_title, entity_title, _ in pending_entities
        ],
    }
