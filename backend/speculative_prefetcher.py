# -*- coding: utf-8 -*-
"""
backend/speculative_prefetcher.py
=================================
Speculative Action & Resource Pre-fetching:
Analysiert eingehende Benutzer- und Agenten-Intents im Millisekundenbereich
und lädt im Hintergrund antizipierte Ressourcen (CRM-Profile, ERP-Belege,
Obsidian-Notizen, Heuristiken) vorab in einen ultra-schnellen RAM-Cache.
Dadurch sinkt die Latenz bei der anschließenden Tool-Ausführung auf unter 5 ms.
"""

import os
import re
import time
import sqlite3
import datetime
from typing import Dict, Any, List, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
try:
    from backend.db_paths import resolve_db
    DB_PATH = resolve_db("agentic_memory.db")
except Exception:
    DB_PATH = os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db")


def _get_cfg() -> Dict[str, Any]:
    try:
        from backend.autonomy_settings import get_module_config
        return get_module_config("speculative_prefetcher")
    except Exception:
        return {
            "enabled": True,
            "ttl_seconds": 180,
            "prefetch_crm": True,
            "prefetch_erp": True,
            "prefetch_learnings": True,
        }


class SpeculativePrefetcher:
    def __init__(self, ttl_seconds: Optional[int] = None):
        self._ttl_override = ttl_seconds
        self.ttl_seconds = ttl_seconds if ttl_seconds is not None else int(_get_cfg().get("ttl_seconds", 180))
        self._cache: Dict[str, Dict[str, Any]] = {}

    def _prune_expired(self, now: float) -> None:
        expired = [k for k, v in self._cache.items() if now > v.get("expires", 0)]
        for k in expired:
            self._cache.pop(k, None)

    def prefetch_for_task(
        self,
        prompt: str,
        tenant_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        is_cloud_target: bool = False,
    ) -> Dict[str, Any]:
        """
        Scannt den Task-Text nach Mustern und lädt relevante Ressourcen spekulativ vor.
        """
        cfg = _get_cfg()
        if not bool(cfg.get("enabled", True)):
            return {
                "status": "disabled",
                "count": 0,
                "keys": [],
                "cached_items": {},
                "timestamp": datetime.datetime.now().isoformat(),
            }

        if is_cloud_target:
            return {
                "status": "blocked_cloud_prefetch",
                "count": 0,
                "keys": [],
                "cached_items": {},
                "timestamp": datetime.datetime.now().isoformat(),
            }

        ttl = self._ttl_override if self._ttl_override is not None else int(cfg.get("ttl_seconds", 180))
        self.ttl_seconds = ttl
        now = time.time()
        self._prune_expired(now)
        prefetched = {}
        scope = f"{tenant_id or 'active'}:{agent_id or 'global'}"

        # 1. CRM / E-Mail Erkennung
        if bool(cfg.get("prefetch_crm", True)):
            email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', prompt)
            if email_match:
                email = email_match.group(0)
                contact = self._lookup_crm_contact(email, tenant_id=tenant_id)
                if contact:
                    prefetched["crm_contact"] = contact
                    self._cache[f"{scope}:crm:{email}"] = {"data": contact, "expires": now + ttl}

        # 2. ERP Beleg-Erkennung (z. B. RE-2026, ANG-1001, ART-200)
        if bool(cfg.get("prefetch_erp", True)):
            doc_match = re.search(r'\b(RE|ANG|AB|AUF|ART)-\d+\b', prompt, re.I)
            if doc_match:
                doc_nr = doc_match.group(0).upper()
                doc_data = self._lookup_erp_document(doc_nr, tenant_id=tenant_id)
                if doc_data:
                    prefetched["erp_doc"] = doc_data
                    self._cache[f"{scope}:erp:{doc_nr}"] = {"data": doc_data, "expires": now + ttl}

        # 3. Agenten-Learnings & Heuristiken zum Thema vorladen
        if bool(cfg.get("prefetch_learnings", True)):
            keywords = [w for w in re.findall(r'\b[a-zA-ZäöüÄÖÜß]{4,}\b', prompt) if w.lower() not in {"bitte", "mache", "erstelle", "zeig", "haben"}]
            if keywords:
                learnings = self._lookup_learnings(keywords[:3], agent_id=agent_id)
                if learnings:
                    prefetched["cached_learnings"] = learnings
                    self._cache[f"{scope}:learnings:{keywords[0]}"] = {"data": learnings, "expires": now + ttl}

        return {
            "status": "prefetched",
            "count": len(prefetched),
            "keys": list(prefetched.keys()),
            "cached_items": prefetched,
            "timestamp": datetime.datetime.now().isoformat()
        }

    def get_cached(self, key: str) -> Optional[Any]:
        """Holt ein spekulativ vorgeladenes Element aus dem schnellen RAM-Cache."""
        entry = self._cache.get(key)
        if not entry:
            return None
        if time.time() > entry.get("expires", 0):
            del self._cache[key]
            return None
        return entry.get("data")

    def _get_erp_conn(self, tenant_id: Optional[str] = None) -> Optional[sqlite3.Connection]:
        cid = tenant_id
        if not cid:
            try:
                from backend.tenant_context import get_active_company_id
                cid = get_active_company_id() or "default"
            except Exception:
                cid = "default"
        try:
            from backend.tenant_context import PRIMARY_TENANT_IDS, sanitize_tenant_id
            safe_cid = sanitize_tenant_id(cid)
            primary_ids = set(PRIMARY_TENANT_IDS)
        except Exception:
            safe_cid = str(cid).strip() or "default"
            primary_ids = {"default", "primary", "archon-systems"}

        candidates = [os.path.join(WORKSPACE_DIR, "data", "tenants", safe_cid, "erp.db")]
        if safe_cid in primary_ids:
            candidates.append(os.path.join(WORKSPACE_DIR, "data", "tenants", "primary", "erp.db"))
            try:
                from backend.db_paths import resolve_db
                candidates.append(resolve_db("erp.db"))
            except Exception:
                pass
        for candidate in candidates:
            if candidate and os.path.exists(candidate):
                conn = sqlite3.connect(candidate, timeout=5.0)
                conn.row_factory = sqlite3.Row
                return conn
        return None

    def _lookup_crm_contact(self, email: str, tenant_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        conn = self._get_erp_conn(tenant_id=tenant_id)
        if not conn:
            return None
        try:
            row = conn.execute("SELECT * FROM crm_contacts WHERE LOWER(email) = LOWER(?) LIMIT 1", (email,)).fetchone()
            return dict(row) if row else None
        except Exception:
            return None
        finally:
            conn.close()

    def _lookup_erp_document(self, doc_nr: str, tenant_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        conn = self._get_erp_conn(tenant_id=tenant_id)
        if not conn:
            return None
        try:
            row = conn.execute(
                "SELECT *, doc_type AS type FROM erp_documents WHERE doc_number = ? LIMIT 1",
                (doc_nr,),
            ).fetchone()
            return dict(row) if row else None
        except Exception:
            return None
        finally:
            conn.close()

    def _lookup_learnings(self, keywords: List[str], agent_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if not os.path.exists(DB_PATH):
            return []
        try:
            conn = sqlite3.connect(DB_PATH, timeout=5.0)
            conn.row_factory = sqlite3.Row
            kw_clause = " OR ".join(["summary LIKE ? OR category LIKE ?" for _ in keywords])
            params: List[Any] = []
            if agent_id:
                query = f"SELECT id, agent_id, category, summary, obsidian_link FROM learnings WHERE agent_id = ? AND ({kw_clause}) LIMIT 5"
                params.append(agent_id)
            else:
                query = f"SELECT id, agent_id, category, summary, obsidian_link FROM learnings WHERE {kw_clause} LIMIT 5"
            for k in keywords:
                params.extend([f"%{k}%", f"%{k}%"])
            rows = conn.execute(query, params).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception:
            return []


# Singleton
_prefetcher = None

def get_speculative_prefetcher() -> SpeculativePrefetcher:
    global _prefetcher
    if _prefetcher is None:
        _prefetcher = SpeculativePrefetcher()
    return _prefetcher
