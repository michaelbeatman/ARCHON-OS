"""F24b (D01): Ehrliche Doku- & Demo-Kennzeichnung fuer M26/M27 und jev_router."""
from __future__ import annotations

import re
from pathlib import Path

import jev_router
from scripts.check_doc_version_sync import check_doc_version_sync

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_f24b_milestones_26_and_27_not_claimed_abgeschlossen_in_docs():
    doc_paths = [
        REPO_ROOT / "docs" / "SYSTEM_HANDBUCH.md",
        REPO_ROOT / "docs" / "system" / "ROADMAP_2026.md",
    ]
    for path in doc_paths:
        text = path.read_text(encoding="utf-8")
        # Tabelleneintraege 26 & 27 duerfen nicht mehr "Abgeschlossen" behaupten
        for ms in ("26", "27"):
            row_pattern = re.compile(rf"^\|\s*\*\*{ms}\*\*\s*\|.*$", re.MULTILINE)
            rows = row_pattern.findall(text)
            assert rows, f"Meilenstein-{ms}-Zeile fehlt in {path.name}"
            for row in rows:
                assert "Abgeschlossen" not in row, (
                    f"Meilenstein {ms} in {path.name} noch als Abgeschlossen markiert: {row}"
                )
                assert "Demo / Simulation" in row, (
                    f"Meilenstein {ms} in {path.name} nicht ehrlich als Demo / Simulation markiert: {row}"
                )

            header_pattern = re.compile(rf"^###\s+Meilenstein\s+{ms}:.*$", re.MULTILINE)
            headers = header_pattern.findall(text)
            assert headers, f"Meilenstein-{ms}-Ueberschrift fehlt in {path.name}"
            for hdr in headers:
                assert "(Abgeschlossen)" not in hdr, (
                    f"Meilenstein-{ms}-Header in {path.name} noch (Abgeschlossen): {hdr}"
                )
                assert "Demo / Simulation" in hdr, (
                    f"Meilenstein-{ms}-Header in {path.name} fehlt Demo/Simulation-Hinweis: {hdr}"
                )


def test_f24b_jev_router_no_fabricated_tokens_saved_and_honest_demo_mode(monkeypatch):
    hit = jev_router.match_local_fast_path("Starte E-Mail-Sync")
    assert hit is not None
    assert hit["intent"] == "email_sync"
    assert hit["tokens_saved"] is None
    assert hit["tokens_saved_estimated"] is False

    monkeypatch.setattr(
        jev_router,
        "get_jev_config",
        lambda: {
            "enabled": True,
            "fast_path_enabled": True,
            "tool_pruning_enabled": True,
            "agent_routing_enabled": True,
        },
    )

    local_res = jev_router.classify_prompt("Starte E-Mail-Sync")
    assert local_res["mode"] == "local_pattern"
    assert local_res["demo_only"] is False
    assert local_res["tokens_saved"] is None

    non_fast = jev_router.classify_prompt("Entwirf eine komplexe Go-to-Market-Strategie")
    assert non_fast["action"] == "llm_required"
    assert non_fast["demo_only"] is True
    assert non_fast["mode"] == "heuristic_demo"
    assert non_fast["reason"] == "no_remote_jev_decision_available"


def test_f24b_doc_version_sync_still_passes():
    version, mismatches = check_doc_version_sync(REPO_ROOT)
    assert version
    assert mismatches == []
