# Mehrfachaktionen im Kanban (Bulk Actions) mit 10-Minuten-Undo (`t-c2b384`)

## 1. Überblick

Mit dem Feature `t-c2b384` können mehrere Kanban-Karten simultan markiert und gemeinsam bearbeitet werden. Aktionen sind über eine schwebende Floating-Toolbar erreichbar und können dank eines transaktionalen Schnappschuss-Puffers **bis zu 10 Minuten lang vollständig rückgängig gemacht werden**.

---

## 2. Bedienkonzept (UX)

### 2.1 Mehrfachauswahl auf den Karten (Option B)
- **Strg-Klick / Cmd-Klick:** Schaltet die Auswahl der angeklickten Karte um (hinzufügen/entfernen).
- **Shift-Klick:** Markiert alle Karten im Bereich zwischen der zuletzt gewählten und der angeklickten Karte.
- **Dezenter Checkbox-Button:** Jede Karte besitzt links oben einen kreisförmigen Checkbox-Indikator, der beim Hover eingeblendet wird bzw. bei Auswahl gefüllt violett leuchtet. Ein direkter Klick schaltet die Auswahl ebenfalls um.
- **Visuelle Rückmeldung:** Ausgewählte Karten erhalten einen 2px violetten Umrandungs-Ring (`ring-2 ring-indigo-500`) und eine dezente Hintergrund-Tönung.
- **Abwählen:** Die Taste `Esc` oder ein Klick auf *„Aufheben“* hebt die Auswahl sofort auf.

### 2.2 Schwebende Floating-Toolbar (Option A)
Sobald mindestens eine Karte markiert ist, erscheint unten zentriert die Toolbar mit:
- Zähler der markierten Aufgaben (`X Aufgaben markiert`)
- **1. Verschieben:** Dropdown mit Ziel-Spalten (*Backlog*, *To-Do*, *In Arbeit*, *Review*, *Blockiert*, *Erledigt*).
- **2. Zuweisen:** Dropdown mit Avatar und Name aller verfügbaren Agenten aus dem Kader.
- **3. Taggen:** Schnelleingabe zum Hinzufügen oder Entfernen von Tags (z.B. `#Sprint-1`, `#P1`).
- **4. Archivieren / Löschen:** Sicherheitsabfrage zur Archivierung der gewählten Karten.

---

## 3. 10-Minuten-Undo-Transaktionspuffer

Nach Ausführung jeder Sammelaktion:
1. Erstellt das Backend einen Schnappschuss aller Original-Zustände (`status`, `assignee`, `tags`) und sichert diesen mit einem kryptografischen Token und `expires_at = now + 600s`.
2. Unten rechts erscheint ein schwebender Toast mit Live-Countdown (`10:00` bis `00:00`):
   ```
   ✓ 3 Aufgaben verschoben · Rückgängig möglich: 09:58  [↩ Rückgängig] [✕]
   ```
3. Ein Klick auf **Rückgängig** ruft `POST /api/operations/kanban/bulk/undo` auf und stellt alle betroffenen Aufgaben auf ihren exakten Ausgangszustand zurück.

---

## 4. API Endpunkte

### `POST /api/operations/kanban/bulk`
Führt eine Sammelaktion aus und liefert einen Undo-Token zurück.
```json
{
  "task_ids": ["t-123", "t-456"],
  "action": "move",
  "payload": { "status": "in_progress" }
}
```

### `POST /api/operations/kanban/bulk/undo`
Stellt den vorherigen Stand der Aufgaben wieder her.
```json
{
  "undo_token": "undo_2137a11010441d78"
}
```
