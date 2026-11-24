"""Audit P2/D08: keine blockierenden Hotpaths mehr."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_chat_sse_writes_off_the_event_loop():
    text = _text("archon/routers/chat.py")
    ast.parse(text)
    assert "await asyncio.to_thread(\n                _save_message_to_db" in text
    assert "await asyncio.to_thread(\n                _record_session_model_usage" in text


def test_bounded_read_queries():
    kanban = _text("archon/routers/kanban.py")
    assert "ORDER BY id DESC LIMIT 5000" in kanban
    hybrid = _text("backend/hybrid_search_engine.py")
    assert "ORDER BY doc_id LIMIT 5000" in hybrid


def test_profile_list_uses_mtime_cache():
    text = _text("archon/routers/agent_chat.py")
    ast.parse(text)
    assert "_PROFILES_LIST_CACHE" in text
    assert "st_mtime_ns" in text


def test_compliance_export_supports_optional_pagination():
    text = _text("backend/audit_log.py")
    ast.parse(text)
    assert "limit: Optional[int] = None" in text
    assert 'sql += " LIMIT ?"' in text
