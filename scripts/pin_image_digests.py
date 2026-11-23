#!/usr/bin/env python3
"""Pinnt alle externen Docker-Images in docker-compose*.yml auf sha256-Digests.

Reproduzierbarkeit / Supply-Chain (Audit 23.11.2026):
Tags sind mutable — ein kompromittiertes oder überschriebenes Tag landet
unerkannt im Produktionsimage. Dieses Skript löst den aktuellen Index-Digest
via `docker buildx imagetools inspect` auf und schreibt ihn in die Compose-Datei.

Bereits gepinnte Images und lokal gebaute Images (ohne Registry-Slash) bleiben
unverändert. Idempotent: mehrfacher Lauf ist sicher.

Usage: python scripts/pin_image_digests.py [datei ...]
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

DEFAULT_FILES = ("docker-compose.yml", "docker-compose.dev.yml",
                 "docker-compose.demo.yml", "docker-compose.hermes.yml")
IMAGE_RE = re.compile(r"^(\s*image:\s*)(.+?)(\s*(?:#.*)?)$")
DIGEST_RE = re.compile(r"@sha256:[0-9a-f]{64}")
VAR_RE = re.compile(r"^\$\{([A-Z0-9_]+):-(.+)\}$")


def resolve_ref(raw: str) -> str | None:
    """Liefert den Registry-Ref aus einem (ggf. Env-default-)Image-Eintrag."""
    value = raw.strip()
    m = VAR_RE.match(value)
    if m:
        value = m.group(2)
    if "@sha256:" in value:
        return None  # bereits gepinnt
    # Offizielle Images ohne Namespace (z. B. 'caddy:2.8.4-alpine') sind
    # trotzdem Registry-Images; nur das lokal gebaute Archon-Image auslassen.
    if value.startswith("agent-os-container"):
        return None
    return value


def get_digest(ref: str) -> str | None:
    try:
        out = subprocess.run(
            ["docker", "buildx", "imagetools", "inspect", ref],
            capture_output=True, text=True, check=True, timeout=120,
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return None
    m = re.search(r"^\s*Digest:\s+(sha256:[0-9a-f]{64})", out, re.MULTILINE)
    return m.group(1) if m else None


def pin_file(path: Path) -> int:
    if not path.is_file():
        return 0
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    changed = 0
    for i, line in enumerate(lines):
        stripped = line.rstrip("\r\n")
        m = IMAGE_RE.match(stripped)
        if not m:
            continue
        prefix, raw, suffix = m.groups()
        ref = resolve_ref(raw)
        if not ref:
            continue
        digest = get_digest(ref)
        if not digest:
            print(f"[skip] {path.name}:{i + 1} — Digest nicht auflösbar: {ref}")
            continue
        pinned = f"{ref}@{digest}"
        if VAR_RE.match(raw.strip()):
            var = VAR_RE.match(raw.strip()).group(1)
            new_raw = f"${{{var}:-{pinned}}}"
        else:
            new_raw = pinned
        lines[i] = prefix + new_raw + suffix + ("\n" if line.endswith("\n") else "")
        changed += 1
        print(f"[pin ] {path.name}:{i + 1} {ref} -> {digest}")
    if changed:
        path.write_text("".join(lines), encoding="utf-8")
    return changed


def main() -> int:
    files = [Path(f) for f in (sys.argv[1:] or DEFAULT_FILES)]
    total = sum(pin_file(f) for f in files)
    print(f"\n{total} Image(s) auf Digests gepinnt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
