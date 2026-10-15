# Markiert eine Quelle im PDF, zeichengenau: Bei einem Chunk wird das zitierte Stueck aus dem Material im Text des
# Chunks gesucht, bei einem Modul wird nur der Modulname markiert. Wird nichts gefunden, bleibt die Quelle unmarkiert.
# Mehrere Zitate einer Quelle kommen durch Zeilenumbrueche getrennt.

import math
import re
from dataclasses import dataclass
from functools import lru_cache

import pymupdf

from services.database import connect



# --- Konstanten ---

SOURCE_ID = re.compile(r"[cm]\d+")
CHUNK_PREFIX = "c"
MODULE_PREFIX = "m"
TEXT_BLOCK = 0
IGNORED_CHARACTERS = re.compile(r"[\s\-]")
# Beim Suchen eines Zitats zaehlen Leerraum, Trennstriche und Anfuehrungszeichen nicht, die bricht das PDF anders um,
# ebenso Tabellenstriche, Klammern, Sternchen und Aufzaehlungspunkte, die das LLM beim Zitieren von Tabellen oder
# Markdown anders setzt, und Doppelpunkte und Semikolons, mit denen der Chunk-Text Tabellenzellen verbindet
# ("ECTS Credits: 15")
IGNORED_IN_QUOTE = re.compile(r"[\s\-–„“”\"»«‚‘’'|()*:;•]")

# Hier wird ein Zitat geteilt, das nicht am Stueck im PDF steht: zwischen Tabellenzellen und an Auslassungen
QUOTE_PART_SEPARATOR = re.compile(r"[:;…]|\.\.\.")

# Ein kurzes oder rein numerisches Stück eines Zitats ("6" hinter "ECTS Credits") kommt im Text oft vor, es gilt nur direkt
# hinter seinem Vorgänger (so viele Zeichen höchstens), sonst würde irgendeine andere "6" markiert
MIN_DISTINCT_CHARACTERS = 6
NEAR_CHARACTERS = 80
NUMBER_ONLY = re.compile(r"[\d.,]+")

# Eine PDF-Zeile am Anfang oder Ende eines Chunks steht oft nur zum Teil im Chunk; ab so vielen gemeinsamen Zeichen gilt sie
MIN_BOUNDARY_OVERLAP = 12
# Nennt das LLM beim Zitieren den falschen Chunk, wird in so vielen Chunks davor und danach weitergesucht, danach im
# ganzen Dokument. Das ganze Dokument durchsucht nur ein kleines (Prüfungsordnung), bei einem Modulhandbuch wäre das
# zu langsam.
NEIGHBOR_CHUNK_RANGE = 3
MAX_CHUNKS_FOR_DOCUMENT_SEARCH = 300

# Spalte der Tabelle modul -> Beschriftung der Zeile im Modulhandbuch (links im PDF steht sie, rechts der Wert)
FIELD_LABELS = {
    "titel": "Modultitel",
    "kennung": "Kennung",
    "version": "Version",
    "dauer_semester": "Dauer (Semester)",
    "turnus": "Turnus (Semester)",
    "gueltig_von": "Gültig von",
    "gueltig_bis": "Gültig bis",
    "niveau": "Modulniveau",
    "inhalt": "Inhalt",
    "lernziele": "Lernziele/Lernergebnisse",
    "lehr_lernmethoden": "Lehr- und Lernmethode",
    "teilnahmebedingungen": "Teilnahmebedingungen (studiengangspezifisch)",
    "empf_voraussetzungen": "(empfohlene) Voraussetzungen",
    "literatur": "Literatur",
    "sprache": "Sprache",
    "pruefungsbedingungen": "Prüfungsbedingungen",
    "sonstiges": "Sonstiges",
    "modulverantwortung": "Modulverantwortung",
    "ects": "ECTS Credits",
    "sws": "Kontaktzeit (SWS)",
    "pruefungsdauer_min": "Prüfungsdauer (min)",
    "stunden_gesamt": "Gesamtstunden (h)",
    "stunden_praesenz": "Präsenzstunden (h)",
    "stunden_selbststudium": "Selbststudium (h)",
}
# Weitere Beschriftungen, die eine Zeile beenden (die Tabellen der Prüfungs- und Angebotsknoten)
OTHER_LABELS = ["Prüfungsknoten", "Angebotsknoten"]
FIELD_QUOTE = re.compile(r"^\s*([a-z_]+)\s*:\s*(.*)$", re.IGNORECASE | re.DOTALL)
COURSE_CODE = re.compile(r"\((\d{6,})\)")
FOOTER_LINE = re.compile(r"^Seite\s+\d+\s*(?:von|/)\s*\d+$", re.IGNORECASE)
# Die Beschriftungen stehen in der linken Spalte (x bis hierhin), der Wert mindestens so weit rechts davon
LABEL_COLUMN_MAX_X = 120
VALUE_MIN_OFFSET = 40
MIN_LABEL_PREFIX = 6
MIN_VALUE_CHARACTERS = 4
ROW_TOLERANCE = 4
MAX_ROW_LINES = 25

# Der Pfad eines Chunks ("Bereich › Abschnitt › Modul") steht nicht in seinem Text im PDF, aber als Kopfzeilen der Seite
PATH_SEPARATOR = "›"

PASSAGE_CACHE_SIZE = 4096
PAGE_CACHE_SIZE = 512
# Eine PDF ist einige MB gross, deshalb nur wenige im Speicher halten
PDF_CACHE_SIZE = 8

RectTuple = tuple[float, float, float, float]
# Seite und Zeichenposition in seite.rohtext
Position = tuple[int, int]



# --- Datenmodelle ---

# start = Position der Zeile in seite.rohtext, char_rects = ein Rechteck je Zeichen von text
@dataclass(frozen=True)
class PdfLine:
    page: int
    start: int
    text: str
    rect: RectTuple
    char_rects: tuple[RectTuple, ...]



# end ist exklusiv, wie bei rohtext[start:end]
@dataclass(frozen=True)
class TextRange:
    start: Position
    end: Position



@dataclass(frozen=True)
class Area:
    page_index: int
    rect: RectTuple



# Text der Zeilen ohne ignorierte Zeichen; je Zeichen: positions = Seite und Position in rohtext,
# continues_word = ob es ein Wort oder eine Zahl aus dem Zeichen davor im PDF fortsetzt
@dataclass(frozen=True)
class SearchableText:
    text: str
    positions: list[Position]
    continues_word: list[bool]



@dataclass
class Passage:
    document_id: int
    page: int
    areas: list[Area]



# --- Endpoints ---

# passages = je (Quellen-ID, Zitat); liest die Seiten vorab, damit ein Klick sofort geht
def precompute_passages(passages: list[tuple[str, str]]) -> None:
    for source_id, quote in passages:
        find_passage(source_id, quote)



# Seite und Markierungen einer Stelle; das Frontend zeichnet sie selbst ueber das PDF.
# Die Rechtecke stehen in PDF-Punkten, breite und hoehe sind die Masse der Seite dazu.
def passage_areas(source_id: str, quote: str) -> dict | None:
    passage = find_passage(source_id, quote)
    if passage is None:
        return None

    return {"dokument_id": passage.document_id, "seite": passage.page, "bereiche": area_rows(passage)}



def area_rows(passage: Passage) -> list[dict]:
    rows = []
    with pymupdf.open(stream=load_pdf(passage.document_id), filetype="pdf") as pdf:
        for area in passage.areas:
            page_rect = pdf[area.page_index].rect
            x0, y0, x1, y1 = area.rect
            rows.append({
                "seite": area.page_index + 1,
                "x0": x0, "y0": y0, "x1": x1, "y1": y1,
                "breite": page_rect.width, "hoehe": page_rect.height,
            })
    return rows



# --- Stelle finden ---

# Eine Quelle ist ein Chunk (c1162) oder ein Modul (m225) mit allen seinen Chunks.
@lru_cache(maxsize=PASSAGE_CACHE_SIZE)
def find_passage(source_id: str, quote: str) -> Passage | None:
    if not SOURCE_ID.fullmatch(source_id):
        return None

    condition = "c.id = %(number)s" if source_id.startswith(CHUNK_PREFIX) else "c.modul_id = %(number)s"
    chunks = load_chunks(condition, {"number": int(source_id[1:])})
    if not chunks:
        return None

    if source_id.startswith(MODULE_PREFIX):
        return module_passage(chunks, quote)

    lines, ranges = find_quotes(chunks, quote)
    if not ranges:
        fallback_areas = header_path_areas(chunks[0], quote) or course_row_areas(chunks, quote)
        if fallback_areas:
            return Passage(chunks[0]["dokument_id"], chunks[0]["start_seite"], fallback_areas)
    if not ranges and quote.strip() and source_id.startswith(CHUNK_PREFIX):
        lines, ranges = find_quote_elsewhere(chunks[0], quote)
    if not ranges:
        return Passage(chunks[0]["dokument_id"], chunks[0]["start_seite"], [])

    areas = []
    for text_range in ranges:
        areas += areas_of_range(lines, text_range)
    return Passage(chunks[0]["dokument_id"], min(ranges, key=range_start).start[0], areas)



# --- Pfad im Seitenkopf ---

# Ein Zitat wie "Wahlpflichtbereich Angewandte Informatik › Module im Wahlpflichtbereich › Computer Vision" markiert die
# Kopfzeilen der ersten Seite des Chunks, die genau einen dieser Teile enthalten.
def header_path_areas(chunk: dict, quote: str) -> list[Area]:
    if PATH_SEPARATOR not in quote:
        return []

    parts = {comparable(part) for part in re.split(rf"{PATH_SEPARATOR}|\n", quote) if part.strip()}
    lines = page_lines(chunk["dokument_id"], chunk["start_seite"])
    return [Area(line.page - 1, line.rect) for line in lines if comparable(line.text) in parts]



# --- Module ---

# Ein Zitat aus einem Modul steht entweder als Text im PDF (Inhalt, Lernziele, Literatur) oder als Wert aus der
# Datenbank ("ects: 6.0"), dann wird die Zeile des Felds im PDF markiert. Findet sich nichts, wird der Modulname markiert.
def module_passage(chunks: list[dict], quote: str) -> Passage:
    areas = []
    for single_quote in quote.split("\n"):
        areas += module_quote_areas(chunks, single_quote)
    if not areas:
        areas = text_areas(chunks, chunks[0]["modul_titel"])

    page = min(area.page_index for area in areas) + 1 if areas else chunks[0]["start_seite"]
    return Passage(chunks[0]["dokument_id"], page, areas)



def module_quote_areas(chunks: list[dict], quote: str) -> list[Area]:
    areas = header_path_areas(chunks[0], quote) or text_areas(chunks, quote)
    if areas:
        return areas

    areas = course_row_areas(chunks, quote)
    if areas:
        return areas

    areas = label_row_areas(chunks, quote)
    if areas:
        return areas

    match = FIELD_QUOTE.match(quote)
    if not match:
        return []

    field, value = match.group(1).lower(), match.group(2)
    areas = field_row_areas(chunks, field)
    if areas:
        return areas
    return text_areas(chunks, value) if len(comparable(value)) >= MIN_VALUE_CHARACTERS else []



# Beginnt das Zitat mit der Beschriftung eines Felds ("ECTS Credits: 6"), steht aber der Wert nicht direkt dahinter im PDF,
# wird die Zeile des Felds markiert, nicht irgendein gleicher Wert woanders.
def label_row_areas(chunks: list[dict], quote: str) -> list[Area]:
    comparable_quote = comparable(quote)
    for field, label in FIELD_LABELS.items():
        if comparable_quote.startswith(comparable(label)):
            return field_row_areas(chunks, field)
    return []



def text_areas(chunks: list[dict], quote: str) -> list[Area]:
    if not quote.strip():
        return []

    lines, ranges = find_quotes(chunks, quote)
    areas = []
    for text_range in ranges:
        areas += areas_of_range(lines, text_range)
    return areas



# Alle Zeilen der Seiten des Moduls, Seite für Seite
def module_lines(chunks: list[dict]) -> list[PdfLine]:
    first_page = min(chunk["start_seite"] for chunk in chunks)
    last_page = max(chunk["ende_seite"] for chunk in chunks)
    lines = []
    for page_number in range(first_page, last_page + 1):
        lines += page_lines(chunks[0]["dokument_id"], page_number)
    return lines



# Die Beschriftung eines Felds und die Werte rechts daneben, z. B. bei "ects" "ECTS Credits" und die "6"
def field_row_areas(chunks: list[dict], field: str) -> list[Area]:
    label = FIELD_LABELS.get(field)
    if label is None:
        return []

    lines = module_lines(chunks)
    label_index = find_label_index(lines, label)
    if label_index is None:
        return []

    row_lines = [lines[label_index]] + value_lines_of_row(lines, label_index)
    return [Area(line.page - 1, line.rect) for line in row_lines]



def find_label_index(lines: list[PdfLine], label: str) -> int | None:
    for index, line in enumerate(lines):
        if is_label_of(line, label):
            return index
    return None



# Eine Beschriftung kann im PDF über zwei Zeilen gehen ("Teilnahmebedingungen" / "(studiengangspezifisch)"), dann
# reicht die erste Zeile als Anfang.
def is_label_of(line: PdfLine, label: str) -> bool:
    if line.rect[0] > LABEL_COLUMN_MAX_X:
        return False

    text, expected = comparable(line.text), comparable(label)
    return text == expected or (len(text) >= MIN_LABEL_PREFIX and expected.startswith(text))



def is_any_label(line: PdfLine) -> bool:
    labels = list(FIELD_LABELS.values()) + OTHER_LABELS
    return any(is_label_of(line, label) for label in labels)



# Vom Feld bis zur nächsten Beschriftung (oder bis zur Fußzeile) die Zeilen rechts der Beschriftungsspalte
def value_lines_of_row(lines: list[PdfLine], label_index: int) -> list[PdfLine]:
    label = lines[label_index]
    value_lines = []
    for line in lines[label_index + 1:]:
        if line.page != label.page or FOOTER_LINE.match(line.text) or is_any_label(line):
            break
        if line.rect[0] >= label.rect[0] + VALUE_MIN_OFFSET:
            value_lines.append(line)
    return value_lines[:MAX_ROW_LINES]



# Prüfungs- und Angebotsknoten sind Tabellen; ein Zitat mit der Nummer einer Veranstaltung, z. B. (121572402), markiert
# deren ganze Tabellenzeile.
def course_row_areas(chunks: list[dict], quote: str) -> list[Area]:
    codes = COURSE_CODE.findall(quote)
    if not codes:
        return []

    lines = module_lines(chunks)
    areas = []
    for line in lines:
        if any(code in line.text for code in codes):
            areas += row_cells(lines, line)
    return areas



def row_cells(lines: list[PdfLine], reference: PdfLine) -> list[Area]:
    cells = [line for line in lines if line.page == reference.page and abs(line.rect[1] - reference.rect[1]) <= ROW_TOLERANCE]
    return [Area(line.page - 1, line.rect) for line in cells]



def load_chunks(condition: str, parameters: dict) -> list[dict]:
    with connect() as conn:
        return conn.execute(
            f"""
            SELECT d.id AS dokument_id, c.position, c.start_seite, c.ende_seite, c.text, m.titel AS modul_titel
            FROM chunk c JOIN dokument d ON d.id = c.dokument_id
            LEFT JOIN modul m ON m.id = c.modul_id
            WHERE {condition} ORDER BY c.position
            """,
            parameters,
        ).fetchall()



# Zitiert das LLM eine Stelle unter der ID eines falschen Chunks, steht sie meist in einem Nachbarn, sonst irgendwo im
# Dokument.
def find_quote_elsewhere(chunk: dict, quote: str) -> tuple[list[PdfLine], list[TextRange]]:
    lines, ranges = find_quotes(load_neighbor_chunks(chunk), quote)
    if ranges:
        return lines, ranges

    document_chunks = load_document_chunks(chunk["dokument_id"])
    if len(document_chunks) > MAX_CHUNKS_FOR_DOCUMENT_SEARCH:
        return [], []

    return find_quotes(document_chunks, quote)



def load_neighbor_chunks(chunk: dict) -> list[dict]:
    parameters = {
        "document": chunk["dokument_id"],
        "first": chunk["position"] - NEIGHBOR_CHUNK_RANGE,
        "last": chunk["position"] + NEIGHBOR_CHUNK_RANGE,
    }
    return load_chunks("c.dokument_id = %(document)s AND c.position BETWEEN %(first)s AND %(last)s", parameters)



def load_document_chunks(document_id: int) -> list[dict]:
    return load_chunks("c.dokument_id = %(document)s", {"document": document_id})



# Mehrere Zitate einer Quelle kommen durch Zeilenumbrueche getrennt. Chunks auf derselben Seite liefern dieselben
# Zeilen, die zaehlen nur einmal, sonst wird doppelt markiert.
def find_quotes(chunks: list[dict], quote: str) -> tuple[list[PdfLine], list[TextRange]]:
    lines = []
    for chunk in chunks:
        lines += chunk_lines(chunk)
    lines = list(dict.fromkeys(lines))
    searchable = searchable_text(lines)

    ranges = []
    for single_quote in quote.split("\n"):
        ranges += find_quote(searchable, single_quote)
    return lines, ranges



def range_start(text_range: TextRange) -> Position:
    return text_range.start



def find_quote(searchable: SearchableText, quote: str) -> list[TextRange]:
    whole_quote = comparable(quote)
    if not whole_quote:
        return []

    index = find_whole_words(searchable, whole_quote, 0, len(searchable.text))
    if index >= 0:
        return [text_range(searchable, index, len(whole_quote))]

    return find_quote_parts(searchable, quote)



# Im PDF stehen Kopf und Werte einer Tabelle in anderer Reihenfolge als im Chunk-Text, deshalb wird jeder Teil
# einzeln gesucht, moeglichst hinter dem vorigen. Das Zitat gilt nur als gefunden, wenn alle Teile gefunden werden.
def find_quote_parts(searchable: SearchableText, quote: str) -> list[TextRange]:
    ranges = []
    previous_end = 0

    for part in QUOTE_PART_SEPARATOR.split(quote):
        comparable_part = comparable(part)
        if not comparable_part:
            continue

        index = find_part(searchable, comparable_part, previous_end, has_anchor=bool(ranges))
        if index < 0:
            return []

        previous_end = index + len(comparable_part)
        ranges.append(text_range(searchable, index, len(comparable_part)))

    return ranges



# Kurze Stücke und Zahlen haben einen Vorgänger als Anker und müssen direkt dahinter stehen
def find_part(searchable: SearchableText, part: str, previous_end: int, has_anchor: bool) -> int:
    if has_anchor and is_ambiguous(part):
        window_end = min(len(searchable.text), previous_end + NEAR_CHARACTERS)
        return find_whole_words(searchable, part, previous_end, window_end)

    return find_after(searchable, part, previous_end)



def is_ambiguous(part: str) -> bool:
    return len(part) < MIN_DISTINCT_CHARACTERS or bool(NUMBER_ONLY.fullmatch(part))



def find_after(searchable: SearchableText, part: str, start: int) -> int:
    index = find_whole_words(searchable, part, start, len(searchable.text))
    if index >= 0:
        return index

    return find_whole_words(searchable, part, 0, start)



# Ein Zitat oder Teil muss ganze Woerter und Zahlen treffen, damit etwa »4« nicht in »450,0« gefunden wird.
def find_whole_words(searchable: SearchableText, part: str, start: int, end: int) -> int:
    index = searchable.text.find(part, start, end)
    while index >= 0 and not is_whole_words(searchable, index, len(part)):
        index = searchable.text.find(part, index + 1, end)
    return index



def is_whole_words(searchable: SearchableText, index: int, length: int) -> bool:
    if searchable.continues_word[index]:
        return False

    end = index + length
    return end == len(searchable.text) or not searchable.continues_word[end]



def text_range(searchable: SearchableText, index: int, length: int) -> TextRange:
    last_page, last_offset = searchable.positions[index + length - 1]
    return TextRange(searchable.positions[index], (last_page, last_offset + 1))



# Ohne Leerraum, Trennstriche, Anfuehrungszeichen usw., klein geschrieben
def comparable(text: str) -> str:
    return "".join(single_lower(character) for character in IGNORED_IN_QUOTE.sub("", text))



# Kleinschreibung, die die Laenge nicht aendert, damit Zeichen und Positionen zusammenpassen
def single_lower(character: str) -> str:
    lower = character.lower()
    return lower if len(lower) == 1 else character



def searchable_text(lines: list[PdfLine]) -> SearchableText:
    texts = []
    positions = []
    continues_word = []
    for line in lines:
        searchable_line = searchable_text_of_line(line)
        texts.append(searchable_line.text)
        positions += searchable_line.positions
        continues_word += searchable_line.continues_word
    return SearchableText("".join(texts), positions, continues_word)



def searchable_text_of_line(line: PdfLine) -> SearchableText:
    characters = []
    positions = []
    continues_word = []
    for index, character in enumerate(line.text):
        if IGNORED_IN_QUOTE.match(character):
            continue
        characters.append(single_lower(character))
        positions.append((line.page, line.start + index))
        continues_word.append(index > 0 and character.isalnum() and line.text[index - 1].isalnum())
    return SearchableText("".join(characters), positions, continues_word)



# --- Zeilen im PDF ---

# Die Zeichenpositionen beziehen sich auf rohtext, und der besteht aus den Zeilen von get_text("dict"),
# je mit "\n" (wie in processing/pipeline/parse.py); rawdict liefert dieselben Zeilen mit einem Rechteck je Zeichen.
# Zeilen, die nicht im Chunk-Text stehen (Kopf- und Fusszeilen), werden nicht durchsucht.
def chunk_lines(chunk: dict) -> list[PdfLine]:
    lines = []
    for page_number in range(chunk["start_seite"], chunk["ende_seite"] + 1):
        lines += page_lines(chunk["dokument_id"], page_number)

    body = chunk["text"].split("\n", 1)[-1]
    chunk_key = IGNORED_CHARACTERS.sub("", body)
    return [line for line in lines if is_line_in_chunk(IGNORED_CHARACTERS.sub("", line.text), chunk_key)]



# Eine Zeile am Rand des Chunks steht nur zum Teil darin ("(2) Nach dem Ablauf ...", wenn der Chunk erst bei "Nach"
# beginnt). Ohne diese Zeilen fehlt dem Zitat sein Anfang oder Ende, und es wird nicht gefunden.
def is_line_in_chunk(line_key: str, chunk_key: str) -> bool:
    if line_key in chunk_key:
        return True

    return starts_inside_chunk(line_key, chunk_key) or ends_inside_chunk(line_key, chunk_key)



# Das Ende der Zeile ist der Anfang des Chunks
def starts_inside_chunk(line_key: str, chunk_key: str) -> bool:
    for start in range(len(line_key) - MIN_BOUNDARY_OVERLAP + 1):
        if chunk_key.startswith(line_key[start:]):
            return True
    return False



# Der Anfang der Zeile ist das Ende des Chunks
def ends_inside_chunk(line_key: str, chunk_key: str) -> bool:
    for end in range(MIN_BOUNDARY_OVERLAP, len(line_key)):
        if chunk_key.endswith(line_key[:end]):
            return True
    return False



@lru_cache(maxsize=PDF_CACHE_SIZE)
def load_pdf(document_id: int) -> bytes:
    with connect() as conn:
        row = conn.execute("SELECT pdf FROM dokument WHERE id = %s", (document_id,)).fetchone()
    return bytes(row["pdf"])



# Das Lesen einer Seite mit rawdict ist der teuerste Schritt, deshalb gecacht.
@lru_cache(maxsize=PAGE_CACHE_SIZE)
def page_lines(document_id: int, page_number: int) -> tuple[PdfLine, ...]:
    with pymupdf.open(stream=load_pdf(document_id), filetype="pdf") as pdf:
        raw_lines = text_lines(pdf[page_number - 1])

    lines = []
    position = 0
    for line in raw_lines:
        chars = line_chars(line)
        text = "".join(char["c"] for char in chars)
        char_rects = tuple(tuple(char["bbox"]) for char in chars)
        lines.append(PdfLine(page_number, position, text, tuple(line["bbox"]), char_rects))
        position += len(text) + 1
    return tuple(lines)



def text_lines(page: pymupdf.Page) -> list[dict]:
    lines = []
    for block in page.get_text("rawdict")["blocks"]:
        if block["type"] == TEXT_BLOCK:
            lines += block["lines"]
    return lines



def line_chars(line: dict) -> list[dict]:
    chars = []
    for span in line["spans"]:
        chars += span["chars"]
    return chars



# --- Bereiche im PDF ---

def areas_of_range(lines: list[PdfLine], text_range: TextRange) -> list[Area]:
    areas = []
    for line in lines:
        area = area_in_line(line, text_range)
        if area is not None:
            areas.append(area)
    return areas



# Ein Rechteck vom ersten bis zum letzten Zeichen der Zeile, das im Bereich liegt; Leerzeichen zaehlen nicht.
def area_in_line(line: PdfLine, text_range: TextRange) -> Area | None:
    if not text_range.start[0] <= line.page <= text_range.end[0]:
        return None

    range_start_offset = text_range.start[1] if line.page == text_range.start[0] else 0
    range_end_offset = text_range.end[1] if line.page == text_range.end[0] else math.inf
    first = max(range_start_offset - line.start, 0)
    last = min(range_end_offset - line.start, len(line.text))
    rects = [line.char_rects[index] for index in range(first, int(last)) if not line.text[index].isspace()]
    if not rects:
        return None

    left = min(rect[0] for rect in rects)
    right = max(rect[2] for rect in rects)
    return Area(line.page - 1, (left, line.rect[1], right, line.rect[3]))
