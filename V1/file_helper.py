import logging
import os
import re

logger = logging.getLogger("FileHelper")


def mark_file_failed(drive_service, audio_file_id, audio_file_name, campaign_name):
    """Renames the audio file on Google Drive to prepend [FAILED]."""
    try:
        new_name = f"[FAILED] {audio_file_name}"
        logger.warning(f"[{campaign_name}] Renaming audio file to: '{new_name}'\n")
        drive_service.files().update(fileId=audio_file_id, body={"name": new_name}).execute()
    except Exception as e:
        logger.error(f"[{campaign_name}] Could not rename failed file in Drive: {e}\n")


def mark_file_processed(drive_service, audio_file_id, audio_file_name, campaign_name):
    """Renames the audio file on Google Drive to prepend [PROCESSED]."""
    try:
        new_name = f"[PROCESSED] {audio_file_name}"
        logger.info(f"[{campaign_name}] Renaming audio file to: '{new_name}'\n")
        drive_service.files().update(fileId=audio_file_id, body={"name": new_name}).execute()
    except Exception as e:
        logger.error(f"[{campaign_name}] Could not rename processed file in Drive: {e}\n")


def mark_file_session(drive_service, audio_file_id, audio_file_name, session_num):
    """Renames the aduio file on Google Drive to sufix [Session NUM]"""
    try:
        target_tag = f"[Session {session_num}]"
        if target_tag.lower() in audio_file_name.lower():
            logger.info(f"Audio file already contains {target_tag}, skipping.")
            return audio_file_name

        new_name = f"{audio_file_name} [Session {session_num}]"
        logger.info(f"Renaming audio file to: '{new_name}'")
        drive_service.files().update(field=audio_file_id, body={"name": new_name}).execute()
        return new_name
    except Exception as e:
        logger.error(f"Could not append session to file name in Drive: {e}\n")
        return audio_file_name
