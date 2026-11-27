"""M72 — Modellabhängiges Task-Sizing & Skills auf Leihbasis.

Prüft:
- Fenster-SSOT aus M99 (128k / 200k / 1M / Fallback 32k) ohne Duplicate,
- deterministische Chunk-Grenzen, Overlap und harte Obergrenze,
- Leih-/Rückgabe im kv_store inkl. Exception, TTL und Duplikatfreiheit,
- Additivität der Budget-Engine (Ceilings unverändert, keine Buchung).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, List

import pytest

from backend import llm_prices, task_sizing
from backend import role_budget_engine as rbe
from backend.context_compactor import DEFAULT_MAX_CONTEXT_TOKENS


@pytest.fixture()
def kv_db(tmp_path: Path) -> str:
    """Bestehende kv_store-Tabelle mit realistischem Schema (kein Upgrade)."""
    path = tmp_path / "agentic_memory.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE kv_store ("
            "key TEXT PRIMARY KEY, value TEXT NOT NULL, "
            "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        )
    return str(path)


@pytest.fixture()
def skill_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    base = tmp_path / "skills"
    for name in ("li-post", "seo-audit", "simplify-code"):
        (base / name).mkdir(parents=True)
    monkeypatch.setattr(task_sizing, "SKILLS_DIR", str(base))
    return base


def _lease_rows(db_path: str) -> List[Any]:
    with sqlite3.connect(db_path) as conn:
        return conn.execute(
            "SELECT key, value FROM kv_store WHERE key LIKE ?",
            (f"{task_sizing.TASK_SKILL_LEASE_PREFIX}%",),
        ).fetchall()


# ---------------------------------------------------------------------------
# 1. Fenster-SSOT: 128k / 200k / 1M + defensiver 32k-Fallback
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "model,expected",
    [
        ("openai/gpt-4o", 128_000),
        ("deepseek/deepseek-chat", 128_000),
        ("anthropic/claude-3.5-sonnet", 200_000),
        ("openai/o3-mini", 200_000),
        ("google/gemini-2.5-pro", 1_000_000),
        ("openai/gpt-4.1", 1_000_000),
        ("ollama/unknown-local-7b", DEFAULT_MAX_CONTEXT_TOKENS),
        ("", DEFAULT_MAX_CONTEXT_TOKENS),
        (None, DEFAULT_MAX_CONTEXT_TOKENS),
    ],
)
def test_resolve_context_window_delegates_to_m99_ssot(
    monkeypatch: pytest.MonkeyPatch, model: Any, expected: int
) -> None:
    monkeypatch.setattr(llm_prices, "_price_cache", None)
    assert task_sizing.resolve_context_window(model) == expected


def test_resolve_context_window_passes_metadata_and_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm_prices, "_price_cache", None)
    assert (
        task_sizing.resolve_context_window(
            "ollama/local", provider_metadata={"context_length": 65536}
        )
        == 65536
    )
    assert task_sizing.resolve_context_window("ollama/local", configured_override=16384) == 16384


def test_resolve_context_window_fallback_on_ssot_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(*_args: Any, **_kwargs: Any) -> int:
        raise RuntimeError("M99 nicht erreichbar")

    monkeypatch.setattr(task_sizing, "_resolve_m99", broken)
    assert (
        task_sizing.resolve_context_window("openai/gpt-4o") == DEFAULT_MAX_CONTEXT_TOKENS
    )
    monkeypatch.setattr(task_sizing, "_resolve_m99", lambda *_a, **_k: -1)
    assert (
        task_sizing.resolve_context_window("openai/gpt-4o") == DEFAULT_MAX_CONTEXT_TOKENS
    )


# ---------------------------------------------------------------------------
# 2. Chunk-Grenzen, Overlap, harte Obergrenze, Determinismus
# ---------------------------------------------------------------------------


def test_size_chunks_scales_with_all_supported_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm_prices, "_price_cache", None)
    capacities: List[int] = []
    for model, window in (
        ("openai/gpt-4o", 128_000),
        ("anthropic/claude-3.5-sonnet", 200_000),
        ("google/gemini-2.5-pro", 1_000_000),
        ("ollama/unknown-local", DEFAULT_MAX_CONTEXT_TOKENS),
    ):
        result = task_sizing.size_chunks("k" * 2000, model)
        assert result["context_window"] == window
        assert result["max_chunk_tokens"] <= window
        assert result["max_chunk_tokens"] <= task_sizing.HARD_CHUNK_TOKEN_CEILING
        assert result["max_chunk_tokens"] >= window // 2
        capacities.append(result["max_chunk_tokens"])
    assert capacities[0] < capacities[1] < capacities[2]


def test_size_chunks_boundaries_overlap_and_estimates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm_prices, "_price_cache", None)
    text = "".join(f"[{i:05d}]" for i in range(4000))
    result = task_sizing.size_chunks(
        text,
        "ollama/local",
        configured_override=4096,
        overlap=64,
        max_chunk_tokens=1024,
    )
    assert result["context_window"] == 4096
    assert result["max_chunk_tokens"] == 1024
    assert result["overlap_tokens"] == 64
    assert result["total_chunks"] >= 3
    assert result["total_estimated_tokens"] >= result["original_estimated_tokens"]

    for chunk in result["chunks"]:
        assert chunk["char_end"] > chunk["char_start"]
        assert chunk["char_end"] - chunk["char_start"] <= 1024 * task_sizing.CHARS_PER_TOKEN
        assert chunk["estimated_tokens"] <= 1024
        assert chunk["text"] == text[chunk["char_start"]:chunk["char_end"]]

    overlap_chars = 64 * task_sizing.CHARS_PER_TOKEN
    for previous, following in zip(result["chunks"], result["chunks"][1:]):
        assert following["char_start"] == previous["char_end"] - overlap_chars
        assert following["text"][:overlap_chars] == text[
            following["char_start"]:previous["char_end"]
        ]


def test_size_chunks_deterministic_and_empty_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm_prices, "_price_cache", None)
    text = "deterministischer text " * 500
    first = task_sizing.size_chunks(text, "openai/gpt-4o", configured_override=4096, overlap=32)
    second = task_sizing.size_chunks(text, "openai/gpt-4o", configured_override=4096, overlap=32)
    assert first == second
    empty = task_sizing.size_chunks("", "openai/gpt-4o")
    assert empty["chunks"] == []
    assert empty["total_chunks"] == 0
    assert empty["total_estimated_tokens"] == 0


def test_size_chunks_hard_cap_and_overlap_cannot_stall(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm_prices, "_price_cache", None)
    text = "x" * 5000
    capped = task_sizing.size_chunks(
        text, "google/gemini-2.5-pro", max_chunk_tokens=1000, overlap=9000
    )
    assert capped["max_chunk_tokens"] == 1000
    assert capped["overlap_tokens"] == 999
    assert all(c["estimated_tokens"] <= 1000 for c in capped["chunks"])
    starts = [c["char_start"] for c in capped["chunks"]]
    assert len(starts) > 1
    assert all(a < b for a, b in zip(starts, starts[1:]))


# ---------------------------------------------------------------------------
# 3. Skills auf Leihbasis: Duplikate, Index, Rückgabe, TTL, Exception
# ---------------------------------------------------------------------------


def test_issue_skills_filters_index_and_deduplicates(
    kv_db: str, skill_index: Path
) -> None:
    issued = task_sizing.issue_skills(
        "task-1",
        ["li-post", "li-post", "seo-audit", "fremder-skill", ""],
        ttl_seconds=60,
        db_path=kv_db,
    )
    assert issued["skill_ids"] == ["li-post", "seo-audit"]
    assert issued["rejected_skill_ids"] == ["fremder-skill"]
    assert issued["status"] == "issued"
    assert task_sizing.get_active_skills("task-1", db_path=kv_db) == [
        "li-post",
        "seo-audit",
    ]
    assert len(_lease_rows(kv_db)) == 1


def test_reissue_replaces_lease_without_duplicates(kv_db: str, skill_index: Path) -> None:
    task_sizing.issue_skills("task-2", ["li-post", "seo-audit"], ttl_seconds=60, db_path=kv_db)
    again = task_sizing.issue_skills(
        "task-2", ["simplify-code", "simplify-code"], ttl_seconds=60, db_path=kv_db
    )
    assert again["skill_ids"] == ["simplify-code"]
    assert task_sizing.get_active_skills("task-2", db_path=kv_db) == ["simplify-code"]
    assert len(_lease_rows(kv_db)) == 1


def test_return_is_idempotent_and_task_scoped(kv_db: str, skill_index: Path) -> None:
    task_sizing.issue_skills("task-a", ["li-post"], ttl_seconds=60, db_path=kv_db)
    task_sizing.issue_skills("task-b", ["seo-audit"], ttl_seconds=60, db_path=kv_db)

    returned = task_sizing.return_skills("task-a", db_path=kv_db)
    assert returned["status"] == "returned"
    assert returned["skill_ids"] == ["li-post"]
    assert task_sizing.get_active_skills("task-a", db_path=kv_db) == []
    assert task_sizing.get_active_skills("task-b", db_path=kv_db) == ["seo-audit"]

    second = task_sizing.return_skills("task-a", db_path=kv_db)
    assert second["status"] == "none"
    assert second["skill_ids"] == []


def test_leased_skills_returns_on_success_and_exception(
    kv_db: str, skill_index: Path
) -> None:
    with task_sizing.leased_skills(
        "task-ctx", ["li-post"], ttl_seconds=60, db_path=kv_db
    ) as skills:
        assert skills == ["li-post"]
        assert task_sizing.get_active_skills("task-ctx", db_path=kv_db) == ["li-post"]
    assert task_sizing.get_active_skills("task-ctx", db_path=kv_db) == []

    with pytest.raises(RuntimeError, match="boom"):
        with task_sizing.leased_skills(
            "task-err", ["seo-audit"], ttl_seconds=60, db_path=kv_db
        ) as skills:
            assert skills == ["seo-audit"]
            raise RuntimeError("boom")
    assert task_sizing.get_active_skills("task-err", db_path=kv_db) == []
    assert _lease_rows(kv_db) == []


def test_ttl_expiry_auto_returns_and_reports_status(
    kv_db: str, skill_index: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = [1_000_000.0]
    monkeypatch.setattr(task_sizing, "_current_ts", lambda: clock[0])
    task_sizing.issue_skills("task-ttl", ["li-post"], ttl_seconds=10, db_path=kv_db)
    assert task_sizing.get_active_skills("task-ttl", db_path=kv_db) == ["li-post"]

    clock[0] += 11
    expired = task_sizing.return_skills("task-ttl", db_path=kv_db)
    assert expired["status"] == "expired"
    assert expired["expired"] is True
    assert expired["skill_ids"] == ["li-post"]
    assert _lease_rows(kv_db) == []


def test_purge_expired_leases_keeps_active_ones(
    kv_db: str, skill_index: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = [1_000_000.0]
    monkeypatch.setattr(task_sizing, "_current_ts", lambda: clock[0])
    task_sizing.issue_skills("short", ["li-post"], ttl_seconds=10, db_path=kv_db)
    task_sizing.issue_skills("long", ["seo-audit"], ttl_seconds=100, db_path=kv_db)

    clock[0] += 20
    assert task_sizing.purge_expired_leases(db_path=kv_db) == 1
    assert task_sizing.get_active_skills("short", db_path=kv_db) == []
    assert task_sizing.get_active_skills("long", db_path=kv_db) == ["seo-audit"]


def test_finalize_hook_returns_lease(kv_db: str, skill_index: Path) -> None:
    task_sizing.issue_skills("task-final", ["simplify-code"], ttl_seconds=60, db_path=kv_db)
    result = task_sizing.finalize_task_skills("task-final", db_path=kv_db)
    assert result["skill_ids"] == ["simplify-code"]
    assert task_sizing.get_active_skills("task-final", db_path=kv_db) == []


def test_invalid_arguments_fail_closed(kv_db: str, skill_index: Path) -> None:
    with pytest.raises(ValueError):
        task_sizing.issue_skills("", ["li-post"], ttl_seconds=1, db_path=kv_db)
    with pytest.raises(ValueError):
        task_sizing.issue_skills("task-x", ["li-post"], ttl_seconds=-1, db_path=kv_db)
    assert task_sizing.load_skill_index(str(skill_index)) == frozenset(
        {"li-post", "seo-audit", "simplify-code"}
    )


# ---------------------------------------------------------------------------
# 4. Budget-Additivität: Ceilings unverändert, keine Buchung
# ---------------------------------------------------------------------------


def test_estimate_task_sizing_is_pure_and_ceiling_invariants(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(llm_prices, "_price_cache", None)
    assert rbe.TASK_BUDGET_TOKEN_CEILING == 2_000_000
    assert rbe.TASK_BUDGET_COST_CEILING_EUR == 1_000.0

    budget_db = tmp_path / "budget.db"
    monkeypatch.setattr(rbe, "BUDGET_DB_PATH", str(budget_db))

    result = rbe.estimate_task_sizing(
        "a" * 4000,
        "openai/gpt-4o",
        token_budget=999,
        overlap=16,
        configured_override=4096,
    )
    assert result["total_estimated_tokens"] == 1000
    assert result["token_budget"] == 999
    assert result["fits_budget"] is False
    assert result["budget_utilization_pct"] == 100.1
    assert result["total_chunks"] >= 1
    # Rein: keine Ledger-/Budget-Tabelle wurde angelegt oder beschrieben.
    assert not budget_db.exists()

    without_budget = rbe.estimate_task_sizing("a" * 40, "openai/gpt-4o", token_budget=None)
    assert without_budget["fits_budget"] is None
    assert without_budget["token_budget"] is None
