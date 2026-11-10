from pathlib import Path
import tkinter as tk
from tkinter import filedialog
import json
import logging

logger = logging.getLogger(__name__)


def dump_to_file(data, path, title):
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=4)
    logger.info(f"{title.title()} saved to disk! Path: {path}!")


def prompt_for_file():
    logger.info("Collecting session file...")
    root = tk.Tk()
    root.withdraw()
    root.wm_attributes("-topmost", True)
    default_types = [("Audio Files", "*.mp3 *.wav *.m4a *.flac *.ogg")]

    file_path = filedialog.askopenfilename(title="Select session recording", filetypes=default_types)
    root.destroy()
    if not file_path:
        raise Exception("No file selected!")

    file_path = Path(file_path)
    file_name = file_path.name
    file = {"path": file_path, "name": file_name}
    logger.info(f"Session file collected successfully: {file_name}")
    return file


def read_json_file(path, text=None):
    file_content = None
    try:
        with open(path, "r") as file:
            file_content = json.load(file)
            if text:
                logger.info(f"{text.title()} retrieved successfully!")
    except Exception:
        if text:
            logger.info(f"{text} not found!")
        else:
            logger.warning(f"File not found!")

    return file_content
