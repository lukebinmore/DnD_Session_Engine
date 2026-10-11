import logging
import traceback

logger = logging.getLogger("Pipeline")


def run(
    drive_service,
    docs_service,
    gemini_client,
    campaign_name,
    doc_id,
    audio_file_id,
    audio_file_name,
    model_name,
):
    """Core Pipeline Switchboard.

    Executes modular steps sequentially for a detected audio file.
    """
    logger.info("------------------------------------------------------------")
    logger.info(f"[{campaign_name}] Pipeline started for: '{audio_file_name}'")
    logger.info("------------------------------------------------------------")

    doc_meta = None
    narrative_log = None

    try:
        # =====================================================================
        # STAGE 1: Document Inspector
        # =====================================================================
        logger.info(f"[{campaign_name}] [STAGE 1/6] Inspecting document structure &" " templates...")
        import inspector

        doc_meta = inspector.run(docs_service, doc_id)
        logger.info(f"[{campaign_name}] [STAGE 1/6] Success: Parsed document metadata &" " tabs.")

        # =====================================================================
        # STAGE 2: Truth Log (Audio -> Narrative)
        # =====================================================================
        # logger.info(f"[{campaign_name}] [STAGE 2/6] Generating chronological truth log via Gemini...")
        # import truth_log
        # known_tabs = list(doc_meta["tabs_info"].keys()) if doc_meta else []
        # narrative_log = truth_log.run(
        #     drive_service=drive_service,
        #     gemini_client=gemini_client,
        #     audio_file_id=audio_file_id,
        #     audio_file_name=audio_file_name,
        #     known_tabs=known_tabs,
        #     model_name=model_name
        # )
        # logger.info(f"[{campaign_name}] [STAGE 2/6] Success: Truth log generated in memory.")

        # =====================================================================
        # STAGE 3: Session Builder
        # =====================================================================
        # logger.info(f"[{campaign_name}] [STAGE 3/6] Updating session tab & prepping next session...")
        # import session_builder
        # session_builder.run(
        #     docs_service=docs_service,
        #     gemini_client=gemini_client,
        #     doc_id=doc_id,
        #     narrative_log=narrative_log,
        #     doc_meta=doc_meta,
        #     model_name=model_name
        # )
        # logger.info(f"[{campaign_name}] [STAGE 3/6] Success: Session tabs updated.")

        # =====================================================================
        # STAGE 4: Entity Creator
        # =====================================================================
        # logger.info(f"[{campaign_name}] [STAGE 4/6] Detecting & generating new entity tabs...")
        # import entity_creator
        # entity_creator.run(
        #     docs_service=docs_service,
        #     gemini_client=gemini_client,
        #     doc_id=doc_id,
        #     narrative_log=narrative_log,
        #     doc_meta=doc_meta,
        #     model_name=model_name
        # )
        # logger.info(f"[{campaign_name}] [STAGE 4/6] Success: New entity tabs created.")

        # =====================================================================
        # STAGE 5: Entity Updater
        # =====================================================================
        # logger.info(f"[{campaign_name}] [STAGE 5/6] Appending delta updates to existing entities...")
        # import entity_updater
        # entity_updater.run(
        #     docs_service=docs_service,
        #     gemini_client=gemini_client,
        #     doc_id=doc_id,
        #     narrative_log=narrative_log,
        #     doc_meta=doc_meta,
        #     model_name=model_name
        # )
        # logger.info(f"[{campaign_name}] [STAGE 5/6] Success: Existing entities updated.")

        # =====================================================================
        # STAGE 6: Tab Linker
        # =====================================================================
        # logger.info(f"[{campaign_name}] [STAGE 6/6] Scanning document to link tab references...")
        # import tab_linker
        # tab_linker.run(docs_service, doc_id)
        # logger.info(f"[{campaign_name}] [STAGE 6/6] Success: Internal tab links inserted.")

        # =====================================================================
        # FINALIZATION: Mark Audio as Processed
        # =====================================================================
        processed_name = f"[PROCESSED] {audio_file_name}"
        logger.info(f"[{campaign_name}] All active stages finished. Renaming audio file to:" f" '{processed_name}'")
        drive_service.files().update(fileId=audio_file_id, body={"name": processed_name}).execute()
        logger.info(f"[{campaign_name}] File successfully marked as processed.")
        return True

    except Exception as e:
        logger.error(f"[{campaign_name}] Pipeline aborted due to error: {e}")
        logger.error(traceback.format_exc())

        # Tag the file with [FAILED] to prevent infinite retry loops
        try:
            failed_name = f"[FAILED] {audio_file_name}"
            logger.warning(f"[{campaign_name}] Renaming audio file to: '{failed_name}'")
            drive_service.files().update(fileId=audio_file_id, body={"name": failed_name}).execute()
        except Exception as rename_err:
            logger.error(f"[{campaign_name}] Failed to mark file as failed: {rename_err}")

        return False
