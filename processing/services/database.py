import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from config import DATABASE_URL



# --- Konstanten ---

# Alles ausser pdf, das ist gross und wird nur bei Bedarf geladen
DOCUMENT_COLUMNS = ("id, typ, titel, sprache, semester, erschienen_am, inhaltsverzeichnis, importiert_am, dateiname, sha256, "
                    "status, fehler")
MODULE_COLUMNS = [
    "kennung", "version", "titel",
    "modulbereich", "modulbereich_pfad", "pflichtstatus", "niveau", "empf_fachsemester_wintersemester",
    "empf_fachsemester_sommersemester",
    "dauer_semester", "turnus", "sprache", "gueltig_von", "gueltig_bis",
    "ects", "sws", "stunden_gesamt", "stunden_praesenz", "stunden_selbststudium",
    "veranstaltungen",
    "modulverantwortung",
    "inhalt", "lernziele", "lehr_lernmethoden", "literatur",
    "teilnahmebedingungen", "empf_voraussetzungen",
    "pruefungsform", "pruefungsdauer_min", "pruefungsbedingungen", "zulassungsvoraussetzung",
    "sonstiges",
    "seite_von", "seite_bis",
]
MODULE_PLACEHOLDERS = ", ".join(f"%({column})s" for column in MODULE_COLUMNS)
# sprache ist ein Array des Enums, Python-Listen kommen aber als text[] an
INSERT_MODULE = f"""
    INSERT INTO modul (handbuch_id, {", ".join(MODULE_COLUMNS)})
    VALUES (%(handbuch_id)s, {MODULE_PLACEHOLDERS})
    RETURNING id
""".replace("%(sprache)s", "%(sprache)s::sprache[]")

INSERT_CHUNK = """
    INSERT INTO chunk (dokument_id, modul_id, position, abschnitt, start_seite, start_offset, ende_seite,
                       ende_offset, text, tokenanzahl, sprache)
    VALUES (%(dokument_id)s, %(modul_id)s, %(position)s, %(abschnitt)s, %(start_seite)s, %(start_offset)s,
            %(ende_seite)s, %(ende_offset)s, %(text)s, %(tokenanzahl)s, %(sprache)s)
"""



# --- Verbindung ---

def connect() -> psycopg.Connection:
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)



# --- Dokumente ---

# Dokumente mit Fehler bleiben liegen, bis jemand fehler auf NULL setzt.
def load_documents_with_status(conn: psycopg.Connection, status: str) -> list[dict]:
    return conn.execute(
        f"SELECT {DOCUMENT_COLUMNS} FROM dokument WHERE status = %s AND fehler IS NULL ORDER BY id", (status,)
    ).fetchall()



def load_pdf(conn: psycopg.Connection, document_id: int) -> bytes:
    row = conn.execute("SELECT pdf FROM dokument WHERE id = %s", (document_id,)).fetchone()
    return bytes(row["pdf"])



def set_status(conn: psycopg.Connection, document_id: int, status: str) -> None:
    conn.execute("UPDATE dokument SET status = %s WHERE id = %s", (status, document_id))



def set_error(conn: psycopg.Connection, document_id: int, error: str) -> None:
    conn.execute("UPDATE dokument SET fehler = %s WHERE id = %s", (error, document_id))



# --- Seiten ---

def save_pages(conn: psycopg.Connection, document_id: int, pages: list[dict], language: str | None) -> None:
    delete_content(conn, document_id)
    conn.execute("DELETE FROM seite WHERE dokument_id = %s", (document_id,))

    for page in pages:
        conn.execute(
            "INSERT INTO seite (dokument_id, seitenzahl, rohtext, layout, tabellen) VALUES (%s, %s, %s, %s, %s)",
            (document_id, page["seitenzahl"], page["rohtext"], Jsonb(page["layout"]), Jsonb(page["tabellen"])),
        )

    if language:
        conn.execute("UPDATE dokument SET sprache = %s WHERE id = %s", (language, document_id))



def load_pages(conn: psycopg.Connection, document_id: int) -> list[dict]:
    return conn.execute(
        "SELECT * FROM seite WHERE dokument_id = %s ORDER BY seitenzahl", (document_id,)
    ).fetchall()



# --- Module und Chunks ---

def save_structure(conn: psycopg.Connection, document: dict, modules: list[dict], chunks: list[dict],
                   table_of_contents: list[dict]) -> None:
    delete_content(conn, document["id"])
    conn.execute(
        "UPDATE dokument SET inhaltsverzeichnis = %s WHERE id = %s",
        (Jsonb(table_of_contents), document["id"]),
    )

    module_ids = []
    for module in modules:
        row = conn.execute(INSERT_MODULE, {**module, "handbuch_id": document["id"]}).fetchone()
        module_ids.append(row["id"])

    for chunk in chunks:
        conn.execute(INSERT_CHUNK, chunk_row(chunk, document, module_ids))



def chunk_row(chunk: dict, document: dict, module_ids: list[int]) -> dict:
    module_id = None
    if chunk["module_index"] is not None:
        module_id = module_ids[chunk["module_index"]]

    return {**chunk, "dokument_id": document["id"], "sprache": document["sprache"], "modul_id": module_id}



def delete_content(conn: psycopg.Connection, document_id: int) -> None:
    conn.execute("DELETE FROM chunk WHERE dokument_id = %s", (document_id,))
    conn.execute("DELETE FROM modul WHERE handbuch_id = %s", (document_id,))



def load_chunks_without_embedding(conn: psycopg.Connection, document_id: int) -> list[dict]:
    return conn.execute(
        "SELECT id, text FROM chunk WHERE dokument_id = %s AND embedding IS NULL ORDER BY position",
        (document_id,),
    ).fetchall()



def save_vectors(conn: psycopg.Connection, chunk_ids: list[int], vectors: list[list[float]], model: str) -> None:
    for chunk_id, vector in zip(chunk_ids, vectors):
        conn.execute(
            "UPDATE chunk SET embedding = %s::vector, embedding_modell = %s WHERE id = %s",
            (str(vector), model, chunk_id),
        )

