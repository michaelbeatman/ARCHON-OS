import os
import re
import hashlib
import datetime
from typing import Dict, Any, Optional, List, Tuple

class SecuritySupervisor:
    def __init__(self, storage, guardrail_path: str = "GUARDRAIL.md"):
        self.storage = storage
        self.guardrail_path = guardrail_path
        self.injection_rules: List[str] = []
        self.sensitive_regexes: List[Tuple[str, re.Pattern]] = []
        self.agent_groups: Dict[str, str] = {} # In-memory Cache für Unit-Tests
        
        self._load_guardrails()
        self._init_audit_log_table()

    def _load_guardrails(self):
        """
        Liest GUARDRAIL.md ein und parst Prompt Injection Signaturen sowie Regex-Muster.
        """
        if not os.path.exists(self.guardrail_path):
            # Fallback falls Datei nicht existiert
            self.injection_rules = ["ignore previous instructions", "jailbreak", "override system"]
            self.sensitive_regexes = [
                ("GENERIC_KEY", re.compile(r"(?:key|secret|token)\s*[:=]\s*['\"a-zA-Z0-9_\-]{16,}")),
                ("OPENAI_KEY", re.compile(r"sk-[a-zA-Z0-9]{48}"))
            ]
            return

        with open(self.guardrail_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        current_section = None
        for line in lines:
            line_str = line.strip()
            if line_str.startswith("## "):
                current_section = line_str[3:].lower()
            elif line_str.startswith("- ") and current_section:
                val = line_str[2:].strip()
                if "prompt injection signatures" in current_section:
                    self.injection_rules.append(val.lower())
                elif "sensitive data leakage regex" in current_section:
                    if ":" in val:
                        name, pat = val.split(":", 1)
                        pat_clean = pat.strip().strip("`")
                        try:
                            self.sensitive_regexes.append((name.strip(), re.compile(pat_clean)))
                        except Exception as e:
                            print(f"[Security] Regex compilation failed for '{pat_clean}': {e}")

    def _init_audit_log_table(self):
        """
        Erstellt die audit_log Tabelle mit Hash-Verkettung.
        """
        conn = self.storage._get_connection()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    details TEXT,
                    status TEXT NOT NULL,
                    prev_hash TEXT,
                    current_hash TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                )
            """)
            conn.commit()
        finally:
            conn.close()

    def log_transaction(self, agent_id: str, action: str, details: str, status: str) -> str:
        """
        Schreibt einen neuen Eintrag ins Audit-Log. Verwendet eine kryptografische Hash-Chain (SHA-256).
        """
        conn = self.storage._get_connection()
        try:
            # 1. Letzten Hash auslesen
            row = conn.execute("SELECT current_hash FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
            prev_hash = row["current_hash"] if row else "0" * 64

            timestamp = datetime.datetime.now().isoformat()
            
            # 2. Block formatieren und hashen
            log_str = f"{agent_id}|{action}|{details}|{status}|{prev_hash}|{timestamp}"
            current_hash = hashlib.sha256(log_str.encode("utf-8")).hexdigest()

            # 3. Speichern
            conn.execute("""
                INSERT INTO audit_log (agent_id, action, details, status, prev_hash, current_hash, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (agent_id, action, details, status, prev_hash, current_hash, timestamp))
            conn.commit()
            
            return current_hash
        finally:
            conn.close()

    def check_rbac(self, agent_id: str, target_agent_id: str, action: str) -> bool:
        """
        Prüft Zugriffsrechte eines Agenten (agent_id) auf die Daten eines anderen (target_agent_id).
        """
        # System/Admin-Bypass
        if agent_id in ("system", "admin") or agent_id == target_agent_id:
            self.log_transaction(agent_id, action, f"Self or System Bypass on target {target_agent_id}", "allowed")
            return True

        # Privilege Groups bestimmen
        grp_src = self.agent_groups.get(agent_id)
        if not grp_src:
            grp_src = self._load_group_from_disk(agent_id)
            self.agent_groups[agent_id] = grp_src

        grp_tgt = self.agent_groups.get(target_agent_id)
        if not grp_tgt:
            grp_tgt = self._load_group_from_disk(target_agent_id)
            self.agent_groups[target_agent_id] = grp_tgt

        # Strikte Rechteprüfung
        is_allowed = (grp_src == grp_tgt) or (grp_src == "admin")
        
        status = "allowed" if is_allowed else "blocked"
        self.log_transaction(
            agent_id=agent_id,
            action=action,
            details=f"Target: {target_agent_id}. Groups: {grp_src} vs {grp_tgt}.",
            status=status
        )
        return is_allowed

    def _load_group_from_disk(self, agent_id: str) -> str:
        """
        Sucht Manifest-Dateien auf der Festplatte und extrahiert die privilege_group.
        """
        for ext in (".yaml", ".md"):
            path = f"./manifests/{agent_id}{ext}"
            if os.path.exists(path):
                try:
                    from core_storage import AgentManifest
                    with open(path, "r", encoding="utf-8") as f:
                        manifest = AgentManifest.from_markdown(path)
                        return manifest.privilege_group
                except Exception:
                    pass
        return "default"

    def filter_content(self, text: str) -> Tuple[bool, str]:
        """
        Prüft Text (Eingaben/Ausgaben) auf Injection-Signaturen und sensible Datenlecks.
        """
        lower_text = text.lower()
        
        # 1. Prompt Injection Erkennung
        for rule in self.injection_rules:
            if rule in lower_text:
                return False, f"Prompt injection pattern detected: '{rule}'"

        # 2. Secret / Credentials Leakerkennung
        for name, regex in self.sensitive_regexes:
            if regex.search(text):
                return False, f"Sensitive data leak detected: '{name}'"

        return True, ""

    def is_hitl_required(self, tool_name: str) -> bool:
        """
        Klassifiziert kritische Tools, die eine manuelle Freigabe erfordern.
        """
        critical_keywords = ["delete", "remove", "write", "destroy"]
        for kw in critical_keywords:
            if kw in tool_name.lower():
                return True
        return False
