# -*- coding: utf-8 -*-
"""
Ergänzt das Word-Handbuch (ARCHON_OS_SYSTEM_HANDBUCH_2026_Vorlage.docx) um:
Kapitel 26: Entscheidungs- & Trade-off-Matrix aller 36 System-Module & 26 Plugins
(Problem, Lösung, Preis/Schattenseite, Wann ausschalten? & Schwellenwert-Kipppunkte).
"""
import os
from docx import Document
from docx.shared import Pt, RGBColor
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

DOCX_PATH = "docs/system/ARCHON_OS_SYSTEM_HANDBUCH_2026_Vorlage.docx"


def set_cell_shading(cell, fill_hex: str):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill_hex)
    tcPr.append(shd)


def add_tradeoff_box(doc, title: str, problem: str, solution: str, tradeoff: str, disable_hint: str, thresholds: str):
    tbl = doc.add_table(rows=1, cols=1)
    tbl.autofit = True
    cell = tbl.rows[0].cells[0]
    set_cell_shading(cell, "F8FAFC")

    p0 = cell.paragraphs[0]
    r_title = p0.add_run(f"⚖️ {title}")
    r_title.bold = True
    r_title.font.size = Pt(10.5)
    r_title.font.color.rgb = RGBColor(15, 23, 42)

    items = [
        ("Problem (Ohne Modul): ", problem, RGBColor(190, 18, 60)),
        ("Lösung (Wie es greift): ", solution, RGBColor(5, 150, 105)),
        ("Preis & Schattenseite (Trade-off): ", tradeoff, RGBColor(180, 83, 9)),
        ("Wann ausschalten? ", disable_hint, RGBColor(30, 58, 138)),
        ("Schwellenwert-Kipppunkte: ", thresholds, RGBColor(71, 85, 105)),
    ]

    for label, text, color in items:
        p = cell.add_paragraph()
        p.paragraph_format.space_before = Pt(2)
        p.paragraph_format.space_after = Pt(2)
        r_lbl = p.add_run(label)
        r_lbl.bold = True
        r_lbl.font.size = Pt(9.5)
        r_lbl.font.color.rgb = color
        r_txt = p.add_run(text)
        r_txt.font.size = Pt(9.5)
        r_txt.font.color.rgb = RGBColor(30, 41, 59)

    doc.add_paragraph()


MODULES_MATRIX = [
    (
        "Modul 0: Nächtliche Gedächtnis-Konsolidierung (Sleep-Cycle)",
        "Temporäre Traces, Heartbeat-Logs und redundante Einzelfakten blähen SQLite- und Vektorspeicher über Wochen auf und verlangsamen jede Abfrage.",
        "Führt nachts (Standard 03:00 Uhr) einen Sleep-Cycle aus, dedupliziert ähnliche Erinnerungen per Cosine-Schwellenwert und bereinigt abgelaufene Roh-Logs.",
        "Während des Konsolidierungslaufs (~10–30 Sek.) entsteht kurze CPU-/Disk-Last; eine zu niedrige Pruning-Schwelle (< 0.88) kann verwandte, aber eigenständige Fakten zusammenfassen.",
        "Ausschalten, wenn lückenlose Roh-Traces für ein forensisches Audit dauerhaft ungefiltert erhalten bleiben müssen.",
        "Aufbewahrung: < 7 Tage = Verlust wichtiger Audit-Spuren | > 60 Tage = große SQLite-DB (Std: 14 Tage). Pruning-Schwelle: 0.95 = konservativ | 0.88 = aggressiv (Std: 0.92)."
    ),
    (
        "Modul 1: Concurrency & Deadlock-Wächter",
        "Wenn zu viele Subagenten gleichzeitig starten oder ein Worker auf eine hängende externe API wartet, friert die gesamte Task-Queue per Deadlock ein.",
        "Begrenzt aktive Worker strikt per Semaphor und bricht stagnierende Agenten nach Ablauf der Stagnations-Schwelle samt automatischem Re-Queueing ab.",
        "Knappe Stagnations-Limits (< 30 Sek.) brechen langsame Deep-Reasoning-Modelle (z. B. o3/R1) fälschlich mitten im Denkprozess ab; mehr Worker erhöhen RAM- und API-Spitzenlast.",
        "Ausschalten bei extrem langlaufenden Einzel-Analysen oder lokalen LLM-Läufen auf langsamer Hardware.",
        "Max Worker: 1–2 = Rückstau | > 8 = RAM-Spitzen & HTTP-429 (Std: 4). Stagnation: < 30s = bricht Denker ab | > 180s = späte Heilung (Std: 45s)."
    ),
    (
        "Modul 2: Loop-Killer, Circuit-Breaker & Token-Clipper",
        "Agenten verfangen sich bei hartnäckigen Tool-Fehlern in Endlosschleifen, rufen denselben Befehl dutzende Male auf und verbrennen in Minuten das Tagesbudget.",
        "Erkennt identische oder semantisch fast gleiche Züge (Jaccard-Ähnlichkeit) sowie Schritt-Überschreitungen und kappt die Schleife sofort per Circuit-Breaker.",
        "Zu scharfe Grenzwerte (Max Identisch = 2 oder Jaccard < 0.80) stoppen legitime iterative Aufgaben wie schrittweises Test-Fixing oder Paginierung zu früh.",
        "Kurzzeitig ausschalten, wenn ein Agent bewusst viele gleichförmige Schleifen-Schritte (z. B. Massen-Migration von 50 Dateien) abarbeiten soll.",
        "Max Identisch: 2 = stoppt Retries | > 5 = teure Schleifen (Std: 3). Jaccard: < 0.80 = Fehlalarme | > 0.96 = erkennt Schleifen spät (Std: 0.90). Max Schritte: Std 15."
    ),
    (
        "Modul 3: Autonome Task-Selbstheilung & Git-Rollback",
        "Ein einziger Syntaxfehler oder fehlender Import nach einem Datei-Edit lässt den gesamten Task scheitern und hinterlässt oft kaputten Code im Repository.",
        "Analysiert den Traceback autonom mit einem Reparatur-Modell, spielt bis zu N gezielte Patches ein und führt bei endgültigem Scheitern ein sauberes Git-Rollback aus.",
        "Jeder Selbstheilungsversuch kostet 1 zusätzlichen LLM-Call (+3 bis +12 Sek. Latenz & Token-Kosten). Ein automatisches Git-Rollback verwirft bei Fehlschlag auch nützliche Teilerfolge.",
        "Git-Rollback ausschalten, wenn unfertige Code-Entwürfe zur manuellen Weiterarbeit im Arbeitsverzeichnis stehen bleiben sollen.",
        "Max Reparaturversuche: 1 = gibt sofort auf | > 5 = teure Reparatur-Kaskade (Std: 3)."
    ),
    (
        "Modul 4: Ephemeral Docker Sandbox",
        "Direkte Ausführung von KI-generiertem Python- oder Bash-Code auf dem Host-System kann Dateien beschädigen, Prozesse blockieren oder Speicherlecks verursachen.",
        "Kapselt jede Code-Ausführung in einen kurzlebigen Docker-Container mit hartem RAM-, CPU- und Timeout-Deckel sowie optionaler Netzwerksperre.",
        "Container-Kaltstart kostet ~300–800 ms Zusatzlatenz pro Tool-Call. Ist das Netzwerk deaktiviert, schlagen pip install oder externe API-Abrufe im Skript sofort fehl.",
        "Ausschalten (oder Netzwerk aktivieren), wenn vertrauenswürdige lokale Skripte direkten Host-Zugriff oder schnelle Paketinstallationen benötigen.",
        "RAM-Limit: < 256 MB = OOM-Kill bei Pandas/NumPy | > 2048 MB = Host-RAM-Risiko (Std: 512 MB). Timeout: < 10s = bricht Builds ab (Std: 30s)."
    ),
    (
        "Modul 5: Time-Travel Debugger & Pre-Write Snapshots",
        "Überschreibt ein Agent eine wichtige Datei fehlerhaft oder trifft im 8. Zwischenschritt eine falsche Entscheidung, lässt sich der Zustand ohne Backup nicht mehr rekonstruieren.",
        "Zeichnet jeden Agenten-Zwischenschritt im Time-Travel-Trace auf und legt vor jedem schreibenden Dateizugriff automatisch eine Pre-Write-Schattenkopie an.",
        "Erhöht Disk-I/O um ~5–15 ms pro Datei-Edit und belegt je nach Snapshot-Limit ~50–250 MB zusätzlichen Speicherplatz auf der Festplatte.",
        "Ausschalten auf Systemen mit extrem knappem Disk-Speicher oder bei massenhaften Datei-Generierungen (z. B. Build-Artefakte).",
        "Max Snapshots: < 10 = kurze Historie | > 200 = höherer Disk-Verbrauch (Std: 50). Max Trace-Steps: Std 100."
    ),
    (
        "Modul 6: Konsens-Gate & Tri-Agent Schiedsgericht",
        "Ein einzelnes LLM unterliegt bei kritischen Architektur-, Lösch- oder Finanzentscheidungen oft einem Bestätigungsfehler (Confirmation Bias).",
        "Schaltet ab der gewählten Aufgaben-Priorität automatisch ein Tri-Agent-Schiedsgericht (Proposer, Kritiker, Richter) vor, das per Mehrheitsregel abstimmt.",
        "Verdreifacht (3x) den Token-Verbrauch und erhöht die Antwortzeit um +6 bis +20 Sek. Bei Einstimmigkeits-Zwang droht Entscheidungs-Stillstand (Deadlock).",
        "Ausschalten (oder erst ab Priorität 4 = Kritisch aktivieren), wenn Geschwindigkeit und niedrige API-Kosten Vorrang haben.",
        "Ab Priorität: Prio 2 = fast jeder Task kostet 3x Tokens | Prio 4 = nur kritische Tasks (Std: Prio 3). Mehrheit: 2/3-Mehrheit empfohlen."
    ),
    (
        "Modul 7: War-Room & Pre-Mortem Risiko-Simulation",
        "Riskante Befehle (Datenbank-Migrationen, Produktions-Deploys, Löschoperationen) werden ohne vorherige Folgenabschätzung direkt ausgeführt.",
        "Simuliert vorab im War-Room ein Pre-Mortem ('Was kann im schlimmsten Fall kaputtgehen?') und blockiert die Ausführung ab der eingestellten Risikostufe.",
        "Kostet ~1.500–3.000 zusätzliche Tokens und +4 bis +10 Sek. Wartezeit vor dem eigentlichen Task. Bei Block-Schwelle MEDIUM entstehen häufiger Fehlalarme.",
        "Auto-Pre-Mortem im normalen Entwicklungsalltag ausschalten und nur für produktionskritische Eingriffe (HIGH/CRITICAL) nutzen.",
        "Block-Schwelle: MEDIUM = blockiert oft vorsorglich | CRITICAL = stoppt nur katastrophale Risiken (Std: HIGH)."
    ),
    (
        "Modul 8: SLA-Verträge & Inter-Agent Handoff-Desk",
        "Subagenten liefern bei komplexen Delegationen manchmal halbfertige Antworten, leere Platzhalter (// TODO) oder überschreiten stillschweigend ihr Zeitfenster.",
        "Prüft jedes Subagenten-Ergebnis gegen einen formellen SLA-Vertrag (Mindestlänge, Pflichtfelder, Turnaround-Zeit) und weist unvollständige Abgaben automatisch zurück.",
        "Wird die Mindestlänge zu hoch angesetzt (> 300 Zeichen), werden präzise Kurzantworten abgelehnt und lösen teure Nacharbeits-Schleifen aus.",
        "Auto-Reject ausschalten, wenn Subagenten auch knappe Status- oder Ja/Nein-Antworten zurückgeben dürfen.",
        "Min. Länge: < 30 = lässt Platzhalter durch | > 300 = lehnt knappe Faktenantworten ab (Std: 100 Zeichen). Max Turnaround: Std 60 Min."
    ),
    (
        "Modul 9: Inbox-Watcher & Autonomes Morgen-Standup",
        "Externe Dokumente, PDFs oder Aufgaben-Drops im Eingangsordner bleiben unbeachtet liegen, bis ein Nutzer sie manuell im Chat hochlädt.",
        "Überwacht den Drop-Ordner im Sekundentakt auf neue Dateien, verarbeitet sie automatisch und erstellt morgens zur Wunschzeit ein kompaktes Standup-Briefing.",
        "Sehr kurze Scan-Intervalle (< 3 Sek.) erzeugen kontinuierliche Dateisystem-Polls; das tägliche Morgen-Standup verbraucht ~1.500–3.000 Tokens pro Lauf.",
        "Ausschalten, wenn der lokale Inbox-Ordner nicht aktiv genutzt wird oder kein morgendlicher Briefing-Bericht gewünscht ist.",
        "Scan-Intervall: 1–2s = unnötige Disk-Polls | > 30s = verzögerte Datei-Erkennung (Std: 5s). Standup-Zeit: Std 08:00 Uhr."
    ),
    (
        "Modul 10: Fleet Self-Healing, DB-Backups, Secret-Masking & Browser-Audit",
        "Abgestürzte Hilfs-Container, ungeschützte Datenbanken ohne aktuelles Backup oder versehentlich geloggte API-Keys gefährden den unbeaufsichtigten 24/7-Betrieb.",
        "Startet ausgefallene Container automatisch neu, rotiert tägliche SQLite-Backups, maskiert Secrets in Logs und prüft UI-Änderungen optional per Headless-Browser.",
        "Ein defekter Container kann durch Auto-Restart in eine Crash-Loop geraten; der visuelle Browser-Audit startet Chromium (+300 MB RAM, +4 Sek. Dauer).",
        "Auto-Restart während manueller Container-Wartung ausschalten; Browser-Audit bei reinem Backend-Betrieb deaktivieren.",
        "DB-Backup-Tage: < 3 Tage = knappe Historie | > 30 Tage = ~500 MB+ Backup-Speicher (Std: 7 Tage)."
    ),
    (
        "Modul 11 (Paket 1.1): Semantischer Prompt- & Response-Cache",
        "Wiederkehrende oder fast gleich formulierte Fragen lösen jedes Mal einen vollen, teuren LLM-API-Aufruf mit mehreren Sekunden Wartezeit aus.",
        "Vergleicht neue Prompts per Cosine-Ähnlichkeit mit dem lokalen Antwort-Cache und liefert bei einem Treffer die Antwort in unter 15 ms zum Nulltarif.",
        "Ist die Cosine-Schwelle zu niedrig (< 0.92), übersieht der Cache feine Bedeutungsunterschiede (z. B. 'lösche Test-DB' vs. 'lösche Prod-DB') und liefert falsche oder veraltete Antworten.",
        "Ausschalten bei Aufgaben mit Echtzeit-Daten (Börsenkurse, Live-Logs, Systemstatus) oder wenn jede Antwort frisch generiert werden muss.",
        "Cosine-Schwelle: < 0.92 = falsche Antworten aus Cache! | > 0.98 = kaum Treffer (Std: 0.95). TTL: Std 24h. Max Einträge: Std 500."
    ),
    (
        "Modul 12 (Paket 1.2): Paralleles Map-Reduce (Fan-Out / Fan-In)",
        "Große Sammelaufgaben (z. B. 15 Dateien prüfen oder 10 Wettbewerber analysieren) dauern sequenziell extrem lange und sprengen oft das Kontextfenster.",
        "Teilt Listen-Aufgaben ab N Elementen automatisch auf parallele Map-Worker auf (Fan-Out) und führt die Teilergebnisse am Ende sauber zusammen (Fan-In).",
        "Erzeugt N-fache gleichzeitige API-Last (Gefahr von HTTP-429 Rate-Limits beim Provider) und ~20–35 % Token-Overhead durch die anschließende Reduce-Synthese.",
        "Ausschalten bei strikten API-Rate-Limits oder wenn die Teilaufgaben eng voneinander abhängen und sequenziell aufeinander aufbauen müssen.",
        "Max Worker: > 8 = Rate-Limit-Gefahr (Std: 4). Chunk-Timeout: Std 30s. Ab Elementen: Std 3."
    ),
    (
        "Modul 13 (Paket 1.3): Speculative Fast-Routing & Latenz-Hedging",
        "Wenn der primäre Cloud-LLM-Provider unter Last steht oder trödelt (Tail-Latency > 10 Sek.), blockiert die gesamte Benutzeroberfläche.",
        "Feuert nach Ablauf der Hedge-Verzögerung (z. B. 2,5 Sek.) automatisch einen parallelen Zweit-Request an das schnelle Fallback-Modell ab und nutzt die erste eintreffende Antwort.",
        "Wenn das Primärmodell kurz nach dem Hedge-Start doch noch antwortet, werden beide Requests abgerechnet (bis zu 2x Token-Kosten bei langsamen Prompts).",
        "Ausschalten bei knappem API-Budget oder wenn langsame Reasoning-Modelle genutzt werden, die regulär > 10 Sek. Denkzeit benötigen.",
        "Hedge-Verzögerung: < 1.5s = fast immer doppelte API-Kosten! | > 8s = kaum Latenz-Schutz (Std: 2.5s)."
    ),
    (
        "Modul 14 (Paket 1.4): Automatische Kontext-Komprimierung (Context Compactor)",
        "Lange Chat- und Agenten-Sitzungen überschreiten irgendwann das Token-Limit oder werden durch riesige alte Tool-Ausgaben extrem teuer und träge.",
        "Komprimiert ältere Gesprächsrunden ab der eingestellten Token-Schwelle automatisch zu einer kompakten Zusammenfassung, während die letzten N Runden im Original erhalten bleiben.",
        "Der Komprimierungslauf kostet einmalig ~1.000 Tokens; exakte Code-Zeilen oder kleine Detailwerte aus weit zurückliegenden Nachrichten können in der Zusammenfassung verloren gehen.",
        "Ausschalten, wenn der Agent wortwörtlich auf sehr frühe Nachrichten derselben Sitzung zurückgreifen muss.",
        "Token-Schwelle: < 3000 = vergisst Details zu früh | > 24000 = hohe Prompt-Kosten (Std: 6000). Letzte Turns behalten: Std 4."
    ),
    (
        "Modul 15 (Paket 1.5): Asynchrones Write-Batching (SQLite & I/O-Coalescing)",
        "Dutzende gleichzeitige Einzel-Schreibzugriffe führen bei SQLite unter Last zu database-is-locked-Fehlern und hohen I/O-Wartezeiten.",
        "Sammelt nicht-kritische Schreiboperationen im RAM-Puffer und schreibt sie gebündelt alle N Sekunden oder ab N Einträgen in einer einzigen WAL-Transaktion auf die Disk.",
        "Im Falle eines harten Stromausfalls oder kill -9 vor dem nächsten Flush-Intervall gehen die im RAM gepufferten Einträge der letzten 1–5 Sekunden verloren.",
        "Ausschalten, wenn jeder einzelne Log-Eintrag sofort und ohne Sekundenverzögerung synchron auf der Festplatte liegen muss.",
        "Batch-Größe: < 5 = viele Disk-Writes | > 100 = mehr Verlust bei Crash (Std: 25). Flush-Intervall: Std 2.0s."
    ),
    (
        "Modul 16 (Paket 2.1): Hybride Suche (BM25 + Vektor + RRF Re-Ranking)",
        "Reine Vektorsuche versteht zwar Synonyme, scheitert aber oft kläglich bei exakten Fehlercodes, Funktionsnamen, Seriennummern oder Akronymen.",
        "Kombiniert lexikalische Volltextsuche (BM25) mit semantischer Vektorsuche und verschmilzt beide Trefferlisten über Reciprocal Rank Fusion (RRF).",
        "Doppelte Index-Abfrage erhöht die Such-Latenz um ~15–40 ms; ein zu hohes Top-K (> 10) füllt den Agenten-Prompt mit tausenden Zusatz-Tokens.",
        "Fast nie ausschalten — höchstens Top-K auf 3–5 reduzieren, wenn Token-Kosten pro Anfrage minimiert werden sollen.",
        "RRF-Konstante K: Std 60. BM25-Gewicht: 0.0 = nur Vektor | 0.5 = Balance | 1.0 = nur Stichwort (Std: 0.50). Top-K: Std 5."
    ),
    (
        "Modul 17 (Paket 2.2): Temporaler Knowledge-Graph (Entitäten & Tripel)",
        "Klassisches RAG findet nur isolierte Textabschnitte, erkennt aber keine mehrstufigen Zusammenhänge über mehrere Dokumente hinweg.",
        "Extrahiert Entitäten und Beziehungen als Subjekt-Prädikat-Objekt-Tripel in einen Knowledge-Graph und traversiert Nachbarknoten über mehrere Hops.",
        "Automatische Tripel-Extraktion kostet beim Speichern ~500 Zusatz-Tokens. Ab > 2 Traversal-Hops explodiert die Anzahl der Nachbarknoten exponentiell.",
        "Auto-Extraktion ausschalten bei reinem Kurzzeit-Chat ohne langfristigen Wissensaufbau; Hops auf maximal 2 begrenzen.",
        "Max Hops: 1 = direkte Nachbarn | 2 = optimal | >= 3 = Knoten-Explosion! (Std: 2). Min. Konfidenz: Std 0.70."
    ),
    (
        "Modul 18 (Paket 2.3): Corrective RAG (CRAG) & Selbstheilende Suche",
        "Liefert die Dokumentensuche unpassende Textstellen, halluziniert das LLM trotzdem eine scheinbar plausible Antwort aus dem unbrauchbaren Kontext.",
        "Bewertet die Relevanz der gefundenen Chunks vorab (CRAG-Grader) und formuliert die Suchanfrage bei schlechtem Score automatisch bis zu N-mal um.",
        "Jede Query-Umformulierung kostet 1 zusätzlichen LLM-Call (+1,5 bis +4 Sek. Latenz). Ist die Relevanz-Schwelle zu hoch (> 0.70), dreht CRAG unnötige Extrarunden.",
        "Ausschalten, wenn die Wissensdatenbank klein und sauber gepflegt ist oder schnelle Antwortzeiten unter 2 Sekunden gefordert sind.",
        "Relevanz-Schwelle: < 0.30 = lässt schwache Quellen durch | > 0.70 = endlose Such-Schleifen (Std: 0.45). Max Rewrites: Std 2."
    ),
    (
        "Modul 19 (Paket 2.4): Hierarchischer Core-Memory-Tier (MemGPT-Prinzip)",
        "Wichtige Grundfakten über den Nutzer, aktive Projektziele oder Systemregeln rutschen bei langen Gesprächen aus dem Kontextfenster und werden vergessen.",
        "Hält bis zu N angepinnte Core-Memory-Blöcke (wie RAM-Register im Betriebssystem) dauerhaft direkt im System-Prompt jedes Agenten präsent.",
        "Jeder angepinnte Block belegt bei absolut jedem LLM-Aufruf dauerhaft Prompt-Tokens (10 Blöcke × 800 Zeichen ≈ 2.000 Tokens Grundlast pro Nachricht).",
        "Ausschalten oder Block-Anzahl auf 3–5 reduzieren, wenn kleine Modelle mit engem Kontextfenster oder knappe Token-Budgets genutzt werden.",
        "Max Blöcke: > 15 = hoher Token-Grundverbrauch (Std: 10). Max Zeichen/Block: < 300 = schneidet Regeln ab | > 1500 = verstopft Prompt (Std: 800)."
    ),
    (
        "Modul 20 (Paket 2.5): Strikte Quellen-Verankerung (Citation Pinning)",
        "KI-Antworten mischen oft echte Fakten aus Dokumenten mit frei erfundenem Modellwissen, ohne dass erkennbar ist, welcher Satz woher stammt.",
        "Zwingt den Agenten zu Inline-Quellenbelegen ([Quelle: Datei, S. X]), hängt eine Quellen-Fußzeile an und prüft die prozentuale Zitat-Abdeckung.",
        "Erhöht den Output-Token-Verbrauch um ~10–15 %; eine zu hohe Mindest-Abdeckung (> 80 %) führt bei kreativen oder zusammenfassenden Fragen zu Fehlwarnungen.",
        "Ausschalten bei freiem Brainstorming, Code-Generierung oder lockerem Alltags-Chat ohne Dokumentenbezug.",
        "Min. Abdeckung: < 30% = unbelegte Aussagen | > 85% = Fehlwarnungen bei Zusammenfassungen (Std: 60%)."
    ),
    (
        "Modul 21 (Paket 3.1): Deterministischer JSON-Schema-Zwang (Structured Outputs)",
        "Wenn LLMs vor oder nach einem JSON-Objekt Höflichkeitsfloskeln ausgeben oder ein Komma vergessen, stürzen nachfolgende Workflows und Parser sofort ab.",
        "Validiert strukturierte Ausgaben strikt gegen das erwartete Schema und repariert kaputtes JSON automatisch in bis zu N Korrekturschleifen.",
        "Jede Auto-Reparatur-Schleife kostet +1 bis +3 Sek. Latenz und zusätzliche Tokens. Strikte Schema-Validierung lehnt Antworten auch wegen harmloser Zusatzfelder ab.",
        "Strikte Validierung ausschalten, wenn API-Endpunkte oder Skripte auch mit flexiblen oder teilweisen JSON-Feldern umgehen können.",
        "Schema-Prüfung: Strikt vs. Tolerant (Std: Strikt). Max Reparaturen: 1–2 = repariert 98 % aller Tippfehler | > 3 = verschwendet Tokens (Std: 2)."
    ),
    (
        "Modul 22 (Paket 3.2): Transaktionales Schritt-Checkpointing (Durable Execution)",
        "Stürzt der Server oder Container bei Schritt 9 einer 10-schrittigen Recherche ab, ist die gesamte bisherige Arbeit samt verbrauchter Tokens verloren.",
        "Speichert nach jedem N-ten Schritt den kompletten Ausführungszustand transaktional in SQLite und nimmt unterbrochene Tasks beim Neustart automatisch wieder auf.",
        "Checkpointing bei jedem einzelnen Schritt (N = 1) erzeugt spürbare SQLite-Schreiblast. Auto-Resume beim Booten kann veraltete Tasks vom Vortag ungewollt wieder anfeuern.",
        "Auto-Resume ausschalten, wenn unterbrochene Aufgaben nach einem Neustart erst manuell geprüft und freigegeben werden sollen.",
        "Alle N Schritte: 1 = absolut absturzsicher, mehr Disk-I/O | 3–5 = schont SSD (Std: 1). Aufbewahrung: Std 14 Tage."
    ),
    (
        "Modul 23 (Paket 3.3): Idempotenz-Wächter für Tool-Aufrufe",
        "Wird ein Schritt nach einem Netzwerk-Wackler automatisch wiederholt, verschickt der Agent dieselbe E-Mail zweimal, bucht doppelt oder legt Duplikate an.",
        "Berechnet aus Tool-Name und Parametern einen deterministischen Idempotenz-Schlüssel und blockiert doppelte schreibende Ausführungen innerhalb der TTL-Frist.",
        "Wenn der Nutzer exakt denselben Befehl innerhalb der Sperrfrist (Standard 24 h) absichtlich ein zweites Mal ausführen will, blockiert der Guard.",
        "TTL-Stunden auf 1 h senken oder kurzzeitig ausschalten, wenn identische Aktionen im Testbetrieb mehrfach hintereinander ausgeführt werden müssen.",
        "TTL (Stunden): < 1h = kurzer Duplikatschutz | > 48h = blockiert gewollte Wiederholungen (Std: 24h)."
    ),
    (
        "Modul 24 (Paket 3.4): Dry-Run & Shadow-Execution-Modus (Simulations-Schalter)",
        "Neue Agenten-Workflows oder umgebaute System-Prompts lassen sich kaum gefahrlos an echten Produktionsdaten und externen APIs testen.",
        "Fängt im aktivierten Shadow-Modus alle schreibenden Datei-Tools und externen API-Calls ab, simuliert den Erfolg und protokolliert nur den geplanten Diff.",
        "SOLANGE AKTIV, WERDEN KEINE ECHTEN DATEIEN GESCHRIEBEN UND KEINE ECHTEN APIS AUSGEFÜHRT! Vergisst man den Schalter, wirkt das System nach außen hin 'tot'.",
        "Im normalen Produktivbetrieb zwingend AUSGESCHALTET lassen! Nur gezielt für Trockenübungen (Dry-Runs) und Sicherheits-Audits einschalten.",
        "Hauptschalter standardmäßig AUS (false). Nur für isolierte Testläufe aktivieren."
    ),
    (
        "Modul 25 (Paket 3.5): Dead-Letter-Queue (DLQ) mit Auto-Replay",
        "Wenn eine externe Schnittstelle (z. B. CRM, SMTP oder Webhook) kurzzeitig für 2 Minuten nicht erreichbar ist, geht der fehlgeschlagene Auftrag endgültig verloren.",
        "Fängt gescheiterte Aufträge in einer Dead-Letter-Queue (DLQ) auf und wiederholt sie zeitversetzt mit exponentiellem Backoff bis zu N-mal.",
        "Bei dauerhaft fehlerhaften Aufträgen (z. B. ungültiger API-Key) verbrauchen die Wiederholungsversuche unnötig Ressourcen; zeitversetzte Replays können Aktionen verspätet auslösen.",
        "Auto-Replay ausschalten, wenn fehlgeschlagene Aufträge ausschließlich manuell gesichtet und einzeln freigegeben werden sollen.",
        "Max Retries: 1 = bricht bei kurzem Ausfall ab | > 5 = staut tote Jobs an (Std: 3). Backoff-Basis: Std 10s (10s -> 20s -> 40s)."
    ),
    (
        "Modul 26 (Paket 4.1): Lokales PII-Scrubbing & Pseudonymisierungs-Gateway",
        "Klarnamen, E-Mail-Adressen, Telefonnummern und IBANs aus internen Dokumenten wandern bei jedem Prompt ungeschützt an externe Cloud-LLM-Anbieter.",
        "Ersetzt sensible personenbezogene Daten (PII) vor dem API-Versand lokal durch Platzhalter ([EMAIL_1], [IBAN_1]) und setzt die echten Werte in der Antwort wieder ein.",
        "Wenn das LLM den Platzhalter im Antworttext leicht abwandelt, schlägt die Rückübersetzung (Rehydrierung) fehl. Zudem kann Regex-Maskierung manchmal Code-Strings verfälschen.",
        "Ausschalten, wenn ausschließlich lokale Modelle (Ollama) genutzt werden oder das LLM zwingend die echten E-Mail-Domains/Namen analysieren muss.",
        "Granulare Schalter für E-Mails, Telefonnummern, IBANs und automatische Rehydrierung (alle standardmäßig aktiv)."
    ),
    (
        "Modul 27 (Paket 4.2): Ausgehende Netzwerk-Allowlist (Egress-Firewall)",
        "Ein durch Prompt-Injection kompromittierter Agent könnte interne Dateien oder API-Keys per HTTP-Request an einen fremden Angreifer-Server exfiltrieren.",
        "Prüft jeden ausgehenden Netzwerkaufruf gegen die Domain-Allowlist und blockiert unbekannte Ziel-Domains sowie direkte Roh-IP-Verbindungen sofort.",
        "Solange allowlist_only aktiv ist, wird jede neue Webseite, API oder Dokumentation, die nicht explizit in der Domain-Liste steht, bei Web-Recherchen hart blockiert.",
        "Ausschalten (oder benötigte Domains ergänzen), wenn der Research-Agent frei im offenen Web recherchieren soll.",
        "Erlaubte Domains: Kommagetrennte Whitelist. Roh-IP-Blockade schützt vor direkten IP-Exfiltrationen."
    ),
    (
        "Modul 28 (Paket 4.3): Rollenbasierte Tool-Rechte & Pfad-Jailing (Agent RBAC)",
        "Ohne Dateisystem-Schranken kann jedes Agenten-Profil per Pfad-Traversal (../../) auf .env-Passwortdateien oder geschützte Systemordner (/etc, /root) zugreifen.",
        "Sperrt Agenten strikt in ihr erlaubtes Workspace-Verzeichnis (Path-Jail) ein und verweigert jeden Lese-/Schreibzugriff auf .env-Dateien und Systempfade.",
        "Verhindert, dass ein Administrator-Agent legitim Konfigurationsdateien außerhalb des Projektordners wartet oder .env-Vorlagen direkt überprüft.",
        "Nur für dedizierte Systemwartungs-Aufgaben kurzzeitig lockern; der .env-Schutz sollte im Normalbetrieb immer aktiv bleiben.",
        "Schalter für Path-Jail, .env-Sperre und Systemordner-Sperre (/etc, /root, /proc)."
    ),
    (
        "Modul 29 (Paket 4.4): Ausgehender Policy- & Anti-Slop-Linter (Output Guardrail)",
        "LLMs verfallen oft in aufgeblähte KI-Floskeln ('Gerne helfe ich dir dabei!') oder schlagen in Code-Blöcken unbedacht gefährliche Löschbefehle (rm -rf /, DROP TABLE) vor.",
        "Scannt jede Antwort vor der Anzeige, entfernt typische KI-Floskeln automatisch und blockiert destruktive Shell- oder SQL-Befehle.",
        "Der Destruktiv-Filter kann auch harmlose Aufräum-Skripte oder gewollte Datenbank-Migrationen blockieren, wenn darin Befehle wie DROP oder rm -rf vorkommen.",
        "Destruktiv-Blocker kurzzeitig ausschalten, wenn gezielt Server-Aufräumskripte oder SQL-Reset-Migrationen erstellt werden.",
        "Schalter für KI-Floskeln entfernen, Destruktive Befehle blockieren und Auto-Bereinigung."
    ),
    (
        "Modul 30 (Paket 4.5): Kryptografisch signierte Ausführungs-Quittungen (Execution Receipts)",
        "Bei autonomen Agentenläufen lässt sich im Nachhinein oft nicht mehr revisionssicher beweisen, wer wann welches Modell mit welchen Kosten und welchem Ergebnis ausgeführt hat.",
        "Erzeugt für jeden Lauf eine kryptografisch verkettete SHA-256-Quittung (Hash-Chain) inklusive Zeitstempel, Tool-Spur und exakter Kostenaufstellung.",
        "Verursacht minimalen Rechen- und Speicher-Overhead (~2 ms und ~2 KB SQLite-Speicher pro Task); die Hash-Kette wächst über Monate kontinuierlich an.",
        "Kann im Produktivbetrieb dauerhaft aktiviert bleiben; nur auf extrem speicherlimitierten Kleinstsystemen ausschalten.",
        "Hash-Verkettung (SHA-256) + detaillierte Kosten-Aufschlüsselung pro Lauf."
    ),
    (
        "Modul 31 (Paket 5.1): Autonome Prompt-Selbstoptimierung (DSPy / TextGrad-Prinzip)",
        "Wenn ein Agent bei bestimmten Aufgaben immer wieder denselben Fehler macht, muss der Nutzer den System-Prompt jedes Mal mühsam von Hand nachbessern.",
        "Analysiert wiederkehrende Fehlermuster ab N Fehlschlägen automatisch und generiert präzise Korrekturregeln (Prompt-Patches) für den Agenten.",
        "Ist Auto-Apply aktiv, kann eine fehlerhaft abgeleitete Regel das Verhalten des Agenten dauerhaft verzerren (Prompt-Drift) und den System-Prompt aufblähen.",
        "Auto-Apply im Produktivbetrieb ausgeschaltet lassen, damit vorgeschlagene Prompt-Patches erst nach menschlicher Prüfung übernommen werden.",
        "Ab Fehlern: 1 = überreagiert auf Einzelfehler | > 8 = lernt sehr träge (Std: 3). Max Regeln: > 10 = bläht System-Prompt auf (Std: 5)."
    ),
    (
        "Modul 32 (Paket 5.2): Kontinuierliche Eval- & Regressions-Suite (Golden Dataset)",
        "Nach einem Modellwechsel oder einer Prompt-Änderung merkt man oft erst im Live-Betrieb, dass wichtige Kernfunktionen plötzlich schlechtere Ergebnisse liefern.",
        "Prüft Änderungen automatisch gegen einen Satz hinterlegter Referenz-Testfälle (Golden Dataset) und blockiert die Aktivierung, wenn die Bestehensquote unter X % fällt.",
        "Jeder komplette Eval-Durchlauf feuert alle hinterlegten Test-Prompts gegen die LLM-API (kostet je nach Testumfang ~5.000–25.000 Tokens und 15–60 Sek. Laufzeit).",
        "Deploy-Blockade ausschalten, wenn schnelle experimentelle Prompt-Tests ohne Wartezeit durchgeführt werden.",
        "Min. Pass-Rate: < 75% = lässt Verschlechterungen durch | 100% = blockiert schon bei kleinsten Abweichungen (Std: 90%)."
    ),
    (
        "Modul 33 (Paket 5.3): Adaptives Multi-Armed-Bandit Modell-Routing",
        "Statische Modell-Zuweisungen nutzen weiter ein teures oder aktuell gestörtes LLM, obwohl ein anderes Modell dieselbe Aufgabenklasse schneller und zuverlässiger löst.",
        "Lernt per Multi-Armed-Bandit-Algorithmus laufend aus Erfolgsquote, Latenz und Kosten und routet Aufträge dynamisch zum besten Modell.",
        "Durch die Explorationsrate (Epsilon, z. B. 0.15 = 15 %) testet der Router absichtlich immer wieder alternative Modelle aus, die im Einzelfall langsamer sein können.",
        "Ausschalten (oder Epsilon auf 0.00 setzen), wenn für jeden Lauf ein 100 % festes, vorhersagbares Modell erzwungen werden soll.",
        "Epsilon: 0.00 = nutzt stur das beste Modell | > 0.30 = probiert zu oft schwächere Modelle (Std: 0.15). Erfolgs-/Latenz-Gewicht: Std 0.60 / 0.40."
    ),
    (
        "Modul 34 (Paket 5.4): Dynamische Ad-hoc-Team-Assemblierung (Ephemeral Teams)",
        "Für einmalige Spezialprojekte existiert oft kein passendes Standard-Team, oder alte Spezial-Agenten bleiben als Karteileichen übrig.",
        "Stellt für komplexe Aufträge ad-hoc eine temporäre Task-Force aus bis zu N Spezialisten zusammen und löst das Team nach Abschluss automatisch wieder auf.",
        "Ein 4-köpfiges Ad-hoc-Team vervielfacht den Token-Verbrauch (3x bis 5x) und benötigt zusätzlichen Koordinations-Overhead zwischen den Teammitgliedern.",
        "Ausschalten bei einfachen Einzelaufgaben oder knappem Token-Budget; Max. Teamgröße im Alltag auf 3–4 begrenzen.",
        "Max Teamgröße: 2–4 = ideal | > 5 = hoher Kommunikations-Overhead & 5x Token-Verbrauch (Std: 4)."
    ),
    (
        "Modul 35 (Paket 5.5): Ressourcen-Backpressure & Selbst-Drosselung (Load Shedding)",
        "Starten mehrere Hintergrund-Jobs, Browser-Instanzen und Indexierungen gleichzeitig, läuft der Server in 100 % CPU-Last oder einen Out-of-Memory-Absturz (OOM).",
        "Überwacht CPU-, RAM- und Disk-Reserven in Echtzeit und pausiert niedrig priorisierte Hintergrund-Jobs automatisch, sobald ein Schwellenwert überschritten wird.",
        "Sind die Schwellenwerte zu niedrig eingestellt (CPU < 70 % oder RAM < 70 %), werden Hintergrund-Aufgaben schon bei normalen kurzen Lastspitzen ständig ausgebremst.",
        "Nicht komplett ausschalten — stattdessen bei starker Hardware die CPU-/RAM-Schwellen auf 90 % anheben.",
        "Max CPU/RAM: < 70% = drosselt bei normaler Arbeit | > 92% = OOM-Gefahr (Std: 85%). Min. freie Disk: Std 2.0 GB."
    ),
]


def main():
    if not os.path.exists(DOCX_PATH):
        raise FileNotFoundError(f"Handbuch nicht gefunden: {DOCX_PATH}")

    doc = Document(DOCX_PATH)

    # Prüfen, ob Kapitel 26 bereits existiert
    full_text = "\n".join(p.text for p in doc.paragraphs)
    if "Kapitel 26: Entscheidungs- & Trade-off-Matrix" in full_text:
        print("Kapitel 26 ist bereits im Handbuch enthalten.")
        return

    doc.add_page_break()
    h1 = doc.add_heading(
        "Kapitel 26: Entscheidungs- & Trade-off-Matrix aller 36 System-Module (Problem, Lösung, Preis & Schattenseite)",
        level=1,
    )
    intro = doc.add_paragraph(
        "Jedes autonome Schutz-, Performance- und Governance-Modul löst ein konkretes operatives Problem, "
        "hat aber im Gegenzug auch einen technischen oder finanziellen Preis (z. B. zusätzlicher Token-Verbrauch, "
        "Latenz-Overhead, strengere Blockaden oder Disk-I/O). Dieses Kapitel dokumentiert für alle 36 System-Module "
        "im Reiter 'AUTONOMIE & MODULE (36)' sowie die gekoppelten Plugins die vollständige Entscheidungsgrundlage: "
        "Welches Problem wird gelöst, wie greift die Lösung, was ist die Schattenseite (Trade-off), wann sollte man "
        "das Modul ausschalten und wo liegen die kritischen Schwellenwert-Kipppunkte."
    )
    intro.paragraph_format.space_after = Pt(8)

    for title, problem, solution, tradeoff, disable_hint, thresholds in MODULES_MATRIX:
        add_tradeoff_box(doc, title, problem, solution, tradeoff, disable_hint, thresholds)

    doc.save(DOCX_PATH)
    print(f"Erfolgreich aktualisiert: {DOCX_PATH} (+{len(MODULES_MATRIX)} Trade-off-Boxen in Kapitel 26)")


if __name__ == "__main__":
    main()
