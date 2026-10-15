from dataclasses import dataclass

import pymupdf
from py3langid.langid import MODEL_FILE, LanguageIdentifier




# --- Konstanten ---

LANGUAGE_IDENTIFIER = LanguageIdentifier.from_model_file(MODEL_FILE)
LANGUAGE_IDENTIFIER.set_languages(["de", "en"])
LANGUAGES = {"de": "deutsch", "en": "englisch"}
BOLD_FLAG = 16
TEXT_BLOCK = 0



# --- Datenmodell ---

# pages = je Seite ein Eintrag fuer die Tabelle seite
@dataclass
class ParseResult:
    language: str | None
    pages: list[dict]



# --- Parsen ---

# Tabellen als Markdown nur bei Pruefungsordnungen, im Modulhandbuch liest process() sie selbst.
def parse(document: dict, pdf_content: bytes) -> ParseResult:
    with_tables = document["typ"] != "modulhandbuch"
    with pymupdf.open(stream=pdf_content, filetype="pdf") as pdf:
        pages = [read_page(page, number, with_tables) for number, page in enumerate(pdf, start=1)]

    text = " ".join(page["rohtext"] for page in pages)
    return ParseResult(detect_language(text), pages)



# layout = pro Zeile von rohtext {x, fett[, tabelle]}, damit process() Ueberschriften und Feldnamen am Layout erkennt.
def read_page(page: pymupdf.Page, number: int, with_tables: bool) -> dict:
    tables = page.find_tables().tables if with_tables else []
    table_boxes = [pymupdf.Rect(table.bbox) for table in tables]

    texts = []
    layouts = []
    for line in text_lines(page):
        texts.append("".join(span["text"] for span in line["spans"]))
        layouts.append(line_layout(line, table_boxes))

    return {
        "seitenzahl": number,
        "rohtext": "".join(f"{text}\n" for text in texts),
        "layout": layouts,
        "tabellen": [table.to_markdown().strip() for table in tables],
    }



def text_lines(page: pymupdf.Page) -> list[dict]:
    lines = []
    for block in page.get_text("dict")["blocks"]:
        if block["type"] == TEXT_BLOCK:
            lines += block["lines"]
    return lines



def line_layout(line: dict, table_boxes: list[pymupdf.Rect]) -> dict:
    spans_with_text = [span for span in line["spans"] if span["text"].strip()]
    is_bold = bool(spans_with_text) and all(span["flags"] & BOLD_FLAG for span in spans_with_text)
    x0, y0, x1, y1 = line["bbox"]
    layout = {"x": round(x0, 1), "fett": is_bold}

    center = pymupdf.Point((x0 + x1) / 2, (y0 + y1) / 2)
    table_index = next((index for index, box in enumerate(table_boxes) if center in box), None)
    if table_index is not None:
        layout["tabelle"] = table_index
    return layout



def detect_language(text: str) -> str | None:
    if not text.strip():
        return None

    language_code = LANGUAGE_IDENTIFIER.classify(text)[0]
    return LANGUAGES[language_code]
