---
name: skill-batna-verhandlungsanalyse
description: Systematische Verhandlungsanalyse nach dem Harvard-Konzept mit BATNA/WATNA-Bestimmung, ZOPA-Korridor und Walk-Away-Schwellen.
version: 1.0.0
author: ARCHON OS Intelligence
category: 1. Strategie, Führung & Lebensplanung
tags: [verhandlung, batna, zopa, harvard-konzept, strategie, b2b]
---

# 🤝 BATNA & ZOPA Verhandlungsanalyse (Harvard-Konzept)

Dieser Skill befähigt den Agenten, vor und während Verhandlungen eine mathematisch und strategisch fundierte Verhandlungsanalyse durchzuführen.

## 1. Kern-Definitionen
- **BATNA (Best Alternative to a Negotiated Agreement):** Die beste Option bei Nicht-Einigung. Gibt Verhandlungsmacht und bestimmt den Schmerzpunkt.
- **WATNA (Worst Alternative to a Negotiated Agreement):** Das worst-case Szenario bei Scheitern.
- **ZOPA (Zone of Possible Agreement):** Der Überlappungsbereich zwischen dem Reservationspreis des Käufers (Maximalpreis) und dem Reservationspreis des Verkäufers (Minimalpreis).
- **Reservationspreis (Walk-Away-Point):** Die absolute Grenze, ab der kein Abschluss mehr getätigt wird.

## 2. 5-Schritte-Analysematrix

### Schritt 1: Stakeholder- & Machtanalyse
- Identifiziere alle Verhandlungsparteien (Entscheider, Beeinflusser, Veto-Geber).
- Bestimme Informationsasymmetrien und Zeitdruck (Wer muss schneller abschließen?).

### Schritt 2: Eigene BATNA quantifizieren & stärken
1. Liste alle verfügbaren Alternativen ohne den Verhandlungspartner auf.
2. Bewerte jede Alternative nach:
   - Finanziellem Erwartungswert (€ / Margin)
   - Risikofaktor (0.0 - 1.0)
   - Realisierungszeitraum (Wochen/Monate)
3. Wähle die stärkste Alternative als offizielle BATNA.
4. Führe Maßnahmen durch, um die eigene BATNA vor der Hauptverhandlung aufzuwerten.

### Schritt 3: Fremd-BATNA antizipieren
- Welche realistischen Optionen hat die Gegenseite, wenn der Deal platzt?
- Wie hoch sind die Wechselkosten (Switching Costs) für die Gegenseite?
- Wie dringend benötigt die Gegenseite die Lösung?

### Schritt 4: ZOPA-Berechnung & Korridor-Bestimmung
$$\text{ZOPA} = [\text{Reservationspreis}_{\text{Verkäufer}}, \text{Reservationspreis}_{\text{Käufer}}]$$
- Wenn Min_Verkäufer > Max_Käufer, ist die ZOPA negativ -> Keine Einigung möglich ohne Änderung der Verhandlungsmasse (Wertschöpfung durch zusätzliche Variablen).

### Schritt 5: Variable Verhandlungsmasse (Logrolling)
Erweitere die Verhandlung über den reinen Preis hinaus um kompensierende Variablen:
- Zahlungsziele (z. B. 14 Tage vs. 90 Tage)
- Vertragslaufzeit & Mindestabnahmemengen
- Exklusivitätsrechte & Co-Marketing
- SLA-Garantien & Haftungsdeckel

## 3. Ausgabe-Format (Template)
Jede Analyse muss strukturiert im folgenden Markdown-Format ausgegeben werden:
```markdown
### 📋 BATNA / ZOPA Strategie-Dossier: [Projekt / Deal-Name]
1. **Eigene BATNA:** [Konkrete Alternative mit Wert/Risiko]
2. **Walk-Away-Grenze (Reservationspreis):** [Hartes Limit]
3. **Geschätzte Gegenpartei-BATNA:** [Optionen & Schmerzpunkte]
4. **ZOPA-Korridor:** [Spanne von Min bis Max]
5. **Verhandlungshebel (Variables):** [Zusatzkonditionen zum Tausch]
6. **Taktische Empfehlung für die Eröffnung (Anchor):** [Strategischer Ankerpreis]
```
