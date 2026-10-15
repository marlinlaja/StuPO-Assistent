#!/bin/sh
# Macht llm_leser (schema.sql) zum Login-Nutzer fuer das Tool sql_modules: Als eigener Nutzer gibt es keine hoehere
# Rolle, zu der eine Query zurueckwechseln koennte. Shell statt .sql, weil das Passwort aus .env kommt.
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -v passwort="$LESE_PASSWORT" <<'SQL'
ALTER ROLE llm_leser LOGIN PASSWORD :'passwort';
ALTER ROLE llm_leser SET default_transaction_read_only = on;
ALTER ROLE llm_leser SET statement_timeout = '5s';
SQL
