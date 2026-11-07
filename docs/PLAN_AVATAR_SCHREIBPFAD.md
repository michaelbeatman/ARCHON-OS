# Plan: Avatar-Schreibpfad aus dem versionierten Verzeichnis holen

**Status: Analyse + Plan. Keine Code-Änderung, kein Commit.**
Repo `/mnt/raid/AgenticOS-2026` · Branch `refactor/a5-di-config` @ `cb90a157`
Erstellt am 2026-11-07 · Grundlage: Messungen dieser Session (Befehle im Abschnitt 1.3)

---

## 1. Befund

### 1.1 Was passiert

Die Laufzeit **materialisiert** Profil-Avatare aus `data:`-URIs in
`APP_ROOT/static/avatars/`. Dieses Verzeichnis ist **versioniert**. Folge: Nach
Profil-Lesen (Cache-Miss, u. a. nach jedem Start/Recreate durch den ersten
Frontend-Request) stehen getrackte PNGs als `M` im Working Tree.

Gemessen in dieser Session (`git status --short`):

```
 M static/avatars/custom_competitive_intelligence_scout.png
 M static/avatars/custom_construction_project_manager.png
 M static/avatars/custom_devops_cloud_sec_specialist.png
 M static/avatars/custom_labor_law_hr_governance.png
```

Byte-Diffs sind echte Bildwechsel, kein Metadaten-Rauschen:

```
custom_competitive_intelligence_scout.png | Bin 420196 -> 422493 bytes
custom_construction_project_manager.png   | Bin 877882 ->  41214 bytes
custom_devops_cloud_sec_specialist.png    | Bin  39353 -> 346698 bytes
custom_labor_law_hr_governance.png        | Bin 133712 ->  55952 bytes
```

Betroffen sind **9** getrackte `custom_*`-Dateien (`git ls-files 'static/avatars/custom_*'`),
nicht nur die vier oben — die anderen fünf sind aktuell byte-gleich und daher still.

### 1.2 Warum überhaupt geschrieben wird

`profile.yaml` ist die Quelle der Wahrheit und hält den Avatar als Base64-`data:`-URI
(`archon/core/profiles.py:28-35`, Kommentar). Beim Auflisten der Profile wird dieser Wert
dekodiert und als Datei abgelegt, damit die Listen-Antwort nicht 1,25 MB Base64 je Profil
enthält. Schreibbedingung: **Bytes ungleich der vorhandenen Datei** → `tmp` + `os.replace`
(`profiles.py:73-85`). Ein identischer Lauf schreibt nicht neu (Idempotenz, getestet in
`tests/test_roles_cache_and_avatars.py:117-128`).

Belegt: alle vier Profile tragen einen `data:image`-Avatar in ihrer YAML
(`grep -nE "^\s*avatar(_url)?:" ~/.hermes/profiles/<id>/profile.yaml`):

| Profil | `profile.yaml:7` bzw. `:9` |
|---|---|
| `construction_project_manager` | `avatar: "data:image/png;base64,iVBOR…` |
| `labor_law_hr_governance` | `avatar: "data:image/png;base64,iVBOR…` |
| `competitive_intelligence_scout` | `avatar: data:image/png;base64,iVBOR…` |
| `devops_cloud_sec_specialist` | `avatar: data:image/png;base64,iVBOR…` |

### 1.3 Messbefehle dieser Session

```bash
git status --short
git diff --stat -- static/avatars
git ls-files 'static/avatars/custom_*' | wc -l          # 9
grep -rn "static/avatars" --include=*.py . --exclude-dir=.venv
grep -rn "avatars_dir\|avatar_dir\|AVATARS_DIR" --include=*.py . --exclude-dir=.venv
grep -n "StaticFiles\|mount(" main.py
git log -S "!static/avatars" --oneline -- .gitignore
git show 75fbad49 -- .gitignore
docker exec ARCHON-OS sh -c 'ls -ld /opt/data/webui 2>/dev/null'   # fehlt
ls -ld ~/.hermes/webui ~/.hermes/webui/static_avatars               # fehlt
```

---

## 2. Inventur der Pfade

### 2.1 Schreibstellen (3)

| Ort | Was | Detail |
|---|---|---|
| `archon/core/profiles.py:46-48` | **Definition des Ziels** | `avatars_dir() -> os.path.join(APP_ROOT, "static", "avatars")` |
| `archon/core/profiles.py:70-86` | **Schreiben** | `materialize_data_uri_avatar()`: `makedirs`, `tmp` schreiben, `os.replace`, Rückgabe `/static/avatars/custom_<id><ext>` |
| `archon/routers/hermes_profiles.py:206-212` | **Schreiben** | in `api_save_hermes_profile` (`POST /api/hermes/profiles`), Base64-Avatar → Datei |
| `archon/routers/hermes_profiles.py:426-432` | **Schreiben** | in `api_upload_hermes_profile_avatar` (`POST /api/hermes/profiles/{profile_id}/avatar`) |

Die beiden Router-Stellen sind **Duplikate** der Materialisierung (eigene Base64-Dekodierung,
eigene `makedirs`, kein `tmp`+`replace`, kein Idempotenz-Check). Der Kommentar an
`hermes_profiles.py:203-205` und `:424-425` dokumentiert einen früheren Fehler
(`archon/routers/static/avatars`, nie ausgeliefert) und dass man auf `avatars_dir()`
vereinheitlicht hat — **das Ziel blieb aber im versionierten Baum.**

### 2.2 Lesestellen (Dateisystem)

| Ort | Art | Detail |
|---|---|---|
| `archon/core/profiles.py:275` | Existenzprüfung | Fallback-Erkennung `custom_<id><ext>` in `avatars_dir()` |
| `archon/routers/hermes_profiles.py:227` | Existenzprüfung | gleiche Fallback-Erkennung beim Speichern |
| `archon/routers/hermes_profiles.py:377` | Präfix-Test | `clean_avatar.startswith("/static/avatars/")` (nur String) |
| `scripts/sync_avatars_db.py:58` | Lesen | erwartet Dateien unter **`/opt/data/webui/static_avatars/…`** — ein Laufzeitpfad, der heute **nicht existiert** |
| `scripts/process_and_sort_avatars.py:63` | Schreiben (Dev-Skript) | hartkodierter Windows-Pfad `c:\.Antigravity-projekte\…` — nicht produktiv |

### 2.3 Auslieferung (HTTP)

| Ort | Art | Detail |
|---|---|---|
| `main.py:10603` | **Mount** | `app.mount("/static", StaticFiles(directory="static"))` — relativ zum CWD (`/app`) = `APP_ROOT/static` |
| `main.py:138` | Middleware | `no-cache`-Header für `/static/avatars/*` |
| `main.py:10590` | Muster | `/builds/apps` wird **vor** `/static` gemountet — spezifischere Mounts zuerst, das ist der vorhandene Präzedenzfall |

### 2.4 Referenzen auf die URL (nicht auf das Dateisystem)

Diese Stellen speichern **URLs** `/static/avatars/…`; sie bleiben unverändert, solange die
URL gleich bleibt:

- `config/org_hierarchy.json` — 64 Avatar-URLs, davon 6 auf `custom_*`
- `static/js/*.js` (`agent_profiles.js`, `mission_control_cockpit.js`, `operations_kanban.js`,
  `chat_engine.js`, `prompt_studio.js`, `skill_markt.js`), `static/views/*.html`
- `backend/operations_api.py:114-118, 2124, 2138, 3877` — Fallback-URLs `avatar_NNN.jpg`
- `archon/routers/mission_control.py:136, 157`, `backend/jit_persona_engine.py:155`
- `tests/test_roles_cache_and_avatars.py:106-133` — prüft den **Dateipfad** (`tmp_path/static/avatars/…`)

**Konsequenz für beide Varianten:** Die URL `/static/avatars/<name>` muss erhalten bleiben.
Geändert wird nur, **aus welchem Verzeichnis** sie bedient wird.

---

## 3. Ursache

1. `avatars_dir()` hängt am **Projektwurzel-Pfad**: `APP_ROOT/static/avatars`
   (`profiles.py:48`). `APP_ROOT` ist das Repo selbst (`archon/core/runtime.py:31`), im
   Container `/app`, und `/app` ist der **Bind-Mount des Repos**
   (`docker-compose.dev.yml:18`: `/mnt/raid/AgenticOS-2026:/app`). Jeder Schreibvorgang
   landet damit unweigerlich im versionierten Baum.
2. `.gitignore` **hebt die Ignorier-Regel für genau dieses Verzeichnis auf**:
   `*.png` (Zeile 87) wird durch `!static/avatars/**` (Zeile 90) ausgehebelt — eingeführt in
   `75fbad49` („unignore custom profile avatars"), das im selben Commit vier der heute
   betroffenen PNGs hinzufügte. Die Entscheidung „Avatare sind versioniert" ist also
   **bewusst** getroffen worden, kollidiert aber mit der Laufzeit-Materialisierung.
3. **Es gibt bereits eine vorgesehene Stelle für Laufzeitdaten**, nur nicht für Avatare:
   - `data/` ist gitignoriert (`.gitignore:70`) und gemountet (`/app/data`),
   - `/opt/data` (= Host `~/.hermes`) ist der etablierte, beschreibbare Laufzeitspeicher
     (Container-UID 1000 = Host-UID 1000, `/opt/data` gehört `streamlituser`),
   - `scripts/sync_avatars_db.py:58` **erwartet Avatare schon unter
     `/opt/data/webui/static_avatars/`** — der Pfad existiert heute nicht, die Absicht aber
     ist im Code dokumentiert.
4. Ein reines `var/`-Verzeichnis gibt es heute nicht; `ansible/roles/archon_node/vars/main.yml:33`
   legt `{{ archon_install_root }}/static/avatars` an — das Provisioning bestätigt die
   Repo-Annahme und müsste bei beiden Varianten mitgezogen werden.

---

## 4. Variante A — Ziel im Repo, aber ungetrackt

**Neues Ziel:** `APP_ROOT/var/avatars/` (Host: `/mnt/raid/AgenticOS-2026/var/avatars/`,
Container: `/app/var/avatars/`).

| Aspekt | Umsetzung |
|---|---|
| Zielpfad | `avatars_dir()` → `os.path.join(APP_ROOT, "var", "avatars")`; neue Funktion `avatars_legacy_dir()` → `APP_ROOT/static/avatars` (nur lesend) |
| Betroffene Dateien | `archon/core/profiles.py` (Ziel + Materialisierung), `archon/routers/hermes_profiles.py` (2 Stellen → gemeinsame Funktion), `main.py` (Auslieferung), `.gitignore`, `ansible/roles/archon_node/vars/main.yml` |
| Auslieferung | **Neue Route** `GET /static/avatars/{filename}`, registriert **vor** `main.py:10603`: erst `var/avatars/<f>`, sonst `static/avatars/<f>` (Katalog der 300 `avatar_NNN.jpg` bleibt liegen). Ein zusätzlicher `app.mount("/static/avatars", …)` scheidet aus, weil er den gesamten Präfix übernimmt und den Katalog unsichtbar machen würde |
| Anlage | `os.makedirs(..., exist_ok=True)` beim Materialisieren (wie heute) + `mkdir -p var/avatars` im Startpfad/Ansible |
| `.gitignore` | `var/` ergänzen; `!static/avatars/**` **entfernen** (sonst bleiben neue Laufzeit-PNGs trackbar) |
| Getrackte PNGs | Die 9 `custom_*` per `git rm --cached` aus dem Index nehmen, **Dateien auf der Platte behalten** → sie dienen als Seed und als Lese-Fallback. Die 300 Katalog-`avatar_NNN.jpg` bleiben unverändert versioniert |
| Migration | Beim ersten Start: wenn `var/avatars/<f>` fehlt und `static/avatars/<f>` existiert → kopieren (nicht verschieben, damit Altstände weiter bedient werden) |
| Teststrategie | (a) Unit: `materialize_data_uri_avatar` schreibt nach `tmp/var/avatars`, **nie** nach `tmp/static/avatars`; (b) Unit: Fallback-Kette liefert bei fehlender Laufzeitdatei die Legacy-Datei; (c) Integration (beweisend): Materialisierung auslösen, danach `git status --short -- static/avatars` **leer** |
| Risiko | Mittel. Repo bleibt Bind-Mount → `var/` ist im Container sichtbar und beschreibbar, aber ein `git clean -xdf` löscht Laufzeit-Avatare. Zweiter Ort neben dem Katalog = mehr Erklärung im Code |

---

## 5. Variante B — Ziel ausserhalb des Repos

**Neues Ziel:** `HOST ~/.hermes/webui/static_avatars/` = im Container
`/opt/data/webui/static_avatars/` (genau der Pfad, den `scripts/sync_avatars_db.py:58`
bereits erwartet). Überschreibbar über `ARCHON_AVATARS_DIR`.

| Aspekt | Umsetzung |
|---|---|
| Zielpfad | `avatars_dir()` → `os.environ.get("ARCHON_AVATARS_DIR")` oder `/opt/data/webui/static_avatars` (Container) bzw. `~/.hermes/webui/static_avatars` (Host) — Auflösung wie bei `get_hermes_profiles_base_dirs()` (`profiles.py:92-110`) |
| Betroffene Dateien | dieselben wie A, **ohne** `.gitignore`-Ausnahme für `var/`, **ohne** Ansible-Verzeichnis ( `/opt/data` legt `.hermes` bereits an) |
| Auslieferung | gleiche Route wie A, nur erste Stufe = `avatars_dir()`, zweite Stufe = `APP_ROOT/static/avatars` |
| Anlage | `makedirs` wie heute; Verzeichnis wird beim ersten Schreiben erzeugt |
| Getrackte PNGs | Die 9 `custom_*` per `git rm --cached` **plus** `git rm` (aus dem Baum entfernen) — das Repo wird reines Artefakt. Restrisiko: frische Installation ohne `profile.yaml` hat dann keinen Custom-Avatar → Fallback `avatar_NNN.jpg` (heutiges Verhalten ohne Datei) |
| Migration | Beim ersten Start: vorhandene 9 PNGs aus dem Repo einmalig nach `avatars_dir()` kopieren, **danach** aus Git entfernen. Reihenfolge zwingend (sonst fehlt das Bild) |
| Teststrategie | wie A, plus: Test, dass `avatars_dir()` **nicht** unter `APP_ROOT` liegt; Test, dass `ARCHON_AVATARS_DIR` greift |
| Risiko | Niedriger im Repo (nichts Versioniertes wird beschrieben), aber **höher im Betrieb**: Avatar-Lebensdauer hängt an `/opt/data` (= `~/.hermes`). Ein Neuaufsetzen ohne dieses Verzeichnis verliert Custom-Avatare, bis sie aus `profile.yaml` neu materialisiert werden. Schreibrechte: Container-UID 1000 == Host-UID 1000, `/opt/data` gehört `streamlituser` — **belegt durch `ls -ld /opt/data`**, aber unter einem anderen Deploymentschema (andere UID) neu zu prüfen |

---

## 6. Vergleich

| Kriterium | A (`var/avatars`) | B (`/opt/data/webui/static_avatars`) |
|---|---|---|
| Repo bleibt artefaktfrei | teilweise (Pfad im Repo, aber ungetrackt) | **ja** |
| Überlebt `git clean -xdf` | nein | **ja** |
| Überlebt Neuaufsetzen des Hosts ohne `~/.hermes` | **ja** (im Repo) | nein |
| Passt zur bestehenden Konvention | neu (`var/` existiert nicht) | **ja** (`sync_avatars_db.py` erwartet ihn) |
| Bind-Mount-/UID-Risiko | keins (schon gemountet) | muss je Deployment geprüft werden |
| Aufwand | 5 Dateien + Ansible | 4 Dateien |

---

## 7. Empfehlung

**Variante B** — sie folgt der im Code bereits dokumentierten Absicht
(`sync_avatars_db.py:58`), macht das Repo zum reinen Artefakt und beseitigt die
`git status`-Verschmutzung an der Wurzel statt sie nur umzubenennen.

**Umsetzungsreihenfolge (jede Stufe mit eigenem Beweis):**

1. `archon/core/profiles.py` — `avatars_dir()` auf den Laufzeitpfad umstellen,
   `avatars_legacy_dir()` als Lese-Fallback ergänzen. **Zuerst**, weil alle anderen Stellen
   diese Funktion rufen.
2. `archon/routers/hermes_profiles.py:206-212` und `:426-432` — die beiden Duplikate durch
   `materialize_data_uri_avatar()` ersetzen (ein Schreibpfad statt drei).
3. `main.py` — Route `GET /static/avatars/{filename}` vor dem `/static`-Mount, Kette
   Laufzeit → Legacy. Parität 585/861 muss unverändert bleiben (Route ersetzt keinen
   bestehenden Pfad; `openapi`-Baseline prüfen).
4. Migration: Kopierschritt Repo → Laufzeitverzeichnis beim Start (einmalig, idempotent).
5. `git rm --cached` der 9 `custom_*` (Dateien bleiben zunächst), danach separat entscheiden,
   ob sie aus dem Baum entfernt werden.
6. `tests/test_roles_cache_and_avatars.py` anpassen (monkeypatcht heute `APP_ROOT`).

**Der beweisende Test** ist kein Unit-Test, sondern diese Zeile nach einer echten
Materialisierung:

```bash
.venv/bin/python -c "…"            # oder: Frontend-Request auf /api/hermes/profiles
git status --short -- static/avatars   # muss leer sein
```

Erst wenn das leer ist, ist der Befund geschlossen. Ein grüner Unit-Test mit
`tmp_path` beweist nur, dass der Pfad umgebogen wurde.

---

## 8. Was dieser Plan nicht anfasst

- **Die Avatar-Inhalte selbst** — keine Datei wird verschoben, gelöscht oder neu kodiert.
  Die 9 PNGs bleiben auf der Platte; über den Git-Index entscheidet erst Stufe 5.
- **Die API-Verträge von `archon/routers/hermes_profiles.py`** — Response-Formen,
  Statuscodes, Feldnamen und die zurückgegebenen `/static/avatars/…`-URLs bleiben gleich.
- **`docker-compose.hermes.yml`** und alles, was diese Session dort geändert hat
  (`cb90a157`, `1d170a92`) — nicht angefasst, nicht bewertet.
- **`main.py:138`** (`no-cache`-Middleware) — bleibt, der URL-Präfix ändert sich nicht.

## 9. Nicht geprüft (bewusst offen)

- Ob ein `StaticFiles`-Mount mit `check_dir=False` gegenüber der Route die bessere Wahl ist —
  die Route ist gewählt, weil sie die Zwei-Quellen-Kette abbilden kann.
- Verhalten mehrerer gleichzeitiger Schreibvorgänge auf dieselbe Datei (heute: `tmp` +
  `os.replace` nur in `profiles.py`, die beiden Router-Stellen schreiben direkt).
- Ob `/opt/data/webui` unter anderen Deployment-Schemata (andere UID, kein `~/.hermes`-Mount)
  beschreibbar ist — hier belegt für **diese** Installation, nicht allgemein.
- Ob die 5 byte-gleichen `custom_*`-PNGs bei einem Bildwechsel ebenfalls als `M` auftauchen
  werden — erwartbar ja, gemessen ist es nur für die vier oben.
