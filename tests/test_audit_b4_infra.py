"""Audit B4: kein Schein-Worker, Tenant-DBs in Backup und Replikation."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_no_sleeping_placeholder_worker_in_compose():
    for name in ("docker-compose.yml", "docker-compose.dev.yml"):
        text = (ROOT / name).read_text(encoding="utf-8")
        # Nur noch erklaerende Kommentare duerfen den Platzhalter erwaehnen.
        for line in text.splitlines():
            if "sleep(86400)" in line:
                assert line.strip().startswith("#"), f"{name}: aktiver Platzhalter"


def test_backup_discovers_tenant_dbs():
    text = (ROOT / "backup_archon.py").read_text(encoding="utf-8")
    assert "data/tenants" in text
    assert "tenant_{_tid}_{_db}" in text
    ast.parse(text)


def test_litestream_watches_tenants():
    text = (ROOT / "config" / "litestream.yml").read_text(encoding="utf-8")
    assert "dir: /app/data/tenants" in text
    assert "watch: true" in text
