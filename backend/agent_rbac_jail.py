"""
backend/agent_rbac_jail.py
Paket 4 (Feature 18): Granulare Agenten-RBAC & Datei-Scope-Jails.
Erzwingt pro Agenten-Rolle strikte Werkzeug-Berechtigungen und Verzeichnis-Grenzen (Path-Jails).
Blockiert unbefugte Zugriffe auf `.env`, SSH-Keys, Systemverzeichnisse oder fremde Code-Ordner.
"""

import os
from typing import Dict, Any, List


def _get_cfg() -> Dict[str, Any]:
    try:
        from backend.autonomy_settings import get_module_config
        return get_module_config("agent_rbac_jail")
    except Exception:
        return {
            "enabled": True,
            "enforce_path_jail": True,
            "block_dotenv_access": True,
            "block_system_dirs": True
        }


ROLE_POLICIES: Dict[str, Dict[str, List[str]]] = {
    "researcher": {
        "allowed_tools": ["read_file", "search_web", "hybrid_search", "crag_retrieve"],
        "allowed_path_prefixes": ["docs/", "agent_workspace/", "memory/", "skills/"]
    },
    "frontend_dev": {
        "allowed_tools": ["read_file", "write_file", "edit_file", "visual_browser_audit"],
        "allowed_path_prefixes": ["static/", "templates/", "docs/", "agent_workspace/"]
    },
    "backend_architect": {
        "allowed_tools": ["read_file", "write_file", "edit_file", "execute_sandbox", "git_status"],
        "allowed_path_prefixes": ["backend/", "scripts/", "docs/", "agent_workspace/", "tests/"]
    },
    "kernel_admin": {
        "allowed_tools": ["*"],
        "allowed_path_prefixes": ["*"]
    }
}

FORBIDDEN_SYSTEM_PREFIXES = ("/etc/", "/root/", "/proc/", "/sys/", "c:/windows", "c:/system32")
# Audit 23.11.2026: der symmetrische Warrant-HMAC-Key liegt unter
# data/warrant_hmac.key. Ein Agent mit Dateilese-Zugriff koennte sonst
# beliebige Privileg-Warrants selbst signieren.
SENSITIVE_FILENAMES = (
    ".env", "id_rsa", "id_ed25519", "shadow", "passwd", "credentials.json",
    "warrant_hmac.key",
)


class AgentRBACJail:
    def check_access(
        self,
        role: str,
        tool_name: str,
        target_path: str = ""
    ) -> Dict[str, Any]:
        cfg = _get_cfg()
        if not bool(cfg.get("enabled", True)):
            return {"allowed": True, "bypassed": True, "role": role, "tool": tool_name}

        norm_role = (role or "researcher").lower().strip()
        if norm_role not in ROLE_POLICIES:
            return {
                "allowed": False,
                "blocked": True,
                "role": norm_role,
                "tool": tool_name,
                "target_path": target_path,
                "reason": f"Unbekannte Rolle '{norm_role}' durch Fail-Closed RBAC-Jail blockiert."
            }
        policy = ROLE_POLICIES[norm_role]
        norm_path = (target_path or "").replace("\\", "/").strip()
        while norm_path.startswith("./"):
            norm_path = norm_path[2:]
        low_path = norm_path.lower()

        # Reale Symlink-Auflösung gegen Workspace-Root, damit Symlink-Escapes auffallen
        workspace_root = os.path.realpath(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        real_check = ""
        if norm_path:
            candidate = norm_path if os.path.isabs(norm_path) else os.path.join(workspace_root, norm_path)
            real_check = os.path.realpath(candidate).replace("\\", "/")
            ws_prefix = workspace_root.replace("\\", "/").rstrip("/") + "/"
            if os.path.isabs(norm_path) or real_check == workspace_root.replace("\\", "/") or real_check.startswith(ws_prefix):
                rel_after_ws = real_check[len(ws_prefix):] if real_check.startswith(ws_prefix) else real_check
            else:
                return {
                    "allowed": False,
                    "blocked": True,
                    "role": norm_role,
                    "tool": tool_name,
                    "target_path": target_path,
                    "reason": f"Symlink- oder Workspace-Ausbruch ('{target_path}' -> '{real_check}') durch RBAC-Jail blockiert."
                }
            # Wenn ein Symlink auf etwas anderes zeigte, prüfen wir sowohl norm_path als auch real_check/rel_after_ws
            low_check = rel_after_ws.lower()
        else:
            low_check = low_path

        # 1. Sensible Dateien (.env / SSH-Keys) schützen
        if bool(cfg.get("block_dotenv_access", True)) and norm_path:
            for candidate_low in (low_path, low_check):
                base = os.path.basename(candidate_low)
                if base in SENSITIVE_FILENAMES or base.startswith(".env"):
                    return {
                        "allowed": False,
                        "blocked": True,
                        "role": norm_role,
                        "tool": tool_name,
                        "target_path": target_path,
                        "reason": f"Zugriff auf geschützte Geheimnis-Datei '{base}' durch RBAC-Jail verweigert."
                    }

        # 2. Systemverzeichnisse & Path-Traversal (..) schützen
        if bool(cfg.get("block_system_dirs", True)) and norm_path:
            if (
                ".." in norm_path.split("/")
                or any(low_path.startswith(p) for p in FORBIDDEN_SYSTEM_PREFIXES)
                or any(real_check.lower().startswith(p) for p in FORBIDDEN_SYSTEM_PREFIXES)
            ):
                return {
                    "allowed": False,
                    "blocked": True,
                    "role": norm_role,
                    "tool": tool_name,
                    "target_path": target_path,
                    "reason": f"Systempfad oder Path-Traversal ('{target_path}') verboten."
                }

        # 3. Tool-Berechtigung prüfen
        allowed_tools = policy["allowed_tools"]
        if "*" not in allowed_tools and tool_name not in allowed_tools:
            return {
                "allowed": False,
                "blocked": True,
                "role": norm_role,
                "tool": tool_name,
                "target_path": target_path,
                "reason": f"Rolle '{norm_role}' besitzt keine Freigabe für Tool '{tool_name}'."
            }

        # 4. Datei-Scope-Jail prüfen
        if bool(cfg.get("enforce_path_jail", True)) and norm_path:
            allowed_prefixes = policy["allowed_path_prefixes"]
            if "*" not in allowed_prefixes and (
                not any(low_path.startswith(pref.lower()) for pref in allowed_prefixes)
                or not any(low_check.startswith(pref.lower()) for pref in allowed_prefixes)
            ):
                return {
                    "allowed": False,
                    "blocked": True,
                    "role": norm_role,
                    "tool": tool_name,
                    "target_path": target_path,
                    "reason": f"Pfad '{target_path}' liegt außerhalb des erlaubten Datei-Jails {allowed_prefixes} für Rolle '{norm_role}'."
                }

        return {
            "allowed": True,
            "blocked": False,
            "role": norm_role,
            "tool": tool_name,
            "target_path": target_path,
            "reason": "RBAC & Datei-Scope-Jail Prüfung bestanden."
        }


agent_rbac_jail = AgentRBACJail()
