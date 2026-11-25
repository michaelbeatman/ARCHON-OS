from fastapi import Depends as _ArchonDepends
from archon.routers._rbac import forbid_viewer_writes as _forbid_viewer_writes
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
from pydantic import BaseModel, ConfigDict, Field

import core_dispatcher  # noqa: F401
from archon.core.runtime import (  # noqa: F401
    WORKSPACE_DIR, MEMORY_DIR, DATA_DIR, SETTINGS_FILE, OBSIDIAN_VAULT_DIR,
    add_ticker, broadcast_event, ticker_entries, _load_json, _save_json,
    atomic_write_json,
)

from archon.routers._rbac import require_admin_or_503

router = APIRouter(dependencies=[_ArchonDepends(_forbid_viewer_writes)])


class _MemoryRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")


class MemoryHarvestRequest(_MemoryRequest):
    text: str = ""
    agent_id: str = "orchestrator"


class MemoryCompactRequest(_MemoryRequest):
    messages: List[Dict[str, Any]] = Field(default_factory=list)
    force: bool = False
    keep_recent_turns: Optional[int] = None


class MemoryIndexRequest(_MemoryRequest):
    doc_id: str = "DOC-1"
    title: str = "Unbenanntes Dokument"
    content: str = ""
    source: str = "system_docs"


class MemorySearchRequest(_MemoryRequest):
    query: str = ""
    top_k: Optional[int] = None
    rrf_k: Optional[int] = None


class MemoryTripleRequest(_MemoryRequest):
    subject: str = ""
    predicate: str = "RELATED_TO"
    object: str = ""
    confidence: float = Field(default=0.90, ge=0.0, le=1.0)
    source: str = "manual"


class MemoryIngestRequest(_MemoryRequest):
    text: str = ""
    source: str = "auto_extractor"


class MemoryCragRequest(_MemoryRequest):
    query: str = ""
    relevance_threshold: Optional[float] = None


class MemoryCoreBlockRequest(_MemoryRequest):
    scope: Optional[str] = None
    block_key: str = "custom_block"
    content: str = ""
    block_title: str = ""
    mode: str = "replace"
    acl: Optional[Any] = None
    ttl_seconds: Optional[int] = None
    project_id: Optional[str] = ""


class MemoryCompartmentStoreRequest(_MemoryRequest):
    scope: Optional[str] = None
    namespace: str = "default"
    content: str = ""
    tags: List[str] = Field(default_factory=list)
    acl: Optional[Any] = None
    ttl_seconds: Optional[int] = None
    agent_id: str = "global"
    project_id: str = ""


class MemoryPinCitationsRequest(_MemoryRequest):
    response_text: str = ""
    sources: List[Any] = Field(default_factory=list)


def _validate_scope(scope: Optional[str]) -> Optional[str]:
    """Prueft einen optionalen Memory-Scope gegen die kanonische Menge (400 bei Fehler)."""
    if scope is None or str(scope).strip() == "":
        return None
    from backend.core_memory_manager import VALID_MEMORY_SCOPES, normalize_scope
    value = str(scope).strip().lower()
    if value not in VALID_MEMORY_SCOPES:
        raise HTTPException(
            status_code=400,
            detail=f"Ungueltiger Memory-Scope: {scope!r} (erlaubt: {', '.join(VALID_MEMORY_SCOPES)})",
        )
    return normalize_scope(value)


@router.post("/api/memory/harvest")
def api_harvest_memory(request: Request, payload: MemoryHarvestRequest = Body(...)):
    require_admin_or_503(request)  # RBAC: Rollenzaun
    data = payload.model_dump()
    from local_memory_bridge import LocalMemoryBridge
    bridge = LocalMemoryBridge()
    text = data.get("text", "")
    agent_id = data.get("agent_id", "orchestrator")
    return bridge.harvest_facts_and_preferences(text, agent_id=agent_id)


@router.post("/api/memory/compact-context")
def api_compact_context(request: Request, payload: MemoryCompactRequest = Body(...)):
    require_admin_or_503(request)  # RBAC: Rollenzaun
    data = payload.model_dump()
    from backend.context_compactor import context_compactor
    return context_compactor.compact_messages(
        messages=data.get("messages", []),
        force=bool(data.get("force", False)),
        keep_recent_override=data.get("keep_recent_turns")
    )


@router.post("/api/memory/hybrid-index")
def api_hybrid_index_doc(request: Request, payload: MemoryIndexRequest = Body(...)):
    require_admin_or_503(request)  # RBAC: Rollenzaun
    data = payload.model_dump()
    from backend.hybrid_search_engine import hybrid_search_engine
    return hybrid_search_engine.index_document(
        doc_id=data.get("doc_id", "DOC-1"),
        title=data.get("title", "Unbenanntes Dokument"),
        content=data.get("content", ""),
        source=data.get("source", "system_docs")
    )


@router.post("/api/memory/hybrid-search")
def api_hybrid_search(request: Request, payload: MemorySearchRequest = Body(...)):
    require_admin_or_503(request)  # RBAC: Rollenzaun
    data = payload.model_dump()
    from backend.hybrid_search_engine import hybrid_search_engine
    return hybrid_search_engine.search(
        query=data.get("query", ""),
        top_k_override=data.get("top_k"),
        rrf_k_override=data.get("rrf_k")
    )


@router.post("/api/memory/knowledge-graph/triple")
def api_kg_add_triple(request: Request, payload: MemoryTripleRequest = Body(...)):
    require_admin_or_503(request)  # RBAC: Rollenzaun
    data = payload.model_dump()
    from backend.knowledge_graph_store import knowledge_graph_store
    return knowledge_graph_store.add_triple(
        subject=data.get("subject", ""),
        predicate=data.get("predicate", "RELATED_TO"),
        obj=data.get("object", ""),
        confidence=float(data.get("confidence", 0.90)),
        source=data.get("source", "manual")
    )


@router.post("/api/memory/knowledge-graph/ingest")
def api_kg_ingest_text(request: Request, payload: MemoryIngestRequest = Body(...)):
    require_admin_or_503(request)  # RBAC: Rollenzaun
    data = payload.model_dump()
    from backend.knowledge_graph_store import knowledge_graph_store
    return knowledge_graph_store.ingest_text(
        text=data.get("text", ""),
        source=data.get("source", "auto_extractor")
    )


@router.get("/api/memory/knowledge-graph/subgraph")
def api_kg_subgraph(entity: str, hops: Optional[int] = None):
    from backend.knowledge_graph_store import knowledge_graph_store
    return knowledge_graph_store.query_subgraph(entity=entity, hops_override=hops)


@router.post("/api/memory/crag-retrieve")
def api_crag_retrieve(request: Request, payload: MemoryCragRequest = Body(...)):
    require_admin_or_503(request)  # RBAC: Rollenzaun
    data = payload.model_dump()
    from backend.corrective_rag import corrective_rag_engine
    return corrective_rag_engine.retrieve_and_verify(
        query=data.get("query", ""),
        threshold_override=data.get("relevance_threshold")
    )


@router.get("/api/memory/core-blocks")
def api_get_core_memory_blocks(
    scope: Optional[str] = Query(default=None),
    agent_id: str = Query(default="global"),
    tenant_id: str = Query(default="default"),
    project_id: str = Query(default=""),
):
    scope = _validate_scope(scope)
    from backend.core_memory_manager import core_memory_manager
    return core_memory_manager.list_blocks(
        agent_id=agent_id, tenant_id=tenant_id, scope=scope, project_id=project_id
    )


@router.post("/api/memory/core-blocks")
def api_upsert_core_memory_block(request: Request, payload: MemoryCoreBlockRequest = Body(...)):
    require_admin_or_503(request)  # RBAC: Rollenzaun
    data = payload.model_dump()
    scope = _validate_scope(data.get("scope"))
    from backend.core_memory_manager import core_memory_manager
    return core_memory_manager.upsert_block(
        block_key=data.get("block_key", "custom_block"),
        content=data.get("content", ""),
        block_title=data.get("block_title", ""),
        mode=data.get("mode", "replace"),
        scope=scope or "global",
        acl=data.get("acl"),
        ttl_seconds=data.get("ttl_seconds"),
        project_id=str(data.get("project_id") or ""),
    )


@router.post("/api/memory/compartment/store")
def api_compartment_store(request: Request, payload: MemoryCompartmentStoreRequest = Body(...)):
    require_admin_or_503(request)  # RBAC: Rollenzaun
    data = payload.model_dump()
    scope = _validate_scope(data.get("scope"))
    from backend.offline_memory_vault import store_memory
    eid = store_memory(
        namespace=str(data.get("namespace") or "default"),
        content=str(data.get("content") or ""),
        tags=list(data.get("tags") or []),
        scope=scope or "global",
        acl=data.get("acl"),
        ttl_seconds=data.get("ttl_seconds"),
        agent_id=str(data.get("agent_id") or "global"),
        project_id=str(data.get("project_id") or ""),
    )
    return {"status": "success", "id": eid, "scope": scope or "global"}


@router.get("/api/memory/compartment/recall")
def api_compartment_recall(
    request: Request,
    namespace: str = Query(default="default"),
    query: str = Query(default=""),
    top_k: int = Query(default=5),
    scope: Optional[str] = Query(default=None),
    agent_id: str = Query(default="global"),
    project_id: str = Query(default=""),
):
    require_admin_or_503(request)  # RBAC: Rollenzaun
    scope = _validate_scope(scope)
    from backend.offline_memory_vault import recall_memory
    return {
        "status": "success",
        "results": recall_memory(
            namespace, query, top_k=max(1, min(20, top_k)),
            scope=scope, agent_id=agent_id, project_id=project_id,
        ),
    }


@router.post("/api/memory/pin-citations")
def api_pin_citations(request: Request, payload: MemoryPinCitationsRequest = Body(...)):
    require_admin_or_503(request)  # RBAC: Rollenzaun
    data = payload.model_dump()
    from backend.citation_pinner import citation_pinner
    return citation_pinner.pin_citations(
        response_text=data.get("response_text", ""),
        sources=data.get("sources", [])
    )
