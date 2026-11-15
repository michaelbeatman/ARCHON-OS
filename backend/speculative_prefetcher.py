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
DB_PATH = os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db")


class SpeculativePrefetcher:
    def __init__(self, ttl_seconds: int = 180):
        self.ttl_seconds = ttl_seconds
        self._cache: Dict[str, Dict[str, Any]] = {}

    def prefetch_for_task(self, prompt: str) -> Dict[str, Any]:
        """
        Scannt den Task-Text nach Mustern und lädt relevante Ressourcen spekulativ vor.
        """
        now = time.time()
        prefetched = {}

        # 1. CRM / E-Mail Erkennung
        email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', prompt)
        if email_match:
            email = email_match.group(0)
            contact = self._lookup_crm_contact(email)
            if contact:
                prefetched["crm_contact"] = contact
                self._cache[f"crm:{email}"] = {"data": contact, "expires": now + self.ttl_seconds}

        # 2. ERP Beleg-Erkennung (z. B. RE-2026, ANG-1001, ART-200)
        doc_match = re.search(r'\b(RE|ANG|AB|AUF|ART)-\d+\b', prompt, re.I)
        if doc_match:
            doc_nr = doc_match.group(0).upper()
            doc_data = self._lookup_erp_document(doc_nr)
            if doc_data:
                prefetched["erp_doc"] = doc_data
                self._cache[f"erp:{doc_nr}"] = {"data": doc_data, "expires": now + self.ttl_seconds}

        # 3. Agenten-Learnings & Heuristiken zum Thema vorladen
        keywords = [w for w in re.findall(r'\b[a-zA-ZäöüÄÖÜß]{4,}\b', prompt) if w.lower() not in {"bitte", "mache", "erstelle", "zeig", "haben"}]
        if keywords:
            learnings = self._lookup_learnings(keywords[:3])
            if learnings:
                prefetched["cached_learnings"] = learnings
                self._cache[f"learnings:{keywords[0]}"] = {"data": learnings, "expires": now + self.ttl_seconds}

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

    def _get_erp_conn(self) -> Optional[sqlite3.Connection]:
        try:
            from backend.tenant_context import get_active_company_id
            cid = get_active_company_id() or "default"
        except Exception:
            cid = "default"
        for candidate in (
            os.path.join(WORKSPACE_DIR, "data", "tenants", cid, "erp.db"),
            os.path.join(WORKSPACE_DIR, "data", "tenants", "primary", "erp.db"),
            os.path.join(WORKSPACE_DIR, "data", "erp.db"),
        ):
            if os.path.exists(candidate):
                conn = sqlite3.connect(candidate, timeout=5.0)
                conn.row_factory = sqlite3.Row
                return conn
        return None

    def _lookup_crm_contact(self, email: str) -> Optional[Dict[str, Any]]:
        conn = self._get_erp_conn()
        if not conn:
            return None
        try:
            row = conn.execute("SELECT * FROM crm_contacts WHERE LOWER(email) = LOWER(?) LIMIT 1", (email,)).fetchone()
            return dict(row) if row else None
        except Exception:
            return None
        finally:
            conn.close()

    def _lookup_erp_document(self, doc_nr: str) -> Optional[Dict[str, Any]]:
        conn = self._get_erp_conn()
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

    def _lookup_learnings(self, keywords: List[str]) -> List[Dict[str, Any]]:
        if not os.path.exists(DB_PATH):
            return []
        try:
            conn = sqlite3.connect(DB_PATH, timeout=5.0)
            conn.row_factory = sqlite3.Row
            query = "SELECT id, agent_id, category, summary, obsidian_link FROM learnings WHERE " + " OR ".join(["summary LIKE ? OR category LIKE ?" for _ in keywords]) + " LIMIT 5"
            params = []
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
