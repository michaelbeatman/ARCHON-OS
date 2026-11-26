"""F12 (D09): CI-Gate fuer Doku-Versionsabgleich gegen config/version.json (SSOT)."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Iterable, List, Tuple

DEFAULT_DOC_TARGETS = (
    "README.md",
    "README.de.md",
    "docs/SYSTEM_HANDBUCH.md",
)


def check_doc_version_sync(
    repo_root: Path,
    targets: Iterable[str] = DEFAULT_DOC_TARGETS,
) -> Tuple[str, List[str]]:
    """Prueft, ob alle Zieldateien die SSOT-Version aus config/version.json nennen."""
    version_file = repo_root / "config" / "version.json"
    data = json.loads(version_file.read_text(encoding="utf-8"))
    version = str(data.get("version") or "").strip()
    if not version:
        return "", ["config/version.json enthaelt keinen gueltigen 'version'-Eintrag"]

    mismatches: List[str] = []
    for rel in targets:
        doc_path = repo_root / rel
        if not doc_path.is_file():
            mismatches.append(f"{rel}: Datei fehlt")
            continue
        text = doc_path.read_text(encoding="utf-8", errors="replace")
        if version not in text:
            mismatches.append(f"{rel}: SSOT-Version '{version}' nicht gefunden")
    return version, mismatches


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    version, mismatches = check_doc_version_sync(root)
    if mismatches:
        print(f"[FAIL] Doku-Versionsdrift gegen SSOT ({version}):", file=sys.stderr)
        for item in mismatches:
            print(f"  - {item}", file=sys.stderr)
        return 1
    print(f"[OK] Doku-Versionen konsistent mit config/version.json ({version}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
