import psycopg
from psycopg.rows import dict_row

from config import DATABASE_URL, READ_ONLY_DATABASE_URL



# --- Verbindungen ---

def connect() -> psycopg.Connection:
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)



def connect_read_only() -> psycopg.Connection:
    return psycopg.connect(READ_ONLY_DATABASE_URL, row_factory=dict_row)
