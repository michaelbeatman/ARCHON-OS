"""Offline-Regressionstests fuer Content-Batch D.

Deckt ab: Dossier-Pfad-Propagation, Redaktionsrollen + Freigabe-Historie,
Skill-Injektion in den Repurposing-DAG und die 48h-GEO-Zitatpruefung.

Es werden keine Netzwerkaufrufe durchgefuehrt; Datei-Schreiber werden wo noetig
via monkeypatch ersetzt.
"""
from __future__ import annotations

import datetime
import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _db(tmp_path):
    return str(tmp_path / "content.db")


def _asset_payload(**overrides):
    payload = {
        "channel": "linkedin",
        "title": "Batch D Asset",
        "hook": "12% mehr Umsatz in 30 Tagen",
        "body": "Wir haben 12% mehr Umsatz in 30 Tagen erzielt. Die Studie belegt 12% Steigerung in 30 Tagen.",
        "cta": "Kommentiere deine Erfahrung.",
        "sources": [{"title": "Studie", "text": "12% Steigerung in 30 Tagen", "url": "https://ok.test/a"}],
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# 1. RESEARCH DOSSIER PATH
# ---------------------------------------------------------------------------

def test_dossier_helper_reuses_base_writer(tmp_path, monkeypatch):
    import research_engine_v2 as rev2

    captured = {}

    def fake_writer(**kwargs):
        captured.update(kwargs)
        return {"local_path": str(tmp_path / "dossier.md"), "obsidian_path": ""}

    monkeypatch.setattr(rev2.base, "build_and_save_dossier", fake_writer)
    monkeypatch.setattr(
        rev2.base, "validate_ai_output",
        lambda *a, **k: {"score": 9, "recommendation": "TRUST"},
    )
    result = {
        "status": "success",
        "synthesis": "Synthese",
        "sources": [{"title": "Quelle", "domain": "x.test", "url": "https://x.test/a"}],
        "triangulation_verdict": "HOCH",
        "triangulation_score": 9,
        "blocked_snippets": 0,
    }
    path = rev2.save_dossier_for_result(result, "Testfrage", workspace_dir=str(tmp_path))
    assert path.endswith("dossier.md")
    assert captured["query"] == "Testfrage"
    assert captured["synthesis_markdown"] == "Synthese"
    assert "DAG-Research-Knoten" in captured["extra_meta"]

    # Keine Evidenz -> kein Dossier, kein Crash.
    assert rev2.save_dossier_for_result({"status": "no_evidence", "sources": []}, "leer") == ""


async def test_research_dag_node_propagates_dossier_path():
    from backend.workflow_dag_runner import _execute_research_dag_node

    fake = {
        "status": "success",
        "synthesis": "Faktenbasierte Synthese",
        "sources": [{"title": "Quelle A", "url": "https://example.org/a", "domain": "example.org"}],
        "triangulation_verdict": "HOCH",
        "triangulation_score": 9,
    }
    with patch("research_engine_v2.run_research_mission_v2", return_value=fake), \
            patch("research_engine_v2.save_dossier_for_result", return_value="/tmp/dossier.md") as saver:
        res = await _execute_research_dag_node(
            {"id": "n_research", "type": "research", "query": "Testthema"}, {}
        )

    assert res["status"] == "success"
    assert res["dossier_path"] == "/tmp/dossier.md"
    assert "/tmp/dossier.md" in res["content"]
    saver.assert_called_once()


def test_asset_schema_carries_dossier_path(tmp_path):
    from backend import content_machine as cm

    db = _db(tmp_path)
    cm.init_content_machine_db(db)
    asset = cm.create_asset(
        _asset_payload(dossier_path="/tmp/dossier.md"),
        db_path=db,
    )
    assert asset["dossier_path"] == "/tmp/dossier.md"
    assert cm.list_assets(db_path=db)[0]["dossier_path"] == "/tmp/dossier.md"


# ---------------------------------------------------------------------------
# 2. EDITORIAL ROLES + APPROVAL HISTORY
# ---------------------------------------------------------------------------

def test_approval_history_and_roles(tmp_path, monkeypatch):
    from backend import content_machine as cm

    # GEO-Artefakte duerfen im Test nicht in den echten Vault schreiben.
    monkeypatch.setattr(cm, "append_llms_txt", lambda *a, **k: str(tmp_path / "llms.txt"))

    db = _db(tmp_path)
    cm.init_content_machine_db(db)
    asset = cm.create_asset(_asset_payload(), db_path=db)

    approved = cm.approve_asset(
        asset["id"], decision_id="dec-1", actor="micha", role="reviewer", db_path=db
    )
    assert approved["status"] == "approved"
    assert approved["reviewer"] == "micha"
    assert approved["decision_id"] == "dec-1"

    published = cm.mark_asset_published(asset["id"], actor="lisa", db_path=db)
    assert published["status"] == "published"
    assert published["publisher"] == "lisa"

    history = cm.approval_history(asset["id"], db_path=db)
    assert [row["action"] for row in history] == ["approved", "published"]
    assert history[0]["decision_id"] == "dec-1"
    assert history[0]["actor"] == "micha" and history[0]["role"] == "reviewer"
    assert history[1]["actor"] == "lisa" and history[1]["role"] == "publisher"


def test_approval_helpers_are_backward_compatible(tmp_path, monkeypatch):
    from backend import content_machine as cm

    monkeypatch.setattr(cm, "append_llms_txt", lambda *a, **k: str(tmp_path / "llms.txt"))
    db = _db(tmp_path)
    cm.init_content_machine_db(db)
    asset = cm.create_asset(_asset_payload(), db_path=db)
    # Alte Aufrufer ohne actor/role duerfen nicht brechen.
    cm.approve_asset(asset["id"], db_path=db)
    cm.mark_asset_published(asset["id"], db_path=db)
    assert len(cm.approval_history(asset["id"], db_path=db)) == 2


# ---------------------------------------------------------------------------
# 3. SKILLS INJECTION INTO DAG
# ---------------------------------------------------------------------------

def test_skill_rules_injected_and_review_node_wired(tmp_path, monkeypatch):
    from backend import content_machine as cm

    skill_dir = tmp_path / ".agents" / "skills" / "li-human"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: li-human\ndescription: Testskill\n---\n"
        "## Regeln\n"
        "- Entferne Gedankenstriche komplett\n"
        "- Keine Emojis in Hashtag-Waenden\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cm, "WORKSPACE_DIR", str(tmp_path))

    dag = cm.build_content_repurposing_dag(
        {"id": "camp-skill", "title": "Skill-Test", "channels": ["linkedin"]}
    )
    channel = next(n for n in dag["nodes"] if n["id"] == "n_ch_linkedin")
    assert "Entferne Gedankenstriche komplett" in channel["prompt"]
    assert "Kanal-Regeln" in channel["prompt"]  # best_practices bleiben erhalten

    review = next(n for n in dag["nodes"] if n["id"] == "n_li_human_review")
    assert review["type"] == "agent"
    assert review["skill"] == "li-human"
    assert "Entferne Gedankenstriche komplett" in review["prompt"]

    gate = next(n for n in dag["nodes"] if n["id"] == "n_editorial_gate")
    assert gate["depends_on"] == ["n_li_human_review"]
    assert any(
        e["from"] == "n_ch_linkedin" and e["to"] == "n_li_human_review"
        for e in dag["edges"]
    )
    assert any(
        e["from"] == "n_li_human_review" and e["to"] == "n_editorial_gate"
        for e in dag["edges"]
    )


def test_missing_skill_file_degrades_gracefully(tmp_path, monkeypatch):
    from backend import content_machine as cm

    monkeypatch.setattr(cm, "WORKSPACE_DIR", str(tmp_path))
    block = cm._extract_skill_rules("li-human", workspace_dir=str(tmp_path))
    assert "nicht gefunden" in block

    # Ohne Skill-Dateien darf der DAG trotzdem gebaut werden.
    dag = cm.build_content_repurposing_dag(
        {"id": "camp-noskill", "title": "Ohne Skill", "channels": ["linkedin"]}
    )
    assert any(n["id"] == "n_li_human_review" for n in dag["nodes"])


# ---------------------------------------------------------------------------
# 4. GEO CITATION CHECK AFTER 48h
# ---------------------------------------------------------------------------

def test_check_geo_citations_aged_and_missing(tmp_path):
    from backend import content_machine as cm

    db = _db(tmp_path)
    cm.init_content_machine_db(db)
    good = cm.create_asset(_asset_payload(title="Gut"), db_path=db)
    bad = cm.create_asset(_asset_payload(title="Schlecht"), db_path=db)

    old = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=72)).isoformat()
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE content_assets SET status='published', published_at=?, geo_jsonld_json=? WHERE id=?",
            (old, json.dumps({"@type": "Article", "citation": ["https://ok.test/a"]}), good["id"]),
        )
        conn.execute(
            "UPDATE content_assets SET status='published', published_at=?, geo_jsonld_json=? WHERE id=?",
            (
                old,
                json.dumps({"@type": "Article", "citation": ["https://ok.test/a", "https://missing.test/b"]}),
                bad["id"],
            ),
        )

    report = cm.check_geo_citations(hours=48, db_path=db)
    assert report["assets_checked"] == 2
    assert report["citations_checked"] == 3
    assert report["citations_missing"] == 1
    assert report["assets_with_missing"] == 1

    good_report = next(r for r in report["reports"] if r["asset_id"] == good["id"])
    bad_report = next(r for r in report["reports"] if r["asset_id"] == bad["id"])
    assert good_report["passed"] is True
    assert bad_report["passed"] is False
    assert "https://missing.test/b" in bad_report["missing"]

    with sqlite3.connect(db) as conn:
        stored = conn.execute(
            "SELECT citation_check_json FROM content_assets WHERE id = ?", (bad["id"],)
        ).fetchone()[0]
    assert "https://missing.test/b" in stored


# ---------------------------------------------------------------------------
# 5. SOURCE ASSERTIONS (MIGRATIONS / COLUMNS / ENDPOINTS)
# ---------------------------------------------------------------------------

def test_batch_d_source_declarations_present():
    cm_src = (REPO_ROOT / "backend" / "content_machine.py").read_text(encoding="utf-8")
    for token in (
        "dossier_path TEXT DEFAULT ''",
        "author TEXT DEFAULT ''",
        "reviewer TEXT DEFAULT ''",
        "publisher TEXT DEFAULT ''",
        "citation_check_json TEXT DEFAULT '{}'",
        "CREATE TABLE IF NOT EXISTS content_asset_approvals",
        "def approval_history(",
        "def check_geo_citations(",
        "def _skill_rules_for_channel(",
        '"n_li_human_review"',
    ):
        assert token in cm_src, token

    rev_src = (REPO_ROOT / "research_engine_v2.py").read_text(encoding="utf-8")
    assert "def save_dossier_for_result(" in rev_src
    assert "base.build_and_save_dossier(" in rev_src

    dag_src = (REPO_ROOT / "backend" / "workflow_dag_runner.py").read_text(encoding="utf-8")
    assert "save_dossier_for_result(result, query)" in dag_src
    assert '"dossier_path": dossier_path' in dag_src

    router_src = (REPO_ROOT / "archon" / "routers" / "content_machine.py").read_text(encoding="utf-8")
    assert '"/api/v2/content-machine/assets/{asset_id}/approvals"' in router_src
    assert '"/api/v2/content-machine/geo/citation-check"' in router_src
