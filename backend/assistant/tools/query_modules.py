import psycopg

from services.access import restrict_to_document
from services.database import connect, connect_read_only



# --- Konstanten ---

MAX_ROWS = 200
ALLOWED_SQL_STARTS = ("select", "with")
MISSING_ID_NOTE = ("Die Zeilen haben keine Spalte id, daher ist keines dieser Module als Quelle zitierbar. "
                   "Willst du Module nennen, frag id mit ab.")



# --- Tool ---

def get_definition() -> dict:
    return {"type": "function", "function": {
        "name": "query_modules",
        "description": (
            "Führt ein SELECT auf der View modul_leseansicht aus (die Module der Modulhandbücher), um Module "
            "aufzulisten, zu filtern oder zu vergleichen. Die Query läuft einzeln auf jedem Modulhandbuch, ohne "
            f"document_id auf allen. Höchstens {MAX_ROWS} Zeilen pro Handbuch. Frag id immer mit ab: Sie steht im "
            "Ergebnis als Quellen-ID wie m225, in SQL nur als Zahl (WHERE id = 225). Modulbereiche und pflichtstatus "
            "stehen unten; die Werte anderer Spalten fragst du bei Bedarf mit SELECT DISTINCT ab.\n\n"
            + describe_columns() + "\n\n" + describe_module_areas()
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "z. B. SELECT id, titel, ects FROM modul_leseansicht WHERE titel ILIKE '%Analysis%'",
                },
                "document_id": {"type": "integer"},
            },
            "required": ["sql"],
        },
    }}



def run(document_ids: list[int], sql: str, document_id: int | None = None) -> list[dict]:
    sql = validate_sql(sql)
    handbooks = load_handbooks(restrict_to_document(document_ids, document_id))
    if not handbooks:
        raise ValueError("Kein Modulhandbuch verfügbar")

    with connect_read_only() as conn:
        return [query_handbook(conn, handbook, sql) for handbook in handbooks]



# --- Query ---

def validate_sql(sql: str) -> str:
    sql = sql.strip().removesuffix(";")
    if ";" in sql or not sql.lower().startswith(ALLOWED_SQL_STARTS):
        raise ValueError("Nur ein einzelnes SELECT ist erlaubt")
    return sql



def load_handbooks(document_ids: list[int]) -> list[dict]:
    with connect() as conn:
        return conn.execute(
            "SELECT id, titel FROM dokument WHERE id = ANY(%s) AND typ = 'modulhandbuch' ORDER BY id", (document_ids,)
        ).fetchall()



# Die View zeigt nur die Module des Handbuchs in app.handbuch_id, ein Fehler geht als Ergebnis ans LLM.
def query_handbook(conn: psycopg.Connection, handbook: dict, sql: str) -> dict:
    result = {"dokument_id": handbook["id"], "titel": handbook["titel"]}
    try:
        conn.execute("SELECT set_config('app.handbuch_id', %s, true)", (str(handbook["id"]),))
        rows = conn.execute(sql).fetchmany(MAX_ROWS + 1)
        result["zeilen"] = [with_source_id(row) for row in rows[:MAX_ROWS]]
        result["abgeschnitten"] = len(rows) > MAX_ROWS
        if rows and "id" not in rows[0]:
            result["hinweis"] = MISSING_ID_NOTE
    except psycopg.Error as error:
        result["fehler"] = str(error).strip()
    finally:
        conn.rollback()
    return result



def with_source_id(row: dict) -> dict:
    if "id" not in row:
        return row

    return {**row, "id": f"m{row['id']}"}



# --- Beschreibung fuer das LLM ---

# Spalten mit Typ, Enum-Werten und Kommentar aus database/schema.sql
def describe_columns() -> str:
    with connect() as conn:
        view = conn.execute("SELECT obj_description('modul_leseansicht'::regclass) AS kommentar").fetchone()
        columns = conn.execute(
            """
            SELECT a.attname AS name, format_type(a.atttypid, a.atttypmod) AS typ,
                   col_description(a.attrelid, a.attnum) AS kommentar,
                   (SELECT string_agg(e.enumlabel, ', ' ORDER BY e.enumsortorder)
                    FROM pg_type t JOIN pg_enum e ON e.enumtypid = coalesce(nullif(t.typelem, 0), t.oid)
                    WHERE t.oid = a.atttypid) AS werte
            FROM pg_attribute a
            WHERE a.attrelid = 'modul_leseansicht'::regclass AND a.attnum > 0
            ORDER BY a.attnum
            """
        ).fetchall()

    lines = [view["kommentar"], "", "Spalten:"] + [describe_column(column) for column in columns]
    return "\n".join(lines)



def describe_column(column: dict) -> str:
    details = column["typ"]
    if column["werte"]:
        details += f"; Werte: {column['werte']}"

    line = f"- {column['name']} ({details})"
    if column["kommentar"]:
        line += f": {column['kommentar']}"
    return line



# Bereichsbaum und Werte von pflichtstatus je Modulhandbuch, damit das LLM sie nicht erst abfragen muss
def describe_module_areas() -> str:
    with connect() as conn:
        areas = conn.execute(
            """
            SELECT d.id, d.titel, m.modulbereich_pfad AS pfad, count(*) AS anzahl,
                   (SELECT string_agg(DISTINCT pflichtstatus, ', ') FROM modul WHERE handbuch_id = d.id) AS pflichtstatus
            FROM modul m JOIN dokument d ON d.id = m.handbuch_id
            WHERE d.status = 'final'
            GROUP BY d.id, d.titel, m.modulbereich_pfad
            ORDER BY d.id, pfad
            """
        ).fetchall()

    lines = ["Modulbereiche je Modulhandbuch (modulbereich_pfad, Anzahl Module):"]
    previous_document_id = None
    for area in areas:
        if area["id"] != previous_document_id:
            lines.append(f"\nDokument {area['id']} ({area['titel']}), pflichtstatus: {area['pflichtstatus']}")
            previous_document_id = area["id"]
        lines.append(f"- {area['pfad']} ({area['anzahl']})")
    return "\n".join(lines)
