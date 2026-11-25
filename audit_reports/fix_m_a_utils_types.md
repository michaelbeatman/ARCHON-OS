# Fix M-A — echte MyPy-Typfehler in `utils/**` (25.11.2026)

> Quelle: Full-Run `audit_reports/mypy_full_stdout.txt` (alle 27 Zeilen mit `utils\`).
> Methodik: `audit_reports/fix_d2_mypy.md` — echte Annotationen/`cast`/Narrowing,
> wo nötig gezielte codierte Ignores mit kurzer Begründung, **keine Laufzeitänderung**.
> Exklusives Datei-Ownership eingehalten: **nur** die fünf zugewiesenen Dateien in
> `utils/`. Keine Änderung an `backend/**`, `scripts/**`, `mypy.ini`, Tests oder `data/**`.

## 1. Zahlen (exakt)

| Metrik | Vorher | Nachher |
|---|---:|---:|
| MyPy-Fehler in den fünf `utils/`-Dateien | **27** | **0** |
| Betroffene Dateien | 5 | 5 |
| Neue echte Typannotationen (ohne Laufzeitwirkung) | — | **6 Zeilen** |
| Gezielte `# type: ignore[attr-defined]` (neu/korrigiert) | — | **4 Zeilen** |

Verteilung:

| Datei | Fehler vorher | Fehler nachher | Art der Auflösung |
|---|---:|---:|---|
| `utils/egress_guard.py` | 14 | 0 | 2 Klassen-/Parameter-Annotationen |
| `utils/safe_http.py` | 7 | 0 | 1 Liste-Annotation + 3 korrigierte/neue codierte Ignores |
| `utils/repo_sync.py` | 3 | 0 | 1 Dict-Annotation, 2 `Optional`-Signaturen |
| `utils/skill_marketplace.py` | 2 | 0 | 2 `Optional`-Signaturen |
| `utils/docker_client.py` | 1 | 0 | 1 codierter Ignore (POSIX-Pfad) |

## 2. Auflösungen im Detail

### `utils/egress_guard.py` (14 → 0)
- `ValidatedURL` (3 Fehler): die in `__new__` gesetzten Instanzattribute
  `pinned_ip` / `validated_ip` wurden als Klassenannotationen deklariert
  (`pinned_ip: str`, `validated_ip: str`). Reine Typdeklaration; die
  Attributzuweisungen im `__new__` bleiben unverändert.
- `_target_ip_allowed` / `_reject_if_internal` (11 Fehler): die Parameter waren
  als `ipaddress._BaseAddress` annotiert. Diese Basisklasse führt die
  `is_loopback` / `is_link_local` / `is_multicast` / `is_unspecified` /
  `is_private` / `is_reserved`-Flags nicht. `ipaddress.ip_address()` liefert
  laut typeshed `IPv4Address | IPv6Address` — genau die konkreten Klassen mit
  den Flags. Die Parameter wurden entsprechend auf
  `ipaddress.IPv4Address | ipaddress.IPv6Address` geändert. Alle Aufrufer
  übergeben bereits diesen Typ, daher kein neuer `arg-type`-Fehler. Kein
  `cast` nötig, kein Ignore.

### `utils/safe_http.py` (7 → 0)
- `_verify_pinned_peer` (2 Fehler): der alte Ignore `# type: ignore[union-attr]`
  war ungenutzt (`warn_unused_ignores`), weil mypy das Mixin isoliert prüft und
  `sock` dort gar nicht deklariert ist → `attr-defined`. Ignore auf
  `[attr-defined]` korrigiert, mit Begründung, dass `sock` von
  `HTTPConnection`/`HTTPSConnection` kommt. (Ein `sock: Optional[...]` auf dem
  Mixin hätte einen `union-attr`-Fehler erzeugt; eine `close()`-Deklaration
  hätte wegen der MRO die echte `close()` überschattet — beides wäre eine
  Laufzeitänderung.)
- `_PinnedHTTPSConnection.connect` (2 Fehler): `_tunnel_host` wird von
  `set_tunnel()` und `_context` von `HTTPSConnection.__init__` zur Laufzeit
  gesetzt, sind aber nicht in typeshed deklariert. Zwei gezielte
  `# type: ignore[attr-defined]` mit Datums-/Grund-Kommentar.
- `safe_http_request` (3 Fehler): `handlers = []` wurde durch den ersten
  `append` auf `list[ProxyHandler]` fixiert, danach scheiterten die übrigen
  Handler. Annotation `handlers: list[urllib.request.BaseHandler] = []`
  (alle Handler erben von `BaseHandler`). Reine Annotation.

### `utils/repo_sync.py` (3 → 0)
- `_CACHE = {}` → `_CACHE: dict[str, list] = {}`.
- `search: str = None` / `category: str = None` → `Optional[str] = None`
  (mit `from typing import Optional`), passend zu `no_implicit_optional = True`
  und zum tatsächlichen Default `None`.

### `utils/skill_marketplace.py` (2 → 0)
- Identische `Optional[str]`-Korrektur für `search` / `category` in
  `list_skills_for_source`.

### `utils/docker_client.py` (1 → 0)
- `socket.AF_UNIX` existiert auf der Windows-Typeshed nicht, der Pfad ist
  POSIX-only. Gezielter `# type: ignore[attr-defined]` mit kurzer Begründung
  statt `getattr(socket, "AF_UNIX")` (das wäre eine Laufzeitänderung).

## 3. Verifikation (selbst ausgeführt, 25.11.2026)

| Gate | Kommando | Ergebnis |
|---|---|---|
| MyPy (Scope) | `.venv\Scripts\mypy.exe --config-file mypy.ini --no-pretty utils/egress_guard.py utils/safe_http.py utils/repo_sync.py utils/skill_marketplace.py utils/docker_client.py` | **Success: no issues found in 5 source files** (0 errors) |
| Syntax | `.ci_venv\Scripts\python.exe -m compileall -q utils` | **Exit 0** (keine Ausgabe) |
| Regressionstests | `.ci_venv\Scripts\python.exe -m pytest -q --tb=short <14 Testdateien, siehe unten>` | **320 passed, 3 skipped** (53,00 s) |

Getestete Dateien (alle mit Bezug zu den fünf geänderten Modulen):
`test_egress_guard.py`, `test_fix_w4_b_integrations.py`, `test_fix_w2_b_silent.py`,
`test_fix_batch12.py`, `test_phase1_security_and_p0_fixes.py`,
`test_audit_fixes_batch.py`, `test_docker_client.py`, `test_docker_admin_client.py`,
`test_critical_hardening.py`, `test_fix_batch10.py`, `test_p7_hermes_core_targets.py`,
`test_stage1_stage3_hardening_and_bus.py`, `test_p2_plagiarism_gate.py`,
`test_cluster3_hardening.py`.

`ARCHON_DATA_DIR` war ausschliesslich das frische Temp-Verzeichnis
`C:\Users\micha\AppData\Local\Temp\archon-m-a-utils-ac23eb3c257447d5b7c3ce32fa7d1c6f`.
`./data/**` wurde von diesem Fix nicht beschrieben.

## 4. Befunde / Ausnahmen

1. **Keine Laufzeitänderung.** Alle Änderungen sind Annotationen, Typdeklarationen
   oder Ignore-Kommentare. Kontrollfluss, Defaults, Host-Pinning, Redirect-Block
   und Allowlist-Logik sind unverändert.
2. **Vier codierte Ignores**, alle mit kurzer Begründung im Code: drei in
   `safe_http.py` (von `http.client` bereitgestellte, nicht in typeshed
   deklarierte Attribute) und einer in `docker_client.py` (`AF_UNIX` nur auf
   POSIX). `warn_unused_ignores = True` bleibt erfüllt — der ursprünglich
   ungenutzte Ignore in `safe_http.py:68` wurde auf den richtigen Code
   korrigiert.
3. **Parallele Arbeit anderer Agenten** in `backend/**` und `scripts/**` wurde
   nicht angefasst; die MyPy-Verifikation lief bewusst nur über die fünf
   eigenen Dateien.
