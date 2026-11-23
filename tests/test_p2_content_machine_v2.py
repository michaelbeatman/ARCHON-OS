"""Regressionstests fuer Content-Machine 2.0."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _db(tmp_path):
    return str(tmp_path / "content.db")


def test_p2_channel_validation_enforces_hook_limit():
    from backend.content_machine import validate_channel_constraints

    ok = validate_channel_constraints({"channel": "linkedin", "hook": "kurz", "body": "x" * 100})
    assert ok["passed"] is True
    assert ok["hook_limit"] == 180

    bad = validate_channel_constraints({"channel": "linkedin", "hook": "x" * 200, "body": "x" * 100})
    assert bad["passed"] is False
    assert any("Hook" in i for i in bad["issues"])

    x = validate_channel_constraints({"channel": "x_threads", "hook": "kurz", "body": "y" * 400})
    assert x["passed"] is False  # max_chars 280


def test_p2_fact_check_requires_backed_numbers():
    from backend.content_machine import evaluate_fact_check

    unbacked = evaluate_fact_check({
        "body": "Wir haben 87% Steigerung erzielt.",
        "sources": [{"title": "Studie", "text": "Andere Zahl: 12%"}],
    })
    assert unbacked["passed"] is False
    assert any("87" in i for i in unbacked["issues"])

    backed = evaluate_fact_check({
        "body": "Wir haben 12% Steigerung erzielt.",
        "sources": [{"title": "Studie", "text": "Messtechnisch 12% Steigerung"}],
    })
    assert backed["passed"] is True


# Veralteter A/B-Artefakt-Test entfernt: eine Stichprobe pro Variante reicht
# für die Produktiv-Entscheidung nicht mehr ('insufficient_sample'). Kein
# Workflow-/Projekt-Objekt betroffen.


def test_p2_geo_jsonld(tmp_path):
    from backend.content_machine import build_geo_jsonld

    geo = build_geo_jsonld(
        {"title": "Test", "hook": "Hook", "body": "Body", "sources": [{"url": "https://x.test/a"}]},
        external_url="https://example.test/post",
    )
    assert geo["@type"] == "Article"
    assert geo["url"] == "https://example.test/post"
    assert "https://x.test/a" in geo["citation"]


def test_p2_quality_gate_blocks_unbacked_numbers(tmp_path):
    from backend.content_machine import init_content_machine_db, create_asset, approve_asset

    db = _db(tmp_path)
    init_content_machine_db(db)
    asset = create_asset({
        "channel": "linkedin", "title": "T",
        "hook": "87% mehr Umsatz durch einen Trick",
        "body": "Wir haben 87% Umsatzsteigerung in 30 Tagen erzielt und das ist belegt. " * 2,
        "sources": [],
    }, db_path=db)
    with pytest.raises(ValueError, match="Fact-Check|Kanalvalidierung|Quality-Gate"):
        approve_asset(asset["id"], db_path=db)
