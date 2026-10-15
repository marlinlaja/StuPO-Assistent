from services.access import ensure_document_available
from services.database import connect



# --- Tool ---

def get_definition() -> dict:
    return {"type": "function", "function": {
        "name": "get_document_index",
        "description": (
            "Inhaltsverzeichnis eines Dokuments: je Abschnitt nr, ebene, titel, seiten und tokens. "
            "Mit der nr liest get_section den ganzen Abschnitt."
        ),
        "parameters": {
            "type": "object",
            "properties": {"document_id": {"type": "integer"}},
            "required": ["document_id"],
        },
    }}



def run(document_ids: list[int], document_id: int) -> list[dict]:
    ensure_document_available(document_id, document_ids)
    with connect() as conn:
        row = conn.execute("SELECT inhaltsverzeichnis FROM dokument WHERE id = %s", (document_id,)).fetchone()

    return [index_entry(number, entry) for number, entry in enumerate(row["inhaltsverzeichnis"], start=1)]



def index_entry(number: int, entry: dict) -> dict:
    return {
        "nr": number,
        "ebene": entry["ebene"],
        "titel": entry["titel"],
        "seiten": f"{entry['seite_von']}-{entry['seite_bis']}",
        "tokens": entry["tokens"],
    }
