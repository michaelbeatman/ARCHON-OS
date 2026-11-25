"""F2: Bildgenerierung als SSOT in ``backend/`` (D09/H-09-2).

Aus ``archon/routers/chat.py:1387-1510`` hierher verlagert: ``backend/**`` darf
``archon.routers`` nicht importieren. Der Chat-Router re-exportiert beide Namen
und registriert die Route weiterhin auf seinem eigenen Router (gleicher Pfad,
gleiche Reihenfolge, ``tags``/``dependencies`` bleiben erhalten).

Wichtig fuer die Tests: ``api_provider`` bleibt ein MODULOBJEKT-Import (ein
Patch auf ``api_provider.collect_keys`` greift), ``backend.llm_egress_guard``
wird weiterhin lazy importiert (Patches greifen zur Laufzeit), und der
DB-Write bei ``session_id`` bleibt unveraendert.

``_save_message_to_db`` ist bewusst eine lokale Kopie des Chat-Helfers: ein
Import aus ``archon.routers.chat`` waere eine neue Layer-Verletzung, und die
SSE-Call-Sites in ``chat.py`` bleiben dadurch unberuehrt.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Optional

import httpx
from fastapi import HTTPException
from pydantic import BaseModel

import api_provider
from archon.core.state_db import _get_state_db

__all__ = ("ImageGenerateToolRequest", "api_tool_image_generate", "_save_message_to_db")

logger = logging.getLogger("archon_os.image_generate")


class ImageGenerateToolRequest(BaseModel):
    prompt: str
    model: Optional[str] = "google/gemini-2.5-flash-image"
    provider: Optional[str] = "openrouter"
    session_id: Optional[str] = None


def _save_message_to_db(
    session_id: str,
    role: str,
    content: str,
    token_count: Optional[int] = None,
) -> None:
    try:
        with _get_state_db() as conn:
            now = time.time()
            conn.execute("""
                INSERT INTO messages (
                    session_id, role, content, timestamp, token_count, active, compacted
                ) VALUES (?, ?, ?, ?, ?, 1, 0)
            """, (session_id, role, content, now, token_count))
            conn.execute("""
                UPDATE sessions
                SET message_count = message_count + 1, last_activity_at = ?
                WHERE id = ?
            """, (now, session_id))
            conn.commit()
    except Exception as e:
        logger.error(f"[Chat Persistence] Error saving message: {e}")


async def api_tool_image_generate(req: ImageGenerateToolRequest) -> Dict[str, Any]:
    """Führt eine direkte Bildgenerierung über OpenRouter (z.B. Google Nano Banana) oder Bild-Modelle aus."""
    # D08/MED: der TTL/Lock-gesicherte Profil-.env-Scan liest beim Cache-Miss
    # ~70 Dateien — im Worker-Thread, nicht im SSE-/API-Event-Loop.
    all_keys = await asyncio.to_thread(api_provider.collect_keys)
    prompt = req.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail={"code": "chat_prompt_empty", "params": {}})

    model = (req.model or "google/gemini-2.5-flash-image").strip()
    provider = (req.provider or "openrouter").strip().lower()

    if provider == "openrouter":
        from backend.llm_egress_guard import (
            ZeroEgressBlockedError,
            audit_dispatch_async,
            enforce_egress_firewall_for_url,
            evaluate_and_gate_llm_dispatch,
            sanitize_outbound_llm_payload,
        )
        target_img_ep = "https://openrouter.ai/api/v1/chat/completions"
        try:
            gate = evaluate_and_gate_llm_dispatch(
                agent_id="image_generate",
                provider=provider,
                model=model,
                messages=[{"role": "user", "content": prompt}],
                intended_url=target_img_ep,
            )
            eff_url = str(gate.get("target_url") or target_img_ep)
            # P0-4/PII: enforce_... hat kein data_category; sanitize_... nimmt
            # ein DICT mit 'messages'-Key — eine nackte Liste wurde unveraendert
            # zurueckgegeben (PII-Scrubbing komplett umgangen).
            enforce_egress_firewall_for_url(eff_url, agent_id="image_generate")
            _scrubbed = sanitize_outbound_llm_payload(
                {"messages": [{"role": "user", "content": prompt}]},
                agent_id="image_generate",
                session_id="image_generate",
            )
            clean_messages = (
                _scrubbed["messages"] if isinstance(_scrubbed, dict) and "messages" in _scrubbed
                else [{"role": "user", "content": prompt}]
            )
        except ZeroEgressBlockedError as ze_err:
            raise HTTPException(
                status_code=403,
                detail={"code": ze_err.error_code, "message": str(ze_err)},
            )

        or_key = all_keys.get("OPENROUTER_API_KEY")
        if not gate.get("routed_to_local") and not or_key:
            raise HTTPException(status_code=400, detail={"code": "chat_openrouter_key_missing", "params": {}})
        headers = {
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:8501",
            "X-Title": "Archon OS",
        }
        if not gate.get("routed_to_local") and or_key:
            headers["Authorization"] = f"Bearer {or_key}"
        payload = {
            "model": str(gate.get("model") or model),
            "messages": clean_messages,
            "stream": False,
        }
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(eff_url, headers=headers, json=payload)
                await audit_dispatch_async(
                    agent_id="image_generate",
                    provider=str(gate.get("provider") or provider),
                    model=str(gate.get("model") or model),
                    target_endpoint=eff_url,
                    http_status=resp.status_code,
                    data_category=gate["data_category"],
                    zero_egress_active=gate["zero_egress_active"],
                )
                if resp.status_code != 200:
                    raise HTTPException(status_code=resp.status_code, detail={"code": "chat_openrouter_error", "params": {"error": resp.text[:300]}})
                data = resp.json()
                choices = data.get("choices") if isinstance(data, dict) else None
                if not isinstance(choices, list) or not choices:
                    raise HTTPException(
                        status_code=502,
                        detail={"code": "EMPTY_RESPONSE", "message": "Bildgenerierung lieferte keine choices."},
                    )
                choice = choices[0] if isinstance(choices[0], dict) else {}
                msg = choice.get("message", {}) if isinstance(choice.get("message"), dict) else {}
                text = msg.get("content", "")
                images = msg.get("images", [])
                if not text and not images:
                    raise HTTPException(
                        status_code=502,
                        detail={"code": "EMPTY_RESPONSE", "message": "Bildgenerierung lieferte weder Text noch Bild."},
                    )
                img_url = ""
                if images:
                    first = images[0]
                    img_url = first.get("image_url", {}).get("url") if isinstance(first, dict) else str(first)

                markdown = f"{text}\n\n![{prompt}]({img_url})" if img_url else text
                if req.session_id and img_url:
                    await asyncio.to_thread(_save_message_to_db, req.session_id, "assistant", markdown)

                return {
                    "status": "ok",
                    "image_url": img_url,
                    "text": text,
                    "markdown": markdown,
                    "model": model
                }
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail={"code": "chat_image_generation_failed", "params": {"error": str(e)}})

    raise HTTPException(status_code=400, detail={"code": "chat_provider_not_supported", "params": {"provider": provider}})
