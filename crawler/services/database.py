import psycopg
from psycopg.rows import dict_row

from config import DATABASE_URL



# --- Verbindung ---

def connect() -> psycopg.Connection:
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)



# --- Dokumente ---

# sprache setzt erst das Parsen anhand des Textes
def insert_document(conn: psycopg.Connection, document: dict) -> int:
    row = conn.execute(
        """
        INSERT INTO dokument (typ, titel, sprache, semester, erschienen_am, dateiname, sha256, pdf)
        VALUES (%(typ)s, %(titel)s, 'deutsch', %(semester)s, %(erschienen_am)s, %(dateiname)s, %(sha256)s, %(pdf)s)
        RETURNING id
        """,
        document,
    ).fetchone()
    return row["id"]



def find_document_id_by_title(conn: psycopg.Connection, title: str) -> int | None:
    row = conn.execute("SELECT id FROM dokument WHERE titel = %s ORDER BY id DESC LIMIT 1", (title,)).fetchone()
    if row is None:
        return None
    return row["id"]



def find_document_id_by_hash(conn: psycopg.Connection, sha256: str) -> int | None:
    row = conn.execute("SELECT id FROM dokument WHERE sha256 = %s", (sha256,)).fetchone()
    if row is None:
        return None
    return row["id"]



def link_document(conn: psycopg.Connection, regulation_id: int, document_id: int) -> None:
    conn.execute(
        "INSERT INTO zugehoerig (pruefungsordnung_id, dokument_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        (regulation_id, document_id),
    )



def load_examination_regulations(conn: psycopg.Connection) -> list[dict]:
    return conn.execute(
        """
        SELECT po.id, po.jahr, po.filter_upo, po.filter_po, po.filter_modulhandbuch,
               studiengang.name, studiengang.abschluss
        FROM pruefungsordnung po
        JOIN studiengang ON studiengang.id = po.studiengang_id
        ORDER BY po.id
        """
    ).fetchall()
