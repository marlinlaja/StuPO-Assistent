import os
import sys



# --- Konstanten ---

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    sys.exit("DATABASE_URL fehlt (in .env setzen)")

# Wer das Modell wechselt, muss alle Chunks neu einbetten (embedding und embedding_modell auf NULL)
# und ggf. vector(768) in database/schema.sql anpassen.
EMBEDDING_BASE_URL = os.environ.get("EMBEDDING_BASE_URL", "").rstrip("/")
EMBEDDING_API_KEY = os.environ.get("EMBEDDING_API_KEY")
EMBEDDING_URL = f"{EMBEDDING_BASE_URL}/v1/embedding"
EMBEDDING_MODEL = "jinaai/jina-embeddings-v5-text-nano"
EMBEDDING_DIMENSIONS = 768
PROCESSING_INTERVAL_SECONDS = 60 * 60 # einmal pro Stunde das Processing starten

LOG_FORMAT = "%(asctime)s %(levelname)-7s %(message)s"
LOG_LEVEL = "INFO"
