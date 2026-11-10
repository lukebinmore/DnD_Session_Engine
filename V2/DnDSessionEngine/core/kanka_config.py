KANKA_DISREGARD_ENTRIES = [
    "entry_parsed",
    "tooltip",
    "image",
    "focus_x",
    "focus_y",
    "image_full",
    "image_thumb",
    "has_custom_image",
    "image_uuid",
    "header_full",
    "header_uuid",
    "has_custom_header",
    "is_private",
    "is_template",
    "is_attributes_private",
    "status",
    "tags",
    "created_at",
    "created_by",
    "updated_at",
    "updated_by",
    "urls",
    "character_id",
    "attributes",
    "entity_events",
    "reminders",
    "relations",
    "inventory",
    "entity_abilities",
    "parents",
    "children",
    "author",
    "author_id",
    "calendar_id",
    "calendar_year",
    "calendar_month",
    "calendar_day",
    "calendar_reminder_length",
    "visibility_id",
    "_alias",
    "_file",
    "_link",
    "is_pinned",
    "type_id",
    "sync",
    "is_personality_visible",
    "is_personality_pinned",
    "is_appearance_pinned",
]

KANKA_MODULES = [
    "characters",
    "locations",
    "families",
    "organisations",
    "items",
    "events",
    "creatures",
    "journals",
]

NAME = {
    "type": "string",
    "required": "yes",
    "action": "default",
    "description": "The name representing the entity",
}

ALIASES = {
    "type": "array of strings",
    "required": "no",
    "action": "append",
    "description": "A list of aliases used by this entity. e.g. old nic, the great old one, Tash (short for lady umbratash), etc",
}

ENTRY = {
    "type": "string",
    "required": "yes",
    "action": "default",
    "description": "A thematic description based on what is known about this entity",
}

TITLE = {
    "type": "string",
    "reqired": "yes",
    "action": "default",
    "description": "A short descriptive title for the entity, e.g. Dwarvern Mayor of Whoosville",
}

TYPE = {
    "type": "string",
    "required": "yes",
    "action": "default",
    "description": "A one or two word description of the entity type, e.g. NPC, Town, Capital City, Sword, etc",
}

LOCATIONS = {
    "type": "array of integers",
    "required": "no",
    "action": "append",
    "description": "A list of location ids (not entity_id) that are relevent to this entity, e.g. hometown of a character, region an organisation operates in, etc",
}

STATUS_ID = {
    "type": "integer",
    "required": "no",
    "action": "default",
    "description": "The status ID for this entity. 1=Alive, 2=Missing, 3=Deceased, 5=Extinct, 6=Destroyed",
}

PARENT_ID = {
    "type": "integer",
    "required": "no",
    "action": "default",
    "description": "The entity_id (not id) of any parent entity. If an event occurs because of or is located in another event, the initial event is the parent. e.g A tavern's parent_id would be the town it's located in.",
}

KANKA_TEMPLATES = {
    "characters": {
        "name": NAME,
        "aliases": ALIASES,
        "entry": ENTRY,
        "title": TITLE,
        "age": {
            "type": "string",
            "required": "no",
            "action": "default",
            "description": "The age of the character (or rough estimate / simple description) if known, e.g. 40, 40ish, hundreds of years old",
        },
        "sex": {
            "type": "string",
            "required": "no",
            "action": "fill if empty",
            "description": "The gender of the character if known, e.g Male, Female, Unisex, Non-Binary, etc",
        },
        "type": TYPE,
        "families": {
            "type": "array of integers",
            "required": "no",
            "action": "append",
            "description": "A list of familiy id's (not parent_id) this character is part of",
        },
        "locations": LOCATIONS,
        "personality": {
            "type": "array of string touple pairs",
            "required": "yes",
            "action": "default",
            "description": "A list of personality descriptor names and values. e.g. [('attitude', 'Calm and collected'), ('Fears', 'Snakes'), ('Goals', 'To become a king')] etc",
        },
        "appearance": {
            "type": "array of string touple pairs",
            "required": "yes",
            "action": "default",
            "description": "A list of appearance descriptor names and values. e.g. [('Hair', 'Short and brown'), ('Height', '6ft Tall'), ('Build', 'Heavyset with a barrel chest'), ('Race', 'Pale skinned Human')] etc",
        },
        "status_id": STATUS_ID,
    },
    "locations": {
        "name": NAME,
        "aliases": ALIASES,
        "entry": ENTRY,
        "title": TITLE,
        "type": TYPE,
        "parent_id": PARENT_ID,
        "status_id": STATUS_ID,
    },
    "families": {
        "name": NAME,
        "aliases": ALIASES,
        "entry": ENTRY,
        "type": TYPE,
        "parent_id": PARENT_ID,
        "locations": LOCATIONS,
        "status_id": STATUS_ID,
    },
    "organisations": {
        "name": NAME,
        "aliases": ALIASES,
        "entry": ENTRY,
        "type": TYPE,
        "parent_id": PARENT_ID,
        "locations": LOCATIONS,
        "status_id": STATUS_ID,
    },
    "items": {
        "name": NAME,
        "aliases": ALIASES,
        "entry": ENTRY,
        "type": TYPE,
        "locations": LOCATIONS,
        "creators": {
            "type": "array of integers",
            "required": "no",
            "action": "default",
            "description": "A list of the ids (not entity_id) of any known creators of this item",
        },
        "price": {
            "type": "string",
            "required": "no",
            "action": "default",
            "description": "The price of the item if known",
        },
        "size": {
            "type": "string",
            "required": "no",
            "action": "default",
            "description": "The size of the item if known",
        },
        "weight": {
            "type": "string",
            "required": "no",
            "action": "default",
            "description": "The items weight if known",
        },
    },
    "events": {
        "name": NAME,
        "aliases": ALIASES,
        "entry": ENTRY,
        "type": TYPE,
        "date": {
            "type": "string",
            "required": "no",
            "action": "default",
            "description": "The fictional (not real) date that this event occured if known, e.g. 100 years ago, In centuries past, During Morganah's reign, 5000BC, etc",
        },
        "locations": LOCATIONS,
        "parent_id": PARENT_ID,
    },
    "creatures": {
        "name": NAME,
        "aliases": ALIASES,
        "entry": ENTRY,
        "type": TYPE,
        "parent_id": PARENT_ID,
        "locations": LOCATIONS,
        "status_id": STATUS_ID,
    },
}
