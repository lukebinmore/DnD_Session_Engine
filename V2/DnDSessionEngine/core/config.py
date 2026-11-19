from DnDSessionEngine.core.theme import con
from DnDSessionEngine.core.helpers import build_table, read_json_file, dump_to_file
from prompt_toolkit import prompt
from prompt_toolkit.formatted_text import HTML
from pathlib import Path
from rich.prompt import Confirm
import sys
import logging

logger = logging.getLogger(__name__)


def get_app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def get_package_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[1]


APP_ROOT = get_app_root()
PACKAGE_ROOT = get_package_root()
APP_DATA = APP_ROOT / "AppData"

CONFIG_DIR = APP_DATA / "config"
LOGS_DIR = APP_DATA / "logs"
RUNTIME_DIR = APP_DATA / "runtime"
VULKAN_DIR = RUNTIME_DIR / "vulkan"
CPU_DIR = RUNTIME_DIR / "cpu"
MODEL_DIR = APP_DATA / "model"
CAMPAIGN_DIR = APP_DATA / "campaign"
TRUTH_LOG_DIR = CAMPAIGN_DIR / "truth_logs"
ENTITIES_DIR = CAMPAIGN_DIR / "entities"
MANIFEST_PATH = CAMPAIGN_DIR / "manifest.json"
DATABASE_PATH = CAMPAIGN_DIR / "campaign.db"
CONFIG_PATH = CONFIG_DIR / "config.json"

DIRECTORIES = [CONFIG_DIR, LOGS_DIR, VULKAN_DIR, CPU_DIR, MODEL_DIR, CAMPAIGN_DIR, TRUTH_LOG_DIR, ENTITIES_DIR]

GEMINI_RETRIES = 3
MODEL_OPTIONS = {
    "small": {"name": "Model A", "url": "", "filename": ""},
    "medium": {"name": "Model A", "url": "", "filename": ""},
    "large": {"name": "Model A", "url": "", "filename": ""},
}

DEFAULT_CONFIG = {
    "Gemini API Key": "",
    "Gemini Models": "gemini-3.8-flash, gemini-3.7-flash, gemini-3.6-flash, gemini-3.5-flash",
    "Kanka Campaign ID": "",
    "Kanka Token": "",
    "Model Size": "large",
}


def initialise_directories():
    logger.info("Initialising Directories...")
    for directory in DIRECTORIES:
        directory.mkdir(parents=True, exist_ok=True)
    logger.info("Initialising Directories, Done!")


def initialise_config():
    logger.info("Initialising Config...")
    dump_to_file(DEFAULT_CONFIG, CONFIG_PATH) if not CONFIG_PATH.exists() else None
    curr_config = read_json_file(CONFIG_PATH)
    changed = False

    for section, default in DEFAULT_CONFIG.items():
        if section not in curr_config:
            curr_config[section] = default
            changed = True

    for key, value in curr_config.items():
        if not value:
            curr_config[key] = DEFAULT_CONFIG[key]
            changed = True

    while True:
        build_table(curr_config, ["Setting", "Value"], "Current Configuration")
        missing = any(v.strip() == "" for v in curr_config.values())

        if not missing:
            if not Confirm.ask("[menu.key]Would you like to edit the config?[/]", console=con, default=False):
                con.print("Configuration accepted.", style="success")
                break

        con.rule("Editing Configuration", style="rule.sub")
        for key, value in curr_config.items():
            curr_config[key] = prompt(HTML(f"<style fg='ansiyellow'><b> - {key}: </b></style>"), default=value)
            changed = True
            if key == "Model Size":
                if curr_config[key] not in ["small", "medium", "large"]:
                    con.print(f"Invalid Choice: {curr_config[key]}! Must be small, medium or large!", style="danger")
                    curr_config[key] = ""
                    input("Press enter to continue")
        con.rule("Updated Values", style="rule.sub")

    if changed:
        dump_to_file(curr_config, CONFIG_PATH, "Configuration")
    logger.info("Initialising Config, Done!")


def load_config(key=None):
    try:
        config = read_json_file(CONFIG_PATH)
        if key:
            return config[key]
        return config
    except Exception:
        logger.error("Failed to load config!")
        raise
