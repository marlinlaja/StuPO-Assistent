import os
import sys



# --- Konstanten ---

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    sys.exit("DATABASE_URL fehlt (in .env setzen)")



# --- Crawler ---

# True: nur deutsche Fassungen laden, False: auch englische (das Processing parst sie nur und stoppt dann)
ONLY_GERMAN = True

# filter_upo und filter_po sind der Suchtext fuer ARCHIVE_SEARCH_URL, filter_modulhandbuch haengt an HANDBOOK_URL
ARCHIVE_URL = "https://www.rwth-aachen.de/cms/root/wir/aktuell/~bpfv/archiv-amtliche-bekanntmachungen/"
ARCHIVE_SEARCH_URL = ARCHIVE_URL + "?search={query}#search-wrapper"
HANDBOOK_URL = ("https://online.rwth-aachen.de/RWTHonline/pl/ui/$ctx;design=pl;header=max;lang=de/"
                "wbModhbReport.downloadPublicMHBVersion?pOrgNr=14194&pStpStpNr=")

CRAWL_INTERVAL_SECONDS = 24 * 60 * 60 # einmal pro Tag die Dokumente crawlen
REQUEST_DELAY_SECONDS = 1
REQUEST_TIMEOUT_SECONDS = 120
USER_AGENT = "StuPO-Assistent-Crawler"

LOG_FORMAT = "%(asctime)s %(levelname)-7s %(message)s"
LOG_LEVEL = "INFO"
