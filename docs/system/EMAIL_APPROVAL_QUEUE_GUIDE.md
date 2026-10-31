# E-Mail Freigabe-Queue (HITL) & Revisionssichere Entwurfsverwaltung (`t-7ca8cd`)

## 1. Überblick & Architekturentscheidung

Um versehentliche oder fehlerhafte E-Mails von KI-Agenten an externe Kunden, Partner oder Behörden zuverlässig auszuschließen, verfügt Archon OS über eine zentrale **E-Mail Freigabe-Queue**. KI-generierte E-Mails verbleiben standardmäßig im Zustand `pending` (Human-in-the-Loop) und werden erst nach manueller Prüfung durch den Operator versendet.

### Kernmerkmale:
- **Human-in-the-Loop (HITL):** Keine unautorisierte externe Kommunikation.
- **GoBD- & ISO 27001 Konformität:** Jede Entwurfsänderung, Freigabe oder Verwerfung wird über eine fortlaufende SHA-256 Hash-Kette (`email_draft_audit_log`) unveränderbar protokolliert.
- **5 operative Prüfaktionen:**
  1. **Freigeben & Senden:** Entwurf genehmigen und final über SMTP versenden (verknüpfte Kanban-Tasks werden automatisch auf `done` gesetzt).
  2. **Im Editor bearbeiten:** Betreff, Empfänger und Text direkt in der UI korrigieren (mit Protokollierung des Prüfpfads).
  3. **Später erinnern (Snooze):** Entwurf für 1h, 4h, 24h oder 3 Tage zurückstellen.
  4. **Neu generieren:** Konkrete Korrekturanweisungen per Freitext an den verfassenden Agenten zurückspielen.
  5. **Abbrechen / Verwerfen:** Entwurf mit Angabe eines Ablehnungsgrundes unwiderruflich archivieren.

---

## 2. Benutzeroberfläche (UI Integration)

### 2.1 Neuer Reiter im Posteingang
Im Kopfbereich der Inbox (`inbox_view.html`) steht der 6. Navigations-Reiter **Freigaben** (Icon: Telemetry/Audit mit Live-Counter-Badge) bereit. Er zeigt in Echtzeit an, wie viele Entwürfe auf Freigabe warten.

### 2.2 Geteilte linke Spalte
Die linke Übersichtspalte wurde gemäß Vorgabe in zwei gleichwertige, aufgeräumte Hälften unterteilt:
- **Obere Hälfte: E-Mail Freigaben:** Kompakte Kacheln mit Status-Pille, Empfänger, Betreff und Uhrzeit. Klick öffnet das Freigabe-Modal.
- **Untere Hälfte: Angepinnt:** Schlanke, auf das Wesentliche reduzierte Kacheln für manuell markierte Meldungen und Webhooks.

### 2.3 Freigabe-Modal (`#modal-email-draft-review`)
Das Modal bietet eine vollständige Ansicht mit:
- Draft-ID, verfassendem Agenten und verknüpfter Task-ID
- GoBD SHA-256 Prüf-Hash
- Direkten Eingabefeldern für Empfänger, Betreff und Fließtext
- Aufklappbaren Bereichen für Neu-Generierungs-Feedback, Snooze-Zeiten und Ablehnungsgründe
- Sofort-Aktionsknöpfen in standardisierten Farbkodierungen (Grün: Senden, Blau: Speichern, Orange: Snooze, Lila: Neu generieren, Rot: Verwerfen).

---

## 3. REST-API Endpunkte

| Methode | Endpunkt | Beschreibung |
|---|---|---|
| `GET` | `/api/operations/email-drafts` | Ruft alle Entwürfe ab (Filter nach `status` möglich) |
| `POST` | `/api/operations/email-drafts` | Erstellt einen neuen Entwurf (Agenten-Tool) |
| `GET` | `/api/operations/email-drafts/{id}` | Detailansicht eines Entwurfs |
| `POST` | `/api/operations/email-drafts/{id}/approve` | **Aktion 1:** Freigabe & SMTP-Versand |
| `PUT` | `/api/operations/email-drafts/{id}` | **Aktion 2:** Text & Empfänger anpassen |
| `POST` | `/api/operations/email-drafts/{id}/snooze` | **Aktion 3:** Entwurf zurückstellen |
| `POST` | `/api/operations/email-drafts/{id}/regenerate` | **Aktion 4:** Neu-Generierung durch Agenten |
| `POST` | `/api/operations/email-drafts/{id}/reject` | **Aktion 5:** Entwurf verwerfen |

---

## 4. Datenbank-Schema (`agentic_memory.db`)

```sql
CREATE TABLE email_drafts (
    draft_id TEXT PRIMARY KEY,
    subject TEXT NOT NULL,
    recipient TEXT NOT NULL,
    sender TEXT NOT NULL,
    agent_id TEXT DEFAULT 'default',
    agent_name TEXT DEFAULT 'Hermes Orchestrator',
    body_text TEXT NOT NULL,
    body_html TEXT,
    status TEXT DEFAULT 'pending', -- pending, approved, snoozed, rejected
    snooze_until TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    approved_at TEXT,
    approved_by TEXT,
    rejected_at TEXT,
    rejected_by TEXT,
    rejection_reason TEXT,
    feedback_text TEXT,
    source_task_id TEXT,
    audit_hash TEXT
);

CREATE TABLE email_draft_audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    draft_id TEXT NOT NULL,
    action TEXT NOT NULL,
    details TEXT,
    prev_hash TEXT NOT NULL,
    block_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    created_by TEXT NOT NULL
);
```
