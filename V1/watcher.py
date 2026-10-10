import os
import sys
import json
import io
import time
import mimetypes
import importlib
import re
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google import genai
from google.genai import types

BASE_DIR = "/app" if os.path.exists("/app") else "."
sys.path.insert(0, BASE_DIR)

SERVICE_ACCOUNT_PATH = os.path.join(BASE_DIR, "service_account.json")
PROMPT_PATH = os.path.join(BASE_DIR, "prompt.txt")

try:
    import doc_updater
except ImportError:
    doc_updater = None


def load_settings():
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    model_name = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash").strip()
    try:
        interval = int(os.environ.get("CHECK_INTERVAL_SECONDS", "60"))
    except ValueError:
        interval = 60

    raw_folders = os.environ.get("CAMPAIGN_FOLDERS", "")
    campaign_folders = [f.strip() for f in raw_folders.split(",") if f.strip()]

    return {
        "gemini_api_key": gemini_key,
        "gemini_model": model_name,
        "check_interval_seconds": interval,
        "campaign_folders": campaign_folders,
    }


creds = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_PATH, scopes=["https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/documents"]
)
drive_service = build("drive", "v3", credentials=creds)
docs_service = build("docs", "v1", credentials=creds)


def parse_line_instruction(raw_text):
    """
    Parses a template line to isolate label/tags from bracketed instructions in ().
    Preserves brackets [...] like [gk5] or [0j9].
    Matches strictly at most one pair of () at the end of the line.
    """
    clean_text = raw_text.strip()
    match = re.search(r"^(.*?)\s*\(([^()]+)\)\s*$", clean_text)
    if match:
        label = match.group(1).strip()
        instruction = match.group(2).strip()
        return label, instruction
    return clean_text, ""


def inspect_doc(doc_id):
    """
    Scans the Google Doc hierarchy:
      - root_tab_id: The top-level root tab (Depth 0)
      - available_sections: Direct child tabs inside Root (Depth 1)
      - tabs_info: Map of tab_title -> {tab_id, parent_tab_id, depth}
      - templates_dict: Map of template_name -> field definitions
      - latest_session_num: Highest session number found
    """
    doc = docs_service.documents().get(documentId=doc_id, includeTabsContent=True).execute()
    tabs_info = {}
    templates_dict = {}
    session_numbers = []
    available_sections = []
    root_tab_id = None

    raw_tabs = doc.get("tabs", [])
    if raw_tabs:
        root_tab_id = raw_tabs[0].get("tabProperties", {}).get("tabId")

    def scan(tab_list, parent_id=None, depth=0):
        for tab in tab_list:
            props = tab.get("tabProperties", {})
            tab_id = props.get("tabId")
            title = props.get("title", "").strip()

            if title:
                tabs_info[title] = {"tab_id": tab_id, "parent_tab_id": parent_id, "depth": depth}

                # Direct child tabs of Root (depth 1) act as available parent sections
                if (
                    depth == 1
                    and not title.lower().endswith("template")
                    and not re.search(r"^session\s*\d+", title, re.IGNORECASE)
                ):
                    available_sections.append(title)

                sess_match = re.search(r"^Session\s*(\d+)", title, re.IGNORECASE)
                if sess_match:
                    session_numbers.append(int(sess_match.group(1)))

            # Discover templates regardless of depth
            if title.lower().endswith("template"):
                type_key = re.sub(r"\btemplate\b", "", title, flags=re.IGNORECASE).strip().lower()
                fields = []
                content = tab.get("documentTab", {}).get("body", {}).get("content", [])

                for elem in content:
                    p = elem.get("paragraph")
                    if not p:
                        continue
                    text = "".join(e.get("textRun", {}).get("content", "") for e in p.get("elements", [])).strip()
                    if not text:
                        continue

                    label, instruction = parse_line_instruction(text)
                    fields.append(
                        {
                            "raw_line": text,
                            "label": label,
                            "instruction": instruction,
                            "requires_link": "link" in instruction.lower(),
                        }
                    )

                templates_dict[type_key] = fields

            if "childTabs" in tab:
                scan(tab["childTabs"], parent_id=tab_id, depth=depth + 1)

    scan(raw_tabs, parent_id=None, depth=0)
    latest_session_num = max(session_numbers) if session_numbers else 1

    return tabs_info, templates_dict, available_sections, root_tab_id, latest_session_num


def get_latest_prompt(tabs_list, templates_dict, available_sections, latest_session_num, file_name):
    with open(PROMPT_PATH, "r") as f:
        prompt_text = f.read()

    entity_types = [k for k in templates_dict.keys() if k != "session"]

    prompt_text = prompt_text.replace("{tabs_list}", json.dumps(tabs_list, indent=2))
    prompt_text = prompt_text.replace("{templates_dict}", json.dumps(templates_dict, indent=2))
    prompt_text = prompt_text.replace("{entity_types}", json.dumps(entity_types))
    prompt_text = prompt_text.replace("{available_sections}", json.dumps(available_sections))
    prompt_text = prompt_text.replace("{latest_session_num}", str(latest_session_num))
    prompt_text = prompt_text.replace("{file_name}", file_name)
    return prompt_text


def process_file(file_meta, campaign_name, doc_id, gemini_client, model_name):
    file_id = file_meta["id"]
    file_name = file_meta["name"]
    local_path = f"/tmp/{file_name}"
    audio_file = None

    try:
        print(f"[{campaign_name}] Streaming {file_name} from Drive...")
        req = drive_service.files().get_media(fileId=file_id)
        with io.FileIO(local_path, "wb") as fh:
            downloader = MediaIoBaseDownload(fh, req)
            done = False
            while not done:
                _, done = downloader.next_chunk()

        mime_type = mimetypes.guess_type(file_name)[0] or "audio/mp4"
        print(f"[{campaign_name}] Ingesting into Gemini...")
        audio_file = gemini_client.files.upload(file=local_path, config=types.UploadFileConfig(mime_type=mime_type))

        tabs_info, templates_dict, available_sections, root_tab_id, latest_session_num = inspect_doc(doc_id)
        prompt = get_latest_prompt(
            list(tabs_info.keys()), templates_dict, available_sections, latest_session_num, file_name
        )

        print(f"[{campaign_name}] Gemini processing audio using {model_name}...")

        max_retries = 3
        backoff_seconds = 10
        response = None

        for attempt in range(1, max_retries + 1):
            try:
                response = gemini_client.models.generate_content(
                    model=model_name,
                    contents=[audio_file, prompt],
                    config=types.GenerateContentConfig(response_mime_type="application/json"),
                )
                break
            except Exception as api_err:
                err_str = str(api_err)
                if (
                    "503" in err_str or "UNAVAILABLE" in err_str or "RESOURCE_EXHAUSTED" in err_str
                ) and attempt < max_retries:
                    print(
                        f"[{campaign_name}] Gemini API spike/busy (attempt {attempt}/{max_retries}). Retrying in {backoff_seconds}s..."
                    )
                    time.sleep(backoff_seconds)
                    backoff_seconds *= 2
                else:
                    raise api_err

        extracted = json.loads(response.text)

        global doc_updater
        if doc_updater:
            doc_updater = importlib.reload(doc_updater)
        else:
            import doc_updater

        doc_updater.apply_updates(
            docs_service, doc_id, extracted, tabs_info, templates_dict, available_sections, root_tab_id
        )

        drive_service.files().update(fileId=file_id, body={"name": f"[PROCESSED] {file_name}"}).execute()
        print(f"[{campaign_name}] Successfully processed {file_name}!")

    except Exception as e:
        print(f"[{campaign_name}] Error during processing of {file_name}: {e}")

    finally:
        if os.path.exists(local_path):
            os.remove(local_path)
        if audio_file:
            try:
                gemini_client.files.delete(name=audio_file.name)
            except Exception:
                pass


def discover_and_process():
    settings = load_settings()
    if not settings["gemini_api_key"] or not settings["campaign_folders"]:
        return

    gemini_client = genai.Client(api_key=settings["gemini_api_key"])
    model_name = settings["gemini_model"]

    for campaign_folder_id in settings["campaign_folders"]:
        try:
            folder_meta = drive_service.files().get(fileId=campaign_folder_id, fields="id, name, trashed").execute()

            if folder_meta.get("trashed"):
                continue

            campaign_name = folder_meta.get("name")
            q_children = f"'{campaign_folder_id}' in parents and trashed = false"
            children = (
                drive_service.files().list(q=q_children, fields="files(id, name, mimeType)").execute().get("files", [])
            )

            doc_id = None
            recordings_folder_id = None

            for item in children:
                mime = item["mimeType"]
                name = item["name"]
                if (
                    mime == "application/vnd.google-apps.document"
                    and name.strip().lower() == campaign_name.strip().lower()
                ):
                    doc_id = item["id"]
                elif mime == "application/vnd.google-apps.folder" and name.strip().lower() == "recordings":
                    recordings_folder_id = item["id"]

            if not doc_id or not recordings_folder_id:
                continue

            q_audio = f"'{recordings_folder_id}' in parents and trashed = false and not name contains '[PROCESSED]'"
            audio_files = (
                drive_service.files().list(q=q_audio, fields="files(id, name, mimeType)").execute().get("files", [])
            )

            for audio_file in audio_files:
                name = audio_file["name"].lower()
                if name.endswith((".m4a", ".mp3", ".wav", ".aac", ".ogg")):
                    print(f"[{campaign_name}] Detected new recording: {audio_file['name']}")
                    process_file(audio_file, campaign_name, doc_id, gemini_client, model_name)

        except Exception as e:
            print(f"Error scanning folder {campaign_folder_id}: {e}")


if __name__ == "__main__":
    print("D&D Session Engine started. Watching folders using Unraid environment variables...")
    while True:
        try:
            discover_and_process()
        except Exception as e:
            print(f"Watcher loop error: {e}")
        settings = load_settings()
        time.sleep(settings["check_interval_seconds"])
