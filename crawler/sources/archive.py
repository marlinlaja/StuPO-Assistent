import logging
import re
from datetime import date, datetime
from functools import cache
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from config import ARCHIVE_SEARCH_URL, ARCHIVE_URL, ONLY_GERMAN
from services.web import fetch
from sources.models import RemoteDocument



# --- Konstanten ---

ARCHIVE_CHARSET = "iso-8859-1"
ENGLISH_ICON_MARKER = "Englisch"
DATE_FORMAT = "%d.%m.%Y"
RESULT_COUNT = re.compile(r"Treffer\s+\d+\s*-\s*(\d+)\s+von\s+(\d+)")
LOGGER = logging.getLogger("crawler")
UNSAFE_FILENAME_CHARS = re.compile(r"[^\w\-.,() ]")
COLUMN_TITLE = 0
COLUMN_PUBLISHED = 3
COLUMN_NUMBER = 4
COLUMN_KIND = 5



# --- Archiv der amtlichen Bekanntmachungen ---

# search_query steht unveraendert in der Such-URL und muss schon URL-kodiert sein, z. B. "%DCbergreifende+bachelor+master".
@cache
def find_archive_documents(search_query: str, document_type: str) -> tuple[RemoteDocument, ...]:
    response = fetch(ARCHIVE_SEARCH_URL.format(query=search_query))
    response.encoding = ARCHIVE_CHARSET
    soup = BeautifulSoup(response.text, "html.parser")
    warn_if_paginated(soup, search_query)

    documents = []
    for row in soup.select("table.results tbody tr"):
        documents += read_row(row, document_type)
    return tuple(documents)



def warn_if_paginated(soup: BeautifulSoup, search_query: str) -> None:
    match = RESULT_COUNT.search(soup.get_text(" "))
    if match and match.group(1) != match.group(2):
        LOGGER.warning("Archiv %s: nur %s von %s Treffern auf der ersten Seite", search_query, match.group(1), match.group(2))



def read_row(row: Tag, document_type: str) -> list[RemoteDocument]:
    cells = [read_cell_text(cell) for cell in row.find_all("td")]
    if len(cells) <= COLUMN_KIND or not is_full_version(cells[COLUMN_KIND]):
        return []

    documents = []
    for link in row.select("a[href*='show_document']"):
        is_english = is_english_link(link)
        if is_english and ONLY_GERMAN:
            continue
        title = build_title(cells, is_english)
        url = urljoin(ARCHIVE_URL, link["href"])
        documents.append(RemoteDocument(title, url, document_type, published_on=parse_date(cells[COLUMN_PUBLISHED])))
    return documents



def parse_date(text: str) -> date | None:
    try:
        return datetime.strptime(text, DATE_FORMAT).date()
    except ValueError:
        return None



def is_english_link(link: Tag) -> bool:
    icon = link.find("img")
    return icon is not None and ENGLISH_ICON_MARKER in icon.get("alt", "")



# Gesamtfassungen und die urspruengliche Ordnung enthalten den ganzen Text, reine Aenderungsordnungen nicht.
def is_full_version(kind: str) -> bool:
    return kind == "Ordnung" or "Gesamtfassung" in kind



# Die Nummer (z. B. 2026/085) macht den Titel eindeutig, denn alle Fassungen einer Ordnung heissen gleich.
def build_title(cells: list[str], is_english: bool) -> str:
    title = f"{cells[COLUMN_TITLE]} - {cells[COLUMN_KIND]}, {cells[COLUMN_NUMBER]}"
    if is_english:
        title += " (englisch)"
    return sanitize_title(title)



def sanitize_title(title: str) -> str:
    return UNSAFE_FILENAME_CHARS.sub("-", title)



def read_cell_text(cell: Tag) -> str:
    for caption in cell.find_all("h3"):
        caption.decompose()
    return re.sub(r"\s+", " ", cell.get_text(" ")).strip()
