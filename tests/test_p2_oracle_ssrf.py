"""Regressionstests: Oracle News Radar mit SSRF-sicherem Client und dynamischem GitHub-Cutoff."""
from __future__ import annotations

import datetime
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

ORACLE_SRC = REPO_ROOT / "oracle_news_radar.py"


def test_p2_oracle_uses_central_safe_http_client():
    """Kein roher urlopen mehr; der zentrale SSRF-Client wird mit public_only genutzt."""
    src = ORACLE_SRC.read_text(encoding="utf-8")
    assert "urllib.request.urlopen" not in src
    assert "from utils.safe_http import safe_http_json" in src
    assert "public_only=True" in src
    assert "2026-10-01" not in src


def test_p2_oracle_fetch_url_returns_json_and_is_public_only(monkeypatch):
    import oracle_news_radar

    captured = {}

    def fake_safe_http_json(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return {"ok": True, "value": 42}

    monkeypatch.setattr(oracle_news_radar, "safe_http_json", fake_safe_http_json)
    radar = oracle_news_radar.OracleNewsRadar()

    result = radar._fetch_url("https://example.com/api", timeout=7)
    assert result == {"ok": True, "value": 42}
    assert captured["url"] == "https://example.com/api"
    assert captured["kwargs"]["public_only"] is True
    assert captured["kwargs"]["timeout"] == 7


def test_p2_oracle_fetch_url_returns_none_on_error(monkeypatch, capsys):
    import oracle_news_radar

    def boom(url, **kwargs):
        raise RuntimeError("Netzwerk nicht erreichbar")

    monkeypatch.setattr(oracle_news_radar, "safe_http_json", boom)
    radar = oracle_news_radar.OracleNewsRadar()

    assert radar._fetch_url("https://example.com/api") is None
    assert "[ORACLE] Fetch error for https://example.com/api:" in capsys.readouterr().err


def test_p2_oracle_github_query_uses_dynamic_30_day_cutoff(monkeypatch):
    """Die GitHub-Suche darf kein hart codiertes Datum enthalten."""
    import oracle_news_radar

    urls = []

    def fake_safe_http_json(url, **kwargs):
        urls.append(url)
        return {"items": []}

    monkeypatch.setattr(oracle_news_radar, "safe_http_json", fake_safe_http_json)
    radar = oracle_news_radar.OracleNewsRadar()
    radar.fetch_github_trending(limit=8)

    assert urls, "Es wurde kein HTTP-Request ausgeloest."
    url = urls[0]
    assert "2026-10-01" not in url
    # Rest der Query muss erhalten bleiben.
    assert "agentic+OR+llm+pushed:>" in url
    assert "sort=stars&order=desc&per_page=12" in url

    match = re.search(r"pushed:>(\d{4}-\d{2}-\d{2})", url)
    assert match is not None, "Kein dynamisches pushed:-Datum in der URL gefunden."
    cutoff = datetime.date.fromisoformat(match.group(1))
    today = datetime.datetime.now(datetime.timezone.utc).date()
    expected = today - datetime.timedelta(days=30)
    assert abs((cutoff - expected).days) <= 1
