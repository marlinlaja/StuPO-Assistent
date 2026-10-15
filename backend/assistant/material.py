# Das Material der Recherche als Text: Jede Quelle bekommt eine Nummer (Q1, Q2, ...), auf die sich die Antwort beruft.
# Dieselbe Darstellung sehen die Recherche (als Tool-Ergebnis) und die Antwort, so kann die Antwort die Unterhaltung der
# Recherche weiterführen und aus dem Cache lesen.

import re



# --- Konstanten ---

SOURCE_ID = re.compile(r"^[cm]\d+$")
TITLE_KEYS = ("titel", "abschnitt")
INDENT = "  "



# --- Material als Text ---

# Tool-Ergebnis als lesbarer Text statt JSON. Jede Quelle (Eintrag mit id c1162 oder m225) beginnt mit ihrer Nummer,
# ihrem Titel und ihrer ID, z. B. "[Q2] Entscheidungslehre (m225)"; dieselbe ID bekommt immer dieselbe Nummer. Die IDs
# braucht die Recherche, um Tools wie get_module oder get_neighbors aufzurufen.
def render_as_text(value, numbers_by_source: dict[str, int], indent: str = "") -> str:
    if isinstance(value, list):
        return render_list(value, numbers_by_source, indent)

    if isinstance(value, dict):
        return render_dict(value, numbers_by_source, indent)
    return f"{indent}{value}"



def render_list(values: list, numbers_by_source: dict[str, int], indent: str) -> str:
    items = []
    for value in values:
        item = render_as_text(value, numbers_by_source, indent + INDENT).lstrip()
        items.append(f"{indent}- {item}")
    return "\n".join(items) or f"{indent}(keine)"



def render_dict(values: dict, numbers_by_source: dict[str, int], indent: str) -> str:
    lines = []
    if SOURCE_ID.match(str(values.get("id"))):
        lines.append(source_heading(values, numbers_by_source, indent))
        values = {key: value for key, value in values.items() if key not in ("id",) + TITLE_KEYS}

    for key, value in values.items():
        line = render_field(key, value, numbers_by_source, indent)
        if line is not None:
            lines.append(line)
    return "\n".join(lines)



def source_heading(values: dict, numbers_by_source: dict[str, int], indent: str) -> str:
    number = numbers_by_source.setdefault(values["id"], len(numbers_by_source) + 1)
    title = values.get("titel") or values.get("abschnitt") or ""
    return f"{indent}[Q{number}] {title} ({values['id']})".replace("  (", " (")



# Leere Werte fallen weg. Weitere IDs (etwa das Modul eines Chunks) bleiben als Feld stehen, die Recherche braucht sie.
def render_field(key: str, value, numbers_by_source: dict[str, int], indent: str) -> str | None:
    if value is None:
        return None

    if isinstance(value, (dict, list)) and value:
        return f"{indent}{key}:\n{render_as_text(value, numbers_by_source, indent + INDENT)}"
    return f"{indent}{key}: {value}"
