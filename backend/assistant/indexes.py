# Die Inhaltsverzeichnisse der Prüfungsordnungen stehen schon im Prompt des Rechercheschritts. So ruft er get_section
# gleich mit der Abschnittsnummer auf, statt erst das Verzeichnis abzurufen, und der Anfang des Prompts bleibt für den
# Cache der API gleich.

from services.database import connect



# --- Konstanten ---

MODULE_HANDBOOK = "modulhandbuch"
NO_INDEX_TEXT = "(keine Verzeichnisse)"



# --- Inhaltsverzeichnisse ---

# Je Prüfungsordnung "nr. Titel (Seiten, Tokens)", eingerückt nach Ebene. Mit der nr liest get_section den Abschnitt.
# Modulhandbücher haben keins, ihre Module fragt man mit query_modules ab.
def describe_indexes(document_ids: list[int]) -> str:
    with connect() as conn:
        documents = conn.execute(
            "SELECT id, titel, inhaltsverzeichnis FROM dokument WHERE id = ANY(%s) AND typ <> %s ORDER BY id",
            (document_ids, MODULE_HANDBOOK),
        ).fetchall()

    blocks = [describe_index(document) for document in documents if document["inhaltsverzeichnis"]]
    return "\n\n".join(blocks) or NO_INDEX_TEXT



def describe_index(document: dict) -> str:
    lines = [f"Dokument {document['id']}: {document['titel']}"]
    for number, entry in enumerate(document["inhaltsverzeichnis"], start=1):
        indent = "  " * (entry["ebene"] - 1)
        lines.append(f"{indent}{number}. {entry['titel']} (S. {entry['seite_von']}-{entry['seite_bis']}, "
                     f"{entry['tokens']} Tokens)")
    return "\n".join(lines)
