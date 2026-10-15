import re

import psycopg

from services.database import connect



# --- Konstanten ---

MARKER = re.compile(r"\[\[([^\]]+)\]\]")
SOURCE_ID = re.compile(r"\b[cm]\d+\b")
QUOTED_SOURCE = re.compile(r"\b([cm]\d+)(?:\s*»([^«]*)«)?")
CHUNK_PREFIX = "c"
MODULE_PREFIX = "m"
PATH_SEPARATOR = " › "



# --- Steckbriefe ---

# Steckbrief jeder Quelle in den Marken einer Antwort: {"c1162": {dokument_id, dokument, seite, titel}, "m225": ...}
def build_source_profiles(markdown: str) -> dict:
    source_ids = source_ids_in_markers(markdown)
    chunk_numbers = [int(source_id[1:]) for source_id in source_ids if source_id.startswith(CHUNK_PREFIX)]
    module_numbers = [int(source_id[1:]) for source_id in source_ids if source_id.startswith(MODULE_PREFIX)]

    with connect() as conn:
        chunks = load_chunk_profiles(conn, chunk_numbers)
        modules = load_module_profiles(conn, module_numbers)

    profiles = {}
    for profile in chunks + modules:
        profiles[profile.pop("id")] = profile
    return profiles



# Alle Stellen der Marken einer Antwort als (Quellen-ID, Zitat); mehrere Zitate derselben Quelle in einer Marke stehen
# zusammen, durch Zeilenumbruch getrennt, so wie das Frontend sie beim Klick anfragt.
def passages_in_markers(markdown: str) -> list[tuple[str, str]]:
    passages = []
    for marker in MARKER.findall(markdown):
        quotes_by_source: dict[str, list[str]] = {}
        for match in QUOTED_SOURCE.finditer(marker):
            quotes = quotes_by_source.setdefault(match.group(1), [])
            if match.group(2):
                quotes.append(match.group(2))
        passages += [(source_id, "\n".join(quotes)) for source_id, quotes in quotes_by_source.items()]
    return passages



def source_ids_in_markers(markdown: str) -> set[str]:
    source_ids = set()
    for marker in MARKER.findall(markdown):
        source_ids.update(SOURCE_ID.findall(marker))
    return source_ids



# Vom Abschnittspfad eines Chunks reicht der letzte Teil als Titel.
def load_chunk_profiles(conn: psycopg.Connection, chunk_numbers: list[int]) -> list[dict]:
    chunks = conn.execute(
        """
        SELECT 'c' || c.id AS id, c.dokument_id, c.start_seite AS seite, c.abschnitt AS titel
        FROM chunk c WHERE c.id = ANY(%s)
        """,
        (chunk_numbers,),
    ).fetchall()

    for chunk in chunks:
        chunk["titel"] = chunk["titel"].split(PATH_SEPARATOR)[-1]
    return chunks



def load_module_profiles(conn: psycopg.Connection, module_numbers: list[int]) -> list[dict]:
    return conn.execute(
        """
        SELECT 'm' || m.id AS id, m.handbuch_id AS dokument_id, m.seite_von AS seite, m.titel
        FROM modul m WHERE m.id = ANY(%s)
        """,
        (module_numbers,),
    ).fetchall()
