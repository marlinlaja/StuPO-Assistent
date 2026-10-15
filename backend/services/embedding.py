import requests

from config import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL, EMBEDDING_API_KEY, EMBEDDING_URL



# --- Konstanten ---

TIMEOUT_SECONDS = 30
INPUT_TYPES = {"query": "query", "document": "document"}



# --- Embedding API ---

# kind = "query" fuer Fragen und Aussagen, "document" fuer Textstellen; die Vektoren sind normiert.
def embed_texts(texts: list[str], kind: str) -> list[list[float]]:
    request = {
        "model": EMBEDDING_MODEL,
        "input": texts,
        "input_type": INPUT_TYPES[kind],
        "output_dimension": EMBEDDING_DIMENSIONS,
    }
    headers = {"Authorization": f"Bearer {EMBEDDING_API_KEY}"}
    response = requests.post(EMBEDDING_URL, json=request, headers=headers, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()

    results = sorted(response.json()["data"], key=result_index)
    return [result["embedding"] for result in results]



def result_index(result: dict) -> int:
    return result["index"]
