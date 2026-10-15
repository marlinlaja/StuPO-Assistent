# Crawler: sucht zu jeder Pruefungsordnung die PDFs im Internet und speichert sie samt Inhalt als Dokument in der Datenbank.
# Das Processing (processing/main.py) verarbeitet sie danach; beide Dienste kennen sich nicht und teilen nur die Datenbank.

import logging
import time
from dataclasses import dataclass

import psycopg

from config import CRAWL_INTERVAL_SECONDS, LOG_FORMAT, LOG_LEVEL
from services.database import (connect, find_document_id_by_hash, find_document_id_by_title, insert_document, link_document,
                               load_examination_regulations)
from services.pdf import calculate_sha256, read_creation_date
from services.web import fetch
from sources.archive import find_archive_documents
from sources.handbook import find_handbook_documents
from sources.models import RemoteDocument



# --- Konstanten ---

PDF_MAGIC = b"%PDF"
BYTES_PER_KB = 1024
SECONDS_PER_HOUR = 3600
LOGGER = logging.getLogger("crawler")
logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT)



# --- Datenmodell ---

@dataclass
class CrawlSummary:
    loaded: int = 0
    linked: int = 0
    failed: int = 0
    search_errors: int = 0

    def add(self, other: "CrawlSummary") -> None:
        self.loaded += other.loaded
        self.linked += other.linked
        self.failed += other.failed
        self.search_errors += other.search_errors



# --- Dokumente suchen ---

# Ein leerer Filter ueberspringt die Quelle (sonst wuerde das ganze Archiv geladen), faellt eine Quelle aus, laufen die uebrigen weiter.
def find_documents(regulation: dict, summary: CrawlSummary) -> list[RemoteDocument]:
    sources = [
        ("UEPO", regulation["filter_upo"], lambda: find_archive_documents(regulation["filter_upo"], "uebergreifende_po")),
        ("PO", regulation["filter_po"], lambda: find_archive_documents(regulation["filter_po"], "fachspezifische_po")),
        ("Modulhandbuch", regulation["filter_modulhandbuch"],
         lambda: find_handbook_documents(regulation["filter_modulhandbuch"])),
    ]

    documents = []
    for name, search_filter, search in sources:
        if not search_filter.strip():
            LOGGER.debug("  %s übersprungen (kein Filter)", name)
            continue

        try:
            found = search()
        except Exception as error:
            summary.search_errors += 1
            LOGGER.error("  Suche fehlgeschlagen (%s, PO %s): %s", name, regulation["id"], error)
            continue

        LOGGER.info("  %s: %d Dokument(e) gefunden", name, len(found))
        documents += found
    return documents



# --- Dokumente laden ---

# Ein Dokument mit gleichem Titel ist schon da und wird nur mit der PO verknuepft (die UEPO gehoert zu vielen POs).
def sync_document(conn: psycopg.Connection, regulation_id: int, document: RemoteDocument, summary: CrawlSummary) -> None:
    document_id = find_document_id_by_title(conn, document.title)
    if document_id is not None:
        LOGGER.debug("  Bereits vorhanden: %s (Dokument %d)", document.title, document_id)
        summary.linked += 1
        link_document(conn, regulation_id, document_id)
        return

    document_id, is_new = download_document(conn, document)
    if is_new:
        summary.loaded += 1
    else:
        summary.linked += 1

    link_document(conn, regulation_id, document_id)



# Rueckgabe: Dokument-ID und ob das Dokument neu angelegt wurde
def download_document(conn: psycopg.Connection, document: RemoteDocument) -> tuple[int, bool]:
    content = fetch(document.url).content
    if not content.startswith(PDF_MAGIC):
        raise ValueError(f"keine PDF unter {document.url}")

    sha256 = calculate_sha256(content)
    existing_id = find_document_id_by_hash(conn, sha256)
    if existing_id is not None:
        LOGGER.info("  Inhalt schon vorhanden: %s (Dokument %d, gleicher Hash)", document.title, existing_id)
        return existing_id, False

    document_id = insert_document(conn, build_record(document, content, sha256))
    LOGGER.info("  Geladen: %s (Dokument %d, %d KB)", document.title, document_id, len(content) // BYTES_PER_KB)
    return document_id, True



# Modulhandbuecher haben im Internet kein Erscheinungsdatum, dort steht das Erstellungsdatum der PDF.
def build_record(document: RemoteDocument, content: bytes, sha256: str) -> dict:
    return {
        "typ": document.document_type,
        "titel": document.title,
        "semester": document.semester,
        "erschienen_am": document.published_on or read_creation_date(content),
        "dateiname": f"{document.title}.pdf",
        "sha256": sha256,
        "pdf": content,
    }



# --- Ablauf ---

def crawl_regulation(conn: psycopg.Connection, regulation: dict) -> CrawlSummary:
    summary = CrawlSummary()
    label = f"{regulation['name']} {regulation['abschluss']} PO {regulation['jahr']}"
    LOGGER.info("%s (ID %s)", label, regulation["id"])
    documents = find_documents(regulation, summary)

    for document in documents:
        try:
            sync_document(conn, regulation["id"], document, summary)
            conn.commit()
        except Exception as error:
            conn.rollback()
            summary.failed += 1
            LOGGER.error("  Fehler bei %s: %s", document.title, error)

    return summary



def crawl_all(conn: psycopg.Connection) -> CrawlSummary:
    find_archive_documents.cache_clear()
    find_handbook_documents.cache_clear()

    regulations = load_examination_regulations(conn)
    LOGGER.info("Crawl gestartet: %d Prüfungsordnung(en)", len(regulations))
    started_at = time.perf_counter()

    total = CrawlSummary()
    for regulation in regulations:
        total.add(crawl_regulation(conn, regulation))

    LOGGER.info(
        "Crawl beendet in %.0f s: %d neu geladen, %d verknüpft, %d Fehler, %d Suchfehler",
        time.perf_counter() - started_at, total.loaded, total.linked, total.failed, total.search_errors,
    )
    return total



# --- Einstiegspunkt ---

def main() -> None:
    while True:
        with connect() as conn:
            crawl_all(conn)
        LOGGER.info("Nächster Crawl in %d h", CRAWL_INTERVAL_SECONDS // SECONDS_PER_HOUR)
        time.sleep(CRAWL_INTERVAL_SECONDS)



if __name__ == "__main__":
    main()
