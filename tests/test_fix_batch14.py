"""
tests/test_fix_batch14.py
Rot-Beweise fuer Batch 14:
- F9b: safe_path ist fail-closed bei Importfehler (wirft PathJailError statt ungeprueftem Pfad)
- F16: /api/debug-db erfordert Admin-Rechte (require_admin_or_503)
- F13: api_crm_avatar schuetzt vor Pfad-Traversal und prueft Parameter mit safe_path/safe_filename
- P-03: _resolve_task_obsidian_rel fuehrt bei reinen Leseabfragen keine wiederholten fsync-Schreibvorgaenge aus
"""
import pytest
from pathlib import Path
from fastapi import HTTPException
from fastapi.testclient import TestClient

import main as main_mod
from archon.routers.crm import api_crm_avatar


def test_f9b_safe_path_fail_closed_on_import_error():
    """F9b: Wenn utils.path_jail nicht importiert werden kann, muss der Fallback fail-closed sein."""
    main_code = Path(main_mod.__file__).read_text(encoding="utf-8")
    
    # Pruefe, dass der Fallback-Block in main.py nicht nur os.path.realpath zurueckgibt
    fallback_part = main_code.split("except Exception as _pj_err:")[1].split("# ---")[0]
    assert "return os.path.realpath" not in fallback_part, "safe_path Fallback ist fail-open (gibt realpath ohne Pruefung zurueck)"


def test_f16_debug_db_requires_admin():
    """F16: /api/debug-db muss geschuetzt sein (require_admin oder require_admin_or_503)."""
    main_code = Path(main_mod.__file__).read_text(encoding="utf-8")
    debug_db_part = main_code.split('@app.get("/api/debug-db")')[1].split("@app.")[0]
    
    assert "require_admin" in debug_db_part, "/api/debug-db hat keinen Rollenzaun (require_admin fehlt)"


def test_f13_crm_avatar_path_traversal():
    """F13: api_crm_avatar muss Traversal-Versuche (z.B. ../../) sofort mit 400 oder 403 abweisen."""
    with pytest.raises(HTTPException) as exc_info:
        api_crm_avatar("valid_id", "../../../etc/passwd")
    
    assert exc_info.value.status_code in (400, 403), f"Traversal-Versuch wurde nicht mit 400/403 abgewiesen: {exc_info.value.status_code}"


def test_p03_resolve_obsidian_no_fsync_on_read(tmp_path, monkeypatch):
    """P-03: _resolve_task_obsidian_rel darf bei auto_heal=False keine Sidecar-Updates auf die Platte schreiben."""
    from backend.operations_api import _resolve_task_obsidian_rel
    import backend.kanban_sidecar as sidecar_mod

    # Vault-Ordner mit Projekt anlegen
    vault_dir = tmp_path / "vault"
    proj_dir = vault_dir / "01_PROJEKTE" / "test-project-123"
    proj_dir.mkdir(parents=True)
    monkeypatch.setattr("backend.post_task_pipeline.get_vault_dir", lambda: str(vault_dir))

    written = []

    def tracking_update(mutator):
        written.append(True)

    monkeypatch.setattr(sidecar_mod, "update_kanban_meta", tracking_update)

    # Bei Leseaufruf (Default auto_heal=False) darf kein update_kanban_meta aufgerufen werden
    res = _resolve_task_obsidian_rel("test-project-123", meta={"tasks": {}}, auto_heal=False)
    assert res == "01_PROJEKTE/test-project-123"
    assert len(written) == 0, "_resolve_task_obsidian_rel fuehrt unnoetige Schreiboperationen bei Leseaufrufen aus"
