"""P0 API-Validierung Etappe 2e: memory.py (10) + mesh.py (14)."""

import os
import sys

import pytest
from pydantic import ValidationError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from archon.routers import memory, mesh  # noqa: E402


def test_memory_models_validate_types():
    with pytest.raises(ValidationError):
        memory.MemoryHarvestRequest(text=123)
    with pytest.raises(ValidationError):
        memory.MemoryTripleRequest(confidence="sehr hoch")


def test_memory_compact_model_keeps_message_list():
    model = memory.MemoryCompactRequest(messages=[{"role": "user", "content": "hi"}], force=True)
    assert model.model_dump()["force"] is True


def test_mesh_models_validate_types():
    with pytest.raises(ValidationError):
        mesh.MeshDiffPreviewRequest(context_lines="drei")
    with pytest.raises(ValidationError):
        mesh.SandboxExecuteRequest(network_enabled="vielleicht")


def test_mesh_config_models_keep_arbitrary_fields():
    model = mesh.ConcurrencyConfigRequest(max_concurrent=7, custom_option="keep")
    dumped = model.model_dump()
    assert dumped["max_concurrent"] == 7
    assert dumped["custom_option"] == "keep"
