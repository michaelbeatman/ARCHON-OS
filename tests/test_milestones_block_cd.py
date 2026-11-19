# -*- coding: utf-8 -*-
import datetime

from backend.contract_deadline_watcher import scan_upcoming_deadlines
from backend.enterprise_calendar import build_calendar_grid, group_events_by_agent, reschedule_calendar_event
from backend.meeting_copilot import build_crm_meeting_note
from backend.operations_templates import list_operations_templates, preview_operations_template
from backend.telegram_gateway_v2 import (
    build_hitl_inline_keyboard,
    format_live_task_status,
    parse_hitl_callback,
    parse_telegram_agent_route,
    resolve_telegram_session_key,
)
from backend.time_tracking_invoice import (
    compute_project_budget_variance,
    export_invoice_line_items,
    start_timer,
    stop_timer,
)
from backend.voice_to_workflow import analyze_dictation_ambiguities, compile_playbook_from_spec
from backend.watchdog_radar_v2 import record_source_health, register_signal_if_new, score_signal_relevance


def test_m32_telegram_gateway_v2():
    assert resolve_telegram_session_key(12345, "legal_counsel") == "tg_12345_legal_counsel"
    agent, prompt = parse_telegram_agent_route("/robert Pruefe Angebot")
    assert agent == "executive_decision_architect"
    assert prompt == "Pruefe Angebot"
    kb = build_hitl_inline_keyboard("ta-99")
    cb = parse_hitl_callback(kb["inline_keyboard"][0][0]["callback_data"])
    assert cb["approved"] is True and cb["approval_id"] == "ta-99"
    assert "01:05" in format_live_task_status("t-1", "Build", 65, "Tests laufen")


def test_m63_m64_m55_ui_hooks():
    with open("static/views/system_settings_modal.html", "r", encoding="utf-8") as f:
        assert "modal-header-onboarding-btn" in f.read()
    with open("static/index.html", "r", encoding="utf-8") as f:
        idx = f.read()
        assert "sidebar_v2.js" in idx
        assert "enterprise_calendar_ui.js" in idx


def test_m62_operations_templates():
    all_tpl = list_operations_templates()
    assert len(all_tpl) >= 3
    prev = preview_operations_template("tpl_invoice_de", {"doc.number": "RE-2026-01", "customer.name": "Muster GmbH", "doc.total_eur": "1190.00"})
    assert "RE-2026-01" in prev["rendered_preview"]
    assert "Muster GmbH" in prev["rendered_preview"]


def test_m55_enterprise_calendar():
    events = [{"id": "e1", "title": "Standup", "start": "2026-11-19T09:00:00", "assignee": "scrum", "recurrence": "weekly", "recurrence_count": 3}]
    grid = build_calendar_grid(events, view="month", anchor_date="2026-11-19")
    assert grid["total_events"] == 3
    moved = reschedule_calendar_event(events[0], "2026-11-20T10:00:00")
    assert moved["start"] == "2026-11-20T10:00:00"
    assert "scrum" in group_events_by_agent(events)


def test_m33_watchdog_radar_v2(tmp_path):
    db = str(tmp_path / "wd.db")
    rel = score_signal_relevance("KI Verordnung EU AI Act", "Neue Pflichten ab 2026", ["eu ai act", "pflichten"])
    assert rel["is_signal"] is True
    assert register_signal_if_new("https://a.de/1", "EU AI Act", rel["score"], db_path=db) is True
    assert register_signal_if_new("https://a.de/1", "EU AI Act", rel["score"], db_path=db) is False
    record_source_health("src1", "https://primary.de", "https://fallback.de", ok=False, db_path=db)
    h2 = record_source_health("src1", "https://primary.de", "https://fallback.de", ok=False, db_path=db)
    assert h2["healed_to_fallback"] is True
    assert h2["active_url"] == "https://fallback.de"


def test_m38_contract_deadline_watcher():
    today = datetime.date(2026, 11, 19)
    contracts = [
        {"id": "c1", "vendor": "CloudHost AG", "contract_number": "CH-42", "cancel_by_date": "2026-11-28"},
        {"id": "c2", "vendor": "Langlauf GmbH", "cancel_by_date": "2027-06-01"},
    ]
    alerts = scan_upcoming_deadlines(contracts, today=today)
    assert len(alerts) == 1
    assert alerts[0]["urgency"] == "critical"
    assert "CloudHost AG" in alerts[0]["cancellation_draft"]


def test_m37_time_tracking_invoice(tmp_path):
    db = str(tmp_path / "time.db")
    eid = start_timer("proj-1", "t-10", "Architektur-Review", hourly_rate_eur=100.0, started_at=1000.0, db_path=db)
    stopped = stop_timer(eid, stopped_at=8200.0, db_path=db)
    assert stopped["duration_hours"] == 2.0
    var = compute_project_budget_variance("proj-1", budget_hours=5.0, db_path=db)
    assert var["actual_hours"] == 2.0
    assert var["billable_total_eur"] == 200.0
    lines = export_invoice_line_items("proj-1", db_path=db)
    assert len(lines) == 1 and lines[0]["net_total_eur"] == 200.0


def test_m39_meeting_copilot():
    segs = [
        {"speaker": "Micha", "timestamp": "00:12", "text": "Wir brauchen bis Freitag ein Update."},
        {"speaker": "Robert", "timestamp": "00:25", "text": "TODO: Angebot an Huber GmbH finalisieren"},
    ]
    # § 201 StGB Consent-Gate: ohne Einwilligung muss PermissionError kommen
    try:
        build_crm_meeting_note("Huber GmbH", segs, all_participants_consented=False)
        assert False, "Expected PermissionError without consent"
    except PermissionError:
        pass
    note = build_crm_meeting_note("Huber GmbH", segs, all_participants_consented=True, consent_timestamp="2026-11-19T07:40:00")
    assert note["consent_verified"] is True
    assert note["task_count"] == 1
    assert "Angebot an Huber GmbH" in note["kanban_tasks"][0]["title"]


def test_m54_voice_to_workflow():
    amb = analyze_dictation_ambiguities("Pruefe neue Rechnungen.")
    assert amb["needs_clarification"] is True
    assert len(amb["questions"]) == 3
    pb = compile_playbook_from_spec("Rechnungspruefung", "Pruefe neue Rechnungen", {"trigger": "cron", "target": "kanban", "hitl": "ja"})
    assert pb["id"] == "rechnungspruefung"
    assert pb["steps"][2]["require_hitl"] is True
