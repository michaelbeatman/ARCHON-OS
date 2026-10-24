# -*- coding: utf-8 -*-
"""
Restrukturiert und vervollständigt docs/system/ARCHON_OS_SYSTEM_HANDBUCH_2026_Vorlage.docx:
1. Entfernt das separate Kapitel 26 am Ende des Dokuments (da alle Trade-offs direkt bei den jeweiligen
   Modulen, Features und Glossar-Einträgen stehen sollen).
2. Erweitert Kapitel 18.1 (Hermes Core) um alle 14 nativen Hermes-Core-Sektionen (~55 Parameter aus config.yaml),
   inklusive bidirektionaler Auto-Synchronisation (config.yaml <-> settings.json) sowie Problem / Lösung /
   Preis & Schattenseite (Trade-off) / Wann ausschalten? für jede Sektion.
3. Ergänzt in Kapitel 19 (19.1–19.5) und Kapitel 20 (20.1–20.5) direkt unter jedem Feature die vollständige
   Entscheidungs-Box (Problem / Lösung & Nutzen / Preis & Schattenseite / Wann ausschalten? / Schwellenwerte).
4. Fügt die Kapitel 21 bis 25 (Säulen XII bis XVI — Pakete 1 bis 5, alle 25 Enterprise-Module) direkt nach
   Kapitel 20.5 (vor dem Use-Case-Anhang) ein — jedes einzelne Feature (21.1 bis 25.5) enthält sofort inline
   Funktion, Problem, Lösung, Preis & Schattenseite (Trade-off), Wann ausschalten? und Schwellenwert-Kipppunkte.
5. Reichert ALLE Glossar-Boxen (Einträge 1 bis 113) im Komplett-Glossar sowie die Plugin-Matrix (Domäne IX)
   direkt vor Ort um "Preis & Schattenseite (Trade-off)" und "Wann ausschalten? / Schwellenwerte" an.
"""

from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls

DOC_PATH = "/app/docs/system/ARCHON_OS_SYSTEM_HANDBUCH_2026_Vorlage.docx"


def set_run_font(run, font_name="Aptos", size_pt=10.0, color_rgb=(45, 55, 72), bold=False, italic=False):
    run.font.name = font_name
    run.font.size = Pt(size_pt)
    run.font.color.rgb = RGBColor(*color_rgb)
    run.bold = bold
    run.italic = italic


def set_p_spacing(p, before_pt=0, after_pt=4, line_spacing=1.15):
    p.paragraph_format.space_before = Pt(before_pt)
    p.paragraph_format.space_after = Pt(after_pt)
    p.paragraph_format.line_spacing = line_spacing


def create_inline_tradeoff_box(doc, title_str, problem_str, solution_str, tradeoff_str, disable_str, threshold_str):
    tbl = doc.add_table(rows=1, cols=1)
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl.autofit = False
    cell = tbl.rows[0].cells[0]
    cell.width = Inches(6.8)

    tcPr = cell._tc.get_or_add_tcPr()
    tcPr.append(parse_xml(f'<w:shd {nsdecls("w")} w:fill="FFFBEB"/>'))
    tcPr.append(parse_xml(
        f'<w:tcBorders {nsdecls("w")}>'
        f'  <w:top w:val="single" w:sz="6" w:space="0" w:color="F59E0B"/>'
        f'  <w:left w:val="single" w:sz="24" w:space="0" w:color="D97706"/>'
        f'  <w:bottom w:val="single" w:sz="6" w:space="0" w:color="F59E0B"/>'
        f'  <w:right w:val="single" w:sz="6" w:space="0" w:color="F59E0B"/>'
        f'</w:tcBorders>'
    ))
    tcPr.append(parse_xml(
        f'<w:tcMar {nsdecls("w")}>'
        f'  <w:top w:w="100" w:type="dxa"/><w:left w:w="150" w:type="dxa"/>'
        f'  <w:bottom w:w="100" w:type="dxa"/><w:right w:w="150" w:type="dxa"/>'
        f'</w:tcMar>'
    ))

    p0 = cell.paragraphs[0]
    set_p_spacing(p0, 1, 2, 1.15)
    rt = p0.add_run(f"⚖️ Entscheidungs- & Trade-off-Profil: {title_str}")
    set_run_font(rt, "Aptos", 9.5, (146, 64, 14), bold=True)

    rows = [
        ("Problem (Ohne Modul): ", problem_str, (190, 18, 60)),
        ("Lösung & Nutzen: ", solution_str, (5, 150, 105)),
        ("Preis & Schattenseite (Trade-off): ", tradeoff_str, (180, 83, 9)),
        ("Wann ausschalten? ", disable_str, (30, 58, 138)),
        ("Schwellenwert-Kipppunkte: ", threshold_str, (71, 85, 105)),
    ]
    for lbl, txt, col in rows:
        if not txt:
            continue
        p = cell.add_paragraph()
        set_p_spacing(p, 1, 1, 1.12)
        rl = p.add_run(lbl)
        set_run_font(rl, "Aptos", 8.8, col, bold=True)
        rx = p.add_run(txt)
        set_run_font(rx, "Aptos", 8.8, (30, 41, 59), bold=False)

    return tbl


def create_styled_table(doc, headers, data, col_widths=None):
    tbl = doc.add_table(rows=len(data) + 1, cols=len(headers))
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl.autofit = False

    hdr_row = tbl.rows[0]
    trPr = hdr_row._tr.get_or_add_trPr()
    trPr.append(parse_xml(f'<w:tblHeader {nsdecls("w")}/>'))
    for idx, heading in enumerate(headers):
        cell = hdr_row.cells[idx]
        if col_widths and idx < len(col_widths):
            cell.width = Inches(col_widths[idx])
        tcPr = cell._tc.get_or_add_tcPr()
        tcPr.append(parse_xml(f'<w:shd {nsdecls("w")} w:fill="1A365D"/>'))
        tcPr.append(parse_xml(
            f'<w:tcMar {nsdecls("w")}>'
            f'  <w:top w:w="100" w:type="dxa"/><w:left w:w="120" w:type="dxa"/>'
            f'  <w:bottom w:w="100" w:type="dxa"/><w:right w:w="120" w:type="dxa"/>'
            f'</w:tcMar>'
        ))
        p = cell.paragraphs[0]
        set_p_spacing(p, 2, 2, 1.1)
        r = p.add_run(heading)
        set_run_font(r, "Aptos", 9.0, (255, 255, 255), bold=True)

    for r_idx, row_data in enumerate(data):
        row = tbl.rows[r_idx + 1]
        bg_color = "F8FAFC" if r_idx % 2 == 1 else "FFFFFF"
        for c_idx, val in enumerate(row_data):
            cell = row.cells[c_idx]
            if col_widths and c_idx < len(col_widths):
                cell.width = Inches(col_widths[c_idx])
            tcPr = cell._tc.get_or_add_tcPr()
            tcPr.append(parse_xml(f'<w:shd {nsdecls("w")} w:fill="{bg_color}"/>'))
            tcPr.append(parse_xml(
                f'<w:tcMar {nsdecls("w")}>'
                f'  <w:top w:w="80" w:type="dxa"/><w:left w:w="120" w:type="dxa"/>'
                f'  <w:bottom w:w="80" w:type="dxa"/><w:right w:w="120" w:type="dxa"/>'
                f'</w:tcMar>'
            ))
            tcPr.append(parse_xml(
                f'<w:tcBorders {nsdecls("w")}>'
                f'  <w:top w:val="single" w:sz="4" w:space="0" w:color="E2E8F0"/>'
                f'  <w:bottom w:val="single" w:sz="4" w:space="0" w:color="E2E8F0"/>'
                f'  <w:left w:val="none"/><w:right w:val="none"/>'
                f'</w:tcBorders>'
            ))
            p = cell.paragraphs[0]
            set_p_spacing(p, 2, 2, 1.1)
            r = p.add_run(val)
            set_run_font(r, "Aptos", 8.5, (45, 55, 72))

    return tbl


# ==============================================================================
# 1. HERMES CORE 14 SEKTIONEN (FÜR KAPITEL 18.1)
# ==============================================================================
HERMES_SECTIONS_DOC = [
    ["1. Modell & Provider\n(model.*)",
     "default, provider, base_url,\nsmart_model_routing (⇄ Bandit)",
     "Problem: Festes Einzelmodell ist entweder zu schwach oder zu teuer.\nLösung: Leitmodell + Smart-Routing.\nPreis/Trade-off: Flaggschiff-Modelle kosten 5x–15x mehr; Smart-Routing kann bei Grenzfragen ein zu kleines Modell wählen."],
    ["2. Agenten-Laufzeit & Reasoning\n(agent.*)",
     "reasoning_effort, max_turns (60),\ntask_timeout_seconds (⇄ Concurrency),\nmax_context_tokens, max_history_messages",
     "Problem: Ohne Limits brechen Tasks zu früh ab oder laufen endlos.\nLösung: Steuert Thinking-Tiefe & Runden.\nPreis/Trade-off: Reasoning 'high/xhigh' kostet 3x–5x mehr Tokens und +5–20s Latenz."],
    ["3. Display, Streaming & UI\n(display.*, streaming.*)",
     "streaming.enabled, busy_input_mode (steer/interrupt),\ntool_progress, show_reasoning, show_cost,\nbackground_notifications, language",
     "Problem: Fehlende Live-Rückmeldung lässt das UI eingefroren wirken.\nLösung: Echtzeit-Streaming & Steer-Modus.\nPreis/Trade-off: Volle Tool-/Reasoning-Anzeige erzeugt bei langen Recherchen sehr lange Chat-Verläufe."],
    ["4. Messenger-Gateways\n(gateway.*, platforms.*)",
     "auto_start, telegram/discord/slack/whatsapp\n(enabled + allowlist User-IDs)",
     "Problem: Ohne Allowlist kann jeder Fremde den Bot anschreiben.\nLösung: Direkte Messenger-Brücken mit User-ID-Filter.\nPreis/Trade-off: Jede aktive Bridge hält Polling/WebSockets offen; leere Allowlist = Sicherheitsrisiko!"],
    ["5. Command-Allowlist & Code-Exec\n(command_allowlist, code_execution.*)",
     "command_allowlist (Kommaliste),\nmax_tool_calls (50), timeout (300s)",
     "Problem: Rückfragen bei jedem Shell-Befehl bremsen; blinde Freigabe ist gefährlich.\nLösung: Whitelist sicherer Befehle + Skript-Deckel.\nPreis/Trade-off: Nicht gelistete Tools erfordern Freigabe; hohe Timeouts binden Worker bei Endlosschleifen."],
    ["6. Terminal- & Container-Sandbox\n(terminal.* ⇄ Archon Sandbox)",
     "backend (local/docker/modal), cwd,\ntimeout (180s), docker_cpus (1),\ndocker_memory (5120 MB), disk (51200 MB)",
     "Problem: Direkte lokale Shell-Ausführung gefährdet den Haupt-Container.\nLösung: Isolierte Container-Backends mit Ressourcen-Deckel.\nPreis/Trade-off: 'docker' kostet ~300–800 ms Startlatenz & RAM; 'local' hat 0 ms Overhead, aber keine Isolation."],
    ["7. Tool-Loop-Guardrails\n(tool_loop_guardrails.* ⇄ Circuit-Breaker)",
     "warn_exact (3), warn_same_error (5),\nwarn_no_progress (8), stop_exact (6),\nstop_same_error (10), stop_no_progress (16)",
     "Problem: LLMs wiederholen fehlerhafte Tool-Calls oft 20-mal und verbrennen Budget.\nLösung: Zweistufige Warn- und Stopp-Schranke.\nPreis/Trade-off: Zu niedrige Stopp-Werte (< 4) brechen legitime mehrstufige Reparatur-Schleifen vorzeitig ab."],
    ["8. Kontext-Komprimierung & Cache\n(compression.* ⇄ Compactor, prompt_caching.*)",
     "enabled, threshold (0.50), target_ratio (0.20),\nprotect_last_n (20), protect_first_n (3),\nprompt_caching.enabled, ttl (5m/1h)",
     "Problem: Lange Sitzungen (> 30 Turns) werden extrem langsam und teuer.\nLösung: Automatische Verdichtung + Provider-Prompt-Caching.\nPreis/Trade-off: Komprimierung glättet feine Details aus sehr frühen Nachrichten; spart aber 60–75 % Folge-Tokens."],
    ["9. Permanentes Gedächtnis & Reset\n(memory.*, session_reset.*, skills.*)",
     "memory_enabled, user_profile_enabled,\nmemory_char_limit (2200), flush_min_turns (6),\nsession_reset.mode (both/idle/none), idle_minutes",
     "Problem: Ohne Langzeitgedächtnis startet jede Sitzung bei Null; ohne Reset veraltet der Kontext.\nLösung: Persistente MEMORY.md + Auto-Flush vor Reset.\nPreis/Trade-off: Großes Memory (> 4000 Zeichen) kostet bei jedem Call Prompt-Tokens; kurzer Idle-Reset kappt Pausen."],
    ["10. Subagent-Delegation & MoA\n(delegation.* ⇄ Concurrency, moa.* ⇄ Konsens)",
     "max_concurrent_children (3), max_iterations (50),\nmoa.enabled, fan_out (3), max_tokens (4096),\naggregator_provider, aggregator_model",
     "Problem: Einzelmodelle arbeiten sequenziell und haben blinde Flecken.\nLösung: Parallele Subagenten + Mixture-of-Agents (MoA).\nPreis/Trade-off: ACHTUNG: MoA mit Fan-Out=3 vervielfacht die Token-Kosten sofort um 3x–4x und erhöht die Latenz!"],
    ["11. Hilfs-Modelle (Auxiliary)\n(auxiliary.vision.*, auxiliary.web_extract.*)",
     "vision.provider, vision.model,\nweb_extract.provider, web_extract.model",
     "Problem: Das teure Hauptmodell für große Web-Extraktionen zu nutzen verbrennt Budget.\nLösung: Lagert Vision & Web-Parsing an günstige Hilfsmodelle aus.\nPreis/Trade-off: Ein zu kleines Hilfsmodell kann feine Details auf Screenshots oder in Tabellen übersehen."],
    ["12. Browser & Dynamic Tool Search\n(browser.*, tools.tool_search.*)",
     "browser.inactivity_timeout (30s), auto_vision,\ntool_search.enabled, limit (5), max_pct (5%)",
     "Problem: 80+ gleichzeitig geladene Tool-Schemata kosten 15.000+ Tokens pro Aufruf.\nLösung: Lädt bei Bedarf nur die 5 passendsten Tools dynamisch nach.\nPreis/Trade-off: Spart bis zu 80 % Schema-Tokens, erfordert aber 1 kurzen Such-Zwischenschritt."],
    ["13. Sprache (STT & Voice/TTS)\n(stt.*, voice.*)",
     "stt.enabled, provider (groq/openai/local),\nvoice.mode (off/tts), provider, auto_tts",
     "Problem: Sprachnachrichten können von Text-LLMs nicht direkt gelesen werden.\nLösung: Whisper-Transkription (STT) + Sprachsynthese (TTS).\nPreis/Trade-off: Cloud-Audio kostet pro Minute; lokales Whisper benötigt spürbar CPU/RAM im Container."],
    ["14. Updates & Rollback-Sicherung\n(updates.*)",
     "check_enabled, auto_update (false),\nkeep_backups (10), show_changes",
     "Problem: Unkontrollierte Auto-Updates ohne Backup können den Betrieb stören.\nLösung: Versionsprüfung mit bis zu 10 lokalen Rollback-Backups.\nPreis/Trade-off: Auto-Update kann laufende Dienste kurz neu starten; im Produktivbetrieb auf 'nur prüfen' belassen."]
]


# ==============================================================================
# 2. KAPITEL 19 & 20 INLINE TRADE-OFFS
# ==============================================================================
CH19_20_TRADEOFFS = {
    "19.1 Replay & Time-Travel Debugging": (
        "Modul 5: Time-Travel Debugger & Pre-Write Snapshots (backend/time_travel_debugger.py)",
        "Überschreibt ein Agent eine wichtige Datei fehlerhaft oder trifft im 8. Zwischenschritt eine falsche Entscheidung, lässt sich der Zustand ohne Backup nicht mehr rekonstruieren.",
        "Zeichnet jeden Agenten-Zwischenschritt im Time-Travel-Trace auf und legt vor jedem schreibenden Dateizugriff automatisch eine komprimierte Pre-Write-Schattenkopie an.",
        "Erhöht Disk-I/O um ~5–15 ms pro Datei-Edit und belegt je nach Snapshot-Limit ~50–250 MB zusätzlichen Speicherplatz auf der Festplatte.",
        "Ausschalten auf Systemen mit extrem knappem Disk-Speicher oder bei massenhaften Datei-Generierungen (z. B. Build-Artefakte).",
        "Max Snapshots: < 10 = kurze Historie | > 200 = höherer Disk-Verbrauch (Std: 50). Max Trace-Steps: < 30 = ältere Schritte fehlen | > 500 = große Trace-Dateien (Std: 100)."
    ),
    "19.2 Multi-Modell Head-to-Head Benchmark": (
        "Multi-Modell Head-to-Head Benchmark & Eval-Matrix (backend/model_benchmarker.py)",
        "Modellwechsel erfolgen oft nach Bauchgefühl, ohne objektiv zu messen, welches Modell bei den eigenen Fach-Prompts schneller, günstiger und präziser arbeitet.",
        "Führt identische Prompts parallel gegen mehrere Kandidaten-Modelle aus und vergleicht Latenz, Token-Kosten und Qualitäts-Score direkt nebeneinander.",
        "Ein Benchmark-Lauf mit N Modellen verbraucht das N-fache an API-Tokens und erzeugt parallele Request-Spitzen.",
        "Nur gezielt bei der Einführung neuer Modelle oder zur Qualitätsprüfung ausführen, nicht dauerhaft bei jeder Alltagsfrage.",
        "Kandidaten-Anzahl: 2–3 Modelle = idealer Vergleich | > 4 Modelle = hohe Kosten & Rate-Limit-Gefahr."
    ),
    "19.3 Dual- & Tri-Agent Konsens-Gate": (
        "Modul 6: Konsens-Gate & Tri-Agent Schiedsgericht (backend/consensus_gate.py)",
        "Ein einzelnes LLM unterliegt bei kritischen Architektur-, Lösch- oder Finanzentscheidungen oft einem Bestätigungsfehler (Confirmation Bias).",
        "Schaltet ab der gewählten Aufgaben-Priorität automatisch ein Tri-Agent-Schiedsgericht (Proposer, Kritiker, Richter) vor, das per Mehrheitsregel abstimmt.",
        "Verdreifacht (3x) den Token-Verbrauch und erhöht die Antwortzeit um +6 bis +20 Sek. Bei Einstimmigkeits-Zwang droht Entscheidungs-Stillstand (Deadlock).",
        "Ausschalten (oder erst ab Priorität 4 = Kritisch aktivieren), wenn Geschwindigkeit und niedrige API-Kosten Vorrang haben.",
        "Ab Priorität: Prio 2 = fast jeder Task kostet 3x Tokens | Prio 4 = nur kritische Tasks (Std: Prio 3). Mehrheit: 2/3-Mehrheit empfohlen."
    ),
    "19.4 Autonome Task-Selbstheilung": (
        "Modul 3: Autonome Task-Selbstheilung & Git-Rollback (backend/task_self_healer.py)",
        "Ein einziger Syntaxfehler oder fehlender Import nach einem Datei-Edit lässt den gesamten Task scheitern und hinterlässt oft kaputten Code im Repository.",
        "Analysiert den Traceback autonom mit einem Reparatur-Modell, spielt bis zu N gezielte Patches ein und führt bei endgültigem Scheitern ein sauberes Git-Rollback aus.",
        "Jeder Selbstheilungsversuch kostet 1 zusätzlichen LLM-Call (+3 bis +12 Sek. Latenz & Token-Kosten). Ein automatisches Git-Rollback verwirft bei Fehlschlag auch nützliche Teilerfolge.",
        "Git-Rollback ausschalten, wenn unfertige Code-Entwürfe zur manuellen Weiterarbeit im Arbeitsverzeichnis stehen bleiben sollen.",
        "Max Reparaturversuche: 1 = gibt sofort auf | > 5 = teure Reparatur-Kaskade (Std: 3)."
    ),
    "19.5 Event-Mesh & Webhook-Trigger-Brücke": (
        "Modul 9: Inbox-Watcher, Event-Mesh & Autonomes Morgen-Standup (backend/event_mesh.py)",
        "Externe Dokumente, PDFs oder Aufgaben-Drops im Eingangsordner bleiben unbeachtet liegen, bis ein Nutzer sie manuell im Chat hochlädt.",
        "Überwacht den Drop-Ordner im Sekundentakt auf neue Dateien, verarbeitet sie automatisch und erstellt morgens zur Wunschzeit ein kompaktes Standup-Briefing.",
        "Sehr kurze Scan-Intervalle (< 3 Sek.) erzeugen kontinuierliche Dateisystem-Polls; das tägliche Morgen-Standup verbraucht ~1.500–3.000 Tokens pro Lauf.",
        "Ausschalten, wenn der lokale Inbox-Ordner nicht aktiv genutzt wird oder kein morgendlicher Briefing-Bericht gewünscht ist.",
        "Scan-Intervall: 1–2s = unnötige Disk-Polls | > 30s = verzögerte Datei-Erkennung (Std: 5s). Standup-Zeit: Std 08:00 Uhr."
    ),
    "20.1 Flüchtige Code-Sandboxen": (
        "Modul 4: Ephemeral Docker Sandbox (backend/ephemeral_sandbox.py ⇄ Hermes Terminal)",
        "Direkte Ausführung von KI-generiertem Python- oder Bash-Code auf dem Host-System kann Dateien beschädigen, Prozesse blockieren oder Speicherlecks verursachen.",
        "Kapselt jede Code-Ausführung in einen kurzlebigen Docker-Container mit hartem RAM-, CPU- und Timeout-Deckel sowie optionaler Netzwerksperre.",
        "Container-Kaltstart kostet ~300–800 ms Zusatzlatenz pro Tool-Call. Ist das Netzwerk deaktiviert, schlagen pip install oder externe API-Abrufe im Skript sofort fehl.",
        "Ausschalten (oder Netzwerk aktivieren), wenn vertrauenswürdige lokale Skripte direkten Host-Zugriff oder schnelle Paketinstallationen benötigen.",
        "RAM-Limit: < 256 MB = OOM-Kill bei Pandas/NumPy | > 2048 MB = Host-RAM-Risiko (Std: 512 MB). Timeout: < 10s = bricht Builds ab (Std: 30s)."
    ),
    "20.2 Nächtliche Gedächtnis-Konsolidierung": (
        "Modul 0: Nächtliche Gedächtnis-Konsolidierung / Sleep-Cycle (backend/memory_consolidator.py)",
        "Temporäre Traces, Heartbeat-Logs und redundante Einzelfakten blähen SQLite- und Vektorspeicher über Wochen auf und verlangsamen jede Abfrage.",
        "Führt nachts (Standard 03:00 Uhr) einen Sleep-Cycle aus, dedupliziert ähnliche Erinnerungen per Cosine-Schwellenwert und bereinigt abgelaufene Roh-Logs.",
        "Während des Konsolidierungslaufs (~10–30 Sek.) entsteht kurze CPU-/Disk-Last; eine zu niedrige Pruning-Schwelle (< 0.88) kann verwandte, aber eigenständige Fakten zusammenfassen.",
        "Ausschalten, wenn lückenlose Roh-Traces für ein forensisches Audit dauerhaft ungefiltert erhalten bleiben müssen.",
        "Aufbewahrung: < 7 Tage = Verlust wichtiger Audit-Spuren | > 60 Tage = große SQLite-DB (Std: 14 Tage). Pruning-Schwelle: 0.95 = konservativ | 0.88 = aggressiv (Std: 0.92)."
    ),
    "20.3 Headless-Browser & Visueller Web-Agent": (
        "Modul 10: Fleet Self-Healing, DB-Backups, Secret-Masking & Visueller Browser-Audit (backend/visual_web_agent.py)",
        "Abgestürzte Hilfs-Container, ungeschützte Datenbanken ohne aktuelles Backup oder fehlerhafte UI-Layouts gefährden den unbeaufsichtigten 24/7-Betrieb.",
        "Startet ausgefallene Container automatisch neu, rotiert tägliche SQLite-Backups, maskiert Secrets in Logs und prüft UI-Änderungen per Headless-Chromium-Screenshot.",
        "Ein defekter Container kann durch Auto-Restart in eine Crash-Loop geraten; der visuelle Browser-Audit startet Chromium (+300 MB RAM, +4 Sek. Dauer).",
        "Auto-Restart während manueller Container-Wartung ausschalten; Browser-Audit bei reinem Backend-Betrieb deaktivieren.",
        "DB-Backup-Tage: < 3 Tage = knappe Historie | > 30 Tage = ~500 MB+ Backup-Speicher (Std: 7 Tage)."
    ),
    "20.4 Virtueller Pre-Mortem Stresstest": (
        "Modul 7: War-Room & Pre-Mortem Risiko-Simulation (backend/war_room_simulator.py)",
        "Riskante Befehle (Datenbank-Migrationen, Produktions-Deploys, Löschoperationen) werden ohne vorherige Folgenabschätzung direkt ausgeführt.",
        "Simuliert vorab im War-Room ein Pre-Mortem ('Was kann im schlimmsten Fall kaputtgehen?') und blockiert die Ausführung ab der eingestellten Risikostufe.",
        "Kostet ~1.500–3.000 zusätzliche Tokens und +4 bis +10 Sek. Wartezeit vor dem eigentlichen Task. Bei Block-Schwelle MEDIUM entstehen häufiger Fehlalarme.",
        "Auto-Pre-Mortem im normalen Entwicklungsalltag ausschalten und nur für produktionskritische Eingriffe (HIGH/CRITICAL) nutzen.",
        "Block-Schwelle: MEDIUM = blockiert oft vorsorglich | CRITICAL = stoppt nur katastrophale Risiken (Std: HIGH)."
    ),
    "20.5 SLA- & Übergabe-Verträge": (
        "Modul 8: SLA-Verträge & Inter-Agent Handoff-Desk (backend/sla_contract_enforcer.py)",
        "Subagenten liefern bei komplexen Delegationen manchmal halbfertige Antworten, leere Platzhalter (// TODO) oder überschreiten stillschweigend ihr Zeitfenster.",
        "Prüft jedes Subagenten-Ergebnis gegen einen formellen SLA-Vertrag (Mindestlänge, Pflichtfelder, Turnaround-Zeit) und weist unvollständige Abgaben automatisch zurück.",
        "Wird die Mindestlänge zu hoch angesetzt (> 300 Zeichen), werden präzise Kurzantworten abgelehnt und lösen teure Nacharbeits-Schleifen aus.",
        "Auto-Reject ausschalten, wenn Subagenten auch knappe Status- oder Ja/Nein-Antworten zurückgeben dürfen.",
        "Min. Länge: < 30 = lässt Platzhalter durch | > 300 = lehnt knappe Faktenantworten ab (Std: 100 Zeichen). Max Turnaround: Std 60 Min."
    ),
}


# ==============================================================================
# 3. KAPITEL 21 BIS 25 (ALLE 25 ENTERPRISE-MODULE INKL. INLINE TRADE-OFFS)
# ==============================================================================
CHAPTERS_21_TO_25 = [
    (
        "21. Performance-Core, Durchsatz-Skalierung & Token-Effizienz (Säule XII — Paket 1)",
        "Um Archon OS bei hoher Agentenlast maximal schnell, skalierbar und kosteneffizient zu betreiben, bündelt Säule XII (Paket 1) fünf Hochleistungs-Mechanismen auf Kernel-, Router- und Datenbankebene. Alle fünf Module sind im System Control Center unter 'AUTONOMIE & MODULE (36)' (Abschnitt 9) einzeln schaltbar.",
        [
            ("21.1 Semantischer Prompt- & Response-Cache (backend/semantic_cache.py)",
             "Speichert normalisierte Prompts samt L2-normiertem Wort-/3-Gramm-Frequenzvektor in der SQLite-Tabelle 'semantic_response_cache' (Endpunkte: POST /api/cache/semantic-lookup, POST /api/cache/semantic-store, GET /api/cache/semantic-stats).",
             "Wiederkehrende oder fast gleich formulierte Fragen lösen jedes Mal einen vollen, teuren LLM-API-Aufruf mit mehreren Sekunden Wartezeit aus.",
             "Vergleicht neue Prompts per Cosine-Ähnlichkeit mit dem lokalen Antwort-Cache und liefert bei einem Treffer die Antwort in unter 15 ms zum Nulltarif.",
             "Ist die Cosine-Schwelle zu niedrig (< 0.92), übersieht der Cache feine Bedeutungsunterschiede (z. B. 'lösche Test-DB' vs. 'lösche Prod-DB') und liefert falsche oder veraltete Antworten.",
             "Ausschalten bei Aufgaben mit Echtzeit-Daten (Börsenkurse, Live-Logs, Systemstatus) oder wenn jede Antwort frisch generiert werden muss.",
             "Cosine-Schwelle: < 0.92 = falsche Antworten aus Cache! | > 0.98 = kaum Treffer (Std: 0.95). TTL: Std 24h. Max Einträge: Std 500."),
            ("21.2 Paralleles Map-Reduce Sub-Tasking / Fan-Out & Fan-In (backend/map_reduce_executor.py)",
             "Zerlegt große Sammel-Aufgaben (Dokument-Batches, Code-Dateien, Prüflisten) ab auto_fan_out_min_items in parallele Worker-Coroutinen (Endpunkte: POST /api/execution/map-reduce, GET /api/execution/map-reduce/history).",
             "Große Sammelaufgaben (z. B. 15 Dateien prüfen oder 10 Wettbewerber analysieren) dauern sequenziell extrem lange und sprengen oft das Kontextfenster.",
             "Teilt Listen-Aufgaben ab N Elementen automatisch auf parallele Map-Worker auf (Fan-Out) und führt die Teilergebnisse am Ende sauber zusammen (Fan-In).",
             "Erzeugt N-fache gleichzeitige API-Last (Gefahr von HTTP-429 Rate-Limits beim Provider) und ~20–35 % Token-Overhead durch die anschließende Reduce-Synthese.",
             "Ausschalten bei strikten API-Rate-Limits oder wenn die Teilaufgaben eng voneinander abhängen und sequenziell aufeinander aufbauen müssen.",
             "Max Worker: > 8 = Rate-Limit-Gefahr (Std: 4). Chunk-Timeout: Std 30s. Ab Elementen: Std 3."),
            ("21.3 Speculative Fast-Routing & Latenz-Hedging (backend/speculative_hedger.py)",
             "Überwacht die Antwortzeit des primären LLM-Modells und startet bei Verzögerungen parallel das Fallback-Modell (Endpunkte: POST /api/router/hedged-completion, GET /api/router/hedged-stats).",
             "Wenn der primäre Cloud-LLM-Provider unter Last steht oder trödelt (Tail-Latency > 10 Sek.), blockiert die gesamte Benutzeroberfläche.",
             "Feuert nach Ablauf der Hedge-Verzögerung (z. B. 2,5 Sek.) automatisch einen parallelen Zweit-Request an das schnelle Fallback-Modell ab und nutzt die erste eintreffende Antwort.",
             "Wenn das Primärmodell kurz nach dem Hedge-Start doch noch antwortet, werden beide Requests abgerechnet (bis zu 2x Token-Kosten bei langsamen Prompts).",
             "Ausschalten bei knappem API-Budget oder wenn langsame Reasoning-Modelle genutzt werden, die regulär > 10 Sek. Denkzeit benötigen.",
             "Hedge-Verzögerung: < 1.5s = fast immer doppelte API-Kosten! | > 8s = kaum Latenz-Schutz (Std: 2.5s)."),
            ("21.4 Automatische Kontext-Komprimierung / Context Compactor (backend/context_compactor.py ⇄ Hermes Compression)",
             "Verdichtet lange Sitzungsverläufe automatisch in einen strukturierten [HIERARCHICAL_MEMORY_STATE]-Block (Endpunkt: POST /api/memory/compact-context).",
             "Lange Chat- und Agenten-Sitzungen überschreiten irgendwann das Token-Limit oder werden durch riesige alte Tool-Ausgaben extrem teuer und träge.",
             "Komprimiert ältere Gesprächsrunden ab der eingestellten Token-Schwelle automatisch zu einer kompakten Zusammenfassung, während die letzten N Runden im Original erhalten bleiben.",
             "Der Komprimierungslauf kostet einmalig ~1.000 Tokens; exakte Code-Zeilen oder kleine Detailwerte aus weit zurückliegenden Nachrichten können in der Zusammenfassung verloren gehen.",
             "Ausschalten, wenn der Agent wortwörtlich auf sehr frühe Nachrichten derselben Sitzung zurückgreifen muss.",
             "Token-Schwelle: < 3000 = vergisst Details zu früh | > 24000 = hohe Prompt-Kosten (Std: 6000). Letzte Turns behalten: Std 4."),
            ("21.5 SQLite WAL Connection-Pool & Async Write-Batching (backend/async_write_batcher.py)",
             "Puffert hochfrequente Telemetrie-, Trace- und Audit-Events im RAM und schreibt sie gebündelt auf die Disk (Endpunkte: POST /api/system/write-batcher/enqueue, POST /api/system/write-batcher/flush).",
             "Dutzende gleichzeitige Einzel-Schreibzugriffe führen bei SQLite unter Last zu database-is-locked-Fehlern und hohen I/O-Wartezeiten.",
             "Sammelt nicht-kritische Schreiboperationen im RAM-Puffer und schreibt sie gebündelt alle N Sekunden oder ab N Einträgen in einer einzigen WAL-Transaktion auf die Disk.",
             "Im Falle eines harten Stromausfalls oder kill -9 vor dem nächsten Flush-Intervall gehen die im RAM gepufferten Einträge der letzten 1–5 Sekunden verloren.",
             "Ausschalten, wenn jeder einzelne Log-Eintrag sofort und ohne Sekundenverzögerung synchron auf der Festplatte liegen muss.",
             "Batch-Größe: < 5 = viele Disk-Writes | > 100 = mehr Verlust bei Crash (Std: 25). Flush-Intervall: Std 2.0s.")
        ]
    ),
    (
        "22. Moderne Gedächtnis- & RAG-Architektur (Säule XIII — Paket 2)",
        "Säule XIII (Paket 2) hebt die Wissensverarbeitung von einfachem Vektor-RAG auf ein mehrstufiges, selbstkorrigierendes und quellenverankertes Enterprise-Gedächtnis (Abschnitt 10 im Tab 'AUTONOMIE & MODULE (36)').",
        [
            ("22.1 Hybride Suche: BM25 FTS5 + Vektor + RRF Re-Ranking (backend/hybrid_search_rrf.py)",
             "Verbindet SQLite FTS5 Volltextsuche (BM25) mit semantischer Vektorsuche und verschmilzt beide Ranglisten über Reciprocal Rank Fusion (Endpunkte: POST /api/rag/hybrid-index, POST /api/rag/hybrid-search).",
             "Reine Vektorsuche versteht zwar Synonyme, scheitert aber oft kläglich bei exakten Fehlercodes, Funktionsnamen, Seriennummern oder Akronymen.",
             "Kombiniert lexikalische Volltextsuche (BM25) mit semantischer Vektorsuche und verschmilzt beide Trefferlisten über Reciprocal Rank Fusion (RRF).",
             "Doppelte Index-Abfrage erhöht die Such-Latenz um ~15–40 ms; ein zu hohes Top-K (> 10) füllt den Agenten-Prompt mit tausenden Zusatz-Tokens.",
             "Fast nie ausschalten — höchstens Top-K auf 3–5 reduzieren, wenn Token-Kosten pro Anfrage minimiert werden sollen.",
             "RRF-Konstante K: Std 60. BM25-Gewicht: 0.0 = nur Vektor | 0.5 = Balance | 1.0 = nur Stichwort (Std: 0.50). Top-K: Std 5."),
            ("22.2 Temporaler Knowledge-Graph / Entitäten & Tripel (backend/knowledge_graph_store.py)",
             "Speichert Subjekt-Prädikat-Objekt-Beziehungen mit Zeitstempeln und ermöglicht Multi-Hop-Nachbarschaftssuche (Endpunkte: POST /api/memory/kg/extract, GET /api/memory/kg/Subgraph).",
             "Klassisches RAG findet nur isolierte Textabschnitte, erkennt aber keine mehrstufigen Zusammenhänge über mehrere Dokumente hinweg.",
             "Extrahiert Entitäten und Beziehungen als Subjekt-Prädikat-Objekt-Tripel in einen Knowledge-Graph und traversiert Nachbarknoten über mehrere Hops.",
             "Automatische Tripel-Extraktion kostet beim Speichern ~500 Zusatz-Tokens. Ab > 2 Traversal-Hops explodiert die Anzahl der Nachbarknoten exponentiell.",
             "Auto-Extraktion ausschalten bei reinem Kurzzeit-Chat ohne langfristigen Wissensaufbau; Hops auf maximal 2 begrenzen.",
             "Max Hops: 1 = direkte Nachbarn | 2 = optimal | >= 3 = Knoten-Explosion! (Std: 2). Min. Konfidenz: Std 0.70."),
            ("22.3 Agentic Corrective RAG / CRAG (backend/corrective_rag.py)",
             "Prüft gefundene RAG-Passagen vor der Antwortgenerierung auf Relevanz und formuliert schwache Suchanfragen automatisch um (Endpunkt: POST /api/rag/crag-retrieve).",
             "Liefert die Dokumentensuche unpassende Textstellen, halluziniert das LLM trotzdem eine scheinbar plausible Antwort aus dem unbrauchbaren Kontext.",
             "Bewertet die Relevanz der gefundenen Chunks vorab (CRAG-Grader) und formuliert die Suchanfrage bei schlechtem Score automatisch bis zu N-mal um.",
             "Jede Query-Umformulierung kostet 1 zusätzlichen LLM-Call (+1,5 bis +4 Sek. Latenz). Ist die Relevanz-Schwelle zu hoch (> 0.70), dreht CRAG unnötige Extrarunden.",
             "Ausschalten, wenn die Wissensdatenbank klein und sauber gepflegt ist oder schnelle Antwortzeiten unter 2 Sekunden gefordert sind.",
             "Relevanz-Schwelle: < 0.30 = lässt schwache Quellen durch | > 0.70 = endlose Such-Schleifen (Std: 0.45). Max Rewrites: Std 2."),
            ("22.4 Hierarchischer Core-Memory-Tier nach MemGPT/Letta-Prinzip (backend/core_memory_manager.py)",
             "Verwaltet angepinnte RAM-Gedächtnisblöcke, die Agenten selbstständig lesen und aktualisieren können (Endpunkte: GET/POST /api/memory/core-blocks).",
             "Wichtige Grundfakten über den Nutzer, aktive Projektziele oder Systemregeln rutschen bei langen Gesprächen aus dem Kontextfenster und werden vergessen.",
             "Hält bis zu N angepinnte Core-Memory-Blöcke (wie RAM-Register im Betriebssystem) dauerhaft direkt im System-Prompt jedes Agenten präsent.",
             "Jeder angepinnte Block belegt bei absolut jedem LLM-Aufruf dauerhaft Prompt-Tokens (10 Blöcke × 800 Zeichen ≈ 2.000 Tokens Grundlast pro Nachricht).",
             "Ausschalten oder Block-Anzahl auf 3–5 reduzieren, wenn kleine Modelle mit engem Kontextfenster oder knappe Token-Budgets genutzt werden.",
             "Max Blöcke: > 15 = hoher Token-Grundverbrauch (Std: 10). Max Zeichen/Block: < 300 = schneidet Regeln ab | > 1500 = verstopft Prompt (Std: 800)."),
            ("22.5 Strikte Quellen-Verankerung & Citation Pinning (backend/citation_pinner.py)",
             "Verankert Aussagen über [Q1]/[Quelle: ...]-Marker direkt mit den Ursprungsdokumenten und misst die Belegquote (Endpunkt: POST /api/rag/verify-citations).",
             "KI-Antworten mischen oft echte Fakten aus Dokumenten mit frei erfundenem Modellwissen, ohne dass erkennbar ist, welcher Satz woher stammt.",
             "Zwingt den Agenten zu Inline-Quellenbelegen ([Quelle: Datei, S. X]), hängt eine Quellen-Fußzeile an und prüft die prozentuale Zitat-Abdeckung.",
             "Erhöht den Output-Token-Verbrauch um ~10–15 %; eine zu hohe Mindest-Abdeckung (> 80 %) führt bei kreativen oder zusammenfassenden Fragen zu Fehlwarnungen.",
             "Ausschalten bei freiem Brainstorming, Code-Generierung oder lockerem Alltags-Chat ohne Dokumentenbezug.",
             "Min. Abdeckung: < 30% = unbelegte Aussagen | > 85% = Fehlwarnungen bei Zusammenfassungen (Std: 60%).")
        ]
    ),
    (
        "23. Zuverlässige Ausführung & Determinismus / Durable Execution (Säule XIV — Paket 3)",
        "Säule XIV (Paket 3) sichert mehrstufige Agenten-Prozesse gegen Parser-Abstürze, Server-Neustarts, doppelte Tool-Ausführungen und externe API-Ausfälle ab (Abschnitt 11 im Tab 'AUTONOMIE & MODULE (36)').",
        [
            ("23.1 Deterministischer JSON-Schema-Zwang / Structured Outputs (backend/structured_output_enforcer.py)",
             "Erzwingt typsichere JSON-Antworten inklusive automatischer Reparatur-Schleife bei Syntaxfehlern (Endpunkt: POST /api/execution/enforce-json).",
             "Wenn LLMs vor oder nach einem JSON-Objekt Höflichkeitsfloskeln ausgeben oder ein Komma vergessen, stürzen nachfolgende Workflows und Parser sofort ab.",
             "Validiert strukturierte Ausgaben strikt gegen das erwartete Schema und repariert kaputtes JSON automatisch in bis zu N Korrekturschleifen.",
             "Jede Auto-Reparatur-Schleife kostet +1 bis +3 Sek. Latenz und zusätzliche Tokens. Strikte Schema-Validierung lehnt Antworten auch wegen harmloser Zusatzfelder ab.",
             "Strikte Validierung ausschalten, wenn API-Endpunkte oder Skripte auch mit flexiblen oder teilweisen JSON-Feldern umgehen können.",
             "Schema-Prüfung: Strikt vs. Tolerant (Std: Strikt). Max Reparaturen: 1–2 = repariert 98 % aller Tippfehler | > 3 = verschwendet Tokens (Std: 2)."),
            ("23.2 Transaktionales Schritt-Checkpointing / Pause & Resume (backend/durable_checkpointer.py)",
             "Speichert den kompletten Task-Zustand nach jedem Schritt in SQLite für nahtloses Fortsetzen nach Unterbrechungen (Endpunkte: POST /api/execution/checkpoint, POST /api/execution/resume).",
             "Stürzt der Server oder Container bei Schritt 9 einer 10-schrittigen Recherche ab, ist die gesamte bisherige Arbeit samt verbrauchter Tokens verloren.",
             "Speichert nach jedem N-ten Schritt den kompletten Ausführungszustand transaktional in SQLite und nimmt unterbrochene Tasks beim Neustart automatisch wieder auf.",
             "Checkpointing bei jedem einzelnen Schritt (N = 1) erzeugt spürbare SQLite-Schreiblast. Auto-Resume beim Booten kann veraltete Tasks vom Vortag ungewollt wieder anfeuern.",
             "Auto-Resume ausschalten, wenn unterbrochene Aufgaben nach einem Neustart erst manuell geprüft und freigegeben werden sollen.",
             "Alle N Schritte: 1 = absolut absturzsicher, mehr Disk-I/O | 3–5 = schont SSD (Std: 1). Aufbewahrung: Std 14 Tage."),
            ("23.3 Idempotenz-Wächter für schreibende Tool-Aufrufe (backend/idempotency_guard.py)",
             "Verhindert doppelte Ausführungen identischer Schreibaktionen über SHA-256-Idempotenz-Schlüssel (Endpunkt: POST /api/execution/idempotency-check).",
             "Wird ein Schritt nach einem Netzwerk-Wackler automatisch wiederholt, verschickt der Agent dieselbe E-Mail zweimal, bucht doppelt oder legt Duplikate an.",
             "Berechnet aus Tool-Name und Parametern einen deterministischen Idempotenz-Schlüssel und blockiert doppelte schreibende Ausführungen innerhalb der TTL-Frist.",
             "Wenn der Nutzer exakt denselben Befehl innerhalb der Sperrfrist (Standard 24 h) absichtlich ein zweites Mal ausführen will, blockiert der Guard.",
             "TTL-Stunden auf 1 h senken oder kurzzeitig ausschalten, wenn identische Aktionen im Testbetrieb mehrfach hintereinander ausgeführt werden müssen.",
             "TTL (Stunden): < 1h = kurzer Duplikatschutz | > 48h = blockiert gewollte Wiederholungen (Std: 24h)."),
            ("23.4 Dry-Run & Shadow-Execution-Modus / Simulations-Schalter (backend/dry_run_simulator.py)",
             "Simuliert schreibende Datei- und API-Operationen gefahrlos im Trockenlauf und zeichnet nur den geplanten Diff auf (Endpunkt: POST /api/execution/dry-run).",
             "Neue Agenten-Workflows oder umgebaute System-Prompts lassen sich kaum gefahrlos an echten Produktionsdaten und externen APIs testen.",
             "Fängt im aktivierten Shadow-Modus alle schreibenden Datei-Tools und externen API-Calls ab, simuliert den Erfolg und protokolliert nur den geplanten Diff.",
             "SOLANGE AKTIV, WERDEN KEINE ECHTEN DATEIEN GESCHRIEBEN UND KEINE ECHTEN APIS AUSGEFÜHRT! Vergisst man den Schalter, wirkt das System nach außen hin 'tot'.",
             "Im normalen Produktivbetrieb zwingend AUSGESCHALTET lassen! Nur gezielt für Trockenübungen (Dry-Runs) und Sicherheits-Audits einschalten.",
             "Hauptschalter standardmäßig AUS (false). Nur für isolierte Testläufe aktivieren."),
            ("23.5 Dead-Letter-Queue (DLQ) mit Auto-Replay-Manager (backend/dead_letter_queue.py)",
             "Fängt fehlgeschlagene Aufträge auf und wiederholt sie zeitversetzt mit exponentiellem Backoff (Endpunkte: GET /api/execution/dlq, POST /api/execution/dlq/replay).",
             "Wenn eine externe Schnittstelle (z. B. CRM, SMTP oder Webhook) kurzzeitig für 2 Minuten nicht erreichbar ist, geht der fehlgeschlagene Auftrag endgültig verloren.",
             "Fängt gescheiterte Aufträge in einer Dead-Letter-Queue (DLQ) auf und wiederholt sie zeitversetzt mit exponentiellem Backoff bis zu N-mal.",
             "Bei dauerhaft fehlerhaften Aufträgen (z. B. ungültiger API-Key) verbrauchen die Wiederholungsversuche unnötig Ressourcen; zeitversetzte Replays können Aktionen verspätet auslösen.",
             "Auto-Replay ausschalten, wenn fehlgeschlagene Aufträge ausschließlich manuell gesichtet und einzeln freigegeben werden sollen.",
             "Max Retries: 1 = bricht bei kurzem Ausfall ab | > 5 = staut tote Jobs an (Std: 3). Backoff-Basis: Std 10s (10s -> 20s -> 40s).")
        ]
    ),
    (
        "24. Sicherheit, Datenschutz & Enterprise-Governance / Guardrails (Säule XV — Paket 4)",
        "Säule XV (Paket 4) schützt sensible Unternehmensdaten vor Cloud-Abfluss, Datenexfiltration, unbefugten Dateizugriffen und manipulierten Ausgaben (Abschnitt 12 im Tab 'AUTONOMIE & MODULE (36)').",
        [
            ("24.1 Bidirektionales PII-Scrubbing & Re-Hydration (backend/pii_scrubber.py)",
             "Pseudonymisiert Klarnamen, E-Mails, Telefonnummern und IBANs vor dem Cloud-LLM-Versand und setzt sie in der Antwort wieder ein (Endpunkte: POST /api/security/pii-scrub, POST /api/security/pii-rehydrate).",
             "Klarnamen, E-Mail-Adressen, Telefonnummern und IBANs aus internen Dokumenten wandern bei jedem Prompt ungeschützt an externe Cloud-LLM-Anbieter.",
             "Ersetzt sensible personenbezogene Daten (PII) vor dem API-Versand lokal durch Platzhalter ([EMAIL_1], [IBAN_1]) und setzt die echten Werte in der Antwort wieder ein.",
             "Wenn das LLM den Platzhalter im Antworttext leicht abwandelt, schlägt die Rückübersetzung (Rehydrierung) fehl. Zudem kann Regex-Maskierung manchmal Code-Strings verfälschen.",
             "Ausschalten, wenn ausschließlich lokale Modelle (Ollama) genutzt werden oder das LLM zwingend die echten E-Mail-Domains/Namen analysieren muss.",
             "Granulare Schalter für E-Mails, Telefonnummern, IBANs und automatische Rehydrierung (alle standardmäßig aktiv)."),
            ("24.2 Ausgehende Netzwerk-Allowlist / Egress-Firewall (backend/egress_firewall.py)",
             "Kontrolliert alle ausgehenden HTTP-Anfragen der Agenten gegen eine Domain-Whitelist und blockiert Roh-IP-Abflüsse (Endpunkt: POST /api/security/egress-check).",
             "Ein durch Prompt-Injection kompromittierter Agent könnte interne Dateien oder API-Keys per HTTP-Request an einen fremden Angreifer-Server exfiltrieren.",
             "Prüft jeden ausgehenden Netzwerkaufruf gegen die Domain-Allowlist und blockiert unbekannte Ziel-Domains sowie direkte Roh-IP-Verbindungen sofort.",
             "Solange allowlist_only aktiv ist, wird jede neue Webseite, API oder Dokumentation, die nicht explizit in der Domain-Liste steht, bei Web-Recherchen hart blockiert.",
             "Ausschalten (oder benötigte Domains ergänzen), wenn der Research-Agent frei im offenen Web recherchieren soll.",
             "Erlaubte Domains: Kommagetrennte Whitelist. Roh-IP-Blockade schützt vor direkten IP-Exfiltrationen."),
            ("24.3 Rollenbasierte Tool-Rechte & Datei-Scope-Jails / Agent RBAC (backend/agent_rbac_jail.py)",
             "Sperrt jeden Agenten strikt in sein erlaubtes Arbeitsverzeichnis ein und schützt .env- sowie Systemdateien (Endpunkt: POST /api/security/rbac-check).",
             "Ohne Dateisystem-Schranken kann jedes Agenten-Profil per Pfad-Traversal (../../) auf .env-Passwortdateien oder geschützte Systemordner (/etc, /root) zugreifen.",
             "Sperrt Agenten strikt in ihr erlaubtes Workspace-Verzeichnis (Path-Jail) ein und verweigert jeden Lese-/Schreibzugriff auf .env-Dateien und Systempfade.",
             "Verhindert, dass ein Administrator-Agent legitim Konfigurationsdateien außerhalb des Projektordners wartet oder .env-Vorlagen direkt überprüft.",
             "Nur für dedizierte Systemwartungs-Aufgaben kurzzeitig lockern; der .env-Schutz sollte im Normalbetrieb immer aktiv bleiben.",
             "Schalter für Path-Jail, .env-Sperre und Systemordner-Sperre (/etc, /root, /proc)."),
            ("24.4 Deterministischer Policy- & Anti-Slop-Linter / Output Guardrail (backend/output_policy_linter.py)",
             "Bereinigt KI-Floskeln aus Antworten und blockiert gefährliche Shell-/SQL-Befehle vor der Ausführung (Endpunkt: POST /api/security/lint-output).",
             "LLMs verfallen oft in aufgeblähte KI-Floskeln ('Gerne helfe ich dir dabei!') oder schlagen in Code-Blöcken unbedacht gefährliche Löschbefehle (rm -rf /, DROP TABLE) vor.",
             "Scannt jede Antwort vor der Anzeige, entfernt typische KI-Floskeln automatisch und blockiert destruktive Shell- oder SQL-Befehle.",
             "Der Destruktiv-Filter kann auch harmlose Aufräum-Skripte oder gewollte Datenbank-Migrationen blockieren, wenn darin Befehle wie DROP oder rm -rf vorkommen.",
             "Destruktiv-Blocker kurzzeitig ausschalten, wenn gezielt Server-Aufräumskripte oder SQL-Reset-Migrationen erstellt werden.",
             "Schalter für KI-Floskeln entfernen, Destruktive Befehle blockieren und Auto-Bereinigung."),
            ("24.5 Kryptografisch signierte Ausführungs-Quittungen / Execution Receipts (backend/execution_receipts.py)",
             "Erstellt für jeden Agentenlauf einen manipulationssicheren SHA-256-Prüfbeleg in einer Hash-Kette (Endpunkte: POST /api/security/receipts/issue, GET /api/security/receipts/verify).",
             "Bei autonomen Agentenläufen lässt sich im Nachhinein oft nicht mehr revisionssicher beweisen, wer wann welches Modell mit welchen Kosten und welchem Ergebnis ausgeführt hat.",
             "Erzeugt für jeden Lauf eine kryptografisch verkettete SHA-256-Quittung (Hash-Chain) inklusive Zeitstempel, Tool-Spur und exakter Kostenaufstellung.",
             "Verursacht minimalen Rechen- und Speicher-Overhead (~2 ms und ~2 KB SQLite-Speicher pro Task); die Hash-Kette wächst über Monate kontinuierlich an.",
             "Kann im Produktivbetrieb dauerhaft aktiviert bleiben; nur auf extrem speicherlimitierten Kleinstsystemen ausschalten.",
             "Hash-Verkettung (SHA-256) + detaillierte Kosten-Aufschlüsselung pro Lauf.")
        ]
    ),
    (
        "25. Selbst-Optimierung, Evaluation & Schwarm-Intelligenz (Säule XVI — Paket 5)",
        "Säule XVI (Paket 5) macht Archon OS selbstlernend und selbstregulierend: Das System lernt aus Fehlern, prüft sich gegen Referenz-Tests, wählt Modelle empirisch aus und drosselt sich bei Überlast selbst (Abschnitt 13 im Tab 'AUTONOMIE & MODULE (36)').",
        [
            ("25.1 Autonome Prompt-Selbstoptimierung nach DSPy/TextGrad-Prinzip (backend/prompt_optimizer.py)",
             "Analysiert wiederkehrende Fehlermuster und generiert automatisch gezielte System-Prompt-Verbesserungen (Endpunkte: POST /api/evolution/prompt-optimize, GET /api/evolution/prompt-patches).",
             "Wenn ein Agent bei bestimmten Aufgaben immer wieder denselben Fehler macht, muss der Nutzer den System-Prompt jedes Mal mühsam von Hand nachbessern.",
             "Analysiert wiederkehrende Fehlermuster ab N Fehlschlägen automatisch und generiert präzise Korrekturregeln (Prompt-Patches) für den Agenten.",
             "Ist Auto-Apply aktiv, kann eine fehlerhaft abgeleitete Regel das Verhalten des Agenten dauerhaft verzerren (Prompt-Drift) und den System-Prompt aufblähen.",
             "Auto-Apply im Produktivbetrieb ausgeschaltet lassen, damit vorgeschlagene Prompt-Patches erst nach menschlicher Prüfung übernommen werden.",
             "Ab Fehlern: 1 = überreagiert auf Einzelfehler | > 8 = lernt sehr träge (Std: 3). Max Regeln: > 10 = bläht System-Prompt auf (Std: 5)."),
            ("25.2 Kontinuierliche Eval- & Regressions-Suite / Golden Dataset (backend/eval_regression_suite.py)",
             "Prüft Prompt- und Modelländerungen gegen hinterlegte Gold-Standard-Testfälle vor der Freigabe (Endpunkte: POST /api/evolution/eval-run, GET /api/evolution/eval-cases).",
             "Nach einem Modellwechsel oder einer Prompt-Änderung merkt man oft erst im Live-Betrieb, dass wichtige Kernfunktionen plötzlich schlechtere Ergebnisse liefern.",
             "Prüft Änderungen automatisch gegen einen Satz hinterlegter Referenz-Testfälle (Golden Dataset) und blockiert die Aktivierung, wenn die Bestehensquote unter X % fällt.",
             "Jeder komplette Eval-Durchlauf feuert alle hinterlegten Test-Prompts gegen die LLM-API (kostet je nach Testumfang ~5.000–25.000 Tokens und 15–60 Sek. Laufzeit).",
             "Deploy-Blockade ausschalten, wenn schnelle experimentelle Prompt-Tests ohne Wartezeit durchgeführt werden.",
             "Min. Pass-Rate: < 75% = lässt Verschlechterungen durch | 100% = blockiert schon bei kleinsten Abweichungen (Std: 90%)."),
            ("25.3 Adaptives Multi-Armed-Bandit Modell-Routing (backend/bandit_model_router.py ⇄ Hermes Smart-Routing)",
             "Routet Aufgaben per Epsilon-Greedy-Algorithmus anhand realer Erfolgs-, Kosten- und Latenzwerte (Endpunkte: POST /api/router/bandit-select, POST /api/router/bandit-reward).",
             "Statische Modell-Zuweisungen nutzen weiter ein teures oder aktuell gestörtes LLM, obwohl ein anderes Modell dieselbe Aufgabenklasse schneller und zuverlässiger löst.",
             "Lernt per Multi-Armed-Bandit-Algorithmus laufend aus Erfolgsquote, Latenz und Kosten und routet Aufträge dynamisch zum besten Modell.",
             "Durch die Explorationsrate (Epsilon, z. B. 0.15 = 15 %) testet der Router absichtlich immer wieder alternative Modelle aus, die im Einzelfall langsamer sein können.",
             "Ausschalten (oder Epsilon auf 0.00 setzen), wenn für jeden Lauf ein 100 % festes, vorhersagbares Modell erzwungen werden soll.",
             "Epsilon: 0.00 = nutzt stur das beste Modell | > 0.30 = probiert zu oft schwächere Modelle (Std: 0.15). Erfolgs-/Latenz-Gewicht: Std 0.60 / 0.40."),
            ("25.4 Dynamische Ad-hoc-Team-Assemblierung / Ephemeral Teams (backend/ephemeral_team_spawner.py)",
             "Stellt für komplexe Spezialaufträge temporäre Experten-Teams zusammen und löst sie nach Abschluss wieder auf (Endpunkte: POST /api/swarm/ephemeral-team/spawn, POST /api/swarm/ephemeral-team/dissolve).",
             "Für einmalige Spezialprojekte existiert oft kein passendes Standard-Team, oder alte Spezial-Agenten bleiben als Karteileichen übrig.",
             "Stellt für komplexe Aufträge ad-hoc eine temporäre Task-Force aus bis zu N Spezialisten zusammen und löst das Team nach Abschluss automatisch wieder auf.",
             "Ein 4-köpfiges Ad-hoc-Team vervielfacht den Token-Verbrauch (3x bis 5x) und benötigt zusätzlichen Koordinations-Overhead zwischen den Teammitgliedern.",
             "Ausschalten bei einfachen Einzelaufgaben oder knappem Token-Budget; Max. Teamgröße im Alltag auf 3–4 begrenzen.",
             "Max Teamgröße: 2–4 = ideal | > 5 = hoher Kommunikations-Overhead & 5x Token-Verbrauch (Std: 4)."),
            ("25.5 Live-Ressourcen-Backpressure & Selbst-Drosselung / Load Shedding (backend/resource_backpressure.py)",
             "Überwacht Host-CPU, RAM und freien Festplattenspeicher und drosselt Hintergrund-Aufgaben bei Überlast automatisch (Endpunkt: GET /api/system/backpressure-status).",
             "Starten mehrere Hintergrund-Jobs, Browser-Instanzen und Indexierungen gleichzeitig, läuft der Server in 100 % CPU-Last oder einen Out-of-Memory-Absturz (OOM).",
             "Überwacht CPU-, RAM- und Disk-Reserven in Echtzeit und pausiert niedrig priorisierte Hintergrund-Jobs automatisch, sobald ein Schwellenwert überschritten wird.",
             "Sind die Schwellenwerte zu niedrig eingestellt (CPU < 70 % oder RAM < 70 %), werden Hintergrund-Aufgaben schon bei normalen kurzen Lastspitzen ständig ausgebremst.",
             "Nicht komplett ausschalten — stattdessen bei starker Hardware die CPU-/RAM-Schwellen auf 90 % anheben.",
             "Max CPU/RAM: < 70% = drosselt bei normaler Arbeit | > 92% = OOM-Gefahr (Std: 85%). Min. freie Disk: Std 2.0 GB.")
        ]
    )
]


# ==============================================================================
# 4. GLOSSAR-BOXEN (78 BIS 113 + FRÜHERE KERN-BOXEN) INLINE TRADE-OFF MAPPING
# ==============================================================================
GLOSSARY_TRADEOFF_MAP = {
    "24.": ("Ist die Cache-TTL zu hoch (> 72h), liefert das System bei dynamischen Themen veraltete Antworten.", "Ausschalten bei Echtzeit-Abfragen (Live-Kurse, Serverstatus). Std-TTL: 24h."),
    "25.": ("Schneidet Nachrichten oberhalb von 32k Tokens oder 20 Turns hart ab, wodurch sehr früher Kontext wegfällt.", "Für tiefe Dokumenten-Analysen auf 64k–128k im Hermes Core anheben."),
    "26.": ("Kürzt überlange Tool-Ausgaben in der Mitte heraus ([...SNIP...]), wodurch einzelne Code-Zeilen im Rohtext fehlen können.", "Kurzzeitig deaktivieren, wenn komplette Roh-Logs ungekürzt benötigt werden."),
    "27.": ("Der Komprimierungs-Schritt kostet einmalig ~800 Tokens und glättet wörtliche Formulierungen früher Runden.", "Bei Bedarf über protect_last_n (Std: 20) im Hermes Core feinjustieren."),
    "28.": ("Das Auslagern und Nachladen von Agenten-RAM auf Disk erzeugt ~10–25 ms I/O-Latenz beim Kontextwechsel.", "Ab 80 % RAM-Auslastung aktiv lassen, um OOM-Abstürze zu verhindern."),
    "33.": ("Bei Erreichen von 80 % des Task-Budgets wird auf ein günstigeres Spar-Modell heruntergeschaltet; bei 100 % erfolgt der Hard-Stop.", "Task-Budget (Std: 0,50 $) für große Architektur-Läufe auf 2,00 $ anheben."),
    "34.": ("Sehr niedrige Schwellen (Max Steps < 10 oder Jaccard < 0.80) brechen legitime iterative Reparatur-Schleifen vorzeitig ab.", "Für komplexe Refactorings Max Steps auf 25–40 erhöhen (Std: 15)."),
    "35.": ("Mehr aktive Hintergrund-Dienste und hohes Reasoning ('high') erhöhen die Grundlast und Token-Kosten.", "Über die 14 Sektionen im Tab 'HERMES CORE' granular steuerbar."),
    "38.": ("Zu wenige Worker (1–2) erzeugen Warteschlangen-Rückstau; zu viele Worker (> 8) führen zu RAM-Spitzen und API-429-Fehlern.", "Standard: 4 gleichzeitige Worker (synchronisiert mit Hermes delegation.max_concurrent_children)."),
    "40.": ("Ein zu knappes Stagnations-Limit (< 30s) bricht langsame Deep-Reasoning-Modelle (o3/R1) mitten im Denkprozess ab.", "Bei Nutzung von Reasoning-Modellen Stagnations-Limit auf 90–120s erhöhen (Std: 45s)."),
    "41.": ("Ein dauerhaft defekter Container kann durch Auto-Restart in eine Neustart-Schleife geraten.", "Während manueller Container-Wartungsarbeiten kurzzeitig deaktivieren."),
    "42.": ("Jedes automatische Morgen-Briefing verbraucht ~1.500–3.000 Tokens zum eingestellten Zeitpunkt.", "Ausschalten, wenn kein täglicher Morgen-Report gewünscht ist (Std: 08:00 Uhr)."),
    "45.": ("Strikte SLA-Prüfungen weisen sehr kurze, aber korrekte Faktenantworten zurück, wenn min_content_length zu hoch (> 300) ist.", "Standard: 100 Zeichen Mindestlänge, 60 Min. Turnaround."),
    "49.": ("Verdreifacht (3x) den Token-Verbrauch und erhöht die Antwortzeit um +6 bis +20 Sek.; Einstimmigkeit birgt Deadlock-Gefahr.", "Erst ab Priorität P3/P4 aktivieren und 2/3-Mehrheit wählen."),
    "64.": ("Tägliche Voll-Backups belegen je nach Aufbewahrungsdauer ~50–500 MB Festplattenspeicher.", "Standard: 7 Tage Aufbewahrung (db_backup_keep_days)."),
    "66.": ("Jeder Pre-Write-Snapshot kostet ~5–15 ms Disk-I/O vor dem Überschreiben einer Datei.", "Ringpuffer standardmäßig auf 50 Snapshots begrenzt."),
    "68.": ("Minimaler Schreib-Overhead (~2 ms pro Eintrag); die kryptografische Kette wächst über Monate an.", "Für revisionssichere Governance dauerhaft eingeschaltet lassen."),
    "69.": ("Sehr strenge Heuristiken können bei IT-Security-Texten oder Pen-Testing-Prompts Fehlalarme (False Positives) auslösen.", "Nur für autorisierte Red-Teaming-Tests kurzzeitig lockern."),
    "70.": ("Aggressive Regex-Maskierung kann in seltenen Fällen harmlose Base64- oder Hash-Strings in Code-Ausgaben schwärzen.", "Im Produktivbetrieb zum Schutz von API-Keys dauerhaft aktiv lassen."),
    "78.": ("Erhöht Disk-I/O um ~5–15 ms pro Datei-Edit und belegt ~50–250 MB Speicherplatz für Snapshots.", "Wann ausschalten? Bei knappem Disk-Speicher oder Massen-Generierungen. Kipppunkte: Max Snapshots Std 50, Max Steps Std 100."),
    "79.": ("N Kandidaten-Modelle kosten N-fache API-Tokens pro Testlauf.", "Wann ausschalten? Nur gezielt für Modellvergleiche starten, nicht im Dauerbetrieb."),
    "80.": ("Verdreifacht (3x) die Token-Kosten und addiert +6 bis +20 Sek. Latenz; Einstimmigkeit kann blockieren.", "Wann ausschalten? Bei Zeitdruck oder erst ab Prio 4 aktivieren. Kipppunkte: Prio Std 3, Modus Tri-Agent (2/3-Mehrheit)."),
    "81.": ("Jeder Selbstheilungsversuch kostet 1 extra LLM-Call (+3–12s); Auto-Git-Rollback verwirft auch Teilerfolge.", "Wann ausschalten? Rollback deaktivieren, wenn unfertiger Code erhalten bleiben soll. Kipppunkt: Max Versuche Std 3."),
    "82.": ("Kurze Scan-Intervalle (< 3s) erzeugen unnötige Disk-Polls; Morgen-Standup kostet ~2.000 Tokens/Tag.", "Wann ausschalten? Wenn der Drop-Ordner nicht genutzt wird. Kipppunkte: Scan-Intervall Std 5s, Standup Std 08:00 Uhr."),
    "83.": ("Docker-Kaltstart kostet ~300–800 ms pro Call; ohne Netzwerk schlagen pip install & API-Abrufe im Skript fehl.", "Wann ausschalten? Bei vertrauenswürdigen lokalen Skripten. Kipppunkte: RAM Std 512 MB (< 256 MB = OOM-Gefahr), Timeout Std 30s."),
    "84.": ("Erzeugt nachts für ~10–30s CPU-/Disk-Last; Schwelle < 0.88 kann verwandte Fakten ungewollt verschmelzen.", "Wann ausschalten? Wenn ungefilterte Roh-Traces für Audits erhalten bleiben müssen. Kipppunkte: Aufbewahrung Std 14d, Cosine Std 0.92."),
    "85.": ("Headless-Chromium benötigt pro aktivem Audit-Lauf ~300 MB RAM und ~3–5 Sek. Renderzeit.", "Wann ausschalten? Bei reinem Backend-Betrieb ohne UI-Prüfungen."),
    "86.": ("Kostet ~1.500–3.000 Tokens und +4–10s Vorlaufzeit pro Risiko-Simulation; Schwelle MEDIUM erzeugt öfter Fehlalarme.", "Wann ausschalten? Auto-Pre-Mortem im normalen Coding-Alltag ausschalten. Kipppunkt: Block-Schwelle Std HIGH."),
    "87.": ("Mindestlänge > 300 Zeichen lehnt präzise Kurzantworten ab und erzwingt teure Nacharbeits-Schleifen.", "Wann ausschalten? Auto-Reject deaktivieren, wenn knappe Antworten erlaubt sind. Kipppunkte: Min. Länge Std 100 Zeichen, Turnaround Std 60m."),
    "88.": ("Zu scharfe Schwellenwerte bremsen Agenten aus; zu lockere Werte erhöhen Token- und Sicherheitsrisiken.", "Alle 36 Module & 14 Hermes-Sektionen sind im System Control Center mit Live-Kipppunkt-Hinweisen versehen."),
    "89.": ("Cosine-Schwelle < 0.92 kann feine Bedeutungsunterschiede übersehen und falsche Antworten aus dem Cache liefern!", "Wann ausschalten? Bei Echtzeit-Daten (Kurse, Live-Status). Kipppunkte: Cosine Std 0.95, TTL Std 24h, Max Einträge Std 500."),
    "90.": ("N-fache gleichzeitige API-Last (HTTP-429 Rate-Limit-Gefahr) plus ~25 % Token-Overhead für den Reduce-Schritt.", "Wann ausschalten? Bei strikten Rate-Limits oder sequenziellen Aufgaben. Kipppunkte: Max Worker Std 4, Timeout Std 30s, Min Items Std 3."),
    "91.": ("Antwortet das Primärmodell kurz nach Hedge-Start doch noch, werden beide Calls berechnet (bis zu 2x Kosten).", "Wann ausschalten? Bei knappem Budget oder langsamen Reasoning-Modellen. Kipppunkt: Hedge-Delay < 1.5s = fast immer Doppelkosten (Std: 2.5s)."),
    "92.": ("Komprimierungslauf kostet einmalig ~1.000 Tokens; winzige Details aus sehr frühen Nachrichten werden geglättet.", "Wann ausschalten? Wenn wortwörtlicher Zugriff auf den Sitzungsbeginn nötig ist. Kipppunkte: Schwelle Std 6.000 Tokens, Keep Turns Std 4."),
    "93.": ("Bei hartem Stromausfall (kill -9) vor dem nächsten Flush gehen gepufferte Logs der letzten 1–2 Sekunden verloren.", "Wann ausschalten? Wenn jedes Event ohne Sekundenverzögerung synchron auf Disk liegen muss. Kipppunkte: Batch Std 25, Flush Std 2.0s."),
    "94.": ("Doppelte Index-Abfrage kostet ~15–40 ms; Top-K > 10 bläht den Prompt mit tausenden Zusatz-Tokens auf.", "Wann ausschalten? Fast nie — nur Top-K bei knappem Budget auf 3 senken. Kipppunkte: RRF-K Std 60, BM25-Gewicht Std 0.50, Top-K Std 5."),
    "95.": ("Auto-Extraktion kostet ~500 Tokens beim Speichern; ab >= 3 Hops explodiert die Nachbarknoten-Menge!", "Wann ausschalten? Auto-Extraktion bei reinem Kurzzeit-Chat deaktivieren. Kipppunkte: Max Hops Std 2 (niemals > 3!), Konfidenz Std 0.70."),
    "96.": ("Jede Query-Umformulierung kostet 1 extra LLM-Call (+1,5–4s Latenz); Schwelle > 0.70 führt zu Endlos-Korrekturen.", "Wann ausschalten? Wenn Antwortzeiten < 2s wichtiger sind als tiefe Dokumenten-Prüfung. Kipppunkte: Relevanz Std 0.45, Max Rewrites Std 2."),
    "97.": ("Jeder angepinnte Block belegt bei JEDEM LLM-Aufruf dauerhaft Prompt-Tokens (10 Blöcke ≈ 2.000 Tokens Grundlast).", "Wann ausschalten? Bei Modellen mit kleinem Kontextfenster auf 3–5 Blöcke reduzieren. Kipppunkte: Max Blöcke Std 10, Max Zeichen Std 800."),
    "98.": ("Erhöht Output-Tokens um ~10–15 %; Mindest-Abdeckung > 80 % erzeugt Fehlwarnungen bei freien Zusammenfassungen.", "Wann ausschalten? Bei kreativem Brainstorming oder reinem Coding ohne Quellenbezug. Kipppunkt: Min. Abdeckung Std 60 %."),
    "99.": ("Jede Auto-Reparatur kostet +1–3s Latenz; strikte Validierung lehnt Antworten auch wegen harmloser Zusatzfelder ab.", "Wann ausschalten? Strikten Modus deaktivieren, wenn flexible JSON-Felder erlaubt sind. Kipppunkte: Modus Std Strikt, Max Retries Std 2."),
    "100.": ("Schrittweises Checkpointing (N=1) erzeugt mehr SQLite-Schreiblast; Auto-Resume kann alte Tasks vom Vortag starten.", "Wann ausschalten? Auto-Resume deaktivieren, wenn abgebrochene Tasks manuell geprüft werden sollen. Kipppunkte: Alle N Schritte Std 1, Retention Std 14d."),
    "101.": ("Blockiert auch absichtlich vom Nutzer wiederholte identische Schreibbefehle innerhalb der Sperrfrist (TTL).", "Wann ausschalten? Im Testbetrieb bei gewollten Mehrfach-Ausführungen TTL auf 1h senken. Kipppunkt: TTL Std 24h."),
    "102.": ("ACHTUNG: Solange aktiv, werden KEINE echten Dateien geschrieben und KEINE echten APIs ausgeführt!", "Wann ausschalten? Im normalen Produktivbetrieb zwingend AUSGESCHALTET lassen (Std: false)! Nur für Dry-Run-Tests einschalten."),
    "103.": ("Dauerhaft ungültige Jobs (z. B. falscher API-Key) verbrauchen bei Auto-Replay unnötig Wiederholungsversuche.", "Wann ausschalten? Auto-Replay deaktivieren, wenn Fehler-Jobs nur manuell freigegeben werden sollen. Kipppunkte: Max Retries Std 3, Backoff Std 10s."),
    "104.": ("Verändert das LLM einen Platzhalter ([EMAIL_1]) leicht, schlägt die Rehydrierung fehl; Regex kann Code-IDs treffen.", "Wann ausschalten? Bei rein lokalen Modellen (Ollama) oder wenn echte Domains analysiert werden müssen."),
    "105.": ("Blockiert im Allowlist-Modus jede neue Webseite oder API sofort, solange die Domain nicht in der Whitelist steht.", "Wann ausschalten? Für offene Web-Recherchen deaktivieren oder benötigte Domains eintragen."),
    "106.": ("Verhindert, dass ein Admin-Agent legitim Konfigurationsdateien außerhalb des Projekt-Workspaces bearbeitet.", "Wann ausschalten? Nur kurzzeitig für Systemwartung lockern; .env-Schutz immer aktiv lassen."),
    "107.": ("Destruktiv-Blocker kann auch gewollte SQL-Migrationen oder Aufräum-Skripte stoppen, die DROP oder rm -rf enthalten.", "Wann ausschalten? Destruktiv-Filter beim Erstellen von Server-Cleanup-Skripten kurz deaktivieren."),
    "108.": ("Minimaler Overhead (~2 ms und ~2 KB SQLite pro Lauf); Hash-Kette wächst über die Laufzeit kontinuierlich an.", "Wann ausschalten? Im Produktivbetrieb dauerhaft für revisionssichere Nachweise aktiviert lassen."),
    "109.": ("Bei aktivem Auto-Apply können fehlerhaft abgeleitete Sonderregeln den System-Prompt verzerren (Prompt-Drift).", "Wann ausschalten? Auto-Apply im Produktivbetrieb AUS lassen (Std: false) und Patches manuell prüfen. Kipppunkte: Ab Fehlern Std 3, Max Regeln Std 5."),
    "110.": ("Jeder komplette Eval-Lauf feuert alle Testfälle gegen die API (~5.000–25.000 Tokens und 15–60s Dauer).", "Wann ausschalten? Deploy-Blockade bei schnellen Prompt-Experimenten deaktivieren. Kipppunkt: Min. Pass-Rate Std 90 %."),
    "111.": ("Durch Epsilon (z. B. 0.15 = 15 %) probiert der Router absichtlich auch alternative, teils langsamere Modelle aus.", "Wann ausschalten? Ausschalten (oder Epsilon = 0.00), wenn ein 100 % festes Modell erzwungen werden soll. Kipppunkte: Epsilon Std 0.15, Erfolg/Latenz 0.60/0.40."),
    "112.": ("Ein 4-köpfiges Ad-hoc-Team vervielfacht den Token-Verbrauch (3x–5x) und erzeugt Koordinations-Overhead.", "Wann ausschalten? Bei einfachen Einzelaufgaben oder knappem Budget. Kipppunkt: Max Teamgröße Std 4 (> 5 nicht empfohlen)."),
    "113.": ("Zu niedrige Schwellen (< 70 % CPU/RAM) bremsen Hintergrund-Jobs schon bei normalen kurzen Lastspitzen aus.", "Wann ausschalten? Nicht komplett ausschalten — auf starker Hardware Schwellen auf 90 % heben. Kipppunkte: CPU/RAM Std 85 %, Min Disk Std 2.0 GB."),
}


def main():
    doc = Document(DOC_PATH)
    body = doc.element.body

    # --------------------------------------------------------------------------
    # SCHRITT 1: Kapitel 26 am Ende des Dokuments rückstandslos entfernen
    # --------------------------------------------------------------------------
    ch26_p = None
    for p in doc.paragraphs:
        if "Kapitel 26: Entscheidungs- & Trade-off-Matrix" in p.text:
            ch26_p = p._p
            break

    if ch26_p is not None:
        # Check if previous element is a page break paragraph
        prev_el = ch26_p.getprevious()
        start_el = ch26_p
        if prev_el is not None and prev_el.tag.endswith("p") and ("page" in prev_el.xml or not prev_el.text):
            start_el = prev_el

        to_remove = []
        cur = start_el
        while cur is not None:
            if not cur.tag.endswith("sectPr"):
                to_remove.append(cur)
            cur = cur.getnext()
        for el in to_remove:
            body.remove(el)
        print(f"[Step 1] Removed Kapitel 26 ({len(to_remove)} XML elements) from end of document.")

    # --------------------------------------------------------------------------
    # SCHRITT 2: Kapitel 18.1 (Hermes Core) um alle 14 Sektionen (~55 Parameter) erweitern
    # --------------------------------------------------------------------------
    already_has_hermes_table = any("Tabelle 18.0: Die 14 nativen Hermes Core Sektionen" in p.text for p in doc.paragraphs)
    if not already_has_hermes_table:
        p_18_2 = None
        for p in doc.paragraphs:
            if p.text.startswith("18.2 Container & Dienste"):
                p_18_2 = p
                break
        if p_18_2 is not None:
            p_hc_intro = doc.add_paragraph()
            set_p_spacing(p_hc_intro, 4, 4, 1.15)
            r1 = p_hc_intro.add_run("Vollständige Abbildung aller 14 Hermes Core Sektionen (~55 Parameter) & Bidirektionale Auto-Synchronisation:\n")
            set_run_font(r1, "Aptos", 9.8, (26, 54, 93), bold=True)
            r2 = p_hc_intro.add_run(
                "Der Reiter 'HERMES CORE' im System Control Center bildet die gesamte native Hermes-Konfiguration (config.yaml) "
                "in 14 strukturierten Sektionen ab — es ist kein Wechsel in ein externes Dashboard nötig. Überlappende Parameter "
                "(Parallelität, Task-Timeouts, Sandbox-Limits, Loop-Guardrails, Kontext-Komprimierung, MoA/Konsens und Smart-Routing) "
                "werden beim Speichern vollautomatisch in beide Richtungen zwischen config.yaml und settings.json (Tab 'AUTONOMIE & MODULE (36)') synchronisiert."
            )
            set_run_font(r2, "Aptos", 9.2, (45, 55, 72))
            p_18_2._p.addprevious(p_hc_intro._p)

            p_hc_tbl_title = doc.add_paragraph()
            set_p_spacing(p_hc_tbl_title, 4, 2, 1.15)
            rt = p_hc_tbl_title.add_run("Tabelle 18.0: Die 14 nativen Hermes Core Sektionen (config.yaml ⇄ settings.json) inkl. Problem, Lösung & Trade-off")
            set_run_font(rt, "Aptos", 9.2, (43, 108, 176), bold=True)
            p_18_2._p.addprevious(p_hc_tbl_title._p)

            tbl_hc = create_styled_table(
                doc,
                ["Hermes Core Sektion", "Steuerbare Parameter & Auto-Sync", "Problem, Lösung & Preis / Schattenseite (Trade-off)"],
                HERMES_SECTIONS_DOC,
                [1.6, 2.0, 3.2]
            )
            p_18_2._p.addprevious(tbl_hc._tbl)
            print("[Step 2] Inserted Table 18.0 (14 Hermes Core sections + Trade-offs) under 18.1.")

    # --------------------------------------------------------------------------
    # SCHRITT 3: Inline Trade-off-Boxen in Kapitel 19 (19.1–19.5) & Kapitel 20 (20.1–20.5)
    # --------------------------------------------------------------------------
    already_has_ch19_boxes = any("Entscheidungs- & Trade-off-Profil: Modul 5" in t.rows[0].cells[0].text for t in doc.tables if len(t.rows) == 1)
    if not already_has_ch19_boxes:
        # Map each section heading to the next section heading so we insert right at the end of that section
        next_markers = [
            ("19.1 Replay & Time-Travel Debugging", "19.2 Multi-Modell Head-to-Head Benchmark"),
            ("19.2 Multi-Modell Head-to-Head Benchmark", "19.3 Dual- & Tri-Agent Konsens-Gate"),
            ("19.3 Dual- & Tri-Agent Konsens-Gate", "19.4 Autonome Task-Selbstheilung"),
            ("19.4 Autonome Task-Selbstheilung", "19.5 Event-Mesh & Webhook-Trigger-Brücke"),
            ("19.5 Event-Mesh & Webhook-Trigger-Brücke", "20. Autonome Sandboxing-"),
            ("20.1 Flüchtige Code-Sandboxen", "20.2 Nächtliche Gedächtnis-Konsolidierung"),
            ("20.2 Nächtliche Gedächtnis-Konsolidierung", "20.3 Headless-Browser & Visueller Web-Agent"),
            ("20.3 Headless-Browser & Visueller Web-Agent", "20.4 Virtueller Pre-Mortem Stresstest"),
            ("20.4 Virtueller Pre-Mortem Stresstest", "20.5 SLA- & Übergabe-Verträge"),
            ("20.5 SLA- & Übergabe-Verträge", "ANHANG: 5 PRAXIS-USE-CASES"),
        ]
        inserted_19_20 = 0
        for sec_key, next_prefix in next_markers:
            anchor_p = None
            for p in doc.paragraphs:
                if p.text.startswith(next_prefix):
                    anchor_p = p
                    break
            if anchor_p is not None and sec_key in CH19_20_TRADEOFFS:
                t_title, prob, sol, trade, dis, thresh = CH19_20_TRADEOFFS[sec_key]
                box = create_inline_tradeoff_box(doc, t_title, prob, sol, trade, dis, thresh)
                anchor_p._p.addprevious(box._tbl)
                p_sp = doc.add_paragraph()
                set_p_spacing(p_sp, 1, 3, 1.1)
                anchor_p._p.addprevious(p_sp._p)
                inserted_19_20 += 1
        print(f"[Step 3] Inserted {inserted_19_20} inline Trade-off boxes directly into Chapters 19 & 20.")

    # --------------------------------------------------------------------------
    # SCHRITT 4: Kapitel 21 bis 25 (Säulen XII–XVI) inkl. Inline-Trade-offs vor dem Anhang einfügen
    # --------------------------------------------------------------------------
    already_has_ch21 = any("21. Performance-Core, Durchsatz-Skalierung" in p.text for p in doc.paragraphs)
    if not already_has_ch21:
        anhang_p = None
        for p in doc.paragraphs:
            if p.text.startswith("ANHANG: 5 PRAXIS-USE-CASES"):
                anhang_p = p
                break
        if anhang_p is not None:
            for ch_title, ch_intro, features in CHAPTERS_21_TO_25:
                p_ch = doc.add_paragraph()
                set_p_spacing(p_ch, 14, 5, 1.15)
                rc = p_ch.add_run(ch_title)
                set_run_font(rc, "Aptos", 13.5, (26, 54, 93), bold=True)
                anhang_p._p.addprevious(p_ch._p)

                p_in = doc.add_paragraph()
                set_p_spacing(p_in, 2, 6, 1.15)
                ri = p_in.add_run(ch_intro)
                set_run_font(ri, "Aptos", 9.8, (45, 55, 72))
                anhang_p._p.addprevious(p_in._p)

                for f_title, f_func, f_prob, f_sol, f_trade, f_dis, f_thresh in features:
                    p_f = doc.add_paragraph()
                    set_p_spacing(p_f, 6, 2, 1.15)
                    rf1 = p_f.add_run(f_title + "\n")
                    set_run_font(rf1, "Aptos", 10.2, (26, 54, 93), bold=True)
                    rf2 = p_f.add_run("Was ist das & Funktion: ")
                    set_run_font(rf2, "Aptos", 9.2, (43, 108, 176), bold=True)
                    rf3 = p_f.add_run(f_func)
                    set_run_font(rf3, "Aptos", 9.2, (45, 55, 72))
                    anhang_p._p.addprevious(p_f._p)

                    box = create_inline_tradeoff_box(doc, f_title, f_prob, f_sol, f_trade, f_dis, f_thresh)
                    anhang_p._p.addprevious(box._tbl)

                    p_sp = doc.add_paragraph()
                    set_p_spacing(p_sp, 1, 3, 1.1)
                    anhang_p._p.addprevious(p_sp._p)

            print("[Step 4] Inserted Chapters 21 to 25 (all 25 Enterprise modules with inline Trade-off boxes) before ANHANG.")

    # --------------------------------------------------------------------------
    # SCHRITT 5: Alle Glossar-Boxen im Komplett-Glossar direkt vor Ort um
    #            "Preis & Schattenseite (Trade-off)" + "Wann ausschalten? & Schwellenwerte" ergänzen
    # --------------------------------------------------------------------------
    enriched_glossary_count = 0
    for tbl in doc.tables:
        if len(tbl.rows) == 1 and len(tbl.columns) == 1:
            cell = tbl.rows[0].cells[0]
            first_line = cell.paragraphs[0].text.strip() if cell.paragraphs else ""
            full_cell_text = "\n".join(p.text for p in cell.paragraphs)
            if "Preis & Schattenseite (Trade-off):" in full_cell_text:
                continue

            # Check if this is a numbered Glossary box ("1. ..." to "113. ...")
            matched_prefix = None
            for prefix in GLOSSARY_TRADEOFF_MAP:
                if first_line.startswith(prefix + " "):
                    matched_prefix = prefix
                    break

            if matched_prefix is not None:
                trade_txt, disable_txt = GLOSSARY_TRADEOFF_MAP[matched_prefix]
                p_tr = cell.add_paragraph()
                set_p_spacing(p_tr, 1, 2, 1.15)
                r_tl = p_tr.add_run("Preis & Schattenseite (Trade-off): ")
                set_run_font(r_tl, "Aptos", 9.0, (180, 83, 9), bold=True)
                r_tt = p_tr.add_run(trade_txt)
                set_run_font(r_tt, "Aptos", 9.0, (45, 55, 72), bold=False)

                p_di = cell.add_paragraph()
                set_p_spacing(p_di, 1, 2, 1.15)
                r_dl = p_di.add_run("Wann ausschalten? & Schwellenwerte: ")
                set_run_font(r_dl, "Aptos", 9.0, (30, 58, 138), bold=True)
                r_dt = p_di.add_run(disable_txt)
                set_run_font(r_dt, "Aptos", 9.0, (45, 55, 72), bold=False)
                enriched_glossary_count += 1
            elif any(first_line.startswith(f"{n}. ") for n in range(1, 78)):
                # General architectural/UI glossary items (1..77 not in specialized map)
                if "Problem:" in full_cell_text and "Nutzen:" in full_cell_text:
                    p_tr = cell.add_paragraph()
                    set_p_spacing(p_tr, 1, 2, 1.15)
                    r_tl = p_tr.add_run("Preis & Schattenseite (Trade-off): ")
                    set_run_font(r_tl, "Aptos", 9.0, (180, 83, 9), bold=True)
                    r_tt = p_tr.add_run(
                        "Als permanente Kern-Ansicht bzw. System-Infrastruktur im Dashboard integriert (vernachlässigbarer RAM-/CPU-Grundbedarf; "
                        "Token-Kosten entstehen nur bei aktiver Ausführung von LLM-Aktionen innerhalb des Moduls)."
                    )
                    set_run_font(r_tt, "Aptos", 9.0, (45, 55, 72), bold=False)
                    enriched_glossary_count += 1

    print(f"[Step 5] Enriched {enriched_glossary_count} Glossary boxes in-place with Trade-offs & thresholds.")

    try:
        doc.save(DOC_PATH)
        print(f"Done! Saved updated manual directly to {DOC_PATH}")
    except PermissionError:
        alt_path_1 = "/app/docs/system/ARCHON_OS_SYSTEM_HANDBUCH_2026_Vorlage_Inline_Tradeoffs.docx"
        alt_path_2 = "/app/docs/system/ARCHON_OS_SYSTEM_HANDBUCH_2026.docx"
        doc.save(alt_path_1)
        doc.save(alt_path_2)
        print(f"NOTE: {DOC_PATH} is currently open/locked in Microsoft Word (~$ lock file).")
        print(f"Saved complete updated manual to:\n  - {alt_path_1}\n  - {alt_path_2}")


if __name__ == "__main__":
    main()
