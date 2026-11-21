# -*- coding: utf-8 -*-
import datetime
import time

from backend.calendar_sync_blocker import (
    export_ics_events,
    parse_ics_events,
    schedule_focus_blocks,
    sync_calendar_bidirectional,
)
from backend.client_approval_portal import (
    create_share_link,
    submit_client_decision,
    verify_share_access,
)
from backend.contract_diff_redliner import diff_contract_clauses


def test_m41_calendar_sync_and_focus_blocker():
    evs = [{"uid": "u1", "title": "Call", "start": "20261119T100000", "end": "20261119T110000", "updated_at": "20261119T080000"}]
    ics = export_ics_events(evs)
    parsed = parse_ics_events(ics)
    assert len(parsed) == 1 and parsed[0]["uid"] == "u1"

    merged = sync_calendar_bidirectional(
        [{"uid": "u1", "title": "Old", "updated_at": "2026-11-19T08:00:00"}],
        [{"uid": "u1", "title": "New", "updated_at": "2026-11-19T09:00:00"}, {"uid": "u2", "title": "Remote"}],
    )
    assert len(merged["merged"]) == 2
    assert len(merged["pull_to_local"]) == 2

    blocks = schedule_focus_blocks(
        busy_events=[{"start": "2026-11-19T09:00:00", "end": "2026-11-19T10:30:00"}],
        deadlines=[{"id": "t-1", "title": "Vertrag pruefen"}],
        target_date=datetime.date(2026, 11, 19),
    )
    assert len(blocks) == 1
    assert blocks[0]["start"] == "2026-11-19T10:30:00"


def test_m40_contract_diff_and_risk():
    old = "1. Laufzeit: 12 Monate.\n2. Haftung begrenzt auf 50000 EUR."
    new = "1. Laufzeit: 12 Monate.\n2. Haftung unbegrenzt inkl. Vertragsstrafe."
    res = diff_contract_clauses(old, new)
    assert res["added_count"] == 1
    assert res["removed_count"] == 1
    assert any(r["severity"] == "high" for r in res["risk_findings"])
    assert "<ins" in res["html_redline"] and "<del" in res["html_redline"]


def test_m42_client_approval_portal(tmp_path):
    db = str(tmp_path / "portal.db")
    link = create_share_link("ang-100", "Angebot KI-Plattform", password="secret", ttl_hours=24, db_path=db)
    assert verify_share_access(link["token"], password="wrong", db_path=db)["allowed"] is False
    assert verify_share_access(link["token"], password="secret", db_path=db)["allowed"] is True
    assert verify_share_access(link["token"], password="secret", now_ts=time.time() + 999999, db_path=db)["allowed"] is False

    # Annahme ohne AGB-Bestaetigung blockiert
    no_terms = submit_client_decision(link["token"], "accepted", comment="Passt!", password="secret", terms_accepted=False, db_path=db)
    assert no_terms["allowed"] is False

    dec = submit_client_decision(
        link["token"], "accepted", comment="Passt!", password="secret",
        terms_accepted=True, ai_disclosure_shown=True, client_ip="127.0.0.1", document_sha256="abc123", db_path=db
    )
    assert dec["erp_status"] == "Auftrag"
    assert dec["ai_disclosure_shown"] is True
