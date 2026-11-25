# -*- coding: utf-8 -*-
"""F011 / W1 / BLOCKER B-11 — Regressionstests für die verlustfreie Session-DAG.

Deckt die vier Glieder aus 00_SOLL_SPEC.md §0 ab:
Produzent (echter Chokepoint), Konsument (rekursive Expansion/UNION-Suche),
Effekt (tenant-scoped Persistenz, Art. 17) und Verifikation (dieser Test).
"""

import os
import sqlite3

import pytest

from backend import lossless_session_dag as lcm
from backend.db_paths import DB_BUSY_TIMEOUT_MS


def _messages(count: int = 6, *, session: str = "prod-session", tenant: str = "acme"):
    msgs = [{
        "role": "system",
        "content": "Du bist ein sicherer Assistent. Regeln: nie Passwörter nennen.",
        "session_id": session,
        "tenant_id": tenant,
    }]
    for i in range(count):
        msgs.append({
            "role": "user" if i % 2 == 0 else "assistant",
            "content": f"Turn {i}: Budget 50000 EUR, Datei backend/modul.py",
            "session_id": session,
            "tenant_id": tenant,
        })
    return msgs


# ---------------------------------------------------------------------------
# 1. Produzent im PRODUKTIVPFAD (kein Test-/Manuell-Artefakt)
# ---------------------------------------------------------------------------

def test_producer_wired_in_agent_router_chokpoints(monkeypatch):
    from backend.agent_router import AgentRouter

    calls = {"turns": [], "compactions": []}

    def fake_record(session_id, messages, tenant_id=None, db_path=None):
        calls["turns"].append((session_id, tenant_id, len(messages)))
        return ["turn-fake"]

    def fake_compact(session_id, older_messages, summary_text, tenant_id=None, db_path=None):
        calls["compactions"].append((session_id, tenant_id, summary_text))
        return "sum-fake"

    monkeypatch.setattr(lcm, "record_turns", fake_record)
    monkeypatch.setattr(lcm, "compact_conversation_turns", fake_compact)

    router = AgentRouter()
    monkeypatch.setattr(
        router, "check_loop_or_circuit_breaker",
        lambda *args, **kwargs: {"tripped": False},
    )
    monkeypatch.setattr(
        router, "_get_guardian_policy",
        lambda: {"daily_budget": 0.0, "max_context_tokens": 32000, "token_clipper_enabled": False},
    )

    # Jeder echte Turn durchläuft den Token-Guard.
    router._enforce_token_guard_unlocked(_messages(3), "local", "test-model", "medium")
    assert calls["turns"], "record_turns wurde im echten Token-Guard nie gerufen"
    assert calls["turns"][0][0] == "session:prod-session"
    assert calls["turns"][0][1] == "acme"

    # Echtes Context-Compacting erzeugt einen Summary-Knoten.
    router._compress_conversation_window(_messages(8), 1000)
    assert calls["compactions"], "compact_conversation_turns wurde beim Compacting nie gerufen"
    assert "KONSOLIDIERTER GESPRÄCHS" in calls["compactions"][0][2]
    assert calls["compactions"][0][1] == "acme"


def test_producer_wired_in_context_compactor(monkeypatch):
    from backend.context_compactor import ContextCompactor

    calls = {}
    monkeypatch.setattr(lcm, "record_turns", lambda *a, **k: [])

    def fake_compact(session_id, older_messages, summary_text, tenant_id=None, db_path=None):
        calls["summary"] = (session_id, tenant_id, summary_text)
        return "sum-fake"

    monkeypatch.setattr(lcm, "compact_conversation_turns", fake_compact)

    result = ContextCompactor().compact_messages(
        _messages(8), force=True, keep_recent_override=2
    )
    assert result["compacted"] is True
    assert calls["summary"][0] == "session:prod-session"
    assert result["lossless_summary_id"] == "sum-fake"


# ---------------------------------------------------------------------------
# 2. Verlustfreie Expansion & UNION-Suche (inkl. verschachtelter Summaries)
# ---------------------------------------------------------------------------

def test_recursive_expansion_over_nested_summaries(tmp_path):
    db = str(tmp_path / "lcm.db")
    t1 = lcm.append_turn("sess", "user", "Budget 50000 EUR", db_path=db)
    t2 = lcm.append_turn("sess", "assistant", "Notiert: 50000 EUR", db_path=db)
    inner = lcm.compact_range_to_summary("sess", [t1, t2], "Budget-Kern: 50000 EUR", db_path=db)
    t3 = lcm.append_turn("sess", "user", "Markteintritt 2027 prüfen", db_path=db)
    outer = lcm.compact_range_to_summary(
        "sess", [inner, t3], "Gesamt: Budget + Markteintritt", db_path=db
    )

    nodes = lcm.expand_summary_node(outer, db_path=db)
    kinds = [node["kind"] for node in nodes]
    assert kinds.count("turn") == 3
    assert kinds.count("summary") == 1  # verschachtelte Summary bleibt sichtbar
    contents = [node["content"] for node in nodes]
    assert any("50000 EUR" in text for text in contents)
    assert any("Markteintritt 2027" in text for text in contents)

    # Verdichteter Inhalt ist über die UNION-Suche auffindbar.
    hits = lcm.search_lossless_history("sess", "Budget-Kern", db_path=db)
    assert any(hit["kind"] == "summary" for hit in hits)
    assert lcm.verify_summary_integrity(inner, db_path=db) is True

    # Manipulation → fail-closed statt versteckter Weitergabe.
    con = sqlite3.connect(db)
    con.execute("UPDATE lcm_summaries SET summary_text = 'MANIPULIERT' WHERE id = ?", (inner,))
    con.commit()
    con.close()
    assert lcm.verify_summary_integrity(inner, db_path=db) is False
    with pytest.raises(lcm.LosslessIntegrityError):
        lcm.expand_summary_node(outer, db_path=db)


# ---------------------------------------------------------------------------
# 3. Tenant-Isolation + Art. 17
# ---------------------------------------------------------------------------

def test_tenant_isolation_and_article17(tmp_path):
    db = str(tmp_path / "lcm.db")
    lcm.append_turn("s1", "user", "ACME Geheimnis 4711", db_path=db, tenant_id="acme")
    lcm.append_turn("s1", "user", "Default Sichtbar 4711", db_path=db, tenant_id="default")

    acme_hits = lcm.search_lossless_history("s1", "4711", db_path=db, tenant_id="acme")
    default_hits = lcm.search_lossless_history("s1", "4711", db_path=db, tenant_id="default")
    assert len(acme_hits) == 1 and "ACME" in acme_hits[0]["content"]
    assert len(default_hits) == 1 and "Default" in default_hits[0]["content"]
    assert acme_hits[0]["tenant_id"] == "acme"

    removed = lcm.delete_tenant_lossless_data("acme", db_path=db)
    assert removed["turns"] == 1
    assert lcm.search_lossless_history("s1", "4711", db_path=db, tenant_id="acme") == []
    assert len(lcm.search_lossless_history("s1", "4711", db_path=db, tenant_id="default")) == 1

    # Art. 17: case-insensitive Schwärzung inkl. Re-Signatur der Summary.
    turn = lcm.append_turn(
        "s2", "user", "Michael Keller ist der Ansprechpartner",
        db_path=db, tenant_id="default",
    )
    summary = lcm.compact_range_to_summary(
        "s2", [turn], "Michael Keller leitet das Projekt",
        db_path=db, tenant_id="default",
    )
    report = lcm.anonymize_subject_in_lossless_history(
        "michael keller", tenant_id="default", db_path=db
    )
    assert report["turns"] == 1 and report["summaries"] == 1
    assert lcm.search_lossless_history("s2", "Michael Keller", db_path=db, tenant_id="default") == []
    assert lcm.verify_summary_integrity(summary, db_path=db, tenant_id="default") is True


# ---------------------------------------------------------------------------
# 4. DB-Pfad konsolidiert + busy_timeout/WAL aus der SSOT
# ---------------------------------------------------------------------------

def test_db_path_consolidated_and_ssot(monkeypatch, tmp_path):
    import backend.db_paths as db_paths

    sentinel = str(tmp_path / "memory.db")
    monkeypatch.setattr(db_paths, "resolve_db", lambda name: sentinel)
    assert lcm._default_db_path() == sentinel
    assert "lcm_sessions" not in lcm._default_db_path()

    db = str(tmp_path / "ssot.db")
    with lcm._connect(db) as conn:
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == DB_BUSY_TIMEOUT_MS
        if os.environ.get("ARCHON_DISABLE_WAL", "").strip().lower() not in ("1", "true", "yes"):
            assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        turn_cols = {row[1] for row in conn.execute("PRAGMA table_info(lcm_turns)")}
        summary_cols = {row[1] for row in conn.execute("PRAGMA table_info(lcm_summaries)")}
        assert "tenant_id" in turn_cols
        assert {"tenant_id", "integrity_hmac"} <= summary_cols
