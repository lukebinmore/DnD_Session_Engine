import logging
import importlib
import file_helper
import inspector
import truth_log
import session_creator
import entity_processor

# Force reload modules if running in a persistent daemon/watcher container
importlib.reload(file_helper)
importlib.reload(inspector)
importlib.reload(truth_log)
importlib.reload(session_creator)
importlib.reload(entity_processor)

logger = logging.getLogger("Pipeline")


def run(
    campaign_name,
    drive_service,
    docs_service,
    gemini_client,
    doc_id,
    audio_file_id,
    audio_file_name,
    **kwargs,
):
    """Orchestrates the 6-stage D&D campaign documentation pipeline."""
    stages = 5
    current_stage = 1

    logger.info("------------------------------------------------------------")
    logger.info(f"[{campaign_name}] Pipeline started for: '{audio_file_name}'")
    logger.info("------------------------------------------------------------\n")

    try:
        # =====================================================================
        # Inspection & Schema Parsing
        # =====================================================================
        if True:
            logger.info(
                f"[{campaign_name}] [STAGE {current_stage}/{stages}] Inspecting document structure & templates..."
            )
            doc_meta = inspector.run(docs_service=docs_service, doc_id=doc_id, audio_file_name=audio_file_name)
            session_num = doc_meta.get("sessions_meta", {}).get("latest_session_num", 1)
            known_tabs = doc_meta.get("entities_list", [])
            previous_session_summary = session_creator.get_previous_session_summary(doc_meta, session_num)
            logger.info(
                f"Loaded {len(previous_session_summary)} characters of prior session notes for Session {session_num}."
            )
            logger.info(f"[{campaign_name}] [STAGE {current_stage}/{stages}] Success.\n")
            current_stage += 1

        # =====================================================================
        # File Session Naming
        # =====================================================================
        if True:
            logger.info(f"[{campaign_name}] [Stage {current_stage}/{stages}] Storing session number in file name...")
            audio_file_name = file_helper.mark_file_session(drive_service, audio_file_id, audio_file_name, session_num)
            logger.info(f"[{campaign_name}] [STAGE {current_stage}/{stages}] Success.\n")
            current_stage += 1

        # =====================================================================
        # Truth Log (Audio -> Objective Event Ledger)
        # =====================================================================
        if True:
            logger.info(
                f"[{campaign_name}] [STAGE {current_stage}/{stages}] Generating chronological truth log via Gemini..."
            )
            truth_log_text = truth_log.run(
                drive_service=drive_service,
                gemini_client=gemini_client,
                audio_file_id=audio_file_id,
                audio_file_name=audio_file_name,
                known_tabs=known_tabs,
                previous_summary=previous_session_summary,
                session_num=session_num,
                cache_dir="/app/truth_logs",
            )
            logger.info(f"[{campaign_name}] [STAGE {current_stage}/{stages}] Success.\n")
            current_stage += 1

        # =====================================================================
        # Session Tab Creation & Ingestion
        # =====================================================================
        if True:
            logger.info(
                f"[{campaign_name}] [STAGE {current_stage}/{stages}] Starting Session Tab Creation & Ingestion..."
            )
            session_result = session_creator.run(
                docs_service=docs_service,
                gemini_client=gemini_client,
                doc_id=doc_id,
                doc_meta=doc_meta,
                truth_log=truth_log_text,
                previous_summary=previous_session_summary,
            )
            logger.info(f"[{campaign_name}] [STAGE {current_stage}/{stages}] Success.\n")
            current_stage += 1

        # =====================================================================
        # Entity Updates and Creation
        # =====================================================================
        if True:
            logger.info(f"[{campaign_name}] [STAGE {current_stage}/{stages}] Starting Entity Processing...")
            entity_results = entity_processor.run(
                gemini_client=gemini_client,
                truth_log=truth_log_text,
                doc_meta=doc_meta,
                docs_service=docs_service,
                doc_id=doc_id,
                session_num=session_num,
                previous_summary=previous_session_summary,
            )
            logger.info(f"[{campaign_name}] [STAGE {current_stage}/{stages}] Success.\n")
            current_stage += 1

        # =====================================================================
        # File Cleanup
        # =====================================================================
        if True:
            logger.info(f"[{campaign_name}] [STAGE {current_stage}/{stages}] Marking file as processed...")
            file_helper.mark_file_processed(drive_service, audio_file_id, audio_file_name, campaign_name)
            logger.info(f"[{campaign_name}] [STAGE {current_stage}/{stages}] Success.\n")

        logger.info("------------------------------------------------------------")
        logger.info(f"[{campaign_name}] Pipeline completed successfully for '{audio_file_name}'.")
        logger.info("------------------------------------------------------------\n")
    except Exception as e:
        logger.error(f"[{campaign_name}] Pipeline aborted due to error: {e}\n", exc_info=True)
        file_helper.mark_file_failed(drive_service, audio_file_id, audio_file_name, campaign_name)
        return False
