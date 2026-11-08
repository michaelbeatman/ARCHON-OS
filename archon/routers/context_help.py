"""
Archon OS Router fuer Kontext-Hilfe und UI-Assistenz.
Extrahiert aus main.py zur Modularisierung und Entschlackung des Monolithen.
"""

from typing import Any, Dict
from fastapi import APIRouter, Body, HTTPException

router = APIRouter(tags=["context-help"])

HELP_CONTEXT_DATA = {
    "operations": {
        "title": "Operations",
        "subtitle": "Echtzeit-Leitstand und Flotten-Überwachung",
        "purpose": "Hier steuerst du den operativen Betrieb aller 56 Spezial-Agenten. Du siehst aktuelle System-KPIs, laufende Hintergrundprozesse, aktive Container und den Ticker.",
        "top_actions": [
            "Klicke auf eine KPI-Karte (Flottenlast, TPM, Latenz), um Detailanalysen zu öffnen.",
            "Nutze 'Neuer autonomer Task', um einer Rolle einen Arbeitsauftrag mit Prompt-Studio zu erteilen.",
            "Prüfe im 'Live Task-Stream' den aktuellen Fortschritt und Logs autonomer Aufgaben."
        ],
        "starter_prompt": "Erkläre mir, wie ich im Operations-Dashboard einen neuen Task an den passenden Agenten delegiere und den Fortschritt überwache."
    },
    "inbox": {
        "title": "Eingang & Triage (Intake)",
        "subtitle": "Operative Triage: HITL-Freigaben, E-Mails & Telegram",
        "purpose": "Zentrale Schleuse für alle eingehenden Signale. Hier genehmigst du Aktionen (Human-in-the-Loop), sichtest E-Mails und verarbeitest Nachrichten.",
        "top_actions": [
            "Filtere nach HITL-Freigaben, um blockierte Schreib-Aktionen der Agenten zu bestätigen.",
            "Synchronisiere das E-Mail-Postfach oder binde neue E-Mails direkt an Kontakte an.",
            "Übergib Nachrichten per Klick an einen spezialisierten Agenten zur automatischen Beantwortung."
        ],
        "starter_prompt": "Wie funktioniert der HITL-Freigabeprozess im Posteingang und wie kann ich eine E-Mail direkt von einem Agenten beantworten lassen?"
    },
    "org": {
        "title": "Organigramm & Teams",
        "subtitle": "Interaktiver 2D-Organisationsbaum aller 56 Agenten",
        "purpose": "Visualisiert die hierarchischen Beziehungen, Berichtswege und Rollen aller Agenten im Unternehmen. Ermöglicht das Umhängen von Vorgesetzten und Neukonfigurieren.",
        "top_actions": [
            "Klicke auf einen Agentenknoten, um das Eigenschaftsfenster zu öffnen und Name, Vorgesetzten oder Modell anzupassen.",
            "Nutze das Mausrad zum Zoomen und die linke Maustaste zum Verschieben der Arbeitsfläche.",
            "Beobachte die Status-Badges (Online / Busy / Idle) für jeden Agenten in Echtzeit."
        ],
        "starter_prompt": "Wie ändere ich den Vorgesetzten eines Agenten im Organigramm und wie wird das Modell für eine Rolle hinterlegt?"
    },
    "kader": {
        "title": "Agenten-Kader",
        "subtitle": "Vollständiges Verzeichnis aller 56 Rollen & Profile",
        "purpose": "Katalog aller aktivierten Agenten-Profile mit Aufgabenprofil, System-Prompts, Zuständigkeiten und Werkzeugberechtigungen.",
        "top_actions": [
            "Suche oder filtere nach Fachabteilungen (Geschäftsführung, IT, Marketing, Recht, Finanzen).",
            "Klicke auf eine Karte, um System-Prompts und operative Anweisungen zu bearbeiten.",
            "Weise dem Agenten direkt eine autonome Aufgabe zu."
        ],
        "starter_prompt": "Welcher Agent im Kader ist für rechtliche Prüfungen zuständig und welche Werkzeuge stehen ihm zur Verfügung?"
    },
    "crm": {
        "title": "CRM & Kundenbeziehungen",
        "subtitle": "Vollintegriertes Kunden- und Kontaktmanagement",
        "purpose": "Verwaltung von Leads, Kontakten, Kundenhistorien, Sprachnotizen und automatischer Dokumenten-Verknüpfung.",
        "top_actions": [
            "Erstelle neue Kontakte oder importiere bestehende Datenbestände.",
            "Nutze die Diktatfunktion im Kontakt-Drawer für schnelle Sprachmemos.",
            "Verknüpfe E-Mail-Verläufe und Rechnungen direkt mit Kundenkonten."
        ],
        "starter_prompt": "Wie lege ich einen neuen Kontakt an und verknüpfe ein Angebot damit?"
    },
    "erp": {
        "title": "ERP & Finanzen",
        "subtitle": "Angebote, Rechnungen, Mahnwesen & GoBD-Archivierung",
        "purpose": "Lückenlose kaufmännische Abwicklung: Generierung von Angeboten, Ausgangsrechnungen, Mahnläufen und GoBD-konformen Revisionsprotokollen.",
        "top_actions": [
            "Erzeuge aus einem genehmigten Angebot mit einem Klick eine Rechnung.",
            "Überprüfe fällige Forderungen in der Dunning Engine.",
            "Exportiere revisionssichere Buchungsdaten für Steuerberater oder DATEV."
        ],
        "starter_prompt": "Wie erstelle ich eine Ausgangsrechnung und starte einen Mahnlauf?"
    },
    "boardroom": {
        "title": "AI Boardroom",
        "subtitle": "Multidisziplinäre Strategiedebatten des C-Level-Kaders",
        "purpose": "Strukturiertes Debattier- und Entscheidungs-Framework. Spezialisierte C-Suite-Agenten wägen komplexe Fragestellungen aus Finanz-, Rechts-, Tech- und Markt-Sicht gegeneinander ab.",
        "top_actions": [
            "Formuliere eine strategische Frage oder Entscheidungsvorlage.",
            "Wähle das passende Framework (z. B. Pre-Mortem, Devil's Advocate, Delphi).",
            "Lass das Protokoll mit Dissens und Beschluss direkt im Obsidian-Vault archivieren."
        ],
        "starter_prompt": "Wie starte ich eine Boardroom-Debatte für eine strategische Investitionsentscheidung?"
    },
    "skills": {
        "title": "Skill- & Werkzeugmarkt",
        "subtitle": "Autonom erweiterbare Funktionsmodule nach Antigravity-Standard",
        "purpose": "Zentrales Verzeichnis aller installierten und synthetisierten Fähigkeiten. Agenten können zur Laufzeit neue Skills erlernen, testen und aktivieren.",
        "top_actions": [
            "Durchsuche vorhandene Skills nach Kategorien oder Schlüsselwörtern.",
            "Prüfe Quellcode und Sicherheitsfreigaben einzelner Fähigkeiten.",
            "Aktiviere neue Skills per Knopfdruck für bestimmte Agenten."
        ],
        "starter_prompt": "Wie installiere ich einen neuen Skill und weise ihn einem Agenten zu?"
    },
    "watchdog": {
        "title": "Internet-Watchdog · Radar",
        "subtitle": "Kontinuierliches Markt-, Wettbewerbs- & Bedrohungs-Monitoring",
        "purpose": "Autonomes Radar, das Web-Quellen, Nachrichten, Marktbegleiter und Sicherheits-Feeds scannt und relevante Signale direkt in den Posteingang triagiert.",
        "top_actions": [
            "Trage Suchbegriffe, URLs oder RSS-Feeds für das Dauermonitoring ein.",
            "Definiere Alarm-Schwellenwerte für automatische Benachrichtigungen.",
            "Lass Zusammenfassungen neuer Marktbewegungen durch den Research-Agenten erstellen."
        ],
        "starter_prompt": "Wie richte ich einen neuen Radar-Watcher für Wettbewerber-Aktivitäten ein?"
    },
    "design_system": {
        "title": "Design System Lab",
        "subtitle": "UI-Tokens, Komponenten & interaktive Schnittstellen-Vorschau",
        "purpose": "Entwicklungsumgebung für UI-Tokens, Farbpaletten, Typografie und standardisierte Tailwind-Komponenten des Archon-Design-Systems.",
        "top_actions": [
            "Prüfe Farbkontraste und Dark-Mode-Verhalten aller Kern-Komponenten.",
            "Kopiere vorgefertigte HTML- und Tailwind-Codeblöcke für neue Ansichten.",
            "Teste Buttons, Modals, Tabellen und Badges interaktiv im Sandkasten."
        ],
        "starter_prompt": "Wie übernehme ich eine Komponente aus dem Design System Lab in eine neue Ansicht?"
    },
    "css_studio": {
        "title": "Archon CSS Live Studio",
        "subtitle": "Echtzeit-Stilinspektor, Visual-Editor & Style-Override-Manager",
        "purpose": "Erlaubt das direkte Anpassen, Vermessen und persistente Speichern von CSS-Regeln und Layout-Größen auf der Live-Oberfläche.",
        "top_actions": [
            "Klicke auf den Inspektieren-Modus, um ein UI-Element direkt auf dem Bildschirm anzuwählen.",
            "Passe Abstände, Farben und Schriftarten im visuellen Inspector an.",
            "Speichere Regeln temporär oder übernehme sie dauerhaft in das Theme."
        ],
        "starter_prompt": "Wie nutze ich den CSS Studio Inspector, um Abstände eines Elements live anzupassen?"
    },
    "log_stream": {
        "title": "Live Log-Stream",
        "subtitle": "Echtzeit-Telemetrie & System-Audit-Trail",
        "purpose": "Zentraler Stream aller Kernel-Ereignisse, Agenten-Ausführungen, Tool-Calls und Fehlermeldungen in Echtzeit mit Filter- und Suchfunktion.",
        "top_actions": [
            "Filtere nach Loglevel (DEBUG, INFO, WARNING, ERROR).",
            "Suche nach spezifischen Task-IDs oder Agenten-Namen.",
            "Pausiere den Stream für eine detaillierte Ursachenanalyse."
        ],
        "starter_prompt": "Wie filtere ich im Log-Stream nach Fehlern eines bestimmten Agenten?"
    }
}


@router.get("/api/help/context/{view_id}")
def api_get_help_context(view_id: str):
    normalized = (view_id or "").strip().lower().replace("-", "_")
    ctx = HELP_CONTEXT_DATA.get(view_id) or HELP_CONTEXT_DATA.get(normalized)
    if not ctx:
        ctx = {
            "title": f"Ansicht: {view_id}",
            "subtitle": "Bereich im Archon Agentic OS",
            "purpose": "Dieser Bereich dient der operativen Steuerung und Interaktion mit dem Agenten-Ökosystem.",
            "top_actions": [
                "Nutze die Aktionen und Buttons im Kopfbereich der Ansicht.",
                "Stelle unten eine konkrete Frage an den System-Assistenten."
            ],
            "starter_prompt": f"Was kann ich im Bereich '{view_id}' tun und wie ist dieser aufgebaut?"
        }
    return ctx


@router.post("/api/help/ask")
async def api_ask_help_assistant(payload: dict = Body(...)):
    view_id = payload.get("view_id", "operations")
    question = payload.get("question", "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="Keine Frage übermittelt.")

    ctx = HELP_CONTEXT_DATA.get(view_id, {})
    view_title = ctx.get("title", view_id)
    view_purpose = ctx.get("purpose", "")

    system_prompt = (
        f"Du bist der hochkompetente, freundliche und präzise Archon OS System-Assistent.\n"
        f"Der Nutzer befindet sich gerade in der Ansicht '{view_title}'.\n"
        f"Zweck dieser Ansicht: {view_purpose}\n"
        f"Beantworte die Frage des Nutzers direkt, konkret und hilfreich auf Deutsch. "
        f"Verzichte auf Floskeln, Begrüßungen und Füllwörter. Gib praxisnahe Schritt-für-Schritt-Anleitungen."
    )

    # Provider-Schluessel ermitteln
    import api_provider
    from backend.agent_router import router_instance
    all_keys = api_provider.collect_keys()
    reply_text = ""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": question}
    ]

    if all_keys.get("OPENROUTER_API_KEY"):
        try:
            reply_text = await router_instance.chat_completion(messages, "openrouter", "google/gemini-2.5-flash", all_keys, max_tokens=500)
        except Exception:
            pass

    if not reply_text and (all_keys.get("GEMINI_API_KEY") or all_keys.get("GOOGLE_API_KEY")):
        try:
            reply_text = await router_instance.chat_completion(messages, "google", "gemini-1.5-flash", all_keys, max_tokens=500)
        except Exception:
            pass

    # 3. Fallback: Heuristische Antwort aus dem Spickzettel
    if not reply_text:
        actions_txt = "\n- ".join(ctx.get("top_actions", []))
        reply_text = (
            f"**{view_title}**\n\n"
            f"{view_purpose}\n\n"
            f"**Wichtigste Aktionen in diesem Bereich:**\n- {actions_txt}\n\n"
            f"*(Hinweis: Für vertiefte KI-Antworten bitte OpenRouter oder Gemini API-Key in den Einstellungen hinterlegen.)*"
        )

    return {
        "status": "success",
        "view_id": view_id,
        "question": question,
        "answer": reply_text
    }
