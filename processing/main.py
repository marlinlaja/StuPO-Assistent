# Processing: neu -> parsed -> processed -> final, englische Fassungen enden nach dem Parsen mit translation.
# Wie weit ein Dokument ist, steht in dokument.status.

import logging
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass

import psycopg
import requests

from config import EMBEDDING_MODEL, EMBEDDING_BASE_URL, LOG_FORMAT, LOG_LEVEL, PROCESSING_INTERVAL_SECONDS
from pipeline.embedding import BATCH_SIZE, embed_batch
from pipeline.parse import parse
from pipeline.process import process
from services.database import (connect, load_chunks_without_embedding, load_documents_with_status, load_pages, load_pdf,
                               save_pages, save_structure, save_vectors, set_error, set_status)



# --- Konstanten ---

if not EMBEDDING_BASE_URL:
    sys.exit("EMBEDDING_BASE_URL fehlt (in .env setzen)")

SECONDS_PER_MINUTE = 60
LOGGER = logging.getLogger("processing")
logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT)



# --- Datenmodelle ---

# Der Schritt laeuft im naechsten Durchlauf erneut, das Dokument wird nicht als fehlerhaft markiert.
class TemporaryError(Exception):
    pass



# Der Schritt hat geklappt, das Dokument bekommt aber statt des naechsten Status diesen.
class StepStopped(Exception):
    def __init__(self, status: str, reason: str):
        super().__init__(reason)
        self.status = status



@dataclass(frozen=True)
class Step:
    name: str
    from_status: str
    run: Callable[[psycopg.Connection, dict], str]
    to_status: str



@dataclass
class StepSummary:
    done: int = 0
    stopped: int = 0
    failed: int = 0
    paused: bool = False



# --- Schritte ---

def parse_document(conn: psycopg.Connection, document: dict) -> str:
    result = parse(document, load_pdf(conn, document["id"]))
    save_pages(conn, document["id"], result.pages, result.language)

    if result.language == "englisch":
        raise StepStopped("translation", "englische Fassung, wird nicht weiterverarbeitet")
    return f"{len(result.pages)} Seiten"



def process_document(conn: psycopg.Connection, document: dict) -> str:
    result = process(document, load_pages(conn, document["id"]))
    if not result.chunks:
        raise ValueError("keine Chunks, z. B. gescannte PDF ohne Text")
    save_structure(conn, document, result.modules, result.chunks, result.table_of_contents)

    if result.unknown_field_names:
        LOGGER.warning("  Unbekannte Feldnamen in Dokument %d: %s", document["id"], result.unknown_field_names)
    for message in result.skipped_modules:
        LOGGER.warning("  Modul nicht gespeichert (Dokument %d): %s", document["id"], message)
    return (f"{len(result.modules)} Module, {len(result.chunks)} Chunks, "
            f"{len(result.table_of_contents)} Abschnitte")



# Ohne Embedding API (nicht erreichbar, kein Key) pausiert der Schritt, das Dokument gilt nicht als fehlerhaft.
# Jeder Batch wird sofort gespeichert, damit ein Abbruch keine bezahlten Vektoren verwirft.
def embed_document(conn: psycopg.Connection, document: dict) -> str:
    chunks = load_chunks_without_embedding(conn, document["id"])
    LOGGER.info("  %d Chunks ohne Vektor, %d pro Batch", len(chunks), BATCH_SIZE)

    for start in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[start:start + BATCH_SIZE]
        try:
            vectors = embed_batch([chunk["text"] for chunk in batch])
        except requests.RequestException as error:
            raise TemporaryError(f"Embedding API nicht erreichbar: {error}")

        save_vectors(conn, [chunk["id"] for chunk in batch], vectors, EMBEDDING_MODEL)
        conn.commit()
        LOGGER.info("  Vektorisiert: %d/%d Chunks", start + len(batch), len(chunks))

    return f"{len(chunks)} Chunks"



STEPS = [
    Step("Parsen", "neu", parse_document, "parsed"),
    Step("Verarbeiten", "parsed", process_document, "processed"),
    Step("Vektorisieren", "processed", embed_document, "final"),
]



# --- Ablauf ---

def run_step(conn: psycopg.Connection, step: Step) -> StepSummary:
    summary = StepSummary()
    documents = load_documents_with_status(conn, step.from_status)
    if not documents:
        LOGGER.debug("%s: nichts zu tun", step.name)
        return summary

    LOGGER.info("%s: %d Dokument(e) offen", step.name, len(documents))
    for document in documents:
        should_continue = run_step_for_document(conn, step, document, summary)
        if not should_continue:
            summary.paused = True
            break

    LOGGER.info("%s beendet: %d ok, %d gestoppt, %d Fehler", step.name, summary.done, summary.stopped, summary.failed)
    return summary



# Gibt False zurueck, wenn der Schritt bis zum naechsten Durchlauf pausiert.
def run_step_for_document(conn: psycopg.Connection, step: Step, document: dict, summary: StepSummary) -> bool:
    label = f"Dokument {document['id']} ({document['titel']})"
    LOGGER.info("%s: %s", step.name, label)
    started_at = time.perf_counter()

    try:
        message = step.run(conn, document)
        set_status(conn, document["id"], step.to_status)
        conn.commit()
        summary.done += 1
        LOGGER.info("  fertig in %.1f s: %s", time.perf_counter() - started_at, message)
    except StepStopped as stop:
        set_status(conn, document["id"], stop.status)
        conn.commit()
        summary.stopped += 1
        LOGGER.info("  gestoppt: %s (Status %s)", stop, stop.status)
    except TemporaryError as error:
        conn.rollback()
        LOGGER.warning("%s pausiert bis zum nächsten Durchlauf: %s", step.name, error)
        return False
    except Exception as error:
        conn.rollback()
        set_error(conn, document["id"], f"{step.name}: {error}")
        conn.commit()
        summary.failed += 1
        LOGGER.error("  Fehler bei %s: %s", label, error, exc_info=True)
    return True



# --- Einstiegspunkt ---

def main() -> None:
    while True:
        LOGGER.info("Durchlauf gestartet")
        started_at = time.perf_counter()

        with connect() as conn:
            for step in STEPS:
                run_step(conn, step)

        LOGGER.info("Durchlauf beendet in %.0f s, nächster in %d min", time.perf_counter() - started_at,
                    PROCESSING_INTERVAL_SECONDS // SECONDS_PER_MINUTE)
        time.sleep(PROCESSING_INTERVAL_SECONDS)



if __name__ == "__main__":
    main()
