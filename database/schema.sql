-- PO- und Modulhandbuch-Assistent – Dokumentenschema
-- Äquivalent zu schema.dbml – Änderungen immer in beiden Dateien nachziehen.
-- Wird beim ersten Start des Containers (leeres Volume) automatisch ausgeführt.

CREATE EXTENSION IF NOT EXISTS vector;

-- ---------------------------------------------------------------------------
-- Enums
-- ---------------------------------------------------------------------------

CREATE TYPE dokument_typ AS ENUM (
  'uebergreifende_po',
  'fachspezifische_po',
  'modulhandbuch'
);

-- Fortschritt eines Dokuments im Processing, in der Reihenfolge der Schritte
CREATE TYPE dokument_status AS ENUM (
  'neu',        -- PDF im Dokumentenordner gefunden
  'parsed',     -- Seiten gelesen
  'processed',  -- Module, Chunks (mit Tokenzahl) und Inhaltsverzeichnis gebildet
  'final',      -- Embedding berechnet, fertig für den Assistenten
  'translation' -- englische Fassung: nur geparst, wird nicht weiterverarbeitet
);

CREATE TYPE sprache AS ENUM (
  'deutsch',
  'englisch'
);

CREATE TYPE modul_turnus AS ENUM (
  'wintersemester',
  'sommersemester',
  'jedes_semester',  -- Wintersemester/Sommersemester
  'unregelmaessig'
);

CREATE TYPE modul_niveau AS ENUM (
  'bachelor',
  'master',
  'bachelor_master'
);

CREATE TYPE nachricht_rolle AS ENUM (
  'nutzer',
  'assistent'
);

-- Übersetzt sprache in die Postgres-Konfiguration für die Volltextsuche
CREATE FUNCTION suchkonfiguration(s sprache) RETURNS regconfig
  LANGUAGE sql IMMUTABLE PARALLEL SAFE
  RETURN CASE s
    WHEN 'deutsch'  THEN 'german'::regconfig
    WHEN 'englisch' THEN 'english'::regconfig
  END;

-- ---------------------------------------------------------------------------
-- Dokumente
-- ---------------------------------------------------------------------------

CREATE TABLE dokument (
  id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  typ                 dokument_typ NOT NULL,

  titel               text NOT NULL,
  sprache             sprache NOT NULL,
  semester            text CHECK (semester ~ '^[0-9]{4}-(sommersemester|wintersemester)$'),
  erschienen_am       date,
  inhaltsverzeichnis  jsonb,

  importiert_am       timestamptz NOT NULL DEFAULT now(),
  dateiname           text NOT NULL,
  sha256              char(64) NOT NULL UNIQUE CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  pdf                 bytea NOT NULL,

  status              dokument_status NOT NULL DEFAULT 'neu',
  fehler              text,

  CONSTRAINT dokument_semester_nur_bei_modulhandbuch CHECK ((typ = 'modulhandbuch') = (semester IS NOT NULL)),
  UNIQUE (id, typ),     -- Ziel des Modul-FK
  UNIQUE (id, sprache)  -- Ziel des Chunk-FK
);

COMMENT ON COLUMN dokument.dateiname IS 'Name der PDF, nur zur Anzeige';
COMMENT ON COLUMN dokument.pdf IS 'Inhalt der PDF-Datei; Backend und Processing lesen sie von hier, es gibt keinen gemeinsamen Dokumentenordner';
COMMENT ON COLUMN dokument.erschienen_am IS 'Prüfungsordnungen: Erscheinungsdatum im Archiv der amtlichen Bekanntmachungen; Modulhandbücher: Erstellungsdatum der PDF (Metadaten), dort gilt für die Version semester';
COMMENT ON COLUMN dokument.semester IS 'Format JJJJ-sommersemester | JJJJ-wintersemester, sortierbar; Wintersemester 2020/21 = 2020-wintersemester; Pflicht bei modulhandbuch, sonst NULL';
COMMENT ON COLUMN dokument.inhaltsverzeichnis IS 'ein Eintrag pro Abschnitt in Dokumentreihenfolge: {ebene, titel, chunk_von, chunk_bis, seite_von, seite_bis, tokens}; ebene 1 = oberste Ebene (PO: Teil/Anlage/§, Modulhandbuch: Einleitung/Modulbereich); chunk_von..chunk_bis = chunk.position des Abschnitts inkl. Unterabschnitten, zum Nachladen des ganzen Abschnitts; tokens = Summe von chunk.tokenanzahl';
COMMENT ON COLUMN dokument.status IS 'zuletzt abgeschlossener Schritt des Processing: neu -> parsed -> processed -> final, englische Fassungen enden nach dem Parsen mit translation; zum erneuten Verarbeiten auf einen früheren Status zurücksetzen';
COMMENT ON COLUMN dokument.fehler IS 'Meldung des fehlgeschlagenen Schritts; solange gesetzt, verarbeitet das Processing das Dokument nicht weiter, zum erneuten Versuch auf NULL setzen';

CREATE TABLE seite (
  dokument_id   bigint NOT NULL REFERENCES dokument (id) ON DELETE CASCADE,
  seitenzahl    integer NOT NULL CHECK (seitenzahl >= 1),
  rohtext       text NOT NULL,
  zeichenanzahl integer GENERATED ALWAYS AS (char_length(rohtext)) STORED,
  layout        jsonb,
  tabellen      jsonb,

  PRIMARY KEY (dokument_id, seitenzahl)
);

COMMENT ON COLUMN seite.seitenzahl IS 'PDF-Index ab 1';
COMMENT ON COLUMN seite.layout IS 'pro Zeile von rohtext (split auf \n) {x, fett[, tabelle]}: linker Rand in PDF-Punkten, ob fett, Index in tabellen';
COMMENT ON COLUMN seite.tabellen IS 'erkannte Tabellen der Seite als Markdown (nur Prüfungsordnungen)';

CREATE TABLE modul (
  id                               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  handbuch_id                      bigint NOT NULL,
  dokument_typ                     dokument_typ NOT NULL DEFAULT 'modulhandbuch' CHECK (dokument_typ = 'modulhandbuch'),
  kennung                          text NOT NULL,
  version                          integer,
  titel                            text NOT NULL,

  modulbereich                     text NOT NULL,
  modulbereich_pfad                text NOT NULL,
  pflichtstatus                    text,
  niveau                           modul_niveau,
  empf_fachsemester_wintersemester integer CHECK (empf_fachsemester_wintersemester >= 1),
  empf_fachsemester_sommersemester integer CHECK (empf_fachsemester_sommersemester >= 1),

  dauer_semester                   integer CHECK (dauer_semester >= 1),
  turnus                           modul_turnus,
  sprache                          sprache[],
  gueltig_von                      text NOT NULL CHECK (gueltig_von ~ '^[0-9]{4}-(sommersemester|wintersemester)$'),
  gueltig_bis                      text CHECK (gueltig_bis ~ '^[0-9]{4}-(sommersemester|wintersemester)$'),

  ects                             numeric(4,1) CHECK (ects >= 0),
  sws                              numeric CHECK (sws >= 0),
  stunden_gesamt                   numeric CHECK (stunden_gesamt >= 0),
  stunden_praesenz                 numeric CHECK (stunden_praesenz >= 0),
  stunden_selbststudium            numeric CHECK (stunden_selbststudium >= 0),
  veranstaltungen                  text,

  modulverantwortung               text,

  inhalt                           text,
  lernziele                        text,
  lehr_lernmethoden                text,
  literatur                        text,

  teilnahmebedingungen             text,
  empf_voraussetzungen             text,

  pruefungsform                    text,
  pruefungsdauer_min               text,
  pruefungsbedingungen             text,
  zulassungsvoraussetzung          text,

  sonstiges                        text,

  seite_von                        integer NOT NULL,
  seite_bis                        integer NOT NULL,

  CHECK (seite_bis >= seite_von),
  CHECK (gueltig_bis >= gueltig_von),
  UNIQUE (handbuch_id, id),  -- Ziel des Chunk-FK, deckt auch Suche nach handbuch_id ab
  -- ein Modul kann in mehreren Modulbereichen stehen; NULLS NOT DISTINCT, damit Module ohne Version nicht doppelt vorkommen
  UNIQUE NULLS NOT DISTINCT (handbuch_id, kennung, version, modulbereich),
  FOREIGN KEY (handbuch_id, dokument_typ) REFERENCES dokument (id, typ) ON DELETE CASCADE,
  FOREIGN KEY (handbuch_id, seite_von) REFERENCES seite (dokument_id, seitenzahl),
  FOREIGN KEY (handbuch_id, seite_bis) REFERENCES seite (dokument_id, seitenzahl)
);

CREATE INDEX ON modul (kennung);

CREATE TABLE chunk (
  id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  dokument_id      bigint NOT NULL,
  modul_id         bigint,
  position         integer NOT NULL CHECK (position >= 0),
  abschnitt        text,

  start_seite      integer NOT NULL,
  start_offset     integer NOT NULL CHECK (start_offset >= 0),
  ende_seite       integer NOT NULL,
  ende_offset      integer NOT NULL CHECK (ende_offset >= 0),

  text             text NOT NULL,
  sprache          sprache NOT NULL,
  tokenanzahl      integer CHECK (tokenanzahl >= 0),
  suchvektor      tsvector GENERATED ALWAYS AS (to_tsvector(suchkonfiguration(sprache), text)) STORED,

  embedding_modell text,
  embedding        vector(768),

  CHECK (ende_seite >= start_seite),
  CHECK (ende_seite > start_seite OR ende_offset > start_offset),
  CHECK ((embedding IS NULL) = (embedding_modell IS NULL)),
  UNIQUE (dokument_id, position),
  -- erzwingt chunk.sprache = dokument.sprache
  FOREIGN KEY (dokument_id, sprache) REFERENCES dokument (id, sprache) ON DELETE CASCADE ON UPDATE CASCADE,
  FOREIGN KEY (dokument_id, start_seite) REFERENCES seite (dokument_id, seitenzahl),
  FOREIGN KEY (dokument_id, ende_seite) REFERENCES seite (dokument_id, seitenzahl),
  FOREIGN KEY (dokument_id, modul_id) REFERENCES modul (handbuch_id, id) ON DELETE SET NULL (modul_id)
);

CREATE INDEX ON chunk (modul_id);
CREATE INDEX ON chunk USING gin (suchvektor);
CREATE INDEX ON chunk USING hnsw (embedding vector_cosine_ops);

COMMENT ON COLUMN chunk.modul_id IS 'NULL, wenn der Chunk zu keinem Modul gehört';
COMMENT ON COLUMN chunk.start_offset IS 'Zeichenposition in seite.rohtext der start_seite';
COMMENT ON COLUMN chunk.ende_offset IS 'Zeichenposition in seite.rohtext der ende_seite';
COMMENT ON COLUMN chunk.sprache IS 'immer gleich dokument.sprache (über FK erzwungen)';
COMMENT ON COLUMN chunk.abschnitt IS 'Pfad des Abschnitts (Titel getrennt mit › ), steht auch als erste Zeile in text';
COMMENT ON COLUMN chunk.tokenanzahl IS 'Tokens von text (tiktoken cl100k_base, Näherung für alle Modelle), ohne Chat-Format';
COMMENT ON COLUMN chunk.embedding_modell IS 'z. B. jinaai/jina-embeddings-v5-text-nano (Embedding API, input_type document)';

-- ---------------------------------------------------------------------------
-- Studiengänge und Prüfungsordnungen
-- ---------------------------------------------------------------------------

CREATE TABLE studiengang (
  id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name      text NOT NULL,
  abschluss text NOT NULL,

  UNIQUE (name, abschluss)
);

COMMENT ON COLUMN studiengang.abschluss IS 'z. B. B.Sc., M.Sc., B.A.';

CREATE TABLE pruefungsordnung (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  studiengang_id bigint NOT NULL REFERENCES studiengang (id) ON DELETE CASCADE,
  jahr           integer NOT NULL,

  filter_upo           text NOT NULL,
  filter_po            text NOT NULL,
  filter_modulhandbuch text NOT NULL,

  UNIQUE (studiengang_id, jahr)
);

COMMENT ON COLUMN pruefungsordnung.jahr IS 'z. B. 2022 für „PO 2022“';
COMMENT ON COLUMN pruefungsordnung.filter_upo IS 'Suchtext (URL-kodiert) für die Übergreifende Prüfungsordnung (ÜPO) im Archiv der amtlichen Bekanntmachungen, z. B. %DCbergreifende+bachelor+master';
COMMENT ON COLUMN pruefungsordnung.filter_po IS 'Suchtext (URL-kodiert) für die fachspezifische Prüfungsordnung (PO) im Archiv der amtlichen Bekanntmachungen, z. B. Informatik+2022+Bachelor';
COMMENT ON COLUMN pruefungsordnung.filter_modulhandbuch IS 'Studiengangsnummer (pStpStpNr) des Modulhandbuchs in RWTHonline, z. B. 1900';

-- n:m – Dokumente, die zu einer Prüfungsordnung gehören
CREATE TABLE zugehoerig (
  pruefungsordnung_id bigint NOT NULL REFERENCES pruefungsordnung (id) ON DELETE CASCADE,
  dokument_id         bigint NOT NULL REFERENCES dokument (id) ON DELETE CASCADE,

  PRIMARY KEY (pruefungsordnung_id, dokument_id)
);

CREATE INDEX ON zugehoerig (dokument_id);

-- ---------------------------------------------------------------------------
-- Nutzer und Chats
-- ---------------------------------------------------------------------------

CREATE TABLE nutzer (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  erstellt_am timestamptz NOT NULL DEFAULT now()
);

-- Eine Sitzung je Nutzer mit dem Tagesverbrauch an Tokens. Der Verbrauch gilt für den Tag token_tag (Zeitzone
-- Europe/Berlin). Mit Mitternacht beginnt der Zähler bei null: Liegt token_tag vor heute, zählt der Verbrauch als 0 und
-- wird beim nächsten Schreiben zurückgesetzt, ein nächtlicher Job ist nicht nötig.
CREATE TABLE sitzung (
  nutzer_id      bigint PRIMARY KEY REFERENCES nutzer (id) ON DELETE CASCADE,
  erstellt_am    timestamptz NOT NULL DEFAULT now(),
  zuletzt_aktiv  timestamptz NOT NULL DEFAULT now(),
  token_tag      date NOT NULL DEFAULT (now() AT TIME ZONE 'Europe/Berlin')::date,
  eingabe_tokens bigint NOT NULL DEFAULT 0 CHECK (eingabe_tokens >= 0),
  ausgabe_tokens bigint NOT NULL DEFAULT 0 CHECK (ausgabe_tokens >= 0)
);

CREATE TABLE chat (
  id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  nutzer_id       bigint NOT NULL REFERENCES nutzer (id) ON DELETE CASCADE,
  zusammenfassung text,
  erstellt_am     timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ON chat (nutzer_id, erstellt_am);  -- Chatliste eines Nutzers

CREATE TABLE nachricht (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  chat_id     bigint NOT NULL REFERENCES chat (id) ON DELETE CASCADE,
  position    integer NOT NULL CHECK (position >= 0),
  rolle       nachricht_rolle NOT NULL,
  inhalt      jsonb NOT NULL,
  erstellt_am timestamptz NOT NULL DEFAULT now(),

  UNIQUE (chat_id, position),
  UNIQUE (id, rolle)  -- Ziel des Zitat-FK
);

-- n:m – an einen Chat angehängte Dokumente
CREATE TABLE angehaengt (
  chat_id     bigint NOT NULL REFERENCES chat (id) ON DELETE CASCADE,
  dokument_id bigint NOT NULL REFERENCES dokument (id) ON DELETE CASCADE,

  PRIMARY KEY (chat_id, dokument_id)
);

CREATE INDEX ON angehaengt (dokument_id);

-- n:m – von einer Antwort des Assistenten zitierte Chunks
CREATE TABLE zitiert (
  nachricht_id    bigint NOT NULL,
  nachricht_rolle nachricht_rolle NOT NULL DEFAULT 'assistent' CHECK (nachricht_rolle = 'assistent'),
  chunk_id        bigint NOT NULL REFERENCES chunk (id) ON DELETE CASCADE,
  rang            integer NOT NULL CHECK (rang >= 1),
  aehnlichkeit    real,

  PRIMARY KEY (nachricht_id, chunk_id),
  UNIQUE (nachricht_id, rang),
  FOREIGN KEY (nachricht_id, nachricht_rolle) REFERENCES nachricht (id, rolle) ON DELETE CASCADE
);

CREATE INDEX ON zitiert (chunk_id);

COMMENT ON COLUMN zitiert.rang IS 'Reihenfolge der Quellen';
COMMENT ON COLUMN zitiert.aehnlichkeit IS 'Score der Vektorsuche';

-- ---------------------------------------------------------------------------
-- LLM-Zugriff: nur Module des aktuellen Handbuchs
--
-- Das Backend verbindet sich für LLM-Queries als llm_leser (Login und Passwort setzt database/leserolle.sh;
-- SET ROLE allein reicht nicht, eine Query könnte mit set_config('role', 'none', true) zurückwechseln)
-- und führt jede Query in einer eigenen Transaktion aus:
--   SELECT set_config('app.handbuch_id', '<id>', true);
--   <SELECT des LLM>          -- nur ein einzelnes Statement zulassen
--   ROLLBACK;
-- Das Backend gibt dem LLM den Bereichsbaum (modulbereich_pfad) und die Werte von pflichtstatus mit.
-- ---------------------------------------------------------------------------

CREATE VIEW modul_leseansicht WITH (security_barrier) AS
SELECT
  id, kennung, version, titel,
  modulbereich, modulbereich_pfad, pflichtstatus, niveau, empf_fachsemester_wintersemester, empf_fachsemester_sommersemester,
  dauer_semester, turnus, sprache, gueltig_von, gueltig_bis,
  ects, sws, stunden_gesamt, stunden_praesenz, stunden_selbststudium,
  veranstaltungen,
  modulverantwortung,
  inhalt, lernziele, lehr_lernmethoden, literatur,
  teilnahmebedingungen, empf_voraussetzungen,
  pruefungsform, pruefungsdauer_min, pruefungsbedingungen, zulassungsvoraussetzung,
  sonstiges,
  seite_von, seite_bis
FROM modul
WHERE handbuch_id = current_setting('app.handbuch_id')::bigint;

COMMENT ON VIEW modul_leseansicht IS 'Module des aktuell ausgewählten Modulhandbuchs. Ein Modul kann in mehreren Modulbereichen stehen (eine Zeile pro Bereich), je Bereich mit eigenen Werten (z. B. ECTS): Zeilen nie über die Kennung zusammenführen, Module zählen mit count(DISTINCT kennung)';
COMMENT ON COLUMN modul_leseansicht.modulbereich IS 'unterster Bereich, Name wie im Handbuch; genau ein Bereich: modulbereich = ''Chemie''';
COMMENT ON COLUMN modul_leseansicht.modulbereich_pfad IS 'Pfad von der obersten Ebene bis zum Modulbereich, getrennt mit " > ", z. B. "Wahlpflichtbereich > Module im Anwendungsbereich > Chemie"; ein Bereich mit allen Unterbereichen: modulbereich_pfad ILIKE ''%Anwendungsbereich%''';
COMMENT ON COLUMN modul_leseansicht.pflichtstatus IS 'wie im Handbuch, z. B. Pflichtfach oder Wahlpflichtfach; mit = filtern, nicht mit ILIKE';
COMMENT ON COLUMN modul_leseansicht.dauer_semester IS 'Dauer in Semestern; NULL = unbekannt oder „mehrere“';
COMMENT ON COLUMN modul_leseansicht.turnus IS 'jedes_semester = Wintersemester und Sommersemester. Sagt, wann das Modul angeboten werden kann, nicht dass es dann sicher stattfindet, vor allem bei Wahl- und Wahlpflichtmodulen';
COMMENT ON COLUMN modul_leseansicht.sprache IS 'Array, z. B. {deutsch,englisch}; Query: ''englisch'' = ANY(sprache)';
COMMENT ON COLUMN modul_leseansicht.gueltig_von IS 'Format JJJJ-sommersemester | JJJJ-wintersemester, als Text sortierbar; Wintersemester 2020/21 = 2020-wintersemester';
COMMENT ON COLUMN modul_leseansicht.gueltig_bis IS 'Format wie gueltig_von; NULL = unbefristet. Gültig im Semester X: gueltig_von <= X AND (gueltig_bis IS NULL OR gueltig_bis >= X)';
COMMENT ON COLUMN modul_leseansicht.veranstaltungen IS 'Prüfungs- und Angebotsknoten (Prüfung, Übung, Vorlesung …) als lesbarer Text, eine Zeile pro Veranstaltung mit Fachsemester, ECTS und SWS; Beschriftung in der Sprache des Handbuchs';
COMMENT ON COLUMN modul_leseansicht.pruefungsdauer_min IS 'Prüfungsdauer in Minuten als Text wie im Handbuch, z. B. "90", "90-120 min", "15-45 (mündlich/oral) | 90-120 (schriftlich/written)"';
COMMENT ON COLUMN modul_leseansicht.seite_von IS 'Seite im Modulhandbuch (PDF-Index ab 1)';

CREATE ROLE llm_leser NOLOGIN;
GRANT USAGE ON SCHEMA public TO llm_leser;
GRANT SELECT ON modul_leseansicht TO llm_leser;
