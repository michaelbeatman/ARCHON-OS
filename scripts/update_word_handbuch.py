# -*- coding: utf-8 -*-
"""
scripts/update_word_handbuch.py
===============================
Aktualisiert die offiziellen Word-Dokumente (.docx) von Archon OS:
- docs/system/ARCHON_OS_SYSTEM_HANDBUCH_2026_Vorlage.docx
- docs/system/ARCHON_OS_SYSTEM_HANDBUCH_2026.docx

Fuegt ein:
1. Kapitel 0. Installationshinweise (1-Click-Installer setup.bat, Docker, start.bat, stop.bat)
2. Kapitel 3.3 Bot Screen (PbD, Ghost-Cursor, Bézier, a11y Pruning, Notfall-Stopp)
3. Renummerierung Kapitel 3.4 Faehigkeiten mit den 4 Autonomie-Engines (Voyager, MCTS, Prefetcher, JIT)
4. Umbenennung von 'AI Mastermind' zu 'AI-Boardroom'
5. Stand & Versionsnummer: 3. November 2026 | v0.3.8 Enterprise
"""

import os
import sys
import docx
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

DOCS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VORLAGE_PATH = os.path.join(DOCS_DIR, "docs", "system", "ARCHON_OS_SYSTEM_HANDBUCH_2026_Vorlage.docx")
MAIN_PATH = os.path.join(DOCS_DIR, "docs", "system", "ARCHON_OS_SYSTEM_HANDBUCH_2026.docx")


def update_single_docx(filepath: str):
    if not os.path.exists(filepath):
        print(f"Datei nicht gefunden: {filepath}")
        return False

    print(f"\n--- Aktualisiere Word-Dokument: {os.path.basename(filepath)} ---")
    doc = docx.Document(filepath)
    print(f"Ursprüngliche Absätze: {len(doc.paragraphs)}")

    # 1. Update Metadaten / Stand
    for i in range(min(15, len(doc.paragraphs))):
        p = doc.paragraphs[i]
        if "Stand:" in p.text or "Release:" in p.text:
            p.text = "Stand: 3. November 2026  |  Release: v0.3.8 Enterprise (4-Säulen-ERP)  |  57 Autonome Spezialisten-Rollen  |  19 Fachmodule"
            print(f"✓ Metadaten-Zeile aktualisiert: {p.text}")
            break

    # 2. Finde Kapitel 1 (Operations) und füge Kapitel 0 davor ein
    chap1_idx = -1
    for i, p in enumerate(doc.paragraphs):
        if p.text.strip().startswith("1. Operations"):
            chap1_idx = i
            break

    if chap1_idx != -1:
        target_p = doc.paragraphs[chap1_idx]
        print(f"✓ Kapitel 1 an Position {chap1_idx} gefunden. Füge Kapitel 0. Installationshinweise davor ein...")

        target_p.insert_paragraph_before("0. Installationshinweise")
        target_p.insert_paragraph_before("Archon OS lässt sich auf jedem modernen Rechner (Windows 10/11, macOS, Linux) mit minimalem Einrichtungsaufwand in Betrieb nehmen:")
        
        target_p.insert_paragraph_before("0.1 Systemvoraussetzungen")
        target_p.insert_paragraph_before("• Docker Desktop: Unter Windows mit aktiviertem WSL2-Backend (Linux-Subsystem). Falls noch nicht vorhanden: docker.com/products/docker-desktop/ herunterladen.")
        target_p.insert_paragraph_before("• Hardware-Empfehlung: Mindestens 8 GB freier Arbeitsspeicher (RAM) und 15 GB freier Festplattenspeicher für Docker-Images, lokale Modelle und SQLite-Datenbanken.")
        
        target_p.insert_paragraph_before("0.2 Installation per 1-Click-Installer (setup.bat / setup.ps1)")
        target_p.insert_paragraph_before("• Unter Windows: Doppelklick auf die Datei setup.bat im Hauptverzeichnis (oder Rechtsklick auf setup.ps1 -> 'Mit PowerShell ausführen').")
        target_p.insert_paragraph_before("• Automatischer Ablauf des Installers:")
        target_p.insert_paragraph_before("  1. Docker-Prüfung: Erkennt automatisch, ob Docker Desktop installiert ist und läuft. Fehlt Docker, bietet das Skript an, die offizielle Download-Seite im Browser zu öffnen.")
        target_p.insert_paragraph_before("  2. Initialisierung: Erstellt notwendige Ordner (data/, logs/, .hermes/) und kopiert bei Bedarf die Standard-.env-Konfigurationsdatei.")
        target_p.insert_paragraph_before("  3. Cluster-Start: Führt 'docker compose up -d' aus und startet die drei Kern-Dienste (ARCHON-OS auf Port 8501, Hermes Core auf Port 8644, n8n Automation auf Port 5678).")
        target_p.insert_paragraph_before("  4. Healthcheck & Browser-Öffnung: Prüft die Betriebsbereitschaft des Web-Dashboards und öffnet es automatisch im Standardbrowser unter http://localhost:8501.")
        
        target_p.insert_paragraph_before("0.3 Täglicher Betrieb")
        target_p.insert_paragraph_before("• Starten: Ein einfacher Doppelklick auf start.bat fährt alle Container hoch und öffnet das Dashboard.")
        target_p.insert_paragraph_before("• Beenden: Ein Doppelklick auf stop.bat fährt alle Container geordnet herunter und sichert den Datenbankzustand.")
        
        target_p.insert_paragraph_before("0.4 Installation unter Linux & macOS")
        target_p.insert_paragraph_before("git clone https://github.com/michaelbeatman/Agentic-Archon-Os.git && cd Agentic-Archon-Os && cp .env.example .env && docker compose up -d && open http://localhost:8501")
        target_p.insert_paragraph_before("")
        print("✓ Kapitel 0. Installationshinweise erfolgreich eingefügt.")

    # 3. Finde Kapitel 3 (Agenten-Kader) und füge Kapitel 3.3 Bot Screen ein, renummeriere Rest
    chap33_idx = -1
    for i, p in enumerate(doc.paragraphs):
        if p.text.strip().startswith("3.3 Fähigkeiten") or p.text.strip() == "3.3 Fähigkeiten":
            chap33_idx = i
            break

    if chap33_idx != -1:
        target_p = doc.paragraphs[chap33_idx]
        print(f"✓ Kapitel 3.3 (alt) an Position {chap33_idx} gefunden. Füge neuen Bot Screen ein...")

        target_p.insert_paragraph_before("3.3 Bot Screen (Desktop & Web-Navigator)")
        target_p.insert_paragraph_before("Der Bot Screen ist als dedizierter Subtab zwischen Chat und Fähigkeiten im Agentenkader integriert. Er ermöglicht die visuelle Überwachung und interaktive Steuerung von Browser- und Desktop-Sitzungen:")
        target_p.insert_paragraph_before("• Adressleiste mit Avatar-Abstand: Manuelle Eingabe oder Übergabe einer Ziel-URL. Die Leiste startet ergonomisch versetzt rechts des 110-Pixel-Avatars, sodass Bedienelemente und Textfelder kollisionsfrei bedienbar bleiben. Ermöglicht dem Operator, sich auf Portalen, Jobbörsen oder Webdiensten persönlich einzuloggen und eventuelle 2FA-Challenges (SMS, Authenticator-App, Cloudflare Turnstile) gefahrlos manuell zu überwinden.")
        target_p.insert_paragraph_before("• Vollbildmodus & Freischwebendes Overlay ([ ⛶ Vollbild ] / Esc): Schaltet den Bot Screen per Knopfdruck in eine immersive Vollbildansicht (100 % Display-Nutzung). Die Adressleiste dockt oben an den Rand an. Das Anweisungs- und Kontrollmodul schwebt als halbtransparente Frosted-Glass-Leiste frei über dem unteren Bildschirmrand.")
        target_p.insert_paragraph_before("• Prominenter Live-Agenten-Mauszeiger & Biomechanischer Ghost-Cursor:")
        target_p.insert_paragraph_before("  - Hochsichtbare, lilafarbene Leucht-Pfeilspitze mit dynamischem Agenten-Namensbadge (🤖 Default) und animierten Radar-Wellen (Click-Ripples).")
        target_p.insert_paragraph_before("  - Bézier-Trajektorien & Fitts's Law: Der Cursor gleitet auf kubischen Bézier-Kurven mit realistischer Beschleunigung und sanfter Abbremsung vor dem Zielfeld.")
        target_p.insert_paragraph_before("  - Gauss-verteilter Bounding-Box Jitter: Klicks treffen nicht starr den geometrischen Mittelpunkt eines Buttons, sondern variieren normalverteilt innerhalb der Schaltfläche, um Anti-Bot-WAFs und Cloudflare Turnstile zu überlisten.")
        target_p.insert_paragraph_before("  - Menschliche Tastatur-Kadenzen: Text-Eingaben erfolgen mit natürlich variierenden Intervallen (50–180 ms) inklusive kognitiver Denkpausen bei Satzzeichen.")
        target_p.insert_paragraph_before("• Programming by Demonstration (PbD) – Vormachen & Aufnehmen ([ 🔴 Vormachen & Aufnehmen ]):")
        target_p.insert_paragraph_before("  - Ermöglicht es dem Bediener, komplexe Web-Workflows (z. B. Bewerber filtern, Belege herunterladen, Datensätze abgleichen) einmalig im Viewport vorzumachen, statt sie in Code zu beschreiben.")
        target_p.insert_paragraph_before("  - Zeichnet Klicks, Scroll-Bewegungen, Formulareingaben und URLs schrittweise auf.")
        target_p.insert_paragraph_before("  - Sprach- & Absichts-Kommentare: Über die integrierte Leiste können Einzelschritte mit gesprochenen oder getippten Erklärungen versehen werden ('Hier filtere ich nach Python-Senioren').")
        target_p.insert_paragraph_before("  - Autonome Skill-Synthese ([ ⏹️ Aufnahme stoppen & Skill erzeugen ]): Generiert auf Knopfdruck ein wiederverwendbares Skill-Manifest (.agents/skills/<name>/SKILL.md) und ein lauffähiges Python-Automationsskript (scripts/dynamic_tools/<name>.py).")
        target_p.insert_paragraph_before("• Observation Pruning & Accessibility-Tree ([ 🌲 a11y Pruning: -85% ]): Schalter in der oberen Leiste reduziert den rohen HTML-DOM um 85–92 %. Entfernt SVGs, Stylesheets, Tracking-Skripte und tiefe Div-Verschachtelungen und übergibt dem LLM einen kompakten, semantischen Interaktionsbaum ([@ID] [button] 'Absenden').")
        target_p.insert_paragraph_before("• Dual-Control Steuerleiste & Notfall-Abbruch:")
        target_p.insert_paragraph_before("  - Autorisierungs-Schalter ([ 👤 Dein Zugriff ] / [ 🤖 Agent autorisiert ]): Nur der Operator oder privilegierte Systemrollen (Robert, default, Micha) können den Agenten aktivieren.")
        target_p.insert_paragraph_before("  - Notfall-Abbruch-Button ([ 🛑 Notfall-Stopp ]): Roter Sofort-Stopp-Knopf. Entzieht dem Agenten augenblicklich alle Zugriffsrechte (POST /api/operations/bot-screen/abort), friert die Sitzung ein und übergibt die volle Kontrolle an den Bediener zurück.")
        target_p.insert_paragraph_before("  - Direktiven-Promptfeld: Eingabefeld mit Sende-Button für Arbeitsaufträge nach erfolgreichem Login.")
        target_p.insert_paragraph_before("• Autonomie-Governance (3-Klassen-Modell): Generelle Aktionen (vollautonom), Sensible Aktionen (HITL-Pflicht für Kaufen/Bezahlen/Löschen), Verbotene Aktionen (Zero Tolerance).")
        target_p.insert_paragraph_before("")

        # Renummeriere 3.3 Fähigkeiten -> 3.4 Fähigkeiten
        target_p.text = "3.4 Fähigkeiten & Autonomie-Engines"
        print("✓ Kapitel 3.3 Bot Screen eingefügt und 3.4 Fähigkeiten renummeriert.")

    # 4. Renummeriere 3.4 -> 3.5, 3.5 -> 3.6, etc.
    renumber_map = {
        "3.4 Operation": "3.5 Operation",
        "3.5 Soul": "3.6 Soul",
        "3.6 Personalakte": "3.7 Personalakte",
        "3.7 Marktplatz": "3.8 Marktplatz"
    }
    for p in doc.paragraphs:
        txt = p.text.strip()
        for old_num, new_num in renumber_map.items():
            if txt.startswith(old_num):
                p.text = txt.replace(old_num, new_num, 1)
                break

    # 5. Aktualisiere 'AI Mastermind' zu 'AI-Boardroom'
    replaced_mastermind = 0
    for p in doc.paragraphs:
        if "AI Mastermind" in p.text:
            p.text = p.text.replace("AI Mastermind", "AI-Boardroom")
            replaced_mastermind += 1
    print(f"✓ 'AI Mastermind' in {replaced_mastermind} Absätzen zu 'AI-Boardroom' aktualisiert.")

    # 6. Speichern
    doc.save(filepath)
    print(f"✓ Datei erfolgreich gespeichert: {filepath} (Neue Absatzzahl: {len(doc.paragraphs)})")
    return True


def main():
    update_single_docx(VORLAGE_PATH)
    update_single_docx(MAIN_PATH)
    print("\n🎉 BEIDE WORD-DOKUMENTE ERFOLGREICH AKTUALISIERT!")


if __name__ == "__main__":
    main()
