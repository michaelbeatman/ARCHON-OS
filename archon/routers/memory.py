"""Router /api/memory — ausgelagerte Routen.

Automatisch aus main.py extrahiert (Critical-Hardening / Modularisierung).
Enthaelt nur Endpunkte ohne Abhaengigkeit zu main.py-Interna; gemeinsame
Helfer kommen aus archon.core.runtime.
"""

import asyncio
import datetime
import json
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional

import httpx
import yaml
from fastapi import APIRouter, Body, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel

import core_dispatcher  # noqa: F401
from archon.core.runtime import (  # noqa: F401
    WORKSPACE_DIR, MEMORY_DIR, DATA_DIR, SETTINGS_FILE, OBSIDIAN_VAULT_DIR,
    add_ticker, broadcast_event, ticker_entries, _load_json, _save_json,
    atomic_write_json,
)

from archon.routers._rbac import require_admin_or_503

router = APIRouter()

@router.post("/api/memory/harvest")
def api_harvest_memory(request: Request, payload: Dict = Body(...)):
    require_admin_or_503(request)  # RBAC: Rollenzaun
    from local_memory_bridge import LocalMemoryBridge
    bridge = LocalMemoryBridge()
    text = payload.get("text", "")
    agent_id = payload.get("agent_id", "orchestrator")
    return bridge.harvest_facts_and_preferences(text, agent_id=agent_id)


@router.post("/api/memory/compact-context")
def api_compact_context(request: Request, payload: Dict = Body(...)):
    require_admin_or_503(request)  # RBAC: Rollenzaun
    from backend.context_compactor import context_compactor
    return context_compactor.compact_messages(
        messages=payload.get("messages", []),
        force=bool(payload.get("force", False)),
        keep_recent_override=payload.get("keep_recent_turns")
    )


@router.post("/api/memory/hybrid-index")
def api_hybrid_index_doc(request: Request, payload: Dict = Body(...)):
    require_admin_or_503(request)  # RBAC: Rollenzaun
    from backend.hybrid_search_engine import hybrid_search_engine
    return hybrid_search_engine.index_document(
        doc_id=payload.get("doc_id", "DOC-1"),
        title=payload.get("title", "Unbenanntes Dokument"),
        content=payload.get("content", ""),
        source=payload.get("source", "system_docs")
    )


@router.post("/api/memory/hybrid-search")
def api_hybrid_search(request: Request, payload: Dict = Body(...)):
    require_admin_or_503(request)  # RBAC: Rollenzaun
    from backend.hybrid_search_engine import hybrid_search_engine
    return hybrid_search_engine.search(
        query=payload.get("query", ""),
        top_k_override=payload.get("top_k"),
        rrf_k_override=payload.get("rrf_k")
    )


@router.post("/api/memory/knowledge-graph/triple")
def api_kg_add_triple(request: Request, payload: Dict = Body(...)):
    require_admin_or_503(request)  # RBAC: Rollenzaun
    from backend.knowledge_graph_store import knowledge_graph_store
    return knowledge_graph_store.add_triple(
        subject=payload.get("subject", ""),
        predicate=payload.get("predicate", "RELATED_TO"),
        obj=payload.get("object", ""),
        confidence=float(payload.get("confidence", 0.90)),
        source=payload.get("source", "manual")
    )


@router.post("/api/memory/knowledge-graph/ingest")
def api_kg_ingest_text(request: Request, payload: Dict = Body(...)):
    require_admin_or_503(request)  # RBAC: Rollenzaun
    from backend.knowledge_graph_store import knowledge_graph_store
    return knowledge_graph_store.ingest_text(
        text=payload.get("text", ""),
        source=payload.get("source", "auto_extractor")
    )


@router.get("/api/memory/knowledge-graph/subgraph")
def api_kg_subgraph(entity: str, hops: Optional[int] = None):
    from backend.knowledge_graph_store import knowledge_graph_store
    return knowledge_graph_store.query_subgraph(entity=entity, hops_override=hops)


@router.post("/api/memory/crag-retrieve")
def api_crag_retrieve(request: Request, payload: Dict = Body(...)):
    require_admin_or_503(request)  # RBAC: Rollenzaun
    from backend.corrective_rag import corrective_rag_engine
    return corrective_rag_engine.retrieve_and_verify(
        query=payload.get("query", ""),
        threshold_override=payload.get("relevance_threshold")
    )


@router.get("/api/memory/core-blocks")
def api_get_core_memory_blocks():
    from backend.core_memory_manager import core_memory_manager
    return core_memory_manager.list_blocks()


@router.post("/api/memory/core-blocks")
def api_upsert_core_memory_block(request: Request, payload: Dict = Body(...)):
    require_admin_or_503(request)  # RBAC: Rollenzaun
    from backend.core_memory_manager import core_memory_manager
    return core_memory_manager.upsert_block(
        block_key=payload.get("block_key", "custom_block"),
        content=payload.get("content", ""),
        block_title=payload.get("block_title", ""),
        mode=payload.get("mode", "replace")
    )


@router.post("/api/memory/pin-citations")
def api_pin_citations(request: Request, payload: Dict = Body(...)):
    require_admin_or_503(request)  # RBAC: Rollenzaun
    from backend.citation_pinner import citation_pinner
    return citation_pinner.pin_citations(
        response_text=payload.get("response_text", ""),
        sources=payload.get("sources", [])
    )
