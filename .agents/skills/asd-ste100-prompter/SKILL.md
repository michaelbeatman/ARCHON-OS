---
name: asd-ste100-prompter
description: Formuliert und transformiert Prompts und Agenten-Instruktionen nach dem Luftfahrt-Standard ASD-STE100 (Simplified Technical English) für maximale Präzision und Fehlertoleranz bei Tool-Calls.
version: 1.0.0
author: Archon OS Intelligence
category: Prompt-Engineering & System-Direktiven
tags: ["asd-ste100", "simplified-english", "prompt-engineering", "deterministic", "aerospace-standard"]
---

# ✈️ ASD-STE100 Simplified Technical Prompting

Dieses Skill wendet die Prinzipien der Spezifikation **ASD-STE100** (Vereinfachtes technisches Englisch aus der Luft- und Raumfahrt) auf System-Prompts, Tool-Parameter und Agenten-Instruktionen an. Das Ziel ist vollständige Eindeutigkeit, um Fehlinterpretationen und Formatbrüche bei LLM-Ausführungen zu verhindern.

---

## 1. Die 5 Kernregeln von ASD-STE100 für LLMs

### Regel 1: Ein Wort = Genau eine Bedeutung
* Verwende keine Synonyme für dieselbe Entität oder Aktion.
* Wenn eine Aktion `start` heißt, verwende niemals abwechselnd `launch`, `initiate`, `trigger` oder `commence`.
* Halte das kontrollierte Vokabular strikt ein.

### Regel 2: Satzlängen-Limit (Maximal 20 Wörter)
* Jeder Satz darf maximal 20 Wörter umfassen (bei Aufzählungen maximal 25).
* Zerlege Schachtelsätze konsequent in Einzelschritte.
* *Falsch:* „Bevor der Server gestartet wird, muss geprüft werden, ob der Port frei ist, da es sonst zu Fehlern kommt.“
* *Richtig:* „Prüfe den Port. Wenn der Port belegt ist, stoppe den Prozess. Wenn der Port frei ist, starte den Server.“

### Regel 3: Nur aktive Verben & Imperativ für Anweisungen
* Verwende für Handlungsanweisungen die direkte Befehlsform.
* Vermeide Passivformen („wird analysiert“, „sollte berechnet werden“).
* Verwende: `Lies`, `Extrahiere`, `Berechne`, `Schreibe`, `Sende`.

### Regel 4: Keine unklaren Pronomen („It“, „This“, „These“)
* Ein Pronomen darf niemals ohne direkt vorangestelltes, eindeutiges Bezugswort stehen.
* Wiederhole das Substantiv, wenn der geringste Zweifel an der Referenz besteht.
* *Falsch:* „Lösche die Datei und überschreibe sie mit der neuen Version. Sie wird danach validiert.“
* *Richtig:* „Lösche Datei A. Erstelle Datei B. Validiere Datei B.“

### Regel 5: Exklusive Konditionen (Wenn / Dann)
* Formuliere Bedingungen immer nach dem Schema:
  1. `WENN <Bedingung>`
  2. `DANN <Aktion>`
  3. `SONST <Aktion>`
* Vermeide verschachtelte oder implizite Bedingungen.

---

## 2. Prompt-Transformations-Pipeline

Wenn dieser Skill aktiv ist oder aufgerufen wird, um einen Prompt zu verfeinern:
1. **Mehrdeutigkeiten identifizieren:** Streiche vage Adjektive („schnell“, „möglichst gut“, „effizient“).
2. **Kriterien quantifizieren:** Ersetze Adjektive durch Metriken („Antwortzeit unter 500 ms“, „Länge maximal 3 Absätze“).
3. **Sequenzialisierung:** Nummeriere Arbeitsschritte chronologisch von 1 bis n.
4. **Output-Format festzurren:** Definiere das Schema (z. B. striktes JSON oder STE100-Text) ohne Prosa-Rahmen.
