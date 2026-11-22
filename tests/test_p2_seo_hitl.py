"""Regressionstests fuer Batch C: SEO-Direkt-Publish abschalten (HITL).

Der SEO-Execution-Agent erzeugt nur noch Entwuerfe (``review``). Veroeffentlicht
wird ausschliesslich ueber die HITL-Freigabe ``mark_asset_published``.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SEO_AGENT_SRC = REPO_ROOT / "seo_execution_agent.py"
ORACLE_SEO_SRC = REPO_ROOT / "archon" / "routers" / "oracle_seo.py"


def _agent():
    from seo_execution_agent import SEOExecutionAgent

    return SEOExecutionAgent()


# ---------------------------------------------------------------------------
# Quellcode-Assertions (Statik)
# ---------------------------------------------------------------------------


def test_p2_seo_no_published_frontmatter_literal():
    src = SEO_AGENT_SRC.read_text(encoding="utf-8")
    assert 'status: "published"' not in src
    assert 'status: "review"' in src
    assert "approval_required: true" in src


def test_p2_seo_no_publish_cms_auto_trigger():
    src = SEO_AGENT_SRC.read_text(encoding="utf-8")
    assert "publish_cms" not in src
    assert 'target_action="draft_cms"' in src
    assert "trigger_n8n: bool = False" in src


def test_p2_seo_generate_requires_admin_and_forwards_serp():
    src = ORACLE_SEO_SRC.read_text(encoding="utf-8")
    assert "require_admin_or_503" in src
    assert "request: Request" in src
    assert "require_admin_or_503(request)" in src
    assert 'serp_analysis = payload.get("serp_analysis")' in src
    assert "serp_analysis=serp_analysis" in src


# ---------------------------------------------------------------------------
# Offline-Unit-Tests
# ---------------------------------------------------------------------------


def test_p2_seo_frontmatter_is_review_and_approval_required():
    agent = _agent()
    blueprint = agent.plan_seo_blueprint("Agentic OS", "Agentic OS")
    md = agent.generate_article_markdown(blueprint)

    assert 'status: "review"' in md
    assert "approval_required: true" in md
    assert 'outline_source: "template_fallback"' in md
    assert "serp_analyzed: false" in md


def test_p2_seo_serp_derived_outline_is_used():
    agent = _agent()
    serp_analysis = {
        "query": "agentic os",
        "headings": ["Was ist Agentic OS?", "Architektur", "Praxis"],
        "people_also_ask": ["Wie startet man?"],
    }

    blueprint = agent.plan_seo_blueprint(
        "Agentic OS", "Agentic OS", serp_analysis=serp_analysis
    )

    assert blueprint["outline_source"] == "serp"
    assert blueprint["serp_analyzed"] is True
    titles = [entry["title"] for entry in blueprint["outline"]]
    assert titles[:3] == ["Was ist Agentic OS?", "Architektur", "Praxis"]
    assert "Wie startet man?" in titles
    assert blueprint["serp_sources"]["headings"] == 3
    assert blueprint["serp_sources"]["people_also_ask"] == 1

    md = agent.generate_article_markdown(blueprint)
    assert 'outline_source: "serp"' in md
    assert "serp_analyzed: true" in md


def test_p2_seo_fallback_marks_template_and_not_analyzed():
    agent = _agent()
    blueprint = agent.plan_seo_blueprint("Agentic OS", "Agentic OS")

    assert blueprint["outline_source"] == "template_fallback"
    assert blueprint["serp_analyzed"] is False
    assert blueprint["serp_sources"] == {}
    assert len(blueprint["outline"]) == 5


def test_p2_seo_pipeline_never_auto_publishes(tmp_path, monkeypatch):
    import seo_execution_agent as seo_mod

    monkeypatch.setattr(seo_mod, "CONTENT_DIR", tmp_path)
    calls = {}

    class _StubDispatcher:
        @staticmethod
        async def trigger_n8n_execution(**kwargs):
            calls.update(kwargs)
            return {"status": "queued"}

    monkeypatch.setitem(sys.modules, "core_dispatcher", _StubDispatcher())

    agent = seo_mod.SEOExecutionAgent()
    result = asyncio.run(
        agent.execute_content_pipeline(
            "Agentic OS",
            "Agentic OS",
            trigger_n8n=True,
            serp_analysis={"headings": ["SERP-Überschrift"]},
        )
    )

    assert result["status"] == "review"
    assert result["approval_required"] is True
    assert result["outline_source"] == "serp"
    assert result["serp_analyzed"] is True
    assert "mark_asset_published" in result["publish_hint"]
    assert calls["target_action"] == "draft_cms"

    written = Path(result["vault_path"])
    assert 'status: "review"' in written.read_text(encoding="utf-8")


def test_p2_seo_pipeline_default_skips_n8n(tmp_path, monkeypatch):
    import seo_execution_agent as seo_mod

    monkeypatch.setattr(seo_mod, "CONTENT_DIR", tmp_path)

    def _boom(*args, **kwargs):
        raise AssertionError("n8n darf ohne expliziten Trigger nicht aufgerufen werden.")

    monkeypatch.setitem(sys.modules, "core_dispatcher", _boom)

    result = asyncio.run(
        seo_mod.SEOExecutionAgent().execute_content_pipeline("Agentic OS", "Agentic OS")
    )
    assert result["n8n_dispatch"] == {"status": "skipped"}
    assert result["outline_source"] == "template_fallback"
