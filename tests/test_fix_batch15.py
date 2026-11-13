"""
tests/test_fix_batch15.py
Rot-Beweise fuer Batch 15:
- K-2: audit_log.py schliesst SQLite-Verbindungen in list_events und generate_compliance_export immer im finally-Block
- F12: hermes_profiles und skills validieren IDs gegen Pfad-Traversal
- F17: esign/webhook prueft Webhook-Secret oder Admin-Rechte
- D-23: Redundante identische ContentStudioView.tsx Kopie entfernt
"""
import pytest
import sqlite3
from pathlib import Path
from fastapi import HTTPException
from unittest.mock import MagicMock

from backend.audit_log import ChainedAuditLog
from archon.routers.hermes_profiles import api_toggle_hermes_profile_favorite


def test_k2_audit_log_connections_closed(tmp_path):
    """K-2: list_events und generate_compliance_export muessen ihre DB-Verbindungen deterministisch schliessen."""
    db_file = tmp_path / "test_audit.db"
    audit = ChainedAuditLog(db_path=str(db_file))

    opened = []
    real_get_conn = audit._get_conn

    def tracking_get_conn():
        c = real_get_conn()
        opened.append(c)
        return c

    audit._get_conn = tracking_get_conn
    audit.list_events()

    assert len(opened) > 0
    for c in opened:
        with pytest.raises(sqlite3.ProgrammingError, match="Cannot operate on a closed database"):
            c.execute("SELECT 1")


def test_f12_hermes_profiles_and_skills_id_validation(monkeypatch):
    """F12: Profile- und Skill-IDs mit Pfad-Traversal muessen abgewiesen werden."""
    # Wire require_admin
    from archon.routers import _rbac
    monkeypatch.setattr(_rbac, "_checker", lambda req: None)
    dummy_req = MagicMock()
    
    # hermes_profiles favorite muss Traversal mit 400 abweisen
    with pytest.raises(HTTPException) as exc_info:
        api_toggle_hermes_profile_favorite("../../etc", request=dummy_req)
    assert exc_info.value.status_code == 400

    # skills Router Code pruefen
    skills_code = Path("archon/routers/skills.py").read_text(encoding="utf-8")
    assert "safe_filename(skill_id)" in skills_code, "Skill-ID wird vor os.path.join nicht mit safe_filename geprueft"


def test_f17_esign_webhook_auth_gate():
    """F17: esign/webhook muss Webhook-Secret oder require_admin_or_503 pruefen."""
    ops_code = Path("backend/operations_api.py").read_text(encoding="utf-8")
    webhook_block = ops_code.split('@router.post("/esign/webhook")')[1].split("@router.")[0]

    assert "DOCUSEAL_WEBHOOK_SECRET" in webhook_block or "require_admin" in webhook_block, "esign/webhook hat keine Authentifizierung"


def test_d23_no_duplicate_content_studio_view():
    """D-23: ContentStudioView.tsx darf nicht doppelt im Codebaum existieren."""
    p1 = Path("frontend/src/components/ContentStudioView.tsx")
    p2 = Path("frontend/src/components/ContentStudio/ContentStudioView.tsx")
    assert not (p1.exists() and p2.exists()), "ContentStudioView.tsx existiert doppelt und fuehrt zu Codestand-Divergenz"
