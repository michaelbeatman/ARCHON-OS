"""
backend/rag_bridge.py
Verbindet Archon OS und den Master-Orchestrator mit dem im Docker laufenden
AnythingLLM Vector-RAG-System (Port 3001).
Greift auf die 6.478 im Workspace 'ARCHON' (mein-workspace) indexierten
Dokumente aus dem Obsidian-Vault zu und liefert relevante Kontexte an die Agenten.
"""

import os
import sys
import json
import urllib.request
import urllib.parse
from typing import Dict, Any, List, Optional

ANYTHINGLLM_URL = os.environ.get("ANYTHINGLLM_URL", "http://127.0.0.1:3001/api/v1")
ANYTHINGLLM_API_KEY = os.environ.get("ANYTHINGLLM_API_KEY", "R9YRVG7-FCFMRNK-NZ3FKSX-QKN5RHF")
WORKSPACE_SLUG = os.environ.get("ANYTHINGLLM_WORKSPACE", "mein-workspace")

class RAGBridge:
    def __init__(self, base_url: str = ANYTHINGLLM_URL, api_key: str = ANYTHINGLLM_API_KEY, workspace: str = WORKSPACE_SLUG):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.workspace = workspace

    def is_alive(self) -> bool:
        try:
            ping_url = self.base_url.replace("/api/v1", "/api/ping")
            req = urllib.request.Request(ping_url)
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                return resp.status == 200
        except Exception:
            return False

    def query_vault_rag(self, query_text: str, top_k: int = 4) -> Dict[str, Any]:
        """
        Fragt relevante Kontextabschnitte aus den 6.478 Vault-Dokumenten über AnythingLLM ab.
        Fallback auf lokale SQLite-Learnings, falls AnythingLLM unerreichbar sein sollte.
        """
        clean_query = query_text.strip()
        if not clean_query:
            return {"status": "empty_query", "context_chunks": [], "source_count": 0}

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        # 1. Versuch: Workspace Similarity Search
        try:
            url = f"{self.base_url}/workspace/{self.workspace}/similar-documents"
            payload = json.dumps({"text": clean_query}).encode("utf-8")
            req = urllib.request.Request(url, data=payload, headers=headers)
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))
                chunks = []
                for item in res_data.get("context", [])[:top_k]:
                    chunks.append({
                        "title": item.get("title", "Dokument"),
                        "text": item.get("text", "")[:1200],
                        "score": item.get("score", 1.0)
                    })
                if chunks:
                    return {
                        "status": "success",
                        "engine": "docker_anything_llm",
                        "context_chunks": chunks,
                        "source_count": len(chunks)
                    }
        except Exception:
            pass

        # 2. Versuch: Workspace Dokumenten-Suche
        try:
            url = f"{self.base_url}/workspace/{self.workspace}"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                ws_info = json.loads(resp.read().decode("utf-8"))
                w = ws_info.get("workspace", [{}])[0] if isinstance(ws_info.get("workspace"), list) else ws_info.get("workspace", {})
                docs = w.get("documents", [])
                matching_docs = []
                q_words = set(clean_query.lower().split())
                for d in docs:
                    title = d.get("title", "")
                    if any(w in title.lower() for w in q_words):
                        matching_docs.append({
                            "title": title,
                            "text": f"Indexiertes Vault-Dokument in AnythingLLM: {title}",
                            "score": 0.85
                        })
                    if len(matching_docs) >= top_k:
                        break
                if matching_docs:
                    return {
                        "status": "success",
                        "engine": "docker_anything_llm_metadata",
                        "context_chunks": matching_docs,
                        "source_count": len(matching_docs)
                    }
        except Exception:
            pass

        # 3. Fallback: Lokale SQLite Learnings
        from local_memory_bridge import LocalMemoryBridge
        bridge = LocalMemoryBridge()
        local_results = bridge.search_learnings(clean_query, limit=top_k)
        chunks = [{"title": f"Learning #{r['id']}: {r['category']}", "text": r["summary"], "score": 0.75} for r in local_results]
        return {
            "status": "fallback_local",
            "engine": "sqlite_learnings",
            "context_chunks": chunks,
            "source_count": len(chunks)
        }

rag_bridge = RAGBridge()
