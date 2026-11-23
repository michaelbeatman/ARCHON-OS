"""Regressionstests: Stations-Konfigurationsschema (Drei-Spalten-Dialog / Kontext-Pakete)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def test_p2_plugin_schema_has_groups_and_advanced_flags():
    from backend.workflow_node_plugins import (
        get_plugin_schema, split_schema_fields,
    )

    schema = get_plugin_schema("ffmpeg")
    assert schema["plugin_id"] == "ffmpeg"
    assert schema["fields"]
    primary, advanced, groups = split_schema_fields(schema["fields"])
    assert primary and advanced
    assert "Schnitt" in groups and "Encode" in groups
    keys_primary = {f["key"] for f in primary}
    keys_advanced = {f["key"] for f in advanced}
    assert "mode" in keys_primary
    assert "crf" in keys_advanced
    assert not (keys_primary & keys_advanced)


def test_p2_resolve_node_config_merges_defaults_and_validates():
    from backend.workflow_node_plugins import (
        resolve_node_config, validate_node_config,
    )

    cfg = resolve_node_config("ffmpeg", {"crf": 23, "duration_sec": 12})
    assert cfg["crf"] == 23
    assert cfg["duration_sec"] == 12
    assert cfg["mode"] == "clip_cut"  # Default aus dem Plugin-Schema

    assert validate_node_config("ffmpeg", {"unknown_key": 1})
    assert validate_node_config("ffmpeg", {"crf": 999})  # oberhalb max
    with pytest.raises(ValueError, match="crf"):
        resolve_node_config("ffmpeg", {"crf": 999})


def test_p2_upstream_templates_are_resolved():
    from backend.workflow_node_plugins import resolve_node_config

    cfg = resolve_node_config(
        "ffmpeg",
        {"input_path": "{{upstream.step_1.video_path}}"},
        {"step_1": {"video_path": "/projects/in.mp4"}},
    )
    assert cfg["input_path"] == "/projects/in.mp4"


def test_p2_design_spec_documents_context_package_storage():
    doc = (REPO_ROOT / "docs" / "system" / "WORKFLOW_STATION_CONFIG_GUIDE.md").read_text(encoding="utf-8")
    assert "ctx_" in doc
    assert "data/context_packages" in doc
    assert "Drei-Spalten" in doc
