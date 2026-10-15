# Drei Schritte: 1. Recherche mit Tools, 2. Antwort nur aus dem gefundenen Material (mit Quellennummern hinter den
# Saetzen), 3. Zitate zu den Saetzen suchen und pruefen (citations.py).

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from assistant.api_call import TokenUsage, call_llm
from assistant.citations import add_citations
from assistant.indexes import describe_indexes
from assistant.material import render_as_text
from assistant.tools import get_document_index, get_module, get_neighbors, get_section, query_modules, search
from config import HISTORY_MESSAGES
from services.database import connect
from services.sources import build_source_profiles



# --- Konstanten ---

PROMPTS_DIR = Path(__file__).parent / "prompts"
TOOLS = [get_document_index, search, get_section, get_neighbors, get_module, query_modules]
MAX_RESEARCH_ROUNDS = 8
ROLES = {"nutzer": "user", "assistent": "assistant"}

STORED_MARKER = re.compile(r"\s*\[\[[^\]]*\]\]")

# Die Antwort führt die Unterhaltung der Recherche weiter (alles bis dahin kommt aus dem Cache). Geht das schief,
# bekommt sie wie früher einen eigenen Prompt mit dem Material.
ANSWER_IN_RESEARCH_CONVERSATION = True

SOURCES_REMINDER = ("Jeder Satz, Absatz und Listenpunkt, der auf dem Material beruht, endet mit den Nummern seiner "
                    "Quellen in eckigen Klammern, z. B. [Q1] oder [Q1, Q3]. Beantworte nur, was gefragt wurde, und "
                    "halte die Antwort kurz.")
ANSWER_REQUEST = ("Die Recherche ist abgeschlossen, ihre Ergebnisse stehen oben als Material mit Quellennummern "
                  "(Q1, Q2, ...). Ab jetzt bist du der Antwortschritt und rufst keine Tools mehr auf. Für die Antwort "
                  "gilt:\n\n{rules}\n\n---\n\nFrage: {question}\n\n{reminder}")
# Was das Frontend während der Recherche anzeigt; ein Tool ohne Eintrag zeigt seinen Namen
TOOL_STATUS = {
    "search": "Sucht nach „{query}“",
    "get_section": "Liest einen Abschnitt",
    "get_neighbors": "Liest den Text um einen Treffer",
    "get_module": "Liest ein Modul",
    "query_modules": "Fragt Module ab",
    "get_document_index": "Liest ein Verzeichnis",
}
SUMMER_SEMESTER_MONTHS = range(4, 10)
WINTER_SEMESTER_START_MONTH = 10



# --- Datenmodell ---

StatusReporter = Callable[[str], None]



# role wie in nachricht.rolle: "nutzer" oder "assistent"
@dataclass(frozen=True)
class ChatMessage:
    role: str
    text: str



# --- Antwort ---

# Das Ergebnis wird so als nachricht.inhalt gespeichert. thinking gilt fuer Recherche und Antwort, siehe call_llm
def answer_question(question: str, document_ids: list[int], history: list[ChatMessage], thinking: str,
                    report_status: StatusReporter = lambda text: None) -> dict:
    start = time.monotonic()
    usage = TokenUsage()
    history = recent_history(history)
    steps = []

    step_start = time.monotonic()
    report_status("Recherchiert in den Dokumenten")
    research_result = research(question, document_ids, history, usage, thinking, report_status)
    steps.append(timed_step("Recherche", step_start))

    step_start = time.monotonic()
    report_status("Schreibt die Antwort")
    message, answer_usage = write_answer(question, history, research_result, thinking)
    usage.add(answer_usage)
    steps.append(timed_step("Antwort", step_start))

    step_start = time.monotonic()
    report_status("Sucht Belege im Text")
    markdown, citation_usage = add_citations(message["content"], research_result.material,
                                             research_result.sources_by_number, question)
    usage.add(citation_usage)
    steps.append(timed_step("Zitate", step_start))

    return {
        "markdown": markdown,
        "quellen": build_source_profiles(markdown),
        "sekunden": round(time.monotonic() - start, 1),
        "schritte": steps,
        "tokens": {"eingabe": usage.input, "ausgabe": usage.output},
        "thinking": thinking,
    }



# Dauer eines Schritts fuer die Anzeige im Frontend
def timed_step(name: str, started_at: float) -> dict:
    return {"name": name, "sekunden": round(time.monotonic() - started_at, 1)}



# Nur die gewählten Dokumente stehen zur Verfügung, und nur fertige. Ohne Auswahl gibt es keine Dokumente.
def select_available_documents(document_ids: list[int]) -> list[int]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT id FROM dokument WHERE status = 'final' AND id = ANY(%s) ORDER BY id", (document_ids,)
        ).fetchall()

    return [row["id"] for row in rows]



# --- Recherche ---

# conversation = alle Nachrichten der Recherche, die Antwort führt sie weiter; material = alle Tool-Ergebnisse als Text
# mit nummerierten Quellen (Q1, Q2, ...); sources_by_number = welche Quellen-ID hinter welcher Nummer steht
@dataclass
class ResearchResult:
    material: str
    sources_by_number: dict[int, str]
    conversation: list[dict]



# Die Recherche kennt die Verzeichnisse der Prüfungsordnungen schon aus ihrem Prompt. Sie ruft Tools auf, bis das LLM
# keine mehr will (es schreibt FERTIG).
def research(question: str, document_ids: list[int], history: list[ChatMessage], usage: TokenUsage,
             thinking: str, report_status: StatusReporter) -> ResearchResult:
    definitions = tool_definitions()
    tools_by_name = {definition["function"]["name"]: tool for definition, tool in zip(definitions, TOOLS)}
    numbers_by_source = {}
    material = []

    placeholders = {"<<DOKUMENTE>>": describe_documents(document_ids), "<<VERZEICHNISSE>>": describe_indexes(document_ids)}
    messages = build_messages("research.md", history, question, placeholders)

    # Ohne Dokumente gibt es nichts zu recherchieren, die Antwort sagt das dann
    rounds = MAX_RESEARCH_ROUNDS if document_ids else 0

    for _ in range(rounds):
        message, round_usage = call_llm(messages, definitions, thinking)
        usage.add(round_usage)
        messages.append(message)
        if "tool_calls" not in message:
            break
        for tool_call in message["tool_calls"]:
            report_status(describe_tool_call(tool_call))
            result = run_tool(tools_by_name, tool_call, document_ids)
            text = render_as_text(result, numbers_by_source)
            messages.append(tool_message(tool_call, text))
            material.append(material_entry(tool_call, text))

    sources_by_number = {number: source_id for source_id, number in numbers_by_source.items()}
    return ResearchResult("\n\n".join(material) or "(nichts abgerufen)", sources_by_number, messages)



def describe_tool_call(tool_call: dict) -> str:
    name = tool_call["function"]["name"]
    template = TOOL_STATUS.get(name, name)
    try:
        arguments = json.loads(tool_call["function"]["arguments"] or "{}")
        return template.format(**arguments)
    except (ValueError, KeyError, IndexError):
        return template.split(" „")[0]



def tool_definitions() -> list[dict]:
    return [tool.get_definition() for tool in TOOLS]



# Fehler gehen als Ergebnis ans LLM, damit es reagieren kann; im Log stehen sie auch.
def run_tool(tools_by_name: dict, tool_call: dict, document_ids: list[int]) -> dict | list:
    name = tool_call["function"]["name"]
    try:
        arguments = json.loads(tool_call["function"]["arguments"] or "{}")
        print(f"Tool {name} {arguments}", flush=True)
        return tools_by_name[name].run(document_ids, **arguments)
    except Exception as error:
        print(f"Tool {name} fehlgeschlagen: {type(error).__name__}: {error}", flush=True)
        return {"fehler": f"{type(error).__name__}: {error}"}



def tool_message(tool_call: dict, text: str) -> dict:
    return {"role": "tool", "tool_call_id": tool_call["id"], "content": text}



def material_entry(tool_call: dict, text: str) -> str:
    function = tool_call["function"]
    return f"### {function['name']} {function['arguments']}\n\n{text}"



# --- Antwort schreiben ---

# Die Antwort hängt als letzte Nachricht an der Unterhaltung der Recherche, ihr ganzer Anfang kommt so aus dem Cache.
# Scheitert das (z. B. weil die API die Nachrichtenfolge ablehnt), schreibt ein eigener Prompt mit dem Material die
# Antwort, wie es vorher war.
def write_answer(question: str, history: list[ChatMessage], research_result: ResearchResult,
                 thinking: str) -> tuple[dict, TokenUsage]:
    if ANSWER_IN_RESEARCH_CONVERSATION:
        try:
            request = answer_request(question)
            messages = research_result.conversation + [{"role": "user", "content": request}]
            return call_llm(messages, tool_definitions(), thinking, step="Antwort", tool_choice="none")
        except Exception as error:
            print(f"Antwort in der Recherche-Unterhaltung fehlgeschlagen: {type(error).__name__}: {error}", flush=True)

    # Frage und Erinnerung nach dem Material, damit sie bei langem Material nicht untergehen
    prompt = f"Material aus der Recherche:\n\n{research_result.material}\n\n---\n\nFrage: {question}\n\n{SOURCES_REMINDER}"
    return call_llm(build_messages("answer.md", history, prompt), thinking=thinking)



def answer_request(question: str) -> str:
    rules = (PROMPTS_DIR / "answer.md").read_text()
    return ANSWER_REQUEST.format(rules=rules, question=question, reminder=SOURCES_REMINDER)



# --- Prompt ---

# Alte Marken fallen aus dem Verlauf, ihre Quellen-IDs passen nicht zu den Nummern im neuen Material.
# placeholders = Platzhalter im Prompt (z. B. <<DOKUMENTE>>) und ihr Text
def build_messages(prompt_file: str, history: list[ChatMessage], message: str,
                   placeholders: dict[str, str] | None = None) -> list[dict]:
    prompt = (PROMPTS_DIR / prompt_file).read_text()
    for placeholder, text in (placeholders or {}).items():
        prompt = prompt.replace(placeholder, text)
    system_prompt = f"{prompt}\n\n{describe_today()}"
    messages = [{"role": "system", "content": system_prompt}]

    for entry in history:
        text = STORED_MARKER.sub("", entry.text)
        messages.append({"role": ROLES[entry.role], "content": text})

    messages.append({"role": "user", "content": message})
    return messages



def recent_history(history: list[ChatMessage]) -> list[ChatMessage]:
    if HISTORY_MESSAGES <= 0:
        return []

    return history[-HISTORY_MESSAGES:]



def describe_documents(document_ids: list[int]) -> str:
    with connect() as conn:
        documents = conn.execute(
            "SELECT id, typ, titel, semester FROM dokument WHERE id = ANY(%s) ORDER BY id", (document_ids,)
        ).fetchall()

    lines = []
    for document in documents:
        semester = f", {document['semester']}" if document["semester"] else ""
        lines.append(f"- {document['id']}: {document['titel']}, {document['typ']}{semester}")
    return "\n".join(lines)



def describe_today() -> str:
    today = date.today()
    return f"Heute ist der {today:%d.%m.%Y}, also im {semester_name(today)}."



def semester_name(day: date) -> str:
    if day.month in SUMMER_SEMESTER_MONTHS:
        return f"Sommersemester {day.year}"

    start_year = day.year if day.month >= WINTER_SEMESTER_START_MONTH else day.year - 1
    return f"Wintersemester {start_year}/{(start_year + 1) % 100:02d}"
