import logging

logger = logging.getLogger("Backup")


def run(drive_service, doc_id, campaign_name=None):
    """
    Creates or overwrites a single snapshot copy of the target Google Doc
    named '{campaign_name} (BACKUP)' in the campaign folder.

    Args:
        drive_service: Authenticated Google Drive API resource.
        doc_id (str): The Google Drive file ID of the document to clone.
        campaign_name (str, optional): The name of the campaign.

    Returns:
        tuple: (backup_file_id, backup_file_name)
    """
    logger.info("Initializing document backup procedure...")

    # Fetch document name and parent folder if not provided
    doc_meta = drive_service.files().get(fileId=doc_id, fields="name, parents").execute()

    if not campaign_name:
        campaign_name = doc_meta.get("name", "Campaign_Document")

    parents = doc_meta.get("parents", [])
    backup_name = f"{campaign_name} (BACKUP)"

    # Look for an existing backup file to replace
    query = f"name = '{backup_name}' and trashed = false"
    if parents:
        query += f" and '{parents[0]}' in parents"

    existing_files = drive_service.files().list(q=query, fields="files(id, name)").execute().get("files", [])

    for old_backup in existing_files:
        old_id = old_backup["id"]
        logger.info(f"Removing previous backup file: '{backup_name}' (ID: {old_id})")
        drive_service.files().delete(fileId=old_id).execute()

    # Create the fresh backup copy
    logger.info(f"Cloning '{campaign_name}' as '{backup_name}'...")
    copy_body = {"name": backup_name}
    if parents:
        copy_body["parents"] = parents

    backup_file = drive_service.files().copy(fileId=doc_id, body=copy_body, fields="id, name").execute()

    backup_id = backup_file.get("id")
    logger.info(f"Backup created successfully: '{backup_name}' (ID: {backup_id})")

    return backup_id, backup_name
