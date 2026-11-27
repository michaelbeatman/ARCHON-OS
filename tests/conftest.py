r"""Optionale Test-DB-Isolation (W6).

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
import sys
import tempfile
from typing import Any, Dict

import pytest

# main._assert_audit_hmac() ist jetzt fail-closed, sobald HMAC-Bloecke in der
# (dev-)DB existieren. Tests brauchen einen deterministischen, nicht-echten
# Key — sonst bricht der App-Lifespan beim ersten Test-Client ab.
os.environ.setdefault("ARCHON_AUDIT_HMAC_KEY", "test-only-" + "a" * 64)


@pytest.fixture(autouse=True)
def _reset_graceful_shutdown_gate():
    """Test-Isolation fuer den zentralen Draining-Gate (P0, 23.11.2026).

    Einige Tests fahren die App ueber den Lifespan-Shutdown herunter; dabei
    ruft ``on_shutdown_graceful()`` den Singleton-Coordinator auf und laesst
    ihn im Draining-Zustand. Seit ``main._spawn_background()`` das Gate
    ``can_start_task()`` wirklich auswertet, wuerde dieser Zustand in den
    naechsten Test hineinwirken und dort Background-Tasks blockieren.
    """
    try:
        from backend.graceful_shutdown_coordinator import graceful_shutdown_coordinator as _coord

        if _coord.is_draining:
            _coord.cancel_draining()
    except Exception:
        pass
    yield
    try:
        from backend.graceful_shutdown_coordinator import graceful_shutdown_coordinator as _coord

        if _coord.is_draining:
            _coord.cancel_draining()
    except Exception:
        pass


_TEST_ADMIN_USER: Dict[str, Any] = {
    "id": "usr_test_admin",
    "username": "test-actor",
    "display_name": "Test Admin",
    "role": "admin",
    "permissions": ["*"],
    "is_service": False,
    "auth_enabled": False,
}


@pytest.fixture
def admin_rbac_bypass(monkeypatch: pytest.MonkeyPatch) -> Dict[str, Any]:
    """Explizite (nicht-autouse) Fixture fuer Tests, die Fachlogik hinter
    fail-closed Auth-/RBAC-Guards pruefen.

    Patched sauber via ``monkeypatch`` (automatisches Teardown nach dem Test):
    - ``archon.routers._rbac`` (``_checker``, ``require_admin_or_503``,
      ``forbid_viewer_writes``, ``require_session_actor``)
    - ``archon.routers.auth`` (``get_current_user_from_request``, ``require_admin``)
    - ``backend.rbac_guards`` (``_GUARDS``-Registry und Modul-Wrapper)
    - ``backend.auth_service.auth_service.is_auth_enabled`` (fuer ``auth_gate``-Middleware)
    - bereits importiertes ``main``-Modul (inkl. ``app.dependency_overrides``)
    """
    from archon.routers import _rbac
    from archon.routers import auth as auth_router
    from backend import rbac_guards
    from backend.auth_service import auth_service

    def _allow_admin(_request: Any = None) -> None:
        return None

    def _allow_write(_request: Any = None) -> None:
        return None

    def _admin_user(_request: Any = None) -> Dict[str, Any]:
        return dict(_TEST_ADMIN_USER)

    def _session_actor(_request: Any = None) -> str:
        return "test-actor"

    orig_forbid_viewer_writes = _rbac.forbid_viewer_writes

    monkeypatch.setattr(_rbac, "_checker", _allow_admin)
    monkeypatch.setattr(_rbac, "require_admin_or_503", _allow_admin)
    monkeypatch.setattr(_rbac, "forbid_viewer_writes", _allow_write)
    monkeypatch.setattr(_rbac, "require_session_actor", _session_actor)

    monkeypatch.setattr(auth_router, "get_current_user_from_request", _admin_user)
    monkeypatch.setattr(auth_router, "require_admin", _admin_user)

    monkeypatch.setitem(rbac_guards._GUARDS, "require_admin_or_503", _allow_admin)
    monkeypatch.setitem(rbac_guards._GUARDS, "forbid_viewer_writes", _allow_write)
    monkeypatch.setitem(rbac_guards._GUARDS, "require_session_actor", _session_actor)
    monkeypatch.setitem(rbac_guards._GUARDS, "get_current_user_from_request", _admin_user)
    monkeypatch.setattr(rbac_guards, "require_admin_or_503", _allow_admin)
    monkeypatch.setattr(rbac_guards, "forbid_viewer_writes", _allow_write)
    monkeypatch.setattr(rbac_guards, "require_session_actor", _session_actor)
    monkeypatch.setattr(rbac_guards, "get_current_user_from_request", _admin_user)

    monkeypatch.setattr(auth_service, "is_auth_enabled", lambda: False)

    main_mod = sys.modules.get("main")
    if main_mod is not None:
        if hasattr(main_mod, "require_admin"):
            monkeypatch.setattr(main_mod, "require_admin", _admin_user)
        if hasattr(main_mod, "require_admin_or_503"):
            monkeypatch.setattr(main_mod, "require_admin_or_503", _allow_admin)
        if hasattr(main_mod, "get_current_user_from_request"):
            monkeypatch.setattr(main_mod, "get_current_user_from_request", _admin_user)
        app_obj = getattr(main_mod, "app", None)
        dep_overrides = getattr(app_obj, "dependency_overrides", None)
        if isinstance(dep_overrides, dict):
            monkeypatch.setitem(dep_overrides, orig_forbid_viewer_writes, _allow_write)

    return dict(_TEST_ADMIN_USER)


_FLAG = os.getenv("ARCHON_TEST_DB_ISOLATION", "").strip().lower()
if _FLAG in ("1", "true", "yes", "on"):
    _test_data_dir = tempfile.mkdtemp(prefix="archon_test_data_")
    os.environ["ARCHON_DATA_DIR"] = _test_data_dir
    atexit.register(lambda: shutil.rmtree(_test_data_dir, ignore_errors=True))
    print(f"[conftest] Test-DB-Isolation aktiv: {_test_data_dir}")
