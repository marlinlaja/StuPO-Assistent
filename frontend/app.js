// --- Elemente und Zustand ---

const API_URL = window.APP_CONFIG.API_URL;

const documentList = document.getElementById("document-list");
const messageList = document.getElementById("messages");
const questionForm = document.getElementById("question-form");
const questionField = document.getElementById("question");
const sendButton = questionForm.querySelector('button[type="submit"]');
const sourcePicker = document.getElementById("source-picker");
const viewerHint = document.getElementById("viewer-hint");
const pdfTitle = document.getElementById("pdf-title");
const programSelect = document.getElementById("program-select");
const regulationSelect = document.getElementById("regulation-select");
const contextList = document.getElementById("context-documents");
const tokenCounter = document.getElementById("token-counter");
const connectionButton = document.getElementById("connection-status");

const ROLE_CLASSES = { nutzer: "user", assistent: "assistant" };
const KIND_LABELS = {
  belegt: "Steht in:",
  abgeleitet: "Abgeleitet aus:",
  hinweis: "Hinweis, ohne Quelle",
  nicht_gefunden: "Kein Zitat gefunden, genannt:",
};
const DOCUMENT_GROUPS = [
  { type: "uebergreifende_po", label: "Übergreifende PO", abbreviation: "ÜPO" },
  { type: "fachspezifische_po", label: "Fachspezifische PO", abbreviation: "PO" },
  { type: "modulhandbuch", label: "Modulhandbuch", abbreviation: "MHB" },
];
const PICKER_WIDTH = 310;
// Titel der Prüfungsordnungen: "... - 3. Änderungsordnung (Gesamtfassung), 2024-116" oder "... - Ordnung, 2022-020"
const AMENDMENT_IN_TITLE = /(\d+)\. Änderungsordnung/;
const FIRST_VERSION_IN_TITLE = /- Ordnung,/;
// kleine Linien-Symbole für die Marken im Kontext
const PIN_ICON = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 17v5"/><path d="M9 10.8a2 2 0 0 1-1.1 1.8l-1.8.9A2 2 0 0 0 5 15.2V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.8a2 2 0 0 0-1.1-1.8l-1.8-.9A2 2 0 0 1 15 10.8V7a1 1 0 0 1 1-1 2 2 0 0 0 0-4H8a2 2 0 0 0 0 4 1 1 0 0 1 1 1z"/></svg>';
const CLOSE_ICON = '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" aria-hidden="true"><path d="M4 4l8 8M12 4l-8 8"/></svg>';
const TIMER_INTERVAL_MS = 1000;
// Die Zeit erscheint erst bei längerem Warten, davor zeigen nur die Punkte und der Status, dass etwas läuft
const TIMER_DELAY_SECONDS = 5;
// Bewegung: kurze, auslaufende Animationen; wer in den Systemeinstellungen "Bewegung reduzieren" gewählt hat, sieht keine
const MOTION_EASING = "cubic-bezier(0.22, 1, 0.36, 1)";
const MOTION_MS = 180;
const CHIP_LEAVE_MS = 140;
const PICKER_CLOSE_MS = 100;
const COLUMN_SLIDE_MS = 220;
const PERCENT_COUNT_MS = 400;
const DEFAULT_STATUS = "Antwort wird erstellt";
// Tagesbudget für die Anzeige in Prozent und für das Sperren von Senden; der Wert kommt vom Backend (limit), bis dahin
// gilt dieser Richtwert. Um Mitternacht beginnt der Zähler im Backend bei null.
const DEFAULT_TOKEN_BUDGET = 1_000_000;
// Antwortzeit der API in Millisekunden: bis FAST schnell (3 Balken), bis SLOW mittel (2), darüber langsam (1)
const CONNECTION_FAST_MS = 100;
const CONNECTION_SLOW_MS = 500;
// Erst bei einer längeren Prüfung blinkt das Symbol, sonst verschwindet es bei jedem schnellen Klick kurz
const CONNECTION_CHECKING_DELAY_MS = 300;
const CONNECTION_TIMEOUT_MS = 8000;

const selectedDocumentIds = new Set();
// Festgehaltene Dokumente bleiben beim Wechsel der Prüfungsordnung im Kontext (der Browser merkt sich ihre IDs)
const pinnedDocumentIds = new Set();
// Alle Dokumente des Katalogs nach ID, damit der Kontext sie auch nach einem Wechsel noch benennen kann
const documentsById = new Map();
// Studiengang und Prüfungsordnung, zu der ein Dokument gehört: id -> {program, regulation} (die übergreifende PO gilt für alle)
const documentOrigins = {};
// Steckbriefe aller Quellen aus den Antworten: "c1162" -> {dokument_id, seite, titel}
const sourceProfiles = {};
let chatId = loadNumber("chat_id");
let userId = loadNumber("nutzer_id");
let programs = [];
let catalogDocuments = [];
let selectedProgram = null;
let selectedRegulation = null;
let dayTokens = { eingabe: 0, ausgabe: 0 };
let tokenBudget = DEFAULT_TOKEN_BUDGET;
let isAnswering = false;
let isRestoringChat = false;
let renderedChipIds = new Set();
let shownPercent = 0;
let percentFrame = 0;
let pickerTimer = 0;
// Ein geöffneter Chat behält seine gespeicherten Dokumente, die neuesten der Prüfungsordnung kommen nicht dazu
let hasRestoredChatDocuments = false;
let isCheckingConnection = false;

// Kein Kursiv in Antworten (*Text* bleibt einfacher Text, auch in älteren Antworten) und ein einfacher Zeilenumbruch bleibt
// einer: Das Modell schreibt Listen oft als Zeilen ohne "- ", die sonst zu einem Absatz verschmelzen
marked.use({ breaks: true, renderer: { em({ tokens }) { return this.parser.parseInline(tokens); } } });



// --- Bewegung ---

const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

// Eine kurze Animation für ein Element, das gerade erscheint oder reagiert
function animateElement(element, keyframes, duration = MOTION_MS) {
  if (prefersReducedMotion.matches) return;

  element.animate(keyframes, { duration, easing: MOTION_EASING });
}

function fadeIn(element) {
  animateElement(element, [{ opacity: 0 }, { opacity: 1 }]);
}

// Symbole und Haken zum Anklicken geben beim Drücken kurz nach und federn beim Loslassen zurück. Alles mit Text bleibt
// unverändert, denn Text, der sich beim Klicken vergrößert und verkleinert, wirkt unruhig.
const PRESSABLE = 'button, input[type="checkbox"]';
const PRESS_SCALE = 0.9;

document.addEventListener("pointerdown", (event) => {
  const target = event.target.closest(PRESSABLE);
  if (!target || target.disabled || target.textContent.trim() || prefersReducedMotion.matches) return;

  const press = target.animate([{ scale: 1 }, { scale: PRESS_SCALE }], { duration: 90, easing: MOTION_EASING, fill: "forwards" });
  const release = () => {
    press.reverse();
    press.onfinish = () => press.cancel();
  };
  window.addEventListener("pointerup", release, { once: true });
  window.addEventListener("pointercancel", release, { once: true });
});

// Ein Schütteln für etwas, das gerade nicht geht (Senden bei erreichtem Limit)
function shake(element) {
  const offsets = [0, -4, 4, -3, 3, 0];
  animateElement(element, offsets.map((offset) => ({ transform: `translateX(${offset}px)` })), 300);
}



// --- Speicher im Browser ---

// Chat und Nutzer merkt sich nur der Browser, alles andere steht in der Datenbank.
function loadNumber(key) {
  try {
    return Number(localStorage.getItem(key)) || null;
  } catch (error) {
    return null;
  }
}

function loadText(key) {
  try {
    return localStorage.getItem(key);
  } catch (error) {
    return null;
  }
}

function storeValue(key, value) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch (error) {}
}



// Ältere Stände im Browser speichern {id, label}, neuere nur die ID
function loadPinnedDocuments() {
  try {
    const stored = JSON.parse(loadText("pinned_documents") || "[]");
    stored.forEach((entry) => {
      const id = typeof entry === "number" ? entry : entry.id;
      pinnedDocumentIds.add(id);
      selectedDocumentIds.add(id);
    });
  } catch (error) {}
}

function storePinnedDocuments() {
  storeValue("pinned_documents", JSON.stringify([...pinnedDocumentIds]));
}



// --- API ---

// Das Backend schickt pro Zeile ein Ereignis: Status während der Arbeit, am Ende das Ergebnis oder einen Fehler
async function askQuestion(body, onStatus) {
  const response = await fetch(`${API_URL}/nachrichten`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(response.status);

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let answer = null;

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop();
    for (const line of lines.filter((entry) => entry.trim())) {
      const event = JSON.parse(line);
      if (event.status) onStatus(event.status);
      if (event.fehler) throw new Error(event.fehler);
      if (event.ergebnis) answer = event.ergebnis;
    }
  }

  if (!answer) throw new Error("Keine Antwort erhalten");
  return answer;
}

async function requestApi(path, body) {
  const options = body === undefined ? {} : {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
  const response = await fetch(`${API_URL}${path}`, options);
  if (!response.ok) throw new Error(response.status);
  return response.json();
}



// --- Start ---

async function start() {
  measureScrollbarWidth();
  loadPinnedDocuments();
  await loadChat();
  loadTokenUsage();
  checkConnection();
  await loadCatalog();
}

// Die Linien der Dokumentliste enden so weit vor dem Rand wie die der Eingabe, die Scrollbar zählt zum Abstand
function measureScrollbarWidth() {
  const paneBody = document.querySelector(".documents .pane-body");
  const scrollbarWidth = paneBody.offsetWidth - paneBody.clientWidth;
  document.documentElement.style.setProperty("--scrollbar-width", `${scrollbarWidth}px`);
}

async function loadChat() {
  if (!chatId) return;

  try {
    const chat = await requestApi(`/chats/${chatId}`);
    chat.dokument_ids.forEach((id) => selectedDocumentIds.add(id));
    hasRestoredChatDocuments = chat.dokument_ids.length > 0;
    isRestoringChat = true;
    chat.nachrichten.forEach((message) => showMessage(message.rolle, message.inhalt));
    isRestoringChat = false;
  } catch (error) {
    isRestoringChat = false;
    chatId = null;
    storeValue("chat_id", null);
  }
}

// Die Dokumente der gewählten Prüfungsordnung stehen schon im Katalog.
function loadDocuments() {
  if (!selectedRegulation) {
    showDocuments([]);
    return;
  }

  const documentIds = new Set(selectedRegulation.dokument_ids);
  const documents = catalogDocuments.filter((doc) => documentIds.has(doc.id));
  if (!hasRestoredChatDocuments) selectNewestDocuments(documents);
  showDocuments(documents);
}

// Die neueste Version jeder Dokumentart geht immer an den Assistenten, weitere Häkchen bleiben erhalten.
function selectNewestDocuments(documents) {
  for (const group of DOCUMENT_GROUPS) {
    const newest = documents.find((doc) => doc.typ === group.type);
    if (newest) selectedDocumentIds.add(newest.id);
  }
}



// --- Studiengang und Prüfungsordnung ---

// Einmal beim Start: Studiengänge, Prüfungsordnungen und alle Dokumente
async function loadCatalog() {
  try {
    const catalog = await requestApi("/katalog");
    programs = catalog.studiengaenge;
    catalogDocuments = catalog.dokumente;
  } catch (error) {
    showDocumentHint("Dokumente nicht verfügbar");
    return;
  }

  catalogDocuments.forEach((doc) => documentsById.set(doc.id, doc));
  findDocumentOrigins();
  fillProgramSelect();
  selectProgram(loadNumber("studiengang_id"), loadNumber("pruefungsordnung_id"));
  loadDocuments();
}

// Die Dokumente der gewählten Prüfungsordnung stehen schon im Katalog.
function loadDocuments() {
  if (!selectedRegulation) {
    showDocuments([]);
    return;
  }

  const documentIds = new Set(selectedRegulation.dokument_ids);
  const documents = catalogDocuments.filter((doc) => documentIds.has(doc.id));
  selectNewestDocuments(documents);
  showDocuments(documents);
}

// Die neueste Version jeder Dokumentart geht immer an den Assistenten, weitere Häkchen bleiben erhalten.
function selectNewestDocuments(documents) {
  for (const group of DOCUMENT_GROUPS) {
    const newest = documents.find((doc) => doc.typ === group.type);
    if (newest) selectedDocumentIds.add(newest.id);
  }
}

function fillProgramSelect() {
  programSelect.innerHTML = "";
  for (const program of programs) {
    programSelect.appendChild(new Option(programName(program), program.id));
  }
}

// Eine unbekannte oder gespeicherte Auswahl, die es nicht mehr gibt, fällt auf den ersten Eintrag zurück.
function selectProgram(programId, regulationId) {
  const program = programs.find((entry) => entry.id === programId) ?? programs[0];
  if (!program) return;

  selectedProgram = program;
  programSelect.value = program.id;
  regulationSelect.innerHTML = "";
  for (const regulation of program.pruefungsordnungen) {
    regulationSelect.appendChild(new Option(`PO ${regulation.jahr}`, regulation.id));
  }

  selectedRegulation = program.pruefungsordnungen.find((entry) => entry.id === regulationId)
    ?? program.pruefungsordnungen[0] ?? null;
  if (selectedRegulation) regulationSelect.value = selectedRegulation.id;
  storeValue("studiengang_id", program.id);
  storeValue("pruefungsordnung_id", selectedRegulation?.id ?? null);
}

// Beim Wechsel beginnt die Dokumentauswahl neu, nur festgehaltene Dokumente bleiben im Kontext.
function changeSelection(programId, regulationId) {
  hasRestoredChatDocuments = false;
  selectProgram(programId, regulationId);
  for (const id of [...selectedDocumentIds]) {
    if (!pinnedDocumentIds.has(id)) selectedDocumentIds.delete(id);
  }
  loadDocuments();
}

programSelect.addEventListener("change", () => changeSelection(Number(programSelect.value), null));
regulationSelect.addEventListener("change", () => changeSelection(Number(programSelect.value), Number(regulationSelect.value)));



// --- Benennung der Dokumente ---

// Ein Dokument heißt überall nach denselben drei Teilen: Art (ÜPO, PO, MHB), Fassung ("09/2025", "WS 26/27") und, wo es
// nicht für alle gilt, Studiengang mit Jahr der PO. Die Liste links, der Kontext und der Pfad über dem PDF setzen sie nur
// unterschiedlich zusammen.

function findGroup(doc) {
  return DOCUMENT_GROUPS.find((entry) => entry.type === doc.typ);
}

function programName(program) {
  return `${program.name} ${program.abschluss}`;
}

// Zu welchem Studiengang und welcher PO ein Dokument laut Katalog gehört; die übergreifende PO gilt für alle
function findDocumentOrigins() {
  for (const program of programs) {
    for (const regulation of program.pruefungsordnungen) {
      regulation.dokument_ids.forEach((id) => { documentOrigins[id] ??= { program, regulation }; });
    }
  }
}

// Kurzform der Fassung: Prüfungsordnungen "09/2025", Modulhandbücher "WS 26/27" bzw. "SS 26" (semester: "2026-wintersemester")
function shortVersion(doc) {
  const semester = doc.semester?.match(/^(\d{4})-(winter|sommer)semester$/);
  if (doc.typ === "modulhandbuch" && semester) {
    const year = Number(semester[1]);
    const shortYear = String(year).slice(-2);
    return semester[2] === "sommer" ? `SS ${shortYear}` : `WS ${shortYear}/${String(year + 1).slice(-2)}`;
  }
  if (!doc.erschienen_am) return doc.titel;

  const [year, month] = doc.erschienen_am.split("-");
  return `${month}/${year}`;
}

function isFirstVersion(doc) {
  return FIRST_VERSION_IN_TITLE.test(doc.titel);
}

// Hauptzeile in der Liste und letzter Teil des Pfads: "Fassung 09/2025", die erste Ordnung "Erstfassung 03/2022", beim
// Modulhandbuch nur "WS 26/27"
function versionLabel(doc) {
  if (doc.typ === "modulhandbuch") return shortVersion(doc);

  return `${isFirstVersion(doc) ? "Erstfassung" : "Fassung"} ${shortVersion(doc)}`;
}

// Zeile im Versionsverlauf: ohne das Wort "Fassung", nur die erste Ordnung behält ihren Namen
function historyLabel(doc) {
  return isFirstVersion(doc) ? versionLabel(doc) : shortVersion(doc);
}

// Name im Kontext (unter der Eingabe), wo Dokumente aus verschiedenen Studiengängen nebeneinander liegen:
// "Informatik B.Sc. 2022 · PO 09/2025"
function contextLabel(doc) {
  const name = `${findGroup(doc).abbreviation} ${shortVersion(doc)}`;
  const origin = documentOrigins[doc.id];
  if (!origin || doc.typ === "uebergreifende_po") return name;

  return `${programName(origin.program)} ${origin.regulation.jahr} · ${name}`;
}

// Überschrift einer Dokumentart in der Liste: Die fachspezifische PO und das Modulhandbuch heißen nach dem Studiengang
function groupTitle(group) {
  if (group.type === "uebergreifende_po" || !selectedProgram) return group.label;

  const kind = group.type === "fachspezifische_po" ? "PO" : group.label;
  return `${kind} ${programName(selectedProgram)}`;
}

// Pfad über dem PDF: Studiengang / Jahr der PO / Art / Fassung. Gehört das Dokument zur gewählten PO, gilt diese, sonst die
// laut Katalog; die übergreifende PO hat ohne gewählte PO keinen Studiengang.
function createBreadcrumbTrail(doc) {
  const origin = findPathOrigin(doc);
  const trail = [findGroup(doc).abbreviation, versionLabel(doc)];
  if (!origin) return trail;

  return [programName(origin.program), String(origin.regulation.jahr), ...trail];
}

function findPathOrigin(doc) {
  if (selectedRegulation?.dokument_ids.includes(doc.id)) return { program: selectedProgram, regulation: selectedRegulation };
  if (doc.typ === "uebergreifende_po") return null;

  return documentOrigins[doc.id] ?? null;
}

// Zweite Zeile in der Liste: "aktuell" bei der neuesten Fassung, was darin eingearbeitet ist und die Seitenzahl
function describeDocument(doc, isNewest) {
  const parts = [];
  if (isNewest) parts.push("aktuell");
  const note = describeContent(doc);
  if (note) parts.push(note);
  if (doc.seiten) parts.push(`${doc.seiten} Seiten`);
  return parts.join(" · ");
}

// Bei einer Prüfungsordnung die eingearbeitete Änderung ("inkl. 21. Änderung"); den Studiengang eines Modulhandbuchs nennt
// schon die Überschrift der Gruppe
function describeContent(doc) {
  const amendment = doc.titel.match(AMENDMENT_IN_TITLE);
  return amendment ? `inkl. ${amendment[1]}. Änderung` : "";
}



// --- Dokumente ---

// Jede Dokumentart steht immer da, ohne Dokument mit einem kurzen Hinweis.
// Die Dokumente kommen mit der neuesten Version zuerst, ältere stehen hinter "ältere Versionen".
function showDocuments(documents) {
  documentList.innerHTML = "";
  for (const group of DOCUMENT_GROUPS) {
    const groupDocuments = documents.filter((doc) => doc.typ === group.type);
    showDocumentGroup(groupTitle(group), groupDocuments);
  }

  fadeIn(documentList);
  renderContext();
}

function showDocumentGroup(title, groupDocuments) {
  const group = document.createElement("li");
  group.className = "group";

  const card = document.createElement("ul");
  card.className = "group-card";
  group.append(createGroupTitle(title, groupDocuments.length), card);
  documentList.appendChild(group);

  if (groupDocuments.length === 0) {
    card.appendChild(createTextItem("empty-group", "Kein Dokument vorhanden."));
    return;
  }

  const [newest, ...olderVersions] = groupDocuments;
  card.appendChild(createDocumentEntry(newest));
  if (olderVersions.length > 0) card.appendChild(createOlderVersions(olderVersions));
}

function createGroupTitle(title, count) {
  const heading = document.createElement("h3");
  heading.className = "group-title";
  heading.textContent = title;
  if (count > 0) heading.appendChild(createTextSpan("counter", count));
  return heading;
}

function createOlderVersions(olderVersions) {
  const wrapper = document.createElement("li");
  wrapper.className = "older-versions";

  const details = document.createElement("details");
  details.open = olderVersions.some((doc) => selectedDocumentIds.has(doc.id));

  const summary = document.createElement("summary");
  summary.textContent = olderVersions.length === 1 ? "1 ältere Version" : `${olderVersions.length} ältere Versionen`;

  const list = document.createElement("ul");
  olderVersions.forEach((doc, index) => {
    const entry = createVersionEntry(doc);
    entry.style.setProperty("--i", Math.min(index, 12));
    list.appendChild(entry);
  });

  details.append(summary, list);
  wrapper.appendChild(details);
  return wrapper;
}

// Die neueste Fassung einer Art: Name und Details, rechts das Häkchen
function createDocumentEntry(doc) {
  const entry = document.createElement("li");
  entry.dataset.id = doc.id;

  const name = createTextSpan("document-name", versionLabel(doc));
  const details = createTextSpan("document-details", describeDocument(doc, true));
  entry.append(createDocumentLink(doc, name, details), createSelectCheckbox(doc));
  return entry;
}

// Ältere Fassungen als kleiner Versionsverlauf: eine Zeile mit Fassung und Notiz, das Häkchen rechts
function createVersionEntry(doc) {
  const entry = document.createElement("li");
  entry.className = "version-entry";
  entry.dataset.id = doc.id;

  const name = createTextSpan("version-name", historyLabel(doc));
  const note = createTextSpan("version-note", describeContent(doc));
  entry.append(createDocumentLink(doc, name, note), createSelectCheckbox(doc));
  return entry;
}

// Ein Klick auf den Namen öffnet das PDF
function createDocumentLink(doc, ...parts) {
  const link = document.createElement("span");
  link.append(...parts);
  link.addEventListener("click", () => showPdf(documentPdfUrl(doc.id), doc.id));
  return link;
}

function createSelectCheckbox(doc) {
  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.dataset.tooltip = "Dem Assistenten geben (in den Kontext)";
  checkbox.checked = selectedDocumentIds.has(doc.id);
  checkbox.addEventListener("change", () => {
    animateElement(checkbox, [{ transform: "scale(0.7)" }, { transform: "none" }], 200);
    setDocumentSelected(doc.id, checkbox.checked);
  });
  return checkbox;
}

function createTextSpan(className, text) {
  const span = document.createElement("span");
  span.className = className;
  span.textContent = text;
  return span;
}

function createTextItem(className, text) {
  const item = document.createElement("li");
  item.className = className;
  item.textContent = text;
  return item;
}

function showDocumentHint(text) {
  documentList.innerHTML = `<li class="hint">${text}</li>`;
}



// --- Kontext ---

// Ein abgewähltes Dokument ist auch nicht mehr festgehalten.
function setDocumentSelected(documentId, isSelected) {
  if (isSelected) {
    selectedDocumentIds.add(documentId);
  } else {
    selectedDocumentIds.delete(documentId);
    pinnedDocumentIds.delete(documentId);
    storePinnedDocuments();
  }

  const checkbox = documentList.querySelector(`[data-id="${documentId}"] input`);
  if (checkbox) checkbox.checked = isSelected;
  if (isSelected) renderContext();
  else removeChipAnimated(documentId);
}

// Eine entfernte Marke schrumpft erst weg, dann wird die Leiste neu gezeichnet
function removeChipAnimated(documentId) {
  const chip = contextList.querySelector(`[data-id="${documentId}"]`);
  if (!chip || prefersReducedMotion.matches) {
    renderContext();
    return;
  }

  chip.classList.add("is-leaving");
  setTimeout(renderContext, CHIP_LEAVE_MS);
}

function togglePinned(documentId) {
  if (pinnedDocumentIds.has(documentId)) pinnedDocumentIds.delete(documentId);
  else pinnedDocumentIds.add(documentId);
  storePinnedDocuments();
  renderContext();

  const pinIcon = contextList.querySelector(`[data-id="${documentId}"] .chip-pin svg`);
  if (pinIcon && pinnedDocumentIds.has(documentId)) {
    fadeIn(pinIcon);
  }
}

// Kleine Leiste unter der Eingabe: alle Dokumente, die der Assistent bei der nächsten Frage bekommt. Ihre PDFs lädt der
// Browser gleich im Hintergrund, damit sie beim Öffnen sofort da sind.
function renderContext() {
  const chips = [...selectedDocumentIds].map(createContextChip);
  chips.forEach((chip) => {
    if (!renderedChipIds.has(Number(chip.dataset.id))) chip.classList.add("is-entering");
  });
  contextList.replaceChildren(...chips);
  renderedChipIds = new Set(selectedDocumentIds);
  keepPdfsPreloaded([...selectedDocumentIds].map(documentPdfUrl));
}

function documentPdfUrl(documentId) {
  return `${API_URL}/dokumente/${documentId}/pdf`;
}

function createContextChip(documentId) {
  const doc = documentsById.get(documentId);
  const label = doc ? contextLabel(doc) : `Dokument ${documentId}`;
  const isPinned = pinnedDocumentIds.has(documentId);

  const chip = document.createElement("span");
  chip.className = "context-chip";
  chip.dataset.id = documentId;
  chip.classList.toggle("pinned", isPinned);

  const name = createChipButton("chip-name", `${label} (Klick öffnet das PDF)`);
  name.textContent = label;
  name.addEventListener("click", () => showPdf(documentPdfUrl(documentId), documentId));

  const pin = createChipButton("chip-pin", isPinned ? "Nicht mehr festhalten" : "Festhalten: bleibt auch bei anderer Prüfungsordnung im Kontext");
  pin.innerHTML = PIN_ICON;
  pin.addEventListener("click", () => togglePinned(documentId));

  const remove = createChipButton("chip-remove", "Aus dem Kontext entfernen");
  remove.innerHTML = CLOSE_ICON;
  remove.addEventListener("click", () => setDocumentSelected(documentId, false));

  chip.append(name, pin, remove);
  return chip;
}

// Ein Knopf der Marke mit Hoverfenster; Text oder Symbol setzt der Aufrufer
function createChipButton(className, tooltip) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = className;
  button.dataset.tooltip = tooltip;
  return button;
}



// --- PDF ---

// page = Seite, auf die der Viewer springt; highlights = Markierungen eines Zitats auf den Seiten; kind = Art des Belegs (Farbe)
async function showPdf(url, documentId, page = 1, highlights = [], kind = "belegt") {
  viewerHint.hidden = true;
  showPdfTitle(documentId);
  documentList.querySelector(".open")?.classList.remove("open");
  documentList.querySelector(`[data-id="${documentId}"]`)?.classList.add("open");

  try {
    await openPdf(url, page, highlights, kind);
  } catch (error) {
    console.error("PDF konnte nicht geladen werden:", error);
    viewerHint.textContent = "Das PDF konnte nicht geladen werden.";
    viewerHint.hidden = false;
  }
}

// Über dem PDF als Pfad: Studiengang / Jahr der PO / Kürzel der Art (ÜPO, PO, MHB) / Fassung
function showPdfTitle(documentId) {
  const doc = catalogDocuments.find((entry) => entry.id === documentId);
  const trail = doc ? createBreadcrumbTrail(doc) : [];
  const parts = [];

  trail.forEach((step, index) => {
    if (index > 0) parts.push(createCrumbSeparator());
    const isLast = index === trail.length - 1;
    const crumb = document.createElement(isLast ? "strong" : "span");
    crumb.textContent = step;
    parts.push(crumb);
  });
  pdfTitle.replaceChildren(...parts);
}

function createCrumbSeparator() {
  const separator = document.createElement("span");
  separator.className = "crumb-separator";
  separator.textContent = "/";
  return separator;
}

// Das Dokument der Quelle, auf der Seite des Zitats und mit dem Zitat markiert
async function showSource(sourceId, quote, kind) {
  const profile = sourceProfiles[sourceId];
  const query = `?${new URLSearchParams({ zitat: quote })}`;

  try {
    const passage = await requestApi(`/quellen/${sourceId}/stelle${query}`);
    showPdf(documentPdfUrl(passage.dokument_id), passage.dokument_id, passage.seite, passage.bereiche, kind);
  } catch (error) {
    if (profile) showPdf(documentPdfUrl(profile.dokument_id), profile.dokument_id, profile.seite ?? 1);
  }
}



// --- Nachrichten ---

// content wie in nachricht.inhalt: {"text"} vom Nutzer, {"markdown", ...} vom Assistenten
function showMessage(role, content) {
  const message = document.createElement("div");
  message.className = `message ${ROLE_CLASSES[role]}`;
  if (role === "nutzer") {
    message.textContent = content.text;
  } else if (content) {
    showAnswer(message, content);
  }
  messageList.appendChild(message);
  messageList.scrollTop = messageList.scrollHeight;
  if (!isRestoringChat) animateElement(message, [{ opacity: 0, transform: "translateY(6px)" }, { opacity: 1, transform: "none" }]);
  return message;
}

// darunter die Dauer, falls gespeichert
function showAnswer(element, content) {
  Object.assign(sourceProfiles, content.quellen);
  element.innerHTML = DOMPurify.sanitize(marked.parse(withCitations(content.markdown)));
  if (content.sekunden === undefined) return;

  const formatNumber = (value) => value.toLocaleString("de-DE");
  const info = document.createElement("div");
  info.className = "info";
  const steps = (content.schritte ?? []).map((step) => `${step.name} ${formatNumber(step.sekunden)} s`).join(" · ");
  info.textContent = `${formatNumber(content.sekunden)} s${steps ? ` (${steps})` : ""}`;
  element.appendChild(info);
}



// --- Marken ---

// Marken [[belegt: c1162, m225]], [[abgeleitet: ...]], [[hinweis]] gelten fuer den Text davor in derselben Zeile
// (Absatz, Listenpunkt oder Ueberschrift). Text ohne Marke bleibt unmarkiert.
// Eine Marke reicht bis zum nächsten "]]", ein Zitat darf also eckige Klammern enthalten.
const MARKER_PATTERN = "\\[\\[(?:(?!\\]\\]).)+\\]\\]";
const MARKER_GROUP = new RegExp(`((?:\\s*${MARKER_PATTERN})+)`);
const MARKER_CONTENT = new RegExp(`\\[\\[((?:(?!\\]\\]).)+)\\]\\]`, "g");
const MARKER_ONLY_LINE = new RegExp(`^(?:\\s*${MARKER_PATTERN})+\\s*$`);
const LEADING_MARKERS = new RegExp(`^(\\s*(?:[-*+] |\\d+\\. |#+ )?)((?:\\s*${MARKER_PATTERN})+)\\s*(\\S.*)$`);

function withCitations(markdown) {
  return attachStrayMarkers(joinMarkerLines(markdown).split("\n")).map(withCitationsInLine).join("\n");
}

// Ein Zitat darf einen Zeilenumbruch enthalten ("Modultitel: …" und "Kennung: …" stehen im PDF in zwei Zeilen), die
// Marke wird aber zeilenweise gelesen. Deshalb werden die Zeilen einer Marke vorher zu einer verbunden.
function joinMarkerLines(markdown) {
  return markdown.replace(/\[\[[\s\S]*?\]\]/g, (marker) => marker.replace(/\s*\n\s*/g, " "));
}

// Marken gelten für den Text davor. Steht eine allein in einer Zeile, gehört sie zur Zeile davor; steht sie vor dem
// Text einer Zeile, gilt sie für diesen Text. Sonst ginge sie verloren.
function attachStrayMarkers(lines) {
  const result = [];
  for (const line of lines) {
    if (MARKER_ONLY_LINE.test(line) && result.some((entry) => entry.trim())) {
      const lastIndex = result.map((entry) => entry.trim() !== "").lastIndexOf(true);
      result[lastIndex] += ` ${line.trim()}`;
      continue;
    }
    result.push(line.replace(LEADING_MARKERS, "$1$3 $2"));
  }
  return result;
}

function withCitationsInLine(line) {
  const prefix = line.match(/^\s*(?:[-*+] |\d+\. |#+ )?/)[0];
  // abwechselnd Text und Marken: [Text, Marken, Text, ..., Text]
  const parts = line.slice(prefix.length).split(MARKER_GROUP);
  const rendered = parts.map((text, index) => {
    if (index % 2) return "";
    const markers = [...(parts[index + 1] ?? "").matchAll(MARKER_CONTENT)].map((match) => match[1]);
    return markers.length && text.trim() ? createCitation(text, markers) : text;
  });
  return prefix + rendered.join("");
}

// Die Art kommt von der ersten Marke, die Quellen von allen; das Zitat einer Quelle steht in »…« dahinter.
// Mehrere Zitate derselben Quelle gehen durch Zeilenumbrueche getrennt ans Backend.
function createCitation(text, markers) {
  const kind = markers[0].match(/^\s*(belegt|abgeleitet|hinweis|nicht_gefunden)/i)?.[1].toLowerCase() ?? "belegt";
  const quotes = {};
  for (const match of markers.join(", ").matchAll(/\b([cm]\d+)(?:\s*»([^«]*)«)?/g)) {
    quotes[match[1]] = [quotes[match[1]], match[2]].filter(Boolean).join("\n");
  }
  const sources = Object.keys(quotes).join(" ");
  const quotesAttribute = encodeURIComponent(JSON.stringify(quotes));
  const leadingSpace = text.match(/^\s*/)[0];
  return `${leadingSpace}<span class="citation" data-kind="${kind}" data-sources="${sources}" ` +
    `data-quotes="${quotesAttribute}">${text.trim()}</span>`;
}

function citationQuotes(citation) {
  return JSON.parse(decodeURIComponent(citation.dataset.quotes || "%7B%7D"));
}



// --- Quellenauswahl ---

// Klick auf eine Marke zeigt unter der Zeile ihre Art und ihre Quellen, ein Klick auf eine Quelle oeffnet sie
// im PDF. Ein Klick woanders schliesst die Auswahl.
document.addEventListener("click", (event) => {
  if (sourcePicker.contains(event.target)) return;

  const citation = event.target.closest(".message .citation");
  if (!citation) {
    hideSourcePicker();
    return;
  }

  fillSourcePicker(citation);
  placeSourcePicker(citation, event);
  showSourcePicker();
});

// Die Auswahl klappt von der Stelle des Klicks auf und kurz vor dem Schließen wieder zu (Animationen im CSS)
function showSourcePicker() {
  clearTimeout(pickerTimer);
  sourcePicker.classList.remove("closing");
  sourcePicker.hidden = false;
}

function hideSourcePicker() {
  if (sourcePicker.hidden) return;

  sourcePicker.classList.add("closing");
  pickerTimer = setTimeout(() => {
    sourcePicker.hidden = true;
    sourcePicker.classList.remove("closing");
  }, PICKER_CLOSE_MS);
}

function fillSourcePicker(citation) {
  const heading = document.createElement("div");
  heading.dataset.kind = citation.dataset.kind;
  heading.textContent = KIND_LABELS[citation.dataset.kind];
  const sourceIds = citation.dataset.sources.split(" ").filter(Boolean);
  const quotes = citationQuotes(citation);
  const buttons = sourceIds.map((sourceId) => createSourceButton(sourceId, quotes[sourceId], citation.dataset.kind));
  sourcePicker.replaceChildren(heading, ...buttons);
}

// Beleg mit Titel, darunter Dokument und Seite, darunter das Zitat
function createSourceButton(sourceId, quote, kind) {
  const profile = sourceProfiles[sourceId];
  const quoteText = quote ? quote.split("\n").join(" … ") : "";
  const button = document.createElement("button");
  button.type = "button";
  button.dataset.kind = kind;
  if (quoteText) button.dataset.tooltip = `»${quoteText}«`;
  button.addEventListener("click", () => showSource(sourceId, quote, kind));

  if (!profile) {
    button.textContent = sourceId;
    return button;
  }

  const doc = documentsById.get(profile.dokument_id);
  const documentName = doc ? contextLabel(doc) : `Dokument ${profile.dokument_id}`;
  button.append(
    createTextSpan("source-title", profile.titel),
    createTextSpan("source-meta", `${documentName} · S. ${profile.seite}`),
  );
  if (quoteText) button.appendChild(createTextSpan("source-quote", `»${quoteText}«`));
  return button;
}



// unter der angeklickten Zeile einer mehrzeiligen Marke
function placeSourcePicker(citation, event) {
  const lineRects = [...citation.getClientRects()];
  const clickedLine = lineRects.find((rect) => rect.top <= event.clientY && event.clientY <= rect.bottom)
    ?? citation.getBoundingClientRect();
  const left = Math.min(event.clientX - 20, innerWidth - PICKER_WIDTH);
  sourcePicker.style.left = `${Math.max(0, left)}px`;
  sourcePicker.style.top = `${clickedLine.bottom + 2}px`;
}



// --- Token-Zähler ---

// Oben im Chat: der Verbrauch des Nutzers heute (Eingabe und Ausgabe zusammen) in Prozent des Tagesbudgets. Das Backend zählt
// ihn und setzt ihn um Mitternacht auf null; nach jeder Antwort kommt der neue Stand mit.
async function loadTokenUsage() {
  if (!userId) {
    showDayTokens({ eingabe: 0, ausgabe: 0 });
    return;
  }

  try {
    showDayTokens(await requestApi(`/nutzer/${userId}/verbrauch`));
  } catch (error) {
    showDayTokens({ eingabe: 0, ausgabe: 0 });
  }
}

// Bei jedem Darüberfahren und bei jedem Klick wird der Stand neu geholt, der Tooltip nennt die Uhrzeit
tokenCounter.addEventListener("mouseenter", loadTokenUsage);
tokenCounter.addEventListener("click", loadTokenUsage);

function showDayTokens({ eingabe, ausgabe, limit }) {
  dayTokens = { eingabe, ausgabe };
  if (limit) tokenBudget = limit;
  renderTokenCounter();
  updateSendButton();
}

function isBudgetExhausted() {
  return dayTokens.eingabe + dayTokens.ausgabe >= tokenBudget;
}

// Senden ist grau und gesperrt, solange eine Antwort läuft oder das Tagesbudget aufgebraucht ist; im zweiten Fall sagt es
// der Tooltip. aria-disabled statt disabled, damit der Tooltip beim Darüberfahren trotzdem erscheint.
function updateSendButton() {
  const isExhausted = isBudgetExhausted();
  sendButton.disabled = isAnswering;
  sendButton.classList.toggle("is-exhausted", isExhausted);
  sendButton.setAttribute("aria-disabled", isExhausted);
  if (isExhausted) sendButton.dataset.tooltip = `Tokenlimit erreicht, Reset in ${describeTimeUntilReset()}`;
  else delete sendButton.dataset.tooltip;
  if (isExhausted && tooltipTarget === sendButton) showTooltip(sendButton);
}

// Die Zeit bis zum Reset rechnet sich beim Darüberfahren neu
sendButton.addEventListener("mouseenter", updateSendButton);

// Wer die Seite über Nacht offen lässt, sieht beim Zurückkehren den neuen Tag
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") loadTokenUsage();
});

// Der Zähler beginnt um Mitternacht (Europe/Berlin) bei null: "5 Std. 12 Min."
function describeTimeUntilReset() {
  const formatter = new Intl.DateTimeFormat("de-DE", { timeZone: "Europe/Berlin", hour: "numeric", minute: "numeric", hourCycle: "h23" });
  const parts = formatter.formatToParts(new Date());
  const hour = Number(parts.find((part) => part.type === "hour").value);
  const minute = Number(parts.find((part) => part.type === "minute").value);

  const minutesLeft = 24 * 60 - (hour * 60 + minute);
  return `${Math.floor(minutesLeft / 60)} Std. ${minutesLeft % 60} Min.`;
}

// Die Prozentzahl zählt vom alten zum neuen Wert, der Ring läuft über seinen eigenen Übergang mit
function showPercent(target) {
  const label = tokenCounter.querySelector(".token-percent");
  const start = shownPercent;
  shownPercent = target;
  cancelAnimationFrame(percentFrame);
  if (prefersReducedMotion.matches || start === target) {
    label.textContent = `${target} %`;
    return;
  }

  const startTime = performance.now();
  const step = (now) => {
    const progress = Math.min(1, (now - startTime) / PERCENT_COUNT_MS);
    label.textContent = `${Math.round(start + (target - start) * progress)} %`;
    if (progress < 1) percentFrame = requestAnimationFrame(step);
  };
  percentFrame = requestAnimationFrame(step);
  // Falls der Browser im Hintergrund keine Bilder zeichnet, steht der Endwert trotzdem da
  setTimeout(() => { if (shownPercent === target) label.textContent = `${target} %`; }, PERCENT_COUNT_MS + 50);
}

function renderTokenCounter() {
  const used = dayTokens.eingabe + dayTokens.ausgabe;
  const percent = Math.min(100, Math.round((used / tokenBudget) * 100));
  showPercent(percent);
  tokenCounter.querySelector(".token-ring-value").setAttribute("stroke-dashoffset", 100 - percent);

  tokenCounter.dataset.tooltip = `${percent} % verbraucht, Reset in ${describeTimeUntilReset()}`;
  if (tooltipTarget === tokenCounter) showTooltip(tokenCounter);
}



// --- Verbindung ---

// Ein kleiner Knopf neben dem Token-Ring: Beim Laden und bei jedem Darüberfahren oder Klick geht ein kleiner Call an die API
// (GET /health, kostet nichts). Die Balken zeigen die Antwortzeit, der Tooltip nennt sie.
async function checkConnection() {
  if (isCheckingConnection) return;

  isCheckingConnection = true;
  const checkingTimer = setTimeout(() => setConnectionState("checking", "Verbindung wird geprüft …"), CONNECTION_CHECKING_DELAY_MS);
  const startTime = performance.now();

  try {
    const response = await fetch(`${API_URL}/health`, { cache: "no-store", signal: AbortSignal.timeout(CONNECTION_TIMEOUT_MS) });
    if (!response.ok) throw new Error(response.status);
    showConnectionSpeed(Math.round(performance.now() - startTime));
  } catch (error) {
    setConnectionState("offline", "Keine Verbindung zur API");
  } finally {
    clearTimeout(checkingTimer);
    isCheckingConnection = false;
  }
}

function showConnectionSpeed(milliseconds) {
  const text = `${milliseconds.toLocaleString("de-DE")} ms`;
  if (milliseconds <= CONNECTION_FAST_MS) setConnectionState("fast", `API schnell · ${text}`);
  else if (milliseconds <= CONNECTION_SLOW_MS) setConnectionState("medium", `API mittel · ${text}`);
  else setConnectionState("slow", `API langsam · ${text}`);
}

function setConnectionState(state, text) {
  connectionButton.dataset.state = state;
  connectionButton.dataset.tooltip = text;
  if (tooltipTarget === connectionButton) showTooltip(connectionButton);
}

connectionButton.addEventListener("mouseenter", checkConnection);
connectionButton.addEventListener("click", checkConnection);



// --- Hoverfenster ---

// Ein gemeinsames Fenster für alle Elemente mit data-tooltip (data-tooltip-side="below" setzt es darunter statt darüber).
// Es sitzt ausserhalb aller scrollenden Bereiche und wird nicht abgeschnitten.
const TOOLTIP_GAP = 8;
const TOOLTIP_MARGIN = 8;
const tooltip = document.createElement("div");
tooltip.className = "tooltip";
tooltip.hidden = true;
document.body.appendChild(tooltip);
let tooltipTarget = null;

function showTooltip(target) {
  tooltipTarget = target;
  tooltip.textContent = target.dataset.tooltip;
  tooltip.hidden = false;

  const rect = target.getBoundingClientRect();
  const height = tooltip.offsetHeight;
  const above = rect.top - height - TOOLTIP_GAP;
  const below = rect.bottom + TOOLTIP_GAP;
  // Standard ist darüber (data-tooltip-side="below": darunter); fehlt dort der Platz, springt es auf die andere Seite
  const prefersBelow = target.dataset.tooltipSide === "below";
  const fitsAbove = above >= TOOLTIP_MARGIN;
  const fitsBelow = below + height <= innerHeight - TOOLTIP_MARGIN;
  const useBelow = prefersBelow ? fitsBelow || !fitsAbove : !fitsAbove && fitsBelow;

  const maxTop = innerHeight - height - TOOLTIP_MARGIN;
  const centered = rect.left + rect.width / 2 - tooltip.offsetWidth / 2;
  const maxLeft = innerWidth - tooltip.offsetWidth - TOOLTIP_MARGIN;
  const left = Math.min(Math.max(TOOLTIP_MARGIN, centered), maxLeft);
  tooltip.style.top = `${Math.min(Math.max(TOOLTIP_MARGIN, useBelow ? below : above), maxTop)}px`;
  tooltip.style.left = `${left}px`;

  // Der Pfeil zeigt auf die Mitte des Elements, auch wenn das Fenster am Rand verschoben wurde
  tooltip.dataset.side = useBelow ? "below" : "above";
  tooltip.style.setProperty("--arrow-left", `${rect.left + rect.width / 2 - left}px`);
}

function hideTooltip() {
  tooltipTarget = null;
  tooltip.hidden = true;
}

function updateTooltip(event) {
  const target = event.target.closest?.("[data-tooltip]");
  if (target === tooltipTarget) return;

  if (target) showTooltip(target);
  else hideTooltip();
}

document.addEventListener("mouseover", updateTooltip);
document.addEventListener("focusin", updateTooltip);
// Bei API und Token bleibt der Tooltip nach dem Klick stehen, er zeigt dann den neu geholten Stand
document.addEventListener("pointerdown", (event) => {
  if (event.target.closest?.("#connection-status, #token-counter")) return;

  hideTooltip();
});
document.addEventListener("scroll", hideTooltip, true);



// --- Spalten ---

// Am Trenner ziehen: links aendert die Dokumente, rechts den Assistenten (Grenzen im CSS).
// Die Spalte bleibt beim Ziehen bei der Mindestbreite stehen, ab einer Schwelle verschwindet sie ganz (und kommt beim
// Zurückziehen wieder). Wer so loslässt, klappt die Seitenleiste ein; ein Knopf am Rand holt sie zurueck.
// So weit unter die Mindestbreite muss man ziehen, damit die Spalte ganz verschwindet
const HIDE_DISTANCE = 70;
const SIDES = {
  left: { column: document.querySelector(".documents"), divider: document.querySelector('.divider[data-side="left"]') },
  right: { column: document.querySelector(".chat"), divider: document.querySelector('.divider[data-side="right"]') },
};

for (const divider of document.querySelectorAll(".divider")) {
  divider.addEventListener("pointerdown", (startEvent) => startResize(divider, startEvent));
}

for (const button of document.querySelectorAll(".expand-button")) {
  button.addEventListener("click", () => setCollapsed(button.dataset.side, false, true));
}

for (const button of document.querySelectorAll(".collapse-button")) {
  button.addEventListener("click", () => setCollapsed(button.dataset.side, true, true));
}

// Beim Ausklappen gilt wieder die Standardbreite aus dem CSS, nicht die zuletzt gezogene (sie lag am Minimum). Mit
// shouldSlide gleitet die Spalte zu oder auf, sonst springt sie.
function setCollapsed(side, isCollapsed, shouldSlide = false) {
  const { column, divider } = SIDES[side];
  document.getElementById(`expand-${side}`).hidden = !isCollapsed;
  document.body.classList.toggle(`${side}-collapsed`, isCollapsed);
  storeValue(`collapsed_${side}`, isCollapsed ? "1" : null);

  if (shouldSlide && !prefersReducedMotion.matches) slideColumn(column, divider, isCollapsed);
  else applyCollapsed(column, divider, isCollapsed);
}

function applyCollapsed(column, divider, isCollapsed) {
  column.style.width = "";
  column.classList.remove("sliding");
  column.classList.toggle("collapsed", isCollapsed);
  divider.classList.toggle("collapsed", isCollapsed);
}

// Die Breite läuft über ein CSS-Transition von der vollen Breite auf 0 oder umgekehrt, danach gilt der endgültige Zustand
function slideColumn(column, divider, isCollapsed) {
  let fullWidth = column.offsetWidth;
  if (!isCollapsed) {
    column.classList.remove("collapsed");
    divider.classList.remove("collapsed");
    column.style.width = "";
    fullWidth = column.offsetWidth;
  }

  column.style.width = `${isCollapsed ? fullWidth : 0}px`;
  column.classList.add("sliding");
  void column.offsetWidth;
  column.style.width = `${isCollapsed ? 0 : fullWidth}px`;
  setTimeout(() => applyCollapsed(column, divider, isCollapsed), COLUMN_SLIDE_MS);
}

function startResize(divider, startEvent) {
  // Ohne das beginnt der Browser beim Ziehen, Text zu markieren
  startEvent.preventDefault();
  divider.setPointerCapture(startEvent.pointerId);
  const side = divider.dataset.side;
  const isLeft = side === "left";
  const column = SIDES[side].column;
  const startWidth = column.offsetWidth;
  const minimumWidth = parseFloat(getComputedStyle(column).minWidth);
  let pendingWidth = startWidth;
  let isHidden = false;
  let isFramePending = false;
  document.body.classList.add("resizing");
  divider.classList.add("active");

  // Die Breite wird höchstens einmal pro Bild gesetzt, sonst rechnet der PDF-Viewer bei jedem Mausereignis neu
  const applyWidth = () => {
    isFramePending = false;
    column.style.width = `${pendingWidth}px`;
  };
  // Eingeklappt (mit dem Pfeil am Rand) wird erst beim Loslassen, und nur, wenn die Spalte da gerade ganz weg ist
  const stopResize = () => {
    window.removeEventListener("pointermove", resize);
    window.removeEventListener("pointerup", stopResize);
    document.body.classList.remove("resizing");
    divider.classList.remove("active");
    column.classList.remove("drag-hidden");
    if (isHidden) setCollapsed(side, true);
  };
  // Die Spalte bleibt bei der Mindestbreite stehen; wer ein Stück weiter zieht, lässt sie ganz verschwinden, beim
  // Zurückziehen kommt sie wieder
  const resize = (event) => {
    const offset = event.clientX - startEvent.clientX;
    const requestedWidth = startWidth + (isLeft ? offset : -offset);
    isHidden = requestedWidth < minimumWidth - HIDE_DISTANCE;
    column.classList.toggle("drag-hidden", isHidden);
    pendingWidth = Math.max(requestedWidth, minimumWidth);
    if (isFramePending) return;

    isFramePending = true;
    requestAnimationFrame(applyWidth);
  };
  window.addEventListener("pointermove", resize);
  window.addEventListener("pointerup", stopResize);
}

["left", "right"].forEach((side) => setCollapsed(side, loadText(`collapsed_${side}`) === "1"));



// --- Eingabe ---

document.getElementById("new-chat").addEventListener("click", () => {
  chatId = null;
  hasRestoredChatDocuments = false;
  storeValue("chat_id", null);
  messageList.innerHTML = "";
  questionField.focus();
});

// Enter schickt ab, Shift+Enter macht einen Zeilenumbruch.
questionField.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    questionForm.requestSubmit();
  }
});

questionForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const question = questionField.value.trim();
  if (isBudgetExhausted()) {
    shake(sendButton);
    return;
  }
  if (!question) return;

  showMessage("nutzer", { text: question });
  questionField.value = "";
  isAnswering = true;
  updateSendButton();
  const answerElement = showMessage("assistent", null);
  const timer = startTimer(answerElement);

  try {
    const body = {
      frage: question,
      dokument_ids: [...selectedDocumentIds],
      chat_id: chatId,
      nutzer_id: userId,
    };
    const answer = await askQuestion(body, timer.setStatus);
    rememberChat(answer.chat_id, answer.nutzer_id);
    if (answer.tagesverbrauch) showDayTokens(answer.tagesverbrauch);
    showAnswer(answerElement, answer);
    fadeIn(answerElement);
  } catch (error) {
    answerElement.classList.add("error");
    answerElement.textContent = error.message === "429"
      ? "Das Tokenlimit ist erreicht. Um 24 Uhr geht es weiter."
      : "Die Antwort konnte nicht geladen werden.";
    if (error.message === "429") loadTokenUsage();
  } finally {
    timer.stop();
    isAnswering = false;
    updateSendButton();
    questionField.focus();
    messageList.scrollTop = messageList.scrollHeight;
  }
});

// Das Backend legt Chat und Nutzer bei der ersten Frage an
function rememberChat(newChatId, newUserId) {
  chatId = newChatId;
  userId = newUserId;
  storeValue("chat_id", chatId);
  storeValue("nutzer_id", userId);
}

// Drei Punkte, der aktuelle Status und nach einigen Sekunden die laufende Zeit, bis stop() sie beendet
function startTimer(element) {
  const startTime = Date.now();
  let status = DEFAULT_STATUS;
  const dots = document.createElement("span");
  dots.className = "typing";
  dots.innerHTML = "<i></i><i></i><i></i>";
  const label = createTextSpan("typing-time", "");
  element.replaceChildren(dots, label);

  const showElapsed = () => {
    const seconds = Math.floor((Date.now() - startTime) / 1000);
    const elapsed = seconds >= TIMER_DELAY_SECONDS ? ` ${seconds} s` : "";
    label.textContent = `${status} …${elapsed}`;
  };
  showElapsed();
  const interval = setInterval(showElapsed, TIMER_INTERVAL_MS);
  return {
    setStatus: (text) => { status = text; showElapsed(); },
    stop: () => clearInterval(interval),
  };
}



start();
