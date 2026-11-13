"""Unveraenderliche Modul-Konstanten aus main.py (A5-Etappe 1).

Enthaelt ausschliesslich unveraenderliche Werte (str, tuple). Bewusst NICHT
hier: Listen, Dicts, Sets und Objekte — mutabler Modul-State bleibt in main.py,
weil eine Neuzuweisung die Import-Bindung brechen wuerde (Fallstrick 24).

Auch NICHT hier: die Pfad-Konstanten unter MEMORY_DIR / WORKSPACE_DIR /
DATA_DIR. Die gehoeren zur B10-Config-Schicht und brauchen dort eine eigene
Baseline (18 Namen, 138 Leser-Stellen) — siehe docs/A5_INVENTUR.md.

Einzige Ausnahme: STUDIO_BG_UPLOAD_DIR. Das ist ein statisches Asset-
Verzeichnis, kein Datenpfad. Es wird ueber APP_ROOT abgeleitet, weil ein
__file__-Bezug aus archon/core/ heraus auf /app/archon/core/static zeigen
wuerde — der aufgeloeste Wert bleibt so identisch zum Vorstand.
"""

from __future__ import annotations

import os

from archon.core.runtime import APP_ROOT

# --- Auth-Gate (wirkt nur, wenn settings.auth.enabled = true) --------------
# Oeffentliche Praefixe ohne Login. Bewusst Tupel, nicht Set: Sets sind mutabel.
_AUTH_PUBLIC_PREFIXES = ("/static/", "/api/auth/login", "/api/auth/status", "/docs", "/redoc")

# API-Pfade, die *unter* einem oeffentlichen Prefix liegen und deshalb wie
# "/api/" behandelt werden (401 statt Durchreichen). F1/R-34:
# "/static/hermes-webui/api/*" reicht an das Hermes-Dashboard durch, das dabei
# den internen Session-Token einsetzt — das ist API, kein Asset. "/static/" als
# Ganzes bleibt oeffentlich, weil die App-Shell (index.html, JS, CSS) ohne Login
# laden muss; ein Verengen auf "/static/assets/" wuerde sie aussperren.
_AUTH_API_PREFIXES = ("/static/hermes-webui/api/",)

# Nicht-/api-Pfade, die trotzdem geschuetzt sein muessen: eingebettete
# Admin-Oberflaechen (n8n-Editor, OmniRoute-Konsole) und App-Shells.
_AUTH_PROTECTED_PREFIXES = (
    "/omniroute-proxy",
    "/n8n-proxy",
    "/anythingllm-proxy",
    "/rest/",
    "/hud",
    "/mobile",
    "/m",
    "/v2",
)

# Erlaubte Entscheidungs-Typen fuer den Kanban-Entscheidungspfad.
_DECISION_TYPEN = ("delegation_review", "synthesis_freigabe",
                   "mission_freigabe", "permission_gate")

# Delegations-Protokoll, das jedem Agenten-Prompt vorangestellt wird.
DELEGATION_PROTOCOL_PROMPT = """

=== DELEGATIONSPROTOKOLL (Engine v2) ===
Wenn eine Aufgabe an einen anderen Agenten delegiert werden soll, MUSST du dafür ausschließlich
den folgenden JSON-Block in deine Antwort schreiben (valides JSON, exakte Feldnamen):

```delegation
{"ziel_agent": "<agent_id>", "auftrag": "<präzise Aufgabenbeschreibung mit Kontext>", "modell": "<auto/best-reasoning|auto/best-coding|auto/best-free|auto/best-vision>", "prioritaet": "normal|hoch", "reasoning_level": "off|minimal|low|medium|high|max", "parent_project_id": "<nur bei Zerlegung in mehrere Teilauftraege: IMMER dieselbe id fuer alle Bloecke, z.B. projekt-immobilienplattform>"}
```

Regeln für reasoning_level:
- Wähle den Denkgrad angepasst an die Komplexität des Auftrags:
  * "off": Für einfache Routine-Aufgaben, Formatierungen oder Textablagen (0 Tokens Denkzeit, maximal schnell & billig).
  * "minimal": Für simple Überprüfungen oder kurze Standardrecherchen (~1k Tokens).
  * "low": Für Standardarbeiten mit kurzer Plausibilitätsprüfung (~2k Tokens).
  * "medium": Ausgewogener Standard für normale Fachaufgaben (~4k Tokens).
  * "high": Für fundierte Code-Architektur, Refactoring oder Finanzmodellierung (~8k Tokens).
  * "max": Für hochkritische strategische Memos, Rechtsgutachten oder System-Apex-Entscheidungen (~16k Tokens).

Wichtige Regeln für Delegation & Berichte:
- ziel_agent = exakte Agent-ID, nie der Anzeigename. Mehrere Blöcke für Parallelaufträge erlaubt.
- KEINE SELBST-DELEGATION: Delegiere NIEMALS an dich selbst (z.B. niemals an deine eigene Agent-ID). Willst du Zwischenergebnisse zusammenfassen, auswerten oder freigeben, mache dies direkt in deiner eigenen Antwort.
- KEINE EIGENEN QUITTUNGEN TEXTEN: Schreibe nach einem ```delegation ...``` Block NIEMALS selbst eine Quittung wie 'DELEGATION QUITTUNG: Auftrag erfolgreich delegiert...'. Die Quittung wird ausschließlich und automatisch vom Backend erzeugt und eingefügt.
- KEINE SCHEIN-AUFTRÄGE: Erfinde keine Aufgaben wie 'Registriere Projekt im System' oder 'Parent-Project-ID registrieren'. Projekte existieren automatisch über ihren Ordner in `01_PROJEKTE/`. Wenn ein Agent Kontext benötigt, gib ihm den genauen Projektpfad oder die Quelldateien im Auftrag mit.
- KEIN ROHES HTML IM CHAT ZUM SELBSTSPEICHERN: Wenn ein Abschlussbericht oder HTML-Dokument erstellt wird, gebe niemals seitenweise rohen HTML-Code im Chat aus mit der Aufforderung, der Nutzer solle diesen manuell in Notepad kopieren! Erstelle stattdessen eine lesbare Zusammenfassung mit Markdown direkt im Chat und speichere die vollwertige HTML-Datei im Projektordner (`01_PROJEKTE/<projekt>/03_Endprodukte/<datei>.html`).
- ZERLEGST du EINEN Auftrag in MEHRERE Teilaufträge: gib in JEDEM Block dieselbe `parent_project_id` an (z.B. "projekt-<kurzname>"). Das sammelt alle Teilergebnisse automatisch in der Projektstruktur.
- Status-Verfolgung über die Task-ID: Kanban in_progress = läuft, review = Ergebnis da, blocked = Problem.
=== ENDE DELEGATIONSPROTOKOLL ==="""

# CSS Live Studio: Hintergrund-Bild-Upload (User-Wunsch 10.10.2026).
# Ueber APP_ROOT statt __file__, damit der Pfad aus archon/core/ stimmt.
STUDIO_BG_UPLOAD_DIR = os.path.join(APP_ROOT, "static", "uploads")

__all__ = (
    "_AUTH_PUBLIC_PREFIXES",
    "_AUTH_PROTECTED_PREFIXES",
    "_DECISION_TYPEN",
    "DELEGATION_PROTOCOL_PROMPT",
    "STUDIO_BG_UPLOAD_DIR",
)
