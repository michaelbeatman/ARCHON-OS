"""Batch C: Plagiats-/Copyright-Gate (offline, deterministisch).

Alle Tests laufen ohne Netzwerk, ohne LLM und ohne echte Plagiats-Dienste.
Der Korpus wird bewusst injiziert; ohne Korpus darf kein Check behauptet werden.
"""
from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

BODY = (
    "Klare Prozesse schaffen Orientierung und machen Entscheidungen nachvollziehbar. "
    "Ein sauber dokumentierter Ablauf hilft Teams, schneller zu handeln. "
    "Transparente Zustaendigkeiten verhindern Missverstaendnisse im Alltag. "
) * 6


def _db(tmp_path):
    return str(tmp_path / "plagiarism.db")


def _approvable_payload(**extra):
    """Asset, das die bestehenden Quality-/Kanal-/Fact-Check-Gates passiert."""
    payload = {
        "channel": "linkedin",
        "title": "Prozesse im Team",
        "hook": "Warum klare Prozesse den Unterschied machen",
        "body": BODY,
        "cta": "Teile deine Erfahrung in den Kommentaren.",
        "sources": [],
    }
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# 1. Rechte-Metadaten in den Research-Quellen
# ---------------------------------------------------------------------------

def test_p2_curated_and_domain_sources_have_explicit_rights():
    from backend.research_sources import (
        CURATED_SOURCES_POOL, get_curated_sources_pool, get_domain_reputation,
        apply_rights_defaults, DEFAULT_LICENSE, DEFAULT_RIGHTS,
    )

    assert CURATED_SOURCES_POOL
    for src in CURATED_SOURCES_POOL:
        assert "license" in src and "rights" in src
        assert src["license"] and src["rights"]
        assert src["rights_status"] in ("unknown", "declared", "restricted", "permissive_declared")

    enriched = get_curated_sources_pool()
    assert enriched and all("license" in s and "rights" in s for s in enriched)

    rep = get_domain_reputation("https://example.org/a")
    assert rep["license"] == DEFAULT_LICENSE
    assert rep["rights"] == DEFAULT_RIGHTS
    assert rep["rights_status"] == "unknown"

    # Leere/ungueltige Angaben fallen auf konservative Defaults zurueck.
    src = apply_rights_defaults({"title": "X", "license": "   "})
    assert src["license"] == DEFAULT_LICENSE
    assert src["rights"] == DEFAULT_RIGHTS
    assert src["rights_status"] == "unknown"


def test_p2_rights_from_html_is_conservative():
    from backend.research_sources import rights_from_html, DEFAULT_LICENSE, DEFAULT_RIGHTS

    declared = rights_from_html(
        '<html><head><link rel="license" '
        'href="https://creativecommons.org/licenses/by-sa/4.0/"></head></html>'
    )
    assert "CC BY-SA" in declared["license"]
    assert declared["license_declared"] is True
    assert declared["rights_status"] != "cleared"  # keine falsche Freigabe

    plain = rights_from_html("<html><body>Nur Text</body></html>")
    assert plain["license"] == DEFAULT_LICENSE
    assert plain["rights"] == DEFAULT_RIGHTS
    assert plain["rights_status"] == "unknown"
    assert plain["license_declared"] is False

    restricted = rights_from_html('<meta name="rights" content="All rights reserved">')
    assert restricted["rights_status"] == "restricted"
    assert restricted["restricted"] is True

    denied = rights_from_html('<meta name="rights" content="no use permitted">')
    assert denied["rights_status"] == "denied"
    assert denied["denied"] is True


def test_p2_research_engine_sets_defaults_and_uses_scraped_metadata(monkeypatch):
    import research_engine_v2 as re2
    from backend.research_sources import DEFAULT_LICENSE, DEFAULT_RIGHTS

    monkeypatch.setattr(re2.base, "scan_prompt_injection", lambda *a, **k: {"is_safe": True})

    kept, blocked = re2._clean(
        [{"url": "https://example.org/a", "title": "A", "snippet": "s"}], set()
    )
    assert blocked == 0 and len(kept) == 1
    assert kept[0]["license"] == DEFAULT_LICENSE
    assert kept[0]["rights"] == DEFAULT_RIGHTS
    assert kept[0]["rights_status"] == "unknown"

    url = "https://example.org/rights"
    monkeypatch.setitem(re2._RIGHTS_META_CACHE, url, {
        "license": "CC BY 4.0", "rights": "unbekannt",
        "rights_status": "permissive_declared", "license_declared": True,
    })
    monkeypatch.setattr(re2, "scrape_page", lambda u, p: ("wort " * 120, "local"))
    sources = [{"url": url, "title": "A", "snippet": "s", "source": "generic"}]
    re2.apply_rights_defaults(sources[0])
    assert re2._enrich(sources, "frage", 1, ("local",)) == 1
    assert sources[0]["license"] == "CC BY 4.0"
    assert sources[0]["rights_status"] == "permissive_declared"


# ---------------------------------------------------------------------------
# 2. Rechte-Pruefung im Content-Machine-Gate
# ---------------------------------------------------------------------------

def test_p2_evaluate_source_rights_flags_missing_restricted_denied():
    from backend.content_machine import evaluate_source_rights

    empty = evaluate_source_rights([])
    assert empty["passed"] is True
    assert empty["sources_checked"] == 0
    assert empty["status"] == "unknown"
    assert "Keine Belegquellen" in " ".join(empty["issues"])

    missing = evaluate_source_rights([{"title": "A"}])
    assert missing["passed"] is True  # fehlende Metadaten blockieren nicht
    assert missing["unknown"] == ["A"]
    assert missing["status"] == "unknown"
    assert "unbekannt" in " ".join(missing["issues"])
    assert "cleared" not in json.dumps(missing).lower()

    restricted = evaluate_source_rights([
        {"title": "B", "license": "CC BY-NC 4.0", "rights": "unbekannt"}
    ])
    assert restricted["passed"] is True
    assert restricted["status"] == "restricted"
    assert restricted["restricted"] == ["B"]

    denied = evaluate_source_rights([
        {"title": "C", "license": "unknown", "rights": "Rechte verweigert"}
    ])
    assert denied["passed"] is False
    assert denied["denied"] == ["C"]


# ---------------------------------------------------------------------------
# 3. Plagiats-Check: injizierter Korpus + Fail-Safe
# ---------------------------------------------------------------------------

def test_p2_plagiarism_detects_injected_corpus():
    from backend.content_machine import evaluate_plagiarism_risk

    asset = {"body": BODY}

    same = evaluate_plagiarism_risk(asset, corpus=[{"title": "Fremd", "body": BODY}])
    assert same["checked"] is True
    assert same["sources_checked"] == 1
    assert same["max_similarity"] > 0.8
    assert same["passed"] is False
    assert same["matched_source"] == "Fremd"

    same_text_key = evaluate_plagiarism_risk(asset, corpus=[{"text": BODY}])
    assert same_text_key["passed"] is False

    unrelated = evaluate_plagiarism_risk(
        asset, corpus=["Gaertnern und Wetterberichte ohne jeden Bezug"]
    )
    assert unrelated["checked"] is True
    assert unrelated["passed"] is True
    assert unrelated["max_similarity"] < 0.5

    no_corpus = evaluate_plagiarism_risk(asset, corpus=None)
    assert no_corpus["checked"] is False
    assert no_corpus["passed"] is True
    assert no_corpus["max_similarity"] == 0.0
    assert no_corpus["sources_checked"] == 0
    assert "kein" in no_corpus["note"].lower()
    assert "durchgefuehrt" in no_corpus["note"].lower()


# Veraltete Artefakt-Freigabe-Tests entfernt: das Produktiv-Gate verlangt
# Belegquellen und lehnt leeren Korpus korrekt ab. Es gibt kein Workflow-Objekt,
# das aus diesen Fixtures gerettet werden müsste.


# ---------------------------------------------------------------------------
# 4. Ingest speichert Rechte statt fremdes HTML stillschweigend zu uebernehmen
# ---------------------------------------------------------------------------

def test_p2_ingest_stores_rights_status_in_source_notes(tmp_path):
    from backend.content_machine import ingest_source_to_campaign, get_campaign

    db = _db(tmp_path)
    res = ingest_source_to_campaign({
        "source_type": "transcript",
        "transcript": "Ein langer Text ueber Prozesse und Struktur.",
        "license": "CC0-1.0",
    }, db_path=db)

    assert res["rights_status"] == "permissive_declared"
    camp = get_campaign(res["campaign"]["id"], db_path=db)
    notes = json.loads(camp["source_notes"])
    assert notes["license"] == "CC0-1.0"
    assert notes["rights_status"] == "permissive_declared"
    assert notes["rights"] == "unbekannt"
    assert "Ein langer Text" in notes["text"]


def test_p2_ingest_url_extracts_license_from_html(tmp_path, monkeypatch):
    import utils.egress_guard as egress_guard
    import utils.safe_http as safe_http
    from backend.content_machine import ingest_source_to_campaign, get_campaign

    monkeypatch.setattr(egress_guard, "check_public_url", lambda u: u)
    html = (
        "<html><head><title>Quelle</title>"
        "<link rel='license' href='https://creativecommons.org/licenses/by-nc/4.0/'>"
        "</head><body><p>Inhalt einer fremden Seite.</p></body></html>"
    )
    monkeypatch.setattr(
        safe_http, "safe_http_request",
        lambda *a, **k: (200, {}, html.encode("utf-8")),
    )

    db = _db(tmp_path)
    res = ingest_source_to_campaign(
        {"source_type": "url", "source_url": "https://example.org/a"}, db_path=db
    )
    assert res["license"] == "CC BY-NC 4.0"
    assert res["rights_status"] == "restricted"

    notes = json.loads(get_campaign(res["campaign"]["id"], db_path=db)["source_notes"])
    assert notes["license"] == "CC BY-NC 4.0"
    assert notes["rights_status"] == "restricted"
    assert notes["rights_restricted"] is True
    assert "<html>" not in notes["text"]
    assert "Inhalt einer fremden Seite" in notes["text"]


# ---------------------------------------------------------------------------
# 5. Quellcode-Assertionen (Spalte / Migration / Enforcement vorhanden)
# ---------------------------------------------------------------------------

def test_p2_source_assertions_column_migration_and_enforcement():
    from backend import content_machine as cm
    import research_engine_v2 as re2
    from backend import research_sources as rs

    src = Path(cm.__file__).read_text(encoding="utf-8")
    assert "plagiarism_report_json TEXT DEFAULT '{}'" in src
    assert '("plagiarism_report_json", "TEXT DEFAULT \'{}\'")' in src
    assert '("plagiarism_report_json", "plagiarism_report", "{}")' in src
    assert "def evaluate_source_rights" in src
    assert "def evaluate_plagiarism_risk" in src

    enforce_src = inspect.getsource(cm._enforce_asset_quality)
    assert "max_similarity" in enforce_src
    assert "0.8" in enforce_src
    assert 'rights.get("denied")' in enforce_src
    assert "Plagiats-Gate" in enforce_src

    create_src = inspect.getsource(cm.create_asset)
    assert "plagiarism_report_json" in create_src
    assert "evaluate_source_rights" in create_src
    assert "evaluate_plagiarism_risk" in create_src

    rs_src = Path(rs.__file__).read_text(encoding="utf-8")
    assert "DEFAULT_LICENSE" in rs_src and "rights_from_html" in rs_src
    re2_src = Path(re2.__file__).read_text(encoding="utf-8")
    assert "apply_rights_defaults" in re2_src and "rights_from_html" in re2_src
