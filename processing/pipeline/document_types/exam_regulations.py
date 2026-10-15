# Gliederung einer Pruefungsordnung: [Anlage] > [Teil I., II., ...] > §, davor die Praeambel. Die Bloecke eines
# Abschnitts sind seine Absaetze (1), (2), ... Die ÜPO enthaelt in ihren Anlagen Musterordnungen mit eigenen Teilen.

import re
from dataclasses import dataclass, field, replace

from pipeline.chunking import (MAX_TOKENS, Block, Line, Section, is_table_of_contents, join_lines, lines_of_page, to_blocks)
from services.tokenizer import count_tokens



# --- Konstanten ---

HEADER_LINE = re.compile(r"^NUMMER\s+\d{4}/\d+$|^\d+\s*/\s*\d+$|^HERAUSGEGEBEN IM AUFTRAGE|^Templergraben 55")
HEADER_AREA_LINES = 8
TABLE_OF_CONTENTS_TITLE = "Inhaltsverzeichnis"
TABLE_OF_CONTENTS_TITLE_AREA_LINES = 10

HEADING_PATTERNS = {
    "paragraph": re.compile(r"^§\s*\d+[a-z]?$"),
    "part": re.compile(r"^[IVX]+\.(\s*\S.*)?$"),
    "appendix": re.compile(r"^Anlage\s+\d+\s*(:.*)?$"),
}
PARAGRAPH_NUMBER = re.compile(r"^\(\d+[a-z]?\)")
ROMAN_NUMERAL_WITHOUT_SPACE = re.compile(r"^([IVX]+\.)(?=\S)")
PREAMBLE_TITLE = "Präambel"



# --- Datenmodelle ---

@dataclass
class DraftSection:
    level: int
    title: str
    heading: list[Line]
    lines: list[Line] = field(default_factory=list)



# Ebene einer Ueberschrift, abhaengig davon, ob gerade eine Anlage und ein Teil offen sind
@dataclass
class Nesting:
    is_in_appendix: bool = False
    is_in_part: bool = False

    def level_for(self, heading_kind: str) -> int:
        if heading_kind == "appendix":
            self.is_in_appendix = True
            self.is_in_part = False
            return 1

        if heading_kind == "part":
            self.is_in_part = True
            return 1 + int(self.is_in_appendix)

        return 1 + int(self.is_in_appendix) + int(self.is_in_part)



# --- Zeilen ---

def clean_lines(pages: list[dict]) -> list[Line]:
    lines = []
    for page in pages:
        page_lines = lines_of_page(page)
        if is_table_of_contents_page(page_lines):
            continue
        page_lines = remove_header_lines(page_lines)
        lines += merge_tables(page_lines, page["tabellen"] or [])
    return lines



def is_table_of_contents_page(lines: list[Line]) -> bool:
    if is_table_of_contents(lines):
        return True

    title_area = lines[:TABLE_OF_CONTENTS_TITLE_AREA_LINES]
    return any(line.text == TABLE_OF_CONTENTS_TITLE for line in title_area)



def remove_header_lines(lines: list[Line]) -> list[Line]:
    kept = []
    for index, line in enumerate(lines):
        is_header = index < HEADER_AREA_LINES and HEADER_LINE.search(line.text)
        if not is_header:
            kept.append(line)
    return kept



# Eine Tabelle wird zu einer Zeile mit dem Markdown aus dem Parsing, ausser sie ist zu gross fuer einen Chunk.
def merge_tables(lines: list[Line], tables: list[str]) -> list[Line]:
    merged = []
    for line in lines:
        if line.table is None or count_tokens(tables[line.table]) > MAX_TOKENS:
            merged.append(line)
        elif merged and merged[-1].table == line.table:
            merged[-1] = replace(merged[-1], end=line.end)
        else:
            merged.append(replace(line, text=tables[line.table]))
    return merged



# --- Ueberschriften ---

# Ueberschriften sind fett, ein "§ 10" im Fliesstext ist ein Verweis.
def heading_kind(line: Line) -> str | None:
    if not line.is_bold or line.table is not None:
        return None

    for kind, pattern in HEADING_PATTERNS.items():
        if pattern.match(line.text):
            return kind
    return None



# Die Ueberschrift und die fetten Zeilen direkt darunter (der Titel)
def heading_lines(lines: list[Line], index: int) -> list[Line]:
    heading = [lines[index]]
    for line in lines[index + 1:]:
        if not continues_heading(line):
            break
        heading.append(line)
    return heading



def continues_heading(line: Line) -> bool:
    if not line.is_bold or line.follows_blank_line or line.table is not None:
        return False

    return not heading_kind(line) and not PARAGRAPH_NUMBER.match(line.text)



def heading_title(heading: list[Line]) -> str:
    title = join_lines([line.text for line in heading])
    return ROMAN_NUMERAL_WITHOUT_SPACE.sub(r"\1 ", title)



# --- Gliederung ---

def build_sections(pages: list[dict]) -> list[Section]:
    lines = clean_lines(pages)
    drafts = [DraftSection(1, PREAMBLE_TITLE, [])]
    nesting = Nesting()

    index = 0
    while index < len(lines):
        kind = heading_kind(lines[index])
        if not kind:
            drafts[-1].lines.append(lines[index])
            index += 1
            continue
        level = nesting.level_for(kind)
        heading = heading_lines(lines, index)
        drafts.append(DraftSection(level, heading_title(heading), heading))
        index += len(heading)

    sections = []
    for draft in drafts:
        if draft.heading or draft.lines:
            sections.append(Section(draft.level, draft.title, draft.heading, paragraph_blocks(draft.lines)))
    return sections



def paragraph_blocks(lines: list[Line]) -> list[Block]:
    paragraphs = []
    for line in lines:
        if not paragraphs or PARAGRAPH_NUMBER.match(line.text):
            paragraphs.append([])
        paragraphs[-1].append(line)

    blocks = []
    for paragraph in paragraphs:
        blocks += to_blocks(paragraph)
    return blocks
