from DnDSessionEngine.core.theme import con
from pathlib import Path
from tkinter import filedialog
from rich.table import Table
import tkinter as tk
import json
import logging

logger = logging.getLogger(__name__)


def build_table(values, headers=[], title=None, numbered=False):
    if title:
        table = Table(
            title=title,
            title_style="table.title",
            border_style="table.border",
            show_header=True,
            header_style="table.header",
            show_lines=True,
        )
    else:
        table = Table(
            border_style="table.border",
            show_header=True,
            header_style="table.header",
            show_lines=True,
        )

    table.add_column(headers[0], style="table.column1", no_wrap=True)
    table.add_column(headers[1], style="table.column2", overflow="fold")

    if numbered:
        for idx, value in enumerate(values):
            table.add_row(str(idx), value[0])
    else:
        for key, value in values.items():
            table.add_row(key, str(value) if str(value).strip() else "[empty]<EMPTY>[/]")

    con.print(table)


def dump_to_file(data, path, title=None):
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=4)
    if title:
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
