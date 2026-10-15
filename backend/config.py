import os
import sys



# --- Konstanten ---

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    sys.exit("DATABASE_URL fehlt (in .env setzen)")
# Nur-Lese-Nutzer fuer die SQL-Queries des LLM (database/leserolle.sh)
READ_ONLY_DATABASE_URL = os.environ.get("LESE_DATABASE_URL")

# Wer das Modell wechselt, muss alle Chunks neu einbetten (embedding und embedding_modell auf NULL)
# und ggf. vector(768) in database/schema.sql anpassen.
EMBEDDING_BASE_URL = os.environ.get("EMBEDDING_BASE_URL", "").rstrip("/")
if not EMBEDDING_BASE_URL:
    sys.exit("EMBEDDING_BASE_URL fehlt (in .env setzen)")
EMBEDDING_API_KEY = os.environ.get("EMBEDDING_API_KEY")
EMBEDDING_URL = f"{EMBEDDING_BASE_URL}/v1/embedding"
EMBEDDING_MODEL = "jinaai/jina-embeddings-v5-text-nano"
EMBEDDING_DIMENSIONS = 768

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL")
LLM_MODEL = os.environ.get("LLM_MODELL") or "deepseek-flash"
LLM_TIMEOUT_SECONDS = 120
# So viele der letzten Nachrichten eines Chats gehen als Verlauf an das LLM (6 = drei Fragen mit Antwort)
HISTORY_MESSAGES = 6
# Thinking-Stufe fuer Recherche und Antwort, wenn im Frontend keine gewaehlt ist (main.py)
DEFAULT_THINKING = "low"
