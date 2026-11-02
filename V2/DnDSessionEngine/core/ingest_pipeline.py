from DnDSessionEngine.core.theme import con
from DnDSessionEngine.core.kanka import get_kanka_data
from DnDSessionEngine.core.file_manager import prompt_for_file, read_json_file
from DnDSessionEngine.core.config import TRUTH_LOG_DIR
from DnDSessionEngine.core.helpers import build_table
from DnDSessionEngine.core.gemini import generate_truth_log
from pathlib import Path
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


def get_truth_log(session_data, title, current=False):
    logger.info(f"Retrieving {title.lower()}...")
    session_num = session_data.get("Session Number")
    if not current:
        session_num += -1
    file_name = f"Session {session_num}.json"
    file_path = TRUTH_LOG_DIR / file_name
    prev_truth_log = read_json_file(file_path, title)
    return prev_truth_log


def get_session_data():
    logger.info("Collecting current session data...")
    session_data = {}
    while True:
        con.print("Please provide the following information for this session:")
        try:
            con.print(" - Session Number: ", end="", style="menu.key")
            session_num = int(input())
            if session_num < 0 or session_num > len(list(Path(TRUTH_LOG_DIR).glob("*"))) + 1:
                raise Exception()

            con.print(" - Session Date: (E.G 05/11/2026) ", end="", style="menu.key")
            session_date = datetime.strptime(input(), "%d/%m/%y").date()

            session_data = {"Session Number": session_num, "Session Date": session_date}

            build_table(session_data, ["Key", "Value"], "Current Session Settings")
            response = input("Is this information correct? (Blank for yes) ")
            if not response:
                break

        except Exception as e:
            print(e)
            con.print("Invalid data entered. Please try again", style="warning")
            input("Press enter to continue")

    logger.info("Current session data collected successfully!")
    return session_data


def run_ingest_pipeline(data):
    gemini_client = data.get("gemini_client")
    llm_model = data.get("llm_model")
    con.rule("Session Ingest", style="rule.header")

    try:
        con.rule("Kanka Data Retrieval", style="rule.section")
        manifest = get_kanka_data()

        con.rule("Session Data Retrieval", style="rule.section")
        session_data = get_session_data()

        con.rule("Previous Truth Log Retrieval", style="rule.section")
        prev_truth_log = get_truth_log(session_data, "Previous session truth log")

        con.rule("Existing Truth Log Check", style="rule.section")
        curr_truth_log = get_truth_log(session_data, "Existing session truth log", True)

        use_existing = False
        if curr_truth_log:
            con.rule("Use Existing Confirmation", style="rule.section")
            if not input("Would you like to use the existing truth log?: (Blank for yes) "):
                use_existing = True

        if not use_existing:
            con.rule("Session File Retrieval", style="rule.section")
            session_file = prompt_for_file()

            con.rule("Gemini", style="rule.section")
            curr_truth_log = generate_truth_log(gemini_client, session_file, session_data, manifest, prev_truth_log)
    except Exception as e:
        logger.error(f"Failed to complete ingest pipeline: {e}")
