import os
import sys
import time
import logging
import importlib
from google.oauth2 import service_account
from googleapiclient.discovery import build
from google import genai

# Unbuffer stdout so log events hit the Unraid web terminal immediately
sys.stdout.reconfigure(line_buffering=True)

# Configure logging format with timestamps and severity levels
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S", stream=sys.stdout
)
logger = logging.getLogger("Watcher")

BASE_DIR = "/app" if os.path.exists("/app") else "."
SERVICE_ACCOUNT_PATH = os.path.join(BASE_DIR, "service_account.json")

# --- Environment Configuration ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3s.5-flash").strip()

try:
    CHECK_INTERVAL_SECONDS = int(os.environ.get("CHECK_INTERVAL_SECONDS", "60"))
except ValueError:
    CHECK_INTERVAL_SECONDS = 60

raw_folders = os.environ.get("CAMPAIGN_FOLDERS", "")
CAMPAIGN_FOLDERS = [f.strip() for f in raw_folders.split(",") if f.strip()]

AUDIO_EXTENSIONS = (".m4a", ".mp3", ".wav", ".aac", ".ogg", ".flac")

# Track pipeline submodules so hot edits reload automatically
PIPELINE_MODULES = [
    "inspector",
    "truth_log",
    "session_builder",
    "entity_creator",
    "entity_updater",
    "tab_linker",
]


def verify_environment():
    """Validates required files and configuration before launching."""
    logger.info("Verifying system configuration and runtime dependencies...")

    if not os.path.exists(SERVICE_ACCOUNT_PATH):
        logger.critical(f"Missing service account file: {SERVICE_ACCOUNT_PATH}")
        sys.exit(1)
    logger.info(f"Service account file confirmed at: {SERVICE_ACCOUNT_PATH}")

    if not GEMINI_API_KEY:
        logger.critical("GEMINI_API_KEY environment variable is missing.")
        sys.exit(1)
    logger.info(f"Gemini API key detected. Configured model: {GEMINI_MODEL}")

    if not CAMPAIGN_FOLDERS:
        logger.warning("CAMPAIGN_FOLDERS is empty. The watcher will idle until folders are specified.")
    else:
        logger.info(f"Loaded {len(CAMPAIGN_FOLDERS)} campaign folder(s) to monitor.")


def init_services():
    """Initializes Google Drive, Google Docs, and Gemini API clients."""
    logger.info("Initializing API connections (Google Drive, Google Docs, Gemini)...")
    try:
        scopes = ["https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/documents"]
        creds = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_PATH, scopes=scopes)
        drive_service = build("drive", "v3", credentials=creds)
        docs_service = build("docs", "v1", credentials=creds)
        gemini_client = genai.Client(api_key=GEMINI_API_KEY)
        logger.info("All API clients authenticated successfully.")
        return drive_service, docs_service, gemini_client
    except Exception as e:
        logger.critical(f"Failed to initialize API clients: {e}")
        sys.exit(1)


def scan_campaign_folder(drive_service, docs_service, gemini_client, folder_id):
    """Scans a single campaign folder for the campaign Doc and any pending audio."""
    try:
        folder_meta = drive_service.files().get(fileId=folder_id, fields="id, name, trashed").execute()
    except Exception as e:
        logger.error(f"Failed to access folder ID {folder_id}: {e}")
        return

    if folder_meta.get("trashed"):
        logger.warning(f"Folder '{folder_meta.get('name')}' ({folder_id}) is in the trash. Skipping.")
        return

    campaign_name = folder_meta.get("name")

    try:
        children = (
            drive_service.files()
            .list(q=f"'{folder_id}' in parents and trashed = false", fields="files(id, name, mimeType)")
            .execute()
            .get("files", [])
        )
    except Exception as e:
        logger.error(f"[{campaign_name}] Error listing children in folder: {e}")
        return

    doc_id = None
    recordings_folder_id = None

    for item in children:
        mime = item["mimeType"]
        name = item["name"]
        if mime == "application/vnd.google-apps.document" and name.strip().lower() == campaign_name.strip().lower():
            doc_id = item["id"]
        elif mime == "application/vnd.google-apps.folder" and name.strip().lower() == "recordings":
            recordings_folder_id = item["id"]

    if not doc_id:
        logger.warning(f"[{campaign_name}] No matching Google Doc named '{campaign_name}' found.")
        return
    if not recordings_folder_id:
        logger.warning(f"[{campaign_name}] No subfolder named 'Recordings' found.")
        return

    query = (
        f"'{recordings_folder_id}' in parents "
        f"and trashed = false "
        f"and not name contains '[PROCESSED]' "
        f"and not name contains '[FAILED]'"
    )
    try:
        audio_files = drive_service.files().list(q=query, fields="files(id, name, mimeType)").execute().get("files", [])
    except Exception as e:
        logger.error(f"[{campaign_name}] Error scanning 'Recordings' folder: {e}")
        return

    for audio_file in audio_files:
        name_lower = audio_file["name"].lower()
        if any(name_lower.endswith(ext) for ext in AUDIO_EXTENSIONS):
            file_id = audio_file["id"]
            file_name = audio_file["name"]

            logger.info("=" * 60)
            logger.info(f"[{campaign_name}] NEW AUDIO DETECTED: '{file_name}' (ID: {file_id})")
            logger.info(f"[{campaign_name}] Passing control to pipeline.py...")
            logger.info("=" * 60)

            # Reload all registered stage modules if already in memory
            for mod_name in PIPELINE_MODULES:
                if mod_name in sys.modules:
                    importlib.reload(sys.modules[mod_name])

            # Unconditionally import and reload pipeline orchestrator
            import pipeline

            importlib.reload(pipeline)

            pipeline.run(
                drive_service=drive_service,
                docs_service=docs_service,
                gemini_client=gemini_client,
                campaign_name=campaign_name,
                doc_id=doc_id,
                audio_file_id=file_id,
                audio_file_name=file_name,
                model_name=GEMINI_MODEL,
            )

            logger.info(f"Watcher active. Polling campaign folders every {CHECK_INTERVAL_SECONDS} second(s)...")


def main():
    logger.info("==================================================")
    logger.info(" D&D Session Engine: Continuous Watcher Started   ")
    logger.info("==================================================")

    verify_environment()
    drive_service, docs_service, gemini_client = init_services()
    logger.info(f"Watcher active. Polling campaign folders every {CHECK_INTERVAL_SECONDS} second(s)...")

    while True:
        for folder_id in CAMPAIGN_FOLDERS:
            scan_campaign_folder(
                drive_service=drive_service,
                docs_service=docs_service,
                gemini_client=gemini_client,
                folder_id=folder_id,
            )

        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
