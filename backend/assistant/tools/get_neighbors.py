from services.database import connect



# --- Tool ---

def get_definition() -> dict:
    return {"type": "function", "function": {
        "name": "get_neighbors",
        "description": "Liest die Textstellen direkt vor und nach einem Chunk, wenn ein Treffer abgeschnitten ist.",
        "parameters": {
            "type": "object",
            "properties": {"chunk_id": {"type": "string", "description": "z. B. c1093"}},
            "required": ["chunk_id"],
        },
    }}



def run(document_ids: list[int], chunk_id: str) -> list[dict]:
    chunk_number = int(str(chunk_id).removeprefix("c"))
    with connect() as conn:
        chunk = conn.execute("SELECT dokument_id, position FROM chunk WHERE id = %s", (chunk_number,)).fetchone()
        if chunk is None or chunk["dokument_id"] not in document_ids:
            raise ValueError(f"Chunk {chunk_number} gibt es in den verfügbaren Dokumenten nicht")

        return conn.execute(
            """
            SELECT 'c' || id AS id, abschnitt, start_seite AS seite, text FROM chunk
            WHERE dokument_id = %s AND position IN (%s, %s) ORDER BY position
            """,
            (chunk["dokument_id"], chunk["position"] - 1, chunk["position"] + 1),
        ).fetchall()
