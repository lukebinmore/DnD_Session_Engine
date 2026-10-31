from DnDSessionEngine.core.theme import con
from rich.table import Table
from prompt_toolkit import prompt
from pathlib import Path
import sys
import json
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
MODELS_DIR = APP_DATA / "models"

DIRECTORIES = [CONFIG_DIR, LOGS_DIR, MODELS_DIR]

CONFIG_PATH = CONFIG_DIR / "config.json"

GEMINI_RETRIES = 3
LLM_REPO_ID = "microsoft/Phi-4-mini-instruct-onnx"
LLM_REPO_FOLDER = "gpu"
LLM_REPO_NAME = LLM_REPO_ID.split("/")[-1]

DEFAULT_CONFIG = {
    "Gemini API Key": "",
    "Gemini Models": "gemini-3.8-flash, gemini-3.7-flash, gemini-3.6-flash, gemini-3.5-flash",
    "Kanka Campaign ID": "",
    "Kanka Token": "",
    "LLM Processor ID": "0",
}


def initialise_directories():
    for directory in DIRECTORIES:
        directory.mkdir(parents=True, exist_ok=True)


def build_config_table(config):
    table = Table(
        title="Current Configuration",
        title_style="table.title",
        border_style="table.border",
        show_header=True,
        header_style="table.header",
        show_lines=True,
    )
    table.add_column("Setting", style="table.column1", no_wrap=True)
    table.add_column("Value", style="table.column2", overflow="fold")

    for key, value in config.items():
        table.add_row(key, value if value.strip() else "[empty]<EMPTY>[/]")

    con.print(table)


def initialise_config():
    if not CONFIG_PATH.exists():
        with CONFIG_PATH.open("w", encoding="utf-8") as file:
            json.dump(DEFAULT_CONFIG, file, indent=4)

    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        curr_config = json.load(file)

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
        build_config_table(curr_config)
        if (
            any(v.strip() == "" for v in curr_config.values())
            or input("Would you like to edit the config?: (Blank for no) ").strip()
        ):
            con.rule("Editing Configuration", style="rule.sub")
            for key, value in curr_config.items():
                con.print(f" - [menu.key]{key}[/]:", end="")
                curr_config[key] = prompt(f" ", default=value)
                changed = True
            con.rule("Updated Values", style="rule.sub")
        else:
            con.print("Configuration accepted.", style="success")
            break

    if changed:
        with CONFIG_PATH.open("w", encoding="utf-8") as file:
            json.dump(curr_config, file, indent=4)
        logger.info("Configuration saved to disk.")


def load_config(key=None):
    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as file:
            config = json.load(file)
            if key:
                return config[key]
            return config
    except Exception:
        logger.error("Failed to load config!")
        raise
