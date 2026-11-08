"""Cluster Spur A — Security-Review (F2, F25) in main.py.

Rot gegen 3269f7e1:

* F2: ``POST /api/healing/attempt`` hatte keinen Rollenzaun — jede
  eingeloggte Rolle konnte den Selbstheilungspfad ausloesen
  (Shell-Injection selbst ist ueber ``validate_affected_file`` geschlossen).
* F25: ``POST /api/diff/preview`` las ``file_path`` ungeprueft und ohne
  Rollenzaun — beliebiges Datei-Lesen (``/etc/passwd``, ``.env.archon``,
  Service-Token) mit dem Inhalt als Diff-Antwort.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

ROOT = Path(os.environ.get("ARCHON_ROOT") or Path(__file__).resolve().parent.parent)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main as app_main  # noqa: E402


# ------------------------------------------------------------------- F-25

def test_diff_preview_lehnt_pfade_ausserhalb_des_repos_ab(monkeypatch, tmp_path):
    secret = tmp_path / "secret.env"
    secret.write_text("SECRET=1", encoding="utf-8")

    monkeypatch.setattr(app_main, "require_admin_or_503", lambda request: None)

    with pytest.raises(HTTPException) as exc:
        app_main.api_diff_preview(None, {"file_path": str(secret), "new_content": "x"})
    assert exc.value.status_code == 403


def test_diff_preview_lehnt_systempfade_ab(monkeypatch):
    monkeypatch.setattr(app_main, "require_admin_or_503", lambda request: None)

    for path in ("/etc/passwd", "/opt/data/.env", "/root/.hermes/config.yaml"):
        with pytest.raises(HTTPException) as exc:
            app_main.api_diff_preview(None, {"file_path": path, "new_content": "x"})
        assert exc.value.status_code == 403, f"{path} wurde nicht blockiert"


def test_diff_preview_erlaubt_repo_dateien(monkeypatch, tmp_path):
    target = tmp_path / "datei.py"
    target.write_text("print('alt')\n", encoding="utf-8")
    repo_root = str(ROOT)
    monkeypatch.setattr(app_main, "require_admin_or_503", lambda request: None)

    # Der Jail-Wurzelbaum des Handlers ist der Repo-Wurzelbaum; die Testdatei
    # liegt darunter, damit der echte Pfad geprueft wird.
    inside = ROOT / "data" / "_orange_a_diff_probe.py"
    inside.parent.mkdir(parents=True, exist_ok=True)
    inside.write_text("print('alt')\n", encoding="utf-8")
    try:
        result = app_main.api_diff_preview(
            None, {"file_path": str(inside), "new_content": "print('neu')\n"}
        )
        assert result is not None
    finally:
        inside.unlink(missing_ok=True)
    assert repo_root


def test_diff_preview_verlangt_einen_pfad(monkeypatch):
    monkeypatch.setattr(app_main, "require_admin_or_503", lambda request: None)
    with pytest.raises(HTTPException) as exc:
        app_main.api_diff_preview(None, {"file_path": "", "new_content": "x"})
    assert exc.value.status_code == 400


# ------------------------------------------------------------------- F-2

def test_healing_attempt_verlangt_admin(monkeypatch):
    """Der Zaun muss VOR der Selbstheilung greifen."""
    calls = {"healer": 0}

    monkeypatch.setattr(app_main, "require_admin_or_503", lambda request: (_ for _ in ()).throw(
        HTTPException(status_code=403, detail="nur admin")
    ))

    import backend.task_self_healer as healer_mod

    class _FakeHealer:
        async def attempt_self_healing(self, **kwargs):
            calls["healer"] += 1
            return {"status": "success"}

    monkeypatch.setattr(healer_mod, "task_self_healer", _FakeHealer())

    import asyncio
    with pytest.raises(HTTPException) as exc:
        asyncio.run(app_main.api_attempt_task_healing(None, {"task_id": "t1"}))
    assert exc.value.status_code == 403
    assert calls["healer"] == 0, "die Selbstheilung lief trotz fehlender Berechtigung"


def test_healing_attempt_hat_einen_zaun():
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    idx = source.index("def api_attempt_task_healing")
    block = source[idx:idx + 700]
    assert "require_admin_or_503(request)" in block, (
        "der Selbstheilungspfad hat keinen Rollenzaun"
    )
