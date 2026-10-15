from dataclasses import dataclass

from pipeline.chunking import build_chunks_and_table_of_contents
from pipeline.document_types import exam_regulations, module_handbook



# --- Datenmodell ---

@dataclass
class ProcessResult:
    modules: list[dict]
    chunks: list[dict]
    table_of_contents: list[dict]
    unknown_field_names: dict[str, int]
    skipped_modules: list[str]



# --- Verarbeiten ---

def process(document: dict, pages: list[dict]) -> ProcessResult:
    pages = sorted(pages, key=page_number)

    if document["typ"] != "modulhandbuch":
        sections = exam_regulations.build_sections(pages)
        chunks, table_of_contents = build_chunks_and_table_of_contents(sections)
        return ProcessResult([], chunks, table_of_contents, {}, [])

    structure = module_handbook.build_structure(pages)
    chunks, table_of_contents = build_chunks_and_table_of_contents(structure.sections)
    return ProcessResult(structure.modules, chunks, table_of_contents, structure.unknown_field_names, structure.skipped_modules)



def page_number(page: dict) -> int:
    return page["seitenzahl"]
