# --- Zugriff ---

def ensure_document_available(document_id: int, document_ids: list[int]) -> None:
    if document_id not in document_ids:
        raise ValueError(f"Dokument {document_id} steht nicht zur Verfügung")



# Mit document_id nur dieses Dokument, sonst alle verfuegbaren
def restrict_to_document(document_ids: list[int], document_id: int | None) -> list[int]:
    if document_id is None:
        return document_ids

    ensure_document_available(document_id, document_ids)
    return [document_id]
