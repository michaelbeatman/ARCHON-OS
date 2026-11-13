"""Katalog-Parität, Anker-Auflösung und Schema-Konformität der 9 Locale-Dateien.

Prüft:
(a) alle Locale-Dateien tragen dieselbe Menge an Katalog-Nachrichten,
(b) jeder ``data-i18n*``-Anker im aktiven HTML löst in der Referenzsprache ``de`` auf,
(c) kein Katalogwert ist leer.
"""

from __future__ import annotations

import json
import pathlib
import re
from html.parser import HTMLParser

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
LOCALES_DIR = REPO_ROOT / "static" / "locales"
SCHEMA_PATH = LOCALES_DIR / "schema.json"
GLOSSARY_PATH = REPO_ROOT / "docs" / "I18N_GLOSSAR.json"
REFERENCE_LANG = "de"
LANGUAGES = ("de", "en", "es", "fr", "ja", "ko", "pt", "ru", "zh")

# CLDR-Pluralkategorien: ein Nachrichtenwert darf statt eines Strings ein Objekt
# aus genau diesen Kategorien sein (Reservierung, siehe static/locales/schema.json).
PLURAL_CATEGORIES = frozenset({"one", "few", "many", "other"})

I18N_ANCHOR_RE = re.compile(r'data-i18n(?:-title|-placeholder)?="([^"]+)"')

ACTIVE_HTML = (
    "static/index.html",
    "static/mobile.html",
    "static/hermes-hud/index.html",
    "static/views/system_settings_modal.html",
)


def locale_files() -> list[pathlib.Path]:
    return [LOCALES_DIR / f"{lang}.json" for lang in LANGUAGES]


def load_catalog(path: pathlib.Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def collect_messages(node, prefix=()):
    """Liefert {dotted_path: value} für alle Katalog-Nachrichten.

    Ein Plural-Objekt (Schlüssel ⊆ PLURAL_CATEGORIES) zählt als *eine* Nachricht,
    damit Sprachen mit weniger Pluralformen (ja/ko/zh) die Parität nicht brechen.
    """
    messages = {}
    if isinstance(node, dict):
        if prefix and node and set(node).issubset(PLURAL_CATEGORIES):
            messages[".".join(prefix)] = node
            return messages
        for key, value in node.items():
            messages.update(collect_messages(value, prefix + (key,)))
    else:
        messages[".".join(prefix)] = node
    return messages


def resolve(catalog: dict, dotted_key: str):
    current = catalog
    for part in dotted_key.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def html_anchor_files() -> list[pathlib.Path]:
    files = [REPO_ROOT / rel for rel in ACTIVE_HTML]
    files.extend(sorted((REPO_ROOT / "static" / "views").glob("*.html")))
    return files


def test_all_locales_have_identical_message_sets():
    reference = set(collect_messages(load_catalog(LOCALES_DIR / f"{REFERENCE_LANG}.json")))
    assert reference, "Referenzkatalog de.json ist leer"

    problems = []
    for path in locale_files():
        keys = set(collect_messages(load_catalog(path)))
        missing = sorted(reference - keys)
        extra = sorted(keys - reference)
        if missing:
            problems.append(f"{path.name}: fehlt {missing}")
        if extra:
            problems.append(f"{path.name}: überzählig {extra}")

    assert not problems, "Locale-Kataloge weichen voneinander ab:\n" + "\n".join(problems)


def test_all_html_anchors_resolve_in_reference_language():
    reference = load_catalog(LOCALES_DIR / f"{REFERENCE_LANG}.json")

    anchors = []
    for path in html_anchor_files():
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            for key in I18N_ANCHOR_RE.findall(line):
                anchors.append((path.relative_to(REPO_ROOT).as_posix(), lineno, key))

    assert len(anchors) >= 25, f"nur {len(anchors)} i18n-Anker gefunden, erwartet >= 25"

    unresolved = []
    for rel_path, lineno, key in anchors:
        value = resolve(reference, key)
        if not isinstance(value, str) or not value.strip():
            unresolved.append(f"{rel_path}:{lineno} -> {key}")

    unique_missing = sorted({entry.split("-> ")[1] for entry in unresolved})
    assert not unresolved, (
        f"{len(unresolved)} Anker ohne Auflösung in {REFERENCE_LANG}: "
        f"{unique_missing}\n" + "\n".join(unresolved)
    )


def test_no_empty_catalog_values():
    problems = []
    for path in locale_files():
        for key, value in collect_messages(load_catalog(path)).items():
            if isinstance(value, dict):
                for category, text in value.items():
                    if not isinstance(text, str) or not text.strip():
                        problems.append(f"{path.name}: {key}.{category} leer")
            elif not isinstance(value, str):
                problems.append(f"{path.name}: {key} ist {type(value).__name__}, nicht String")
            elif not value.strip():
                problems.append(f"{path.name}: {key} leer")

    assert not problems, "Leere oder ungültige Katalogwerte:\n" + "\n".join(problems)


# --- (c2) Vollstaendige Annotation der Gruppe-1-Regionen --------------------
#
# Die drei Regionen Sidebar, Topbar und Drawer in static/index.html muessen
# vollstaendig annotiert sein: jeder Textknoten mit mindestens einem Buchstaben
# braucht einen data-i18n*-Anker am eigenen oder einem umschliessenden Element.
# Ausnahmen sind ausschliesslich die unten begruendeten, nicht uebersetzbaren
# Knoten (Produktname, Badge, Initial, Laufzeitwerte aus JS).

INDEX_HTML = REPO_ROOT / "static" / "index.html"

GROUP1_REGIONS = (
    ("sidebar", '<aside class="flex-shrink-0 flex flex-col border-r h-full'),
    ("topbar", '<div id="main-topbar"'),
    ("drawer", '<div id="galaxy-node-drawer"'),
)

GROUP1_EXCEPTIONS = {
    # Sidebar
    "ARCHON OS": "Produktname (Wortmarke im Logo-Header)",
    "alpha": "Release-Badge der Wirtschaft-Sektion",
    "KILL-SWITCH AKT...": "dynamischer Zustandstext, kommt aus JS",
    "1 Vorfall: telegram_bot ge...": "dynamischer Text mit Laufzeitdaten",
    "-- ms": "dynamischer Messwert der Telemetrie",
    "Healthy": "Live-Status, kommt aus JS (health-overall-text)",
    "H": "Avatar-/Initial-Kuerzel des Hermes-Dashboards",
    # Topbar
    # (keine: ACTIVE/LIGHT/CSS LIVE STUDIO/RADAR/SETTINGS sind Beschriftungen)
    # Drawer
    # (keine: NODE und Knoten-Details sind Beschriftungen)
}

_VOID_TAGS = frozenset(
    {"img", "br", "hr", "input", "meta", "link", "source", "area", "base",
     "col", "embed", "param", "track", "wbr"}
)


class _Scanner(HTMLParser):
    """Sammelt Textknoten mit Buchstaben samt Anker-Status innerhalb einer Region."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags: list[str] = []
        self.attrs: list[dict] = []
        self.total = 0
        self.open_nodes: list[tuple[str, str]] = []

    def handle_starttag(self, tag, attrs):
        if tag in _VOID_TAGS:
            return
        self.tags.append(tag)
        self.attrs.append(dict(attrs))

    def handle_endtag(self, tag):
        if tag in _VOID_TAGS:
            return
        for index in range(len(self.tags) - 1, -1, -1):
            if self.tags[index] == tag:
                del self.tags[index:]
                del self.attrs[index:]
                return

    def handle_data(self, data):
        if not any(char.isalpha() for char in data):
            return
        self.total += 1
        anchored = any(
            name.startswith("data-i18n") for attrs in self.attrs for name in attrs
        )
        if not anchored:
            self.open_nodes.append((self.tags[-1] if self.tags else "?", " ".join(data.split())))


def _region_bounds(lines: list[str], marker: str) -> tuple[int, int]:
    """Zeilenbereich (1-basiert, inklusiv) des Elements, das ``marker`` enthaelt."""
    start = next((i for i, line in enumerate(lines) if marker in line), None)
    assert start is not None, f"Region nicht gefunden: {marker}"

    counter = _Scanner()
    counter.feed(lines[start])
    end = start
    while counter.tags:
        end += 1
        counter.feed(lines[end])
    return start + 1, end + 1


def _scan_group1_regions() -> dict[str, _Scanner]:
    lines = INDEX_HTML.read_text(encoding="utf-8").split("\n")
    scanners = {}
    for name, marker in GROUP1_REGIONS:
        first, last = _region_bounds(lines, marker)
        scanner = _Scanner()
        scanner.feed("\n".join(lines[first - 1 : last]))
        scanners[name] = scanner
    return scanners


def test_sidebar_region_fully_annotated():
    scanners = _scan_group1_regions()

    unexpected: list[str] = []
    for name, scanner in scanners.items():
        assert scanner.total > 0, f"Region {name} ohne Textknoten - falsch isoliert"
        for tag, text in scanner.open_nodes:
            if text in GROUP1_EXCEPTIONS:
                continue
            unexpected.append(f"{name}: <{tag}> {text!r}")

    assert not unexpected, (
        f"{len(unexpected)} Textknoten ohne data-i18n*-Anker in Gruppe 1:\n"
        + "\n".join(f"  {entry}" for entry in unexpected)
    )


# --- (c3) Vollstaendige Annotation des System-Settings-Modals ----------------
#
# Messquelle ist der Scanner ``scripts/i18n_scan_textnodes.py`` (dieselbe
# Anker-Semantik wie ``static/js/archon_i18n.js``). Fuer das Modal gilt:
# jeder Textknoten mit Buchstaben braucht einen ``data-i18n*``-Anker am eigenen
# oder einem umschliessenden Element; offen bleiben nur die unten begruendeten
# Knoten.
#
# Etappe 3 wurde in Gruppen geliefert. ``SETTINGS_MODAL_DONE`` sind die Tabs,
# die bereits vollstaendig annotiert sind, ``SETTINGS_MODAL_PENDING`` die noch
# offenen Tranchen. Der Test verlangt 0 offene Knoten in allen DONE-Tabs;
# ein Tab, der in keiner der beiden Mengen steht, laesst den Test scheitern,
# damit kein Bereich stillschweigend ungeprueft bleibt.

SETTINGS_MODAL = REPO_ROOT / "static" / "views" / "system_settings_modal.html"
SCANNER_PATH = REPO_ROOT / "scripts" / "i18n_scan_textnodes.py"

SETTINGS_MODAL_DONE = frozenset({
    "general", "search", "users", "keys", "update", "routing",
    "services", "frameworks", "comm", "kernel", "autonomy", "design", "plugins",
})

SETTINGS_MODAL_PENDING = frozenset()

# Nicht uebersetzbare Knoten: Laufzeitwerte aus JS/Backend, technische
# Identifier und Einheiten. Textgleichheit ist hier eindeutig genug.
SETTINGS_MODAL_EXCEPTIONS = {
    # Laufzeitwerte, die static/js/*.js in den Knoten schreibt
    "0 Treffer": "Zaehler der Live-Suche, settings_search.js",
    "Einzelplatz (Keine Anmeldung nötig)": "Zustandstext, auth_manager.js",
    "Multi-User aktivieren": "Zustandstext, auth_manager.js",
    "0 Keys": "Zaehler der Key-Tabelle, system_settings.js",
    "Lade...": "Versionsnummer aus dem Backend",
    "Wird geprüft...": "Update-Status aus JS",
    "main (GitHub)": "Branch/Remote aus dem Backend",
    "Neue Commits verfügbar": "von JS gesetzter Titel des Incoming-Banners",
    "Authentifizierung fehlgeschlagen: Private Repositories erfordern ein GITHUB_TOKEN in der .env-Datei auf dem Server.":
        "Fehlertext aus JS mit Laufzeitkontext",
    "👑 Admin (Master: Push autorisiert)": "Rollenlabel aus data.auth.role_label",
    "Bereit": "Push-Status aus JS",
    "Release": "JS schreibt das Button-Label per innerHTML neu",
    "v0.5.2": "Dynamischer Versions-Schritt im Release-Button, aus JS",
    "zu GitHub pushen": "JS schreibt das Button-Label per innerHTML neu",
    "0 Dateien": "Zaehler des Git-Status-Dialogs, JS",
    "NICHT GETESTET": "OmniRoute-Status aus JS",
    "Wird geladen...": "SMTP-Status aus JS",
    # Technische Identifier (Glossar: bleibt unuebersetzt)
    "Scope: read_only": "Scope-Identifier",
    "Scope: kanban_rw": "Scope-Identifier",
    "Scope: agent_execute": "Scope-Identifier",
    "Scope: admin_full": "Scope-Identifier",
    "read_only": "Scope-Identifier",
    "kanban_rw": "Scope-Identifier",
    "agent_execute": "Scope-Identifier",
    "admin_full": "Scope-Identifier",
    "MCP Tool: 'mcp__n8n__trigger_workflow'": "Tool-Identifier",
    # Einheiten, Ports, Beispielwerte
    "LOW": "Kostenstufen-Kennung (Routing-Tier)",
    "MEDIUM": "Kostenstufen-Kennung (Routing-Tier)",
    "HIGH": "Kostenstufen-Kennung (Routing-Tier)",
    "NO CAP (USE BEST)": "Kostenstufen-Kennung (Routing-Tier)",
    "Max $": "Waehrungszeichen der Eingabe",
    "/1M": "Einheit (pro 1 Million Token)",
    "Port 20128": "Portnummer des lokalen Gateways",
    "Port 5678 (": "Portnummer des n8n-Containers",
    "http://localhost:20128/v1": "Gateway-URL im Placeholder (Laufzeitwert)",
    "omniroute-local-key": "Beispiel-Key im Placeholder (technischer Wert)",
    "lisa@unternehmen.de": "Beispiel-Adresse im Placeholder (kein Prosa-Text)",
    # Tab kernel: Werte, die die View per JS ueberschreibt (Tab HERMES CORE)
    "Lade Profile...": "Platzhalter-Option, system_settings.js befuellt das Select neu",
    "Synchronisiert": "Status-Badge hermes-yaml-status-badge, aus JS",
    "⚡ Standard aktiv (~3.100 Zeichen/Agent)": "Status-Badge settings-soul-mode-status-badge, aus JS",
    "Vault Status prüfen...": "Status-Badge break-glass-status-badge, aus JS",
    "Checksumme: --": "Checksummen-Zeile break-glass-checksum-line, aus JS",
    "ARCHON-BG-...": "Platzhalter fuer den Laufzeitschluessel break-glass-displayed-key",
    "Änderungen werden direkt in das Profil übernommen.": "Statuszeile hermes-form-status-msg, aus JS",
    "data/backups/break_glass_vault.enc": "Pfad-Identifier des Notfall-Archivs",
    # Tab design: Komponenten-Inspektor und Farbpalette (per JS befuellt)
    "04. Insel-Container (Außenkarte)": "cds-active-comp-title, aus component_design_studio.js",
    ".os-island": "cds-active-comp-selector, CSS-Selektor aus component_design_studio.js",
    "Äußere Haupt-Container für Bereiche, Filterleisten und Sektionen": "cds-active-comp-desc, aus component_design_studio.js",
    "Alle Inhalts-Karten, Filter-Container, Dialoge & Listen": "cds-active-comp-usage, aus component_design_studio.js",
    "Lade Farbpalette…": "Platzhalter der Kanban-Palette, aus operations_kanban.js",
    # Tab plugins: Statusanzeigen und Schalter-Beschriftungen (per JS gesetzt)
    "Lade Status...": "Status-Badge settings-plugins-stats-badge, aus system_settings.js",
    "Lade Plugin-Katalog und Konfigurationen...": "Ladehinweis des Plugin-Katalogs, aus JS",
    "Inaktiv": "Schalter-Label setting-jev-toggle-label, wird per JS umgeschaltet",
    "Aktiv": "Schalter-Label der Plugin-Toggles, wird per JS umgeschaltet",
}

ATTRIBUTE_SECTIONS = SETTINGS_MODAL_DONE


def _load_scanner():
    """Importiert scripts/i18n_scan_textnodes.py als Modul (Messquelle)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("i18n_scan_textnodes", SCANNER_PATH)
    assert spec is not None and spec.loader is not None, "Scanner nicht ladbar"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _node_section(key: str) -> str:
    parts = key.split(".")
    return parts[1] if len(parts) > 2 else "general"


def test_view_fully_annotated_system_settings_modal():
    scanner = _load_scanner()
    result = scanner.scan(SETTINGS_MODAL)

    seen_sections = set()
    unexpected: list[str] = []
    pending = 0
    used_exceptions: set[str] = set()

    def judge(line: int, section: str, text: str, what: str) -> None:
        nonlocal pending
        seen_sections.add(section)
        if section in SETTINGS_MODAL_PENDING:
            pending += 1
            return
        if text in SETTINGS_MODAL_EXCEPTIONS:
            used_exceptions.add(text)
            return
        unexpected.append(f"{SETTINGS_MODAL.name}:{line} {what} <{section}> {text!r}")

    for node in result.open_nodes:
        judge(node["line"], _node_section(node["key"]), node["text"],
              f"<{node['tag']}>")
    for entry in result.attr_candidates:
        judge(entry["line"], _node_section(entry["key"]), entry["text"],
              f"@{entry['attr']}")

    unknown_sections = seen_sections - SETTINGS_MODAL_DONE - SETTINGS_MODAL_PENDING
    assert not unknown_sections, (
        f"unbekannte Tabs ohne Zuordnung: {sorted(unknown_sections)}"
    )

    dead = set(SETTINGS_MODAL_EXCEPTIONS) - used_exceptions
    assert not dead, f"Ausnahmen ohne Vorkommen (veraltet): {sorted(dead)}"

    assert not unexpected, (
        f"{len(unexpected)} offene Textknoten in den fertigen Tabs "
        f"({sorted(SETTINGS_MODAL_DONE)}):\n"
        + "\n".join(f"  {entry}" for entry in unexpected)
    )

    # Restmenge der naechsten Tranchen wird sichtbar gemacht, nicht versteckt.
    print(
        f"[i18n] {SETTINGS_MODAL.name}: {result.total} Textknoten, "
        f"{result.annotated} annotiert, {pending} offen in "
        f"{sorted(SETTINGS_MODAL_PENDING)}"
    )


# --- (c4) Vollstaendige Annotation der Views (Etappe 3, Paket 1) -------------
#
# Messquelle ist derselbe Scanner wie beim Settings-Modal. Je View gilt: jeder
# Textknoten mit Buchstaben und jedes der Attribute placeholder/title/aria-label
# braucht einen ``data-i18n*``-Anker, offen bleiben nur die unten begruendeten
# Laufzeitwerte. ``VIEWS_DONE`` sind die fertigen Dateien (0 offen erzwungen),
# ``VIEWS_PENDING`` die noch offenen Tranchen (nur gemessen). Eine View, die in
# keiner der beiden Mengen steht, laesst den Test scheitern - kein stilles
# Ueberspringen, auch nicht bei neu angelegten Dateien.

VIEWS_DIR = REPO_ROOT / "static" / "views"

# Das Settings-Modal hat seinen eigenen, tabweisen Test weiter oben
# (SETTINGS_MODAL_DONE/PENDING) und wird hier nicht doppelt gefuehrt.
VIEWS_SEPARATELY_TESTED = frozenset({"system_settings_modal.html"})

VIEWS_DONE = frozenset({
    "view_finance.html",
    "view_items.html",
    "view_addresses.html",
    "view_app_frame_studio.html",
    "agent_profiles_view.html",
    "view_research.html",
    "view_guardian.html",
    "inbox_view.html",
    "view_approval_policies.html",
    # Etappe 3, Paket 5 (Views-Tranche A)
    "view_corporate.html",
    "watchdog_view.html",
    "library_view.html",
    # Etappe 3, Paket 6 (Views-Tranche B1)
    "view_brain.html",
    "operations_view.html",
    "view_operations_erp.html",
    "view_showroom.html",
    # Etappe 3, Paket 7 (Views-Tranche B2) - Abschluss der Views
    "log_stream_view.html",
    "master_chat_view.html",
    "view_plugins.html",
})

# Abschluss der Views-Tranche B2: keine offene View mehr. Der Test fordert
# weiterhin eine Zuordnung jeder Datei - eine neue View muss also entweder
# fertig annotiert in ``VIEWS_DONE`` stehen oder hier bewusst als Tranche
# eingetragen werden.
VIEWS_PENDING = frozenset()

# Nicht uebersetzbare Knoten je View: Laufzeitwerte aus JS/Backend, technische
# Identifier, Einheiten, Beispielwerte. Textgleichheit ist eindeutig genug.
VIEW_EXCEPTIONS = {
    # --- Research Lab ----------------------------------------------------
    # Laufzeitwerte aus research_lab.js, Modell-/Produkt-Identifier und
    # technische Platzhalter.
    "view_research.html": {
        "6 aktiv": "Zaehler research-stat-engines, research_lab.js:246",
        "free-forever (OmniRoute)": "Modell-Alias der Routing-Auswahl (Identifier, Wert = Anzeige)",
        "claude-3-5-sonnet (Anthropic)": "Modell-Identifier der Auswahlliste",
        "gpt-4o (OpenAI)": "Modell-Identifier der Auswahlliste",
        "gemini-1.5-pro (Google)": "Modell-Identifier der Auswahlliste",
        "hermes-3 (Local/Open)": "Modell-Identifier der Auswahlliste",
        "AGENT: LEAD RESEARCHER": "Status-Badge dossier-agent-badge, research_lab.js:368",
        "MODELL: AUTO/BEST-REASONING": "Status-Badge dossier-model-badge, research_lab.js:371",
        "TRIANGULATION: BEREIT": "Status-Badge dossier-triangulation-badge, research_lab.js:374",
        "QUALITY GATE: UNGEPRÜFT": "Status-Badge dossier-quality-badge, research_lab.js:381",
        # Produkt-/Wortmarken der Suchmaschinen (Glossar: bleiben unuebersetzt)
        "DuckDuckGo": "Produktname (Wortmarke)",
        "Wikipedia": "Produktname (Wortmarke)",
        "ArXiv": "Produktname (Wortmarke)",
        "Perplexity Sonar": "Produktname (Wortmarke)",
        "SearXNG": "Produktname (Wortmarke)",
        "Tavily AI": "Produktname (Wortmarke)",
        "Agentic Search API": "technische Bezeichnung der Tavily-Schnittstelle (Lehnwort)",
        # Technische Platzhalter
        "[Quelle: Name](URL)": "Platzhalter des Zitationsformats (Code-Beispiel)",
        "memories/research/": "Pfad-Identifier des Vault-Ordners",
    },
    "view_guardian.html": {
        # Laufzeitwerte, die guardian.js in die Knoten schreibt
        "-- Calls": "Zaehler guard-kpi-calls, guardian.js:49",
        "-- MCP Tools": "Zaehler guard-kpi-mcp-tools, guardian.js befuellt den Knoten",
        "-- Tokens verbraucht": "KPI-Wert guard-kpi-top-tokens, guardian.js:56",
        "✓ Gespeichert!": "Status-Feedback guard-save-feedback, wird per JS eingeblendet",
    },
    "inbox_view.html": {
        # Laufzeitwerte, die inbox_*.js in die Knoten schreiben
        "0 Items": "Zaehler inbox-total-badge, wird per JS aus der Trefferzahl gesetzt",
    },
    "view_approval_policies.html": {
        # Laufzeitwerte aus approval_policies_controller.js / Backend
        "0 Ausstehend": "Zaehler approvals-pending-badge, approval_policies_controller.js:178",
        "24 h": "Laufzeitwert val-finance_timeout_hours (Wert + Einheit)",
        # Personenangaben der Urlaubsvertretung (Demo-/Stammdaten, kein Prosa-Text)
        "i.V. Katharina Völk (QM)": "Demo-/Stammdaten der Urlaubsvertretung (Name + Rolle)",
        "i.V. Robert (CEO)": "Demo-/Stammdaten der Urlaubsvertretung (Name + Rolle)",
        "i.V. Eva (Operations)": "Demo-/Stammdaten der Urlaubsvertretung (Name + Rolle)",
    },
    "view_finance.html": {
        "0 Belege": "Zaehler-Badge finance-receipt-count-badge, finance_controller.js:59",
        "0.00 EUR": "Betrags-Badge/KPI finance-total-amount-badge, finance-kpi-*, finance_controller.js:60/274/275",
        "Ausstehend": "Status-Badge finance-detail-status-badge, finance_controller.js:187",
        "Keine Auswahl": "Mahnstufen-Badge finance-dunning-stage-badge, finance_controller.js:434",
        "buchhaltung@musterfirma.de": "Beispiel-Adresse im Placeholder (kein Prosa-Text)",
    },
    "view_items.html": {
        "0 Artikel": "Zaehler-Badge erp-items-count-badge, erp_studio.js:1370",
        "\u00d8 Marge & VK-Kalkulation": "KPI-Banner erp-items-mode-kpi, erp_studio.js setzt Laufzeitwerte",
        "0.00 EUR (0.0%)": "Margenanzeige erp-itm-margin-display, updateLiveItemMargin()",
        "Artikelbezeichnung": "Drawer-Titel erp-item-drawer-title, erp_studio.js:1502",
        "Service": "Typ-Badge erp-item-drawer-type-badge, erp_studio.js setzt typeLabels",
        "Art-Nr: ART-1001": "Nummernzeile erp-item-drawer-no, erp_studio.js",
        "8400 (SKR03) / 4400 (SKR04)": "Beispiel-Kontonummern im Placeholder",
        "Regal A-04": "Beispiel-Lagerort im Placeholder",
        "ANG-2026-0842": "Demo-Belegnummer der Absatzhistorie (erp_studio.js schreibt die Tabelle neu)",
        "AB-2026-0199": "Demo-Belegnummer der Absatzhistorie (erp_studio.js schreibt die Tabelle neu)",
        "Nordstern Digital AG": "Demo-Kundenname der Absatzhistorie",
        "Bormann Bioscience": "Demo-Kundenname der Absatzhistorie",
        "10 Std.": "Demo-Mengenangabe (Einheit) der Absatzhistorie",
        "40 Std.": "Demo-Mengenangabe (Einheit) der Absatzhistorie",
    },
    "view_addresses.html": {
        # Laufzeitwerte, die JS/Backend in die Knoten schreibt
        "2.331 Kontakte": "Zaehler-Badge erp-addr-count-badge, aus dem Backend",
        "2331 Treffer": "Treffer-Zaehler crm-kontakte-hits-badge, crm_studio.js",
        "ID: -": "Laufzeit-ID crm-drawer-id, crm_studio.js setzt sie",
        "SEPA-AUTOGEN": "Laufzeit-Mandatsreferenz cd-sepa-ref",
        # Technische Identifier und Einheiten (Glossar: bleibt unuebersetzt)
        "SQLite Engine (WAL)": "technischer Engine-Name (Lehnwort)",
        "T": "Icon-Glyphe der Tabellenkopfzeilen (lucide-Fallback), Z. 192-200",
        "Std.": "Einheit der Mengenspalte (cd-doc-unit)",
        # Demo-Belegzeile der Vorgaenge-Tabelle (Z. 953-970)
        "Angebot": "Demo-Belegart der statischen Belegzeile",
        "ANG-2026-0842": "Demo-Belegnummer der statischen Belegzeile",
        "In Prüfung": "Demo-Status der statischen Belegzeile",
        "📄 DIN-PDF": "Demo-Aktionsbutton der statischen Belegzeile",
        "Auftrag": "Demo-Belegart der statischen Belegzeile",
        "AB-2026-0199": "Demo-Belegnummer der statischen Belegzeile",
        "Bestätigt": "Demo-Status der statischen Belegzeile",
        # Demo-Ansprechpartner (Z. 991-1006): Namen, Rollen, Adressen
        "Dr. Markus Weimer": "Demo-Ansprechpartner der Beispielkarte",
        "Einkauf / CPO": "Demo-Rolle des Beispiel-Ansprechpartners",
        "m.weimer@bormann-bio.de": "Demo-E-Mail des Beispiel-Ansprechpartners",
        "Sabine Lindemann": "Demo-Ansprechpartnerin der Beispielkarte",
        "Buchhaltung / AP": "Demo-Rolle der Beispiel-Ansprechpartnerin",
        "finance@bormann-bio.de": "Demo-E-Mail der Beispiel-Ansprechpartnerin",
        # Artikelstamm-Optionen mit Preisangabe (Preise sind Laufzeitdaten)
        "Senior AI Architecture Consulting (180,00 € / Std.)": "Demo-Artikel mit Preisangabe im Beleg-Builder",
        "Archon OS Enterprise Subscription (4.500,00 € / Pauschal)": "Demo-Artikel mit Preisangabe im Beleg-Builder",
        "Dedizierter Agenten-Cluster & Setup (950,00 € / Setup)": "Demo-Artikel mit Preisangabe im Beleg-Builder",
        # Beispiel-Belegungsdaten der Formularfelder (Placeholder)
        "Vorname Nachname": "Beispiel-Name im Placeholder (Demo-Daten)",
        "Firma GmbH": "Beispiel-Firma im Placeholder (Demo-Daten)",
        "name@firma.de": "Beispiel-E-Mail im Placeholder (Demo-Daten)",
        "https://www.linkedin.com/in/...": "Beispiel-URL im Placeholder (Demo-Daten)",
        "DACH / Berlin": "Beispiel-Region im Placeholder (Demo-Daten)",
        "https://www.firma.de": "Beispiel-URL im Placeholder (Demo-Daten)",
        "Musterstraße 123, 10115 Berlin, Deutschland": "Beispiel-Adresse im Placeholder (Demo-Daten)",
        "Consultant & Co-Lead Private Equity...": "Beispiel-LinkedIn-Ueberschrift (Demo-Daten)",
        "D-10042": "Beispiel-Debitorennummer im Placeholder (Demo-Daten)",
        "K-70018": "Beispiel-Kreditorennummer im Placeholder (Demo-Daten)",
        "Commerzbank Frankfurt": "Beispiel-Bankname im Placeholder (Demo-Daten)",
        "DE89 3704 0044 0532 0130 00": "Beispiel-IBAN im Placeholder (Demo-Daten)",
        "COBADEFFXXX": "Beispiel-BIC im Placeholder (Demo-Daten)",
        "DE 123456789": "Beispiel-USt-IdNr. im Placeholder (Demo-Daten)",
    },
    # --- Corporate & Mandanten (Views-Tranche A) -------------------------
    # Die Auswahl-Option des Mandanten-Switchers wird zur Laufzeit neu gebaut,
    # alle uebrigen offenen Knoten sind Beispielwerte der Formularfelder
    # (Demo-Daten, keine Prosa) bzw. ein Pfad-Identifier.
    "view_corporate.html": {
        "Archon Systems GmbH (Standard)": "Laufzeitwert: corporate_controller.js:19 leert corp-company-select (innerHTML='') und baut die Option aus /api/corporate/companies neu; view_corporate.html:386 macht dasselbe inline",
        "Friedrichstraße 123": "Beispiel-Adresse im Placeholder corp-input-street (view_corporate.html:108)",
        "Berlin": "Beispiel-Stadt im Placeholder corp-input-city (view_corporate.html:119)",
        "kontakt@firma.de": "Beispiel-Adresse im Placeholder corp-input-email (view_corporate.html:134)",
        "https://firma.de": "Beispiel-URL im Placeholder corp-input-web (view_corporate.html:138)",
        "Amtsgericht Charlottenburg": "Beispiel-Registergericht im Placeholder corp-input-court (view_corporate.html:156)",
        "HRB 248910 B": "Beispiel-Registernummer im Placeholder corp-input-hrb (view_corporate.html:160)",
        "Michael Mustermann, Dr. Anna Schmidt": "Beispiel-Namen im Placeholder corp-input-directors (view_corporate.html:166)",
        "DE345678901": "Beispiel-USt-IdNr. im Placeholder corp-input-vatid (view_corporate.html:172)",
        "Deutsche Bank Berlin": "Beispiel-Bankname im Placeholder corp-input-bankname (view_corporate.html:196)",
        "DE89 1007 0000 0123 4567 89": "Beispiel-IBAN im Placeholder corp-input-iban (view_corporate.html:200)",
        "DEUTDEDDBER": "Beispiel-BIC im Placeholder corp-input-bic (view_corporate.html:204)",
        "/static/img/logo.png": "Pfad-Identifier im Placeholder corp-input-logo (view_corporate.html:242)",
    },
    # --- Internet Watchdog (Views-Tranche A) -----------------------------
    # Ausschliesslich Zaehler/Badges, die watchdog_controller.js in die Knoten
    # schreibt. Zwei weitere Laufzeitknoten (wd-status-pill-text 'Aktiv',
    # wd-scan-btn-label 'Scan') liegen unter einem Element mit data-i18n-title
    # und gelten daher schon als abgedeckt; sie bleiben bewusst unuebersetzt.
    "watchdog_view.html": {
        "0 Funde": "Laufzeitwert wd-findings-total-badge, watchdog_controller.js:70",
        "Letzter Scan: --:--": "Laufzeitwert wd-last-scan-time-badge, watchdog_controller.js:77",
        "Alle": "Laufzeitwert wd-cat-active-label, watchdog_controller.js:733",
        "0/0 aktiv": "Laufzeitwert wd-sources-active-ratio, watchdog_controller.js:67",
        "30 Min.": "Laufzeitwert wd-sources-footer-interval, watchdog_controller.js:84",
        "0 Treffer": "Laufzeitwert wd-findings-counter-label, watchdog_controller.js:73",
    },
    # --- Zentralbibliothek (Views-Tranche A) -----------------------------
    # Vault-Ordner-Identifier, vom JS neu gerenderte Container und der
    # technische Port der AnythingLLM-Instanz.
    "library_view.html": {
        "Port 3001": "Technischer Port-Identifier der AnythingLLM-Instanz (library_view.html:90)",
        "Workspace: ARCHON (6.478 Docs)": "Statischer Bestandszähler mit Workspace-Identifier ARCHON (Demo-Wert, library_view.html:93)",
        "00_HR_Agenten": "Ordnername des Vault-Pfads (Identifier, library_view.html:142)",
        "02_Wissensbibliothek": "Laufzeitwert lib-hub-books-count-sub: wissensbibliothek.js:78 schreibt '${n} Dokumente & Werke'",
        "Protokolle/": "Ordnername des Vault-Pfads (Identifier, library_view.html:158)",
        "00_Notebook_Synthesen": "Ordnername des Vault-Pfads (Identifier, library_view.html:166)",
        "🌿 06_Cannabis_Wirtschaft_Medizin": "Kategorie-Identifier des Vault-Ordners, value = Anzeige (library_view.html:193)",
        "💼 07_Betriebswirtschaft_Finanzen": "Kategorie-Identifier des Vault-Ordners, value = Anzeige (library_view.html:194)",
        "📋 08_Projektmanagement_Organisation": "Kategorie-Identifier des Vault-Ordners, value = Anzeige (library_view.html:195)",
        "🏗️ 01_Immobilien_Modulbau": "Kategorie-Identifier des Vault-Ordners, value = Anzeige (library_view.html:196)",
        "⚖️ 02_Recht_Steuern": "Kategorie-Identifier des Vault-Ordners, value = Anzeige (library_view.html:197)",
        "📈 03_Strategie_Markt": "Kategorie-Identifier des Vault-Ordners, value = Anzeige (library_view.html:198)",
        "💻 09_Tech_Software_KI": "Kategorie-Identifier des Vault-Ordners, value = Anzeige (library_view.html:199)",
        "🩺 10_Medizin_Gesundheit": "Kategorie-Identifier des Vault-Ordners, value = Anzeige (library_view.html:200)",
        "📚 04_Allgemein": "Kategorie-Identifier des Vault-Ordners, value = Anzeige (library_view.html:201)",
        "0 Dateien ausgewählt:": "Laufzeitwert library-files-count-label-sub, wissensbibliothek.js:282 setzt den Zaehler",
        "Verarbeite Dokumente...": "Laufzeitwert library-ingest-status-title, wissensbibliothek.js:351/409 ueberschreiben den Knoten",
        "Alle": "wissensbibliothek.js:117 rendert library-category-filter-container-sub neu ('Alle (n)')",
        "Lade Werke...": "wissensbibliothek.js:46 ersetzt tbody library-books-table-body-sub",
        "Lade Vault-Dateien...": "Laufzeitwert vault-tree-container, static/index.html:4689 schreibt denselben Text",
        "Bereit": "Laufzeitwert vault-tree-count-label, static/index.html:4681/4701/4709",
        "Keine Datei ausgewählt": "Laufzeitwert vault-viewer-filename, static/index.html:4887 setzt innerText",
        "Wähle eine Notiz aus dem Vault auf der linken Seite aus.": "Laufzeitwert vault-viewer-content, static/index.html:4891 ueberschreibt mit 'Lade Inhalt...'",
    },
# --- Second Brain (Views-Tranche B1) -------------------------------
# Vault-Pfade und Ordner-Identifier (value = Anzeige, unuebersetzbar),
# Laufzeitwerte aus wissensbibliothek.js sowie gekapselte Mixed-Knoten.
    "view_brain.html": {
        "./obsidian_vault":
            "Vault-Pfad: wissensbibliothek.js:23/42 schreibt den Pfad in current-vault-path-label",
        "Füge PDFs, DIN-Normen, B-Pläne oder Fachbücher hinzu. Das System extrahiert Texte, Tabellen und Pläne vollständig lokal per Text-Extraction & OCR, sortiert sie thematisch und speichert sie als saubere Markdown-Dateien in deinem Obsidian Vault (":
            "Mixed-Knoten: Text und Kind-Element teilen sich den Elternknoten; archon_i18n.js:128-133 setzt el.textContent und wuerde das Kind loeschen (<code> mit Vault-Pfad, view_brain.html:22)",
        "02_Wissensbibliothek/":
            "Vault-Ordner-Identifier im <code> der Einleitung (view_brain.html:22)",
        "📁 ./obsidian_vault (Haupt-Vault)":
            "Vault-Pfad der Auswahl obsidian-vault-selector (value = Anzeige, view_brain.html:29)",
        "00_HR_Agenten":
            "Ordnername des Vault-Hubs (Identifier, view_brain.html:46)",
        "02_Wissensbibliothek":
            "Ordnername des Vault-Hubs; wissensbibliothek.js:77 ueberschreibt lib-hub-books-count mit dem Bestand",
        "Protokolle/":
            "Ordnername des Vault-Hubs (Identifier, view_brain.html:62)",
        "00_Notebook_Synthesen":
            "Ordnername des Vault-Hubs (Identifier, view_brain.html:70)",
        "🌿 06_Cannabis_Wirtschaft_Medizin":
            "Kategorie-Identifier des Vault-Ordners (value = Anzeige, view_brain.html:96)",
        "💼 07_Betriebswirtschaft_Finanzen":
            "Kategorie-Identifier des Vault-Ordners (value = Anzeige, view_brain.html:97)",
        "📋 08_Projektmanagement_Organisation":
            "Kategorie-Identifier des Vault-Ordners (value = Anzeige, view_brain.html:98)",
        "🏗️ 01_Immobilien_Modulbau":
            "Kategorie-Identifier des Vault-Ordners (value = Anzeige, view_brain.html:99)",
        "⚖️ 02_Recht_Steuern":
            "Kategorie-Identifier des Vault-Ordners (value = Anzeige, view_brain.html:100)",
        "📈 03_Strategie_Markt":
            "Kategorie-Identifier des Vault-Ordners (value = Anzeige, view_brain.html:101)",
        "💻 09_Tech_Software_KI":
            "Kategorie-Identifier des Vault-Ordners (value = Anzeige, view_brain.html:102)",
        "🩺 10_Medizin_Gesundheit":
            "Kategorie-Identifier des Vault-Ordners (value = Anzeige, view_brain.html:103)",
        "📚 04_Allgemein":
            "Kategorie-Identifier des Vault-Ordners (value = Anzeige, view_brain.html:104)",
        "0 Dateien ausgewählt:":
            "Zaehler library-files-count-label, wissensbibliothek.js:282 setzt 'n Datei(en) ausgewaehlt:'",
        "Verarbeite Dokumente...":
            "Laufzeitwert library-ingest-status-title, wissensbibliothek.js:323/404 ueberschreiben den Knoten",
        "Alle (":
            "Mixed-Knoten: Text und Kind-Element teilen sich den Elternknoten; archon_i18n.js:128-133 setzt el.textContent und wuerde das Kind loeschen (Zaehler <span id=lib-count-all>); wissensbibliothek.js:76/117 rendert den Filter neu",
        "Lade Vault-Bestand...":
            "Ladezustand library-books-table-body, wissensbibliothek.js:44/153 ersetzen das tbody",
    },
# --- Operations / Kanban, Org & Comm (Views-Tranche B1) ------------
# Laufzeit-Badges aus operations_kanban.js, Kanal- und Rollen-Identifier
# sowie die Mixed-Knoten der Bulk-Menue-Buttons (Farbpunkt-<span>).
    "operations_view.html": {
        "Archiv (…)":
            "Laufzeitwert operations_kanban.js:400 setzt 'Archiv (n)' in den Button-Span",
        "0 markiert":
            "Zaehler ops-kanban-bulk-count, operations_kanban.js:3051 setzt die Auswahlzahl",
        "Backlog":
            "Mixed-Knoten: Text und Kind-Element teilen sich den Elternknoten; archon_i18n.js:128-133 setzt el.textContent und wuerde das Kind loeschen (Farbpunkt-<span> im Bulk-Menue, operations_view.html:85)",
        "To-Do":
            "Mixed-Knoten: Text und Kind-Element teilen sich den Elternknoten; archon_i18n.js:128-133 setzt el.textContent und wuerde das Kind loeschen (Farbpunkt-<span> im Bulk-Menue, operations_view.html:88)",
        "In Arbeit":
            "Mixed-Knoten: Text und Kind-Element teilen sich den Elternknoten; archon_i18n.js:128-133 setzt el.textContent und wuerde das Kind loeschen (Farbpunkt-<span> im Bulk-Menue, operations_view.html:91)",
        "Review":
            "Mixed-Knoten: Text und Kind-Element teilen sich den Elternknoten; archon_i18n.js:128-133 setzt el.textContent und wuerde das Kind loeschen (Farbpunkt-<span> im Bulk-Menue, operations_view.html:94)",
        "Blockiert":
            "Mixed-Knoten: Text und Kind-Element teilen sich den Elternknoten; archon_i18n.js:128-133 setzt el.textContent und wuerde das Kind loeschen (Farbpunkt-<span> im Bulk-Menue, operations_view.html:97)",
        "Erledigt":
            "Mixed-Knoten: Text und Kind-Element teilen sich den Elternknoten; archon_i18n.js:128-133 setzt el.textContent und wuerde das Kind loeschen (Farbpunkt-<span> im Bulk-Menue, operations_view.html:100)",
        "Aufgaben aktualisiert":
            "Laufzeitwert ops-kanban-undo-msg, operations_kanban.js:3266 setzt die Meldung",
        "#all-stream":
            "Kanal-Identifier (switchCommChannel('all'), operations_kanban.js:3492)",
        "#boardroom":
            "Kanal-Identifier (switchCommChannel('boardroom'), operations_kanban.js:3511)",
        "#projekte-tasks":
            "Kanal-Identifier (switchCommChannel('projects'), operations_kanban.js:3514)",
        "📡 #all-stream — Gesamt-Funkverkehr aller Agenten":
            "Laufzeitwert ops-comm-active-title, operations_kanban.js:3518/3349 ueberschreiben den Knoten",
        "· Echtzeit-Streaming aktiv":
            "Laufzeitwert ops-comm-active-desc, operations_kanban.js:3519 ueberschreibt den Knoten",
        "👑 Commander":
            "Rollen-Identifier des Absenders (option value=commander, operations_view.html:313)",
        "🤖 Dispatcher":
            "Rollen-Identifier des Absenders (option value=system_dispatcher, operations_view.html:314)",
        "n":
            "Ein-Zeichen-Platzhalter der Zahleneingabe ops-kanban-wip-n (Feldbreite, view:39)",
    },
# --- Vorgaenge & Vertraege (Views-Tranche B1) ----------------------
# Ausschliesslich Laufzeitwerte, die erp_studio.js in die Knoten schreibt.
    "view_operations_erp.html": {
        "Offene Angebote: 0.00 EUR":
            "Laufzeitwert erp-ops-volume-badge, erp_studio.js:2012-2013 setzt das Angebotsvolumen",
        "Lade Vorgänge...":
            "Ladezustand erp-offers-list-container, erp_studio.js:2026-2040 rendert die Liste neu",
        "0 aktive Angebote":
            "Laufzeitwert erp-pipe-offers-count, erp_studio.js:2015-2016 setzt den Zaehler",
        "0.00 EUR":
            "Laufzeitwert erp-pipe-won-volume, erp_studio.js:2021-2022 setzt den Bruttoumsatz",
    },
# --- Showroom (Views-Tranche B1) -----------------------------------
# Laufzeitwerte aus dem Inline-Skript in static/index.html, der
# Projekt-Ordner-Identifier und ein Mixed-Knoten (Icon im Button).
    "view_showroom.html": {
        "0 Projekte":
            "Zaehler showroom-projects-count-badge, static/index.html:5007 setzt den Projektzaehler",
        "Lade Projekt-Dateibaum...":
            "Ladezustand showroom-tree-container, static/index.html:5009 ersetzt den Container",
        "01_PROJEKTE":
            "Ordnername des Projekt-Stamms (Identifier, view_showroom.html:148)",
        "Keine Datei ausgewählt":
            "Laufzeitwert showroom-file-name, static/index.html:5337 setzt den Dateinamen",
        "Wähle links im Explorer einen Zwischenbericht, Medien oder ein Endprodukt":
            "Laufzeitwert showroom-file-breadcrumb, static/index.html:5338 setzt den Pfad",
        "Im neuen Tab öffnen":
            "Mixed-Knoten: Text und Kind-Element teilen sich den Elternknoten; archon_i18n.js:128-133 setzt el.textContent und wuerde das Kind loeschen (Icon <i data-lucide=external-link>, view_showroom.html:239)",
        "0 ms":
            "Laufzeitwert showroom-sandbox-duration, static/index.html:5423 setzt die Laufzeit",
    },
    "view_app_frame_studio.html": {
        # Laufzeitwerte, die design_studio JS in die Knoten schreibt
        "div#target": "Laufzeit-Selektor archon-highlighter-badge, aus JS",
        "W: 0px × H: 0px | R: 0px": "Live-Masse gizmo-info-badge, aus JS",
        "0 Regeln": "Zaehler studio-active-rules-count, aus JS",
        "none": "Tag-Badge studio-element-tag-badge, aus JS",
        "14px": "Laufzeitwert st-val-font-size, aus JS",
        "1px": "Laufzeitwert st-val-border-width, aus JS",
        "8px": "Laufzeitwert st-val-border-radius und Platzhalter der Eckenfelder",
        "Sichtbar": "Status-Badge studio-symbols-vis-badge, aus JS",
        # Produktname (Wortmarke) des Studios
        "Archon CSS Live Studio": "Produktname der Studio-Wortmarke",
        # Beispielwerte/Einheiten in Platzhaltern
        "#cbd5e1": "Beispiel-Hexwert im Placeholder (Farbe)",
        "T: 0": "Box-Modell-Platzhalter (Beispielwert)",
        "L: 0": "Box-Modell-Platzhalter (Beispielwert)",
        "R: 0": "Box-Modell-Platzhalter (Beispielwert)",
        "B: 0": "Box-Modell-Platzhalter (Beispielwert)",
        "T: 8px": "Box-Modell-Platzhalter (Einheit)",
        "L: 8px": "Box-Modell-Platzhalter (Einheit)",
        "R: 8px": "Box-Modell-Platzhalter (Einheit)",
        "B: 8px": "Box-Modell-Platzhalter (Einheit)",
        "auto / 100% / 320px": "Beispielwerte im Placeholder (Einheiten)",
        "auto / 40px / 100%": "Beispielwerte im Placeholder (Einheiten)",
    },
    # --- Agenten-Kader ---------------------------------------------------
    # Werte, die agent_profiles.js in die Knoten schreibt, Demo-Inhalte des
    # Beispielprofils und technische Identifier/Pfade.
    "agent_profiles_view.html": {
        # Laufzeitwerte aus agent_profiles.js
        "Executive Decision Architect": "Demo-Rolle des Beispielprofils (profile-editor-role, pa-inline-role-name)",
        "Alexander Richter": "Demo-Name des Beispielprofils (profile-editor-title, pa-inline-person-name)",
        "1. STRATEGIE, FÜHRUNG & LEBENSPLANUNG": "Kategorie-Tag profile-editor-cat-tag, aus JS",
        "-- Aktiv": "Status-Badge gateway-widget-status-badge, aus JS",
        "aktiv: -": "Label prof-active-model-label, aus JS",
        "Lade Modelle...": "Platzhalter-Option, agent_profiles.js befuellt das Select neu",
        "In: $0.15 | Out: $0.60 /1M Tok": "Tokenpreis-Badge prof-edit-model-cost, aus JS",
        "0 Projekte": "Zaehler prof-projects-count, aus JS",
        "Lade Projektbeteiligungen...": "Ladezustand der Projektliste, aus JS",
        "Live": "Status prof-log-status, aus JS",
        "Lade Agenten-Aktivität...": "Ladezustand des Aktivitaets-Logs, aus JS",
        "✓ Gespeichert": "Status prof-callsign-status, aus JS",
        "Alex Rivera (Owner / CEO)": "Laufzeit-Supervisor kpi-val-supervisor",
        "24 Tasks abgeschlossen": "KPI-Wert kpi-val-tasks, aus JS",
        "99.4% (Einsatzbereit)": "KPI-Wert kpi-val-success, aus JS",
        "0 zugewiesen": "Zaehler prof-skills-summary-badge / prof-tools-summary-badge",
        "0 aktiv": "Zaehler prof-skills-count / prof-tools-count, aus JS",
        "Bereit": "Status agent-tab-chat-status / prof-soul-save-status, aus JS",
        "Live Telemetrie": "Status pa-scorecard-status, aus JS",
        "Synchronisiert": "Status pa-inline-save-status / pa-inline-sync-badge, aus JS",
        "0 Reviews": "KPI-Unterzeile pa-kpi-success-sub, aus JS",
        "$0.00 / Task": "KPI-Unterzeile pa-kpi-tokens-sub, aus JS",
        "0 Ratings": "KPI-Unterzeile pa-kpi-feedback-sub, aus JS",
        "--k": "Laufzeitwert pa-kpi-tokens, aus JS",
        "--m": "Laufzeitwert pa-kpi-speed, aus JS",
        "0 aktive Tasks": "Zaehler operations-tasks-count, aus JS",
        "~2.200 Zeichen": "Zeichenzaehler prof-soul-char-badge, aus JS",
        "174 Porträts verfügbar – farblich sortiert": "Zaehler avatar-library-count-text, aus JS",
        "[[Alex Rivera (Owner / CEO)]]": "Laufzeit-Supervisor pa-inline-supervisor, aus JS",
        # Technische Identifier und Pfade
        "meta-llama/llama-3.3-70b-instruct": "Modell-Identifier in der Auswahlliste",
        "anthropic/claude-3.7-sonnet": "Modell-Identifier in der Auswahlliste",
        "deepseek/deepseek-v3": "Modell-Identifier in der Auswahlliste",
        "openai/gpt-4o-mini": "Modell-Identifier in der Auswahlliste",
        "Display :99 (CDP 9222)": "technischer Display-/CDP-Identifier des Bot-Screens",
        "~/.hermes/profiles/SOUL.md": "Pfad-Identifier prof-soul-path-label",
        "00_HR_Agenten/Personalakten/agent.md": "Pfad-Identifier pa-inline-path",
        "Karriere & Bewerbungs-Portal — Autonome Sitzung": "Titel cadre-botscreen-title, agent_profiles.js:4126",
        # Demo-Inhalt der Login-Kachel des Bot-Screens (Z. 1004-1033)
        "Bewerbungs- & Karriereportal": "Demo-Mock der Login-Kachel (Z. 1011)",
        "Eingeloggte Sitzung: Michael (Geschäftsleitung)": "Demo-Daten der Login-Kachel (Z. 1012)",
        "Sitzung Aktiv": "Demo-Status der Login-Kachel (Z. 1015)",
        "12 neue Bewerbungen eingegangen": "Demo-Zaehler der Login-Kachel (Z. 1020)",
        "3 ungeprüft": "Demo-Zaehler der Login-Kachel (Z. 1021)",
        "Initiativ-Bewerbungen & Matchmaking": "Demo-Zeile der Login-Kachel (Z. 1024)",
        "Logge dich hier ein. Sobald du fertig bist, autorisiere unten den Agenten und gib ihm den Arbeitsauftrag.": "Demo-Hinweis der Login-Kachel (Z. 1031)",
        # Beispiel-Belegung des Formularfelds
        "z.B. Alexander Richter": "Beispiel-Name im Placeholder (Demo-Daten)",
    },
# --- Telemetrie & Logs (Views-Tranche B2) --------------------------
# Titel/Untertitel und Badges schreibt das Inline-Skript in static/index.html;
# feste Log-Level-Kennungen, Dateiendungen, ein Spalten-Identifier und die
# Mixed-Knoten (Icon plus Text im selben Elternknoten).
    "log_stream_view.html": {
        "Telemetrie & Logs — Container":
            "Laufzeitwert logstream-main-title: static/index.html:5961-5963 setzt Titel und Untertitel je Modus aus dem meta-Objekt",
        "Live-Audit, Docker-Streams, Hermes Agentenprotokolle und SHA-256 Hash-Chains":
            "Laufzeitwert logstream-main-subtitle: static/index.html:5961-5963 ueberschreibt den Knoten beim Moduswechsel",
        "10 Live":
            "Zaehler logstream-source-count-badge: static/index.html:6001/6009/6025 setzt 'Hash-Chain', 'n Container' oder 'n Profile'",
        "Supervisor aktiv (60s)":
            "Mixed-Knoten: Text und Kind-Element teilen sich den Elternknoten; archon_i18n.js:128-133 setzt el.textContent und wuerde den Status-Punkt loeschen (log_stream_view.html:24)",
        "HERMES ID: --":
            "Laufzeitwert logstream-active-title: static/index.html:6156 (updateLogStreamHeaderTitle) setzt den Titel je Container/Profil",
        "ALL":
            "Log-Level-Kennung; der Wert ist zugleich Argument von setLogStreamLevel('ALL') (log_stream_view.html:145)",
        "ERR":
            "Log-Level-Kennung; der Wert ist zugleich Argument von setLogStreamLevel('ERROR') (log_stream_view.html:146)",
        "WARN":
            "Log-Level-Kennung; der Wert ist zugleich Argument von setLogStreamLevel('WARN') (log_stream_view.html:147)",
        "LIVE":
            "Log-Level-Kennung der Pause-Umschaltung (toggleLogStreamPause, log_stream_view.html:148)",
        "Verbinde mit Docker & Hermes Log-Stream...":
            "Laufzeit-Container logstream-terminal-lines: static/index.html:6136-6151 ersetzt ihn durch 'Lade Logs fuer [...]...'",
        "200 Zeilen angezeigt":
            "Zaehler logstream-footer-line-count: static/index.html:6299 setzt 'n Zeilen angezeigt'",
        "Export (.log)":
            "Mixed-Knoten: Text und Kind-Element teilen sich den Elternknoten; archon_i18n.js:128-133 wuerde das Download-Icon loeschen (log_stream_view.html:178)",
        "Kette ungeprüft":
            "Status-Badge audit-chain-badge: static/index.html:8815/8823 setzt 'Kette intakt' bzw. 'Kette kompromittiert'",
        "Prüfbericht exportieren":
            "Mixed-Knoten: Text und Kind-Element teilen sich den Elternknoten; archon_i18n.js:128-133 wuerde die beiden Icons loeschen (log_stream_view.html:208)",
        ".json":
            "Dateiendung des Export-Menueeintrags (Identifier, kein Prosa-Text)",
        ".csv":
            "Dateiendung des Export-Menueeintrags (Identifier, kein Prosa-Text)",
        "Aktualisieren":
            "Mixed-Knoten: Text und Kind-Element teilen sich den Elternknoten; archon_i18n.js:128-133 wuerde das Refresh-Icon loeschen (log_stream_view.html:224)",
        "Kette verifizieren":
            "Mixed-Knoten: Text und Kind-Element teilen sich den Elternknoten; archon_i18n.js:128-133 wuerde das Pruef-Icon loeschen (log_stream_view.html:227)",
        "# ID":
            "Spaltenkennung der Audit-Tabelle (Identifier-Kuerzel, kein Prosa-Text)",
        "Lade kryptografische Audit-Einträge...":
            "Ladezustand audit-log-table-body: static/index.html:8651 ersetzt das tbody beim Laden",
        "Audit Block #--":
            "Laufzeitwert audit-modal-title: static/index.html:8843 setzt 'Audit Block #<id>'",
        "Signierter Block-Hash (SHA-256):":
            "Mixed-Knoten: Text und Kind-Element teilen sich den Elternknoten; archon_i18n.js:128-133 wuerde den Farbpunkt-<span> loeschen (log_stream_view.html:334)",
        "Kopieren":
            "Mixed-Knoten: Text und Kind-Element teilen sich den Elternknoten; archon_i18n.js:128-133 wuerde das Copy-Icon loeschen (log_stream_view.html:337)",
        "JSON kopieren":
            "Mixed-Knoten: Text und Kind-Element teilen sich den Elternknoten; archon_i18n.js:128-133 wuerde das Copy-Icon loeschen (log_stream_view.html:348)",
        "Revisionssicher & unveränderbar":
            "Mixed-Knoten: Text und Kind-Element teilen sich den Elternknoten; archon_i18n.js:128-133 wuerde das Haekchen-Icon loeschen (log_stream_view.html:357)",
    },
# --- Master Chat (Views-Tranche B2) --------------------------------
# Profilkopf und Sessionliste schreibt chat_engine.js, der Trust-Schalter
# schreibt static/index.html; Anbieter- und Modellnamen sind Wortmarken bzw.
# Modell-Identifier.
    "master_chat_view.html": {
        "1. Strategie":
            "Laufzeitwert master-chat-profile-category: chat_engine.js:281-283 setzt prof.category",
        "Zentrales Hermes-Basissystem mit Zugriff auf Container Tools":
            "Laufzeitwert master-chat-profile-desc: chat_engine.js:285-287 setzt prof.description",
        "OpenRouter":
            "Wortmarke des Anbieters (Glossar: Produktname bleibt unuebersetzt)",
        "Google AI (Gemini)":
            "Wortmarke des Anbieters (Glossar: Produktname bleibt unuebersetzt)",
        "OmniRoute":
            "Wortmarke des Anbieters (Glossar: Produktname bleibt unuebersetzt)",
        "Groq":
            "Wortmarke des Anbieters (Glossar: Produktname bleibt unuebersetzt)",
        "OpenAI":
            "Wortmarke des Anbieters (Glossar: Produktname bleibt unuebersetzt)",
        "NVIDIA NIM":
            "Wortmarke des Anbieters (Glossar: Produktname bleibt unuebersetzt)",
        "meta-llama/llama-3.3-70b-instruct":
            "Modell-Identifier der Auswahlliste; chat_engine.js:239 baut das Select ohnehin neu auf",
        "anthropic/claude-3.7-sonnet":
            "Modell-Identifier der Auswahlliste; chat_engine.js:239 baut das Select ohnehin neu auf",
        "deepseek/deepseek-v3":
            "Modell-Identifier der Auswahlliste; chat_engine.js:239 baut das Select ohnehin neu auf",
        "openai/gpt-4o-mini":
            "Modell-Identifier der Auswahlliste; chat_engine.js:239 baut das Select ohnehin neu auf",
        "Lade Sessions...":
            "Ladezustand master-chat-sessions-list: chat_engine.js:476-485 ersetzt den Container durch die gerenderte Liste",
    },
# --- Erweiterungen & Module (Views-Tranche B2) ---------------------
# Zaehler und Fachreiter-Kopf schreibt static/index.html; ein Mixed-Knoten im
# Action-Button.
    "view_plugins.html": {
        "34 Module":
            "Zaehler plugins-active-badge: static/index.html:9007-9008 setzt 'n / m aktiv'",
        "Neu laden":
            "Mixed-Knoten: Text und Kind-Element teilen sich den Elternknoten; archon_i18n.js:128-133 wuerde das Refresh-Icon loeschen (view_plugins.html:34)",
        "Sicherheit & Wächter Module":
            "Laufzeitwert plugin-center-tab-title: static/index.html:8983-8985 setzt '<Kategorie> Module' beim Reiterwechsel",
        "Schutz vor unbegrenztem Tokenverbrauch, Endlosschleifen und Injection-Angriffen.":
            "Laufzeitwert plugin-center-tab-desc: static/index.html:8984-8985 setzt catMeta.desc beim Reiterwechsel",
        "-- aktiv":
            "Laufzeitwert plugin-center-active-count: static/index.html:9025-9026 setzt 'n von m aktiv'",
        "Lade Erweiterungen...":
            "Ladezustand plugin-center-cards-grid: static/index.html:9030+ (renderPluginCenterCards) ersetzt das Grid",
    },
}


def test_all_view_files_are_classified():
    """Jede View auf der Platte steht in VIEWS_DONE oder VIEWS_PENDING."""
    on_disk = {path.name for path in VIEWS_DIR.glob("*.html")}
    unknown = sorted(on_disk - VIEWS_DONE - VIEWS_PENDING - VIEWS_SEPARATELY_TESTED)
    assert not unknown, f"Views ohne Zuordnung in DONE/PENDING: {unknown}"

    vanished = sorted((VIEWS_DONE | VIEWS_PENDING) - on_disk)
    assert not vanished, f"Views in DONE/PENDING existieren nicht: {vanished}"


def _view_files() -> list[str]:
    on_disk = {path.name for path in VIEWS_DIR.glob("*.html")}
    return sorted((on_disk - VIEWS_SEPARATELY_TESTED) | VIEWS_DONE | VIEWS_PENDING)


@pytest.mark.parametrize("name", _view_files())
def test_views_fully_annotated(name):
    assert name in VIEWS_DONE or name in VIEWS_PENDING, (
        f"{name} steht in keiner der Mengen VIEWS_DONE/VIEWS_PENDING"
    )

    scanner = _load_scanner()
    result = scanner.scan(VIEWS_DIR / name)
    exceptions = VIEW_EXCEPTIONS.get(name, {})
    used: set[str] = set()

    def allowed(text: str) -> bool:
        if text in exceptions:
            used.add(text)
            return True
        return False

    open_nodes = [node for node in result.open_nodes if not allowed(node["text"])]
    open_attrs = [entry for entry in result.attr_candidates if not allowed(entry["text"])]

    dead = set(exceptions) - used
    assert not dead, f"{name}: Ausnahmen ohne Vorkommen (veraltet): {sorted(dead)}"

    if name not in VIEWS_DONE:
        print(
            f"[i18n] {name}: {result.total} Textknoten, {result.annotated} annotiert, "
            f"{len(open_nodes)} offen, {len(open_attrs)} offene Attribute (PENDING)"
        )
        return

    unexpected = [
        f"{name}:{node['line']} <{node['tag']}> {node['text']!r}" for node in open_nodes
    ] + [
        f"{name}:{entry['line']} @{entry['attr']} {entry['text']!r}" for entry in open_attrs
    ]
    assert not unexpected, (
        f"{len(unexpected)} offene Textknoten/Attribute in {name}:\n"
        + "\n".join(f"  {entry}" for entry in unexpected)
    )


# --- (c5) Vollstaendige Annotation von static/index.html, zeilenweise --------
#
# Die groesste Datei wird in Zeilenbereichen abgearbeitet (Etappe 3, Pakete
# 1-4). Messquelle ist derselbe Scanner wie bei den Views. Je Zeilenbereich
# gilt: jeder offene Textknoten und jedes offene Attribut (placeholder/title/
# aria-label) braucht einen data-i18n*-Anker, offen bleiben nur die unten
# begruendeten Werte. ``INDEX_HTML_RANGES_DONE`` wird mit 0 offenen Knoten
# erzwungen, ``INDEX_HTML_RANGES_PENDING`` nur gemessen.
#
# Der Vollstaendigkeitstest verlangt zusaetzlich, dass *jeder* offene Knoten
# der Datei in genau einem der beiden Bereiche liegt - ein neuer Block
# ausserhalb der Bereiche laesst den Test scheitern, statt still ungeprueft
# zu bleiben.

INDEX_HTML_RANGES_DONE = (
    (1, 9999),          # Pakete 1-2: Sidebar bis Sandbox, Operations/Chat-Bereiche
    (10000, 10999),     # Paket 2: Gateway-Manager, Task-Erstellung/-Details, Agenten-Karte, Prompt-Studio
    (11000, 11999),     # Paket 3: Prompt-Vorlagen-Editor, Archon Prompt Studio, Watchdog-Auditor,
                        #          Ad-hoc-Sicherheitskanal, Brain-Theme-Studio
    (12000, 12999),     # Paket 4: Quartz-Pane, Plugin-Konfiguration, Bereichshilfe, Datei-Preview
    (13000, 13525),     # Paket 4: Datenschutz-/LLM-Modal, Hermes-Core-Update-Dialog
)

INDEX_HTML_RANGES_PENDING = ()

# Nicht uebersetzbare Knoten in index.html. Drei Gruppen, jede mit Grund und
# Fundstelle: (a) Laufzeitwerte, die static/js/*.js in den Knoten schreiben,
# (b) technische Identifier/Pfade/Produktnamen, (c) Fachinhalt.
INDEX_HTML_EXCEPTIONS = {
    # --- (a) Laufzeitwerte aus JS ---------------------------------------
    "KILL-SWITCH AKT...": "Zustandstext der Sidebar-Alarm-Pille, aus JS (index.html:397)",
    "1 Vorfall: telegram_bot ge...": "sidebar-killswitch-subtitle, index.html:6594 setzt den Text",
    "-- ms": "Telemetriewerte health-val-hermes_core/omniroute/hermes_dashboard/docker_proxy (index.html:472-475), aus JS",
    "Healthy": "Live-Status health-overall-text, index.html:8166 setzt den Text",
    "51 Profile": "Zaehler mc-sub-fleet (mission_control_cockpit.js) und statischer Kartenzaehler (index.html:668) - Wert + Einheit",
    "0 / 51 Aktiv": "KPI-Wert mc-kpi-fleet, mission_control_cockpit.js",
    "0 Tok/m": "KPI-Wert mc-kpi-tpm, mission_control_cockpit.js",
    "Limit 2M": "Unterzeile mc-sub-tpm, mission_control_cockpit.js",
    "Limit $5.00": "Unterzeile mc-sub-cost, mission_control_cockpit.js",
    "0.0% Fehler": "KPI-Wert mc-kpi-stability, mission_control_cockpit.js",
    "100% nominal": "Unterzeile mc-sub-stability, mission_control_cockpit.js",
    "0 Ausstehend": "KPI-Wert mc-kpi-governance-count, mission_control_cockpit.js",
    "Keine Sperren": "Unterzeile mc-kpi-governance-subtext, mission_control_cockpit.js",
    "Daemon nominal · Alle Worker auf Standby": "mc-inspect-slot-a-text, mission_control_cockpit.js",
    "0 / 10 Belegt": "Zaehler mc-inspect-slots-count, mission_control_cockpit.js",
    "web_search [0/5]": "Werkzeug-Badge der Slot-Liste mc-inspect-slots-list, cockpit.js:518 rendert neu",
    "code_gen [0/2]": "Werkzeug-Badge der Slot-Liste mc-inspect-slots-list, cockpit.js:518 rendert neu",
    "obsidian [1/3]": "Werkzeug-Badge der Slot-Liste mc-inspect-slots-list, cockpit.js:518 rendert neu",
    "deepseek-v4-flash: 18k / 128k": "mc-inspect-model-label, mission_control_cockpit.js",
    "deepseek-v4-flash-0731": "mc-inspect-model-full, mission_control_cockpit.js",
    "110k Tokens Puffer": "mc-inspect-context-buffer, mission_control_cockpit.js",
    "0.0k/m": "Sparkline-Werte mc-sparkline-avg/peak, mission_control_cockpit.js",
    "ID: A-01 | Modell: free-forever | Rolle: Researcher": "agent-terminal-subtitle, prompt_studio.js setzt den Text",
    "Web-Oberfläche Adresse": "agent-web-url-text, prompt_studio.js setzt die Adresse",
    "Keine Datei ausgewählt": "agent-artifact-name-preview, prompt_studio.js",
    "Preview": "agent-artifact-type-badge, prompt_studio.js",
    "Wählen Sie eine Datei links aus, um eine Vorschau anzuzeigen.": "agent-artifact-preview-box, prompt_studio.js:1717",
    "0 MB / 0 %": "agent-metric-ram, prompt_studio.js",
    "Bereit": "boardroom-total-badge, skill_markt.js",
    "AI Boardroom Debatte läuft im Hintergrund...": "boardroom-loading-status, skill_markt.js",
    "Michael": "boardroom-chair-person, skill_markt.js setzt den Namen",
    "Aufgabenstellung...": "boardroom-dialog-subtitle, skill_markt.js",
    "Debatte läuft...": "boardroom-dialog-status-text, skill_markt.js",
    "Datum · Framework · Runden": "boardroom-detail-meta, skill_markt.js",
    "Lade Preise...": "llm-price-modal-count, skill_markt.js",
    # --- (b) Produktnamen, technische Identifier -------------------------
    "ARCHON-OS": "Produktname (Wortmarke im <title>, index.html:6)",
    "ARCHON OS": "Produktname (Wortmarke im Logo-Header, index.html:170)",
    "/opt/data/obsidian/Projects/...": "Pfad-Identifier mc-artifact-modal-path (index.html:1026)",
    "http://host.docker.internal:20128/v1": "Gateway-URL im LLM-Router-Status (index.html:1344)",
    "free-forever": "Modell-Identifier der Agenten-Auswahl (index.html:1384)",
    "gpt-4o": "Modell-Identifier der Agenten-Auswahl (index.html:1385)",
    "gpt-4o-mini": "Modell-Identifier der Agenten-Auswahl (index.html:1386)",
    "claude-3-5-sonnet": "Modell-Identifier der Agenten-Auswahl (index.html:1387)",
    "hermes-3": "Modell-Identifier der Agenten-Auswahl (index.html:1388)",
    "gemini-1.5-pro": "Modell-Identifier der Agenten-Auswahl (index.html:1389)",
    "OpenRouter": "Provider-Name der Boardroom-Auswahl (index.html:1770)",
    "OpenAI Direct": "Provider-Name der Boardroom-Auswahl (index.html:1771)",
    "Anthropic Direct": "Provider-Name der Boardroom-Auswahl (index.html:1772)",
    "Google Gemini Direct": "Provider-Name der Boardroom-Auswahl (index.html:1773)",
    "Groq High-Speed": "Provider-Name der Boardroom-Auswahl (index.html:1774)",
    "DeepSeek Direct": "Provider-Name der Boardroom-Auswahl (index.html:1775)",
    "OmniRoute Gateway": "Provider-Name der Boardroom-Auswahl (index.html:1776)",
    "DeepSeek": "Hersteller-Filterbutton des Preis-Katalogs (index.html:2008)",
    "OpenAI": "Hersteller-Filterbutton des Preis-Katalogs (index.html:2010)",
    "Anthropic": "Hersteller-Filterbutton des Preis-Katalogs (index.html:2011)",
    "Google": "Hersteller-Filterbutton des Preis-Katalogs (index.html:2012)",
    "Llama": "Hersteller-Filterbutton des Preis-Katalogs (index.html:2013)",
    # --- (c) Fachinhalt --------------------------------------------------
    "import os print('Sandbox-Verzeichnis:', os.getcwd()) print('Ausf\u00fchrung erfolgreich!')":
        "Fachinhalt: ausfuehrbares Python-Beispiel im Sandbox-Editor (index.html:2124), kein UI-String",
    # --- (a) Laufzeitwerte aus JS, Paket 2 (Z. 10000-10999) ---------------
    "datei.txt": "Laufzeitwert: operations_kanban.js setzt den Dateinamen in ops-task-attachment-name (index.html:10187)",
    "t-000000": "Laufzeitwert: operations_kanban.js setzt die Task-ID in ops-detail-badge-id (index.html:10294)",
    "Nicht zugewiesen": "Laufzeitwert: operations_kanban.js setzt den Agentennamen in ops-detail-assignee-name (index.html:10322)",
    "Auto": "Laufzeitwert: operations_kanban.js setzt Modell/Route in ops-detail-model-tag (index.html:10327)",
    "Keine Beschreibung hinterlegt.": "Laufzeitwert: operations_kanban.js ueberschreibt ops-detail-body mit der Aufgabenbeschreibung (index.html:10353)",
    "Status": "Laufzeitwert: operations_kanban.js setzt das Qualitaets-Badge ops-qr-badge (index.html:10417)",
    "Score: 85%": "Laufzeitwert: operations_kanban.js setzt den Score in ops-qr-score (index.html:10418)",
    "Geprüft von Katharina Völk": "Laufzeitwert: operations_kanban.js setzt den Reviewer-Namen in ops-qr-reviewer (index.html:10420)",
    "Noch nicht bewertet": "Laufzeitwert: operations_kanban.js setzt den Bewertungsstatus in ops-detail-feedback-status (index.html:10440)",
    "Keine Events aufgezeichnet.": "Laufzeitwert: operations_kanban.js rendert die Event-Liste (index.html:10479)",
    "Agent Name": "Laufzeitwert: operations_kanban.js setzt den Agentennamen in ond-name (index.html:10516)",
    "Tier 3": "Laufzeitwert: operations_kanban.js setzt die Hierarchie-Stufe in ond-tier-badge (index.html:10517)",
    "Spezialist": "Laufzeitwert: operations_kanban.js setzt die Rolle in ond-role (index.html:10520)",
    "Fachbereich": "Laufzeitwert: operations_kanban.js setzt den Fachbereich in ond-team-badge (index.html:10522)",
    "OmniRoute Auto": "Laufzeitwert: operations_kanban.js setzt die Modell-Route in ond-model (index.html:10666)",
    "OmniRoute": "Laufzeitwert: operations_kanban.js setzt den Provider in ond-provider (index.html:10670)",
    "0 aktiv": "Laufzeitwert: operations_kanban.js setzt die Aufgabenzahl in ond-tasks-count (index.html:10674)",
    "Profil wird geladen...": "Laufzeitwert: operations_kanban.js ueberschreibt ond-description mit dem Profiltext (index.html:10684)",
    "255+ Muster": "Laufzeitwert: prompt_studio.js setzt die Vorlagenzahl in tpl-count-badge (index.html:10836)",
    "Template Titel": "Laufzeitwert: prompt_studio.js setzt den Vorlagentitel in tpl-detail-title (index.html:10926)",
    "Zweck & Beschreibung": "Laufzeitwert: prompt_studio.js setzt die Beschreibung in tpl-detail-desc (index.html:10927)",
    # --- (b) Produktnamen, Paket 2 (Z. 10000-10999) -----------------------
    "OmniRoute (Smart Multi-Provider Routing)": "Provider-/Produktname OmniRoute der KI-Provider-Auswahl (index.html:10571), Markenbezeichnung",
    "Anthropic (Claude)": "Provider-/Produktname Anthropic (Claude) der KI-Provider-Auswahl (index.html:10573), Markenbezeichnung",
    "Google Gemini": "Provider-/Produktname Google Gemini der KI-Provider-Auswahl (index.html:10576), Markenbezeichnung",
    "Lokal / Ollama": "Provider-Label Lokal / Ollama der KI-Provider-Auswahl (index.html:10577), Produktname",
    "auto/best-free": "Modell-Identifier auto/best-free der Preset-Auswahl (index.html:10587)",
    "auto/best-reasoning": "Modell-Identifier auto/best-reasoning der Preset-Auswahl (index.html:10588)",
    "auto/best-coding": "Modell-Identifier auto/best-coding der Preset-Auswahl (index.html:10589)",
    "Claude 3.7": "Produktname Claude 3.7 der Preset-Auswahl (index.html:10590), Markenbezeichnung",
    "DeepSeek V3": "Produktname DeepSeek V3 der Preset-Auswahl (index.html:10591), Markenbezeichnung",
    "DeepSeek R1": "Produktname DeepSeek R1 der Preset-Auswahl (index.html:10592), Markenbezeichnung",
    "GPT-4o": "Produktname GPT-4o der Preset-Auswahl (index.html:10593), Markenbezeichnung",
    "o3-mini": "Modell-Identifier o3-mini der Preset-Auswahl (index.html:10594)",
    # --- Paket 3 (Z. 11000-11999): Prompt-Studio, Watchdog-Auditor,
    #     Ad-hoc-Sicherheitskanal, Brain-Theme-Studio ------------------
    'Kategorie': 'Laufzeitwert: prompt_studio.js:703 setzt die Kategorie in sp-detail-category (index.html:11272)',
    'Beschreibung': 'Laufzeitwert: prompt_studio.js:704 setzt die Beschreibung in sp-detail-desc (index.html:11284)',
    '0 / 25.000 Zeichen': 'Laufzeitwert: prompt_studio.js:953 setzt den Zeichenzaehler sp-upload-char-count (index.html:11304)',
    '7x registriert': 'Demo-Zaehler der Vorfallkarte, Laufzeitwert (index.html:11541)',
    '🐳 hermes': 'Container-Identifier hermes der Audit-Kachel auditor-tile-container (index.html:11558)',
    '⚡ tk_test_sandbox': 'Thread-Identifier tk_test_sandbox der Audit-Kachel auditor-tile-task (index.html:11564)',
    '12.500 tok/min': 'Messwert der Audit-Kachel auditor-tile-rate (index.html:11569)',
    '> 2026-08-27 19:41:17.185563315 | Messaging platforms + cron scheduler | > 2026-08-27 19:41:17.185564107 | Press Ctrl+C to stop | > 2026-08-27 19:41:17.185565209 | > 2026-08-27 19:41:17.185565590': 'Log-Datenblock (Zeitstempel/Telemetrie), auditor-incident-logs (index.html:11591)',
    'Dr. Hendrik Sasse': 'Personenname als Dialog-Titel (Eigenname, index.html:11643)',
    "Hallo! Bitte analysiere den aktuellen Watchdog-Sicherheitsvorfall bei Agent 'telegram_bot': Token Usage Limit Exceeded (14.200 > 10.000 tok/min).": 'Prompt-Inhalt: Nutzernachricht des Demo-Sicherheitskanals (index.html:11662)',
    'Hallo Dr. Sasse! Bitte analysiere als IT-Sicherheits-Auditor den folgenden System-Vorfall aus unseren Docker- und Watchdog-Logs: Betroffener Agent: telegram_bot • Docker-Container: hermes • Auslöser: Token Usage Limit Exceeded (14.200 > 10.000 tok/min) 🚨 Supervisor Log-Telemetrie: > 2026-08-27 19:41:17.185563315 | Messaging platforms + cron scheduler | > 2026-08-27 19:41:17.185564107 | Press Ctrl+C to stop | > 2026-08-27 19:41:17.185565209 | > 2026-08-27 19:41:17.185565590 Bitte erstelle eine technische Ursachenanalyse auf Deutsch und erkläre, welche Gegenmaßnahmen empfohlen werden.': 'Prompt-Inhalt: Nutzernachricht des Demo-Sicherheitskanals (index.html:11663)',
    'Technische Ursachenanalyse: Token-Limit-Überschreitung bei telegram_bot (Container: hermes)': 'Fachinhalt: gecachte Modellantwort des Demo-Sicherheitskanals (index.html:11671)',
    '2026-08-27 19:41:17 UTC': 'Fachinhalt: Fragment der gecachten Modellantwort (index.html:11675)',
    'Zeitpunkt:': 'Fachinhalt: Fragment der gecachten Modellantwort (index.html:11675)',
    'Ereignis:': 'Fachinhalt: Fragment der gecachten Modellantwort (index.html:11676)',
    'Token-Nutzung von 14.200 Tokens pro Minute überschreitet das Limit von 10.000 tokens/min.': 'Fachinhalt: Fragment der gecachten Modellantwort (index.html:11676)',
    '### 1. Einordnung des Vorfalls': 'Fachinhalt: Markdown-Ueberschrift der gecachten Modellantwort (index.html:11679)',
    'Der Telegram-Bot': 'Fachinhalt: Fragment der gecachten Modellantwort (index.html:11680)',
    '(Container': 'Fachinhalt: Fragment/Code-Identifier der gecachten Modellantwort (index.html:11681)',
    ') hat das konfigurierte Rate-Limit für API-Token überschritten. Dies deutet auf eine': 'Fachinhalt: Fragment/Code-Identifier der gecachten Modellantwort (index.html:11681)',
    'hermes': 'Fachinhalt: Fragment/Code-Identifier der gecachten Modellantwort (index.html:11681)',
    'hin. Die Log-Einträge aus Supervisor zeigen eine Kombination aus "Messaging platforms + cron scheduler", was auf einen möglichen automatisierten Cron-Job hindeutet, der Nachrichten oder Updates in hoher Frequenz verarbeitet.': 'Fachinhalt: Fragment/Code-Identifier der gecachten Modellantwort (index.html:11681)',
    'ineffiziente Nutzung der Telegram-API': 'Fachinhalt: Fragment/Code-Identifier der gecachten Modellantwort (index.html:11681)',
    'oder': 'Fachinhalt: Fragment/Code-Identifier der gecachten Modellantwort (index.html:11681)',
    'telegram_bot': 'Fachinhalt: Fragment/Code-Identifier der gecachten Modellantwort (index.html:11681)',
    'ungewöhnlich hohe Anfragefrequenz': 'Fachinhalt: Fragment/Code-Identifier der gecachten Modellantwort (index.html:11681)',
    '### 2. Mögliche technische Ursachen': 'Fachinhalt: Markdown-Ueberschrift der gecachten Modellantwort (index.html:11685)',
    '#### a) Fehlerhafte Schleifen oder Endlos-Rekursionen:': 'Fachinhalt: Fragment/Code-Identifier der gecachten Modellantwort (index.html:11687)',
    '-Schleife ohne Abbruchbedingung) könnte dazu führen, dass der Bot kontinuierlich API-Aufrufe an Telegram sendet. Besonders kritisch: Wenn der Bot auf eingehende Updates reagiert und dabei selbst neue Updates generiert (z. B. durch automatische Antworten), kann eine Feedback-Schleife entstehen.': 'Fachinhalt: Fragment/Code-Identifier der gecachten Modellantwort (index.html:11687)',
    'Ein Bug im Bot-Code (z. B. eine': 'Fachinhalt: Fragment/Code-Identifier der gecachten Modellantwort (index.html:11687)',
    'while': 'Fachinhalt: Fragment/Code-Identifier der gecachten Modellantwort (index.html:11687)',
    '#### b) Cron-Job-Überlastung:': 'Fachinhalt: Fragment/Code-Identifier der gecachten Modellantwort (index.html:11688)',
    '. Falls ein Cron-Job (z. B. alle 1-2 Minuten) den Bot dazu veranlasst, Nachrichten an Gruppen/Kanäle zu senden oder Daten abzurufen, summiert sich dies schnell auf das Token-Limit.': 'Fachinhalt: Fragment/Code-Identifier der gecachten Modellantwort (index.html:11688)',
    'Der Supervisor-Log erwähnt': 'Fachinhalt: Fragment/Code-Identifier der gecachten Modellantwort (index.html:11688)',
    'cron scheduler': 'Fachinhalt: Fragment/Code-Identifier der gecachten Modellantwort (index.html:11688)',
    # --- Paket 4 (Z. 12000-13525): Quartz-Pane, Plugin-Konfiguration,
    #     Bereichshilfe, Datei-Preview, Datenschutz-/LLM-Modal, Update-Dialog ---
    # (b) Schriftart- und Theme-Namen: Eigen- bzw. Produktnamen, in allen
    #     Sprachen identisch (Glossar-Regel "Markenform bleibt unuebersetzt")
    'Outfit': 'Schriftart-Name der Quartz-Font-Auswahl (index.html:12031/12046), Eigenname',
    'Cinzel (Archon OS)': 'Schriftart-Name mit Produktzusatz der Quartz-Font-Auswahl (index.html:12032)',
    'Schibsted Grotesk': 'Schriftart-Name der Quartz-Font-Auswahl (index.html:12033)',
    'Montserrat': 'Schriftart-Name der Quartz-Font-Auswahl (index.html:12034/12047)',
    'Plus Jakarta Sans': 'Schriftart-Name der Quartz-Font-Auswahl (index.html:12035/12043)',
    'Inter': 'Schriftart-Name der Quartz-Font-Auswahl (index.html:12036/12045)',
    'Playfair Display': 'Schriftart-Name der Quartz-Font-Auswahl (index.html:12037)',
    'Source Sans Pro': 'Schriftart-Name der Quartz-Font-Auswahl (index.html:12044)',
    'JetBrains Mono': 'Schriftart-Name der Quartz-Code-Font-Auswahl (index.html:12053)',
    'IBM Plex Mono': 'Schriftart-Name der Quartz-Code-Font-Auswahl (index.html:12054)',
    'Fira Code': 'Schriftart-Name der Quartz-Code-Font-Auswahl (index.html:12055)',
    'GitHub Dark': 'Theme-Name des Code-Highlightings (index.html:12170), Eigenname',
    'Dracula': 'Theme-Name des Code-Highlightings (index.html:12171), Eigenname',
    'Tokyo Night': 'Theme-Name des Code-Highlightings (index.html:12172), Eigenname',
    'Nord': 'Theme-Name des Code-Highlightings (index.html:12173/12183), Eigenname',
    'Catppuccin Macchiato': 'Theme-Name des Code-Highlightings (index.html:12174), Eigenname',
    'Monokai': 'Theme-Name des Code-Highlightings (index.html:12175), Eigenname',
    'Solarized Dark': 'Theme-Name des Code-Highlightings (index.html:12176), Eigenname',
    'GitHub Light': 'Theme-Name des Code-Highlightings (index.html:12182), Eigenname',
    'Nord Light': 'Theme-Name des Code-Highlightings (index.html:12183), Eigenname',
    'Solarized Light': 'Theme-Name des Code-Highlightings (index.html:12184), Eigenname',
    # (b) Technische Identifier
    '@plugin': 'Platzhalter der Plugin-Kennung plugin-cfg-id (index.html:12220), wertet das JS aus',
    'NousResearch/hermes-agent': 'Laufzeitwert: system_update_badge.js schreibt Branch/Upstream in upd-modal-branch (index.html:13481)',
    # (a) Laufzeitwerte aus JS
    'Wird geladen...': 'Ladezustand help-modal-purpose, wissensbibliothek.js:485 ueberschreibt den Knoten (index.html:12273)',
    'Empfohlene Frage laden...': 'Platzhalter help-modal-starter-text, wissensbibliothek.js:487 setzt den Text (index.html:12299)',
    'Lädt...': 'Laufzeitwert upd-modal-version, system_update_badge.js:95 (index.html:13474)',
    'Prüfe...': 'Laufzeitwert upd-modal-status-badge, system_update_badge.js:96 (index.html:13476)',
    # Beispielwerte in Platzhaltern (Demo-/Laufzeitdaten, kein Prosa-Text)
    '| Archon OS': 'Produktname-Suffix im Platzhalter quartz-cfg-page-suffix (index.html:12018)',
    'http://127.0.0.1:11434/v1': 'Beispiel-Endpunkt des lokalen LLM im Platzhalter (index.html:13389)',
    'llama3.2': 'Beispiel-Modellkennung im Platzhalter (index.html:13393)',
    'mis_...': 'Beispiel-Keyformat im Platzhalter (index.html:13415)',
    'mistral-large-latest': 'Beispiel-Modellkennung im Platzhalter (index.html:13421)',
}


def _index_open_entries() -> list[dict]:
    """Alle offenen Textknoten und Attribute der index.html (mit ``kind``)."""
    scanner = _load_scanner()
    result = scanner.scan(INDEX_HTML)
    entries = [dict(node, kind="node") for node in result.open_nodes]
    entries += [dict(entry, kind="attr") for entry in result.attr_candidates]
    for entry in entries:
        assert isinstance(entry["text"], str)
    return entries


def test_index_html_ranges_cover_every_open_entry():
    """Jeder offene Knoten liegt in genau einem DONE-/PENDING-Bereich."""
    entries = _index_open_entries()
    assert entries, "index.html hat keine offenen Knoten - Scanner oder Pfad falsch"

    # Die Bereiche werden unabhaengig von der Reihenfolge ihrer Deklaration
    # geprueft: DONE und PENDING duerfen in beliebiger Folge gefuellt werden
    # (Etappe 3 arbeitet Pakete ausserhalb der Dateireihenfolge ab).
    ranges = sorted(INDEX_HTML_RANGES_DONE + INDEX_HTML_RANGES_PENDING)
    overlaps = [
        (a, b) for a, b in zip(ranges, ranges[1:]) if b[0] <= a[1]
    ]
    assert not overlaps, f"Zeilenbereiche ueberlappen sich: {overlaps}"
    assert ranges[0][0] == 1, "erster Bereich muss bei Zeile 1 beginnen"

    total_lines = len(INDEX_HTML.read_text(encoding="utf-8").splitlines())
    assert ranges[-1][1] >= total_lines, (
        f"letzter Bereich endet bei {ranges[-1][1]}, Datei hat {total_lines} Zeilen"
    )

    uncovered = [
        f"{entry['kind']} Z.{entry['line']} {entry['text']!r}"
        for entry in entries
        if not any(first <= entry["line"] <= last for first, last in ranges)
    ]
    assert not uncovered, (
        f"{len(uncovered)} offene Knoten ausserhalb der DONE/PENDING-Bereiche:\n  "
        + "\n  ".join(uncovered)
    )


def test_index_html_exceptions_are_used():
    """Jede Ausnahme kommt in der Datei wirklich vor (kein toter Eintrag)."""
    seen = {entry["text"] for entry in _index_open_entries()}
    dead = sorted(set(INDEX_HTML_EXCEPTIONS) - seen)
    assert not dead, f"Ausnahmen ohne Vorkommen (veraltet): {dead}"


@pytest.mark.parametrize("first,last", INDEX_HTML_RANGES_DONE + INDEX_HTML_RANGES_PENDING)
def test_index_html_range_annotated(first, last):
    entries = [
        entry for entry in _index_open_entries() if first <= entry["line"] <= last
    ]
    done = (first, last) in INDEX_HTML_RANGES_DONE
    unexpected = [
        f"index.html:{entry['line']} <{entry['tag']}> {entry['text']!r}"
        for entry in entries
        if entry["text"] not in INDEX_HTML_EXCEPTIONS
    ]

    if not done:
        print(
            f"[i18n] index.html Z.{first}-{last}: {len(entries)} offen "
            f"({len(unexpected)} ohne Ausnahme, PENDING)"
        )
        return

    assert not unexpected, (
        f"{len(unexpected)} offene Textknoten/Attribute in Zeilen {first}-{last}:\n  "
        + "\n  ".join(unexpected)
    )


# --- (c5) Vollstaendige Annotation der eigenstaendigen Seiten ----------------
#
# static/hermes-hud/index.html (Route /hud) und static/mobile.html (Route
# /mobile) sind eigenstaendige Routen, keine Fragmente: beide laden
# /static/js/archon_i18n.js selbst (main.py:1546 mountet /static).
# Messquelle ist derselbe Scanner wie bei den Views. Offen bleiben nur die
# unten begruendeten Knoten. Analog zu den Views verlangt der Test eine
# Zuordnung jeder Datei - eine neue Seite braucht einen Eintrag.
#
# Zwei Gruppen von Ausnahmen:
# (1) mixed-Knoten: der Textknoten sitzt in einem Element, das bereits ein
#     Kind-Element traegt (Laufzeitwert im <b>, Status-Dot, Zaehler im
#     <span>). Die Engine setzt bei data-i18n den gesamten textContent und
#     wuerde das Kind loeschen - Anker sind hier ohne Markup-Aenderung
#     unmoeglich.
# (2) Laufzeitwerte (renderHUD / loadKanbanTasks / innerHTML-Neubau),
#     Marken- und Service-Identifier, Portnummern, Demo-Werte.

PAGES_ANNOTATED = {
    "static/hermes-hud/index.html": {
        "ACTIVE CONSCIOUSNESS": "mixed-Knoten: Status-Dot <span> als Kind, Anker wuerde ihn loeschen",
        "24h 12m": "Demo-Wert der Uptime-Anzeige (Wert + Einheit), kein JS-Update im Markup",
        "In:": "mixed-Knoten: Laufzeitwert im Kind <b id=val-prompt-tokens>",
        "128.4k": "Laufzeitwert val-prompt-tokens, renderHUD static/hermes-hud/index.html:394",
        "Out:": "mixed-Knoten: Laufzeitwert im Kind <b id=val-comp-tokens>",
        "55.8k": "Laufzeitwert val-comp-tokens, renderHUD static/hermes-hud/index.html:395",
        "142 ms": "Laufzeitwert val-latency, renderHUD static/hermes-hud/index.html:396",
        "Cost:": "mixed-Knoten: Kostenwert im Kind <b>",
        "Hermes Master Orchestrator": "Profil-/Agentenname (Identifier, agent_profiles.json)",
        "Hermes Deep Researcher": "Profil-/Agentenname (Identifier, agent_profiles.json)",
        "Hermes Senior Coder": "Profil-/Agentenname (Identifier, agent_profiles.json)",
        "Hermes Odysseus Strategist": "Profil-/Agentenname (Identifier, agent_profiles.json)",
        "Status:": "mixed-Knoten: Badge-Text im Kind <b>, Anker wuerde das <b> loeschen",
        "Type:": "mixed-Knoten: Typ-Wert im Kind <b>, Anker wuerde das <b> loeschen",
        "omniroute/best-reasoning": "Modell-Alias der Routing-Engine (Identifier)",
        "omniroute/free-forever": "Modell-Alias der Routing-Engine (Identifier)",
        "omniroute/deepseek-coder": "Modell-Alias der Routing-Engine (Identifier)",
        "[--:--:--] Initialisiere Telemetrie-Stream...":
            "Laufzeitknoten hud-log-stream, renderHUD static/hermes-hud/index.html:408",
        "Archon OS": "Markenform (Glossar: fix)",
        "Paperclip Orchestrator": "Service-Identifier des Docker-Fleet-Eintrags",
        "Hermes Dashboard Proxy": "Service-Identifier des Docker-Fleet-Eintrags",
        "Hermes WebUI": "Service-Identifier des Docker-Fleet-Eintrags",
        "Hermes Gateway": "Service-Identifier des Docker-Fleet-Eintrags",
        "OmniRoute Mesh": "Service-Identifier des Docker-Fleet-Eintrags",
        "Port 8501": "Portnummer (Sachwert)",
        "Port 3180": "Portnummer (Sachwert)",
        "Port 9119": "Portnummer (Sachwert)",
        "Port 8787": "Portnummer (Sachwert)",
        "Port 8420": "Portnummer (Sachwert)",
        "Port 20128": "Portnummer (Sachwert)",
        "RAG Chroma": "Produktname der Vektordatenbank (Wortmarke Chroma)",
    },
    "static/mobile.html": {
        "Archon Mobile": "Produkt-/App-Name (Wortmarke, identisch mit manifest.json 'name')",
        "👔 Robert (CEO)": "Profil-Pille, loadAgents() static/mobile.html:613-617 baut den Container neu",
        "👤 Founder": "Profil-Pille, loadAgents() static/mobile.html:613-617 baut den Container neu",
        "⚖️ Anwalt": "Profil-Pille, loadAgents() static/mobile.html:613-617 baut den Container neu",
        "💻 Dev Lead": "Profil-Pille, loadAgents() static/mobile.html:613-617 baut den Container neu",
        "📊 Analyst": "Profil-Pille, loadAgents() static/mobile.html:613-617 baut den Container neu",
        "Hallo! Ich bin dein mobiler Direktkontakt. Wähle oben ein Profil oder schreibe mir direkt einen Auftrag.":
            "mixed-Knoten: Kind <div class=msg-time>; zudem ersetzt loadQuickchatSession() den Container (static/mobile.html:639-645)",
        "Jetzt": "Laufzeitwert msg-time, sendMessage() static/mobile.html:657",
        "⚡ Freigaben (": "mixed-Knoten: Zaehler im Kind <span id=count-review>, Anker wuerde den Zaehler loeschen",
        "ARCHON-OS": "Container-Identifier der Log-Auswahl (value = Anzeige)",
        "hermes": "Container-Identifier der Log-Auswahl (value = Anzeige)",
        "n8n": "Container-Identifier der Log-Auswahl (value = Anzeige)",
    },
}


def test_standalone_pages_fully_annotated():
    scanner = _load_scanner()
    problems: list[str] = []

    for rel_path, exceptions in PAGES_ANNOTATED.items():
        result = scanner.scan(REPO_ROOT / rel_path)
        used: set[str] = set()
        unexpected: list[str] = []

        for node in result.open_nodes:
            if node["text"] in exceptions:
                used.add(node["text"])
            else:
                unexpected.append(f"{rel_path}:{node['line']} <{node['tag']}> {node['text']!r}")
        for entry in result.attr_candidates:
            if entry["text"] in exceptions:
                used.add(entry["text"])
            else:
                unexpected.append(
                    f"{rel_path}:{entry['line']} @{entry['attr']} {entry['text']!r}"
                )

        dead = set(exceptions) - used
        if dead:
            problems.append(f"{rel_path}: Ausnahmen ohne Vorkommen: {sorted(dead)}")
        if unexpected:
            problems.append(
                f"{rel_path}: {len(unexpected)} offene Knoten/Attribute:\n  "
                + "\n  ".join(unexpected)
            )

    assert not problems, "\n".join(problems)


# --- (d) Validierung gegen static/locales/schema.json -----------------------
#
# Bewusst kleiner JSON-Schema-Kern (draft-07-Teilmenge), weil im Projekt-venv
# kein jsonschema installiert ist: $ref, anyOf, type, properties, required,
# additionalProperties, patternProperties, minLength, minProperties.
# Alles, was das Schema nicht kennt, wird ignoriert - nicht "akzeptiert".

_JSON_TYPES = {
    "object": dict,
    "string": str,
    "array": list,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
}


def _resolve_ref(ref: str, root: dict) -> dict:
    assert ref.startswith("#/"), f"nur lokale Refs unterstuetzt: {ref}"
    node = root
    for part in ref[2:].split("/"):
        node = node[part]
    return node


def _validate(instance, schema: dict, root: dict, path: str = "$") -> list[str]:
    if "$ref" in schema:
        return _validate(instance, _resolve_ref(schema["$ref"], root), root, path)

    if "anyOf" in schema:
        branches = [_validate(instance, branch, root, path) for branch in schema["anyOf"]]
        if all(branch for branch in branches):
            expected = [branch.get("type") or branch.get("$ref") for branch in schema["anyOf"]]
            return [f"{path}: passt zu keinem anyOf-Zweig {expected}"]
        return []

    errors = []
    declared = schema.get("type")
    if declared is not None:
        allowed = declared if isinstance(declared, list) else [declared]
        if not any(isinstance(instance, _JSON_TYPES[name]) for name in allowed):
            return [f"{path}: Typ {type(instance).__name__}, erwartet {allowed}"]

    if isinstance(instance, str) and "minLength" in schema:
        if len(instance) < schema["minLength"]:
            errors.append(f"{path}: leerer String (minLength {schema['minLength']})")

    if isinstance(instance, dict):
        properties = schema.get("properties", {})
        pattern_properties = schema.get("patternProperties", {})
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{path}: Pflichtschluessel '{key}' fehlt")
        if "minProperties" in schema and len(instance) < schema["minProperties"]:
            errors.append(f"{path}: zu wenige Schluessel (minProperties {schema['minProperties']})")
        for key, value in instance.items():
            matched = False
            if key in properties:
                matched = True
                errors.extend(_validate(value, properties[key], root, f"{path}.{key}"))
            for pattern, subschema in pattern_properties.items():
                if re.search(pattern, key):
                    matched = True
                    errors.extend(_validate(value, subschema, root, f"{path}.{key}"))
            if not matched:
                extra = schema.get("additionalProperties", True)
                if extra is False:
                    errors.append(f"{path}: unbekannter Schluessel '{key}'")
                elif isinstance(extra, dict):
                    errors.extend(_validate(value, extra, root, f"{path}.{key}"))

    return errors


def test_catalogs_validate_against_schema():
    schema = load_catalog(SCHEMA_PATH)
    assert "$schema" in schema and "properties" in schema, "schema.json unbrauchbar"

    problems = []
    for path in locale_files():
        errors = _validate(load_catalog(path), schema, schema)
        problems.extend(f"{path.name} {error}" for error in errors)

    assert not problems, "Kataloge verletzen schema.json:\n" + "\n".join(problems)


def test_schema_reserves_plural_skeleton():
    schema = load_catalog(SCHEMA_PATH)
    plural = schema["x-archon-plural"]

    assert plural["suffixes"] == ["_one", "_few", "_many", "_other"]
    assert set(plural["categories"]) == set(LANGUAGES)
    assert plural["categories"]["ru"] == ["one", "few", "many", "other"]
    assert plural["categories"]["ja"] == ["other"]
    assert plural["populated"] is False, "Plural-Skeleton wird in Etappe 2 nicht befuellt"

    reserved = re.compile(plural["key_suffix_pattern"])
    for path in locale_files():
        for key in collect_messages(load_catalog(path)):
            assert not reserved.search(key), (
                f"{path.name}: Schluessel '{key}' nutzt reserviertes Plural-Suffix; "
                "Plural wird als Objekt unter dem Nachrichten-Schluessel gefuehrt"
            )


# --- (e) Glossar-Abgleich (Drift-Assertion) ---------------------------------

def test_glossary_matches_catalogs():
    glossary = load_catalog(GLOSSARY_PATH)
    assert glossary["reference_language"] == REFERENCE_LANG
    terms = glossary["terms"]
    assert len(terms) == 20, f"Glossar hat {len(terms)} Begriffe, erwartet 20"

    catalogs = {lang: load_catalog(LOCALES_DIR / f"{lang}.json") for lang in LANGUAGES}
    problems = []

    for term in terms:
        translations = term["translations"]
        assert set(translations) == set(LANGUAGES), f"{term['id']}: Sprachset unvollstaendig"
        for lang in LANGUAGES:
            assert translations[lang].strip(), f"{term['id']}: {lang} leer"
        if term["fixed"]:
            assert len(set(translations.values())) == 1 or term["id"] == "token", (
                f"{term['id']}: als fix markiert, aber uebersetzt"
            )
        for key in term["keys"]:
            for lang in LANGUAGES:
                value = resolve(catalogs[lang], key)
                if not isinstance(value, str):
                    problems.append(f"{term['id']}: {lang}.{key} fehlt")
                elif translations[lang].casefold() not in value.casefold():
                    problems.append(
                        f"{term['id']}: {lang}.{key}='{value}' "
                        f"enthaelt nicht '{translations[lang]}'"
                    )

    assert not problems, "Glossar-Drift:\n" + "\n".join(problems)
