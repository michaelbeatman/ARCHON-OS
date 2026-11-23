"""Optionale Test-DB-Isolation (W6).

Problem: pytest (Windows-Host) und der laufende ARCHON-OS-Container (Linux)
schreiben bei Bind-Mounts gleichzeitig WAL auf dieselben Dateien unter
``./data/*.db``. Am 23.11.2026 führte das zu einer korrumpierten
``data/memory.db``.

Lösung: wenn ``ARCHON_TEST_DB_ISOLATION=1`` gesetzt ist, zeigt
``backend.db_paths.APP_DATA_DIR`` (und damit der gesamte DB-Resolver inkl.
Tenant-Isolation) auf ein frisches temporäres Verzeichnis. Der Container
greift weiterhin auf das echte ``./data`` zu — es gibt keinen Konflikt mehr.

Das muss VOR dem Import von App-Modulen passieren; conftest wird von pytest
vor der Test-Kollektion geladen. Standardmäßig AUS, damit die bestehende
Testsuite unverändert bleibt.

Aufruf:  .\scripts\run_tests_isolated.ps1
    oder: $env:ARCHON_TEST_DB_ISOLATION=1; python -m pytest tests/ -q
"""

import atexit
import os
import shutil
import tempfile

_FLAG = os.getenv("ARCHON_TEST_DB_ISOLATION", "").strip().lower()
if _FLAG in ("1", "true", "yes", "on"):
    _test_data_dir = tempfile.mkdtemp(prefix="archon_test_data_")
    os.environ["ARCHON_DATA_DIR"] = _test_data_dir
    atexit.register(lambda: shutil.rmtree(_test_data_dir, ignore_errors=True))
    print(f"[conftest] Test-DB-Isolation aktiv: {_test_data_dir}")
