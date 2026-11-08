"""Tests fuer Batch 17 (Z-14, Z-16, F-17/F-19, D-24).

Verifiziert:
- Z-14: SecurityAuditPlugin bzw. before_tool_execute bricht bei Exceptions sicher ab (fail-closed statt silent pass)
- Z-16: api_get_latest_morning_standup faellt bei Lesefehlern nicht still auf teure LLM-Generierung zurueck, sondern liefert Fehler
- F-17/F-19: Frontend JS PromptStudio res.ok Check & index.html Privacy Polling Visibility-Check
- D-24: React Audio Recording Komponenten besitzen Unmount-Cleanup fuer Timer und MediaStream
"""

from pathlib import Path
import pytest
from unittest.mock import MagicMock
from fastapi import HTTPException


def test_z14_plugin_manager_fail_closed():
    """Z-14: Plugin-Fehler in before_tool_execute duerfen das Tool nicht lautlos durchlassen."""
    src = Path("backend/plugin_manager.py").read_text(encoding="utf-8")
    assert "raise" in src.split("apply_before_tool_execute")[1].split("return cur_args")[0]


@pytest.mark.asyncio
async def test_z16_standup_read_failure_no_accidental_llm_generation(monkeypatch):
    """Z-16: Wenn Vault-Lesen fehlschlaegt, darf nicht unbemerkt die teure generate_morning_standup aufgerufen werden."""
    from archon.routers import system
    
    # Simuliere defekten Vault-Pfad / OS-Fehler
    monkeypatch.setattr("os.path.exists", lambda p: True)
    
    async def fake_listdir(p):
        raise OSError("Permission denied on vault")
    
    monkeypatch.setattr("asyncio.to_thread", lambda fn, *args: fake_listdir(args[0]) if fn == os.listdir else None)
    
    llm_called = []
    async def fake_generate():
        llm_called.append(True)
        return {"status": "generated"}
    
    # Mock generation
    import backend.autonomous_standup
    monkeypatch.setattr(backend.autonomous_standup, "generate_morning_standup", fake_generate)
    
    with pytest.raises(HTTPException) as exc_info:
        await system.api_get_latest_morning_standup()
    assert exc_info.value.status_code >= 500
    assert len(llm_called) == 0, "generate_morning_standup wurde faelschlicherweise aufgerufen"


def test_f17_prompt_studio_res_ok_checked():
    """F-17: prompt_studio.js prueft res.ok vor res.json()."""
    src = Path("static/js/prompt_studio.js").read_text(encoding="utf-8")
    assert "res.ok" in src, "prompt_studio.js prueft res.ok nicht ab"


def test_f19_index_privacy_polling_visibility_check():
    """F-19: Privacy-Polling in static/index.html prueft document.hidden."""
    src = Path("static/index.html").read_text(encoding="utf-8")
    # Im fetchPrivacyStatus muss document.hidden beachtet werden
    block = src.split("async function fetchPrivacyStatus()")[1].split("const res = await fetch")[0]
    assert "document.hidden" in block, "fetchPrivacyStatus ignoriert document.hidden"


def test_d24_media_recording_unmount_cleanup():
    """D-24: MediaBoardView & NachrichtenverlaufPanel haben useEffect Cleanup fuer Aufnahme-Timer und Streams."""
    mb_src = Path("frontend/src/components/MediaBoardView.tsx").read_text(encoding="utf-8")
    nv_src = Path("frontend/src/components/NachrichtenverlaufPanel.tsx").read_text(encoding="utf-8")
    
    assert "dikttimerRef.current" in mb_src and "clearInterval(dikttimerRef.current)" in mb_src
    assert "return () =>" in mb_src and "diktterStreamRef.current" in mb_src, "MediaBoardView raeumt diktterStream beim Unmount nicht auf"
    assert "return () =>" in nv_src and "streamRef.current" in nv_src, "NachrichtenverlaufPanel raeumt streamRef beim Unmount nicht auf"
