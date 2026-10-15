import re
from functools import cache
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from config import HANDBOOK_URL, ONLY_GERMAN
from services.web import fetch
from sources.models import RemoteDocument



# --- Konstanten ---

FILE_NAME = re.compile(r"^(?P<name>.+_(?P<language>de|en)_(?P<season>SoSe|WiSe)(?P<year>\d{4}))\.pdf$")
SEMESTER_NAMES = {"SoSe": "sommersemester", "WiSe": "wintersemester"}
DOCUMENT_TYPE = "modulhandbuch"



# --- Modulhandbuecher aus RWTHonline ---

# study_number steht in filter_modulhandbuch (pStpStpNr), die Seite listet alle Semester und Sprachen.
@cache
def find_handbook_documents(study_number: str) -> tuple[RemoteDocument, ...]:
    list_url = HANDBOOK_URL + study_number
    soup = BeautifulSoup(fetch(list_url).text, "html.parser")

    documents = []
    for link in soup.select("a[href*='downloadPublicMHBVersion']"):
        document = read_link(link, list_url)
        if document is not None:
            documents.append(document)
    return tuple(documents)



def read_link(link: Tag, list_url: str) -> RemoteDocument | None:
    match = FILE_NAME.match(link.get_text(strip=True))
    if match is None:
        return None

    if ONLY_GERMAN and match.group("language") != "de":
        return None

    semester = f"{match.group('year')}-{SEMESTER_NAMES[match.group('season')]}"
    return RemoteDocument(match.group("name"), urljoin(list_url, link["href"]), DOCUMENT_TYPE, semester)
