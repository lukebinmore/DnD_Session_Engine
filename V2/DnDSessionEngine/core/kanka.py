from DnDSessionEngine.core.config import load_config
import requests
import logging

logger = logging.getLogger(__name__)

KANKA_URL = "https://api.kanka.io/1.0/"
KANKA_HEADERS = {"Accept": "application/json", "Authorization": "Bearer "}


def kanka_get(url=None, *args, **kwargs):
    headers = KANKA_HEADERS
    headers["Authorization"] += load_config("Kanka Token")

    response = requests.get(KANKA_URL + url if url else "", headers=headers, *args, **kwargs)

    if response.status_code != 200:
        response.raise_for_status()

    body = response.json()["data"]
    return body


def initialise_kanka():
    logger.info("Verifying Kanka API token...")

    try:
        response = kanka_get(url="profile", timeout=10.0)
        logger.info(f"Kanka API token verified successfully! User: {response['name']}")
    except Exception as e:
        logger.error("Failed to verify Kanka APi token!")
        raise e
