import tiktoken



# --- Konstanten ---

# Naeherung fuer alle Modelle
ENCODING = tiktoken.get_encoding("cl100k_base")



# --- Zaehlen ---

def count_tokens(text: str) -> int:
    return len(ENCODING.encode(text))
