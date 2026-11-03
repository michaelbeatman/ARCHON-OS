---
name: agent-browser-navigator
description: Autonome und interaktive Browser- und Desktop-Steuerung für Agenten über Headless Xfce und Chrome DevTools Protocol mit dreistufiger Governance (Generell, Sensibel/HITL, Verboten).
---

# Agent Browser Navigator (Interaktive Desktop-Steuerung)

Dieses Skill verleiht ausgewählten Spezialisten (Robert, Alexander Richter / default, Research Analysten, HR/Recruiting-Agenten) die Fähigkeit, über den virtuellen Bot-Screen im Agentenkader Webseiten zu bedienen, Portale zu durchsuchen und Arbeitsschritte auszuführen.

## Berechtigte Rollen
- `orchestrator` (Robert)
- `default` (Alexander Richter / Executive Decision Architect)
- `micha` (System-Administrator)
- `recruiter_talent_scout` (Karriere & Bewerbungs-Agent)
- `research_deep_analyst` (Deep Research Spezialist)

## Dreistufige Autonomie-Governance (Branchenstandard)

### 1. Generelle Aktionen (Vollautonom)
Diese Operationen darf der Agent nach Freigabe des Benutzers selbstständig und ohne Rückfrage ausführen:
- Webseiten aufrufen, Navigieren, Links anklicken, Scrollen.
- Daten, Profile, Angebote und Dokumente extrahieren und strukturieren.
- Suchfelder und Filter bedienen.
- **Bewerbungen einreichen / Formulare absenden:** Ausfüllen von Formularen, Hochladen von Lebensläufen und Absenden von Bewerbungen, sofern die Daten im Profil hinterlegt sind.

### 2. Sensible Aktionen (Human-in-the-Loop Pflicht)
Sobald eine Aktion finanzielle, rechtliche oder irreversible Konsequenzen hat, **stoppt der Agent automatisch** und fordert über das HITL-System eine Freigabe:
- **Bestellungen & Einkäufe:** Warenkorb auschecken, Kaufverträge abschließen.
- **Zahlungen & Überweisungen:** Eingabe von Kreditkartendaten, PayPal-Autorisierung, SEPA-Lastschriften.
- **Konto- & Profillöschungen:** Löschen von Benutzerkonten oder dauerhaften Datenbanken.
- **Vertragsunterzeichnungen:** Verbindliche Unterschriften oder Kündigungen.

### 3. Verbotene Aktionen (Strict Ban)
- Zugriff auf oder Exfiltration von internen API-Schlüsseln, Passwörtern oder Tresordaten.
- Umgehung von Sicherheitsprotokollen oder Manipulieren lokaler Container.

## Interaktions-Workflow
1. **Manueller Login:** Der Benutzer ruft die Zielseite (z. B. StepStone, LinkedIn, Intranet) über die Adressleiste auf und führt Login sowie 2FA eigenhändig aus.
2. **Autorisierung:** Der Benutzer legt den Schalter `[ 🤖 Agent autorisieren ]` um.
3. **Instruktion:** Über das integrierte Chatfeld erhält der Agent seinen präzisen Arbeitsauftrag.
4. **Ausführung:** Der Agent übernimmt die Session, erfasst Zwischenergebnisse und berichtet im Chat.
