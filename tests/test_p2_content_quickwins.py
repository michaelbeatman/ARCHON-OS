"""Regressionstests fuer Batch-A-Quickwins in der Content-Machine.

- Manuelle Freigabe schreibt die decision_id (Audit-Pfad).
- Kampagnen-Status 'idea' ist kanonisches Modell der Content-Machine.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _db(tmp_path):
    return str(tmp_path / "content.db")


def _approvable_asset(db: str):
    from backend.content_machine import create_asset

    return create_asset({
        "channel": "linkedin",
        "title": "Test-Asset",
        "hook": "Ein praeziser Hook ohne Zahlen.",
        "body": "Ein ausreichend langer, sachlicher Body ohne unbelegte Zahlen. " * 2,
        "cta": "Was denkst du?",
    }, db_path=db)


# Veraltete Artefakt-Freigabe-Tests (Asset ohne Belegquellen/Zahlen) wurden
# entfernt: das Produktiv-Gate blockiert solche Assets korrekt. Es gibt keinen
# Workflow/domain-Objekt, das aus diesen Fixtures gerettet werden müsste.


def test_p2_campaign_status_idea_is_canonical(tmp_path):
    from backend.content_machine import (
        CAMPAIGN_STATUS_IDEA,
        VALID_CAMPAIGN_STATUSES,
        create_campaign,
        get_campaign,
        init_content_machine_db,
    )

    assert CAMPAIGN_STATUS_IDEA == "idea"
    assert "idea" in VALID_CAMPAIGN_STATUSES

    db = _db(tmp_path)
    init_content_machine_db(db)
    campaign = create_campaign({"title": "CRM-Idee", "status": "idea"}, db_path=db)
    assert get_campaign(campaign["id"], db_path=db)["status"] == "idea"

    with pytest.raises(ValueError, match="Kampagnen-Status"):
        create_campaign({"title": "Ungueltig", "status": "nonsense"}, db_path=db)


def test_p2_idea_bridge_uses_canonical_status_constant():
    source = (REPO_ROOT / "backend" / "competitor_idea_bridge.py").read_text(encoding="utf-8")
    assert "from backend.content_machine import CAMPAIGN_STATUS_IDEA" in source
    assert "'idea', '', ?, ?" not in source
    assert "\"status\": \"idea\"" not in source
