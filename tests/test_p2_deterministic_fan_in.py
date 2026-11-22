"""Regressionstest: Fan-in-Synthese deterministisch statt LLM-Prompt (aggregation_lisa)."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def test_p2_fan_in_no_longer_dispatches_aggregation_lisa():
    src = (REPO_ROOT / "archon" / "core" / "orchestration.py").read_text(encoding="utf-8")
    assert 'agent_id="aggregation_lisa"' not in src
    assert "from backend.consensus_gate import resolve_debate_consensus" in src
    assert "fan_consensus = resolve_debate_consensus(fan_statements)" in src
    # Kein Reparatur-Retry mehr über ein LLM.
    assert "Marker-Repair an Lisa" not in src
    assert "_rres2" not in src
    assert "lisa_prompt" not in src


def test_p2_fan_in_keeps_marker_contract_and_structure():
    src = (REPO_ROOT / "archon" / "core" / "orchestration.py").read_text(encoding="utf-8")
    assert '_MARKER = "SYNTHESE-BEREIT"' in src
    assert "## Executive-Kurzfassung" in src
    assert "## Integriertes Ergebnis" in src
    assert "## Widersprueche & offene Punkte" in src
    assert "## Naechste Schritte" in src
