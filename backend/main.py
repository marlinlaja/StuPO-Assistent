import json
import queue
import threading
from datetime import date
from typing import Annotated, Literal

import psycopg
from fastapi import FastAPI, HTTPException, Path, Query
from fastapi.responses import Response, StreamingResponse
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from assistant.answer import ChatMessage, answer_question, select_available_documents
from config import DEFAULT_THINKING
from services.database import connect
from services.highlight import passage_areas, precompute_passages
from services.sources import passages_in_markers



# --- Konstanten ---

# Grenzen für Eingaben des Frontends
MAX_QUESTION_LENGTH = 2000
MAX_DOCUMENTS_PER_QUESTION = 50
MAX_QUOTE_LENGTH = 4000
# Der Tagesverbrauch an Tokens beginnt um Mitternacht dieser Zeitzone bei null
TODAY_SQL = "(now() AT TIME ZONE 'Europe/Berlin')::date"
# Tokens (Eingabe und Ausgabe), die ein Nutzer pro Tag verbrauchen darf; danach kommt keine Antwort mehr. Richtwert, der
# angepasst werden muss.
DAILY_TOKEN_BUDGET = 1_000_000
SOURCE_ID_PATTERN = r"^[cm][0-9]+$"

# "none" = ohne Thinking, sonst die Stufe fuer reasoning_effort von DeepSeek
ThinkingLevel = Literal["none", "low", "high", "max"]



# --- Datenmodelle ---

# Feldnamen wie im JSON der API
class Document(BaseModel):
    id: int
    typ: str
    titel: str
    semester: str | None
    erschienen_am: date | None
    seiten: int



class Regulation(BaseModel):
    id: int
    jahr: int
    dokument_ids: list[int]



class Program(BaseModel):
    id: int
    name: str
    abschluss: str
    pruefungsordnungen: list[Regulation]



class Catalog(BaseModel):
    studiengaenge: list[Program]
    dokumente: list[Document]



class QuestionRequest(BaseModel):
    frage: str = Field(min_length=1, max_length=MAX_QUESTION_LENGTH)
    dokument_ids: list[int] = Field(max_length=MAX_DOCUMENTS_PER_QUESTION)
    thinking: ThinkingLevel = DEFAULT_THINKING
    chat_id: int | None = None
    nutzer_id: int | None = None



# --- App ---

app = FastAPI()



# --- Status ---

@app.get("/health")
def get_health() -> dict:
    return {"status": "ok"}



# --- Katalog ---

# Alle Studiengänge mit ihren Prüfungsordnungen (neuestes Jahr zuerst) und alle fertigen Dokumente (neueste Version zuerst).
# Welche Dokumente zu einer Prüfungsordnung gehören, steht dort als Liste von IDs.
@app.get("/katalog")
def get_catalog() -> Catalog:
    with connect() as conn:
        programs = conn.execute("SELECT id, name, abschluss FROM studiengang ORDER BY name, abschluss").fetchall()
        regulations = conn.execute(
            "SELECT id, studiengang_id, jahr FROM pruefungsordnung ORDER BY jahr DESC"
        ).fetchall()
        documents = load_documents(conn)
        links = conn.execute("SELECT pruefungsordnung_id, dokument_id FROM zugehoerig").fetchall()

    return Catalog(studiengaenge=build_programs(programs, regulations, documents, links), dokumente=documents)



def load_documents(conn: psycopg.Connection) -> list[dict]:
    return conn.execute(
        """
        SELECT id, typ, titel, semester, erschienen_am,
               (SELECT count(*) FROM seite WHERE seite.dokument_id = dokument.id) AS seiten
        FROM dokument
        WHERE status = 'final'
        ORDER BY erschienen_am DESC NULLS LAST, titel
        """
    ).fetchall()



def build_programs(programs: list[dict], regulations: list[dict], documents: list[dict], links: list[dict]) -> list[Program]:
    document_order = [document["id"] for document in documents]
    result = []

    for program in programs:
        program_regulations = []
        for regulation in regulations:
            if regulation["studiengang_id"] != program["id"]:
                continue
            linked_ids = {link["dokument_id"] for link in links if link["pruefungsordnung_id"] == regulation["id"]}
            document_ids = [document_id for document_id in document_order if document_id in linked_ids]
            program_regulations.append(Regulation(id=regulation["id"], jahr=regulation["jahr"], dokument_ids=document_ids))
        result.append(Program(**program, pruefungsordnungen=program_regulations))

    return result



# Ohne Dateinamen im Header zeigt der Browser das PDF an, statt es herunterzuladen.
@app.get("/dokumente/{document_id}/pdf")
def get_document_pdf(document_id: int) -> Response:
    with connect() as conn:
        document = conn.execute(
            "SELECT pdf FROM dokument WHERE id = %s AND status = 'final'", (document_id,)
        ).fetchone()

    if document is None:
        raise HTTPException(404, f"Dokument {document_id} gibt es nicht")
    return Response(bytes(document["pdf"]), media_type="application/pdf")



# --- Quellen ---

# Seite und Markierungen des Zitats in einem Chunk (c1162) oder Modul (m225)
@app.get("/quellen/{source_id}/stelle")
def get_source_passage(
    source_id: Annotated[str, Path(pattern=SOURCE_ID_PATTERN)],
    zitat: Annotated[str, Query(max_length=MAX_QUOTE_LENGTH)] = "",
) -> dict:
    passage = passage_areas(source_id, zitat)
    if passage is None:
        raise HTTPException(404, f"Quelle {source_id} gibt es nicht")
    return passage



# --- Chats ---

@app.get("/chats/{chat_id}")
def get_chat(chat_id: int) -> dict:
    with connect() as conn:
        if not conn.execute("SELECT 1 FROM chat WHERE id = %s", (chat_id,)).fetchone():
            raise HTTPException(404, f"Chat {chat_id} gibt es nicht")
        attached = conn.execute(
            "SELECT dokument_id FROM angehaengt WHERE chat_id = %s ORDER BY dokument_id", (chat_id,)
        ).fetchall()
        messages = conn.execute(
            "SELECT rolle, inhalt FROM nachricht WHERE chat_id = %s ORDER BY position", (chat_id,)
        ).fetchall()

    return {"dokument_ids": [row["dokument_id"] for row in attached], "nachrichten": messages}



# Ohne chat_id beginnt ein neuer Chat, ohne (gültige) nutzer_id wird ein neuer Nutzer angelegt. Die Antwort kommt als
# Stream, eine JSON-Zeile pro Ereignis: {"status": ...} während der Arbeit, am Ende {"ergebnis": ...} oder {"fehler": ...}.
# Frage und Antwort werden erst gespeichert, wenn die Antwort da ist. Die Stellen der Antwort rechnet das Backend danach
# vor, damit ein Klick auf einen Beleg sofort geht.
@app.post("/nachrichten")
def ask_question(request: QuestionRequest) -> StreamingResponse:
    check_token_budget(request.nutzer_id)

    events = queue.Queue()
    threading.Thread(target=run_question, args=(request, events), daemon=True).start()
    return StreamingResponse(stream_events(events), media_type="application/x-ndjson")



# Läuft in einem eigenen Thread; None in der Queue beendet den Stream
def run_question(request: QuestionRequest, events: queue.Queue) -> None:
    try:
        result = answer_and_save(request, lambda text: events.put({"status": text}))
    except Exception as error:
        print(f"Frage fehlgeschlagen: {type(error).__name__}: {error}", flush=True)
        events.put({"fehler": "Die Antwort konnte nicht erstellt werden"})
        events.put(None)
        return

    events.put({"ergebnis": result})
    events.put(None)
    precompute_passages(passages_in_markers(result["markdown"]))



def stream_events(events: queue.Queue):
    while (event := events.get()) is not None:
        yield json.dumps(event, ensure_ascii=False) + "\n"



def answer_and_save(request: QuestionRequest, report_status) -> dict:
    messages = load_messages(request.chat_id)
    history = [as_chat_message(message) for message in messages]
    document_ids = select_available_documents(request.dokument_ids)
    answer = answer_question(request.frage, document_ids, history, request.thinking, report_status)

    with connect() as conn:
        user_id = find_or_create_user(conn, request.nutzer_id)
        chat_id = request.chat_id or create_chat(conn, user_id)
        attach_documents(conn, chat_id, document_ids)
        save_message(conn, chat_id, len(messages), "nutzer", {"text": request.frage})
        save_message(conn, chat_id, len(messages) + 1, "assistent", answer)
        add_token_usage(conn, user_id, answer.get("tokens", {}))
        usage = load_token_usage(conn, user_id)

    return {**answer, "chat_id": chat_id, "nutzer_id": user_id, "tagesverbrauch": usage}



def load_messages(chat_id: int | None) -> list[dict]:
    if chat_id is None:
        return []

    return get_chat(chat_id)["nachrichten"]



def as_chat_message(message: dict) -> ChatMessage:
    content = message["inhalt"]
    return ChatMessage(message["rolle"], content.get("text") or content["markdown"])



def find_or_create_user(conn: psycopg.Connection, user_id: int | None) -> int:
    if user_id is not None and conn.execute("SELECT 1 FROM nutzer WHERE id = %s", (user_id,)).fetchone():
        return user_id

    new_user_id = conn.execute("INSERT INTO nutzer DEFAULT VALUES RETURNING id").fetchone()["id"]
    conn.execute("INSERT INTO sitzung (nutzer_id) VALUES (%s)", (new_user_id,))
    return new_user_id



# --- Tagesverbrauch ---

# Zählt die Tokens einer Antwort zum Verbrauch des Tages. Liegt der gespeicherte Tag vor heute, beginnt der Zähler bei
# null, so gilt er ab Mitternacht neu, ohne dass ein Job laufen muss.
def add_token_usage(conn: psycopg.Connection, user_id: int, tokens: dict) -> None:
    conn.execute(
        f"""
        INSERT INTO sitzung (nutzer_id, eingabe_tokens, ausgabe_tokens)
        VALUES (%(user)s, %(input)s, %(output)s)
        ON CONFLICT (nutzer_id) DO UPDATE SET
          eingabe_tokens = CASE WHEN sitzung.token_tag = {TODAY_SQL} THEN sitzung.eingabe_tokens ELSE 0 END
                           + EXCLUDED.eingabe_tokens,
          ausgabe_tokens = CASE WHEN sitzung.token_tag = {TODAY_SQL} THEN sitzung.ausgabe_tokens ELSE 0 END
                           + EXCLUDED.ausgabe_tokens,
          token_tag = {TODAY_SQL},
          zuletzt_aktiv = now()
        """,
        {"user": user_id, "input": tokens.get("eingabe", 0), "output": tokens.get("ausgabe", 0)},
    )



# Ist das Tagesbudget des Nutzers aufgebraucht, gibt es keine Antwort mehr (429); ohne Nutzer gibt es noch nichts zu prüfen
def check_token_budget(user_id: int | None) -> None:
    if user_id is None:
        return

    with connect() as conn:
        usage = load_token_usage(conn, user_id)
    if usage["eingabe"] + usage["ausgabe"] >= DAILY_TOKEN_BUDGET:
        raise HTTPException(429, "Das Tagesbudget an Tokens ist aufgebraucht")



# Verbrauch von heute; ein älterer Stand zählt als 0
def load_token_usage(conn: psycopg.Connection, user_id: int) -> dict:
    row = conn.execute(
        f"""
        SELECT CASE WHEN token_tag = {TODAY_SQL} THEN eingabe_tokens ELSE 0 END AS eingabe,
               CASE WHEN token_tag = {TODAY_SQL} THEN ausgabe_tokens ELSE 0 END AS ausgabe
        FROM sitzung WHERE nutzer_id = %s
        """,
        (user_id,),
    ).fetchone()
    return {"eingabe": row["eingabe"] if row else 0, "ausgabe": row["ausgabe"] if row else 0, "limit": DAILY_TOKEN_BUDGET}



# Verbrauch von heute, damit das Frontend ihn beim Start anzeigen kann
@app.get("/nutzer/{user_id}/verbrauch")
def get_token_usage(user_id: int) -> dict:
    with connect() as conn:
        if conn.execute("SELECT 1 FROM nutzer WHERE id = %s", (user_id,)).fetchone() is None:
            raise HTTPException(404, f"Nutzer {user_id} gibt es nicht")
        return load_token_usage(conn, user_id)



# --- Chats ---

def create_chat(conn: psycopg.Connection, user_id: int) -> int:
    return conn.execute("INSERT INTO chat (nutzer_id) VALUES (%s) RETURNING id", (user_id,)).fetchone()["id"]



def attach_documents(conn: psycopg.Connection, chat_id: int, document_ids: list[int]) -> None:
    conn.execute("DELETE FROM angehaengt WHERE chat_id = %s", (chat_id,))
    conn.execute(
        "INSERT INTO angehaengt (chat_id, dokument_id) SELECT %s, id FROM dokument WHERE id = ANY(%s)",
        (chat_id, document_ids),
    )



def save_message(conn: psycopg.Connection, chat_id: int, position: int, role: str, content: dict) -> None:
    conn.execute(
        "INSERT INTO nachricht (chat_id, position, rolle, inhalt) VALUES (%s, %s, %s, %s)",
        (chat_id, position, role, Jsonb(content)),
    )
