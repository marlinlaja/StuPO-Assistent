import psycopg

from services.access import restrict_to_document
from services.database import connect
from services.embedding import embed_texts



# --- Konstanten ---

RESULT_COUNT = 5
CANDIDATE_COUNT = RESULT_COUNT * 4
RRF_K = 60



# --- Tool ---

def get_definition() -> dict:
    return {"type": "function", "function": {
        "name": "search",
        "description": (
            f"Sucht die {RESULT_COUNT} passendsten Textstellen (Chunks), nach Stichworten und nach Bedeutung. "
            "Formuliere die Anfrage mit den Fachbegriffen der Dokumente. Ohne document_id wird in allen Dokumenten "
            "gesucht."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "z. B. 'Wiederholung Modulprüfung Anzahl Versuche'"},
                "document_id": {"type": "integer"},
            },
            "required": ["query"],
        },
    }}



def run(document_ids: list[int], query: str, document_id: int | None = None) -> list[dict]:
    document_ids = restrict_to_document(document_ids, document_id)
    vector = embed_query(query)

    with connect() as conn:
        semantic_ids = search_semantic(conn, vector, document_ids)
        keyword_ids = search_keywords(conn, query, document_ids)
        best_ids = fuse_rankings([semantic_ids, keyword_ids])
        return load_chunks(conn, best_ids)



# --- Suche ---

def embed_query(query: str) -> str:
    vector = embed_texts([query], "query")[0]
    return str(vector)



def search_semantic(conn: psycopg.Connection, vector: str, document_ids: list[int]) -> list[int]:
    # sonst filtert der HNSW-Index erst nach der Suche und es bleiben zu wenige Treffer
    conn.execute("SET LOCAL hnsw.iterative_scan = strict_order")
    rows = conn.execute(
        "SELECT id FROM chunk WHERE dokument_id = ANY(%s) ORDER BY embedding <=> %s::vector LIMIT %s",
        (document_ids, vector, CANDIDATE_COUNT),
    ).fetchall()
    return [row["id"] for row in rows]



# Woerter mit ODER statt UND verknuepft, sonst trifft eine ganze Anfrage fast nie
def search_keywords(conn: psycopg.Connection, query: str, document_ids: list[int]) -> list[int]:
    rows = conn.execute(
        """
        SELECT id FROM chunk, (SELECT replace(plainto_tsquery('german', %s)::text, '&', '|')::tsquery AS suche) AS q
        WHERE dokument_id = ANY(%s) AND suchvektor @@ suche
        ORDER BY ts_rank(suchvektor, suche) DESC LIMIT %s
        """,
        (query, document_ids, CANDIDATE_COUNT),
    ).fetchall()
    return [row["id"] for row in rows]



# Reciprocal Rank Fusion: zaehlt nur den Platz in jeder Liste
def fuse_rankings(rankings: list[list[int]]) -> list[int]:
    scores = {}
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0) + 1 / (RRF_K + rank)

    return sorted(scores, key=scores.get, reverse=True)[:RESULT_COUNT]



def load_chunks(conn: psycopg.Connection, chunk_ids: list[int]) -> list[dict]:
    return conn.execute(
        """
        SELECT 'c' || id AS id, dokument_id, 'm' || modul_id AS modul_id, abschnitt, start_seite AS seite, text
        FROM chunk WHERE id = ANY(%s) ORDER BY array_position(%s, id)
        """,
        (chunk_ids, chunk_ids),
    ).fetchall()
