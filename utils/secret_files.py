"""Umgang mit Secret-Dateien (.env, Service-Tokens).

Problem im Review: Secrets lagen teilweise world-readable im Repo
(`.env.backup_pre_v02` 755) und im Container (`profiles/telegram_bot/.env` 755).
Wer Prozess-Listen oder Backups einsehen kann, liest den Bot-Token mit.

Dieses Modul kümmert sich um:
  * Rechte-Härtung (chmod 600) für Secret-Dateien
  * Audit: welche Dateien sind zu offen?
  * Sicheres Schreiben (Temp-Datei + 600 + replace), damit Rechte beim
    Schreiben nicht auf den Default zurückfallen
"""

from __future__ import annotations

import os
import tempfile
from typing import Iterable, List, Tuple

__all__ = ["SECRET_FILE_MODES", "harden_file", "harden_known_secrets",
           "audit_known_secrets", "write_secret_file", "is_secret_name"]

# 600 = nur Eigentümer lesen/schreiben
SAFE_MODE = 0o600


def is_secret_name(path: str) -> bool:
    base = os.path.basename(path)
    return (
        base.startswith(".env")
        or base.endswith(".env")
        or "token" in base.lower()
        or "secret" in base.lower()
        or base in (".archon_service_token", "credentials.json")
    )


def harden_file(path: str) -> bool:
    """Setzt Rechte auf 600. True, wenn danach sicher (oder Datei fehlt)."""
    if not path or not os.path.exists(path):
        return True
    try:
        current = os.stat(path).st_mode & 0o777
        if current == SAFE_MODE:
            return True
        os.chmod(path, SAFE_MODE)
        return True
    except Exception:
        return False


def candidate_secret_paths(extra_roots: Iterable[str] = ()) -> List[str]:
    """Bekannte Secret-Orte (Host + Container-Mounts)."""
    home = os.path.expanduser("~")
    out = [
        "/app/.env.archon",
        "/app/.env",
        "/opt/data/.env",
        "/opt/data/profiles",
        os.path.join(home, ".hermes"),
        "/app/data/.archon_service_token",
        "/app/config/permission_gates.json",
        ".env",
        ".env.archon",
        ".env.backup_pre_v02",
    ]
    out.extend(extra_roots)
    return out


def _walk_secret_files(root: str, max_depth: int = 2) -> List[str]:
    found: List[str] = []
    if not os.path.isdir(root):
        return found
    base_depth = root.rstrip(os.sep).count(os.sep)
    for dirpath, dirnames, filenames in os.walk(root):
        if dirpath.count(os.sep) - base_depth >= max_depth:
            dirnames[:] = []
        dirnames[:] = [d for d in dirnames if not d.startswith(".") or d == ".hermes"]
        for fn in filenames:
            if fn == ".env" or fn.startswith(".env.") or fn.endswith(".env"):
                found.append(os.path.join(dirpath, fn))
    return found


def audit_known_secrets(extra_roots: Iterable[str] = ()) -> List[Tuple[str, int]]:
    """Liste (pfad, modus) aller Secret-Dateien, die zu offen sind."""
    offenders: List[Tuple[str, int]] = []
    seen = set()

    def check(p: str) -> None:
        if p in seen or not os.path.exists(p):
            return
        seen.add(p)
        try:
            mode = os.stat(p).st_mode & 0o777
        except Exception:
            return
        if mode & 0o077:  # Gruppen- oder Andere-Zugriff
            offenders.append((p, mode))

    for p in candidate_secret_paths(extra_roots):
        if os.path.isdir(p):
            for f in _walk_secret_files(p):
                check(f)
        else:
            check(p)
    return offenders


def harden_known_secrets(extra_roots: Iterable[str] = ()) -> List[str]:
    """Härtet alle gefundenen Secret-Dateien und liefert die reparierten Pfade."""
    fixed: List[str] = []
    for path, _mode in audit_known_secrets(extra_roots):
        if harden_file(path):
            fixed.append(path)
    return fixed


def write_secret_file(path: str, content: str) -> bool:
    """Schreibt eine Secret-Datei atomar mit 600-Rechten."""
    try:
        directory = os.path.dirname(os.path.abspath(path)) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tmp_env_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.chmod(tmp, SAFE_MODE)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return True
    except Exception:
        return False


def mask_secret(value: str, keep: int = 4) -> str:
    """Maskiert ein Secret für API-Antworten (zeigt nur die letzten Zeichen)."""
    if not value:
        return ""
    v = str(value)
    if len(v) <= keep * 2:
        return "•" * 8
    return f"{'•' * 8}{v[-keep:]}"