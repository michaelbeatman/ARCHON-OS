---
name: skill-entscheidungsmatrix-analyse
description: Systematische Nutzwertanalyse (NWA), Entscheidungsbäume und probabilistische Risikobewertung für komplexe Unternehmensbeschlüsse.
version: 1.0.0
author: ARCHON OS Intelligence
category: 1. Strategie, Führung & Lebensplanung
tags: ["entscheidung", "nutzwertanalyse", "risiko", "strategie"]
---

# 📊 Nutzwertanalyse & Entscheidungsmatrix

Dieser Skill liefert strukturierte Entscheidungsgrundlagen bei konkurrierenden Handlungsoptionen.

## 1. Methodik der Nutzwertanalyse (NWA)
1. **Kriterien-Definition:** Festlegung von Muss- und Soll-Kriterien (z. B. ROI, Amortisationszeit, Umsetzungsaufwand, Skalierbarkeit).
2. **Gewichtung:** Vergabe von Prozentwerten ($\sum w_i = 100\%$).
3. **Punktebewertung:** Skala von 1 (sehr schlecht) bis 10 (hervorragend) pro Kriterium.
4. **Gesamtnutzwert:** $N = \sum (w_i \cdot p_i)$.

## 2. Risikomatrix (FMEA-Prinzip)
- **RPZ (Risiko-Prioritäts-Zahl):** $RPZ = A \text{ (Auftretenswahrscheinlichkeit)} \cdot B \text{ (Bedeutung)} \cdot E \text{ (Entdeckungschance)}$.
- Schwellenwert: Handlungsbedarf bei $RPZ > 100$.

## 3. Ausgabe-Format
```markdown
### 🎯 Entscheidungsdossier: [Entscheidungsgegenstand]
| Kriterium | Gewichtung | Option A | Option B | Option C |
|---|---|---|---|---|
| 1. Finanzieller Ertrag | 30% | 8 (2.4) | 6 (1.8) | 9 (2.7) |
| 2. Umsetzungsrisiko | 25% | 7 (1.75) | 9 (2.25) | 5 (1.25) |
| 3. Zeithorizont | 20% | 6 (1.2) | 8 (1.6) | 7 (1.4) |
| 4. Strategischer Fit | 25% | 9 (2.25) | 7 (1.75) | 8 (2.0) |
| **Gesamtnutzwert** | **100%** | **7.60** | **7.40** | **7.35** |

**Empfehlung & Begründung:** [Option A gewinnt aufgrund des hohen strategischen Fits...]
```
