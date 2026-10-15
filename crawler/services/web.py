import logging
import time

import requests

from config import REQUEST_DELAY_SECONDS, REQUEST_TIMEOUT_SECONDS, USER_AGENT



# --- Konstanten ---

LOGGER = logging.getLogger("crawler")
SESSION = requests.Session()
SESSION.headers["User-Agent"] = USER_AGENT



# --- Abrufen ---

# Zwischen zwei Abrufen eine kurze Pause, um die Server der RWTH nicht zu belasten.
def fetch(url: str) -> requests.Response:
    time.sleep(REQUEST_DELAY_SECONDS)
    started_at = time.perf_counter()
    response = SESSION.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()

    LOGGER.debug("GET %s -> %d, %d Bytes, %.1f s", url, response.status_code, len(response.content),
                 time.perf_counter() - started_at)
    return response
