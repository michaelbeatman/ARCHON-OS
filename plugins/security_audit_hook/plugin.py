# -*- coding: utf-8 -*-
"""
plugins/security_audit_hook/plugin.py
=====================================
Sicherheits-Hook zur Überwachung und Filterung von Tool-Aufrufen.
"""

import re
import logging
from typing import Dict, Any, Optional
from backend.plugin_manager import BasePlugin

logger = logging.getLogger("archon.plugins.security")

DANGEROUS_PATTERNS = [
    r"rm\s+-rf\s+[/~]",
    r":\(\)\s*\{\s*:\|:&\s*\};:",
    r"mkfs\.",
    r"dd\s+if=.*of=/dev/[sh]d",
    r">\s*/dev/sd[a-z]",
    r"chmod\s+-R\s+777\s+/",
    r"curl\s+.*\|\s*(?:bash|sh)"
]


class SecurityAuditPlugin(BasePlugin):
    async def before_tool_execute(self, tool_name: str, args: Dict[str, Any], context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Prüft Terminal-Befehle und Dateipfade auf gefährliche Muster.
        """
        if not self.config.get("block_destructive_commands", True):
            return args

        # Prüfe Shell-Befehle
        cmd = args.get("command") or args.get("CommandLine") or args.get("cmd") or ""
        if isinstance(cmd, str) and cmd:
            for pattern in DANGEROUS_PATTERNS:
                if re.search(pattern, cmd, re.IGNORECASE):
                    error_msg = f"[SecurityAuditPlugin] Blockiert: Befehl enthält destruktives Muster '{pattern}'"
                    logger.warning(error_msg)
                    raise PermissionError(error_msg)

        # Prüfe Directory Traversal in Dateipfaden (Workspace-Jail + sensible Ziele)
        path = args.get("path") or args.get("Path") or args.get("file_path") or ""
        if isinstance(path, str) and path:
            from pathlib import Path

            norm = path.replace("\\", "/")
            sensitive_targets = ("/etc", "/root", "Windows/System32", ".env", "audit_anchor")
            if ".." in norm or any(seg in norm for seg in sensitive_targets):
                workspace_root = Path(
                    str(context.get("workspace_root") or self.config.get("workspace_root") or ".")
                ).resolve()
                cand = (workspace_root / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
                outside_ws = not cand.is_relative_to(workspace_root)
                touches_sensitive = any(seg.lower() in norm.lower() for seg in sensitive_targets)
                if outside_ws or touches_sensitive:
                    error_msg = f"[SecurityAuditPlugin] Blockiert: Unerlaubter Pfadzugriff ({path})"
                    logger.warning(error_msg)
                    raise PermissionError(error_msg)

        return args

    async def after_tool_execute(self, tool_name: str, result: Any, context: Dict[str, Any]) -> Any:
        """
        Maskiert sensible Secrets (z. B. sk-ant-*, ghp_*, eyJ*) in Ausgaben, falls aktiviert.
        """
        if not self.config.get("mask_env_secrets", True):
            return result

        if isinstance(result, str):
            # API-Key Pattern Maskierung
            result = re.sub(r"(sk-[a-zA-Z0-9_\-]{20,})", r"sk-***[MASKED]***", result)
            result = re.sub(r"(ghp_[a-zA-Z0-9]{30,})", r"ghp_***[MASKED]***", result)
        elif isinstance(result, dict):
            for k, v in result.items():
                if isinstance(v, str):
                    v = re.sub(r"(sk-[a-zA-Z0-9_\-]{20,})", r"sk-***[MASKED]***", v)
                    v = re.sub(r"(ghp_[a-zA-Z0-9]{30,})", r"ghp_***[MASKED]***", v)
                    result[k] = v
        return result
