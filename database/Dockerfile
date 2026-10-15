FROM pgvector/pgvector:pg16

# Beim ersten Start mit leerem Datenverzeichnis: Schema anlegen, dann llm_leser zum Login-Nutzer machen
COPY schema.sql /docker-entrypoint-initdb.d/1_schema.sql
COPY leserolle.sh /docker-entrypoint-initdb.d/2_leserolle.sh

HEALTHCHECK --interval=5s --timeout=3s --retries=20 CMD pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" || exit 1
