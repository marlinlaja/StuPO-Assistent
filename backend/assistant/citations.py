# Dritter Schritt der Antwort: Zu jedem Satz mit Quellennummern ([Q1], [Q2–Q4]) sucht ein eigener LLM-Aufruf die
# wörtlichen Zitate in diesen Quellen. Der Server prüft jedes Zitat gegen den Text der Quelle; was nicht wörtlich darin
# steht, fliegt raus, und ein Satz ohne gültiges Zitat gilt als unbelegt. Das Ergebnis sind die gespeicherten Marken
# [[belegt: c1162 »Zitat«]], die das Frontend im Text und im PDF markiert. Nannte die Antwort eine Quelle, fand der
# Zitier-Schritt aber kein Zitat, steht [[nicht_gefunden: c1162]] (rot); ohne Quelle in der Antwort [[hinweis]] (grau).

import json
import re
from dataclasses import dataclass
from pathlib import Path

from assistant.api_call import TokenUsage, call_llm
from services.database import connect



# --- Konstanten ---

PROMPT_FILE = Path(__file__).parent / "prompts" / "cite.md"
# Das Zitieren ist eine enge Abschreibaufgabe und braucht kein Denken
CITATION_THINKING = "none"

# "Q1", "Q2–Q4", "Q2 bis Q4" (ein Bereich meint alle Nummern dazwischen)
NUMBER_ITEM = r"Q(\d+)(?:\s*(?:–|-|bis)\s*Q?(\d+))?"
ITEM = re.compile(NUMBER_ITEM)
SOURCE_TAG = re.compile(rf"\s*\[({NUMBER_ITEM}(?:\s*[,;]\s*{NUMBER_ITEM})*)\]")
SOURCE_HEADING = re.compile(r"^\s*(?:- )?\[Q(\d+)\]")
MODULE_PREFIX = "m"
MODULE_TITLE_LINE = re.compile(r"^Modultitel:\s*(.+)$", re.MULTILINE)
TRAILING_BRACKET = re.compile(r"\s*\([^()]*\)\s*$")
TAG_IN_ANSWER = re.compile(r"\s*\[Q[^\]]*\]")
TOOL_HEADING = "### "

# Beim Vergleich zählen Leerraum, Trennstriche, Anführungszeichen, Tabellenstriche und ähnliches nicht, wie bei der
# Suche im PDF (services/highlight.py)
IGNORED_IN_QUOTE = re.compile(r"[\s\-–„“”\"»«‚‘’'|()\[\]*:;•]")
MIN_QUOTE_CHARACTERS = 6
LIST_ITEM = re.compile(r"^(?:[-*+]|\d+\.)\s+")
TEXT_CHARACTER = re.compile(r"[A-Za-zÄÖÜäöüß0-9]")
# Überschrift: Markdown-Überschrift oder eine Zeile, die nur aus fettem Text besteht (z. B. ein Gruppenname in einer Liste)
BOLD_ONLY_LINE = re.compile(r"\*\*[^*]+\*\*:?")

KINDS = ("belegt", "abgeleitet", "hinweis")
DEFAULT_KIND = "abgeleitet"
NOT_FOUND_KIND = "nicht_gefunden"
NOTE_KIND = "hinweis"



# --- Datenmodelle ---

# Ein Satz, Absatz oder Listenpunkt mit den Quellen dahinter. number ist seine Nummer im Aufruf an das Zitier-LLM
# (0 = ohne Quellen, geht nicht dorthin).
@dataclass
class Statement:
    text: str
    numbers: list[int]
    number: int = 0



@dataclass(frozen=True)
class Quote:
    source_number: int
    text: str



# kind und quotes einer Aussage nach der Prüfung; source_numbers (die Quellen der Antwort, ohne Zitat) stehen nur bei
# "nicht_gefunden" und bei "abgeleitet" als Ausweg, wenn das Zitieren ausgefallen ist
@dataclass
class Citation:
    kind: str
    quotes: list[Quote]
    source_numbers: list[int]



# --- Einstieg ---

# Setzt hinter jede Aussage der Antwort die Marke mit den geprüften Zitaten. Gibt den Text mit den Marken und den
# Verbrauch des Zitier-Aufrufs zurück.
def add_citations(answer: str, material: str, sources_by_number: dict[int, str],
                  question: str) -> tuple[str, TokenUsage]:
    lines = [parse_line(line, set(sources_by_number)) for line in attach_stray_tags(answer.split("\n"))]
    inherit_list_sources(lines)
    statements = [statement for line in lines for statement in line if statement.numbers]
    for number, statement in enumerate(statements, start=1):
        statement.number = number

    material_texts = split_source_texts(material)
    chunk_texts = load_module_chunk_texts(statements, sources_by_number, material_texts)
    context = describe_context(question, answer)
    citations, usage = find_citations(statements, {**material_texts, **chunk_texts},
                                      merge_texts(material_texts, chunk_texts), context)
    add_module_titles(statements, citations, chunk_texts)
    drop_nested_quotes(citations)

    markdown = "\n".join(render_line(line, citations, sources_by_number) for line in lines)
    return markdown, usage



# --- Aussagen der Antwort ---

# Hängt das Modell die Quelle nur an die Einleitungszeile einer Liste ("Die Verteilung sieht so aus: [Q2]"), gilt sie für
# die Listenpunkte darunter, die keine eigene haben. Ein Punkt mit eigener Quelle behält sie, eine andere Zeile beendet die
# Liste.
def inherit_list_sources(lines: list[list[Statement]]) -> None:
    inherited: list[int] = []
    for line in lines:
        text = "".join(statement.text for statement in line).strip()
        if not text:
            continue

        if LIST_ITEM.match(text):
            add_inherited_numbers(line, inherited)
            continue

        numbers = [number for statement in line for number in statement.numbers]
        inherited = numbers if text.endswith(":") else []



def add_inherited_numbers(line: list[Statement], inherited: list[int]) -> None:
    if not inherited or any(statement.numbers for statement in line):
        return

    first_text = next((statement for statement in line if has_text(statement.text)), None)
    if first_text:
        first_text.numbers = list(inherited)

# Steht eine Quellennummer allein in einer Zeile, gehört sie zur Zeile davor.
def attach_stray_tags(lines: list[str]) -> list[str]:
    result = []
    for line in lines:
        previous_index = last_text_index(result)
        if SOURCE_TAG.fullmatch(line.strip()) and previous_index is not None:
            result[previous_index] += f" {line.strip()}"
            continue
        result.append(line)
    return result



def last_text_index(lines: list[str]) -> int | None:
    for index in range(len(lines) - 1, -1, -1):
        if lines[index].strip():
            return index
    return None



# Zerlegt eine Zeile an den Quellennummern: "Satz eins. [Q1] Satz zwei. [Q2]" -> zwei Aussagen mit ihren Nummern, dazu
# der Rest hinter der letzten Nummer. Unbekannte Nummern fallen weg.
def parse_line(line: str, valid_numbers: set[int]) -> list[Statement]:
    statements = []
    leading_numbers = []
    position = 0

    for match in SOURCE_TAG.finditer(line):
        numbers = [number for number in numbers_in(match.group(1)) if number in valid_numbers]
        text = line[position:match.start()]
        position = match.end()
        if not text.strip():
            add_to_previous_or_wait(statements, leading_numbers, numbers)
            continue
        statements.append(Statement(text, leading_numbers + numbers))
        leading_numbers = []

    statements.append(Statement(line[position:], leading_numbers))
    return statements



# Eine Nummer ohne Text davor gehört zum Satz davor, am Zeilenanfang zum Satz danach.
def add_to_previous_or_wait(statements: list[Statement], leading_numbers: list[int], numbers: list[int]) -> None:
    if statements:
        statements[-1].numbers += numbers
    else:
        leading_numbers += numbers



def numbers_in(sources: str) -> list[int]:
    numbers = []
    for first, last in ITEM.findall(sources):
        numbers += range(int(first), int(last or first) + 1)
    return numbers



# --- Text der Quellen ---

# Das Material ist ein Text mit Überschriften "[Q2] Titel"; zu jeder Quelle gehört alles bis zur nächsten Überschrift.
# Das ist genau das, was das Modell beim Antworten gesehen hat.
def split_source_texts(material: str) -> dict[int, str]:
    texts = {}
    current = None

    for line in material.split("\n"):
        heading = SOURCE_HEADING.match(line)
        if heading:
            current = int(heading.group(1))
            texts.setdefault(current, [])
        elif line.startswith(TOOL_HEADING):
            current = None
        if current is not None:
            texts[current].append(line)

    return {number: "\n".join(lines) for number, lines in texts.items()}



# Bei Modulen steht im Material die Datenbank-Fassung ("ects: 6.0"), im PDF und damit in den Chunks die Fassung des
# PDFs ("ECTS Credits: 6"). Zitiert wird aus den Chunks, denn ein Zitat daraus lässt sich genau im PDF markieren.
# Fällt das Laden aus, gilt das Material.
def load_module_chunk_texts(statements: list[Statement], sources_by_number: dict[int, str],
                            material_texts: dict[int, str]) -> dict[int, str]:
    used_numbers = {number for statement in statements for number in statement.numbers}
    module_ids = {number: int(sources_by_number[number][1:]) for number in used_numbers
                  if sources_by_number[number].startswith(MODULE_PREFIX)}
    if not module_ids:
        return {}

    try:
        bodies = load_chunk_bodies(list(module_ids.values()))
    except Exception as error:
        print(f"Modul-Chunks nicht geladen: {type(error).__name__}: {error}", flush=True)
        return {}

    texts = {}
    for number, module_id in module_ids.items():
        if module_id in bodies:
            heading = material_texts.get(number, f"[Q{number}]").split("\n")[0]
            texts[number] = f"{heading}\n{bodies[module_id]}"
    return texts



# Der Text eines Chunks beginnt mit dem Pfad des Abschnitts, der gehört nicht zum Modul.
def load_chunk_bodies(module_ids: list[int]) -> dict[int, str]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT modul_id, text FROM chunk WHERE modul_id = ANY(%s) ORDER BY modul_id, position", (module_ids,)
        ).fetchall()

    bodies = {}
    for row in rows:
        body = row["text"].split("\n", 1)[-1]
        bodies[row["modul_id"]] = f"{bodies[row['modul_id']]}\n{body}" if row["modul_id"] in bodies else body
    return bodies



# Ein Zitat darf aus dem Material oder aus den Chunks stammen.
def merge_texts(material_texts: dict[int, str], chunk_texts: dict[int, str]) -> dict[int, str]:
    merged = dict(material_texts)
    for number, text in chunk_texts.items():
        merged[number] = f"{merged.get(number, '')}\n{text}"
    return merged



# --- Zitate suchen ---

# Ohne Aussagen mit Quellen gibt es nichts zu zitieren. Fällt der Aufruf aus, behalten die Aussagen ihre Quellen
# ohne Zitat ("abgeleitet"), damit sich die Quelle trotzdem öffnen lässt. prompt_texts gehen an das LLM, ein Zitat
# gilt, wenn es in check_texts steht.
def find_citations(statements: list[Statement], prompt_texts: dict[int, str], check_texts: dict[int, str],
                   context: str) -> tuple[dict[int, Citation], TokenUsage]:
    if not statements:
        return {}, TokenUsage()

    try:
        entries, usage = request_entries(statements, prompt_texts, context)
    except Exception as error:
        print(f"Zitieren fehlgeschlagen: {type(error).__name__}: {error}", flush=True)
        return {statement.number: fallback_citation(statement) for statement in statements}, TokenUsage()

    normalized_sources = {number: normalize(text) for number, text in check_texts.items()}
    citations = {}
    for statement in statements:
        citations[statement.number] = check_entry(entries.get(statement.number), statement, normalized_sources)
    return citations, usage



# Ist die Antwort kein gültiges JSON (meist ein gerades Anführungszeichen im Zitat), gibt es einen zweiten Versuch mit dem
# Fehler als Hinweis.
def request_entries(statements: list[Statement], source_texts: dict[int, str],
                    context: str) -> tuple[dict[int, dict], TokenUsage]:
    reply, usage = request_citations(statements, source_texts, context)
    try:
        return parse_reply(reply), usage
    except (ValueError, KeyError, TypeError) as error:
        problem = f"{type(error).__name__}: {error}"

    print(f"Zitier-Antwort ungültig ({problem}), zweiter Versuch", flush=True)
    retry_reply, retry_usage = request_citations(statements, source_texts, context, previous_error=problem)
    usage.add(retry_usage)
    return parse_reply(retry_reply), usage



def request_citations(statements: list[Statement], source_texts: dict[int, str], context: str,
                      previous_error: str | None = None) -> tuple[str, TokenUsage]:
    used_numbers = sorted({number for statement in statements for number in statement.numbers})
    sources = "\n\n".join(source_texts[number] for number in used_numbers if number in source_texts)
    claims = "\n".join(describe_statement(statement) for statement in statements)
    content = f"Quellen:\n\n{sources}\n\n---\n\n{context}\n\n---\n\nAussagen:\n\n{claims}"
    if previous_error:
        content += (f"\n\n---\n\nDeine letzte Antwort war kein gültiges JSON ({previous_error}). Ersetze gerade "
                    "Anführungszeichen (\") im Text eines Zitats durch ein einfaches (') und gib das JSON noch einmal aus.")

    messages = [
        {"role": "system", "content": PROMPT_FILE.read_text()},
        {"role": "user", "content": content},
    ]
    message, usage = call_llm(messages, thinking=CITATION_THINKING, step="Zitate", json_output=True)
    return message["content"], usage



# Frage und ganze Antwort, nur damit das LLM jede Aussage im Zusammenhang versteht (z. B. unter welcher Überschrift ein
# Listenpunkt steht); zitiert wird weiter nur aus den Quellen.
def describe_context(question: str, answer: str) -> str:
    plain_answer = TAG_IN_ANSWER.sub("", answer).strip()
    return f"Zur Einordnung, hier wird nicht zitiert.\n\nFrage: {question}\n\nAntwort:\n{plain_answer}"



def describe_statement(statement: Statement) -> str:
    sources = ", ".join(f"Q{number}" for number in statement.numbers)
    return f"{statement.number}. [Quellen: {sources}] {plain_text(statement.text)}"



def plain_text(text: str) -> str:
    return re.sub(r"^\s*(?:[-*+] |\d+\. |#+ )?", "", text).replace("**", "").strip()



# Antwort des Zitier-LLM als {Nummer der Aussage: Eintrag}
def parse_reply(reply: str) -> dict[int, dict]:
    data = json.loads(reply)
    entries = {}
    for entry in data["aussagen"]:
        entries[int(entry["nr"])] = entry
    return entries



def fallback_citation(statement: Statement) -> Citation:
    return Citation(DEFAULT_KIND, [], statement.numbers)



# --- Zitate prüfen ---

# Aus dem Eintrag des LLM wird die Marke: Nur Zitate, die wörtlich in einer Quelle stehen, bleiben. Bleibt keines
# übrig, obwohl die Antwort Quellen nannte, ist das "nicht gefunden" (rot), auch wenn das LLM "belegt" meinte. Die
# Quellen der Antwort bleiben in der Marke, damit man sie selbst nachsehen kann.
def check_entry(entry: dict | None, statement: Statement, normalized_sources: dict[int, str]) -> Citation:
    if entry is None:
        return not_found(statement)

    quotes = verified_quotes(entry.get("zitate"), statement.numbers, normalized_sources)
    kind = entry.get("art") if entry.get("art") in KINDS else DEFAULT_KIND
    if kind == NOTE_KIND or not quotes:
        return not_found(statement)
    return Citation(kind, quotes, [])



def not_found(statement: Statement) -> Citation:
    return Citation(NOT_FOUND_KIND, [], statement.numbers)



def verified_quotes(raw_quotes: object, statement_numbers: list[int],
                    normalized_sources: dict[int, str]) -> list[Quote]:
    quotes = []
    for raw_quote in raw_quotes if isinstance(raw_quotes, list) else []:
        quote = quote_from_entry(raw_quote, statement_numbers, normalized_sources)
        if quote and quote not in quotes:
            quotes.append(quote)
    return quotes



# Das LLM nennt die Quelle des Zitats; stimmt sie nicht, wird das Zitat in den anderen Quellen der Aussage und dann in
# allen gesucht und dort zugeordnet.
def quote_from_entry(raw_quote: object, statement_numbers: list[int],
                     normalized_sources: dict[int, str]) -> Quote | None:
    if not isinstance(raw_quote, dict):
        return None

    text = clean_quote(str(raw_quote.get("text", "")))
    needle = normalize(text)
    if len(needle) < MIN_QUOTE_CHARACTERS:
        return None

    claimed = numbers_in(str(raw_quote.get("quelle", "")))
    for number in claimed + statement_numbers + list(normalized_sources):
        if needle in normalized_sources.get(number, ""):
            return Quote(number, text)
    return None



def normalize(text: str) -> str:
    return IGNORED_IN_QUOTE.sub("", text).lower()



# Eckige Klammern und »« im Zitat würden die gespeicherte Marke [[...]] beenden, Zeilenumbrüche würden sie über mehrere
# Zeilen ziehen. Die Suche im PDF ignoriert Leerraum, ein Zitat in einer Zeile findet dieselbe Stelle.
def clean_quote(text: str) -> str:
    text = " ".join(text.split()).replace("[", "(").replace("]", ")")
    return text.replace("»", "").replace("«", "")



# --- Modultitel ---

# Nennt eine Aussage ein Modul beim Namen ("Entscheidungslehre: 6 ECTS"), gehört die Titelzeile des Moduls mit zu den
# Zitaten, sonst steht dort nur die Zahl. Der Titel kommt aus dem Chunk-Text, ist also im PDF wörtlich zu finden.
def add_module_titles(statements: list[Statement], citations: dict[int, Citation], chunk_texts: dict[int, str]) -> None:
    for statement in statements:
        citation = citations[statement.number]
        if not citation.quotes:
            continue

        for number in statement.numbers:
            title_quote = module_title_quote(number, statement.text, chunk_texts)
            if title_quote and title_quote not in citation.quotes:
                citation.quotes.insert(0, title_quote)



def module_title_quote(number: int, statement_text: str, chunk_texts: dict[int, str]) -> Quote | None:
    match = MODULE_TITLE_LINE.search(chunk_texts.get(number, ""))
    if not match:
        return None

    title = TRAILING_BRACKET.sub("", match.group(1)).strip()
    if len(normalize(title)) < MIN_QUOTE_CHARACTERS or normalize(title) not in normalize(statement_text):
        return None
    return Quote(number, clean_quote(f"Modultitel: {match.group(1).strip()}"))



# --- Überlappende Zitate ---

# Steht ein Zitat ganz in einem längeren Zitat derselben Quelle ("Modultitel: X" in "Modultitel: X Kennung: 1"), ist es
# überflüssig, denn das längere markiert dieselbe Stelle im PDF schon. Gleiche Zitate bleiben nur einmal.
def drop_nested_quotes(citations: dict[int, Citation]) -> None:
    for citation in citations.values():
        citation.quotes = without_nested_quotes(citation.quotes)



def without_nested_quotes(quotes: list[Quote]) -> list[Quote]:
    unique = {}
    for quote in quotes:
        unique.setdefault((quote.source_number, normalize(quote.text)), quote)

    kept = []
    for (source_number, needle), quote in unique.items():
        if not is_nested_in_other(source_number, needle, unique):
            kept.append(quote)
    return kept



def is_nested_in_other(source_number: int, needle: str, unique: dict[tuple[int, str], Quote]) -> bool:
    for other_source_number, other_needle in unique:
        if other_source_number == source_number and other_needle != needle and needle in other_needle:
            return True
    return False



# --- Marken ---

def render_line(line: list[Statement], citations: dict[int, Citation], sources_by_number: dict[int, str]) -> str:
    is_heading = is_heading_line(line)
    parts = []
    for statement in line:
        parts.append(statement.text)
        marker = marker_for(statement, citations, sources_by_number, is_heading)
        if marker:
            parts.append(marker)
    return "".join(parts)



def marker_for(statement: Statement, citations: dict[int, Citation], sources_by_number: dict[int, str],
               is_heading: bool) -> str:
    if statement.numbers:
        return format_marker(citations[statement.number], sources_by_number)

    if has_text(statement.text) and not is_heading:
        return f"[[{NOTE_KIND}]]"
    return ""



# Text ohne Quelle ist unbelegt, auch Einleitungen und kurze Sätze. Ohne Marke bleiben Überschriften und Zeilen ohne
# Buchstaben und Zahlen, etwa Leerzeilen oder Trennlinien.
def has_text(text: str) -> bool:
    return bool(TEXT_CHARACTER.search(text))



def is_heading_line(line: list[Statement]) -> bool:
    text = "".join(statement.text for statement in line).strip()
    return text.startswith("#") or bool(BOLD_ONLY_LINE.fullmatch(text))



def format_marker(citation: Citation, sources_by_number: dict[int, str]) -> str:
    items = [f"{sources_by_number[quote.source_number]} »{quote.text}«" for quote in citation.quotes]
    items += [sources_by_number[number] for number in citation.source_numbers]
    return f"[[{citation.kind}: {', '.join(items)}]]"
