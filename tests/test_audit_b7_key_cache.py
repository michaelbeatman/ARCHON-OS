"""Audit B7: Key-Scan nicht mehr bei jedem Dispatch."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_collect_keys_is_cached_and_invalidatable(monkeypatch):
    import api_provider as ap

    ap.invalidate_key_cache()
    calls = {"n": 0}
    original = ap._read_flat_env

    def counted(path):
        calls["n"] += 1
        return original(path)

    monkeypatch.setattr(ap, "_read_flat_env", counted)
    first = ap.collect_keys()
    n_after_first = calls["n"]
    assert n_after_first > 0
    second = ap.collect_keys()
    assert first == second
    assert calls["n"] == n_after_first, "zweiter Aufruf darf nicht erneut scannen"

    ap.invalidate_key_cache()
    ap.collect_keys()
    assert calls["n"] > n_after_first, "Invalidierung muss den Cache leeren"
    ap.invalidate_key_cache()
