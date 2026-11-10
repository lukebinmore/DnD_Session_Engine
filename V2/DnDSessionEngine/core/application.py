from DnDSessionEngine.core.startup import startup
from DnDSessionEngine.core.ingest_pipeline import run_ingest_pipeline
from DnDSessionEngine.core.assistant_pipeline import run_assistant_pipeline
from DnDSessionEngine.core.helpers import build_table
from DnDSessionEngine.core.theme import con
import traceback
import logging

logger = logging.getLogger(__name__)


def run():
    con.rule("Starting Application...", style="rule.header")
    try:
        con.rule("Initial Setup", style="rule.header")
        data = startup()

        options = [
            ("Launch AI Campaign Assistant", run_assistant_pipeline),
            ("Ingest New Session Recording", run_ingest_pipeline),
        ]

        while True:
            con.rule("Main Menu", style="rule.header")
            build_table(options, ["Key", "Option"], numbered=True)
            try:
                con.print("Please select an option: (Blank for 0) ", end="", style="menu.key")
                response = input()
                if not response:
                    response = 0
                else:
                    response = int(response)
                if response >= len(options) or response < 0:
                    raise Exception()
            except Exception:
                con.print("Invalid selection, please try again", style="danger")
                input("Press enter to continue ")
                continue

            chosen_func = options[response][1]
            chosen_func(data)

    except Exception as e:
        print()
        logger.critical(f"Program execution cancelled. Critical Error: {e}")
        print(traceback.format_exc())
        input("Press any key to continue")
