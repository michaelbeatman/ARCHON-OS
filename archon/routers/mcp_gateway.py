"""
archon/routers/mcp_gateway.py
=============================
M48 — Native Archon OS MCP-Server (/mcp Gateway).

Endpunkte:
- POST /mcp        : Streamable HTTP JSON-RPC 2.0 (Single & Batch)
- GET  /mcp        : Server-Sent Events (SSE) Stream für MCP-Clients
- DELETE /mcp      : Beendet eine aktive MCP-Session
- GET  /mcp/sse    : Legacy HTTP+SSE Alias (Claude Desktop / ältere Clients)
- POST /mcp/messages : Legacy HTTP+SSE Message-Endpunkt
- GET  /mcp/info   : Client-Konfigurationsvorlagen (Claude Desktop, Cursor, VS Code)
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from backend.mcp_gateway import mcp_gateway

router = APIRouter(tags=["MCP Gateway"])


def _has_valid_service_token(request: Request) -> bool:
    try:
        from main import _request_has_service_token
        return bool(_request_has_service_token(request))
    except Exception:
        return False


def _authenticate_mcp_request(request: Request) -> Dict[str, Any]:
    ok, key_info, err = mcp_gateway.authenticate_headers(
        dict(request.headers),
        service_token_valid=_has_valid_service_token(request),
    )
    if not ok or key_info is None:
        raise HTTPException(status_code=401, detail=err)
    return key_info


@router.post("/mcp")
@router.post("/mcp/messages")
async def mcp_streamable_http_post(request: Request):
    """Streamable HTTP (JSON-RPC 2.0) Endpunkt für Claude Desktop, Cursor & VS Code."""
    key_info = _authenticate_mcp_request(request)
    session_id = request.headers.get("mcp-session-id") or request.query_params.get("sessionId")

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error: Ungültiges JSON."},
            },
        )

    # Batch-Support
    if isinstance(body, list):
        if not body:
            return JSONResponse(
                status_code=400,
                content={
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32600, "message": "Invalid Request: Leerer Batch."},
                },
            )
        responses: List[Dict[str, Any]] = []
        active_sid = session_id
        for item in body:
            resp_obj, active_sid = mcp_gateway.handle_jsonrpc(item, key_info, active_sid)
            if resp_obj is not None:
                responses.append(resp_obj)
        headers = {"Mcp-Session-Id": active_sid} if active_sid else {}
        if not responses:
            return Response(status_code=202, headers=headers)
        return JSONResponse(status_code=200, content=responses, headers=headers)

    resp_obj, active_sid = mcp_gateway.handle_jsonrpc(body, key_info, session_id)
    headers = {"Mcp-Session-Id": active_sid} if active_sid else {}
    if resp_obj is None:
        return Response(status_code=202, headers=headers)
    return JSONResponse(status_code=200, content=resp_obj, headers=headers)


@router.get("/mcp")
@router.get("/mcp/sse")
async def mcp_sse_stream(request: Request):
    """Server-Sent Events (SSE) Stream für MCP-Server-Benachrichtigungen."""
    _authenticate_mcp_request(request)
    session_id = request.headers.get("mcp-session-id") or mcp_gateway.sessions.create()

    async def _event_generator():
        yield f"event: endpoint\ndata: /mcp/messages?sessionId={session_id}\n\n"
        # In Test/Kurz-Requests einen initialen Keepalive liefern und sauber prüfen
        if request.query_params.get("once") == "1":
            return
        try:
            for _ in range(120):
                if await request.is_disconnected():
                    break
                await asyncio.sleep(15)
                yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Mcp-Session-Id": session_id,
        },
    )


@router.delete("/mcp")
async def mcp_delete_session(request: Request):
    """Beendet eine aktive MCP-Session."""
    _authenticate_mcp_request(request)
    session_id = request.headers.get("mcp-session-id")
    if not session_id:
        raise HTTPException(status_code=400, detail="Mcp-Session-Id Header erforderlich.")
    removed = mcp_gateway.sessions.delete(session_id)
    return {"status": "closed" if removed else "not_found", "session_id": session_id}


@router.get("/mcp/info")
def mcp_gateway_info(request: Request):
    """Liefert Client-Konfigurationsbeispiele für Claude Desktop, Cursor & VS Code."""
    base_url = str(request.base_url).rstrip("/")
    mcp_url = f"{base_url}/mcp"
    tools = mcp_gateway.get_tool_definitions()
    return {
        "status": "ready",
        "server": mcp_gateway.server_name,
        "version": mcp_gateway.server_version,
        "endpoint": mcp_url,
        "sse_endpoint": f"{base_url}/mcp/sse",
        "tool_count": len(tools),
        "tools": [t["name"] for t in tools],
        "clients": {
            "claude_desktop": {
                "mcpServers": {
                    "archon-os": {
                        "url": mcp_url,
                        "headers": {"Authorization": "Bearer archon_live_YOUR_API_KEY"},
                    }
                }
            },
            "cursor": {
                "mcpServers": {
                    "archon-os": {
                        "url": mcp_url,
                        "headers": {"Authorization": "Bearer archon_live_YOUR_API_KEY"},
                    }
                }
            },
            "vscode": {
                "servers": {
                    "archon-os": {
                        "type": "http",
                        "url": mcp_url,
                        "headers": {"Authorization": "Bearer archon_live_YOUR_API_KEY"},
                    }
                }
            },
        },
    }
