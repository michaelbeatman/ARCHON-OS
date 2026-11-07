# Analyse: Gate-Approve-Defekt (P2) — Schnittform-Entscheidung

Stand: 2026-11-07, Branch `refactor/a5-di-config` @ `cb90a157` (Arbeitsstand).
Eingriffsstufe: nur Lesen. Kein Code geaendert, kein Commit, kein Deploy.

## 0. Befund gegengeprueft (gemessen, nicht nur gelesen)

`main.py` bindet die beiden Dispatch-Ziele nicht. Belegt durch AST-Lauf
(`/home/micha/.hermes/profiles/senior_fullstack_engineer/cache/scratch/ast_unbound.py`)
und durch einen echten Lauf der Gate-Entscheidung:

```
ERROR archon_os:[Gate] Ausfuehrung nach Freigabe fehlgeschlagen: name 'api_save_hermes_profile' is not defined
ERROR archon_os:[Gate] Ausfuehrung nach Freigabe fehlgeschlagen: name 'api_delete_hermes_profile' is not defined
```

Beide Gates antworten mit **HTTP 200** und `ergebnis = "FEHLER bei der Ausfuehrung: ..."`.
Der Telegram-Adapter wertet nur `status_code == 200` aus
(`scripts/patches/hermes_telegram_adapter.py:6803-6805`) und antwortet dem Owner
„✅ Rechte freigegeben - wird jetzt ausgefuehrt." — der Fehlschlag wird **nicht** gemeldet.

Zweiter, unabhaengiger Defekt im selben Handler: der Gate-Status wird **vor** der
Ausfuehrung persistiert (`main.py:2880-2882`), danach laeuft die Ausfuehrung
(`main.py:2887-2899`). Ein Fehlschlag verbraucht das Gate: erneutes Zustellen
liefert `already_decided` (`main.py:2877-2878`). Gemessen mit
`test_fehlgeschlagene_ausfuehrung_verbraucht_das_gate_nicht` → rot
(`Gate wurde ohne Ausfuehrung verbraucht: approved`).

## 1. Was aus den Endpunktfunktionen heraus muss

### `api_save_hermes_profile` — `archon/routers/hermes_profiles.py:98-408`

| Zeilen | Inhalt | Ziel |
|---|---|---|
| 98 | Signatur `(request: Request, profile_data: Dict = Body(...))` | Service nimmt `profile_data: dict` |
| 99 | `require_admin_or_503(request)` | **bleibt** im Router (HTTP-Zaun) |
| 100-109 | id-/person_name-/avatar-Normalisierung | Service |
| 110-136 | Gate-Zweig: `_gate_ok = bool(profile_data.get("_approved_gate_id"))` (111), profile.yaml-Vergleich (113-123), `_create_permission_gate` (128-131) | Service, aber **Trust-Zweig muss verifizieren** (s. §2) |
| 137-146 | tools/skills/provider/model/reasoning-Defaults | Service |
| 147-165 | Prompt-Aufloesung inkl. SOUL.md-Datei-I/O | Service |
| 166-186 | Pydantic-Validierung, `raise HTTPException(422)` (185-187) | Service, aber **HTTPException muss zu einem Domaenenfehler werden** |
| 187-230 | Avatar base64-Decode, Schreiben nach `avatars_dir()` | Service |
| 231-247 | Avatar-Pfadaufloesung | Service |
| 248-330 | je Basisordner: mkdir, `create_rolling_backup`, SOUL.md/profile.yaml/config.yaml | Service |
| 310-330 | Skill-Kopieren (`shutil.copytree/copy2`) | Service |
| 331-367 | agent_profiles.json-Sync via `os.path.dirname(__file__)` | Service — **Pfad ist heute falsch** (s. §5) |
| 368-400 | avatars.db-Sync (sqlite3) | Service |
| 395-401 | `_DEPS["_sync_org_hierarchy_node"](...)` | Service — **einziger main.py-gebundener Dep** |
| 404-408 | `invalidate_hermes_profiles_cache()`, `api_get_hermes_profiles()`, `add_ticker`, Return | Service |

Abhaengigkeiten vollstaendig: `re`, `os`, `json`, `shutil`, `yaml`, `datetime`,
`sqlite3`/`hashlib`/`time` (lokal importiert, 369), `base64` (lokal, 189),
`HTTPException` (185), `Body`/`Request` (nur Signatur), `require_admin_or_503`
(nur 99), `_create_permission_gate`, `_load_permission_gates` (590),
`create_rolling_backup`, `avatars_dir`, `get_hermes_profiles_base_dirs`,
`invalidate_hermes_profiles_cache`, `api_get_hermes_profiles`,
`DEFAULT_HERMES_TOOLS`, `MEMORY_DIR`, `add_ticker`, `logger`,
`_DEPS["_sync_org_hierarchy_node"]`.

**Telegram ist nicht Teil des Service** — der Ping liegt im Decide-Handler
(`main.py:2903-2909`) und bleibt dort. Ebenso Ticker/Ticker-Eintrag des Gates
(`main.py:2909`).

### `api_delete_hermes_profile` — `archon/routers/hermes_profiles.py:584-635`

| Zeilen | Inhalt | Ziel |
|---|---|---|
| 584 | Signatur `(request, profile_id, gate_approved_id="")` | Service: `(profile_id, approved_gate_id="")` |
| 585 | `require_admin_or_503(request)` | **bleibt** im Router |
| 586-587 | System-Profil-Schutz, `raise HTTPException(400)` | Service als Domaenenfehler |
| 589-600 | Gate-Anlage-Zweig (`_load_permission_gates`, `_create_permission_gate`) | Service |
| 602-616 | `shutil.move` ins `.archive`, Zeitstempel | Service |
| 617-629 | agent_profiles.json-Filter + `create_rolling_backup` | Service — **Pfad falsch** (`__file__` → `archon/routers/`) |
| 631-635 | Cache-Invalidierung, `api_get_hermes_profiles()`, `add_ticker`, Return | Service |

Abhaengigkeiten: `os`, `json`, `shutil`, `datetime`, `datetime`, `HTTPException`,
`_load_permission_gates`, `_create_permission_gate`, `create_rolling_backup`,
`get_hermes_profiles_base_dirs`, `invalidate_hermes_profiles_cache`,
`api_get_hermes_profiles`, `add_ticker`, `logger`. **Kein** main.py-Dep.
`Request` wird ausschliesslich in Zeile 585 benutzt.

## 2. RBAC-Vertraeglichkeit — das entscheidende Kriterium

Gemessene Autorisierungslage auf dem Gate-Pfad:

1. Der **HTTP-Eingang** ist gated: `require_admin(request)` als erste Anweisung
   (`main.py:2869`).
2. `require_admin` (`main.py:7331-7360`) laesst durch bei: Admin-Session,
   `X-Archon-Service-Token` (`main.py:7306-7315`), und — **im Single-User-Modus
   fuer jeden** — `get_fallback_admin()` (`main.py:7326-7328`).
3. Der **Telegram-Pfad** prueft die Owner-Identitaet **vor** dem HTTP-Aufruf:
   `_is_callback_user_authorized(caller_id, ...)` (`hermes_telegram_adapter.py:6783-6791`),
   sonst „⛔ You are not authorized to decide permission gates."
4. Der Gate-Record wird **nur** an einer Stelle auf `approved` gesetzt:
   `main.py:2880` — hinter dem Zaun aus (1). `grep '"approved"'` liefert genau
   diesen einen Treffer.

Damit gilt: **die Autorisierung findet bereits vor dem Dispatch statt.** Der
interne Aufruf ist kein zweiter Einstiegspunkt, sondern ein Folgeschritt
*innerhalb* eines bereits autorisierten Requests. Keine der beiden Varianten
kann eine Autorisierung erzeugen, die Zeile 2869 nicht schon erteilt hat — die
Frage ist nur, **wo** die Pruefung sitzt und **wie faelschbar** sie ist.

**Variante 1 (Service):** Der Zaun bleibt unveraendert in beiden Routern
(`:99`, `:585`) und damit fuer den HTTP-Pfad voll wirksam — die Router-Signaturen
werden nicht angefasst. Auf dem internen Pfad ersetzt die Pruefung **das
Gate-Record** die Request-Pruefung: der Service darf nur laufen, wenn er selbst
einen Datensatz mit `status == "approved"`, passendem `kind` und passender
`payload` laedt. Das ist ein **persistiertes, einfach-genutztes, auditierbares
Beweisstueck** statt eines synthetischen Requests.

**Luecke, die Variante 1 schliessen muss (heute schon offen):**
`_gate_ok = bool(profile_data.get("_approved_gate_id"))`
(`hermes_profiles.py:111`) prueft nur **Wahrheitswert**, nicht die Existenz. Ein
beliebiger Admin-Client kann `"_approved_gate_id": "x"` posten und den
Tools-Gate ueberspringen. Solange der Service diese Zeile unveraendert
uebernimmt, wird er zum Bypass: er wuerde ein Flag glauben, das er nicht
verifiziert hat. **Die Service-Variante ist deshalb nur zulaessig, wenn die
Verifikation echt wird** (Gate laden, Status/Kind/Payload vergleichen, danach
als verbraucht markieren).

**Variante 2 (Shim) oeffnet die groessere Flaeche:** sie gibt der aufrufenden
Stelle einen echten Admin-Ausweis in die Hand. Um `require_admin_or_503` zu
befriedigen, muss `main.py` entweder das Service-Token setzen
(`_get_service_token()`, `main.py:154-171`) oder eine Marker-Pruefung in
`require_admin` einbauen. Beides macht aus „intern" ein universelles
Durchlass-Kriterium, das jede andere Stelle in `main.py` ebenfalls benutzen
kann — ohne Gate-Record, ohne Spur. Zusaetzlich haengt die Fail-closed-Eigenschaft
dann an der Deployment-Konfiguration: bei `auth.enabled = false` liefert
`get_fallback_admin()` ohnehin Admin, der Shim "funktioniert" also auch ohne
jede Pruefung. Gleicher Code, andere Sicherheitslage je `settings.json`.

## 3. Fail-closed-Regel

Regel, die gelten muss:

> Eine Gate-Ausfuehrung darf nur stattfinden, wenn ein **verifizierter**
> Gate-Datensatz mit `status == "approved"` **und** passendem `kind` **und**
> passender `payload` vorliegt. Fehlt er, ist er nicht eindeutig oder ist die
> Pruefung nicht durchfuehrbar (Datei unlesbar), wird **gesperrt** und der
> Gate-Status **nicht** auf `approved` fortgeschrieben.

Konkret:

* **Variante 1:** Service wirft `GateNotApproved` (Domaenenfehler) → Handler
  antwortet 409/403 mit `status: "error"` — nicht 200. Gate bleibt `pending`.
  Das ist deterministisch, ohne HTTP-Stack testbar und deckungsgleich mit dem
  bestehenden Muster in `archon/routers/_rbac.py:11-16` („ohne Injektion
  sperren statt durchlassen").
* **Variante 2:** `require_admin_or_503` wirft 503, wenn nicht verdrahtet
  (`_rbac.py:50-56`) — das ist fuer sich gut. Aber der Shim liefert genau dann
  Admin, wenn `auth.enabled = false`; die Sperre greift also **nicht** in der
  Standardkonfiguration des Hauses. Fail-closed ist damit nicht code-, sondern
  konfigurationsabhaengig. **Nicht akzeptabel.**

Zusatzregel, unabhaengig von der Variante: `main.py:2880-2882` muss **nach**
die Ausfuehrung wandern (Status erst nach Erfolg persistieren, bei Fehlschlag
`failed` + HTTP != 200), sonst ist jeder Fehlschlag ein verbranntes Gate und
der Owner bekommt trotzdem „✅".

## 4. Teststrategie

Datei: `tests/test_gate_approve_ausfuehrung.py` (neu).

Der Test darf **den Namen unter Test nicht anlegen.** Erster Entwurf mit
`monkeypatch.setattr(main, "api_save_hermes_profile", ..., raising=False)` war
**gruen ohne Fix** — der monkeypatch legt genau den Namen an, dessen Fehlen der
Defekt ist. Genau diese Falle ist im Mandat gemeint und sie ist real
eingetreten.

Tragfaehig ist ein Test, der den Namen **nicht** anlegt und den Pfad echt bis
zur Dateiebene laufen laesst (nur die Zielordner zeigen auf `tmp_path`):

| Fall | Zusage | Heute |
|---|---|---|
| `test_tools_erweiterung_schreibt_profil` | Freigabe schreibt `profile.yaml` mit den neuen Tools, `ergebnis` ohne „FEHLER" | **rot** (`name 'api_save_hermes_profile' is not defined`) |
| `test_profil_loeschen_archiviert` | Profilordner ist nach Freigabe weg | **rot** (`name 'api_delete_hermes_profile' is not defined`) |
| `test_fehlgeschlagene_ausfuehrung_verbraucht_das_gate_nicht` | bei Fehlschlag bleibt `status == "pending"` | **rot** (`approved`) |

Alle drei wurden mit dem Projekt-venv ausgefuehrt: `3 failed in 1.68s`.

Zusatztest fuer §2 (in derselben Datei): `test_service_verweigert_unverifiziertes_gate`
— Service mit `_approved_gate_id="gibt_es_nicht"` muss `GateNotApproved` werfen.
Dieser Fall ist heute **nicht** rot (das Flag existiert nicht), er ist die
Absicherung gegen die in §2 beschriebene Luecke und muss mit der Extraktion
zusammen entstehen.

## 5. Nicht-Ziele

* Keine Aenderung an Response-Formaten der beiden Endpunkte
  (`{"status": "pending_owner_approval", ...}` bei Anlage,
  `{"status": "success", "profile": ...}` bzw. `{"status": "success",
  "profile_id": ..., "archived_to": [...]}` bei Ausfuehrung).
* Keine Aenderung der Router-Pfade, Methoden oder Signaturen nach aussen
  (`POST /api/hermes/profiles`, `DELETE /api/hermes/profiles/{profile_id}`).
* Keine Aenderung an `archon/core/profiles.py` (Lese-/Cache-Schicht) und nicht
  an `archon/routers/_rbac.py`.
* Keine Aenderung an `main.py:2869` (`require_admin` auf dem Decide-Endpunkt)
  und keine Aufweichung von `require_admin` (`main.py:7331`).
* Kein Umbau der anderen vier `hermes_profiles`-Endpunkte (Avatar, Status,
  Hire/Fire-Paperclip, Model, Favorit) — sie sind nicht Teil des Defekts.
* Keine Aenderung am Telegram-Adapter und am Gate-Anlage-Zweig: die beiden
  Gate-Kinds `tools_erweiterung`/`profil_loeschen` sind die einzigen im System
  (`grep create_permission_gate` → genau zwei Aufrufer, `:128`, `:595`;
  `grep 'kind =='` → genau die zwei Dispatch-Zweige `main.py:2888`, `:2892`).

**Bewusst mitzunehmen, weil sonst still falsch:** die `agent_profiles.json`-Pfade
in `hermes_profiles.py:333` und `:557`/`:618` leiten sich aus
`os.path.dirname(os.path.abspath(__file__))` ab — im Router ist das
`archon/routers/`. Gemessen: `archon/routers/agent_profiles.json` existiert
**nicht**, der gesamte Sync-Block (331-367, 617-629) ist heute toter Code,
bestaetigt durch `ls`. Wandert die Datei nach `archon/services/`, zeigt der Pfad
auf ein drittes falsches Verzeichnis — der Fehler bleibt unsichtbar. Bei der
Extraktion muss hier `APP_ROOT` stehen (wie `avatars_dir()`,
`archon/core/profiles.py:46-48` es richtig macht).

## 6. Zusatzfrage: weitere ungebundene Aufrufe

AST-Lauf ueber alle `ast.Call`-Knoten mit `ast.Name`-Funktion in `main.py`,
abzueglich aller Bindungen (def/class/arg/Store/Import/ImportFrom/except/
global/Match) und der Builtins; gegengeprueft gegen Definitionen in
`archon/routers/*.py`. Ergebnis: **4 ungebundene Namen, 3 davon Router-Funktionen.**

| Name | Aufrufstelle | Definition | Wirkung heute |
|---|---|---|---|
| `api_save_hermes_profile` | `main.py:2890` | `hermes_profiles.py:98` | Gate `tools_erweiterung` → NameError, HTTP 200 mit „FEHLER" |
| `api_delete_hermes_profile` | `main.py:2893` | `hermes_profiles.py:584` | Gate `profil_loeschen` → dito |
| `get_llm_prices` | `main.py:4920` | `llm_providers.py:215` | **still**: steht in `try/except Exception: pass` (4924-4925) → Kostenanzeige bleibt 0/unbekannt, keine Spur |
| `parse_docker_stream_bytes` | `main.py:8936` | `utils/docker_client.py:250` | **hart**: kein try, Endpunkt „Datei aus Container lesen" → 500. Der Nachbaraufruf `main.py:8889` nutzt korrekt `parse_docker_stream`, importiert in `main.py:27` |

Die beiden letzten sind nicht Teil des P2-Mandats (kein Gate), gehoeren aber in
dieselbe Klasse und in dieselbe Nachpruefung.
