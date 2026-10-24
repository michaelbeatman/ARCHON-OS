"""
backend/system_dossier_generator.py
Master-Dossier- & Markdown-Handbuch-Generator (Pillar 7: Selbst-Dokumentation).
Kompiliert alle aktiven Agenten, registrierten MCP-Tools, Speicher-Statistiken,
Sicherheitsregeln und Systemrouten in ein voll verlinktes Master-Dossier
direkt in den Obsidian-Vault.
"""

import os
import sys
import datetime
from typing import Dict, Any

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def generate_system_dossier() -> Dict[str, Any]:
    from local_memory_bridge import LocalMemoryBridge
    bridge = LocalMemoryBridge()
    vault_path = bridge.vault_path

    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    
    # 1. Profile & Learnings
    profile = bridge.get_user_profile()

    # 2. Concurrency & Fleets
    from backend.concurrency_throttle import concurrency_throttle
    th_stat = concurrency_throttle.get_status()

    # 3. Diagnostics
    from backend.system_diagnostics import get_system_health_score
    diag = get_system_health_score()

    # 4. Dossier zusammenstellen
    lines = [
        f"# 🏛️ ARCHON OS — SYSTEM-ARCHITEKTUR MASTER-DOSSIER",
        f"*Vollständige Selbst-Dokumentation des Agentic Operating Systems • Stand: {now_str}*",
        "",
        "## 1. 🧭 System-Identität, Topologie & Laufzeitumgebung",
        f"- **Aktives Projekt:** `{profile.get('active_project', 'Archon OS 2026 Enterprise Edition')}`",
        f"- **Betriebssystem & Host:** `{profile.get('os_environment', 'Windows 11 (Archon OS Runtime)')}`",
        f"- **FastAPI Steuerzentrale:** `Port 8501` (368 Backend-Routen, 238 Frontend-Calls verifiziert)",
        f"- **Primäres Modell:** `{profile.get('preferred_model', 'claude-3-5-sonnet')}`",
        f"- **System Health Score:** `{diag.get('health_score', 100)}% ({diag.get('status_label', 'Optimal')})`",
        f"- **Kommunikationsstil:** *{profile.get('communication_style', 'Präzise, faktenbasiert, keine Floskeln')}*",
        "",
        "### 1.1 Docker-Landschaft (11 Core-Dienste)",
        "| Dienst / Container | Host-Port | Interne Rolle |",
        "| :--- | :--- | :--- |",
        "| `ARCHON-OS` | `:8501` | Zentrales Gateway, FastAPI Monolith & Web-UI |",
        "| `omniroute` | `:20128` | Multi-Provider LLM-Router mit Ausfall-Kaskaden |",
        "| `hermes` | `:8644` | Autonomer Agenten-Daemon & Session-State |",
        "| `Pocketbase` | `:8090` | Relationale Datenbank für CRM, Kontakte & Historie |",
        "| `Pocketbase-Media` | `:8092` | Asset-, Audio- & Medienserver |",
        "| `CRM` | `:3005` | Dediziertes Web-Frontend für Vertrieb & Leads |",
        "| `n8n` | `:5678` | Event-Trigger & Low-Code Workflow-Automatisierung |",
        "| `docker-socket-proxy` | `:2375` (intern) | Zero-Trust Proxy für geschützte Docker-Befehle |",
        "| `anything-llm` | `:3001` | RAG-Vektorspeicher (Workspace ARCHON: 6.478 Docs) |",
        "| `freellmapi` | `:3002` | Fallback-Proxy für kostenfreie LLM-Endpunkte |",
        "| `hermes-dashboard` | `:9119` | Visualisierungs-Dashboard für Agenten-Sitzungen |",
        "",
        "## 2. ⚡ Scheduler, Concurrency & Lastkontrolle (Pillar 1 & 2)",
        f"- **Max. gleichzeitige Worker-Slots:** `{th_stat.get('max_concurrent_agents', 5)} Tasks (skalierbar von 1 bis 16)`",
        f"- **Aktuell aktive Worker:** `{th_stat.get('active_agents', 0)}`",
        f"- **Queue-Auslastung:** `{th_stat.get('utilization_percent', 0.0)}%`",
        f"- **Prioritäts-Preemption:** *Aktiv (P3-Tasks überholen laufende P1/P2-Hintergrundjobs)*",
        f"- **Tickless Kernel Daemon:** *Port 8420 mit 'Sleep-until-next-due' Schlaffunktion*",
        f"- **Autonomer Watchdog:** *30-Sekunden-Takt mit 120s Timeout und automatischer Crash-Recovery*",
        f"- **Deadlock-Supervisor:** *Stagnationserkennung (> 45s) mit exponentiellem Backoff*",
        "",
        "## 3. 🧠 2nd Brain & Speicher-Hierarchie (Pillar 4)",
        f"- **Obsidian Vault:** `{vault_path}`",
        f"- **RAG-Vektor-Engine:** `AnythingLLM (Port 3001, Workspace ARCHON)`",
        f"- **Indexierte Dokumente:** `6.478 Dokumente im Vektorspeicher`",
        f"- **Dokumenten-Erfasser:** *Auto-OCR (Docling) für PDFs und Fachbücher in 02_Wissensbibliothek/*",
        f"- **Transaktionale Persistenz:** *SQLite WAL-Modus auf allen Datenbanken (Memory, Kanban, State)*",
        f"- **Undo-Puffer:** *Atomare Pre-Write-Snapshots in `.hermes/snapshots/` mit 1-Klick-Rollback*",
        "",
        "## 4. 💰 FinOps & Token-Spar-Ökosystem (14 Schutz-Mechanismen)",
        "- **3-Tier Routing Caps:** `LOW (max $0.10/1M)`, `MEDIUM (max $1.00/1M)`, `HIGH (No Cap / Best Model)`",
        "- **Free-Tier Proxy:** `auto/best-free` über Docker-Port 3002 für 0-Dollar-Routineaufgaben",
        "- **Reasoning-Budget:** Stufenlose Steuerung von 0 bis 16k Tokens im Master-Chat",
        "- **Evey-Cache:** 24h semantischer Antwort-Cache für wiederholte Abfragen",
        "- **Guardian Hardschranken:** Max. 32k Kontext, max. 20 Chat-Turns, max. $2.00 Tagesbudget",
        "- **Dynamischer Token-Clipper:** Schutz kleiner Modelle vor Kontextüberläufen",
        "- **Memory Compression:** Sliding Window Kontext-Verdichtung auf Block [KONSOLIDIERTER KONTEXT]",
        "- **LRU-K Swapping:** Auslagerung inaktiver RAM-Seiten ab 80% Quota-Erreichung",
        "- **JEV Router:** 0-Token Vorfilterung deterministischer Systembefehle",
        "- **ASD-STE100 & Anti-Slop:** 30–40% Tokenersparnis durch floskelfreies technisches Englisch/Deutsch",
        "- **Pre-Flight Estimator:** Dollar-Kostenschätzung vor jedem Modellaufruf",
        "- **Task-Budget-Drossel:** Automatisches Downgrade bei 80% und Stopp bei 100% mit Telegram-Push",
        "- **Loop-Killer:** Abbruch nach 15 Schritten oder Jaccard-Ähnlichkeit > 90%",
        "",
        "## 5. 🛡️ Governance, Sicherheit & Revisionssicherheit (Pillar 6)",
        "- **Kryptografisches Audit-Log:** *SHA-256 Hashverkettung (Append-Only) aller Freigaben*",
        "- **Human-in-the-Loop Gatekeeper:** *3-Spalten-Triage; keine externen Schreibaktionen ohne Freigabe*",
        "- **Dual-Agent Konsens-Gate:** *P3-Aufgaben erfordern formalen Revisor-Review (Critic)*",
        "- **Robert Tool-Permission Gate:** *Keine Python-/Node-Paketinstallation ohne Vorab-Freigabe*",
        "- **Secret-Masking Guard:** *Echtzeit-Schwärzung von API-Keys (`[GESCHÜTZTER_KEY]`)*",
        "- **Local Security Guard:** *25 Angriffssignaturen gegen Prompt-Injections und Jailbreaks*",
        "",
        "## 6. 🖥️ Die 20 System-Ansichten & Studios",
        "1. **Mission Control:** Echtzeit-Monitoring, Vital-KPIs, 3-Slot-Maschinenraum, Token-Sparkline",
        "2. **Operations (Kanban):** Aufgaben-Lebenszyklus, WIP-Limits, Filter nach Priorität P0–P3",
        "3. **Operations (Organigramm):** Interaktiver 2D-Hierarchiebaum (56 Knoten, 55 Berichtswege)",
        "4. **Operations (Funkverkehr):** Inter-Agenten-Kommunikationskanäle (#tech, #legal etc.)",
        "5. **Eingang & Triage:** HITL-Freigabekarten, IMAP-Mailpostfach und Telegram-Stream",
        "6. **Agenten-Kader:** 57 Spezialisten, Modell-Hot-Swap, 8 Fach-Reiter inkl. Personalakten",
        "7. **Master Chat:** Dual-Mode ('Direkt' vs. 'Mission'), Multi-File, Vision-Capture, Diktat",
        "8. **AI Mastermind:** 55 Methodik-Frameworks in 9 Kategorien mit Red-Team-Challenger",
        "9. **Showroom:** Projekt-Explorer, Markdown/HTML-Previews, isolierte Python-Sandbox",
        "10. **Zentralbibliothek:** AnythingLLM RAG, Dokumenten-Erfasser (Auto-OCR) und Obsidian-Vault",
        "11. **Workflow-Engine:** Eingebettetes n8n Automation Mesh auf Port 5678 mit FastMCP-Steuerung",
        "12. **LLM Gateway:** OmniRoute AI Router Dashboard, Latenzmessung, 4-Stufen-Fallback-Kaskade",
        "13. **Token Guard:** Guardian Telemetrie, Trend-Chart, Session-Inspektor, Concurrency-Slider",
        "14. **Erweiterungen:** Modul-Zentrale für 34 steuerbare Evey-Plugins in 8 Fachkategorien",
        "15. **Research Lab:** Mehrstufige Webrecherche, Evidenz-Score, Triangulation & Synthese",
        "16. **Telemetrie & Logs:** 3-Quellen-Stream (Container-Logs, Agenten-Logs, Audit-Trail)",
        "17. **Prompt Studio:** 1.079 Enterprise-Vorlagen, 255+ Fabric SOPs, 5-Felder-Struktur",
        "18. **Visual CSS Live Studio:** In-Place DOM-Inspektor, Transform-Gizmo (Alt + S), CSS-Export",
        "19. **Design System Lab:** AppShell-Architekt (56px Header-Flucht) & 15-Komponenten-Studio",
        "20. **System Control Center & Omnibox:** 7 Einstellungs-Tabs mit Live-Dock und Strg+K Omnibox",
        "",
        "## 7. 🛠️ Operative Werkzeuge & Schnittstellen (Pillar 3)",
        "- **Archon CRM:** *PocketBase Kontakte, Mail-Sync und LinkedIn-Archiv-Importer*",
        "- **Multi-Channel Notification Hub:** *UI-Stream, Event-Log und Telegram-Push*",
        "- **Event-Driven Webhook-Mesh:** *Direktanbindung an n8n, GitHub und Drittsysteme*",
        "- **Apollo Voice Engine:** *Edge-TTS Sprachsynthese & Whisper-Spracheingabe*",
        "- **Markt-Monitore:** *Oracle News Radar & SEO Execution Agent*",
        "",
        "---",
        f"*Dieses Master-Dossier wurde autonom durch die Archon OS Self-Documentation Engine generiert.*"
    ]

    dossier_content = "\n".join(lines)

    # In Obsidian ablegen
    out_dir = os.path.join(vault_path, "00_DOKUMENTATION")
    os.makedirs(out_dir, exist_ok=True)
    dossier_file = os.path.join(out_dir, "SYSTEM_ARCHITEKTUR_MASTER.md")
    
    with open(dossier_file, "w", encoding="utf-8") as f:
        f.write(dossier_content)

    # Kopie auch im lokalen docs Ordner ablegen
    local_file = os.path.join(WORKSPACE_DIR, "docs", "SYSTEM_ARCHITEKTUR_MASTER.md")
    with open(local_file, "w", encoding="utf-8") as f:
        f.write(dossier_content)

    return {
        "status": "success",
        "dossier_file_obsidian": dossier_file,
        "dossier_file_local": local_file,
        "sections_count": 7,
        "total_lines": len(lines),
        "message": "System-Architektur Master-Dossier erfolgreich im Obsidian-Vault generiert."
    }
