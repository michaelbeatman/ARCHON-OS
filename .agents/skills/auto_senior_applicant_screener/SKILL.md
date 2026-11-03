---
name: auto_senior_applicant_screener
description: Bewerbungen Prüfen und Senior Coder Selektieren (Autonom erzeugt via Programming by Demonstration / PbD)
author: recruiter_specialist
created_at: 2026-11-03T12:55:40.197072
---

# Bewerbungen Prüfen und Senior Coder Selektieren

Dieser Skill wurde durch menschliches Vormachen im Bot-Screen (Programming by Demonstration) erlernt.

## Ziel-Kontext
- **Ursprüngliche Ziel-URL:** `https://karriere.portal.internal`
- **Anzahl aufgezeichneter Interaktionsschritte:** 4
- **Anti-Bot Schutz:** Biomechanischer Ghost-Cursor (Bézier-Kurven), Gauss-verteilter Klick-Jitter & variable Tasten-Kadenzen.

## Aufgezeichneter Handlungsablauf
1. **NAVIGATE**: {"url": "https://karriere.portal.internal"} — *"Navigiere zum Karriereportal"*
2. **CLICK**: {"selector": "#btn-filter-senior", "x": 65, "y": 42} — *"Klicke auf Filter für Senior-Profile"*
3. **TYPE**: {"field": "Suche", "text": "Python Fullstack"} — *"Tippe Suchbegriff mit natürlicher Kadenz"*
4. **CLICK**: {"selector": "#btn-submit-review", "x": 80, "y": 70} — *"Bewerbungen freigeben"*

## Ausführung
Führe das generierte Automations-Skript aus:
```bash
python scripts/dynamic_tools/auto_senior_applicant_screener.py
```
