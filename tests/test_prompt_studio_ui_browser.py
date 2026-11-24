# -*- coding: utf-8 -*-
"""Audit D08/E2E: Prompt-Studio-Batching im echten Browser (Playwright/Chromium)."""
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_prompt_studio_batches_and_debounce_in_chromium():
    spec = ROOT / "tests" / "ui" / "prompt_studio_batches.js"
    assert spec.is_file()
    env = os.environ.copy()
    env["NODE_PATH"] = str(ROOT / "node_modules")
    try:
        proc = subprocess.run(
            ["node", str(spec)], cwd=str(ROOT), env=env,
            capture_output=True, text=True, timeout=120,
        )
    except FileNotFoundError:
        pytest.skip("node nicht verfuegbar")
    if "SKIP: Chromium nicht installiert" in proc.stdout:
        pytest.skip("Chromium nicht installiert")
    assert proc.returncode == 0, (proc.stdout + "\n" + proc.stderr)
    assert "OK:" in proc.stdout, proc.stdout
