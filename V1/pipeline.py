import logging
import importlib
import file_helper
import inspector
import truth_log
import session_creator
import entity_updater

# Force reload modules if running in a persistent daemon/watcher container
importlib.reload(file_helper)
importlib.reload(inspector)
importlib.reload(truth_log)
importlib.reload(session_creator)
importlib.reload(entity_updater)

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
    stages = 6
    current_stage = 1

    logger.info("------------------------------------------------------------")
    logger.info(f"[{campaign_name}] Pipeline started for: '{audio_file_name}'")
    logger.info("------------------------------------------------------------\n")

    try:
        # =====================================================================
        # Inspection & Schema Parsing
        # =====================================================================
        logger.info(f"[{campaign_name}] [STAGE {current_stage}/{stages}] Inspecting document structure & templates...")
        doc_meta = inspector.run(docs_service=docs_service, doc_id=doc_id, audio_file_name=audio_file_name)
        known_tabs = doc_meta.get("entities_list", [])
        logger.info(f"[{campaign_name}] [STAGE {current_stage}/{stages}] Success: Parsed document metadata & tabs.\n")
        current_stage += 1

        # =====================================================================
        # Inspection & Schema Parsing
        # =====================================================================
        logger.info(f"[{campaign_name}] [Stage {current_stage}/{stages}] Storing session number in file name...")
        session_num = doc_meta.get("session_meta", {}).get("latest_session_num", 1)
        audio_file_name = file_helper.mark_file_session(drive_service, audio_file_id, audio_file_name, session_num)
        logger.info(f"[{campaign_name}] [Stage {current_stage}/{stages}] Success: Updated file name on Drive\n")
        current_stage += 1

        # =====================================================================
        # Truth Log (Audio -> Objective Event Ledger)
        # =====================================================================
        logger.info(
            f"[{campaign_name}] [STAGE {current_stage}/{stages}] Generating chronological truth log via Gemini..."
        )
        truth_log_text = truth_log.run(
            drive_service=drive_service,
            gemini_client=gemini_client,
            audio_file_id=audio_file_id,
            audio_file_name=audio_file_name,
            known_tabs=known_tabs,
            cache_dir="/app/truth_logs",
        )
        logger.info(
            f"[{campaign_name}] [STAGE {current_stage}/{stages}] Success: Truth log generated ({len(truth_log_text.splitlines())} events).\n"
        )
        current_stage += 1

        # =====================================================================
        # Session Tab Creation & Ingestion
        # =====================================================================
        logger.info(f"[{campaign_name}] [STAGE {current_stage}/{stages}] Starting Session Tab Creation & Ingestion...")
        session_result = session_creator.run(
            docs_service=docs_service,
            gemini_client=gemini_client,
            doc_id=doc_id,
            doc_meta=doc_meta,
            truth_log=truth_log_text,
        )
        logger.info(
            f"[{campaign_name}] [STAGE {current_stage}/{stages}] Success: Tab '{session_result['tab_title']}' created and populated.\n"
        )
        current_stage += 1

        # =====================================================================
        # Entity Reconciliation & Ledger (Delta Extraction)
        # =====================================================================
        """
        logger.info(f"[{campaign_name}] [STAGE {current_stage}/{stages}] Starting Entity Updates...")
        entity_results = entity_updater.run(
            gemini_client=gemini_client,
            truth_log=truth_log,
            doc_meta=doc_meta,
            docs_service=docs_service,
            doc_id=doc_id,
        )
        logger.info(f"[{campaign_name}] [STAGE {current_stage}/{stages}] Success: Entity updates are completed.\n")
        current_stage += 1
        """

        # =====================================================================
        # Document Mutation & Tab Updates
        # =====================================================================
        # logger.info(f"[{campaign_name}] [STAGE 5/6] Pending: Applying batch updates to Google Doc...")

        # =====================================================================
        # Hyperlinking & Formatting Cleanup
        # =====================================================================
        # logger.info(f"[{campaign_name}] [STAGE 6/6] Pending: Internal hyperlinking...")

        file_helper.mark_file_processed(drive_service, audio_file_id, audio_file_name, campaign_name)

        logger.info("------------------------------------------------------------")
        logger.info(f"[{campaign_name}] Pipeline completed successfully for '{audio_file_name}'.")
        logger.info("------------------------------------------------------------\n")
    except Exception as e:
        logger.error(f"[{campaign_name}] Pipeline aborted due to error: {e}\n", exc_info=True)
        file_helper.mark_file_failed(drive_service, audio_file_id, audio_file_name, campaign_name)
        return False
