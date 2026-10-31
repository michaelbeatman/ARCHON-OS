# Agent-Scorecards & Personalakte mit Obsidian-Synchronisation (`t-f257ba`)

## 1. Überblick

Mit dem Feature `t-f257ba` wurden die **Agent-Scorecards** direkt in die **Digitale Personalakte** (`agent_profiles_view.html`) integriert. Anstelle der redundanten Fach-Skills-Kachel zeigt die Personalakte nun eine ganzheitliche Leistungsübersicht mit 6 Kern-KPIs, verknüpften Obsidian-Projektsphären, Meilensteinen und persistenter Operator-Beurteilung.

---

## 2. Die 6 Leistungs-KPIs

1. **Erfolgsquote & 4-Augen-Review (🎯):** Anteil der Aufgaben ohne Beanstandung im 4-Augen-Gate.
2. **Token- & Kosten-Effizienz (🪙):** Ø Token-Verbrauch und durchschnittliche Kosten (\$ pro Task).
3. **Durchlaufzeit / Speed (⏱️):** Ø Bearbeitungsdauer vom Start (`started_at`) bis Abschluss (`completed_at`).
4. **Operator-Feedbackwert (👍):** Positiv-Quote aus der Master Console (`human_feedback`).
5. **Autonomie-Index / First-Pass (🤖):** Quote von Aufgaben, die ohne Nachbesserung oder manuelle Intervention direkt abgeschlossen wurden.
6. **Erkenntnisgewinn / Learnings (💡):** Anzahl der extrahierten Heuristiken und System-Regeln (`learnings`).

---

## 3. Qualitative Inhalte & Obsidian-Sync

- **Beteiligte Projekte (Obsidian Sphären):** Automatische Auflistung aller Projekt-Ordner, in denen der Agent Aufgaben bearbeitet hat.
- **Letzte Meilensteine:** Die 5 neuesten Kanban-Aufgaben mit Status-Badge.
- **Operator-Beurteilung & Arbeitsanweisungen (Option A):**
  - Editierbare Notizen des Operators direkt in der Personalakte.
  - Zwei-Wege-Sync: Wird persistent in `kv_store` und im Markdown-Dossier unter `00_HR_Agenten/Personalakten/{agent_id}.md` (Abschnitt `## Operator-Beurteilung & Arbeitsanweisungen`) gespeichert.

---

## 4. REST Endpunkte

| Methode | Endpunkt | Beschreibung |
|---|---|---|
| `GET` | `/api/operations/agents/{id}/scorecard` | Liefert aggregierte KPIs, Projekte und Meilensteine |
| `POST` | `/api/operations/agents/{id}/operator-notes` | Speichert Operator-Notizen & synct nach Obsidian |
| `GET` | `/api/v1/hr/personalakte/{id}` | Lädt Obsidian-Markdown der Personalakte |
| `POST` | `/api/v1/hr/personalakte/{id}` | Speichert Änderungen im Obsidian-Vault |
