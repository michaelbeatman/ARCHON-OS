# -*- coding: utf-8 -*-
"""
Aktualisiert alle 26 aktiven Archon-OS-Plugins in /opt/data/plugins mit detaillierter
Dreiteilung: Problem -> Lösung -> Preis / Schattenseite (inkl. konkreter Zahlen & Wann ausschalten).
"""
import os
import shutil
import yaml

PLUGINS_DIR = "/opt/data/plugins"
ARCHIVE_DIR = "/opt/data/plugins/_archive_legacy"
CONFIG_YAML = "/opt/data/config.yaml"

DEAD_PLUGINS = [
    "evey-moltbook",
    "evey-github",
    "evey-habits",
    "evey-wallet",
    "evey-mqtt",
    "evey-news",
    "evey-bridge",
    "evey-commands",
]

ARCHON_PLUGINS_META = {
    "evey-cost-guard": {
        "display_name": "Cost Guard & Budget-Wächter",
        "category": "Sicherheit & Wächter",
        "provides_tools": ["cost_check", "budget_guard_enforce"],
        "problem": "Endlosschleifen, unbemerkte Subagenten-Kaskaden oder teure Frontier-Modelle (Opus/GPT-4o) können in wenigen Minuten das Tagesbudget verbrennen.",
        "solution": "Überwacht Token-Ausgaben in Echtzeit vor jedem Call und schaltet ab Erreichen der Warnschwelle (80%) automatisch auf günstige Fast-Modelle um oder stoppt bei 100%.",
        "tradeoff": "Kann mitten in einer komplexen Analyse abrupt auf ein schwächeres Modell herunterstufen (Qualitätsverlust bei Code/Mathe) oder einen fast fertigen Großauftrag bei 100% hart abbrechen.",
        "when_to_disable": "Ausschalten, wenn ein kritischer Großauftrag zwingend bis zum Ende mit dem stärksten Frontier-Modell durchlaufen muss – unabhängig von den Kosten.",
    },
    "evey-session-guard": {
        "display_name": "Session Guard & Durable Checkpoints",
        "category": "Sicherheit & Wächter",
        "provides_tools": ["session_checkpoint_save", "compact_context"],
        "problem": "Bei langen Sitzungen (>20 Schritte) läuft das Kontextfenster über ('Context Rot', steigende API-Kosten) und bei Container-Neustarts geht der gesamte Arbeitsstand verloren.",
        "solution": "Speichert nach jedem Schritt einen SQLite-Checkpoint (Durable Execution) zum nahtlosen Fortsetzen und verdichtet ältere Dialogrunden automatisch per Sliding-Window.",
        "tradeoff": "Kostet pro Schritt ~5–15 ms zusätzlichen SQLite-Disk-I/O; durch die Kontext-Kompaktierung können feine Details oder exakte Code-Zeilen aus sehr frühen Chat-Nachrichten verloren gehen.",
        "when_to_disable": "Ausschalten, wenn der Agent wortwörtlich auf jede einzelne Zeile eines sehr langen Original-Protokolls zugreifen muss, ohne dass ältere Runden zusammengefasst werden.",
    },
    "evey-email-guard": {
        "display_name": "Injection-Schild & DSGVO PII-Scrubber",
        "category": "Sicherheit & Wächter",
        "provides_tools": ["screen_email_injection", "pii_scrub_text"],
        "problem": "Eingehende E-Mails können versteckte Prompt-Injections ('Ignoriere alle Regeln...') enthalten; zudem dürfen Klarnamen, IBANs und E-Mail-Adressen laut DSGVO nicht ungeschützt an externe Cloud-LLMs abfließen.",
        "solution": "Scannt externe Texte vorab auf Injection-Muster und ersetzt personenbezogene Daten vor dem API-Versand durch Platzhalter ([EMAIL_1], [IBAN_1]) mit anschließender Re-Hydration.",
        "tradeoff": "Fügt ~10–30 ms Regex-/Scan-Latenz hinzu; strenge Filterung kann legitime E-Mails über IT-Sicherheit fälschlich als Angriff blockieren (False Positives) oder Zahlenkolonnen versehentlich als Telefonnummer schwärzen.",
        "when_to_disable": "Nur bei rein lokalen Offline-Modellen (Ollama) ausschalten oder wenn das LLM zwingend die echten Domains/E-Mail-Adressen für eine DNS-/Reputationsanalyse sehen muss.",
    },
    "evey-watchdog": {
        "display_name": "30s Kernel-Watchdog & Backpressure",
        "category": "Sicherheit & Wächter",
        "provides_tools": ["watchdog_healthcheck", "resource_backpressure_check"],
        "problem": "Hängende Netzwerk-Calls blockieren Worker-Slots dauerhaft (Deadlocks), und parallele Subagenten-Spitzen können Host-RAM und CPU bis zum Systemabsturz (OOM-Kill) überlasten.",
        "solution": "Prüft alle 30 Sekunden alle laufenden Tasks, bricht festgefressene Prozesse nach Timeout ab und pausiert neue Niedrig-Prioritäts-Tasks automatisch ab 85% CPU-/RAM-Last.",
        "tradeoff": "Kann sehr langsame, aber legitime Deep-Thinking- oder große Datei-Indexierungs-Jobs fälschlich als 'hängend' einstufen und vorzeitig abwürgen; Backpressure verzögert Hintergrund-Jobs bei Lastspitzen.",
        "when_to_disable": "Kurzzeitig ausschalten (oder Timeout hochsetzen), wenn mehrminütige lokale Kompilierungs-, Video- oder Batch-Aufträge ohne Unterbrechung durchlaufen sollen.",
    },
    "evey-cache": {
        "display_name": "Semantischer Prompt- & Antwort-Cache",
        "category": "Performance & Cache",
        "provides_tools": ["semantic_cache_lookup", "semantic_cache_store"],
        "problem": "Wiederkehrende oder leicht umformulierte Fragen kosten jedes Mal volle LLM-Wartezeit (2–8 Sek.) und unnötige API-Gebühren.",
        "solution": "Vergleicht neue Prompts per Cosine-Similarity (ab 0.90) mit gespeicherten Antworten in SQLite und liefert Treffer in unter 10 ms für $0.00 aus.",
        "tradeoff": "Gefahr veralteter Daten ('Stale Cache' bis zum Ablauf der TTL von 24h) sowie das Risiko, dass zwei ähnlich klingende Fragen mit kleinem, aber entscheidendem Bedeutungsunterschied dieselbe alte Antwort erhalten.",
        "when_to_disable": "Ausschalten bei Echtzeit-Abfragen (Live-Kurse, aktuelles Server-Log, heutige Nachrichten) oder wenn kreativer, jedes Mal neu generierter Text gewünscht ist.",
    },
    "evey-telemetry": {
        "display_name": "Time-Travel-Debugger & Write-Batcher",
        "category": "Monitoring & Analytics",
        "provides_tools": ["trace_snapshot_record", "write_batcher_flush"],
        "problem": "Wenn ein Agent in Schritt 12 einen falschen Pfad einschlägt, weiß man ohne Zwischenstände nicht warum, und hunderte synchrone Log-Schreibzugriffe bremsen die Datenbank aus.",
        "solution": "Speichert jeden Schritt als Time-Travel-Snapshot (inkl. Replay/Fork ab Schritt X) und bündelt Telemetrie-Schreibvorgänge im RAM zu asynchronen Sammel-Transaktionen (alle 2,5 Sek.).",
        "tradeoff": "Erhöht den SQLite-Speicherbedarf auf der Festplatte spürbar (~50–200 KB pro komplexer Mission); beim Write-Batcher können im Fall eines harten Stromausfalls die letzten 2,5 Sekunden Telemetrie im RAM verloren gehen.",
        "when_to_disable": "Time-Travel ausschalten, wenn der Festplattenspeicher knapp wird oder maximale Ausführungsgeschwindigkeit ohne Audit-Snapshots gefragt ist.",
    },
    "evey-status": {
        "display_name": "Execution-Receipt-Ledger (SHA-256)",
        "category": "Monitoring & Analytics",
        "provides_tools": ["issue_execution_receipt", "verify_receipt_chain"],
        "problem": "Ohne revisionssicheren Nachweis lässt sich nachträglich nicht belegen, welcher Agent wann welches Tool mit welchem Token-Preis aufgerufen hat.",
        "solution": "Erzeugt für jede abgeschlossene Aktion eine kryptografisch verkettete SHA-256-Quittung (Hash-Chain wie eine lokale Mini-Blockchain) inklusive USD-Kostenaufschlüsselung.",
        "tradeoff": "Wächst kontinuierlich in der SQLite-Datenbank an (Append-Only Ledger) und kostet ~3–8 ms Hashing- & Schreibzeit pro abgeschlossener Aktion.",
        "when_to_disable": "Ausschalten in reinen Test-/Spielumgebungen, in denen keine Revisionssicherheit oder Kosten-Quittierung benötigt wird.",
    },
    "evey-delegation-score": {
        "display_name": "Modell-Benchmarker & Gold-Eval-Suite",
        "category": "Monitoring & Analytics",
        "provides_tools": ["model_benchmark_score", "run_eval_regression_suite"],
        "problem": "Modell-Updates beim Provider oder Änderungen am System-Prompt verschlechtern oft schleichend die Antwortqualität, ohne dass es sofort auffällt.",
        "solution": "Misst kontinuierlich Antwortgüte, Latenz und Token-Effizienz jedes Modells und prüft Prompt-Änderungen gegen eine Gold-Standard-Testsuite (mind. 90% Pass-Rate).",
        "tradeoff": "Das Ausführen der Regression-Test-Suite erzeugt zusätzliche Hintergrund-API-Calls (Token-Kosten) und blockiert bei strenger Einstellung (90% Gate) schnelle Prompt-Experimente.",
        "when_to_disable": "Ausschalten, wenn du Prompts schnell und unbürokratisch im Live-Betrieb umbauen willst, ohne auf den Durchlauf der Test-Suite zu warten.",
    },
    "evey-autonomy": {
        "display_name": "Ephemeral Task-Force & Dry-Run-Simulator",
        "category": "Agenten-Intelligenz",
        "provides_tools": ["spawn_ephemeral_team", "simulate_dry_run"],
        "problem": "Ein einzelner Generalisten-Agent scheitert oft an vielschichtigen Großprojekten, während ungetestete destruktive Tool-Calls (Löschen, Senden, DB-Schreiben) reale Schäden anrichten können.",
        "solution": "Spawnt bei Bedarf kurzlebige Spezialisten-Teams (Architect, Coder, QA, Security) und simuliert kritische Aktionen vorab gefahrlos im Dry-Run-Modus.",
        "tradeoff": "Ein 4-köpfiges Ephemeral-Team vervielfacht den Token-Verbrauch um den Faktor 3x bis 4x und erhöht die Gesamtlaufzeit um +10 bis +30 Sekunden.",
        "when_to_disable": "Ausschalten bei einfachen Alltagsaufgaben oder engem Token-Budget, damit ein einzelner Agent direkt ohne Team-Overhead antwortet.",
    },
    "evey-council": {
        "display_name": "Multi-Agenten Konsens-Gate (Boardroom)",
        "category": "Agenten-Intelligenz",
        "provides_tools": ["council_consensus_vote"],
        "problem": "Ein einzelnes LLM unterliegt oft Halluzinationen oder blinden Flecken bei folgenschweren Architektur-, Finanz- oder Sicherheitsentscheidungen.",
        "solution": "Holt vor kritischen Freigaben unabhängige Voten mehrerer Prüfer-Rollen (Security, Logic, Quality) ein und verlangt eine Mehrheit (z. B. 2 von 3 Stimmen).",
        "tradeoff": "Verdreifacht die Token-Kosten für den jeweiligen Prüfschritt (~3x API-Calls) und erhöht die Antwortzeit um +3 bis +8 Sekunden; zudem Gefahr von 'Entscheidungsstarre' bei Stimmengleichheit.",
        "when_to_disable": "Ausschalten, wenn schnelle Direkt-Ausführung wichtiger ist als mehrstufige Gegenprüfung durch ein Gremium.",
    },
    "evey-reflect": {
        "display_name": "Task-Selbstheilung & TextGrad-Optimizer",
        "category": "Agenten-Intelligenz",
        "provides_tools": ["self_heal_task", "optimize_system_prompt"],
        "problem": "Schlägt ein Tool-Call wegen eines falschen Parameters fehl, bricht ein normaler Agent sofort mit einer Fehlermeldung ab und macht denselben Fehler beim nächsten Mal wieder.",
        "solution": "Fängt Tool-Fehler ab, analysiert den Traceback zur automatischen Korrektur (Self-Healing) und generiert ab 3 Fehlschlägen per TextGrad einen Regel-Patch für den System-Prompt.",
        "tradeoff": "Bis zu 2 automatische Heilungsversuche kosten bei echten Ausfällen (z. B. Zielserver komplett offline) zusätzliche Retry-Tokens und +5 bis +15 Sekunden Wartezeit; Auto-Prompt-Patches können Prompts mit der Zeit aufblähen.",
        "when_to_disable": "Ausschalten beim gezielten Debuggen, wenn du jeden rohen Fehler sofort ungefiltert sehen willst statt automatischer Reparaturversuche.",
    },
    "evey-learner": {
        "display_name": "Erfahrungs-Gedächtnis & Skill-Synthesizer",
        "category": "Agenten-Intelligenz",
        "provides_tools": ["learn_from_interaction", "synthesize_runtime_skill"],
        "problem": "Ohne Erfahrungsspeicher muss der Agent wiederkehrende mehrstufige Abläufe jedes Mal von Grund auf neu erfinden.",
        "solution": "Extrahiert erfolgreiche Lösungswege als Lektionen in SQLite und bündelt wiederkehrende Befehlsfolgen (ab 3 Wiederholungen) automatisch zu wiederverwendbaren Skills (SKILL.md).",
        "tradeoff": "Risiko von 'Fehl-Lernen' (Suboptimale Workarounds werden als vermeintliche Best Practice verfestigt); zu viele injizierte Lektionen kosten zusätzliche Prompt-Tokens bei jedem Call.",
        "when_to_disable": "Ausschalten, wenn das System keine neuen Skills selbstständig im Dateisystem anlegen soll oder der Verhaltenstand eingefroren werden soll.",
    },
    "evey-identity": {
        "display_name": "Core-Memory-Pinner (Persona & Direktiven)",
        "category": "Agenten-Intelligenz",
        "provides_tools": ["core_memory_read", "core_memory_upsert"],
        "problem": "Wichtige Nutzer-Vorgaben, Tonalitätsregeln und der aktuelle Projektfokus rutschen bei langen Gesprächen irgendwann aus dem aktiven Kontextfenster.",
        "solution": "Reserviert feste, unverdrängbare Speicherblöcke (bis 2.000 Zeichen pro Block) direkt im obersten Bereich jedes System-Prompts (nach dem MemGPT/Letta-Prinzip).",
        "tradeoff": "Belegt permanent ~500 bis 1.500 Tokens des Kontextfensters bei absolut jedem API-Aufruf – auch bei simplen Ein-Wort-Fragen, die diesen Kontext gar nicht bräuchten.",
        "when_to_disable": "Ausschalten, wenn du maximale Token-Sparsamkeit bei kurzen Einzelbefehlen brauchst oder einen völlig neutralen Agenten ohne Vorwissen testen willst.",
    },
    "evey-proactive": {
        "display_name": "Inbox-Watcher & Event-Trigger-Daemon",
        "category": "Agenten-Intelligenz",
        "provides_tools": ["inbox_watcher_poll"],
        "problem": "Ohne Hintergrund-Überwachung reagiert das System nur auf manuelle Klicks, während wichtige E-Mails oder Datei-Eingänge stundenlang unbearbeitet liegen bleiben.",
        "solution": "Prüft im Hintergrund-Intervall (alle 300 Sek.) Posteingang und Eingangsordner und stößt bei neuen Eingängen selbstständig die Vorab-Triage an.",
        "tradeoff": "Erzeugt regelmäßigen Hintergrund-Traffic (IMAP/Filesystem-Polls) und verbraucht bei automatischer KI-Triage unaufgefordert Tokens für jede eingehende Werbe- oder Newsletter-Mail.",
        "when_to_disable": "Ausschalten, wenn das System ausschließlich auf deinen ausdrücklichen Befehl hin aktiv werden und im Hintergrund 0,00 $ verbrauchen soll.",
    },
    "evey-goals": {
        "display_name": "Map-Reduce Parallel-Executor",
        "category": "Planung & Tasks",
        "provides_tools": ["execute_map_reduce"],
        "problem": "Wenn ein Agent 10 Dokumente oder 20 Kundenprofile nacheinander abarbeitet, dauert der Durchlauf Minuten und sprengt ein einzelnes Kontextfenster.",
        "solution": "Teilt große Aufgabenpakete per Fan-Out auf bis zu 4 parallele Async-Worker mit isoliertem Einzelkontext auf und führt die Teilergebnisse am Ende zusammen (Fan-In).",
        "tradeoff": "Erzeugt kurzzeitige API-Rate-Limit-Spitzen (429 Too Many Requests bei engen Provider-Limits) plus einen zusätzlichen Synthese-Call zum Zusammenführen der Teilantworten.",
        "when_to_disable": "Ausschalten bei kostenlosen/streng limitierten API-Keys (z. B. Groq Free Tier mit niedrigem RPM-Limit), wo parallele Requests sofort in Rate-Limits laufen.",
    },
    "evey-scheduler": {
        "display_name": "Idempotenz-Guard & Dead-Letter-Queue (DLQ)",
        "category": "Planung & Tasks",
        "provides_tools": ["idempotency_check", "dlq_enqueue_replay"],
        "problem": "Bei Netzwerk-Timeouts oder Retries werden E-Mails, Webhooks oder Datenbank-Einträge oft versehentlich doppelt ausgeführt, während endgültig abgebrochene Tasks spurlos verschwinden.",
        "solution": "Blockiert identische Tool-Aufrufe innerhalb von 24 Stunden per SHA-256-Idempotenz-Schlüssel und legt gescheiterte Aufträge zur späteren Wiederholung in der Dead-Letter-Queue ab.",
        "tradeoff": "Wenn du absichtlich zweimal kurz hintereinander exakt denselben Befehl mit denselben Parametern ausführen willst, blockiert der Idempotenz-Guard den zweiten Aufruf und liefert nur das gespeicherte Erst-Ergebnis.",
        "when_to_disable": "Idempotenz-Guard kurz ausschalten, wenn identische Test-Aufrufe (z. B. Test-Webhook zweimal hintereinander feuern) bewusst mehrfach ausgeführt werden sollen.",
    },
    "evey-telegram-ux": {
        "display_name": "Telegram-Gateway & Mobile Bot-Brücke",
        "category": "Brücken & Schnittstellen",
        "provides_tools": ["telegram_send_card"],
        "problem": "Unterwegs hat man keinen Zugriff auf das lokale Dashboard und verpasst dringende HITL-Freigaben oder Systemalarme.",
        "solution": "Verbindet Archon OS bidirektional mit deinem Telegram-Bot für formatierte Statuskarten, mobile Befehlseingabe und Sofort-Benachrichtigungen.",
        "tradeoff": "Externe Angriffsfläche über die Telegram-API (erfordert strikte Chat-ID-Whitelist); bei vielen Status-Updates kann es zu Benachrichtigungs-Spam auf dem Smartphone kommen.",
        "when_to_disable": "Ausschalten, wenn Archon OS komplett abgeschottet nur lokal im Browser ohne externe Messenger-Anbindung betrieben werden soll.",
    },
    "evey-research": {
        "display_name": "Deep-Research Lab & Corrective Web-Fallback",
        "category": "Tools & Recherche",
        "provides_tools": ["deep_research_query", "crag_web_fallback"],
        "problem": "Wenn die lokale Wissensdatenbank keine passenden Dokumente zu einer Frage enthält, erfindet (halluziniert) ein Standard-RAG-System oft plausibel klingende Falschantworten.",
        "solution": "Prüft vor der Antwort die Relevanz der gefundenen Textstellen (CRAG-Schwelle 0.45); fällt sie durch, wird die Anfrage automatisch umformuliert und auf externe Web-/Fakten-Suche erweitert.",
        "tradeoff": "Wenn der Fallback greift, verlängert sich die Antwortzeit deutlich um +2 bis +6 Sekunden und es fließen Suchbegriffe an externe Such-Endpunkte ab.",
        "when_to_disable": "Web-Fallback ausschalten, wenn Antworten aus Geheimhaltungsgründen zu 100% nur aus dem lokalen Tresor stammen dürfen ('Air-Gapped Vault Only').",
    },
    "evey-digest": {
        "display_name": "Autonomes Morgen-Briefing (Daily Standup)",
        "category": "Tools & Recherche",
        "provides_tools": ["generate_daily_standup"],
        "problem": "Nach nächtlichen Hintergrund-Läufen und E-Mail-Eingängen fehlt morgens der schnelle Überblick, was erledigt wurde und wo Entscheidungen anstehen.",
        "solution": "Generiert täglich zur eingestellten Uhrzeit (z. B. 07:30 Uhr) automatisch einen kompakten Standup-Report über offene Tasks, Posteingang und Systemgesundheit.",
        "tradeoff": "Verbraucht jeden Morgen automatisch ein kleines Token-Kontingent (~2.000–4.000 Tokens) – auch an freien Tagen oder Wochenenden, an denen du gar nicht arbeitest.",
        "when_to_disable": "Ausschalten, wenn du Statusberichte lieber nur auf Knopfdruck abrufst statt täglich automatisiert.",
    },
    "evey-sandbox": {
        "display_name": "Ephemeral Docker-Sandbox (Code-Isolation)",
        "category": "Tools & Execution",
        "provides_tools": ["run_ephemeral_sandbox"],
        "problem": "Vom Agenten geschriebener Python- oder Bash-Code kann bei direkter Ausführung auf dem Host versehentlich Systemdateien beschädigen, Endlosschleifen erzeugen oder Geheimnisse auslesen.",
        "solution": "Startet für jede Code-Ausführung eine isolierte Wegwerf-Umgebung mit hartem CPU-/RAM-Deckel (512 MB), 30s Timeout und komplett gekapptem Netzwerk (--network none).",
        "tradeoff": "Container-Start kostet ~300–800 ms Zusatzlatenz pro Aufruf; durch die Netzwerksperre schlagen Skripte fehl, die im Lauf `pip install` oder externe HTTP-Requests benötigen.",
        "when_to_disable": "Netzwerksperre oder Sandbox lockern, wenn das ausgeführte Skript gezielt externe APIs abfragen oder Pakete nachladen muss.",
    },
    "evey-rag": {
        "display_name": "Hybrid-RAG (BM25 + Vektor + Wissensgraph)",
        "category": "Gedächtnis & Wissen",
        "provides_tools": ["hybrid_rag_search", "knowledge_graph_query", "crag_retrieve"],
        "problem": "Reine Vektorsuche übersieht oft exakte Artikelnummern, Paragrafen oder Eigennamen, während reine Stichwortsuche (BM25) keine inhaltlichen Zusammenhänge versteht.",
        "solution": "Kombiniert exakte BM25-Stichwortsuche und semantische Vektorsuche per Reciprocal Rank Fusion (RRF) plus SQLite-Wissensgraph (Subjekt-Prädikat-Objekt-Tripel).",
        "tradeoff": "Dreifache Suchpipeline (BM25 + Cosine + Graph-Traversierung) benötigt ~20–60 ms mehr Rechenzeit beim Abruf und speichert beim Indexieren zusätzliche Graph-Tripel in SQLite.",
        "when_to_disable": "Nur bei extrem großem Dokumentenbestand und knapper CPU auf einfache Stichwortsuche reduzieren.",
    },
    "evey-memory-adaptive": {
        "display_name": "Adaptives Gedächtnis & Citation-Pinner",
        "category": "Gedächtnis & Wissen",
        "provides_tools": ["adaptive_memory_recall", "pin_citations"],
        "problem": "Veraltete Erinnerungen überfluten mit der Zeit den Kontext, und bei RAG-Antworten lässt sich oft nicht prüfen, ob ein Satz wirklich im Dokument stand oder erfunden wurde.",
        "solution": "Lässt ungenutzte Erinnerungen per Halbwertszeit (14 Tage) verblassen und erzwingt bei Wissensantworten harte Quellen-Spans ([Quelle: doc_id#chunk]) mit Wort-Überlappungsprüfung.",
        "tradeoff": "Strikte Zitat-Verankerung kann kreative oder frei formulierte Zusammenfassungen als 'unbelegt' markieren; der Decay-Mechanismus kann selten genutzte, aber wichtige Fakten nach Wochen ausblenden.",
        "when_to_disable": "Citation-Pinner ausschalten bei freiem Brainstorming, Textentwürfen oder E-Mail-Formulierungen, bei denen keine Quellen-Klammern im Text stehen sollen.",
    },
    "evey-memory-consolidate": {
        "display_name": "Nächtliche Sleep-Cycle Konsolidierung",
        "category": "Gedächtnis & Wissen",
        "provides_tools": ["consolidate_memory_now"],
        "problem": "Ohne regelmäßige Datenpflege blähen sich SQLite-Tabellen, temporäre Heartbeat-Logs und doppelte Gedächtniseinträge über Wochen immer weiter auf.",
        "solution": "Bereinigt nachts um 03:00 Uhr abgelaufene Logs (älter als 14 Tage), fasst nahezu identische Gedächtniseinträge (Cosine >= 0.92) zusammen und führt SQLite VACUUM/WAL-Checkpoints aus.",
        "tradeoff": "Während des nächtlichen Laufs sind die Datenbanken für einige Sekunden kurz gesperrt; bei zu aggressiver Ähnlichkeitsschwelle (<0.88) können ähnlich klingende, aber unterschiedliche Fakten verschmolzen werden.",
        "when_to_disable": "Ausschalten, wenn du aus Forensik- oder Debugging-Gründen sämtliche historischen Roh-Logs lückenlos ohne Zeitablauf behalten willst.",
    },
    "evey-validate": {
        "display_name": "SLA-Vertragsprüfer & Structured-Output-Guard",
        "category": "Qualität & Ausführung",
        "provides_tools": ["enforce_sla_contract", "enforce_structured_json"],
        "problem": "Günstige oder schnelle Modelle liefern statt sauberem JSON oft Markdown-Erklärtexte drumherum oder vergessen Pflichtfelder, wodurch nachgelagerte Pipelines abstürzen.",
        "solution": "Validiert jede Ausgabe gegen das geforderte JSON-Schema und Qualitäts-SLAs (Mindestscore 0.75) und schickt fehlerhafte Strukturen bis zu 3-mal mit gezieltem Fehler-Prompt zur Selbstkorrektur zurück.",
        "tradeoff": "Jeder Korrektur-Durchlauf bei ungültigem JSON kostet einen kompletten zusätzlichen LLM-Call (+1x bis +3x Tokens und +2 bis +6 Sek. Wartezeit).",
        "when_to_disable": "Ausschalten bei lockeren Chat-Konversationen, in denen keine strikten JSON-Strukturen oder formellen Abnahmekriterien benötigt werden.",
    },
    "evey-verification": {
        "display_name": "Egress-Firewall, RBAC-Jail & Policy-Linter",
        "category": "Qualität & Ausführung",
        "provides_tools": ["egress_firewall_check", "rbac_permission_check", "lint_output_policy"],
        "problem": "Kompromittierte Agenten könnten Daten an fremde Webhooks exfiltrieren, auf `.env`-Schlüsseldateien zugreifen oder Antworten voller KI-Floskeln ('delve', 'testament') und gefährlicher `rm -rf`-Befehle ausgeben.",
        "solution": "Blockiert alle nicht auf der Allowlist stehenden Domains (Egress-Firewall), sperrt jeden Agenten in seinen Datei-/Tool-Scope (RBAC-Jail) und bereinigt Ausgaben vorab per Output-Linter.",
        "tradeoff": "Die Egress-Firewall blockiert legitime Web-Recherchen auf neuen, noch nicht freigeschalteten Domains; das RBAC-Jail verhindert, dass ein Agent spontan außerhalb seines Rollen-Ordners aushilft.",
        "when_to_disable": "Egress-Firewall auf 'Offen' stellen, wenn der Research-Agent frei im gesamten Web nach beliebigen neuen Quellen recherchieren soll.",
    },
    "evey-delegate-model": {
        "display_name": "Speculative Hedging & Bandit-Modell-Router",
        "category": "Qualität & Ausführung",
        "provides_tools": ["bandit_select_model", "hedged_completion"],
        "problem": "Ein einzelner Cloud-Provider hat oft plötzliche Latenz-Ausreißer (>10 Sek. Wartezeit), und starre Routing-Regeln merken nicht, welches Modell heute tatsächlich am besten abschneidet.",
        "solution": "Wählt Modelle dynamisch per Multi-Armed Bandit (UCB1 aus Erfolgsquote & Latenz) und feuert nach 3,5 Sek. ohne Antwort automatisch einen parallelen Backup-Request an einen Zweit-Provider ab.",
        "tradeoff": "Immer wenn das Hedging nach 3,5 Sek. auslöst, laufen kurzzeitig zwei Requests parallel (bis zu ~1,5x bis 2x Token-Kosten für diesen Call); der Bandit-Router probiert in 15% der Fälle (Epsilon 0.15) testweise alternative Modelle aus.",
        "when_to_disable": "Speculative Hedging ausschalten, wenn Kostenminimierung absoluten Vorrang vor Antwortgeschwindigkeit hat.",
    },
}


def main():
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    for dp in DEAD_PLUGINS:
        src = os.path.join(PLUGINS_DIR, dp)
        dst = os.path.join(ARCHIVE_DIR, dp)
        if os.path.exists(src):
            if os.path.exists(dst):
                shutil.rmtree(dst)
            shutil.move(src, dst)

    for pid, meta in ARCHON_PLUGINS_META.items():
        pdir = os.path.join(PLUGINS_DIR, pid)
        os.makedirs(pdir, exist_ok=True)
        pyaml = os.path.join(pdir, "plugin.yaml")
        data = {
            "name": pid,
            "display_name": meta["display_name"],
            "description": f"Problem: {meta['problem']} | Lösung: {meta['solution']} | Preis/Risiko: {meta['tradeoff']}",
            "problem": meta["problem"],
            "solution": meta["solution"],
            "tradeoff": meta["tradeoff"],
            "when_to_disable": meta["when_to_disable"],
            "category": meta["category"],
            "version": "2.6.0",
            "provides_tools": meta["provides_tools"],
        }
        with open(pyaml, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)

    print(f"Alle {len(ARCHON_PLUGINS_META)} Plugins mit Problem/Lösung/Preis/Abschalt-Empfehlung aktualisiert.")


if __name__ == "__main__":
    main()
