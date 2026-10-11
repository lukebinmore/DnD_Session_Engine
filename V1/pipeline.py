import os
import json
import logging
import importlib
import inspector
import truth_log

# Force reload modules if running in a persistent daemon/watcher container
importlib.reload(inspector)
importlib.reload(truth_log)

logger = logging.getLogger("Pipeline")


def mark_file_failed(drive_service, audio_file_id, audio_file_name, campaign_name):
    """Renames the audio file on Google Drive to prepend [FAILED]."""
    try:
        new_name = f"[FAILED] {audio_file_name}"
        logger.warning(f"[{campaign_name}] Renaming audio file to: '{new_name}'")
        drive_service.files().update(fileId=audio_file_id, body={"name": new_name}).execute()
    except Exception as e:
        logger.error(f"[{campaign_name}] Could not rename failed file in Drive: {e}")


def mark_file_processed(drive_service, audio_file_id, audio_file_name, campaign_name):
    """Renames the audio file on Google Drive to prepend [PROCESSED]."""
    try:
        new_name = f"[PROCESSED] {audio_file_name}"
        logger.info(f"[{campaign_name}] Renaming audio file to: '{new_name}'")
        drive_service.files().update(fileId=audio_file_id, body={"name": new_name}).execute()
    except Exception as e:
        logger.error(f"[{campaign_name}] Could not rename processed file in Drive: {e}")


def run(
    campaign_name,
    drive_service,
    docs_service,
    gemini_client,
    doc_id,
    audio_file_id,
    audio_file_name,
    model_name=None,
):
    """Orchestrates the 6-stage D&D campaign documentation pipeline."""
    logger.info("------------------------------------------------------------")
    logger.info(f"[{campaign_name}] Pipeline started for: '{audio_file_name}'")
    logger.info("------------------------------------------------------------")

    try:
        # =====================================================================
        # STAGE 1: Inspection & Schema Parsing
        # =====================================================================
        logger.info(f"[{campaign_name}] [STAGE 1/6] Inspecting document structure & templates...")
        doc_meta = inspector.run(docs_service=docs_service, doc_id=doc_id)
        known_tabs = doc_meta.get("all_tab_titles", [])
        logger.info(f"[{campaign_name}] [STAGE 1/6] Success: Parsed document metadata & tabs.")

        # =====================================================================
        # STAGE 2: Truth Log (Audio -> Objective Event Ledger)
        # =====================================================================
        logger.info(f"[{campaign_name}] [STAGE 2/6] Generating chronological truth log via Gemini...")
        narrative_log = truth_log.run(
            drive_service=drive_service,
            gemini_client=gemini_client,
            audio_file_id=audio_file_id,
            audio_file_name=audio_file_name,
            known_tabs=known_tabs,
            model_name=model_name,
            cache_dir="/app/truth_logs",
        )
        logger.info(
            f"[{campaign_name}] [STAGE 2/6] Success: Truth log generated ({len(narrative_log.splitlines())} events)."
        )

        # =====================================================================
        # STAGE 3: Session Tab Creation & Ingestion
        # =====================================================================
        # logger.info(f"[{campaign_name}] [STAGE 3/6] Pending: Session Tab creation & ingestion...")

        # =====================================================================
        # STAGE 4: Entity Reconciliation & Ledger (Delta Extraction)
        # =====================================================================
        # logger.info(f"[{campaign_name}] [STAGE 4/6] Pending: Entity reconciliation...")

        # =====================================================================
        # STAGE 5: Document Mutation & Tab Updates
        # =====================================================================
        # logger.info(f"[{campaign_name}] [STAGE 5/6] Pending: Applying batch updates to Google Doc...")

        # =====================================================================
        # STAGE 6: Hyperlinking & Formatting Cleanup
        # =====================================================================
        # logger.info(f"[{campaign_name}] [STAGE 6/6] Pending: Internal hyperlinking...")

        mark_file_processed(drive_service, audio_file_id, audio_file_name, campaign_name)

        logger.info("------------------------------------------------------------")
        logger.info(f"[{campaign_name}] Pipeline completed successfully for '{audio_file_name}'.")
        logger.info("------------------------------------------------------------")
        return True

    except Exception as e:
        logger.error(f"[{campaign_name}] Pipeline aborted due to error: {e}", exc_info=True)
        mark_file_failed(drive_service, audio_file_id, audio_file_name, campaign_name)
        return False
