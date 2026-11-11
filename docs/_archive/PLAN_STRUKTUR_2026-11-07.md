# Etappenplan Struktur (Paket 3) — 2026-11-07

**Status: PLAN, nicht beauftragt zur Ausführung.** Michael hat entschieden: erst Paket 1 (Quick Wins)
und Paket 2 (RBAC-Rest), dann Struktur. Dieses Dokument ist die Vorlage, damit die Reihenfolge nicht
jedes Mal neu verhandelt wird.

Projekt: Archon OS, `/mnt/raid/AgenticOS-2026`. Branch-Basis: `refactor/a5-di-config`.
Alle Zahlen sind gemessen (Belege in `docs/GRUNDPRUEFUNG_2026-11-07.md`, `docs/AUDIT_STATUS.md`).

## Regeln für JEDE Etappe (unverhandelbar)

1. **Vorbedingung:** Paket 1 und Paket 2 sind committet, Guards grün, Working Tree ohne fremde `M`-Zeilen.
2. **Ein Schnitt pro Etappe**, mit wörtlich benannten **Nicht-Zielen**. Kein Etappen-Mix.
3. **Drei Pflicht-Guards nach jeder Änderung** — Parität 585/861, `check_router_names` exit 0,
   `pytest tests/`. Rot → sofort `git checkout -- <Datei>`, Bericht.
4. **Erst Inventur (nur lesen, Ergebnis als Dokument), dann Schnitt.** Eine Etappe darf **0 Änderungen**
   ergeben, wenn kein Kandidat die Bedingungen erfüllt — das ist ein Ergebnis, kein Scheitern.
5. **Tests vor Code**, Rot-Beweis gegen den Altstand (`git show HEAD:<datei>` ins Scratch, nicht ins Repo).
6. **Kein Commit durch den Ausführenden.** Michael gibt frei, der Router committet pfadgenau.
7. **Messwert vor/nach** je Etappe, sonst ist die Etappe nicht abgenommen.

---

## Etappe 1 — `hermes_updater` auf den Allowlist-Client (B3/S1-Rest)

| | |
|---|---|
| **Ziel** | `DockerSocketClient` in `backend/hermes_updater.py` (roher `AF_UNIX` auf `/var/run/docker.sock`) verschwindet vollständig; alle Aufrufe laufen über `utils/docker_client` |
| **Warum** | Zweite, ungeprüfte Wahrheit neben der Allowlist; repo-weit gibt es genau **zwei** AF_UNIX-Stellen — eine ist der Guard, die andere dieser Client |
| **Vorbedingung** | Grundprüfung §4.3 (Inventar der Endpunkte) + Hunk-Tabelle aus der Defektanalyse |
| **Nicht-Ziele** | Kein Umbau der Update-Logik, kein Recreate-Test gegen einen echten Container, keine Änderung an `_ALLOWED` für den Hauptpfad |
| **Schnitt** | Opt-in-Admin-Allowlist (`admin=True`) im Client + Migration der 14 Aufrufstellen; Image-Allowlist für Recreate |
| **Test** | AST-Scan: kein `socket.AF_UNIX` mehr außerhalb `utils/docker_client.py`; Admin-Endpunkte nur mit `admin=True`; 8 Endpunktformen einzeln erlaubt |
| **Abbruch** | Wenn ein Updater-Endpunkt nicht ohne `create/rename/delete`-Rechte abbildbar ist → Etappe anhalten, Befund dokumentieren (kein Aufweichen der Basis-Allowlist) |
| **Aufwand** | 3–4 h |
| **Risiko** | mittel: der Update-Pfad hat heute **keinen** Test; falsche Allowlist bricht ihn zur Laufzeit |

## Etappe 2 — B10: 145 hartkodierte `/opt/data`-Pfade

| | |
|---|---|
| **Ziel** | Pfad-Konstanten aus `archon/core/paths.py` benutzen statt Literale (`/opt/data` = Host `~/.hermes`) |
| **Warum** | 145 Vorkommen (main 75, archon 20, backend 41, utils 9); Andockpunkt `paths.py` existiert bereits aus der A5-Etappe 5 (18 Konstanten) |
| **Nicht-Ziele** | Keine Änderung der Pfad-**Werte**, keine Umstellung von `scripts/`/`tests/` (dort 50 weitere), keine Verhaltensänderung |
| **Schnitt** | Nur `archon/` + `utils/` in dieser Etappe (61 Stellen) — `main.py` (75) in einer Folgetappe |
| **Test** | AST-Test: kein `/opt/data`-Literal mehr in den Zielbäumen; Snapshot-Vergleich `scripts/path_constants_snapshot.py` **in Host und Container** vor/nach identisch |
| **Abbruch** | Wenn ein Literal bewusst einen anderen Wert meint (z. B. Container-intern) → als Ausnahme im Test pinnen, nicht umschreiben |
| **Aufwand** | 2–3 h je Etappe |
| **Risiko** | mittel: Host-Import von `main.py` löst `MEMORY_DIR`/`DATA_DIR` als `"."` auf → Snapshot nur im Container aussagekräftig |

## Etappe 3 — B9: 50 doppelte `api_route` in `main.py`

| | |
|---|---|
| **Ziel** | Doppelte Routen (gleicher Handler unter zwei Pfaden) auf eine Meta-Route mit Alias/Redirect konsolidieren |
| **Warum** | 50 × `api_route(` in `main.py`; Frontend-Aufrufe prüfen: **0** Aufrufe ohne Route, aber viele Routen ohne Aufrufer (543 von 861, Obergrenze) |
| **Nicht-Ziele** | Keine Pfad-Löschung ohne Frontend-Beleg; keine Änderung am Auth-Gate; keine Routen-Zusammenlegung über Router-Grenzen |
| **Vorbedingung** | **Inventur:** je der 50 Paare → wer ruft welchen Pfad (Frontend, Tests, Skripte, Cron)? Ergebnis als Tabelle. Nur Paare **ohne** externen Aufrufer auf der Zweitroute werden zusammengelegt |
| **Test** | Parität **muss** sich hier ändern — Baseline explizit neu erzeugen, Diff der Pfadliste vorlegen, Altdaten für Rollback behalten |
| **Abbruch** | Sobald ein Aufrufer der Zweitroute existiert: Paar auslassen |
| **Aufwand** | 1–2 Tage (Inventur ~60 % der Zeit) |
| **Risiko** | hoch: Parität ist hier kein Schutz, sondern das Ziel — jede Etappe braucht einen eigenen Baseline-Diff |

## Etappe 4 — A8: Config-Zentralisierung (26 Dateien mit `os.environ`/`os.getenv`)

| | |
|---|---|
| **Ziel** | Ein zentraler Zugriffspunkt für Umgebungs-Konfiguration, Defaults an einer Stelle |
| **Warum** | 26 Dateien lesen Env direkt; Defaults sind verstreut und teils widersprüchlich |
| **Nicht-Ziele** | Keine Änderung von Default-Werten (Verhalten bleibt bitgleich), keine Env-Datei-Umstellung, keine Secrets anfassen |
| **Schnitt** | Erst Inventur (welche Variablen, welche Defaults, wer liest sie), dann ein Modul `archon/core/config.py` mit Lesefunktionen; Migration in zwei Etappen (archon/utils, dann main) |
| **Test** | Für jede Variable: gelesener Wert identisch bei gesetzt/ungesetzt (Test reiht beide Fälle durch); kein `os.environ` mehr außerhalb des Config-Moduls |
| **Abbruch** | Wenn eine Variable zur Laufzeit mutiert wird (Reload-Pfad) → auslassen, dokumentieren |
| **Aufwand** | 1 Tag |

## Etappe 5 — A6: 31 × `asyncio.to_thread` (Sync-I/O in async)

| | |
|---|---|
| **Ziel** | Verbleibende sync-I/O-Aufrufe in `async def`-Handlern über Threadpool führen oder den Handler sync machen |
| **Warum** | 31 repo-weit (main 15, archon 14, backend 2); die Grundprüfung hat gezeigt, dass **kein** Docker-Aufruf in einem `async def` steht (P2 entlastet) — die Kandidaten sind also andere |
| **Vorbedingung** | **Inventur per AST:** welche `async def`-Handler rufen blockierende Funktionen (Datei-I/O, `subprocess`, `sqlite3`, `requests`)? Ergebnis als Liste mit Datei:Zeile |
| **Nicht-Ziele** | Kein Umbau von Handlern, die bereits korrekt sync sind; keine neuen Dependencies |
| **Test** | Je Handler: Event-Loop bleibt frei (Test mit `asyncio.wait_for`-Zeitbudget), Verhalten identisch |
| **Abbruch** | Kandidatenliste leer → Etappe endet mit Befund, 0 Änderungen |
| **Aufwand** | 4–6 h |

---

## Empfohlene Reihenfolge

1. **Etappe 1** (hermes_updater) — kleinster Blast-Radius, schließt den letzten rohen Socket.
2. **Etappe 5** (A6-Inventur) — kann eine Nullnummer ergeben, kostet wenig, entlastet A6 endgültig.
3. **Etappe 2** (B10) — mechanisch, gut testbar, in kleinen Dosen.
4. **Etappe 4** (A8) — braucht die B10-Konstanten als Vorarbeit.
5. **Etappe 3** (B9) — zuletzt: hier wird die Parität zum Ziel, das braucht die stabilste Suite.

## Was bei JEDER Etappe in die Doku gehört

- Etappendokument mit Inventur, Schnitt, Nicht-Zielen, Messwerten.
- `AUDIT_STATUS.md`: betroffene Punkte auf den neuen Stand (Status + Zahl + Messbefehl).
- Handover-Nachtrag mit Revert-Handle je Commit.
