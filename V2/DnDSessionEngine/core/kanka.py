from DnDSessionEngine.core.config import load_config
import requests
import logging

import json

logger = logging.getLogger(__name__)

KANKA_URL_BASE = "https://api.kanka.io/1.0/campaigns/"
KANKA_HEADERS = {"Accept": "application/json", "Authorization": "Bearer ", "Content-Type": "application/json"}

kanka_url = KANKA_URL_BASE

KANKA_MODULES = [
    "characters",
    "locations",
    "organisations",
    "items",
    "events",
    "quests",
    "journals",
    "families",
    "notes",
]

DISCARD_FIELDS = {
    "is_private",
    "created_at",
    "updated_at",
    "created_by",
    "updated_by",
    "urls",
    "image",
    "image_uuid",
    "image_full",
    "image_thumb",
    "has_custom_image",
    "focus_x",
    "focus_y",
    "header_full",
    "header_uuid",
    "has_custom_header",
    "tooltip",
    "is_template",
    "is_personality_visible",
    "is_personality_pinned",
    "is_appearance_pinned",
    "is_attributes_private",
    "status_id",
    "entry_parsed",
    "private_races",
    "private_families",
    "visibility_id",
    "layout_id",
    "permissions",
    "settings",
    "sync",
    "position",
    "is_pinned",
    "is_star",
}

KANKA_ENTITY_SCHEMA = {
    "_meta": {
        "rules": [
            "All foreign keys ending in '_id' or named 'locations', 'races', 'families' require the target module's 'id'.",
            "'tags' and nested 'posts' require the parent or target's global 'entity_id'.",
            "Do not hallucinate IDs; only link to IDs present in campaign context.",
            "Dates should be formatted as freeform strings or in-universe calendar strings.",
            "Fields marked 'optional' can be omitted or set to null if unknown.",
        ]
    },
    "characters": {
        "required": ["name"],
        "fields": {
            "name": {"type": "string", "desc": "Character's full name"},
            "entry": {"type": "string", "desc": "Main biography and narrative summary"},
            "title": {"type": "string", "desc": "Honorific, military rank, or social title"},
            "type": {"type": "string", "desc": "Role classification (e.g., NPC, PC, Merchant, Villain)"},
            "age": {"type": "string", "desc": "Age descriptor (e.g., '35', 'Unknown', 'Ancient')"},
            "sex": {"type": "string", "desc": "Gender/sex identity"},
            "pronouns": {"type": "string", "desc": "e.g., 'they/them', 'he/him', 'she/her'"},
            "status": {
                "type": "string",
                "desc": "Operational state (e.g., 'Alive', 'Deceased', 'Missing', 'Imprisoned')",
            },
            "is_dead": {"type": "boolean", "desc": "True if deceased, False otherwise"},
            "locations": {"type": "list[int]", "desc": "List of Location module IDs"},
            "races": {"type": "list[int]", "desc": "List of Race module IDs"},
            "families": {"type": "list[int]", "desc": "List of Family module IDs"},
            "tags": {"type": "list[int]", "desc": "List of Tag global entity_ids"},
            "traits": {
                "type": "list[object]",
                "schema": {
                    "name": "string (trait label)",
                    "entry": "string (description)",
                    "section": "'appearance' | 'personality'",
                },
            },
            "posts": {
                "type": "list[object]",
                "schema": {
                    "name": "string (article title, e.g., 'Backstory', 'Session 14 Encounter')",
                    "entry": "string (article content)",
                },
            },
        },
    },
    "locations": {
        "required": ["name"],
        "fields": {
            "name": {"type": "string", "desc": "Location name"},
            "type": {"type": "string", "desc": "Settlement type (e.g., City, Dungeon, Tavern, Kingdom, District)"},
            "entry": {"type": "string", "desc": "Geographical/lore description"},
            "parent_location_id": {"type": "int", "desc": "Location module ID of enclosing parent location"},
            "is_underwater": {"type": "boolean", "desc": "True if aquatic"},
            "tags": {"type": "list[int]", "desc": "List of Tag global entity_ids"},
            "posts": {"type": "list[object]", "schema": {"name": "string", "entry": "string"}},
        },
    },
    "organisations": {
        "required": ["name"],
        "fields": {
            "name": {"type": "string", "desc": "Faction, guild, military, or religious order name"},
            "type": {"type": "string", "desc": "e.g., 'Thieves Guild', 'Holy Order', 'Mercenary Band'"},
            "entry": {"type": "string", "desc": "History, goals, and structure"},
            "organisation_id": {"type": "int", "desc": "Organisation module ID of parent organisation"},
            "location_id": {"type": "int", "desc": "Location module ID of headquarters/seat"},
            "tags": {"type": "list[int]", "desc": "List of Tag global entity_ids"},
            "posts": {"type": "list[object]", "schema": {"name": "string", "entry": "string"}},
        },
    },
    "items": {
        "required": ["name"],
        "fields": {
            "name": {"type": "string", "desc": "Item or artifact name"},
            "type": {"type": "string", "desc": "e.g., 'Weapon', 'Relic', 'Potion', 'Document'"},
            "entry": {"type": "string", "desc": "Appearance, magical properties, or history"},
            "price": {"type": "string", "desc": "Monetary value (e.g., '250 gp', 'Priceless')"},
            "size": {"type": "string", "desc": "Size classification (e.g., 'Tiny', 'Medium')"},
            "weight": {"type": "string", "desc": "Weight measurement (e.g., '3 lbs', '15 kg')"},
            "character_id": {"type": "int", "desc": "Character module ID currently holding the item"},
            "location_id": {"type": "int", "desc": "Location module ID where item resides (if unheld)"},
            "tags": {"type": "list[int]", "desc": "List of Tag global entity_ids"},
            "posts": {"type": "list[object]", "schema": {"name": "string", "entry": "string"}},
        },
    },
    "quests": {
        "required": ["name"],
        "fields": {
            "name": {"type": "string", "desc": "Quest or objective title"},
            "type": {"type": "string", "desc": "e.g., 'Main Quest', 'Bounty', 'Side Quest'"},
            "entry": {"type": "string", "desc": "Objectives, steps, and reward details"},
            "quest_id": {"type": "int", "desc": "Quest module ID of parent quest"},
            "character_id": {"type": "int", "desc": "Character module ID of quest giver"},
            "is_completed": {"type": "boolean", "desc": "True if resolved/completed"},
            "tags": {"type": "list[int]", "desc": "List of Tag global entity_ids"},
            "posts": {"type": "list[object]", "schema": {"name": "string", "entry": "string"}},
        },
    },
    "events": {
        "required": ["name"],
        "fields": {
            "name": {"type": "string", "desc": "Event or battle name"},
            "type": {"type": "string", "desc": "e.g., 'Battle', 'Festival', 'Assassination', 'Treaty'"},
            "date": {"type": "string", "desc": "In-universe or session timeline date"},
            "entry": {"type": "string", "desc": "What occurred during the event"},
            "location_id": {"type": "int", "desc": "Location module ID where event took place"},
            "event_id": {"type": "int", "desc": "Event module ID of parent event series"},
            "tags": {"type": "list[int]", "desc": "List of Tag global entity_ids"},
            "posts": {"type": "list[object]", "schema": {"name": "string", "entry": "string"}},
        },
    },
    "journals": {
        "required": ["name"],
        "fields": {
            "name": {"type": "string", "desc": "Session or log title"},
            "type": {"type": "string", "desc": "e.g., 'Session Log', 'Letter', 'Diary'"},
            "date": {"type": "string", "desc": "Session date or in-game date"},
            "entry": {"type": "string", "desc": "Log contents or narrative recount"},
            "character_id": {"type": "int", "desc": "Character module ID of author/perspective"},
            "location_id": {"type": "int", "desc": "Location module ID where written/occurred"},
            "tags": {"type": "list[int]", "desc": "List of Tag global entity_ids"},
            "posts": {"type": "list[object]", "schema": {"name": "string", "entry": "string"}},
        },
    },
}


def filter_entity(raw):
    clean = {}
    for key, value in raw.items():
        if key in DISCARD_FIELDS:
            continue

        if not isinstance(value, list):
            clean[key] = value
            continue

        if value and not isinstance(value[0], dict):
            clean[key] = value
            continue

        clean_value = [
            {k: v for k, v in item.items() if k not in DISCARD_FIELDS} for item in value if isinstance(item, dict)
        ]
        if clean_value:
            clean[key] = clean_value
    return clean


def pull_all_data():
    campaign_data = {}

    for module in KANKA_MODULES:
        try:
            records = kanka_get(f"{module}?related=1")
            campaign_data[module] = [filter_entity(record) for record in records]
        except Exception as e:
            logger.error(f"Could not load module '{module}'")
            raise e

    return campaign_data


def kanka_get(url="", timeout=10.0, *args, **kwargs):
    url = kanka_url + url
    response = requests.get(url=url, headers=KANKA_HEADERS, timeout=timeout, *args, **kwargs)
    response.raise_for_status()
    body = response.json()["data"]
    return body


def initialise_kanka():
    KANKA_HEADERS["Authorization"] += load_config("Kanka Token")
    global kanka_url
    kanka_url += f"{load_config("Kanka Campaign ID")}/"

    try:
        logger.info("Verifying Kanka API token...")
        response = kanka_get()
        logger.info(f"Kanka API token verified successfully! Campaign: {response['name']}")

        logger.info("Pulling entities from campaign...")
        campaign_data = pull_all_data()
        logger.info("Entities pulled successfully!")

        return campaign_data

    except Exception as e:
        logger.error("Failed to initialise Kanka!")
        raise e
