from DnDSessionEngine.core.config import LOGS_DIR
from datetime import datetime
from rich.console import Console
from rich.logging import RichHandler
import logging
import sys

logger = logging.getLogger(__name__)
console = Console()


def initialise_logging():
    console_handler = RichHandler(
        console=console,
        show_time=False,
        show_path=False,
        rich_tracebacks=True,
        tracebacks_show_locals=False,
        markup=True,
    )
    console_handler.setLevel(logging.INFO)

    log_file = LOGS_DIR / f"{datetime.now():%Y-%m-%d_%H-%M-%S}.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(getattr(logging, "INFO"))
    file_formatter = logging.Formatter(fmt="[%(asctime)s] - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    file_handler.setFormatter(file_formatter)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(getattr(logging, "INFO"))
    stream_format = logging.Formatter(fmt="%(message)s")
    stream_handler.setFormatter(stream_format)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    root_logger.handlers.clear()
    # root_logger.addHandler(stream_handler)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    logs = sorted(LOGS_DIR.glob("*.log"), key=lambda path: path.stat().st_mtime)
    if len(logs) > 10:
        for log in logs[:-10]:
            log.unlink()
