# Verdrahtungs-Audit 2026 — „100 % korrekt verdrahtet"

**Einstufung: KRITISCH.** Der vorige Auditbefund lautete: „Zwei Drittel der
Kernmechaniken sind verdrahteter Schein." Das ist kein Kosmetikproblem,
sondern ein Vertrauensproblem: Ein System, das Gates, Queues, Guards und
Publishing anzeigt, aber nicht ausführt, ist gefährlicher als ein System,
das diese Features gar nicht behauptet.

## 100%-Kriterium

Eine Mechanik gilt nur als **korrekt verdrahtet**, wenn alle vier Glieder
nachweisbar im Produktivpfad existieren:

1. **Produzent** – wer erzeugt den Zustand/das Event/das Artefakt?
2. **Konsument** – wer liest es im echten Ablauf (nicht nur in Tests und
   nicht nur über einen manuellen Endpoint)?
3. **Effekt** – welche sichtbare/ nachweisbare Wirkung hat es (DB-Status,
   Datei, Webhook, Audit-Event)?
4. **Verifikation** – es gibt einen Test oder eine Metrik, die Scheitern
   sichtbar macht.

Fehlt eines davon, ist die Mechanik „Theater" und wird in diesem Dokument
mit `FUND` erfasst.

## Prüffelder

| Feld | Erwartung |
|---|---|
| Quality-/Fact-Check-/Plagiat-/Kanal-Gates | blockieren Freigabe, nicht nur Score |
| Outbox / DLQ | produktiver Drainer mit CAS + Retry + Dead-Letter |
| Cancel-Token | nach jedem `await` geprüft, Status `cancelled` persistiert |
| `synthesis_started` | mit Timestamp + Watchdog rücksetzbar |
| Tool-Output-Firewall | im echten Tool-Chokepoint, nicht nur Endpoint |
| Secret-Masking | vor jedem externen LLM-Dispatch |
| Egress-Firewall | auch für als „lokal" klassifizierte Zonen |
| Tenant-Scope | in Cache, Idempotency, Ledger, GDPR-Löschung |
| Audit-Schreibfehler | nicht verschluckt |
| UI-Controls | Handler vorhanden, Ziel-Endpunkt existiert |
| SSE | Cockpits hören auf echte Events statt manuellem Refresh |
| Status-Maps | alle Backend-Statuswerte sind im Frontend bekannt |

## Vorgehen

1. Paralleleaudits: Infrastruktur, Content, Orchestrierung, Frontend, Sicherheit/DB.
2. Jeder Fund: Datei:Zeile · Ist · Soll · minimaler Fix · Schwere.
3. Fixe in priorisierter Reihenfolge, danach Re-Audit gegen dieses Dokument.
4. Abschluss erst, wenn alle vier Glieder für jede Kernmechanik belegt sind.

## Status

_Abgeschlossen (23.11.2026): 15 Audits konsolidiert, Produktivpfade nachgezogen,
Gesamt-Testlauf grün (1727 passed)._details siehe `AUDIT_ABSCHLUSS_2026_11_23.md`._
