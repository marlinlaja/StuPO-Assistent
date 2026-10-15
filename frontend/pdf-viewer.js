// Klassischer PDF-Viewer mit PDF.js: Zoom, Textsuche (Strg+F) und Seitenzahl-Eingabe.
// app.js ruft nur openPdf(url, seite, markierungen, art) auf.

// --- Konstanten ---

const PDFJS_WORKER_URL = "https://cdn.jsdelivr.net/npm/pdfjs-dist@3.11.174/build/pdf.worker.min.js";
const ZOOM_STEP = 1.15;
const MIN_ZOOM = 0.25;
const MAX_ZOOM = 5;
const FIT_WIDTH = "page-width";
const MAX_ANIMATED_HIGHLIGHTS = 12;
const HIGHLIGHT_SCROLL_MARGIN = 90;
// Markierungen sind etwas größer als der Text (in PDF-Punkten, wächst mit dem Zoom)
const HIGHLIGHT_PADDING_X = 3;
const HIGHLIGHT_PADDING_Y = 1;
const NOT_FOUND_STATE = 1;
// Mehr PDFs hält der Browser nicht vor; eine PDF ist bis zu einigen MB groß
const MAX_PRELOADED_PDFS = 8;

pdfjsLib.GlobalWorkerOptions.workerSrc = PDFJS_WORKER_URL;



// --- Elemente und Zustand ---

const pdfPanel = document.getElementById("pdf-viewer");
const pdfContainer = document.getElementById("pdf-container");
const pdfPages = document.getElementById("pdf-pages");
const zoomLabel = document.getElementById("pdf-zoom-label");
const pageInput = document.getElementById("pdf-page-input");
const pageCount = document.getElementById("pdf-page-count");
const searchInput = document.getElementById("pdf-search");
const searchCount = document.getElementById("pdf-search-count");

const eventBus = new pdfjsViewer.EventBus();
const linkService = new pdfjsViewer.PDFLinkService({ eventBus });
const findController = new pdfjsViewer.PDFFindController({ eventBus, linkService });
const pdfPageViewer = new pdfjsViewer.PDFViewer({
  container: pdfContainer,
  viewer: pdfPages,
  eventBus,
  linkService,
  findController,
  // Ohne Editor für Anmerkungen: PDF.js wirft sonst beim Wechsel auf ein anderes Dokument einen Fehler
  annotationEditorMode: pdfjsLib.AnnotationEditorType.DISABLE,
});
linkService.setViewer(pdfPageViewer);

let loadedUrl = null;
let pendingPage = 1;
// 1 = 100 %: die Seite füllt genau die Breite des Viewers, auch wenn die Spalte verschoben wird
let zoomFactor = 1;
let lastContainerWidth = 0;
// Markierungen eines Zitats: [{seite, x0, y0, x1, y1, breite, hoehe}] in PDF-Punkten
let highlights = [];
// Art des Belegs, bestimmt die Farbe der Markierungen
let highlightKind = "belegt";



// --- Vorladen ---

// Die PDFs der Dokumente im Kontext: Adresse -> Download (läuft noch oder fertig, mit den Bytes oder null bei Fehler)
const preloadedPdfs = new Map();

// Lädt die PDFs dieser Adressen im Hintergrund und gibt die anderen frei (außer der gerade geöffneten).
function keepPdfsPreloaded(urls) {
  const wanted = urls.slice(0, MAX_PRELOADED_PDFS);
  for (const url of preloadedPdfs.keys()) {
    if (!wanted.includes(url) && url !== loadedUrl) preloadedPdfs.delete(url);
  }
  wanted.filter((url) => !preloadedPdfs.has(url)).forEach((url) => preloadedPdfs.set(url, downloadPdf(url)));
}

async function downloadPdf(url) {
  try {
    const response = await fetch(url, { priority: "low" });
    if (!response.ok) throw new Error(response.status);
    return new Uint8Array(await response.arrayBuffer());
  } catch (error) {
    preloadedPdfs.delete(url);
    return null;
  }
}

// Mit vorgeladenen Bytes (eine Kopie, PDF.js übernimmt sie) oder, ohne sie, mit der Adresse selbst
async function pdfSource(url) {
  const bytes = preloadedPdfs.has(url) ? await preloadedPdfs.get(url) : null;
  return bytes ? { data: bytes.slice() } : url;
}



// --- Öffnen ---

// Dasselbe PDF wird nicht neu geladen, es springt nur auf die Seite und setzt die Markierungen neu.
async function openPdf(url, page = 1, newHighlights = [], kind = "belegt") {
  pdfPanel.hidden = false;
  highlights = newHighlights;
  highlightKind = kind;
  if (url === loadedUrl) {
    pdfPageViewer.currentPageNumber = page;
    showHighlights();
    return;
  }

  loadedUrl = url;
  pendingPage = page;
  clearSearch();
  showLoading();

  try {
    const pdf = await pdfjsLib.getDocument(await pdfSource(url)).promise;
    if (url !== loadedUrl) return;

    pdfPageViewer.setDocument(pdf);
    linkService.setDocument(pdf, null);
    pageCount.textContent = pdf.numPages;
    pageInput.max = pdf.numPages;
  } catch (error) {
    loadedUrl = null;
    pdfPanel.hidden = true;
    pdfPanel.classList.remove("is-loading");
    throw error;
  }
}

// Das alte PDF verschwindet sofort, statt dessen dreht sich ein kleines Symbol, bis die erste Seite gezeichnet ist
function showLoading() {
  pdfPanel.classList.add("is-loading");
  pageCount.textContent = "–";
}

eventBus.on("pagerendered", () => pdfPanel.classList.remove("is-loading"));

eventBus.on("pagesinit", () => {
  applyZoom();
  pdfPageViewer.currentPageNumber = pendingPage;
  showHighlights();
});



// --- Markierungen ---

// Die Markierungen liegen als eigene Boxen über der Seite (in Prozent, so folgen sie jedem Zoom). PDF.js
// entfernt sie beim Neuzeichnen einer Seite, deshalb kommen sie nach "pagerendered" wieder.
function drawHighlights(pageNumber) {
  const pageElement = pdfPageViewer.getPageView(pageNumber - 1)?.div;
  if (!pageElement) return;

  pageElement.querySelector(".citation-highlights")?.remove();
  const pageHighlights = highlights.filter((highlight) => highlight.seite === pageNumber);
  if (pageHighlights.length === 0) return;

  const layer = document.createElement("div");
  layer.className = "citation-highlights";
  layer.dataset.kind = highlightKind;
  pageHighlights.forEach((highlight, index) => layer.appendChild(createHighlightBox(highlight, index)));
  pageElement.appendChild(layer);
}

function createHighlightBox(highlight, index) {
  const left = Math.max(0, highlight.x0 - HIGHLIGHT_PADDING_X);
  const right = Math.min(highlight.breite, highlight.x1 + HIGHLIGHT_PADDING_X);
  const top = Math.max(0, highlight.y0 - HIGHLIGHT_PADDING_Y);
  const bottom = Math.min(highlight.hoehe, highlight.y1 + HIGHLIGHT_PADDING_Y);

  const box = document.createElement("div");
  box.className = "citation-highlight";
  box.style.left = `${(left / highlight.breite) * 100}%`;
  box.style.top = `${(top / highlight.hoehe) * 100}%`;
  box.style.width = `${((right - left) / highlight.breite) * 100}%`;
  box.style.height = `${((bottom - top) / highlight.hoehe) * 100}%`;
  box.style.setProperty("--order", Math.min(index, MAX_ANIMATED_HIGHLIGHTS));
  return box;
}

function showHighlights() {
  for (let pageNumber = 1; pageNumber <= pdfPageViewer.pagesCount; pageNumber++) drawHighlights(pageNumber);
  scrollToFirstHighlight();
}

// Springt so, dass die oberste Markierung etwas unter dem oberen Rand steht
function scrollToFirstHighlight() {
  const first = [...highlights].sort((a, b) => a.seite - b.seite || a.y0 - b.y0)[0];
  const pageElement = first && pdfPageViewer.getPageView(first.seite - 1)?.div;
  if (!pageElement) return;

  const top = pageElement.offsetTop + (first.y0 / first.hoehe) * pageElement.clientHeight;
  pdfContainer.scrollTo({ top: top - HIGHLIGHT_SCROLL_MARGIN, behavior: "smooth" });
}

eventBus.on("pagerendered", ({ pageNumber }) => drawHighlights(pageNumber));



// --- Zoom ---

// Der Zoom ist immer relativ zur Breite des Viewers: erst "Breite anpassen", dann der Faktor darauf.
function applyZoom() {
  pdfPageViewer.currentScaleValue = FIT_WIDTH;
  pdfPageViewer.currentScale = pdfPageViewer.currentScale * zoomFactor;
  zoomLabel.textContent = `${Math.round(zoomFactor * 100)} %`;
}

function zoomBy(factor) {
  zoomFactor = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoomFactor * factor));
  applyZoom();
}

document.getElementById("pdf-page-previous").addEventListener("click", () => pdfPageViewer.previousPage());
document.getElementById("pdf-page-next").addEventListener("click", () => pdfPageViewer.nextPage());
document.getElementById("pdf-zoom-in").addEventListener("click", () => zoomBy(ZOOM_STEP));
document.getElementById("pdf-zoom-out").addEventListener("click", () => zoomBy(1 / ZOOM_STEP));
zoomLabel.addEventListener("click", () => {
  zoomFactor = 1;
  applyZoom();
});

// Strg + Mausrad (und Pinch auf dem Trackpad) zoomt statt zu scrollen
pdfContainer.addEventListener("wheel", (event) => {
  if (!event.ctrlKey) return;

  event.preventDefault();
  zoomBy(event.deltaY < 0 ? ZOOM_STEP : 1 / ZOOM_STEP);
}, { passive: false });

// Ändert sich die Breite des Viewers, folgt die Seite mit demselben Faktor.
new ResizeObserver(() => {
  const width = pdfContainer.clientWidth;
  if (!pdfPageViewer.pagesCount || width === lastContainerWidth) return;

  lastContainerWidth = width;
  applyZoom();
}).observe(pdfContainer);



// --- Seitenzahl ---

// Das Feld ist so breit wie die Ziffern der Seitenzahl, damit auch dreistellige Seiten nicht abgeschnitten werden
function showPageNumber(pageNumber) {
  pageInput.value = pageNumber;
  pageInput.style.setProperty("--digits", String(pageNumber).length);
}

eventBus.on("pagechanging", ({ pageNumber }) => showPageNumber(pageNumber));

pageInput.addEventListener("change", () => {
  const page = Math.round(Number(pageInput.value));
  const clampedPage = Math.min(pdfPageViewer.pagesCount, Math.max(1, page || 1));
  pdfPageViewer.currentPageNumber = clampedPage;
  showPageNumber(clampedPage);
});

pageInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") pageInput.blur();
});



// --- Suche ---

function search({ again = false, backwards = false } = {}) {
  eventBus.dispatch("find", {
    source: searchInput,
    type: again ? "again" : "",
    query: searchInput.value,
    caseSensitive: false,
    entireWord: false,
    highlightAll: true,
    findPrevious: backwards,
    matchDiacritics: true,
  });
}

function clearSearch() {
  searchInput.value = "";
  searchCount.textContent = "";
}

function showMatchCount({ current, total }, state) {
  if (!searchInput.value) {
    searchCount.textContent = "";
  } else if (state === NOT_FOUND_STATE || total === 0) {
    searchCount.textContent = "nicht gefunden";
  } else {
    searchCount.textContent = `${current} / ${total}`;
  }
}

eventBus.on("updatefindmatchescount", ({ matchesCount }) => showMatchCount(matchesCount));
eventBus.on("updatefindcontrolstate", ({ matchesCount, state }) => showMatchCount(matchesCount, state));

searchInput.addEventListener("input", () => search());
searchInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    search({ again: true, backwards: event.shiftKey });
  }
  if (event.key === "Escape") {
    clearSearch();
    search();
    searchInput.blur();
  }
});

document.getElementById("pdf-search-next").addEventListener("click", () => search({ again: true }));
document.getElementById("pdf-search-previous").addEventListener("click", () => search({ again: true, backwards: true }));

// Die Suche ist ein Lupen-Knopf, der das Feld aufklappt; leer und ohne Fokus klappt es wieder zu.
const searchGroup = document.querySelector(".pdf-search-group");

function openSearch() {
  searchGroup.classList.add("open");
  searchInput.focus();
  searchInput.select();
}

// Die Lupe schaltet um: Ein zweiter Klick schließt die Suche. Der Klick nimmt dem Feld erst den Fokus (und klappt es
// zu, wenn es leer ist), darum merkt sich mousedown, ob die Suche vorher offen war.
const searchToggle = document.getElementById("pdf-search-toggle");
let wasSearchOpen = false;

function closeSearch() {
  clearSearch();
  search();
  searchGroup.classList.remove("open");
}

searchToggle.addEventListener("mousedown", () => {
  wasSearchOpen = searchGroup.classList.contains("open");
});

searchToggle.addEventListener("click", () => {
  if (wasSearchOpen) closeSearch();
  else openSearch();
  wasSearchOpen = false;
});

searchInput.addEventListener("blur", () => {
  if (!searchInput.value) searchGroup.classList.remove("open");
});

// Strg+F (bzw. Cmd+F) sucht im PDF, solange der Cursor nicht im Chat steht
document.addEventListener("keydown", (event) => {
  const isFind = (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "f";
  if (!isFind || pdfPanel.hidden) return;
  if (document.querySelector(".chat").contains(document.activeElement)) return;

  event.preventDefault();
  openSearch();
});
