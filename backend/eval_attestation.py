# -*- coding: utf-8 -*-
"""backend/eval_attestation.py
=============================
M71 — Eval-Attestierung für die Agent-Eval-Arena.

Vor jedem Lauf wird ein deterministischer SHA-256-Fingerprint über den
konfigurationsrelevanten Stand gebildet: Agenten-Profile, SOUL.md/Prompts,
Policy-Dateien und Routing-Config. Der Fingerprint wird additiv am Eval-
Result gespeichert und revisionssicher über ``chained_audit_log.record_event``
protokolliert.

Invarianten:
- Der Hash enthält keine Uhrzeit und keine Lauf-ID. Gleicher Konfigurations-
  stand liefert zu jedem Zeitpunkt denselben Wert.
- Fehlende Pflichtquellen brechen ab (fail-closed); keine Datei wird still
  übersprungen. Reine Laufzustands-Felder (Timestamps, last_run, ...) werden
  vor dem Hashing entfernt, damit normale Betriebsupdates keine Drift-Meldung
  erzeugen.
- Nach außen gehen nur relative Pfade und Hex-Digests. Dateiinhalte landen
  weder in Logs noch in Audit-Payloads oder API-Responses.
- ``backend/audit_log.py`` bleibt unberührt; der Audit-Singleton wird erst bei
  Bedarf importiert (kein Datenbankzugriff zur Importzeit).
"""

from __future__ import annotations

import hashlib
import inspect
import json
import logging
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

logger = logging.getLogger("archon.eval_attestation")

ALGORITHM = "sha256"
FORMAT_VERSION = 1
# Domänen-Trenner: verhindert, dass ein fremder Hash gleicher Struktur als
# Attestation dieses Moduls misinterpretiert wird. Bewusst ohne Zeitstempel.
_FINGERPRINT_DOMAIN = "archon-eval-attestation-v1\n"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

PathInput = Union[str, os.PathLike[str]]


class EvalAttestationError(RuntimeError):
    """Fail-closed-Fehler: Attestation konnte nicht verlässlich gebildet werden."""


@dataclass(frozen=True)
class FileDigest:
    """Ein hashbarer Bestandteil des Konfigurations-Fingerprints."""

    path: str  # POSIX- relativer Pfad, deterministisch sortierbar
    sha256: str
    category: str  # profile | soul | prompt | policy | routing

    def to_dict(self) -> Dict[str, str]:
        return {"path": self.path, "sha256": self.sha256, "category": self.category}

    @classmethod
    def from_dict(cls, data: Any) -> "FileDigest":
        if not isinstance(data, Mapping):
            raise EvalAttestationError("Attestation-Dateieintrag ist kein Objekt.")
        path = str(data.get("path") or "")
        digest = str(data.get("sha256") or "")
        category = str(data.get("category") or "")
        if not path or not _SHA256_RE.fullmatch(digest):
            raise EvalAttestationError(f"Attestation-Dateieintrag ungueltig: {path or '<leer>'}")
        return cls(path=path, sha256=digest, category=category)


@dataclass(frozen=True)
class ConfigFingerprint:
    """Gesamthash plus einzelne Datei-Digests für die Drift-Differenzliste."""

    sha256: str
    files: Tuple[FileDigest, ...]
    algorithm: str = ALGORITHM
    version: int = FORMAT_VERSION

    def to_dict(self) -> Dict[str, Any]:
        """Additive Erweiterung für Eval-Result-Schemas."""
        return {
            "algorithm": self.algorithm,
            "version": self.version,
            "sha256": self.sha256,
            "files": [item.to_dict() for item in self.files],
        }

    @classmethod
    def from_dict(cls, data: Any) -> "ConfigFingerprint":
        if not isinstance(data, Mapping):
            raise EvalAttestationError("Attestation fehlt oder ist kein Objekt.")
        algorithm = str(data.get("algorithm") or "")
        version = data.get("version")
        digest = str(data.get("sha256") or "")
        raw_files = data.get("files")
        if algorithm != ALGORITHM or version != FORMAT_VERSION:
            raise EvalAttestationError(
                f"Attestation-Format nicht kompatibel: algorithm={algorithm!r}, version={version!r}"
            )
        if not _SHA256_RE.fullmatch(digest):
            raise EvalAttestationError("Attestation-SHA256 ist kein 64-stelliger Hex-Wert.")
        if not isinstance(raw_files, list):
            raise EvalAttestationError("Attestation-Dateiliste fehlt.")
        files = sorted((FileDigest.from_dict(entry) for entry in raw_files), key=lambda f: f.path)
        return cls(sha256=digest, files=tuple(files), algorithm=algorithm, version=int(version))


@dataclass(frozen=True)
class _FileSpec:
    relative_path: str
    category: str


@dataclass(frozen=True)
class _GlobSpec:
    pattern: str
    category: str
    require_matches: bool


# SSOT der attestationrelevanten Quellen. Neue Quellen hier ergänzen — jede
# Aufnahme ist eine bewusste Entscheidung, weil sie den Fingerprint ändert.
_REQUIRED_FILES: Tuple[_FileSpec, ...] = (
    _FileSpec("agent_profiles.json", "profile"),
    _FileSpec("roles.json", "profile"),
    _FileSpec("config/org_hierarchy.json", "profile"),
    _FileSpec("config/permission_gates.json", "policy"),
    _FileSpec("config/passkey_hitl.json", "policy"),
    _FileSpec("config/approval_policy.yaml", "policy"),  # M69: Policy-SSOT
    _FileSpec("settings.json", "routing"),
)

_GLOB_FILES: Tuple[_GlobSpec, ...] = (
    _GlobSpec("souls/*/SOUL.md", "soul", True),
    _GlobSpec(".agents/skills/*/SOUL.md", "prompt", False),
    # In diesem Repo liegen Skill-Prompts als SKILL.md; SOUL.md bleibt für
    # neuere Skill-Pakete zusätzlich berücksichtigt.
    _GlobSpec(".agents/skills/*/SKILL.md", "prompt", False),
)

# Reine Betriebszustände: keine Konfigurationssemantik, dürfen keine Drift
# auslösen. Die Liste ist bewusst klein und betrifft JSON-Dateien aller Ebenen.
_VOLATILE_JSON_KEYS = frozenset({
    "updated_at",
    "created_at",
    "timestamp",
    "last_run",
    "last_check",
    "last_status",
    "last_used_at",
    "detected_at",
})


def _strip_volatile(value: Any) -> Any:
    """Entfernt Laufzustands-Timestamps aus geparstem JSON (rekursiv)."""
    if isinstance(value, dict):
        return {key: _strip_volatile(item) for key, item in value.items() if key not in _VOLATILE_JSON_KEYS}
    if isinstance(value, list):
        return [_strip_volatile(item) for item in value]
    return value


def _canonical_content(relative_path: str, raw: bytes) -> str:
    """Normalisiert Dateiinhalte: UTF-8, LF, sortierte JSON-Keys, keine Uhrzeit."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise EvalAttestationError(f"Attestation-Datei ist nicht UTF-8: {relative_path}") from exc
    text = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    if Path(relative_path).suffix.lower() == ".json":
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            # Keine Parser-Details mit Dateiinhalten in Logs/Responses aufnehmen.
            raise EvalAttestationError(f"Ungueltiges JSON in {relative_path}") from exc
        return json.dumps(
            _strip_volatile(parsed),
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    lines = [line.rstrip() for line in text.split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines) + ("\n" if lines else "")


def _workspace_root(root: Optional[PathInput] = None) -> Path:
    base = Path(root).resolve() if root is not None else Path(__file__).resolve().parent.parent
    if not base.is_dir():
        raise EvalAttestationError(f"Attestation-Wurzel ist kein Verzeichnis: {base}")
    return base


def _file_digest(root: Path, relative_path: str, category: str) -> FileDigest:
    absolute = root / relative_path
    if not absolute.is_file():
        raise EvalAttestationError(
            f"Attestation-Pflichtdatei fehlt: {relative_path} (erwartet unter {root})"
        )
    try:
        raw = absolute.read_bytes()
    except OSError as exc:
        raise EvalAttestationError(f"Attestation-Datei nicht lesbar: {relative_path}: {exc}") from exc
    canonical = _canonical_content(relative_path, raw)
    return FileDigest(
        path=relative_path,
        sha256=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        category=category,
    )


def _glob_digests(root: Path, spec: _GlobSpec) -> List[FileDigest]:
    base_relative = spec.pattern.split("/*/", 1)[0]
    if not (root / base_relative).is_dir():
        raise EvalAttestationError(
            f"Attestation-Quellverzeichnis fehlt: {base_relative}/ (Muster {spec.pattern})"
        )
    matches = sorted(
        (path for path in root.glob(spec.pattern) if path.is_file()),
        key=lambda path: path.relative_to(root).as_posix(),
    )
    if spec.require_matches and not matches:
        raise EvalAttestationError(f"Attestation-Muster ohne Treffer (fail-closed): {spec.pattern}")
    return [
        _file_digest(root, path.relative_to(root).as_posix(), spec.category)
        for path in matches
    ]


def build_config_fingerprint(root: Optional[PathInput] = None) -> ConfigFingerprint:
    """Bildet den deterministischen SHA-256 über sortierte Pfade + Inhalte.

    Fehlt eine Pflichtquelle, wird ``EvalAttestationError`` geworfen. Es gibt
    bewusst keinen Parameter zum Abschalten dieser Pflicht.
    """
    base = _workspace_root(root)
    collected: List[FileDigest] = [
        _file_digest(base, spec.relative_path, spec.category) for spec in _REQUIRED_FILES
    ]
    for spec in _GLOB_FILES:
        collected.extend(_glob_digests(base, spec))
    # Überlappende Muster dürfen keinen Eintrag doppelt zählen.
    by_path: Dict[str, FileDigest] = {item.path: item for item in collected}
    ordered = tuple(by_path[path] for path in sorted(by_path))
    payload = _FINGERPRINT_DOMAIN + "".join(
        f"{item.path}\0{item.sha256}\n" for item in ordered
    )
    return ConfigFingerprint(
        sha256=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        files=ordered,
    )


def get_current_attestation(root: Optional[PathInput] = None) -> Dict[str, Any]:
    """Read-only-Hilfe: aktuellen Fingerprint liefern, ohne DB-Schreibzugriff."""
    return build_config_fingerprint(root).to_dict()


# Der Audit-Singleton wird erst beim Schreiben importiert. ``_AUDIT_LOG`` ist
# ausschließlich für Tests mit temporärer DB überschreibbar (kein Guard-Pfad).
_AUDIT_LOG: Optional[Any] = None


def _get_audit_log() -> Any:
    global _AUDIT_LOG
    if _AUDIT_LOG is None:
        from backend.audit_log import chained_audit_log

        _AUDIT_LOG = chained_audit_log
    return _AUDIT_LOG


def _audit_strict() -> bool:
    """Audit-Schreibfehler sind default fail-closed (Repo-Muster)."""
    value = str(os.environ.get("ARCHON_AUDIT_STRICT", "1") or "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def _record_attestation_event(
    fingerprint: ConfigFingerprint, result: Mapping[str, Any], agent_id: str
) -> None:
    """Schreibt den Attestation-Nachweis in die zentrale Hashkette."""
    payload: Dict[str, Any] = {
        "eval_id": str(result.get("eval_id") or ""),
        "target_type": str(result.get("target_type") or ""),
        "target_id": str(result.get("target_id") or ""),
        "fingerprint_sha256": fingerprint.sha256,
        "fingerprint_version": fingerprint.version,
        "files": [{"path": item.path, "sha256": item.sha256} for item in fingerprint.files],
    }
    try:
        _get_audit_log().record_event(
            category="eval",
            action="eval_run_attested",
            agent_id=str(agent_id or "eval-system"),
            payload=payload,
        )
    except Exception as exc:
        logger.error("[M71] Attestation-Audit fehlgeschlagen: %s", exc)
        if _audit_strict():
            raise RuntimeError("eval_attestation_audit_write_failed") from exc


def _attach(
    raw_result: Any, fingerprint: ConfigFingerprint, agent_id: str
) -> Dict[str, Any]:
    if not isinstance(raw_result, Mapping):
        raise EvalAttestationError("Eval-Runner muss ein Mapping als Result liefern.")
    result = dict(raw_result)
    result["attestation"] = fingerprint.to_dict()
    _record_attestation_event(fingerprint, result, agent_id)
    return result


async def attest_eval_run(
    runner: Callable[[], Any],
    *,
    root: Optional[PathInput] = None,
    agent_id: str = "eval-system",
) -> Dict[str, Any]:
    """Führt einen Eval-Lauf aus und attestiert ihn.

    Der Fingerprint wird zwingend VOR dem Aufruf von ``runner`` gebildet.
    Sync- und Async-Runner werden beide unterstützt; das bestehende Result-
    Schema wird nur um den Schlüssel ``attestation`` ergänzt.
    """
    fingerprint = build_config_fingerprint(root)
    raw_result = runner()
    if inspect.isawaitable(raw_result):
        raw_result = await raw_result
    return _attach(raw_result, fingerprint, agent_id)


def attest_eval_run_sync(
    runner: Callable[[], Any],
    *,
    root: Optional[PathInput] = None,
    agent_id: str = "eval-system",
) -> Dict[str, Any]:
    """Synchrone Variante für z. B. ``replay_and_evaluate``."""
    fingerprint = build_config_fingerprint(root)
    return _attach(runner(), fingerprint, agent_id)


def verify_attestation(
    result: Any,
    *,
    root: Optional[PathInput] = None,
) -> Dict[str, Any]:
    """Vergleicht das gespeicherte Attestation mit dem aktuellen Konfigstand.

    Liefert eine klare Differenzliste mit relativem Dateinamen und Art der
    Abweichung (changed/added/removed). Fehlt eine Pflichtquelle, wird wie beim
    Bilden fail-closed abgebrochen.
    """
    if not isinstance(result, Mapping):
        return {
            "valid": False,
            "status": "invalid_attestation",
            "reason": "result_ist_kein_mapping",
            "differences": [],
        }
    try:
        stored = ConfigFingerprint.from_dict(result.get("attestation"))
    except EvalAttestationError as exc:
        return {
            "valid": False,
            "status": "invalid_attestation",
            "reason": str(exc),
            "differences": [],
        }
    current = build_config_fingerprint(root)
    stored_files = {item.path: item for item in stored.files}
    current_files = {item.path: item for item in current.files}

    differences: List[Dict[str, str]] = []
    for path in sorted(set(stored_files) | set(current_files)):
        before = stored_files.get(path)
        after = current_files.get(path)
        if before is None and after is not None:
            differences.append({
                "path": path,
                "kind": "added",
                "stored_sha256": "",
                "current_sha256": after.sha256,
            })
        elif after is None and before is not None:
            differences.append({
                "path": path,
                "kind": "removed",
                "stored_sha256": before.sha256,
                "current_sha256": "",
            })
        elif before is not None and after is not None and before.sha256 != after.sha256:
            differences.append({
                "path": path,
                "kind": "changed",
                "stored_sha256": before.sha256,
                "current_sha256": after.sha256,
            })
    if stored.sha256 != current.sha256 and not differences:
        differences.append({
            "path": "<fingerprint>",
            "kind": "algorithm_or_version_mismatch",
            "stored_sha256": stored.sha256,
            "current_sha256": current.sha256,
        })
    valid = not differences and stored.sha256 == current.sha256
    return {
        "valid": valid,
        "status": "ok" if valid else "drift",
        "stored_sha256": stored.sha256,
        "current_sha256": current.sha256,
        "differences": differences,
    }
