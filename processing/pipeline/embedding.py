import time

import requests

from config import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL, EMBEDDING_API_KEY, EMBEDDING_URL



# --- Konstanten ---

TIMEOUT_SECONDS = 120
# Kleine Batches, damit eine Frage vom Backend nie lange auf den Service wartet
BATCH_SIZE = 8



# --- Embedding API ---

# Textstellen als "document", Fragen bettet das Backend als "query" ein; die Vektoren sind normiert.
def embed_batch(texts: list[str]) -> list[list[float]]:
    request = {
        "model": EMBEDDING_MODEL,
        "input": texts,
        "input_type": "document",
        "output_dimension": EMBEDDING_DIMENSIONS,
    }
    started_at = time.perf_counter()
    headers = {"Authorization": f"Bearer {EMBEDDING_API_KEY}"}
    response = requests.post(EMBEDDING_URL, json=request, headers=headers, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()

    # Pause so lang wie die Rechenzeit, der Service ist durch Processing höchstens halb ausgelastet
    time.sleep(time.perf_counter() - started_at)

    results = sorted(response.json()["data"], key=result_index)
    return [result["embedding"] for result in results]



def result_index(result: dict) -> int:
    return result["index"]
