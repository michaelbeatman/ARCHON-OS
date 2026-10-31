# Archon OS – Human-Feedback-Loop & Qualitäts-Steuerung

*Stand: Oktober 2026 | Governance & Selbst-Evolution / Säule 6 & 7*

---

## 1. Übersicht & Architektur

Der Human-Feedback-Loop schließt die Brücke zwischen der menschlichen Bewertung von Agenten-Ergebnissen und der kontinuierlichen Selbst-Optimierung des Systems.

Bisher liefen die beiden Qualitäts-Module (`backend/eval_regression_runner.py` und `backend/prompt_optimizer.py`) isoliert ohne direkte Rückmeldung aus dem operativen Arbeitsalltag. Mit der Feedback-Engine werden Bewertungen direkt an den Task-Ergebnissen erfasst:

```
[Menschliche Bewertung] (Kanban Modal / Chat)
        │
        ├── 👍 Positiv (+1) ──────────> Feedback-Historie & Agent-Scorecard (Zustimmungsquote)
        │
        └── 👎 Mangelhaft (-1)
                 │
                 ├── 1. Auto-Generierung eines Gold-Standard Regressionstests
                 │      (eval_gold_cases mit erwarteten/verbotenen Signalwörtern)
                 │
                 └── 2. Trigger an Prompt-Optimizer
                        (Erkennt ab 3 Fehlern Muster und generiert Härtungs-Direktiven)
```

---

## 2. Benutzeroberfläche (Kanban Task Modal)

In jedem Aufgaben-Detailfenster des Operations Kanban steht unterhalb des Ergebnisses und des 4-Augen Qualitäts-Gates die Feedback-Box bereit:
- **Buttons:** `👍 Gut (Akzeptiert)` und `👎 Mangelhaft (Regressionstest)`
- **Eingabefelder:** 
  - *Korrekturhinweis:* Kurze Notiz zum Mangel (z. B. "JSON-Syntax fehlerhaft" oder "Frist fehlt").
  - *Wunschergebnis:* Erwartetes Wunschergebnis zur Definition der Gold-Standard-Erwartung.

---

## 3. API-Schnittstellen

| Endpunkt | Methode | Beschreibung |
| :--- | :--- | :--- |
| `/api/operations/feedback` | `POST` | Nimmt Feedback entgegen (`task_id`, `agent_id`, `score`, `comment`, `corrected_text`). |
| `/api/operations/feedback/stats` | `GET` | Liefert globale Gesamtzahlen, Zufriedenheitsrate in % und Auswertung je Agent. |
| `/api/operations/feedback/task/{task_id}` | `GET` | Liefert alle Bewertungen zu einer konkreten Aufgabe. |

Beispiel `POST /api/operations/feedback`:
```json
{
  "task_id": "t-b3f578",
  "agent_id": "realestate_concept_strategist",
  "score": -1,
  "comment": "Quellenbelege für Mietpreise fehlen",
  "corrected_text": "Mietspiegel 2026 Münster: 14,50 EUR/qm [Quelle: Gutachterausschuss]"
}
```
**Automatische Wirkung:** Das System legt sofort den Testfall `GOLD-FB-XXXX` in `eval_gold_cases` an, sodass künftige Prompt-Änderungen an diesem Agenten daran gemessen werden.
