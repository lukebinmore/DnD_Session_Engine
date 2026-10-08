import os
import sys
import json
import io
import time
import mimetypes
import importlib
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google import genai
from google.genai import types

BASE_DIR = "/app" if os.path.exists("/app") else "."
sys.path.insert(0, BASE_DIR)

SERVICE_ACCOUNT_PATH = os.path.join(BASE_DIR, "service_account.json")
PROMPT_PATH = os.path.join(BASE_DIR, "prompt.txt")

# Dynamically import external doc_updater
try:
    import doc_updater
except ImportError:
    doc_updater = None


def load_settings():
    """Reads configuration directly from Unraid environment variables."""
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()

    try:
        interval = int(os.environ.get("CHECK_INTERVAL_SECONDS", "60"))
    except ValueError:
        interval = 60

    raw_folders = os.environ.get("CAMPAIGN_FOLDERS", "")
    campaign_folders = [f.strip() for f in raw_folders.split(",") if f.strip()]

    return {"gemini_api_key": gemini_key, "check_interval_seconds": interval, "campaign_folders": campaign_folders}


def get_latest_prompt(tabs_list, templates_dict):
    """Re-reads prompt.txt fresh from disk each time."""
    with open(PROMPT_PATH, "r") as f:
        prompt_template = f.read()
    return prompt_template.format(tabs_list=json.dumps(tabs_list), templates_dict=json.dumps(templates_dict))


# Authenticate Google APIs
creds = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_PATH, scopes=["https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/documents"]
)
drive_service = build("drive", "v3", credentials=creds)
docs_service = build("docs", "v1", credentials=creds)


def inspect_doc(doc_id):
    """Inspects the Google Doc for existing tab names and template definitions."""
    doc = docs_service.documents().get(documentId=doc_id, includeTabsContent=True).execute()
    tabs_list = []
    templates_dict = {}

    def scan(tab_list):
        for tab in tab_list:
            props = tab.get("tabProperties", {})
            title = props.get("title", "").strip()
            if title:
                tabs_list.append(title)
            if title.lower().endswith("template"):
                type_key = title.lower().replace("template", "").strip()
                headings = []
                content = tab.get("documentTab", {}).get("body", {}).get("content", [])
                for elem in content:
                    p = elem.get("paragraph")
                    if p:
                        text = "".join(e.get("textRun", {}).get("content", "") for e in p.get("elements", [])).strip()
                        style = p.get("paragraphStyle", {}).get("namedStyleType", "")
                        if text.startswith("#") or text.endswith(":") or "HEADING" in style:
                            clean = text.lstrip("#").rstrip(":").strip()
                            if clean and clean not in headings:
                                headings.append(clean)
                templates_dict[type_key] = headings
            if "childTabs" in tab:
                scan(tab["childTabs"])

    scan(doc.get("tabs", []))
    return tabs_list, templates_dict


def process_file(file_meta, campaign_name, doc_id, gemini_client):
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

        tabs_list, templates_dict = inspect_doc(doc_id)
        prompt = get_latest_prompt(tabs_list, templates_dict)

        print(f"[{campaign_name}] Gemini processing audio...")
        response = gemini_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[audio_file, prompt],
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )
        extracted = json.loads(response.text)

        # Dynamic doc_updater execution with hot-reload
        global doc_updater
        if doc_updater:
            doc_updater = importlib.reload(doc_updater)
            doc_updater.apply_updates(docs_service, doc_id, extracted)
        else:
            import doc_updater as fresh_doc_updater

            fresh_doc_updater.apply_updates(docs_service, doc_id, extracted)

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

    if not settings["gemini_api_key"]:
        print("GEMINI_API_KEY missing. Please provide it in the Unraid container settings.")
        return

    if not settings["campaign_folders"]:
        print("CAMPAIGN_FOLDERS empty. Please provide Google Drive folder ID(s) in the Unraid container settings.")
        return

    gemini_client = genai.Client(api_key=settings["gemini_api_key"])

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

            if not doc_id:
                print(f"[{campaign_name}] Skipped: No Google Doc named '{campaign_name}' found.")
                continue

            if not recordings_folder_id:
                print(f"[{campaign_name}] Skipped: No 'Recordings' subfolder found.")
                continue

            q_audio = f"'{recordings_folder_id}' in parents and trashed = false and not name contains '[PROCESSED]'"
            audio_files = (
                drive_service.files().list(q=q_audio, fields="files(id, name, mimeType)").execute().get("files", [])
            )

            for audio_file in audio_files:
                name = audio_file["name"].lower()
                if name.endswith((".m4a", ".mp3", ".wav", ".aac", ".ogg")):
                    print(f"[{campaign_name}] Detected new recording: {audio_file['name']}")
                    process_file(audio_file, campaign_name, doc_id, gemini_client)

        except Exception as e:
            print(f"Error scanning folder {campaign_folder_id}: {e}")


if __name__ == "__main__":
    print("D&D Session Engine started. Watching folders using Unraid environment variables...")
    while True:
        try:
            discover_and_process()
        except Exception as e:
            print(f"Watcher loop error: {e}")

        current_settings = load_settings()
        time.sleep(current_settings["check_interval_seconds"])
