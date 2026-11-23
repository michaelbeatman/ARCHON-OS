# Archon OS — NEVER-DO-Liste

**Verbindlich, Benutzerentscheidung vom 22.11.2026.** Die folgenden Punkte
wurden ausdrücklich **abgelehnt**. Sie dürfen nicht implementiert, nicht
vorgeschlagen und nicht als „offene Verbesserung" in Roadmaps aufgeführt
werden.

---

## 1. Echtes Coroutine-Replay im Durable Kernel — ABGELEHNT

- **Entscheidung:** Nicht machen. Unter keinen Umständen.
- **Begründung (Benutzer):** bewusst abgelehnt.
- **Geltender Zustand:** Der Durable Execution Kernel bleibt bei persistierten
  Node-States und Checkpoints. Das ist die akzeptierte Lösung.
- **Regel:** Keine Umstellung auf Event-Sourcing/Coroutine-Snapshotting, kein
  Replay-Framework, keine Diskussion als „Folgearbeit" in neuen Audits.

## 2. PostgreSQL-Migration — ABGELEHNT

- **Entscheidung:** Nicht machen. Unter keinen Umständen.
- **Begründung (Benutzer):** bewusst abgelehnt.
- **Geltender Zustand:** SQLite bleibt die Datenbank. Die Konsolidierung
  28 → 3 Domänen-DBs plus physisch isolierte Mandanten-DBs ist die
  endgültige Architektur.
- **Regel:** Keine PostgreSQL-Container, keine DSN-Konfiguration, kein
  Migrationstool, keine Empfehlung in Audits oder Roadmaps.

---

## Hinweis für Agenten

Diese Datei hat Vorrang vor `ROADMAP_2026.md`,
`SYSTEM_ARCHITEKTUR_UND_AUDIT_2026.md` und
`AUDIT_2026_11_SANIERUNG.md`, falls dort noch Hinweise auf Replay oder
PostgreSQL stehen. Die dortigen Erwähnungen sind historisch und nicht mehr
gültig.
