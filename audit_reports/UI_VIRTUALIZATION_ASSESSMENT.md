# UI-Virtualisierungs-Assessment — Prompt-Studio-Katalog & 70-Agenten-Liste

**Projekt:** Archon OS v0.5.7.6 · **Stand:** 24.11.2026
**Domäne:** Frontend / Rendering-Performance (Subagent, **read-only**)
**Vorgängerbefund:** `audit_reports/2026-11-24_d08_performance.md`, Befund 7 (Zeile 56) und Zeile 114
**Methode:** Shell war in dieser Session gesperrt (`Zugriff verweigert, os error 5` — bereits im D08-Bericht vermerkt). Alle Aussagen stammen aus direkt gelesenem Code (`read`/`grep`/`glob`). **Kein Code geändert, kein Commit erstellt.**

---

## 1. Scope

Geprüft wurden:

| Datei | Relevanz |
|---|---|
| `archon/routers/templates.py` (545 LOC) | Catalog-Endpoint, `_PROMPT_STUDIO_CACHE`, Filter/Suche |
| `static/js/prompt_studio.js` (~2.400 LOC) | **Renderer des 832-Katalogs** und des Fabric/5-Felder-Katalogs |
| `static/js/agent_profiles.js` (~2.000 LOC) | **Renderer der 70-Agenten-Liste** |
| `static/index.html` (13.790 LOC) | Skript-Ladeweise, Suchfeld, Karten-Container, Kategorie-Buttons |
| `static/vendor/lucide.min.js` | Nachweis des `createIcons()`-Verhaltens |
| `static/js/crm_studio.js:19,187-216` | Bestehendes Pagination-Pattern im selben Repo |
| `frontend/package.json`, `frontend/src/**` | Separater Next.js-App-Build — **kein** Build für `static/js` |
| `scripts/build_tailwind_css.mjs` | Nur CSS-Precompile, kein JS-Build |
| `tests/**`, `scripts/test_catalog_api.py`, `docs/system/smoke_test_results.json` | Test-Abdeckung und gemessene Payload-Größe |
| `prompt_studio_catalog.json`, `CHANGELOG.md:202` | Datenmenge |

Nicht geprüft (kein Bezug zur Aufgabe): Backend-Dispatch, SSE, SQLite-Pfade — dazu siehe D08.

---

## 2. Ist-Zustand: Renderpfad

### 2.1 Backend — Catalog-Endpoint

`archon/routers/templates.py:265-323`:

- `get_prompt_studio_catalog(category: Optional[str], q: Optional[str], lang: Query("de"))` (Zeile 266).
- Der Katalog wird **einmalig** in `_PROMPT_STUDIO_CACHE` geladen (Deklaration Zeile 42, Loader Zeilen 236-262). Kein wiederholtes Datei-I/O pro Request.
- Filter `category` (276-283) und Suche `q` (284-295) sind **serverseitig implementiert**, werden aber vom Prompt-Studio-Frontend **nicht benutzt**.
- Zeilen 297-315 bauen `summaries` für **alle** gefilterten Einträge; Zeilen 317-323 geben `total`, `count`, `categories`, `templates` zurück.
- **Es gibt keinen `limit`- und keinen `offset`-Parameter.** Die Antwort enthält immer das komplette Result-Set.

### 2.2 Frontend — 832-Katalog (der eigentliche Pfad)

`static/js/prompt_studio.js`:

1. `loadSurePromptsCatalog()` (470-560) holt bei jedem Öffnen des Modals
   `fetch("/api/templates/catalog?lang=…")` (Zeile 478) — **ohne `q`, ohne `category`, ohne `limit`** — parallel `/api/fabric/patterns` (479).
2. Die Fabric-Patterns werden clientseitig zuKatalog-Einträgen umgebaut (489-545) und mit den Katalog-Einträgen konkateniert: `currentSurePromptsCatalog = [...sureTemplates, ...fabricTemplates]` (Zeile 547).
3. `renderSurePromptsCards(search)` (582-650) ist der Renderer:
   - `wrapper.innerHTML = ""` (585) — **die gesamte Liste wird verworfen und neu aufgebaut**,
   - `currentSurePromptsCatalog.filter(...)` (587-607) — Filter + Suche **clientseitig**,
   - `filtered.forEach(t => { … })` (618) — **ein `document.createElement("div")` pro Treffer**,
   - `card.innerHTML = \`…\`` (629-646), `wrapper.appendChild(card)` (647),
   - `window.lucide.createIcons()` (649) — **global** über das ganze Dokument.

**Antwort auf Frage 1 (präzise):** Es ist *kein* einzelnes `innerHTML` mit einer konkatenierten Riesenzaichenkette, sondern `innerHTML=""` + eine Schleife mit `card.innerHTML` pro Datensatz und `appendChild`. Funktional ist das gleichwertig: **alle Datensätze werden in einem einzigen synchronen Durchgang zu DOM-Knoten**. Der zweite Renderer `renderPromptTemplateCards()` (164-224, Muster `filtered.forEach` bei 192, `createIcons()` bei 223) bedient das separate Fabric/5-Felder-Modal mit "~255 Mustern" (Kommentar Zeile 24, `static/index.html:11214`) und ist nachgelagert.

**Voll-Neuaufbau wird ausgelöst durch:**
- Modal öffnen: `openSurePromptsModal()` → `loadSurePromptsCatalog()` → Render (459, 551)
- Kategorie-Filter: `filterSurePrompts()` (561-577 → 577)
- **Jeden Tastendruck** in der Suche: `static/index.html:11223` `oninput="searchSurePrompts(this.value)"` → 579-580 → Render. **Kein Debounce** (im Gegensatz zur Agenten-Liste, siehe 2.3). D08 bestätigt das in Zeile 114.
- Favoriten-Toggle (426)
- **Jede Auswahl**: `selectSurePrompt()` ruft Zeile 653 erneut `renderSurePromptsCards(...)` auf.

### 2.3 Frontend — 70-Agenten-Liste (deutlich besser)

`static/js/agent_profiles.js:423-558` `renderHermesProfilesList()`:

- Ebenfalls `container.innerHTML = ""` (426) + `filtered.forEach(prof => …)` (479) + `card.innerHTML` (501/528) + `appendChild` (507/554) + `lucide.createIcons()` (557).
- **Aber:** die Menge ist ~70 statt ~1.087, die Suche ist mit **180 ms Debounce** gedrosselt (`_profileFilterTimer`, 559-565, aufgerufen via `onProfileSearchOrFilter()`), und es existiert ein kollabierter Icon-Rail-Modus (490-507), der pro Eintrag nur noch einen 44px-Avatar statt einer vollen Karte erzeugt. Das ist bereits eine manuelle, grobe DOM-Reduktion.

### 2.4 Einbindung & Build-Schritt

- `static/index.html:2160`: `<script src="/static/js/prompt_studio.js?v=2026111113"></script>` — **reines JS, ohne `defer`, ohne Bundler, ohne Build**. Änderung = Datei editieren + `?v=`-Cachebuster erhöhen.
- `frontend/package.json` beschreibt eine **getrennte Next.js-16/React-19-App** (`dev/build/start` auf Port 3005). Sie baut **nicht** `static/js/prompt_studio.js`. Ein Port nach React/Next ist kein „Umbau im gleichen Pfad", sondern eine zweite App.
- `scripts/build_tailwind_css.mjs` kompiliert ausschließlich `static/css/tailwind.generated.css` (Ausgabe Zeile 17/17-18, `fs.writeFileSync` 195-198). Es scannt `.js`-Dateien nur nach Klassennamen (Zeilen 33-68), übersetzt aber **kein JavaScript**. Neue Tailwind-Klassen würden einen CSS-Rebuild erfordern; Wiederverwendung vorhandener Klassen nicht.
- `static/index.html:13` lädt das vorkompilierte CSS; `prompt_studio.js` wird direkt ausgeliefert (D08, Zeile 113, bestätigt).

### 2.5 Tests

- **Keine Frontend-Unit-/E2E-Tests** für diese Renderer. Einziger JS-Test im Repo: `frontend/src/lib/sanitizeSvg.test.mjs`. Kein `playwright.config.*`, `vitest.config.*` oder `jest.config.*` vorhanden (außer den `package.json`).
- Python-Tests prüfen **Quelltext-Strings**, kein DOM-Verhalten:
  - `tests/test_block5_infra_frontend.py:75-79` — `prompt_studio.js` darf bestimmte Funktionen *nicht* enthalten, muss `loadVaultFiles` enthalten.
  - `tests/test_m31_global_english.py:104-122` — `/api/templates/catalog?lang=…` muss `templates[0]` mit `name_de`/`name_en` liefern und `categories` enthalten (Assert `total >= 824` in 110).
  - `tests/test_audit_p2_performance.py:22-27` — prüft `ORDER BY … LIMIT 5000` in anderen Modulen, **nicht** im Template-Endpoint.
  - `scripts/test_catalog_api.py:8-19` — gedruckte `TOTAL TEMPLATES IN CATALOG` und `templates[0]`.
- `docs/system/smoke_test_results.json:1681-1685`: `GET /api/templates/catalog` → 200, **46 ms, 385.397 Bytes**.

---

## 3. Engpass mit Zahlen

| Messgröße | Wert | Quelle |
|---|---|---|
| Katalog-Einträge | **832** (Aufgabenstellung; `CHANGELOG.md:202`) | `templates.py:267` Docstring, Test grenzt `>= 824` ab (`test_m31_global_english.py:110`) |
| Fabric-Patterns zusätzlich | **~255** | `prompt_studio.js:24`, `static/index.html:11214` |
| Effektiv gerenderte Karten | **~1.079–1.087** pro Render | `prompt_studio.js:396,547` |
| DOM-Knoten pro Karte | ~10–12 (div, 2 spans, button, `i`, h4, p …) | `prompt_studio.js:629-646` |
| DOM-Knoten gesamt | **~11.000–13.000** + SVG-Subknoten | berechnet aus 629-646 |
| `lucide.createIcons()` | `document.querySelectorAll('[data-lucide]')` + `replaceChild` **pro Icon** | `static/vendor/lucide.min.js:8-11` |
| SVG-Ersetzungen pro Render | **~1.080** (`star`-Icon je Karte, Zeile 641) | `prompt_studio.js:641,649` |
| HTTP-Payload pro Modal-Öffnen | **385 KB / 46 ms** (Server) | `docs/system/smoke_test_results.json:1681-1685` |
| Rebuilds bei 10-Zeichen-Suche | **10 vollständige Rebuilds** (kein Debounce) | `static/index.html:11223` + `prompt_studio.js:579-580` |
| Agenten-Liste | ~70 Karten, **180 ms Debounce**, Rail-Modus | `agent_profiles.js:479,559-565,490-507` |

**Bewertung:** Der Engpass ist **Client-seitiges DOM + Icon-Austausch**, nicht das Backend. Der Cache (`_PROMPT_STUDIO_CACHE`) verhindert wiederholtes Datei-I/O; die 46 ms Serverzeit und 385 KB Transfer sind einmalig pro Öffnen. Die teure Arbeit passiert danach im Browser: ~1.080 `innerHTML`-Karten + ~1.080 `replaceChild`-Operationen, bei jedem Tastendruck erneut. Der ~92%-Anteil der DOM-Arbeit entfällt auf den Katalog, nicht auf die 70 Agenten (≈6% der Kartenmenge, zusätzlich gedrosselt).

---

## 4. Optionen — Aufwand & Risiko

### Option A — „Mehr laden" clientseitig (minimal, empfohlen)

`filtered.slice(0, spVisibleCount)` in `renderSurePromptsCards` (Zeile 618) + Button, der den Zähler um 60 erhöht und neu rendert. Daten bleiben komplett im Speicher; Filter/Suche laufen weiter clientseitig.

- **Aufwand: ~1,5–2 h** (eine JS-Datei, ~15 Zeilen, `?v=`-Bump in `index.html`; kein Build).
- **Risiko: niedrig.**
- **Kaputtgehen kann:** Auswahl-Highlight (Zeile 653 rendert neu → `visibleCount` muss erhalten bleiben); Favoriten-Toggle (426); Zähleranzeige (608-609 muss `filtered.length`, nicht `visibleCount` zeigen); Fabric-Filterzweig (591-592); Erstauswahl (552-553). Die *Daten*-Suche bei `selectSurePrompt` nutzt `currentSurePromptsCatalog.find(...)` (660), nicht den DOM — das bleibt sicher. Scroll-Position wird heute schon bei jedem Render zurückgesetzt; das ändert sich nicht.

### Option B — Nur Debounce der Suche

Spiegelung von `onProfileSearchOrFilter` (`agent_profiles.js:559-565`) als `onSurePromptSearchOrFilter`, Aufruf in `static/index.html:11223` umstellen.

- **Aufwand: ~0,5 h. Risiko: sehr niedrig.**
- **Wirkung:** 10 Tastendrücke → 1 Render. **Allein nicht ausreichend**, weil das Öffnen des Modals weiterhin ~1.080 Karten erzeugt. Als Teil des Minimal-Plans sinnvoll.

### Option C — Serverseitige Pagination (`limit`/`offset`/`q`) im Endpoint

Neue Query-Parameter in `templates.py:266`, Slicing vor `summaries` (298-315), Rückgabe von `next_offset`; Frontend holt bei Suche `?q=…&limit=…` und hängt bei „Mehr laden" an. Bestehendes Muster: `crm_studio.js:19,187-216` (`pageSize=50`, `limit`, `renderPagination`).

- **Aufwand: ~3–4 h** (Backend + Frontend + Tests).
- **Risiko: mittel.**
- **Kaputtgehen kann:** `test_m31_global_english.py:110-122` (erster Eintrag muss erhalten bleiben — bei Default-`limit` erfüllbar); `total`-Semantik für `scripts/test_catalog_api.py:13`; OpenAPI-Parity-Baselines `scripts/parity_baselines/openapi_baseline_2026-11-0*.json:277` (Signaturänderung kann Diff auslösen); der „Favoriten"-Filter (`prompt_studio.js:589-590`) liegt nur in `localStorage` und **kann nicht** serverseitig gefiltert werden → Hybrid-Logik nötig; Fabric-Patterns werden clientseitig gemergt (547), d. h. `total`/`count` des Servers decken sich nicht mehr mit dem Badge (549, 608-609).

### Option D — Echtes Windowing / Virtual Scroller

Feste Zeilenhöhen, absolute Positionierung, Scroll-Handler, Platzhalter für variable Kartenhöhen; ggf. `react-window` im Next.js-App-Kontext.

- **Aufwand: ~8–24 h (1–3 Tage). Risiko: hoch.**
- **Kaputtgehen kann:** `line-clamp-2`-Beschreibungen (645) haben variable Höhe → Offset-Berechnung; `selectSurePrompt` (653) rendert die Liste neu und setzt den Highlight über den DOM; globales `lucide.createIcons()` (649) scannt den ganzen Container; der scrollbare Container `static/index.html:11394` (`overflow-y-auto`) bräuchte Spacer-Logik; Tastaturfokus, Scroll-zu-Auswahl, i18n-Klassen und der CSS-Build (`build_tailwind_css.mjs`) sind zusätzliche Risiken. **Es gibt kein Frontend-Testnetz, das solche Regressionen auffängt** (siehe 2.5). Ein Port nach React/Next ist zusätzlich ein Architekturbruch, weil `frontend/` und `static/` zwei getrennte Apps sind.

### Vergleich

| Option | Aufwand | Risiko | Rendert Zeit? | Empfehlung |
|---|---|---|---|---|
| A Mehr laden (client) | 1,5–2 h | niedrig | ja (~60 statt ~1.080) | **Ja** |
| B Debounce | 0,5 h | sehr niedrig | ja (nur Tastatureingaben) | **Ja, als Zusatz** |
| C Server-Pagination | 3–4 h | mittel | ja | optional, später |
| D Virtualisierung | 8–24 h | hoch | ja | **Nein** |

---

## 5. Empfehlung (Antwort auf Frage 5)

**Keine Virtualisierung.** Der Aufwand ist derzeit **nicht gerechtfertigt**: 1.087 Einträge sind eine Größenordnung, die ein simpler Batch-Render souverän bewältigt, während Virtualisierung hier genau die Stellen trifft, die am empfindlichsten sind (DOM-basierter Highlight, globaler Icon-Austausch, fehlende Frontend-Tests, getrennte App-Architektur).

Für die Frage „reicht `LIMIT` im Endpoint + Mehr-laden-Button?": **Der Button ist der entscheidende Teil, `LIMIT` allein reicht nicht.** Solange der Frontend alle Einträge lädt und `filtered.forEach` über alles laufen lässt (618), hilft ein serverseitiges `LIMIT` gar nichts — im Gegenteil: es würde den Fabric-Merge, den Favoriten-Filter und den clientseitigen Count-Bezug brechen (siehe Option C). Empfohlen wird daher: **A + B jetzt**, `limit`/`offset` im Endpoint **optional und rückwärtskompatibel** (Default = alle) als spätere Skalierungsoption, aber nicht als Voraussetzung.

Für die **70-Agenten-Liste: gar nichts ändern.** Sie hat bereits 180 ms Debounce und einen kollabierten Icon-Rail; ein Virtualisierungs-Eingriff dort würde mehr Risiko als Nutzen bringen.

**Nachschärfen erst wenn:** gemessene Renderzeit nach A+B weiterhin >200 ms liegt oder die Datenmenge >5.000 Einträge steigt. Dann Option D mit eigenem Test-Harness neu bewerten.

---

## 6. Minimal-Plan (Reihenfolge, ~2 h)

1. **`static/js/prompt_studio.js`** — bei Zeile 398 (`let currentSurePromptsCatalog = []`) `let spVisibleCount = 60;` ergänzen. In `renderSurePromptsCards()` (582) Zeile 618 ändern nach `filtered.slice(0, spVisibleCount).forEach(...)`. Nach Zeile 648 einen „Mehr laden (N verbleibend)"-Button erzeugen, der `spVisibleCount += 60` und `renderSurePromptsCards(currentSuchwert)` aufruft. `spVisibleCount = 60` zurücksetzen in `filterSurePrompts()` (561) und beim Such-Input. Zähler (608-609) bleibt bei `filtered.length`. **Keine neuen Tailwind-Klassen** verwenden (sonst `node scripts/build_tailwind_css.mjs` nötig).
2. **`static/js/prompt_studio.js`** — Debounce-Helfer analog `agent_profiles.js:559-565` (`clearTimeout`/`setTimeout(..., 180)`) ergänzen; **`static/index.html:11223`** von `oninput="searchSurePrompts(this.value)"` auf den gedebouncsten Helfer umstellen. `searchSurePrompts()` selbst unverändert lassen.
3. **`static/index.html:2160`** — Cachebuster erhöhen: `?v=2026111113` → `?v=20261124a`. Kein Build-Schritt für JS; kein `defer` nötig (Funktionen werden per `oninput`/`onclick` global aufgerufen).
4. **Optional, nicht im Minimal-Plan:** `archon/routers/templates.py:266` `limit`/`offset` als `Optional[int] = Query(None)` ergänzen und vor Zeile 298 slicen; `total` und `templates[0]`-Reihenfolge beibehalten, damit `test_m31_global_english.py:104-122` und `scripts/test_catalog_api.py` grün bleiben.
5. **Verifikation:** `pytest tests/test_m31_global_english.py tests/test_block5_infra_frontend.py tests/test_audit_p2_performance.py`; manuell im Browser: Modal öffnen → 10 Zeichen tippen → Favorit umschalten → Kategorie wechseln → Eintrag jenseits der ersten 60 per „Mehr laden" auswählen. Da keine DOM-Tests existieren, ggf. eine kleine Quelltext-Assertion im Stil von `test_block5_infra_frontend.py:75-79` ergänzen (z. B. `assert "spVisibleCount" in ps`).

---

**Gesamturteil:** Aufwand für echte Virtualisierung ~1–3 Tage bei **hohem** UI-Risiko und ohne Testnetz — nicht gerechtfertigt. Minimalmaßnahme ~2 h bei **niedrigem** Risiko bringt den Großteil des Effekts.
