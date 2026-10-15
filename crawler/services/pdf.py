import hashlib
import re
from datetime import date

import pymupdf



# --- Konstanten ---

# PDF-Metadaten schreiben das Datum als D:JJJJMMTT..., z. B. D:20260727061707+02'00'
PDF_DATE = re.compile(r"D:(\d{4})(\d{2})(\d{2})")



# --- PDF-Inhalt ---

def calculate_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()



# Erstellungsdatum aus den Metadaten der PDF; None, wenn die PDF kein Datum enthaelt.
def read_creation_date(content: bytes) -> date | None:
    with pymupdf.open(stream=content, filetype="pdf") as pdf:
        match = PDF_DATE.match(pdf.metadata.get("creationDate") or "")
    if match is None:
        return None
    return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
