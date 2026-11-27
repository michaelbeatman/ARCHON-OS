# -*- coding: utf-8 -*-
"""
backend/code_mode_sandbox.py
============================
M109b - Isolierte Code-Sandbox fuer Archon OS.

Ebenen:
  1. AST-Whitelist vor jeder Ausfuehrung (Importe, Gefahren-Names, Dunder,
     ``os.environ``).
  2. Eigener Prozess (``python -I -S``), leeres Environment, cwd = Tempdir.
  3. Runner mit minimalem ``__builtins__``: kein ``open``, kein ``eval``/
     ``exec``/``compile``, nur ``json``/``math`` importierbar.
  4. Capability-Bridge ueber JSONL-Dateien (keine pass_fds, Windows-kompatibel)
     ausschliesslich durch den CapabilityBroker.

Es gibt bewusst KEINEN Pfad aus der Sandbox in Repo, DB oder .env.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, Iterable, Optional

from backend.code_mode_capability_broker import mask_broker_response

__all__ = [
    "SandboxViolation",
    "SANDBOX_ALLOWED_MODULES",
    "validate_sandbox_source",
    "SandboxResult",
    "execute_code",
]


class SandboxViolation(Exception):
    """Quellcode verletzt die statische Sandbox-Whitelist."""


SANDBOX_ALLOWED_MODULES: FrozenSet[str] = frozenset({"json", "math"})

_FORBIDDEN_NAMES: FrozenSet[str] = frozenset({
    "open", "eval", "exec", "compile", "input", "breakpoint", "__import__",
    "getattr", "setattr", "vars", "globals", "locals", "memoryview",
})

_FORBIDDEN_IMPORT_ROOTS: FrozenSet[str] = frozenset({
    "os", "sys", "subprocess", "socket", "pathlib", "shutil", "tempfile",
    "importlib", "builtins", "ctypes", "multiprocessing", "threading",
    "requests", "urllib", "http", "ftplib", "smtplib", "sqlite3", "signal",
    "pickle", "marshal", "code", "codeop", "runpy", "site", "inspect",
})

_ENVIRON_ACCESS = re.compile(r"\bos\s*\.\s*environ\b")


# ---------------------------------------------------------------------------
# 1) Statische Validierung
# ---------------------------------------------------------------------------

def validate_sandbox_source(code: str) -> None:
    """Hart ablehnen, was die Sandbox verlassen oder Secrets lesen koennte.

    ``SandboxViolation`` wird ohne Quelltext-Ausschnitt erzeugt, damit ein
    Secret nie ueber eine Exception-Meldung nach aussen gelangt.
    """
    if not isinstance(code, str):
        raise SandboxViolation("source must be a string")

    if _ENVIRON_ACCESS.search(code):
        raise SandboxViolation("environment access is not allowed")

    try:
        tree = ast.parse(code, filename="<sandbox>")
    except (SyntaxError, ValueError, RecursionError):
        raise SandboxViolation("invalid syntax") from None

    def _reject(message: str) -> None:
        raise SandboxViolation(message)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = str(alias.name or "").split(".")[0].lower()
                if root not in SANDBOX_ALLOWED_MODULES or root in _FORBIDDEN_IMPORT_ROOTS:
                    _reject("import of this module is not allowed")
        elif isinstance(node, ast.ImportFrom):
            root = str(node.module or "").split(".")[0].lower()
            if node.level or root not in SANDBOX_ALLOWED_MODULES or root in _FORBIDDEN_IMPORT_ROOTS:
                _reject("import of this module is not allowed")
        elif isinstance(node, ast.Name):
            name = str(node.id or "")
            if name in _FORBIDDEN_NAMES:
                _reject("use of this builtin is not allowed")
            if name.startswith("__") and name.endswith("__"):
                _reject("dunder names are not allowed")
            if name.lower() == "environ":
                _reject("environment access is not allowed")
        elif isinstance(node, ast.Attribute):
            attr = str(node.attr or "")
            if attr.startswith("__") and attr.endswith("__"):
                _reject("dunder attributes are not allowed")
            if attr.lower() == "environ":
                _reject("environment access is not allowed")


# ---------------------------------------------------------------------------
# 2) Ergebnis
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SandboxResult:
    ok: bool
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool
    error: str
    duration_ms: int


# ---------------------------------------------------------------------------
# 3) Runner (host-erzeugt, wird in den Tempdir geschrieben)
# ---------------------------------------------------------------------------

RUNNER_SOURCE = r'''
# Code-Mode Runner: nur hier existieren echte builtins.user code bekommt
# ausschliesslich _SAFE_BUILTINS über restricted_globals.
import builtins
import json
import math
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_REAL_IMPORT = builtins.__import__
_MAX_PRINT_CHARS = 8192
_printed = 0
_request_counter = 0

# Leeres Environment -> Windows-Defaultcodepage koennte Maskierungszeichen
# („…“) verstuemmeln. Streams explizit auf UTF-8 festlegen.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
except Exception:
    pass

with open(os.path.join(_HERE, "config.json"), "r", encoding="utf-8") as _fh:
    _CONFIG = json.load(_fh)
# deadline_ms ist eine Restlaufzeit_ab JETZT_, keine absolute Uhrzeit:
# time.monotonic() liefert auf Windows Sekunden seit Boot, nicht 0.
_DEADLINE = time.monotonic() + float(_CONFIG["deadline_ms"]) / 1000.0
_ALLOWED_MODULES = frozenset(_CONFIG["allowed_modules"])

_REQUESTS = os.path.join(_HERE, "requests.jsonl")
_RESPONSES = os.path.join(_HERE, "responses.jsonl")


def _call_capability(name, arguments=None):
    """Bridge: JSONL-Request schreiben, auf host-massierte Antwort warten."""
    global _request_counter
    if not isinstance(name, str) or not name:
        return {"status": "blocked", "error_code": "INVALID_CAPABILITY", "result": None}
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        return {"status": "blocked", "error_code": "INVALID_ARGUMENTS", "result": None}
    _request_counter += 1
    _id = _request_counter
    try:
        with open(_REQUESTS, "a", encoding="utf-8") as _fh:
            _fh.write(json.dumps(
                {"id": _id, "name": name, "arguments": arguments},
                ensure_ascii=False,
            ) + "\n")
            _fh.flush()
            os.fsync(_fh.fileno())
    except Exception as exc:
        return {
            "status": "blocked",
            "error_code": "CAPABILITY_BRIDGE_ERROR",
            "error": type(exc).__name__,
            "result": None,
        }

    _offset = 0
    while time.monotonic() < _DEADLINE:
        try:
            with open(_RESPONSES, "r", encoding="utf-8") as _fh:
                _fh.seek(_offset)
                _new = _fh.read()
                _offset = _fh.tell()
        except Exception:
            _new = ""
        for _line in _new.splitlines():
            try:
                _item = json.loads(_line)
            except Exception:
                continue
            if isinstance(_item, dict) and _item.get("id") == _id:
                return _item
        time.sleep(0.005)
    return {
        "status": "blocked",
        "error_code": "CAPABILITY_TIMEOUT",
        "error": "Capability response deadline exceeded",
        "result": None,
    }


def _safe_print(*args, **kwargs):
    """print mit hartem Gesamt-Limit (8192 Zeichen)."""
    global _printed
    _sep = str(kwargs.get("sep", " "))
    _end = str(kwargs.get("end", "\n"))
    try:
        _text = _sep.join(str(_a) for _a in args) + _end
    except Exception:
        return
    _remaining = _MAX_PRINT_CHARS - _printed
    if _remaining <= 0:
        return
    if len(_text) <= _remaining:
        _chunk = _text
    else:
        # Silent truncation would hide lost output from the caller: always
        # mark it, within the remaining character budget.
        _marker = "[OUTPUT_TRUNCATED]"
        if _remaining <= len(_marker):
            _chunk = _marker[:_remaining]
        else:
            _chunk = _text[:_remaining - len(_marker)] + _marker
    _printed += len(_chunk)
    sys.stdout.write(_chunk)
    sys.stdout.flush()


def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    _root = str(name or "").split(".")[0]
    if _root not in _ALLOWED_MODULES:
        raise ImportError("module is not available in sandbox")
    return _REAL_IMPORT(name, globals, locals, fromlist, level)


def _deny_open(*args, **kwargs):
    raise PermissionError("open() is not available in sandbox")


_SAFE_BUILTINS = {
    "print": _safe_print,
    "len": len,
    "range": range,
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "list": list,
    "dict": dict,
    "tuple": tuple,
    "set": set,
    "sorted": sorted,
    "sum": sum,
    "min": min,
    "max": max,
    "abs": abs,
    "round": round,
    "enumerate": enumerate,
    "zip": zip,
    "map": map,
    "filter": filter,
    "any": any,
    "all": all,
    "isinstance": isinstance,
    "type": type,
    "repr": repr,
    "hash": hash,
    "Exception": Exception,
    "ValueError": ValueError,
    "TypeError": TypeError,
    "RuntimeError": RuntimeError,
    "KeyError": KeyError,
    "IndexError": IndexError,
    "ZeroDivisionError": ZeroDivisionError,
    "ArithmeticError": ArithmeticError,
    "open": _deny_open,
    "__import__": _safe_import,
}

_RESTRICTED = {
    "__builtins__": _SAFE_BUILTINS,
    "__name__": "__sandbox__",
    "_call_capability": _call_capability,
    "json": json,
    "math": math,
}

try:
    with open(os.path.join(_HERE, "code.py"), "r", encoding="utf-8") as _fh:
        _SOURCE = _fh.read()
    exec(compile(_SOURCE, "<sandbox>", "exec"), _RESTRICTED)
except Exception as _exc:
    # Nur der Typ, nie der Wert: der Exception-Text koennte Secrets enthalten.
    sys.stderr.write("SandboxError: " + type(_exc).__name__ + "\n")
    sys.stderr.flush()
    sys.exit(1)
'''


# ---------------------------------------------------------------------------
# 4) Host-Ausfuehrung
# ---------------------------------------------------------------------------

_TRUNCATION_MARKER = "[OUTPUT_TRUNCATED]"
_POLL_INTERVAL = 0.005


def _read_capped(path: str, limit: int) -> str:
    """Datei bis ``limit`` Bytes lesen; danach Truncation-Marker anhaengen."""
    try:
        with open(path, "rb") as fh:
            data = fh.read(limit + 1)
    except OSError:
        return ""
    if len(data) <= limit:
        return data.decode("utf-8", errors="replace")
    head = data[: max(0, limit - len(_TRUNCATION_MARKER))]
    return head.decode("utf-8", errors="replace") + _TRUNCATION_MARKER


def _failure(
    error: str,
    *,
    stdout: str = "",
    stderr: str = "",
    exit_code: int = -1,
    timed_out: bool = False,
    duration_ms: int = 0,
) -> SandboxResult:
    return SandboxResult(
        ok=False,
        stdout=stdout,
        stderr=stderr,
        exit_code=exit_code,
        timed_out=timed_out,
        error=error,
        duration_ms=duration_ms,
    )


def _normalize_broker(broker: Any, allowed: FrozenSet[str]) -> Any:
    """Broker-Instanz (oder -Klasse mit allowlist) zurueckgeben."""
    if broker is None:
        return None
    if inspect.isclass(broker):
        # Any verhindert, dass mypy die Klasse auf object-Konstruktor reduziert.
        constructor: Any = broker
        try:
            return constructor(allowed)
        except Exception:
            try:
                return constructor(allowlist=allowed)
            except Exception:
                return None
    return broker


def _invoke_broker(broker: Any, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Capability-Call im Host-Thread - Ergebnisse werden zusätzlich maskiert."""
    try:
        if broker is None:
            return {"status": "blocked", "error_code": "NO_BROKER", "result": None}
        if hasattr(broker, "invoke_sync"):
            response = broker.invoke_sync(
                name,
                arguments,
                agent_id="code_mode_sandbox",
                session_id="sandbox_session",
            )
        elif hasattr(broker, "invoke"):
            response = asyncio.run(
                broker.invoke(
                    name,
                    arguments,
                    agent_id="code_mode_sandbox",
                    session_id="sandbox_session",
                )
            )
        else:
            return {"status": "blocked", "error_code": "NO_BROKER", "result": None}
        if not isinstance(response, dict):
            return {"status": "blocked", "error_code": "INVALID_BROKER_RESPONSE", "result": None}
        masked = mask_broker_response(response)
        return masked if isinstance(masked, dict) else {
            "status": "blocked", "error_code": "INVALID_BROKER_RESPONSE", "result": None
        }
    except Exception:
        # Keine Exception-Details: sie koennten Secrets aus Argumenten enthalten.
        return {"status": "blocked", "error_code": "BROKER_ERROR", "result": None}


def _bridge_loop(
    *,
    workdir: str,
    broker: Any,
    allowed: FrozenSet[str],
    stop: threading.Event,
    deadline: float,
) -> None:
    """Pollt requests.jsonl und schreibt maskierte Responses zurueck."""
    requests_path = os.path.join(workdir, "requests.jsonl")
    responses_path = os.path.join(workdir, "responses.jsonl")
    offset = 0

    def _drain() -> int:
        nonlocal offset
        try:
            with open(requests_path, "r", encoding="utf-8") as fh:
                fh.seek(offset)
                new_data = fh.read()
                offset = fh.tell()
        except OSError:
            return 0
        count = 0
        for line in new_data.splitlines():
            count += 1
            try:
                request = json.loads(line)
            except Exception:
                request = {}
            request_id = request.get("id") if isinstance(request, dict) else None
            name = str(request.get("name") or "") if isinstance(request, dict) else ""
            arguments = request.get("arguments") if isinstance(request, dict) else {}
            if not isinstance(arguments, dict):
                arguments = {}
            if broker is None:
                response = {"status": "blocked", "error_code": "NO_BROKER", "result": None}
            elif name not in allowed:
                response = {"status": "blocked", "error_code": "CAPABILITY_NOT_ALLOWLISTED", "result": None}
            else:
                response = _invoke_broker(broker, name, arguments)
            response = dict(response)
            response["id"] = request_id
            try:
                with open(responses_path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(response, ensure_ascii=False, default=str) + "\n")
                    fh.flush()
                    os.fsync(fh.fileno())
            except Exception:
                return count
        return count

    while True:
        try:
            _drain()
        except Exception:
            pass
        if stop.is_set():
            try:
                _drain()
            except Exception:
                pass
            return
        if time.monotonic() >= deadline:
            return
        stop.wait(_POLL_INTERVAL)


def execute_code(
    code: str,
    *,
    broker: Any = None,
    allowed_capabilities: Iterable[str] = (),
    timeout_seconds: float = 2.0,
    max_output_bytes: int = 65536,
) -> SandboxResult:
    """Quellcode in einem isolierten Prozess ausfuehren."""
    started = time.monotonic()
    try:
        validate_sandbox_source(code)
    except SandboxViolation as exc:
        return _failure("SANDBOX_VIOLATION: " + str(exc))

    try:
        timeout = max(0.05, float(timeout_seconds))
        output_limit = max(0, int(max_output_bytes))
    except (TypeError, ValueError):
        return _failure("INVALID_SANDBOX_CONFIG")

    allowed = frozenset(str(item).strip() for item in (allowed_capabilities or ()) if str(item).strip())
    active_broker = _normalize_broker(broker, allowed)

    try:
        temp_dir = tempfile.TemporaryDirectory(prefix="archon_code_mode_")
    except OSError:
        return _failure("SANDBOX_TEMPDIR_FAILED")

    workdir = temp_dir.name
    stdout_path = os.path.join(workdir, "stdout.txt")
    stderr_path = os.path.join(workdir, "stderr.txt")
    stop = threading.Event()
    bridge_thread: Optional[threading.Thread] = None
    process: Optional[subprocess.Popen] = None
    # Zwei unterschiedliche File-Handle-Typen (open(..., "wb") vs. None).
    out_fh: Any = None
    err_fh: Any = None

    try:
        with open(os.path.join(workdir, "runner.py"), "w", encoding="utf-8") as fh:
            fh.write(RUNNER_SOURCE)
        with open(os.path.join(workdir, "code.py"), "w", encoding="utf-8") as fh:
            fh.write(code)
        for filename in ("requests.jsonl", "responses.jsonl"):
            with open(os.path.join(workdir, filename), "w", encoding="utf-8"):
                pass

        # Capability-Deadline deutlich vor der Prozess-Deadline, damit der
        # Host-Thread niemals ueber die subprocess-timeout hinaus blockiert.
        bridge_deadline = started + max(0.05, timeout * 0.70)
        config = {
            "deadline_ms": int(max(1, (bridge_deadline - time.monotonic()) * 1000)),
            "allowed_modules": sorted(SANDBOX_ALLOWED_MODULES),
        }
        with open(os.path.join(workdir, "config.json"), "w", encoding="utf-8") as fh:
            json.dump(config, fh)

        env: Dict[str, str] = {}
        if os.name == "nt":
            # Windows braucht SystemRoot fuer CreateProcess/DLL-Ladung; ein
            # komplett leeres env laesst python.exe dort nicht starten.
            # NUR SystemRoot uebernehmen - niemals PATH, TEMP, USERPROFILE oder
            # ENV-Secrets in die Sandbox durchreichen.
            system_root = os.environ.get("SystemRoot") or os.environ.get("SYSTEMROOT")
            if system_root:
                env["SystemRoot"] = system_root

        out_fh = open(stdout_path, "wb")
        err_fh = open(stderr_path, "wb")
        process = subprocess.Popen(
            [sys.executable, "-I", "-S", os.path.join(workdir, "runner.py")],
            cwd=workdir,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=out_fh,
            stderr=err_fh,
        )

        bridge_thread = threading.Thread(
            target=_bridge_loop,
            kwargs={
                "workdir": workdir,
                "broker": active_broker,
                "allowed": allowed,
                "stop": stop,
                "deadline": bridge_deadline,
            },
            daemon=True,
            name="code-mode-capability-bridge",
        )
        bridge_thread.start()

        timed_out = False
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                process.kill()
            except OSError:
                pass
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                pass

        stderr_text = _read_capped(stderr_path, output_limit)
        stdout_text = _read_capped(stdout_path, output_limit)
        exit_code = process.returncode if process.returncode is not None else -1
        duration_ms = int((time.monotonic() - started) * 1000)

        if timed_out:
            return _failure(
                "SANDBOX_TIMEOUT",
                stdout=stdout_text,
                stderr=stderr_text,
                exit_code=exit_code,
                timed_out=True,
                duration_ms=duration_ms,
            )
        if exit_code != 0:
            return _failure(
                stderr_text.strip() or "SANDBOX_EXIT_ERROR",
                stdout=stdout_text,
                stderr=stderr_text,
                exit_code=exit_code,
                duration_ms=duration_ms,
            )
        return SandboxResult(
            ok=True,
            stdout=stdout_text,
            stderr=stderr_text,
            exit_code=0,
            timed_out=False,
            error="",
            duration_ms=duration_ms,
        )
    except Exception:
        return _failure(
            "SANDBOX_EXECUTION_ERROR",
            duration_ms=int((time.monotonic() - started) * 1000),
        )
    finally:
        stop.set()
        if bridge_thread is not None:
            bridge_thread.join(timeout=1.0)
        for close_fh in (out_fh, err_fh):
            if close_fh is not None:
                try:
                    close_fh.close()
                except OSError:
                    pass
        try:
            temp_dir.cleanup()
        except OSError:
            pass
