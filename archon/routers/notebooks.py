"""NotebookLM Studio & Grounded Retrieval Router.

Verwaltet Notebooks, Wissensquellen, Vault-Anhaenge, Recherchen
und Obsidian-Synchronisationen.
"""

from fastapi import APIRouter, Body, HTTPException, Request
from archon.routers._rbac import require_admin_or_503
try:
    from utils.path_jail import PathJailError
except ImportError:
    class PathJailError(PermissionError):
        pass


router = APIRouter(tags=["notebooks"])


@router.get("/api/v1/notebooks")
def api_get_notebooks():
    try:
        from utils.notebook_engine import list_notebooks
        return {"notebooks": list_notebooks()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/notebooks")
def api_create_notebook(payload: dict = Body(...)):
    try:
        from utils.notebook_engine import create_notebook
        name = payload.get("name", "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Name ist erforderlich.")
        description = payload.get("description", "").strip()
        nb = create_notebook(name, description)
        return {"status": "success", "notebook": nb}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/v1/notebooks/{nb_id}")
def api_delete_notebook(nb_id: str):
    try:
        from utils.notebook_engine import delete_notebook
        ok = delete_notebook(nb_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Notebook nicht gefunden.")
        return {"status": "deleted", "id": nb_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/notebooks/{nb_id}/sources")
def api_get_notebook_sources(nb_id: str):
    try:
        from utils.notebook_engine import list_sources
        sources = list_sources(nb_id)
        return {"sources": sources, "count": len(sources)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/notebooks/{nb_id}/sources/upload")
async def api_upload_notebook_source(nb_id: str, request: Request):
    # RBAC: Upload schreibt in die Bibliothek -> Admin-Sache (F19/M-03).
    require_admin_or_503(request)
    try:
        from utils.notebook_engine import add_source_file
        form = await request.form()
        file = form.get("file")
        if not file:
            raise HTTPException(status_code=400, detail="Keine Datei übermittelt.")
        file_bytes = await file.read()
        res = add_source_file(nb_id, file_bytes, file.filename)
        return res
    except HTTPException:
        raise
    except PathJailError as pe:
        raise HTTPException(status_code=400, detail=f"Dateiname nicht erlaubt: {pe}")
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/notebooks/{nb_id}/sources/attach-vault")
def api_attach_vault_source(nb_id: str, payload: dict = Body(...)):
    try:
        from utils.notebook_engine import add_source_from_vault
        rel_path = payload.get("rel_path")
        if not rel_path:
            raise HTTPException(status_code=400, detail="rel_path ist erforderlich.")
        res = add_source_from_vault(nb_id, rel_path)
        return res
    except HTTPException:
        raise
    except PathJailError as pe:
        raise HTTPException(status_code=400, detail=f"Pfad nicht erlaubt: {pe}")
    except (ValueError, FileNotFoundError) as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/v1/notebooks/{nb_id}/sources/{src_id}")
def api_delete_notebook_source(nb_id: str, src_id: str):
    try:
        from utils.notebook_engine import delete_source
        ok = delete_source(nb_id, src_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Quelle nicht gefunden.")
        return {"status": "deleted", "source_id": src_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/notebooks/{nb_id}/chat-history")
def api_get_notebook_chat(nb_id: str):
    try:
        from utils.notebook_engine import get_notebook
        nb = get_notebook(nb_id)
        if not nb:
            raise HTTPException(status_code=404, detail="Notebook nicht gefunden.")
        return {"chat_history": nb.get("chat_history", [])}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/notebooks/{nb_id}/query")
async def api_query_notebook(nb_id: str, payload: dict = Body(...)):
    try:
        from utils.notebook_engine import query_notebook
        prompt = payload.get("prompt", "").strip()
        if not prompt:
            raise HTTPException(status_code=400, detail="Prompt ist erforderlich.")
        res = await query_notebook(nb_id, prompt)
        return res
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/notebooks/{nb_id}/sync-obsidian")
def api_sync_notebook_obsidian(nb_id: str, payload: dict = Body(...)):
    try:
        from utils.notebook_engine import save_to_obsidian
        query = payload.get("query", "")
        response_text = payload.get("response", "")
        citations = payload.get("citations", "")
        res = save_to_obsidian(nb_id, query, response_text, citations)
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
