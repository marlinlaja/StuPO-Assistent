# Gliederung eines Modulhandbuchs: Einleitung, dann Modulbereich > ... > Modul. Die Bloecke eines Moduls sind seine
# Felder ("Feldname: Wert"). Die Feldnamen stehen fett in einer eigenen Spalte links, die Werte rechts daneben.

import re
from collections import Counter
from dataclasses import dataclass, field
from itertools import chain

from pipeline.chunking import (Block, Line, Section, count_common_leading_lines, is_table_of_contents, join_lines, lines_of_page, to_blocks)



# --- Konstanten ---

FIELD_KEYS = {
    "Modultitel": "title",
    "Kennung": "code",
    "Version": "version",
    "Dauer (Semester)": "duration",
    "Turnus (Semester)": "frequency",
    "Gültig von": "valid_from",
    "Gültig bis": "valid_until",
    "Modulniveau": "level",
    "Inhalt": "content",
    "Lernziele/Lernergebnisse": "learning_goals",
    "Lehr- und Lernmethode": "teaching_methods",
    "Teilnahmebedingungen (studiengangspezifisch)": "participation_requirements",
    "(empfohlene) Voraussetzungen": "recommended_prerequisites",
    "Literatur": "literature",
    "Sprache": "language",
    "Prüfungsbedingungen": "exam_conditions",
    "Sonstiges": "miscellaneous",
    "Nachhaltigkeitsbezug der Modulinhalte": "sustainability",
    "Modulverantwortung": "responsible_persons",
    "ECTS Credits": "ects",
    "Kontaktzeit (SWS)": "contact_hours",
    "Prüfungsdauer (min)": "exam_duration",
    "Gesamtstunden (h)": "total_hours",
    "Präsenzstunden (h)": "attendance_hours",
    "Selbststudium (h)": "self_study_hours",
    "Prüfungsknoten": "exam_nodes",
    "Angebotsknoten": "offering_nodes",
}
# Feldnamen werden ohne Gross-/Kleinschreibung, Doppelpunkt und Leerraum um "/" verglichen
def normalize_name(text: str) -> str:
    text = re.sub(r"\s*/\s*", "/", text.strip().rstrip(":"))
    return re.sub(r"\s+", " ", text).casefold()



FIELD_KEYS_BY_NAME = {normalize_name(name): key for name, key in FIELD_KEYS.items()}
# Felder ohne eigene Spalte in der Tabelle modul, sie landen in sonstiges
FIELDS_WITHOUT_COLUMN = {"sustainability"}
TABLE_FIELDS = ["exam_nodes", "offering_nodes"]
REQUIRED_COLUMNS = ["kennung", "titel", "modulbereich", "modulbereich_pfad", "gueltig_von"]
EMPTY_VALUES = {"-", "–", "—"}

MODULE_START = "Modultitel"
INTRODUCTION_TITLE = "Einleitung"
FALLBACK_MODULE_TITLE = "Modul"
AREA_SEPARATOR = " > "
AREA_LABEL = "Modulbereich"
UNKNOWN_AREA = "Ohne Modulbereich"

FOOTER = re.compile(r"^Seite\s+\d+\s*(?:von|/)\s*\d+$", re.IGNORECASE)
DIRECTORY_ENTRY = re.compile(r"^(.*?)\s*\.{2,}\s*(\d+)\s*>?$")
DIRECTORY_MARKER = re.compile(r"^[>\s]+")
DIRECTORY_MODULE = re.compile(r"^\[([A-Za-z]*\d+)\]\s*(.*)$")
REQUIRED_STATUS_IN_TITLE = re.compile(r"^(.*?)\s*\(([^()]*(?:pflicht|wahl)[^()]*)\)$", re.IGNORECASE)
# Zahl am Anfang, dahinter nur Text (z. B. "8 ECTS"), keine weitere Zahl ("8-10")
NUMBER = re.compile(r"\s*(\d*[.,]\d+|\d+)(?![\d.,]*\d)(?:\s*[^\d\s-][^\d]*)?\s*")
SEMESTER = re.compile(r"\b(winter|sommer|ws|ss|wise|sose)\s*(?:semester|sem\.?)?\s*(\d{4})", re.IGNORECASE)
SEMESTER_TYPES = {"winter": "wintersemester", "ws": "wintersemester", "wise": "wintersemester",
                  "sommer": "sommersemester", "ss": "sommersemester", "sose": "sommersemester"}
DIGITS = re.compile(r"\d+")
RECOMMENDED_SEMESTER = re.compile(r"(\d+)\D*semester", re.IGNORECASE)

COLUMN_TOLERANCE = 10
MAX_FIELD_NAME_LINES = 3
LEVEL_TOLERANCE = 5
DURATION_WORDS = [("ein", 1), ("zwei", 2), ("drei", 3)]
LEVELS = ["bachelor", "master"]
LANGUAGES = ["deutsch", "englisch"]

# Spalten der Pruefungsknoten-Tabelle: Studienstart im Winter bzw. im Sommer
WINTER_START_COLUMN = 1
SUMMER_START_COLUMN = 2



# --- Datenmodelle ---

@dataclass
class ModuleField:
    key: str
    name: str
    heading: list[Line]
    lines: list[Line] = field(default_factory=list)



@dataclass(frozen=True)
class DirectoryEntry:
    name: str
    page: int
    x: float | None
    module_code: str | None



@dataclass(frozen=True)
class DirectoryModule:
    module_code: str
    page: int
    area: str | None
    top_area: str | None



# new_indexes = fuer jedes urspruengliche Modul sein Index in valid_modules (None = verworfen)
@dataclass
class ModuleValidation:
    valid_modules: list[dict] = field(default_factory=list)
    new_indexes: list[int | None] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)



@dataclass
class ModuleHandbookStructure:
    modules: list[dict]
    sections: list[Section]
    unknown_field_names: dict[str, int]
    skipped_modules: list[str]



# --- Gliederung ---

# Die Chunks eines uebersprungenen Moduls bleiben, nur ohne Modul.
def build_structure(pages: list[dict]) -> ModuleHandbookStructure:
    introduction, module_lines = split_introduction_and_modules(clean_pages(pages))
    column = field_name_column(module_lines)
    fields_per_module = [read_fields(lines, column) for lines in module_lines]

    modules = build_modules(fields_per_module, module_lines)
    assign_module_areas(modules, pages)
    validation = validate_modules(modules)

    sections = build_sections(introduction, modules, fields_per_module, validation.new_indexes)
    unknown_field_names = count_unknown_field_names(fields_per_module)
    return ModuleHandbookStructure(validation.valid_modules, sections, unknown_field_names, validation.messages)



def build_modules(fields_per_module: list[list[ModuleField]], module_lines: list[list[Line]]) -> list[dict]:
    modules = []
    for fields, lines in zip(fields_per_module, module_lines):
        module = module_columns(fields)
        module["seite_von"] = lines[0].page
        module["seite_bis"] = lines[-1].page
        modules.append(module)
    return modules



def build_sections(introduction: list[Line], modules: list[dict], fields_per_module: list[list[ModuleField]],
                   new_indexes: list[int | None]) -> list[Section]:
    sections = []
    if introduction:
        sections.append(Section(1, INTRODUCTION_TITLE, blocks=to_blocks(introduction)))

    previous_path = []
    for module, fields, module_index in zip(modules, fields_per_module, new_indexes):
        path = area_path_parts(module)
        sections += new_area_sections(path, previous_path)
        previous_path = path
        sections.append(Section(len(path) + 1, section_title(module), blocks=field_blocks(fields),
                                module_index=module_index))
    return sections



def area_path_parts(module: dict) -> list[str]:
    if not module["modulbereich_pfad"]:
        return []

    return module["modulbereich_pfad"].split(AREA_SEPARATOR)



# Bereiche, die ein Modul nicht mit dem vorigen teilt, beginnen einen eigenen Abschnitt.
def new_area_sections(path: list[str], previous_path: list[str]) -> list[Section]:
    shared = 0
    while shared < min(len(path), len(previous_path)) and path[shared] == previous_path[shared]:
        shared += 1

    return [Section(level + 1, path[level]) for level in range(shared, len(path))]



def section_title(module: dict) -> str:
    title = module["titel"] or FALLBACK_MODULE_TITLE
    if not module["kennung"]:
        return title

    return f"{title} ({module['kennung']})"



def count_unknown_field_names(fields_per_module: list[list[ModuleField]]) -> dict[str, int]:
    all_fields = chain.from_iterable(fields_per_module)
    unknown = Counter(module_field.name for module_field in all_fields if not is_known_field_name(module_field.name))
    return dict(unknown)



# --- Seiten ---

# Kopfzeile: auf der ersten Seite eines Moduls alles vor "Modultitel", auf Folgeseiten dieselbe wie davor,
# sonst (Einleitung) der gemeinsame Anfang mit einer Nachbarseite.
def clean_pages(pages: list[dict]) -> list[list[Line]]:
    page_lines = [lines_before_footer(lines_of_page(page)) for page in pages]
    cleaned = []
    module_header_length = 0

    for index, lines in enumerate(page_lines):
        if is_table_of_contents(lines):
            cleaned.append([])
            module_header_length = 0
            continue

        module_start = find_module_start(lines)
        if module_start is not None:
            module_header_length = module_start
            header_length = module_start
        elif module_header_length:
            common_length = count_common_leading_lines(page_lines[index - 1], lines)
            module_header_length = min(common_length, module_header_length)
            header_length = module_header_length
        else:
            header_length = introduction_header_length(page_lines, index)
        cleaned.append(lines[header_length:])

    return cleaned



def is_module_start(text: str) -> bool:
    return normalize_name(text) == normalize_name(MODULE_START)



def lines_before_footer(lines: list[Line]) -> list[Line]:
    for index, line in enumerate(lines):
        if FOOTER.match(line.text):
            return lines[:index]
    return lines



def find_module_start(lines: list[Line]) -> int | None:
    for index, line in enumerate(lines):
        if is_module_start(line.text):
            return index
    return None



def introduction_header_length(page_lines: list[list[Line]], index: int) -> int:
    lengths = []
    for neighbour_index in (index - 1, index + 1):
        if 0 <= neighbour_index < len(page_lines) and not is_table_of_contents(page_lines[neighbour_index]):
            lengths.append(count_common_leading_lines(page_lines[neighbour_index], page_lines[index]))
    return max(lengths, default=0)



def split_introduction_and_modules(page_lines: list[list[Line]]) -> tuple[list[Line], list[list[Line]]]:
    introduction = []
    modules = []

    for lines in page_lines:
        if lines and is_module_start(lines[0].text):
            modules.append([])
        if modules:
            modules[-1].extend(lines)
        else:
            introduction.extend(lines)

    return introduction, [module for module in modules if module]



# --- Felder ---

# Die Feldnamen-Spalte ist die x-Position mit den meisten bekannten Feldnamen, ersatzweise fetter Zeilen
# (in manchen PDFs ist nichts fett).
def field_name_column(module_lines: list[list[Line]]) -> int | None:
    all_lines = list(chain.from_iterable(module_lines))
    known_positions = [line.x for line in all_lines if is_known_field_name(line.text)]
    if known_positions:
        return most_crowded_position(known_positions)

    bold_positions = [line.x for line in all_lines if line.is_bold]
    if not bold_positions:
        return None

    return most_crowded_position(bold_positions)



# Position, in deren Toleranz die meisten Werte liegen (kleine Schwankungen der x-Werte stoeren nicht)
def most_crowded_position(positions: list[float]) -> int:
    def count_nearby(position: float) -> int:
        return sum(1 for other in positions if abs(other - position) <= COLUMN_TOLERANCE)

    return round(max(positions, key=count_nearby))



def read_fields(lines: list[Line], column: int | None) -> list[ModuleField]:
    fields = []
    index = 0

    while index < len(lines):
        name_lines = lines[index:index + field_name_length(lines, index, column)]
        if name_lines and starts_new_field(fields, name_lines):
            name = field_name(name_lines)
            fields.append(ModuleField(field_key(name), name, name_lines))
            index += len(name_lines)
            continue
        if fields:
            fields[-1].lines.append(lines[index])
        index += 1

    return fields



def field_name(lines: list[Line]) -> str:
    return " ".join(line.text for line in lines).replace("/ ", "/")



def is_known_field_name(name: str) -> bool:
    return normalize_name(name) in FIELD_KEYS_BY_NAME



def field_key(name: str) -> str:
    return FIELD_KEYS_BY_NAME.get(normalize_name(name), name)



# Ein Feldname ist ein bekannter Name (auch ueber bis zu drei Zeilen) oder fette Zeilen in der Feldnamen-Spalte.
def field_name_length(lines: list[Line], index: int, column: int | None) -> int:
    if column is None:
        return 0

    known_length = known_field_name_length(lines, index, column)
    if known_length:
        return known_length
    return bold_field_name_length(lines, index, column)



def known_field_name_length(lines: list[Line], index: int, column: int) -> int:
    for length in range(MAX_FIELD_NAME_LINES, 0, -1):
        candidate = lines[index:index + length]
        if len(candidate) < length:
            continue
        is_in_column = all(abs(line.x - column) <= COLUMN_TOLERANCE for line in candidate)
        if is_in_column and is_known_field_name(field_name(candidate)):
            return length
    return 0



# Fette Zeilen untereinander in der Feldnamen-Spalte sind ein Feldname, ausser die erste ist schon einer
# (z. B. "Prüfungsknoten", darunter der fette Tabellenkopf).
def bold_field_name_length(lines: list[Line], index: int, column: int) -> int:
    length = 0
    for line in lines[index:]:
        if not line.is_bold or abs(line.x - column) > COLUMN_TOLERANCE:
            break
        length += 1

    if length <= 1:
        return length

    is_combined_name_known = is_known_field_name(field_name(lines[index:index + length]))
    if not is_combined_name_known and is_known_field_name(lines[index].text):
        return 1
    return length



# In einer Tabelle stehen auch die Spaltenkoepfe fett links, dort beginnt nur die andere Tabelle ein neues Feld.
def starts_new_field(fields: list[ModuleField], name_lines: list[Line]) -> bool:
    is_in_table = bool(fields) and fields[-1].key in TABLE_FIELDS
    if not is_in_table:
        return True

    return field_key(field_name(name_lines)) in TABLE_FIELDS



def field_blocks(fields: list[ModuleField]) -> list[Block]:
    blocks = []
    for module_field in fields:
        if not is_empty_field(module_field):
            blocks += blocks_of_field(module_field)
    return blocks



def is_empty_field(module_field: ModuleField) -> bool:
    if not module_field.lines:
        return True

    return join_lines([line.text for line in module_field.lines]) in EMPTY_VALUES



def blocks_of_field(module_field: ModuleField) -> list[Block]:
    first_line = module_field.heading[0]
    last_line = module_field.lines[-1]

    if module_field.key in TABLE_FIELDS:
        rows = "\n".join(f"- {row}" for row in table_as_rows(module_field.lines))
        return [Block(f"{module_field.name}:\n{rows}", first_line, last_line)]

    if module_field.key == "responsible_persons":
        names = "; ".join(line.text for line in module_field.lines)
        return [Block(f"{module_field.name}: {names}", first_line, last_line)]

    return to_blocks(module_field.lines, prefix=f"{module_field.name}: ", heading=module_field.heading)



# --- Tabellen ---

# Spalten erkennt man an der x-Position der Kopfzeilen, eine neue Tabellenzeile beginnt, wenn nach Werten
# wieder die erste Spalte kommt. Auf Folgeseiten wiederholte Koepfe werden ignoriert.
def read_table(lines: list[Line]) -> tuple[list[str], list[list[str]]]:
    is_header = mark_header_lines(lines)
    header_positions = [line.x for line, header in zip(lines, is_header) if header]
    column_positions = cluster_positions(header_positions)
    if len(column_positions) < 2:
        return [], []

    repeated_header_texts = {line.text for line, header in zip(lines, is_header) if header}
    headers = [[] for _ in column_positions]
    rows = []
    for line, header in zip(lines, is_header):
        column = nearest_column(column_positions, line.x)
        if header and not rows:
            headers[column].append(line.text)
        if header or line.text in repeated_header_texts:
            continue
        if starts_new_row(rows, column):
            rows.append([[] for _ in column_positions])
        rows[-1][column].append(line.text)

    column_titles = [join_lines(header) for header in headers]
    row_texts = [join_cells(row) for row in rows]
    return column_titles, row_texts



# Kopfzeilen sind fett; ohne Fettdruck reicht der Kopf bis zur zweiten Zeile in der ersten Spalte (die erste Zeile
# der naechsten Tabellenzeile).
def mark_header_lines(lines: list[Line]) -> list[bool]:
    if any(line.is_bold for line in lines):
        return [line.is_bold for line in lines]

    if not lines:
        return []

    first_column_x = min(line.x for line in lines)
    is_header = []
    first_column_lines = 0
    for line in lines:
        if abs(line.x - first_column_x) <= COLUMN_TOLERANCE:
            first_column_lines += 1
        is_header.append(first_column_lines < 2)
    return is_header



# Positionen innerhalb der Toleranz gehoeren zu einer Spalte
def cluster_positions(positions: list[float]) -> list[int]:
    clusters = []
    for position in sorted(positions):
        if clusters and position - clusters[-1][-1] <= COLUMN_TOLERANCE:
            clusters[-1].append(position)
        else:
            clusters.append([position])
    return [round(cluster[0]) for cluster in clusters]



def nearest_column(column_positions: list[int], x: float) -> int:
    distances = [abs(position - x) for position in column_positions]
    return distances.index(min(distances))



def starts_new_row(rows: list[list[list[str]]], column: int) -> bool:
    if not rows:
        return True

    has_values_after_first_column = any(rows[-1][1:])
    return column == 0 and has_values_after_first_column



def join_cells(row: list[list[str]]) -> list[str]:
    return [join_lines(cell) for cell in row]



def table_as_rows(lines: list[Line]) -> list[str]:
    headers, rows = read_table(lines)
    texts = []
    for values in rows:
        details = row_details(headers, values)
        if details:
            texts.append(f"{values[0]}: {'; '.join(details)}")
        else:
            texts.append(values[0])
    return texts



def row_details(headers: list[str], values: list[str]) -> list[str]:
    details = []
    for header, value in zip(headers[1:], values[1:]):
        if value and value not in EMPTY_VALUES:
            details.append(f"{header}: {value}")
    return details



# Bei mehreren Zeilen (Pruefung, Uebung) zaehlt die frueheste.
def earliest_recommended_semester(rows: list[list[str]], column: int) -> int | None:
    semesters = []
    for values in rows:
        if column >= len(values):
            continue
        match = RECOMMENDED_SEMESTER.match(values[column])
        if match:
            semesters.append(int(match.group(1)))
    return min(semesters, default=None)



# --- Modulbereiche ---

def assign_module_areas(modules: list[dict], pages: list[dict]) -> None:
    entries = read_directory(pages)
    directory_modules = directory_modules_with_areas(entries)
    area_names = {entry.name for entry in entries if entry.module_code is None}
    pages_by_number = {page["seitenzahl"]: page for page in pages}

    for module in modules:
        area, top_area = areas_from_directory(directory_modules, module)
        first_page_lines = lines_of_page(pages_by_number[module["seite_von"]])
        header_areas = areas_in_header(first_page_lines, area_names)
        module["modulbereich"] = area
        module["modulbereich_pfad"] = area_path(top_area, area, header_areas)
        if module["modulbereich"] is None:
            apply_header_area(module, first_page_lines)



# Steht das Modul nicht im Verzeichnis, stehen seine Bereiche in der Kopfzeile unter "Modulbereich".
def apply_header_area(module: dict, first_page_lines: list[Line]) -> None:
    header_areas = areas_after_area_label(first_page_lines)
    if not header_areas:
        header_areas = [UNKNOWN_AREA]

    module["modulbereich"] = header_areas[-1]
    module["modulbereich_pfad"] = AREA_SEPARATOR.join(header_areas)



def areas_after_area_label(lines: list[Line]) -> list[str]:
    areas = []
    is_after_label = False

    for line in lines:
        if is_module_start(line.text):
            break
        if is_after_label:
            areas.append(line.text)
        if normalize_name(line.text) == normalize_name(AREA_LABEL):
            is_after_label = True

    return areas



def read_directory(pages: list[dict]) -> list[DirectoryEntry]:
    directory_pages = []
    for page in pages:
        lines = lines_of_page(page)
        if is_table_of_contents(lines):
            directory_pages.append(lines)

    entries = []
    for index, lines in enumerate(directory_pages):
        header_length = count_common_leading_lines(lines, comparison_page(directory_pages, index))
        entries += read_directory_page(lines[header_length:])
    return entries



# Die Kopfzeile ist der gemeinsame Anfang mit der vorigen Verzeichnisseite, bei der ersten mit der zweiten.
def comparison_page(directory_pages: list[list[Line]], index: int) -> list[Line]:
    if index:
        return directory_pages[index - 1]

    if len(directory_pages) > 1:
        return directory_pages[1]
    return []



# Lange Namen gehen ueber mehrere Zeilen, erst die letzte endet mit Punkten und Seitenzahl.
def read_directory_page(lines: list[Line]) -> list[DirectoryEntry]:
    entries = []
    pending = []

    for line in lines:
        match = DIRECTORY_ENTRY.match(line.text)
        if not match:
            pending.append(line)
            continue
        entries.append(directory_entry(pending, line, match))
        pending = []

    return entries



def directory_entry(pending: list[Line], line: Line, match: re.Match) -> DirectoryEntry:
    raw_name = join_lines([pending_line.text for pending_line in pending] + [match.group(1)])
    name = DIRECTORY_MARKER.sub("", raw_name)
    module_match = DIRECTORY_MODULE.match(name)
    module_code = module_match.group(1) if module_match else None
    first_line = pending[0] if pending else line

    # Mit Marker steht die Einrueckung nicht in x, die Ebene ist dann unbekannt
    x = None if name != raw_name else first_line.x
    return DirectoryEntry(name.rstrip(":"), int(match.group(2)), x, module_code)



# Im Inhaltsverzeichnis sind nur die oberste und eine tiefere Ebene unterscheidbar eingerueckt.
def directory_modules_with_areas(entries: list[DirectoryEntry]) -> list[DirectoryModule]:
    area_positions = [entry.x for entry in entries if entry.module_code is None and entry.x is not None]
    top_level_x = min(area_positions, default=None)
    modules = []
    area = None
    top_area = None

    for entry in entries:
        if entry.module_code:
            modules.append(DirectoryModule(entry.module_code, entry.page, area, top_area))
            continue
        area = entry.name
        if is_top_level(entry, top_level_x):
            top_area = entry.name

    return modules



def is_top_level(entry: DirectoryEntry, top_level_x: float | None) -> bool:
    if entry.x is None or top_level_x is None:
        return True

    return abs(entry.x - top_level_x) < LEVEL_TOLERANCE



# Steht ein Modul mehrfach im Verzeichnis, zaehlt der Eintrag mit der naechsten Seitenzahl.
def areas_from_directory(directory_modules: list[DirectoryModule], module: dict) -> tuple[str | None, str | None]:
    candidates = [candidate for candidate in directory_modules if candidate.module_code == module["kennung"]]
    if not candidates:
        return None, None

    distances = [abs(candidate.page - module["seite_von"]) for candidate in candidates]
    closest = candidates[distances.index(min(distances))]
    return closest.area, closest.top_area



# Bereiche am Anfang der Kopfzeile einer Modulseite
def areas_in_header(lines: list[Line], area_names: set[str]) -> list[str]:
    areas = []
    for line in lines:
        matching_names = matching_area_names(line.text, area_names)
        if len(matching_names) != 1:
            break
        areas.append(matching_names[0])
    return areas



# Gekuerzte Namen ("Wahlpflichtbereich Daten- und ...") zaehlen, wenn sie eindeutig passen.
def matching_area_names(text: str, area_names: set[str]) -> list[str]:
    if text in area_names:
        return [text]

    if not text.endswith("..."):
        return []

    prefix = text.removesuffix("...").strip()
    return [name for name in area_names if name.startswith(prefix)]



# Die Bereiche zwischen oberstem und eigenem Bereich kommen aus der Kopfzeile der ersten Modulseite.
def area_path(top_area: str | None, area: str | None, header_areas: list[str]) -> str | None:
    if not header_areas or header_areas[-1] != area:
        header_areas = [area]

    path = [top_area] if top_area else []
    for header_area in header_areas:
        if header_area and header_area not in path:
            path.append(header_area)
    return AREA_SEPARATOR.join(path) or None



# --- Spalten der Tabelle modul ---

def module_columns(fields: list[ModuleField]) -> dict:
    lines_by_key = {}
    names_by_key = {}
    for module_field in fields:
        lines_by_key.setdefault(module_field.key, []).extend(module_field.lines)
        names_by_key.setdefault(module_field.key, module_field.name)

    values = {key: "\n".join(line.text for line in lines) for key, lines in lines_by_key.items()}
    title_text = join_lines([line.text for line in lines_by_key.get("title", [])])
    title, required_status = split_required_status(title_text)
    exam_rows = read_table(lines_by_key.get("exam_nodes", []))[1]

    return {
        "kennung": first_line_of(values.get("code")),
        "version": parse_version(values.get("version")),
        "titel": title,
        "modulbereich": None,
        "modulbereich_pfad": None,
        "pflichtstatus": required_status,
        "niveau": parse_level(values.get("level")),
        "empf_fachsemester_wintersemester": earliest_recommended_semester(exam_rows, WINTER_START_COLUMN),
        "empf_fachsemester_sommersemester": earliest_recommended_semester(exam_rows, SUMMER_START_COLUMN),

        "dauer_semester": parse_duration(values.get("duration")),
        "turnus": parse_frequency(values.get("frequency")),
        "sprache": parse_languages(values.get("language")),
        "gueltig_von": parse_semester(values.get("valid_from")),
        "gueltig_bis": parse_semester(values.get("valid_until")),

        "ects": parse_number(values.get("ects")),
        "sws": parse_number(values.get("contact_hours")),
        "stunden_gesamt": parse_number(values.get("total_hours")),
        "stunden_praesenz": parse_number(values.get("attendance_hours")),
        "stunden_selbststudium": parse_number(values.get("self_study_hours")),
        "veranstaltungen": courses_text(lines_by_key, names_by_key),

        "modulverantwortung": responsible_persons_text(values.get("responsible_persons")),

        "inhalt": clean_text(values.get("content")),
        "lernziele": clean_text(values.get("learning_goals")),
        "lehr_lernmethoden": clean_text(values.get("teaching_methods")),
        "literatur": clean_text(values.get("literature")),

        "teilnahmebedingungen": clean_text(values.get("participation_requirements")),
        "empf_voraussetzungen": clean_text(values.get("recommended_prerequisites")),

        # TODO EXTRAKTION: steht nur als Fliesstext in pruefungsbedingungen ("Klausur (100 %). ...")
        "pruefungsform": None,
        "pruefungsdauer_min": clean_text(values.get("exam_duration")),
        "pruefungsbedingungen": clean_text(values.get("exam_conditions")),
        # TODO EXTRAKTION: kein eigenes Feld
        "zulassungsvoraussetzung": None,

        "sonstiges": miscellaneous_text(values, names_by_key),
    }



def courses_text(lines_by_key: dict[str, list[Line]], names_by_key: dict[str, str]) -> str | None:
    courses = []
    for key in TABLE_FIELDS:
        rows = table_as_rows(lines_by_key.get(key, []))
        if rows:
            listed_rows = "\n".join(f"- {row}" for row in rows)
            courses.append(f"{names_by_key[key]}:\n{listed_rows}")
    return "\n".join(courses) or None



# Unbekannte Felder und Felder ohne eigene Spalte kommen mit ihrem Namen hinter das Feld Sonstiges.
def miscellaneous_text(values: dict[str, str], names_by_key: dict[str, str]) -> str | None:
    known_keys = set(FIELD_KEYS.values())
    parts = [clean_text(values.get("miscellaneous"))]
    for key, value in values.items():
        has_no_column = key in FIELDS_WITHOUT_COLUMN or key not in known_keys
        text = clean_text(value)
        if has_no_column and text:
            parts.append(f"{names_by_key[key]}: {text}")
    return "\n\n".join(part for part in parts if part) or None



def responsible_persons_text(value: str | None) -> str | None:
    names = [line.strip() for line in (value or "").split("\n")]
    return "; ".join(name for name in names if name and name not in EMPTY_VALUES) or None



# --- Werte ---

def first_line_of(value: str | None) -> str | None:
    return (value or "").split("\n")[0].strip() or None



def parse_number(value: str | None) -> float | None:
    match = NUMBER.fullmatch(value or "")
    if not match:
        return None

    return float(match.group(1).replace(",", "."))



def parse_version(value: str | None) -> int | None:
    numbers = re.findall(r"\d+", value or "")
    if len(numbers) != 1:
        return None

    return int(numbers[0])



def parse_duration(value: str | None) -> int | None:
    text = (value or "").strip().lower()
    for word, semester_count in DURATION_WORDS:
        if text.startswith(word):
            return semester_count

    digits = DIGITS.search(text)
    if digits:
        return int(digits.group())
    return None



def parse_frequency(value: str | None) -> str | None:
    text = (value or "").lower()
    if "winter" in text and "sommer" in text:
        return "jedes_semester"

    if "unregelm" in text:
        return "unregelmaessig"

    if "winter" in text:
        return "wintersemester"

    if "sommer" in text:
        return "sommersemester"
    return None



def parse_semester(value: str | None) -> str | None:
    match = SEMESTER.search(value or "")
    if not match:
        return None

    semester_type = SEMESTER_TYPES[match.group(1).lower()]
    return f"{match.group(2)}-{semester_type}"



def parse_level(value: str | None) -> str | None:
    text = (value or "").lower()
    return "_".join(level for level in LEVELS if level in text) or None



def parse_languages(value: str | None) -> list[str] | None:
    text = (value or "").lower()
    return [language for language in LANGUAGES if language in text] or None



def clean_text(value: str | None) -> str | None:
    text = join_lines((value or "").split("\n"))
    if not text or text in EMPTY_VALUES:
        return None

    return text



def split_required_status(title: str) -> tuple[str | None, str | None]:
    match = REQUIRED_STATUS_IN_TITLE.match(title)
    if not match:
        return title or None, None

    return match.group(1) or None, match.group(2)



# --- Pruefung ---

# Behaelt nur Module, die sich speichern lassen. Dasselbe Modul in verschiedenen Modulbereichen ist kein Doppel.
def validate_modules(modules: list[dict]) -> ModuleValidation:
    validation = ModuleValidation()
    known_indexes = {}

    for module in modules:
        label = f"{module['titel'] or '?'} ({module['kennung'] or '?'}, S. {module['seite_von']})"
        key = (module["kennung"], module["version"], module["modulbereich"])
        error = module_error(module)
        if error:
            validation.messages.append(f"{label}: {error}")
            validation.new_indexes.append(None)
        elif key in known_indexes:
            validation.messages.append(f"{label}: doppelt im selben Modulbereich, Chunks gehen an den ersten Eintrag")
            validation.new_indexes.append(known_indexes[key])
        else:
            known_indexes[key] = len(validation.valid_modules)
            validation.new_indexes.append(known_indexes[key])
            validation.valid_modules.append(module)

    return validation



def module_error(module: dict) -> str | None:
    missing = [column for column in REQUIRED_COLUMNS if module[column] is None]
    if missing:
        return f"fehlt {', '.join(missing)}"

    if module["gueltig_bis"] and module["gueltig_bis"] < module["gueltig_von"]:
        return f"gueltig_bis {module['gueltig_bis']} liegt vor gueltig_von {module['gueltig_von']}"
    return None
