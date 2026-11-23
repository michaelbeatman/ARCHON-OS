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
import logging
_archon_exc_logger = logging.getLogger("secret_files")

import os
import subprocess
import tempfile
from typing import Iterable, List, Optional, Tuple

from archon.core.paths import HERMES_PROFILES_BASE, OPT_DATA_DIR

__all__ = ["SAFE_MODE", "expected_secret_mode", "is_hardened_mode",
           "harden_file", "harden_known_secrets",
           "audit_known_secrets", "write_secret_file", "is_secret_name",
           "mask_secret", "mask_value", "mask_yaml_secrets", "restore_masked_values"]

# 600 = nur Eigentümer lesen/schreiben
SAFE_MODE = 0o600


def expected_secret_mode() -> int:
    """Erwarteter POSIX-Modus nach der Härtung (nur auf POSIX aussagekraeftig)."""
    return SAFE_MODE


# G1: bekannte "Everybody"-Principal-Kennungen in icacls-Ausgaben.
_WINDOWS_OPEN_ACL_MARKERS = (
    "everyone:", "*s-1-1-0:", "authenticated users:", "*s-1-5-11:",
    "builtin\\users:", "*s-1-5-32-545:", "all application packages:",
    "*s-1-15-2-1:", "(i)",  # (I) = geerbte ACE
)


def _windows_dacl_is_hardened(path: str) -> bool:
    """Prueft die tatsaechliche NTFS-DACL via icacls (nur Windows)."""
    if os.name != "nt" or not path or not os.path.exists(path):
        return False
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.run(
            ["icacls", path], capture_output=True, text=True,
            timeout=15, creationflags=flags,
        )
        if proc.returncode != 0:
            return False
        lines = [ln.strip() for ln in (proc.stdout or "").splitlines() if ln.strip()]
        aces = lines[1:] if lines else []  # erste Zeile = Dateipfad
        if not aces:
            return False
        lowered = [ace.lower() for ace in aces]
        return not any(
            marker in ace for ace in lowered for marker in _WINDOWS_OPEN_ACL_MARKERS
        )
    except Exception as exc:
        _archon_exc_logger.debug("[secret_files] NTFS-DACL-Pruefung fehlgeschlagen: %s", exc)
        return False


def _windows_principal() -> str:
    """Aktueller Windows-Principal (whoami, Fallback ENV) fuer icacls."""
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.run(
            ["whoami"], capture_output=True, text=True,
            timeout=10, creationflags=flags,
        )
        principal = (proc.stdout or "").strip()
        if principal:
            return principal
    except Exception:
        pass
    domain = os.environ.get("USERDOMAIN") or os.environ.get("COMPUTERNAME") or ""
    user = os.environ.get("USERNAME") or ""
    if domain and user:
        return f"{domain}\\{user}"
    return user or "*S-1-5-11"


def _windows_dacl_harden(path: str) -> bool:
    """Setzt eine restriktive DACL (nur Owner, keine Vererbung) via icacls."""
    if os.name != "nt":
        return False
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.run(
            ["icacls", path, "/inheritance:r", "/grant:r", f"{_windows_principal()}:(F)"],
            capture_output=True, text=True, timeout=15,
            creationflags=flags, check=True,
        )
        return _windows_dacl_is_hardened(path)
    except Exception as exc:
        _archon_exc_logger.error("[secret_files] NTFS-DACL-Haertung fehlgeschlagen: %s", exc)
        return False


def is_hardened_mode(mode: int, path: Optional[str] = None) -> bool:
    """Prueft, ob eine Datei gehaertet ist.

    G1: Windows bildet POSIX-Modi nicht ab (chmod 0o600 -> stat 0o666). Statt
    "immer True" gilt hier nur eine tatsaechlich gepruefte NTFS-DACL als
    gehaertet; ohne Pfad/Pruefung bleibt der Status 'unverified' = False.
    """
    if os.name == "nt":
        return bool(path) and _windows_dacl_is_hardened(path)
    return mode == SAFE_MODE


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
    """Setzt Rechte auf 600 (POSIX) bzw. eine restriktive NTFS-DACL (Windows)."""
    if not path or not os.path.exists(path):
        return True
    # G1: auf Windows ist chmod wirkungslos — DACL setzen und verifizieren.
    if os.name == "nt":
        return _windows_dacl_harden(path)
    try:
        current = os.stat(path).st_mode & 0o777
        if is_hardened_mode(current, path):
            return True
        os.chmod(path, SAFE_MODE)
        return is_hardened_mode(os.stat(path).st_mode & 0o777, path)
    except Exception:
        return False


def candidate_secret_paths(extra_roots: Iterable[str] = ()) -> List[str]:
    """Bekannte Secret-Orte (Host + Container-Mounts)."""
    home = os.path.expanduser("~")
    out = [
        "/app/.env.archon",
        "/app/.env",
        os.path.join(OPT_DATA_DIR, ".env"),
        HERMES_PROFILES_BASE,
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
        if os.name == "nt":
            # G1: auf Windows ist der POSIX-Modus irrelevant — echte DACL pruefen.
            if not _windows_dacl_is_hardened(p):
                offenders.append((p, 0))
            return
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
            if os.name == "nt" and not _windows_dacl_harden(tmp):
                raise OSError(f"NTFS-DACL-Haertung der Temp-Datei fehlgeschlagen: {tmp}")
            os.replace(tmp, path)
            if os.name == "nt" and not _windows_dacl_harden(path):
                # G1: kein ungesichertes Secret zuruecklassen.
                try:
                    os.unlink(path)
                except OSError:
                    pass
                return False
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError as _exc:
                _archon_exc_logger.debug("[secret_files] Ignorierte Ausnahme (Z.139): %s", _exc)
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

# ---------------------------------------------------------------- YAML-Secrets

import re as _re

_YAML_LINE_RE = _re.compile(
    r'^(?P<indent>\s*)(?P<key>[A-Za-z0-9_.-]+)\s*:\s*(?P<value>.*)$'
)

# Nur echte Secret-Schluessel maskieren. "max_tokens" enthaelt zwar "token",
# ist aber eine Zahl - solche Felder duerfen nicht angefasst werden.
_SECRET_SUFFIXES = (
    "api_key", "apikey", "_key", "bot_token", "access_token", "refresh_token",
    "auth_token", "secret", "client_secret", "password", "passwd", "passphrase",
)
_SECRET_EXACT = {"token", "key", "secret", "password"}


def is_secret_key(key: str) -> bool:
    k = (key or "").strip().lower()
    if k.endswith("key_env") or k.endswith("_tokens") or k.endswith("token_count"):
        return False
    if k in _SECRET_EXACT:
        return True
    return any(k.endswith(suf) for suf in _SECRET_SUFFIXES)


def _match_secret_line(line: str):
    m = _YAML_LINE_RE.match(line)
    if not m:
        return None
    return m if is_secret_key(m.group("key")) else None


def mask_value(value: str) -> str:
    """Maskiert einen Wert und behaelt Form (Quotes) bei."""
    v = value.strip()
    if not v or v in ("''", '""', "null", "~", "[]", "{}"):
        return value
    quoted = len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"')
    core = v[1:-1] if quoted else v
    if not core:
        return value
    masked = mask_secret(core)
    return f'"{masked}"' if quoted else masked


def mask_yaml_secrets(text: str) -> str:
    """Maskiert secret-tragende Werte in einem YAML-Text (Zeilenweise)."""
    out = []
    for line in (text or "").splitlines():
        m = _match_secret_line(line)
        if m:
            out.append(f'{m.group("indent")}{m.group("key")}: {mask_value(m.group("value"))}')
        else:
            out.append(line)
    return "\n".join(out)


def _extract_scoped_yaml_secrets(text: str):
    """Extrahiert Secrets mit vollständigem Section-Pfad (und Vorkommensindex für Listen),
    damit gleichnamige Schlüssel wie 'api_key:' in verschiedenen Provider-Abschnitten
    sich beim Wiederherstellen niemals gegenseitig überschreiben.
    """
    section_stack = []  # Liste aus (indent_len, section_name)
    scoped = {}         # (section_path_tuple, key, occ_idx) -> raw_val
    path_counts = {}    # (section_path_tuple, key) -> count
    flat_counts = {}    # key -> count
    flat_last = {}      # key -> raw_val

    _ANY_KV_RE = _re.compile(r'^(?P<indent>\s*)(?:-\s+)?(?P<key>[A-Za-z0-9_.-]+)\s*:\s*(?P<rest>.*)$')

    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        m_sec = _ANY_KV_RE.match(line)
        m_sec_ind = len(m_sec.group("indent")) if m_sec else None
        if m_sec and m_sec_ind is not None:
            while section_stack and section_stack[-1][0] >= m_sec_ind:
                section_stack.pop()

        m = _match_secret_line(line)
        if m:
            key = m.group("key").strip()
            val = m.group("value").strip()
            sec_path = tuple(name for _, name in section_stack)
            occ = path_counts.get((sec_path, key), 0)
            path_counts[(sec_path, key)] = occ + 1
            scoped[(sec_path, key, occ)] = val
            flat_counts[key] = flat_counts.get(key, 0) + 1
            flat_last[key] = val
            continue

        if m_sec:
            k_name = m_sec.group("key").strip()
            rest = (m_sec.group("rest") or "").strip()
            if not rest or rest.startswith("#") or rest in ("|", ">"):
                section_stack.append((len(m_sec.group("indent")), k_name))

    return scoped, flat_counts, flat_last


def restore_masked_values(original_text: str, new_text: str) -> str:
    """Ersetzt maskierte Werte im neuen YAML section-aware durch die echten aus dem Original.

    Notwendig, weil der Live-Editor die maskierte Fassung zurueckschickt -
    ohne diesen Schritt wuerde das Speichern die echten Keys ueberschreiben.
    """
    orig_scoped, flat_counts, flat_last = _extract_scoped_yaml_secrets(original_text or "")

    section_stack = []
    seen_counts = {}
    _ANY_KV_RE = _re.compile(r'^(?P<indent>\s*)(?:-\s+)?(?P<key>[A-Za-z0-9_.-]+)\s*:\s*(?P<rest>.*)$')

    out = []
    for line in (new_text or "").splitlines():
        stripped = line.strip()
        m_sec = _ANY_KV_RE.match(line) if stripped and not stripped.startswith("#") else None
        if m_sec:
            ind_len = len(m_sec.group("indent"))
            while section_stack and section_stack[-1][0] >= ind_len:
                section_stack.pop()

        m = _match_secret_line(line)
        if m:
            key = m.group("key").strip()
            val = m.group("value").strip()
            sec_path = tuple(name for _, name in section_stack)
            occ = seen_counts.get((sec_path, key), 0)
            seen_counts[(sec_path, key)] = occ + 1
            if "\u2022" in val or "•" in val:
                real = orig_scoped.get((sec_path, key, occ))
                if real is None and occ > 0:
                    real = orig_scoped.get((sec_path, key, 0))
                if real is None and flat_counts.get(key, 0) == 1:
                    real = flat_last.get(key)
                if real is not None:
                    out.append(f'{m.group("indent")}{m.group("key")}: {real}')
                    continue
        elif m_sec:
            k_name = m_sec.group("key").strip()
            rest = (m_sec.group("rest") or "").strip()
            if not rest or rest.startswith("#") or rest in ("|", ">"):
                section_stack.append((len(m_sec.group("indent")), k_name))

        out.append(line)
    return "\n".join(out)
