# Bausteine fuer Gliederung und Chunks, fuer Pruefungsordnungen und Modulhandbuecher gleich.
# Ein Abschnitt ist z. B. ein §, eine Anlage oder ein Modul, seine Bloecke sind ganze Absaetze bzw. Felder.
# Ein Chunk fasst Bloecke eines Abschnitts bis MAX_TOKENS zusammen, nie ueber eine Abschnittsgrenze hinweg.
# Jeder Chunk beginnt mit dem Pfad des Abschnitts ("I. Allgemeines › § 10 Bewertung ...").

import re
from dataclasses import dataclass, field, replace

from services.tokenizer import count_tokens



# --- Konstanten ---

# Obergrenze pro Chunk; nur ein einzelner Absatz darueber wird geteilt (am Satzende)
MAX_TOKENS = 400

# Zeilen eines Inhaltsverzeichnisses enden mit Punkten und Seitenzahl, z. B. "Bachelorarbeit ........ 8"
TABLE_OF_CONTENTS_LINE = re.compile(r"\.{5,}\s*\d+\s*>?$")
MIN_TABLE_OF_CONTENTS_LINES = 3

# Woerter, vor denen ein Bindestrich am Zeilenende stehen bleibt ("Lehr- und Lernmethode")
CONNECTING_WORDS = {"und", "oder", "bzw.", "sowie", "bis", "and", "or", "to"}
HYPHEN_AT_END = re.compile(r"[^\W\d_]-$")
SUBHEADING = re.compile(r"[A-ZÄÖÜ][\w-]*:")
BULLET = "•"
TABLE_ROW_START = "|"

# Satzende mitten in der Zeile: Satzzeichen nach einem Wort (nicht "z. B."), danach Leerraum und ein Grossbuchstabe
SENTENCE_END = re.compile(r"(?<=\w\w)[.;:!?](?=\s+[A-ZÄÖÜ(„])")
SENTENCE_END_AT_LINE_END = re.compile(r"[.;:!?]$")

PATH_SEPARATOR = " › "
EMPTY_SECTION_TEXT = "(ohne Text im PDF, z. B. nur eine Grafik oder ein Scan)"



# --- Datenmodelle ---

# Eine nicht-leere Zeile mit ihrer Position im rohtext der Seite (wie bei rohtext[start:end]) und ihrem Layout
@dataclass(frozen=True)
class Line:
    page: int
    text: str
    start: int
    end: int
    x: float
    is_bold: bool
    table: int | None
    follows_blank_line: bool



# Ein Absatz bzw. Feld, first_line und last_line geben seine Position im rohtext
@dataclass(frozen=True)
class Block:
    text: str
    first_line: Line
    last_line: Line



# heading = Zeilen der Ueberschrift, leer, wenn es im Text keine gibt (z. B. bei Modulbereichen)
@dataclass(frozen=True)
class Section:
    level: int
    title: str
    heading: list[Line] = field(default_factory=list)
    blocks: list[Block] = field(default_factory=list)
    module_index: int | None = None



# --- Zeilen ---

def lines_of_page(page: dict) -> list[Line]:
    lines = []
    position = 0
    follows_blank_line = False

    for raw_text, layout in zip(page["rohtext"].split("\n"), page["layout"]):
        text = raw_text.strip()
        if text:
            start = position + len(raw_text) - len(raw_text.lstrip())
            lines.append(Line(page["seitenzahl"], text, start, start + len(text), layout["x"], layout["fett"],
                              layout.get("tabelle"), follows_blank_line))
        follows_blank_line = not text and bool(lines)
        position += len(raw_text) + 1

    return lines



def is_table_of_contents(lines: list[Line]) -> bool:
    entries = [line for line in lines if TABLE_OF_CONTENTS_LINE.search(line.text)]
    return len(entries) >= MIN_TABLE_OF_CONTENTS_LINES



# Kopfzeilen wiederholen sich auf jeder Seite
def count_common_leading_lines(first: list[Line], second: list[Line]) -> int:
    count = 0
    while count < min(len(first), len(second)) and first[count].text == second[count].text:
        count += 1
    return count



# --- Fliesstext ---

# Aufzaehlungspunkte und Zwischenueberschriften ("Kenntnisse:") beginnen eine neue Zeile,
# Markdown-Tabellen bleiben mehrzeilig.
def join_lines(lines: list[str]) -> str:
    text = ""
    for line in lines:
        text = append_line(text, line)

    text = re.sub(r"[^\S\n]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return text.strip()



def append_line(text: str, line: str) -> str:
    if line.startswith(TABLE_ROW_START):
        return f"{text}\n{line}\n"

    if line.startswith(BULLET):
        return f"{text}\n{line}"

    if not text:
        return line

    if is_hyphenated(text, line):
        return join_hyphenated(text, line)

    if SUBHEADING.match(line):
        return f"{text}\n{line}"

    return f"{text} {line}"



def is_hyphenated(text: str, line: str) -> bool:
    if not HYPHEN_AT_END.search(text):
        return False

    return line.split()[0] not in CONNECTING_WORDS



# Kleiner Anschluss ist Silbentrennung ("Vor-" + "schriften"), grosser ein Kompositum ("Software-Architektur")
def join_hyphenated(text: str, line: str) -> str:
    if line[0].islower():
        return text[:-1] + line

    return text + line



# --- Bloecke ---

# Ueber MAX_TOKENS wird moeglichst spaet nach einem Satzende oder vor einem Aufzaehlungspunkt geteilt.
# heading = Zeilen eines Feldnamens davor, der erste Block beginnt dann dort.
def to_blocks(lines: list[Line], prefix: str = "", heading: list[Line] | None = None) -> list[Block]:
    if count_tokens_of_lines(lines) > MAX_TOKENS:
        lines = split_lines_at_sentence_ends(lines)

    blocks = []
    for group in group_lines(lines):
        text = prefix + join_lines([line.text for line in group])
        blocks.append(Block(text, group[0], group[-1]))

    if blocks and heading:
        blocks[0] = replace(blocks[0], first_line=heading[0])
    return blocks



def count_tokens_of_lines(lines: list[Line]) -> int:
    return sum(count_tokens(line.text) for line in lines)



def split_lines_at_sentence_ends(lines: list[Line]) -> list[Line]:
    pieces = []
    for line in lines:
        pieces += split_at_sentence_ends(line)
    return pieces



def split_at_sentence_ends(line: Line) -> list[Line]:
    sentence_ends = [match.end() for match in SENTENCE_END.finditer(line.text)]
    boundaries = [0] + sentence_ends + [len(line.text)]

    pieces = []
    for piece_start, piece_end in zip(boundaries, boundaries[1:]):
        piece = line.text[piece_start:piece_end]
        text = piece.strip()
        start = line.start + piece_start + len(piece) - len(piece.lstrip())
        pieces.append(replace(line, text=text, start=start, end=start + len(text)))

    return pieces



def group_lines(lines: list[Line]) -> list[list[Line]]:
    groups = []
    current = []
    token_counts = []

    for line in lines:
        line_tokens = count_tokens(line.text)
        if current and sum(token_counts) + line_tokens > MAX_TOKENS:
            cut = find_cut(current, line, token_counts)
            groups.append(current[:cut])
            current = current[cut:]
            token_counts = token_counts[cut:]
        current.append(line)
        token_counts.append(line_tokens)

    if current:
        groups.append(current)
    return groups



# Geschnitten wird erst ab der halben Groesse; gibt es dort kein Satzende, an der letzten Zeilengrenze.
def find_cut(current: list[Line], next_line: Line, token_counts: list[int]) -> int:
    following_lines = current[1:] + [next_line]
    cut = len(current)

    for index, line in enumerate(current):
        is_good_cut = SENTENCE_END_AT_LINE_END.search(line.text) or following_lines[index].text.startswith(BULLET)
        is_large_enough = sum(token_counts[:index + 1]) >= MAX_TOKENS // 2
        if is_good_cut and is_large_enough:
            cut = index + 1

    return cut



# --- Chunks und Inhaltsverzeichnis ---

# Der Pfad steht als erste Zeile im Text, damit jeder Chunk fuer sich verstaendlich und darueber auffindbar ist.
def build_chunk(path: str, blocks: list[Block], module_index: int | None) -> dict:
    text = "\n".join([path] + [block.text for block in blocks])
    return {
        "module_index": module_index,
        "abschnitt": path,
        "text": text,
        "tokenanzahl": count_tokens(text),
        "start_seite": blocks[0].first_line.page,
        "start_offset": blocks[0].first_line.start,
        "ende_seite": blocks[-1].last_line.page,
        "ende_offset": blocks[-1].last_line.end,
    }



def pack_chunks(path: str, blocks: list[Block], module_index: int | None) -> list[dict]:
    chunks = []
    current = []
    tokens = count_tokens(path)

    for block in blocks:
        block_tokens = count_tokens(block.text)
        if current and tokens + block_tokens > MAX_TOKENS:
            chunks.append(build_chunk(path, current, module_index))
            current = []
            tokens = count_tokens(path)
        current.append(block)
        tokens += block_tokens

    if current:
        chunks.append(build_chunk(path, current, module_index))
    return chunks



# Ein Eintrag im Inhaltsverzeichnis umfasst die Chunks des Abschnitts und aller Unterabschnitte (chunk_von bis
# chunk_bis), so laesst sich jeder Abschnitt ganz nachladen.
def build_chunks_and_table_of_contents(sections: list[Section]) -> tuple[list[dict], list[dict]]:
    chunks = []
    table_of_contents = []
    path = []

    for index, section in enumerate(sections):
        path = path[:section.level - 1] + [section.title]
        blocks = blocks_from_heading(section, has_subsections(sections, index))
        table_of_contents.append({"ebene": section.level, "titel": section.title, "chunk_von": len(chunks) + 1})
        chunks += pack_chunks(PATH_SEPARATOR.join(path), blocks, section.module_index)

    for position, chunk in enumerate(chunks, start=1):
        chunk["position"] = position

    for index, entry in enumerate(table_of_contents):
        complete_entry(entry, table_of_contents[index + 1:], chunks)
    return chunks, table_of_contents



def has_subsections(sections: list[Section], index: int) -> bool:
    if index + 1 >= len(sections):
        return False

    return sections[index + 1].level > sections[index].level



# Ein Abschnitt ohne Text und ohne Unterabschnitte (z. B. eine Anlage, die nur aus einer Grafik besteht)
# bekommt einen Hinweis als Block, damit er auffindbar bleibt.
def blocks_from_heading(section: Section, has_subsections: bool) -> list[Block]:
    blocks = list(section.blocks)
    heading = section.heading

    if not blocks and heading and not has_subsections:
        return [Block(EMPTY_SECTION_TEXT, heading[0], heading[-1])]

    if blocks and heading:
        blocks[0] = replace(blocks[0], first_line=heading[0])
    return blocks



# chunk_bis = letzter Chunk vor dem naechsten Eintrag auf derselben oder einer hoeheren Ebene
def complete_entry(entry: dict, following_entries: list[dict], chunks: list[dict]) -> None:
    next_entry = next((other for other in following_entries if other["ebene"] <= entry["ebene"]), None)
    entry["chunk_bis"] = next_entry["chunk_von"] - 1 if next_entry else len(chunks)

    section_chunks = chunks[entry["chunk_von"] - 1:entry["chunk_bis"]]
    entry["seite_von"] = section_chunks[0]["start_seite"] if section_chunks else None
    entry["seite_bis"] = section_chunks[-1]["ende_seite"] if section_chunks else None
    entry["tokens"] = sum(chunk["tokenanzahl"] for chunk in section_chunks)
