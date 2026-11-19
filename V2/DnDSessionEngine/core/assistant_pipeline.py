from DnDSessionEngine.core.theme import con
from DnDSessionEngine.core.kanka import get_kanka_data
from DnDSessionEngine.core.local_llm import launch_llm_server, run_local_generation
import logging

logger = logging.getLogger(__name__)


def run_assistant_pipeline():
    con.rule("AI Campaign Assistant Setup", style="rule.header")
    con.rule("LLM Server Setup", style="rule.section")
    launch_llm_server()

    con.clear()
    con.rule("AI Campaign Assistant", style="rule.header")
    while True:
        con.rule("New Query", style="rule.section")
        con.print("What is your question?: (Blank to exit) ", end="", style="menu.key")
        user_query = input()
        if not user_query:
            break

        con.rule("AI Response", style="rule.dim")
        con.print(run_local_generation(user_query))
