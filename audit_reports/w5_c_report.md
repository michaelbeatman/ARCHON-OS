# W5-C — System-Härtung & Resilienz (Partition C)

> **Welle/Partition:** W5-C · **Branch:** `main`, HEAD bei Übergabe `65e0f4d9` ·
> **Funde:** D10-M3, D10-M4, D10-M5, D10-M6, D10-M8 · **Sprache:** Deutsch.
> **Dateibesitz strikt eingehalten:** nur `ansible/**`, `docker-compose.yml`,
> `deploy/docker-socket-proxy/haproxy.cfg`, die drei `.bat`-Starter,
> `tests/test_w5_c_hardening.py` und dieser Report. Keine Python-/JS-Datei
> anderer Partitionen verändert. **Kein Commit, kein `git add`.**

## 0. Randbedingungen

- `docs/system/NEVER_DO_LIST.md` hat Vorrang: **kein** PostgreSQL/DSN/Migration,
  **kein** Coroutine-/Event-Replay, **keine** eigene Content-Domäne. Keiner der
  Fixes berührt diese Punkte.
- Shell ist in Subagent-Sessions häufig gesperrt (`pwsh.exe: Zugriff verweigert`).
  Alle Änderungen wurden **statisch** mit `read`/`edit`/`write` erstellt.
  **Der Koordinator verifiziert zentral** (Ruff/MyPy/Pytest, `docker compose
  -f docker-compose.yml config`, `haproxy -c`).
- Keine Secrets und keine `sk-<Zeichen>`-Strings in Tests; keine `# noqa`-Zeile,
  die einen String öffnet.
- `.gitignore:55` (`**/*report*`) → dieser Report braucht beim Commit `git add -f`.

---

## 1. D10-M3 (MED 7) — DR aus Observability entkoppeln

**Ist:** `archon_observability: "off"` (Normal-Start) gatte beide 6-h-Cronjobs
(`ansible/roles/archon_node/tasks/main.yml`) und das Litestream-Profil
(`docker-compose.yml`) hinter `full`. Im Default-Deploy liefen weder
Replikation noch Restore- noch Chaos-Test — der 6-h-Restore-Test war nur Doku.

**Fix:**

| Datei | Änderung |
|---|---|
| `ansible/roles/archon_node/vars/main.yml` | Neuer Schalter `archon_dr_enabled: true` (Default aktiv). Opt-out nur bewusst für isolierte Entwicklungs-Hosts. |
| `ansible/roles/archon_node/tasks/main.yml` | Warn-/Stat-/Abort-Tasks für das DR-Ziel sowie **beide** Cronjobs jetzt an `archon_dr_enabled | bool` statt an `archon_observability == "full"`. Neuer `config --quiet`-Gate vor dem Stack-Start. `COMPOSE_PROFILES` setzt `replication` aus `archon_dr_enabled`, Observability bleibt `full`-Opt-in. `up` ergänzt `--scale litestream=0` nur beim Opt-out. Neuer hartes `failed_when`: `docker compose ps --services` muss `litestream` zeigen. |
| `docker-compose.yml` | `litestream` hat **kein** `profiles:`-Gate mehr → Default-Dienst wie `archon-autoheal`. Ohne `ARCHON_LITESTREAM_REPLICA_DIR` bewusst lokales `./dr_replicas` (Entwicklung). |

**Effekt/Nachweis (§0):** Der Ansible-Default-Deploy (`archon_observability: off`)
plant `crontab -l` beide Jobs und `docker ps` zeigt `litestream`. Der
Regressionstest prüft statisch die echte Rolle und den echten Compose-Dienst.

---

## 2. D10-M4 (MED 6) — Dead-Man-Switch mit Konsument + unabhängiger Heartbeat

**Ist:** `ARCHON_HEARTBEAT_WEBHOOK_URL` hatte leeren Default; Prometheus
(`config/prometheus/alerts.yml`, Partition B) wurde ohne Profil nicht deployt;
`backend/fleet_self_healing.py` setzte `dead_man_switch_configured` nur bei
erreichbarem Empfänger und loggte sonst eine Warnung. Der Heartbeat lief im
30-s-Deadlock-Loop — Sender und Prüfer hängen gemeinsam.

**Fix im Besitz dieser Partition:**

| Datei | Änderung |
|---|---|
| `docker-compose.yml` | `ARCHON_HEARTBEAT_WEBHOOK_URL=${ARCHON_HEARTBEAT_WEBHOOK_URL:?...}` als **Pflicht-Env** in `archon-os` **und** `archon-autoheal`. Fehlt/leer die Variable, bricht `docker compose config/up` hart ab (`§0`: Fail-Fast statt `dead_man_switch_configured: false`). Kein erfundenes Ziel — der Betreiber trägt die URL in `.env` ein. |
| `ansible/roles/archon_node/tasks/main.yml` | `docker compose -f … config --quiet` als Deploy-Gate **vor** dem Stack-Start. Neuer Cron `archon-deadman-heartbeat` (`*/5`): posted einen `ok` direkt aus der `.env` (URL nie in `crontab -l`), **unabhängig vom überwachten 30-s-Loop**. |
| `ansible/roles/archon_node/vars/main.yml` | `archon_deadman_enabled: true`. |

**Abhängigkeit an andere Partitionen (nicht in meinem Besitz, nicht verändert):**

- `config/prometheus/alerts.yml` (W5-B): Regeln `ArchonHeartbeatStale` /
  `ArchonHeartbeatMetricAbsent` sind korrekt, bleiben aber ohne Prometheus-Profil
  wirkungslos. Der externe Cron-Heartbeat ist der zweite, unabhängige Kanal;
  die Metrik muss weiterhin im `full`-Profil ausgewertet werden.
- `backend/metrics_collector.py` / `background_loops.py` (nicht in W5-C): der
  Prometheus-Heartbeat wird weiterhin aus `check_and_dispatch_alerts_now()`
  im 30-s-Deadlock-Loop geschrieben. Der unabhängige Prometheus-seitige
  Heartbeat-Thread ist dort nachzurüsten; der Cron ersetzt ihn betrieblich,
  nicht semantisch. Bitte vom Koordinator zentral einplanen.
- `.env.example` (nicht in meinem Besitz): sollte einen **neutralen**
  Platzhalter für `ARCHON_HEARTBEAT_WEBHOOK_URL` dokumentieren, sonst bleibt der
  neue `:?`-Gate für Erstinstallationen hart. Bewusst gewollt: ohne echten
  Empfänger kein Produktiv-Deploy.

---

## 3. D10-M5 (MED 7) — Socket-Proxy härten, Allowlist verengen

**Ist:** `docker-socket-proxy` (roher, auch nur `ro` gemounteter Docker-Socket)
war das einzige Element ohne `user`/`read_only`/`cap_drop`/`no-new-privileges`.
Die Ziel-Regex `[A-Za-z0-9_.-]+` erlaubte **jeden** Container im Admin-Netz
(inkl. `hermes`, `promtail`).

**Fix:**

| Datei | Änderung |
|---|---|
| `docker-compose.yml` | `init: true`, `user: ${SOCKET_PROXY_UID:-1000}:${SOCKET_PROXY_GID:-1000}`, `read_only: true`, `cap_drop: [ALL]`, `security_opt: ["no-new-privileges:true"]`, `pids: 128`, tmpfs für `/run`, `/tmp`, `/var/lib/haproxy` (pidfile/state-file bleiben beschreibbar, Image non-root-kompatibel: Port 2375 > 1024). |
| `deploy/docker-socket-proxy/haproxy.cfg` | Alle Container-Ziel-Regexe von `[A-Za-z0-9_.-]+` auf die im Repo tatsächlich genutzten Namen verengt: `ARCHON-OS`, `hermes`, `hermes-agent`, `hermes-dashboard-proxy`, `archon-autoheal`, `omniroute`, `anything-llm`, `n8n`, `ef47f1b25a78_CRM`, `freellmapi` plus hexadezimale Docker-IDs `[A-Fa-f0-9]{12,64}`. Exec-Pfade nur noch hex IDs. `create`/`rename` zusätzlich an `?name=<erlaubter Name>` gebunden (ACL `proxy_managed_name`), DELETE weiterhin nur `_old_backup`. Methoden-Whitelist und abschließendes `http-request deny` bleiben aktiv. |

**Hinweis:** `ARCHON_FLEET_EXTRA_CONTAINERS` (`backend/fleet_self_healing.py`)
ermöglicht zusätzliche Namen nur im Aufrufer. Ein solcher Name wird jetzt auch
an der Proxy-Aussenkante blockiert; er muss dort explizit in die Regex
aufgenommen werden. Das ist die beabsichtigte Einengung (Audit §2.1).

**Nachweis:** `docker compose -f docker-compose.yml config` zeigt die Flags;
`haproxy -c -f deploy/docker-socket-proxy/haproxy.cfg` muss 0 liefern; ein
Probe-Request aus `hermes` auf `/containers/<fremd>/stop` liefert 403.

---

## 4. D10-M6 (MED 6) — Drei Starter: Override-Bypass schließen

**Ist:** `archon-os-rebuild.bat`, `archon-os-neu-starten.bat` und
`scripts/update_archon.bat` riefen `docker compose build/up` **ohne `-f`**.
Bei lokal vorhandener, gitignorierter `docker-compose.override.yml` merged
Compose diese automatisch → `./:/app` bind-mounted die `.env` mit dem
Audit-HMAC-Key in den Container und shadowed den Image-Code.

**Fix:** In allen drei Skripten vorher
`docker compose -f docker-compose.yml config --quiet` als hartes Gate und
jeder Compose-Aufruf auf `-f docker-compose.yml` umgestellt. `start.bat`,
`install.sh`, `setup.ps1`, `stop.bat` und die Ansible-Rolle nutzten bereits die
explizite Datei und bleiben unberührt.

**Nachweis:** `docker compose -f docker-compose.yml config | Select-String ':/app$'`
liefert 0 Treffer; `docker compose exec archon-os test -f /app/.env` → Exit 1.
Der Regressionstest prüft statisch **jede** `docker compose`-Zeile der drei
Starter auf `-f docker-compose.yml`.

---

## 5. D10-M8 (MED 6) — Worker-Netz prüfbar + Vertrag an `/readyz`

**Ist:** `NETWORKS=0` verweigerte `docker network inspect`. Der Startup-Hook
(`backend/llm_egress_guard.py::ensure_worker_zero_egress_network`) ignorierte
den Exitcode und lieferte `exists=False` zurück; `/readyz` blieb trotz
nicht verifizierter Zero-Egress-Isolation grün.

**Fix im Besitz dieser Partition:**

| Datei | Änderung |
|---|---|
| `docker-compose.yml` | `NETWORKS=1` im Proxy (statt 0). |
| `haproxy.cfg` | Der breite Subtree `/networks(/.*)?$` ist ersetzt durch zwei exakte, lesende Regeln: `GET /networks` und `GET /networks/<archon-worker-zero-egress_net\|archon-sandbox_net\|archon-admin_net\|hex-ID>/json`. Damit ist `docker network inspect` aus dem Archon-Container möglich, ohne `/networks/create`/`connect`/`delete` zu öffnen. |
| `ansible/roles/archon_node/tasks/main.yml` | Neuer harter Post-Deploy-Gate: `docker compose -f … exec -T archon-os python -c …` inspiziert `archon-worker-zero-egress_net` **über den Proxy** und beendet das Deployment mit Fehler, wenn das Netz fehlt oder `Internal != true`. |

**Vertrag an die Backend-Partition (dokumentiert, nicht verändert):**

`backend/llm_egress_guard.py::ensure_worker_zero_egress_network()` muss
`exists=False` **oder** `internal_no_internet_route=False` künftig als
`RuntimeError` an den Startup-Hook zurückmelden (statt nur
`inspect_worker_network_isolation()` zu returnen), damit `/readyz` 503
liefert. `backend/ephemeral_sandbox.py::_ensure_sandbox_network()` fail-closed
bereits korrekt (Comment `NETWORKS=0` dort ist jetzt veraltet und darf von
Partition B/F bereinigt werden). Der lesende Proxy-Pfad steht ab W5-C zur
Verfügung; der Sandbox-Lauf mit `zero_egress_worker_net=True` ist damit im
Default-Stack ausführbar.

---

## 6. Verifikation & Abnahme

- Regressionstests: `tests/test_w5_c_hardening.py` — 5 Tests, eine pro Fund,
  ausschließlich statische Produktivpfad-Prüfung der echten Dateien.
- Vom Koordinator zentral zu verifizieren (Subagent-Shell gesperrt):
  ```powershell
  $env:ARCHON_TEST_DB_ISOLATION='1'
  .venv\Scripts\python.exe -m pytest tests/test_w5_c_hardening.py -q
  .venv\Scripts\python.exe -m ruff check --select E,F,I --ignore E501 tests/test_w5_c_hardening.py
  .venv\Scripts\python.exe -m mypy --config-file mypy.ini tests/test_w5_c_hardening.py
  docker compose -f docker-compose.yml config --quiet
  docker compose -f docker-compose.yml config | Select-String ':/app$'
  ```
  Zusätzlich (eigene Deploy-Umgebung, bewusst nicht in Subagent-Shell):
  `haproxy -c -f deploy/docker-socket-proxy/haproxy.cfg`.
- Für Report-Commit: `git add -f audit_reports/w5_c_report.md` (Koordinator).
- `GEWICHTETE_BEFUNDLISTE.md`-Status und `git commit` erfolgen ausschließlich
  durch die Haupt-Session.
