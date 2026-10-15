from dataclasses import dataclass
from datetime import date



# --- Datenmodell ---

# document_type wie dokument.typ, semester nur bei modulhandbuch, published_on nur bei Pruefungsordnungen
@dataclass(frozen=True)
class RemoteDocument:
    title: str
    url: str
    document_type: str
    semester: str | None = None
    published_on: date | None = None
