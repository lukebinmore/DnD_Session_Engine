from DnDSessionEngine.core.startup import startup
from DnDSessionEngine.core.local_llm import shutdown_llm_server
from DnDSessionEngine.core.ingest_pipeline import run_ingest_pipeline
from DnDSessionEngine.core.assistant_pipeline import run_assistant_pipeline
from DnDSessionEngine.core.helpers import build_table
from DnDSessionEngine.core.theme import con
from rich.prompt import IntPrompt
import traceback
import logging

logger = logging.getLogger(__name__)


def run():
    con.rule("Starting Application...", style="rule.header")
    try:
        con.rule("Initial Setup", style="rule.header")
        startup()

        options = [
            ("Launch AI Campaign Assistant", run_assistant_pipeline),
            ("Ingest New Session Recording", run_ingest_pipeline),
        ]

        while True:
            con.rule("Main Menu", style="rule.header")
            build_table(options, ["Key", "Option"], numbered=True)
            choices = [str(i) for i in range(len(options))]
            response = IntPrompt.ask(
                "[menu.key]Please select an option[/]",
                console=con,
                show_choices=False,
                choices=choices,
                default=0,
            )

            try:
                chosen_func = options[response][1]
                chosen_func()
            except Exception as e:
                print()
                logger.error(f"Option failed to run!: {e}")
                print(traceback.format_exc())
                input("Press any key to continue")
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print()
        logger.critical(f"Program execution cancelled. Critical Error: {e}")
        print(traceback.format_exc())
        input("Press any key to continue")
    finally:
        print()
        logger.info("Program exited by user!")
        shutdown_llm_server()
