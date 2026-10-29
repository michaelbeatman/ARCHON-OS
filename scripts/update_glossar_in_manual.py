import sys
import docx
from pathlib import Path

def update_table_cell(cell, additions):
    """
    additions: dict mapping prefix (e.g. 'Mechanik:', 'Nutzen:') to text to append.
    """
    for p in cell.paragraphs:
        for prefix, extra_text in additions.items():
            if p.text.startswith(prefix):
                # Check if extra_text is already present
                if extra_text.strip()[:30] in p.text:
                    continue
                # Append a run to this paragraph
                run = p.add_run(extra_text)
                # Keep font size consistent if possible
                if len(p.runs) > 1 and p.runs[1].font.size:
                    run.font.size = p.runs[1].font.size
                    run.font.name = p.runs[1].font.name

def run():
    vorlage_path = Path("docs/system/ARCHON_OS_SYSTEM_HANDBUCH_2026_Vorlage.docx")
    glossar_path = Path("docs/ARCHON_OS_SYSTEM_GLOSSAR_2026.docx")

    # Define additions per title substring
    updates = {
        "Operations – Kanban Board": {
            "Mechanik:": " Integriert das 4-Augen Qualitäts-Gate: Vor Verschieben einer Aufgabe auf 'done' prüft ein Peer-Reviewer (Katharina Völk für QM/Compliance oder Robert) das Arbeitsergebnis auf Vollständigkeit, Substanz und Handlungsfähigkeit (1–100% Score). Bei 'changes_requested' greift eine Status-Sperre; ein Human-in-the-Loop Override (force=True) übersteuert bei Bedarf.",
            "Nutzen:": " Verhindert unfertige Arbeitsstände im 'done'-Status durch zwingendes Vier-Augen-Review."
        },
        "Master Chat (Dual-Mode Workspace": {
            "Mechanik:": " Beinhaltet die Telegram Voice-Pipeline: Eingehende Sprachnachrichten (.ogg/Opus) von unterwegs werden via Whisper/Gemini transkribiert, anhand von Rufnamen (/robert, /anwalt etc.) an den Fachagenten geroutet und Antworten via edge-tts (de-DE-ConradNeural) als natürliche Sprachmemos direkt auf Telegram zurückgesendet.",
            "Nutzen:": " Ermöglicht vollständige mobile Sprachbedienung und bidirektionalen Audio-Austausch über Telegram."
        },
        "Showroom (Projekt-Explorer": {
            "Mechanik:": " Erweitert um den interaktiven Showroom Live-Runner: Ermöglicht die direkte Ausführung von Python- und Code-Dateien im Browser mit 12s Timeout, isoliertem Scratch-Verzeichnis und ausklappbarem Terminal-Drawer (STDOUT, STDERR, Exit-Code und Millisekunden-Laufzeit).",
            "Nutzen:": " Code-Artefakte und Skripte lassen sich ohne Konsolenwechsel direkt im Showroom verifizieren und testen."
        },
        "Erweiterungen & Modul-Zentrale": {
            "Mechanik:": " Beinhaltet das standardisierte Pluginsystem & Runtime-Hooks: Modulare Ordnerstruktur (plugins/<plugin_id>/plugin.json), 4 Lifecycle-Hooks (on_load, on_enable, on_disable, on_unload) und 2 Tool-Interzeptoren (before_tool_execute, after_tool_execute) mit vorinstallierten Starter-Plugins (System Metrics, Security Audit Hook, Cost Guard).",
            "Nutzen:": " Ermöglicht isolierte Runtime-Erweiterungen und globale Tool-Interzeption ohne Eingriff in den Kernel-Code."
        },
        "Research Lab (Deep Search": {
            "Mechanik:": " Beinhaltet die Autonome Tiefenrecherche & Reflexionsschleife v2 (Re-Search Loop): Zerlegung komplexer Recherchen in 3–5 Teilfragen, autonome Lückenanalyse, bis zu 3 iterative Nachfolge-Suchläufe, Multi-Provider Fallback (SearXNG / Jina Reader) und SSRF-Schutz.",
            "Nutzen:": " Schließt Wissenslücken selbstständig durch rekursive Folgerecherchen bei widersprüchlichen oder unvollständigen Quellen."
        },
        "System Control Center (7 Reiter": {
            "Mechanik:": " Integriert das 1-Klick Updatesystem & Continuous Deployment: Automatischer GitHub-Sync mit Pre-Update Snapshots aller SQLite-Datenbanken (WAL) in data/snapshots/ vor jedem Git-Pull, 1-Klick Rollback und minimalen Git-Stat-Prüfungen gegen Mount-Timeouts.",
            "Nutzen:": " Ermöglicht gefahrlose Software-Updates mit automatischem Datenbank-Rollback im Fehlerfall."
        },
        "Dual-Agent Konsens-Gate": {
            "Mechanik:": " Im Kanban-Board als automatisiertes 4-Augen Qualitäts-Gate verdrahtet (Katharina Völk / Robert Review mit 1–100% Score und Status-Lock bei Revisionsbedarf).",
        },
        "Apollo Voice Engine": {
            "Mechanik:": " Vollständige Telegram-Voice-Integration (POST /api/telegram/voice-relay und POST /api/voice/synthesize) für mobile Audio-Memos via edge-tts (de-DE-ConradNeural).",
        },
        "Atomares Pre-Write-Snapshotting": {
            "Mechanik:": " Zusätzlich als Pre-Update Snapshots aller SQLite-Datenbanken vor GitHub-Pulls und Container-Updates in data/snapshots/ integriert.",
        }
    }

    for doc_path in [vorlage_path, glossar_path]:
        if not doc_path.exists():
            print(f"[SKIP] Datei nicht gefunden: {doc_path}")
            continue

        print(f"\n[Verarbeite] {doc_path} ...")
        doc = docx.Document(str(doc_path))
        modified_count = 0

        # Update matching tables
        for t_idx, table in enumerate(doc.tables):
            if not table.rows:
                continue
            cell = table.rows[0].cells[0]
            title = cell.paragraphs[0].text if cell.paragraphs else ""

            for key, additions in updates.items():
                if key in title:
                    update_table_cell(cell, additions)
                    print(f"  -> Aktualisiert: Table {t_idx} ({key})")
                    modified_count += 1
                    break

        # Also update subtitle / header if present
        for p in doc.paragraphs:
            if "KOMPLETT-GLOSSAR" in p.text and "118" in p.text:
                p.text = p.text.replace("118 MODULE", "118 MODULE + v0.3.5 UPGRADES")
                print(f"  -> Angepasst: {p.text}")
            elif "Vollständige Referenz aller 118 System-Features" in p.text:
                p.text = p.text.replace("118 System-Features", "System-Features inkl. v0.3.5 Erweiterungen (Qualitäts-Gate, Code-Sandbox, Voice-Pipeline, Pluginsystem, Tiefenrecherche)")
                print(f"  -> Angepasst: {p.text}")

        doc.save(str(doc_path))
        print(f"[OK] {doc_path.name} gespeichert mit {modified_count} aktualisierten Glossar-Tabellen.")

if __name__ == "__main__":
    run()
