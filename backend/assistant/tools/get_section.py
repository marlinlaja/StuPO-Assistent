import psycopg

from services.access import ensure_document_available
from services.database import connect



# --- Konstanten ---

MAX_TOKENS = 10000



# --- Tool ---

def get_definition() -> dict:
    return {"type": "function", "function": {
        "name": "get_section",
        "description": (
            "Liest einen ganzen Abschnitt aus dem Inhaltsverzeichnis (get_document_index), mit allen Unterabschnitten. "
            f"Abschnitte über {MAX_TOKENS} Tokens gehen nicht, dann einen Unterabschnitt wählen."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "document_id": {"type": "integer"},
                "section_number": {"type": "integer", "description": "nr des Abschnitts aus get_document_index"},
            },
            "required": ["document_id", "section_number"],
        },
    }}



def run(document_ids: list[int], document_id: int, section_number: int) -> dict:
    ensure_document_available(document_id, document_ids)
    with connect() as conn:
        section = load_section(conn, document_id, section_number)
        chunks = conn.execute(
            """
            SELECT 'c' || id AS id, start_seite AS seite, text FROM chunk
            WHERE dokument_id = %s AND position BETWEEN %s AND %s ORDER BY position
            """,
            (document_id, section["chunk_von"], section["chunk_bis"]),
        ).fetchall()

    return {"titel": section["titel"], "chunks": chunks}



def load_section(conn: psycopg.Connection, document_id: int, section_number: int) -> dict:
    row = conn.execute("SELECT inhaltsverzeichnis FROM dokument WHERE id = %s", (document_id,)).fetchone()
    table_of_contents = row["inhaltsverzeichnis"]
    if not 1 <= section_number <= len(table_of_contents):
        raise ValueError(f"Abschnitt {section_number} gibt es nicht")

    section = table_of_contents[section_number - 1]
    if section["tokens"] > MAX_TOKENS:
        raise ValueError(f"Abschnitt {section_number} hat {section['tokens']} Tokens, wähle einen Unterabschnitt")
    return section
