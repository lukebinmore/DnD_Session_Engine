from DnDSessionEngine.core.theme import con
from DnDSessionEngine.core.config import load_config, MANIFEST_PATH, ENTITIES_DIR
from DnDSessionEngine.core.file_manager import dump_to_file
from DnDSessionEngine.core.kanka_config import KANKA_MODULES, KANKA_DISREGARD_ENTRIES
from rich.live import Live
import time
import html
import os
import re
import requests
import json
import logging

logger = logging.getLogger(__name__)

KANKA_RATE_LIMIT_DELAY = 30
KANKA_URL_BASE = "https://api.kanka.io/1.0/campaigns/"
KANKA_HEADERS = {"Accept": "application/json", "Authorization": "Bearer ", "Content-Type": "application/json"}

kanka_url = KANKA_URL_BASE


def build_campaign_data(campaign_data):
    logger.info("Building campaign data json files...")
    for module, records in campaign_data.items():
        for record in records:
            record_id = record.get("entity_id")
            name = record.get("name")

            if not record_id or not name:
                continue

            file_name = f"{record_id}.json"
            entity_file_path = ENTITIES_DIR / file_name
            dump_to_file(record, entity_file_path, f"{module} {name} ({record_id})")
    logger.info("Campaign json data files build successfully!")


def create_summary(entity):
    title = entity.get("title")
    entity_type = entity.get("type")

    descriptor_parts = []
    if title:
        descriptor_parts.append(str(title).strip())
    if entity_type:
        descriptor_parts.append(f"({str(entity_type).strip()})")

    descriptor = " ".join(descriptor_parts).strip()

    raw_entry = entity.get("entry", "")
    first_sentence = ""
    if raw_entry:
        clean_text = re.sub(r"<[^>]+>", "", raw_entry)
        clean_text = html.unescape(clean_text).strip()
        match = re.search(r"^,*?[.!?](?:\s|$)", clean_text)
        if match:
            first_sentence = match.group(0).strip()
        else:
            first_sentence = clean_text[:120].strip()

    if descriptor and first_sentence:
        return f"{descriptor} - {first_sentence}"
    if descriptor:
        return descriptor
    if first_sentence:
        return first_sentence

    return "No description provided."


def build_manifest_index(manifest):
    index_lines = []

    for eid, value in manifest.items():
        id = value.get("id")
        module = value.get("module")
        name = value.get("name", "").strip()
        aliases = value.get("aliases")
        summary = value.get("summary") or ""

        if not name:
            continue

        clean_summary = summary.replace("\n", " ").strip()
        index_lines.append(
            f"- ID: {id} | Entity ID: {eid} | Module: {module} | Name: {name} | Aliases: {aliases} | Summary: {clean_summary}"
        )

    manifest_index = "\n".join(index_lines)
    return manifest_index


def build_manifest(campaign_data):
    logger.info("Building campaign data manifest...")
    manifest = {}

    for module, records in campaign_data.items():
        for record in records:
            record_id = record.get("id")
            eid = record.get("entity_id")
            name = record.get("name")
            aliases = record.get("aliases", [])

            if not record_id or not name:
                continue

            manifest[eid] = {
                "name": name,
                "aliases": aliases,
                "id": record_id,
                "entity_id": record.get("entity_id"),
                "module": module,
                "type": record.get("type"),
                "summary": create_summary(record),
            }

    dump_to_file(manifest, MANIFEST_PATH, "manifest")
    logger.info("Built campaign data manifest successfully!")
    return manifest


def filter_entity(raw, module=None):
    clean = {}
    if module:
        clean["module"] = module
    for key, value in raw.items():
        if key in KANKA_DISREGARD_ENTRIES:
            continue

        if value in [None, "", [], {}]:
            continue

        if key == "entity_assets":
            clean["aliases"] = [a["name"] for a in value if a.get("type_id") == 3]
            continue

        if key == "traits":
            appearance = [[t.get("name"), t.get("entry")] for t in value if t.get("section") == "appearance"]
            personality = [[t.get("name"), t.get("entry")] for t in value if t.get("section") == "personality"]
            if appearance:
                clean["appearance"] = appearance
            if personality:
                clean["personality"] = personality
            if not appearance and not personality:
                clean[key] = value
            continue

        if key == "posts":
            clean["posts"] = [{"name": e.get("name"), "entry": e.get("entry")} for e in value]

        if isinstance(value, str):
            clean[key] = value.replace("<p>", "").replace("</p>", "").strip("\"'“”‘’")
            continue

        if isinstance(value, list):
            cleaned_list = []
            for item in value:
                if isinstance(item, dict):
                    cleaned_list.append(filter_entity(item))
                else:
                    cleaned_list.append(item)
            if cleaned_list:
                clean[key] = cleaned_list
            continue

        if isinstance(value, dict):
            cleaned_dict = filter_entity(value)
            if cleaned_dict:
                clean[key] = cleaned_dict
            continue

        clean[key] = value
    return clean


def get_kanka_data():
    campaign_data = {}
    campaign_data_orig = {}
    logger.info("Pulling entities from campaign...")
    for module in KANKA_MODULES:
        try:
            records = kanka_get(f"{module}?related=1")
            campaign_data_orig[module] = [record for record in records]
            campaign_data[module] = [filter_entity(record, module) for record in records]
        except Exception as e:
            logger.error(f"Could not load module '{module}'")
            raise e
    logger.info("Entities pulled successfully!")

    manifest = build_manifest(campaign_data_orig)
    build_campaign_data(campaign_data)
    return manifest


def kanka_post(url="", data=None, timeout=10.0, mode="POST", *args, **kwargs):
    url = kanka_url + url
    data = json.dumps(data, default=str)

    upload = requests.post if mode == "POST" else requests.patch if mode == "PATCH" else requests.put
    while True:
        try:
            response = upload(url=url, headers=KANKA_HEADERS, data=data, timeout=timeout, *args, **kwargs)
            response.raise_for_status()

            if response.ok:
                break
        except requests.exceptions.HTTPError as e:
            processed = process_http_error(0, data)
            if not isinstance(processed, bool):
                data = processed
            if not processed:
                raise e

    return response.json().get("data", {})


def kanka_get(url="", timeout=10.0, *args, **kwargs):
    next_url = kanka_url + url
    all_data = []
    while next_url:
        try:
            response = requests.get(url=next_url, headers=KANKA_HEADERS, timeout=timeout, *args, **kwargs)
            response.raise_for_status()
            payload = response.json()
            data = payload.get("data")

            if not isinstance(data, list):
                return data

            all_data.extend(data)
            next_url = payload.get("link", {}).get("next")
        except requests.exceptions.HTTPError as e:
            if not process_http_error(e):
                raise e

    return all_data


def process_http_error(error, obj=None):
    if not error.get("response", {}).get("status_code"):
        print(error)
        return False

    status_code = error.response.status_code
    if status_code == 429:
        delay = KANKA_RATE_LIMIT_DELAY
        live = Live(console=con, transient=True)
        live.start()
        for _ in range(1, delay + 1):
            live.update(f"[warning]Kanka rate limit exceeded! Waiting for {delay} seconds before retry...[/]")
            time.sleep(1)
            delay += -1
        live.stop()
        return True
    if status_code == 422:
        logger.error("Upload Failed, incorrect payload format!")
        if obj:
            with open("PAYLOAD.json", "w") as file:
                json.dumps(obj, file)
            con.print("Payload saved to 'PAYLOAD.json'.", type="highlight")
            con.print(
                "Please update and safe the file and press enter. if the payload is not fixable, enter any value: ",
                style="menu.key",
            )
            response = input()
            if not response:
                with open("PAYLOAD.json", "r") as file:
                    obj = json.loads(file)
                    os.remove("PAYLOAD.json")
                    return obj
            return False
    else:
        print(error)
    return False


def initialise_kanka():
    logger.info("Initialising Kanka...")
    KANKA_HEADERS["Authorization"] += load_config("Kanka Token")
    global kanka_url
    kanka_url += f"{load_config("Kanka Campaign ID")}/"

    try:
        response = kanka_get()
        logger.info(f"Kanka API token verified successfully! Campaign: {response['name']}")
        logger.info("Initialising Kanka, Done!")

    except Exception as e:
        logger.error("Failed to initialise Kanka!")
        raise e
