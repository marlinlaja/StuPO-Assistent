from services.database import connect



# --- Tool ---

def get_definition() -> dict:
    return {"type": "function", "function": {
        "name": "get_module",
        "description": (
            "Alle Angaben zu einem Modul (ECTS, Turnus, Inhalt, Lernziele, Prüfung, Voraussetzungen ...). "
            "Die module_id (z. B. m225) steht bei search unter modul_id, bei query_modules unter id."
        ),
        "parameters": {
            "type": "object",
            "properties": {"module_id": {"type": "string", "description": "z. B. m225"}},
            "required": ["module_id"],
        },
    }}



def run(document_ids: list[int], module_id: str) -> dict:
    module_number = int(str(module_id).removeprefix("m"))
    with connect() as conn:
        module = conn.execute("SELECT * FROM modul WHERE id = %s", (module_number,)).fetchone()

    if module is None or module["handbuch_id"] not in document_ids:
        raise ValueError(f"Modul m{module_number} gibt es in den verfügbaren Dokumenten nicht")
    return {**module, "id": f"m{module_number}"}
