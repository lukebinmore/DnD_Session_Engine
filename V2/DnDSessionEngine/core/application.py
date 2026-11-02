from DnDSessionEngine.core.startup import startup
from DnDSessionEngine.core.ingest_pipeline import run_ingest_pipeline
from DnDSessionEngine.core.assistant_pipeline import run_assistant_pipeline
from DnDSessionEngine.core.helpers import build_table
from DnDSessionEngine.core.theme import con
from rich.table import Table
import logging

logger = logging.getLogger(__name__)


def run():
    con.rule("Starting Application...", style="rule.header")
    try:
        con.rule("Initial Setup", style="rule.header")
        data = startup()

        options = [
            ("Ingest new session recording", run_ingest_pipeline),
            ("Launch AI Campaign Assistant", run_assistant_pipeline),
        ]

        while True:
            con.rule("Main Menu", style="rule.header")
            build_table(options, ["Key", "Option"], numbered=True)
            try:
                response = input("Please select an option: (Blank for 0) ")
                if not response:
                    response = 0
                else:
                    response = int(response)
                if response >= len(options) or response < 0:
                    raise Exception()
            except Exception:
                con.print("Invalid selection, please try again", style="danger")
                input("Press enter to continue")
                continue

            chosen_func = options[response][1]
            chosen_func(data)

    except Exception as e:
        print()
        logger.critical(f"Program execution cancelled. Critical Error: {e}")
        input("Press any key to continue")
