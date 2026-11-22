"""Regressionstest fuer den P2-Verdict-Fix im Research-DAG-Knoten.

research_engine_v2.run_research_mission_v2() liefert das Triangulations-Urteil
unter 'triangulation_verdict'. Der DAG-Knoten muss diesen Wert sowohl in der
gerenderten Ausgabe als auch im zurueckgegebenen 'verdict'-Feld verwenden und
daneben weiterhin den Legacy-Key 'verdict' unterstuetzen.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

VERDICT = "HOCH (3 unabhängige Quellen)"


def _realistic_result(verdict_key: str) -> dict:
    """Realistisches Ergebnis der Research-Engine (offline, ohne HTTP/LLM)."""
    return {
        "status": "ok",
        "synthesis": "Faktenbasierte Synthese aus drei unabhaengigen Quellen.",
        "sources": [
            {
                "title": "Quelle A",
                "url": "https://example.org/a",
                "domain": "example.org",
            }
        ],
        verdict_key: VERDICT,
    }


async def test_p2_research_node_uses_triangulation_verdict():
    """Der kanonische Key 'triangulation_verdict' erscheint in content und verdict."""
    from backend.workflow_dag_runner import _execute_research_dag_node

    fake = _realistic_result("triangulation_verdict")
    with patch(
        "research_engine_v2.run_research_mission_v2", return_value=fake
    ):
        res = await _execute_research_dag_node(
            {"id": "n_research", "type": "research", "query": "test"}, {}
        )

    assert res["verdict"] == VERDICT
    assert VERDICT in res["content"]
    assert res["status"] == "success"


async def test_p2_research_node_falls_back_to_legacy_verdict():
    """Legacy-Mocks mit 'verdict' bleiben kompatibel (Rueckwaerts-Kompatibilitaet)."""
    from backend.workflow_dag_runner import _execute_research_dag_node

    fake = _realistic_result("verdict")
    with patch(
        "research_engine_v2.run_research_mission_v2", return_value=fake
    ):
        res = await _execute_research_dag_node(
            {"id": "n_research", "type": "research", "query": "test"}, {}
        )

    assert res["verdict"] == VERDICT
    assert VERDICT in res["content"]
