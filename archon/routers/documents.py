"""Router fuer Dokumenten-Parsing und Tabellenextraktion."""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Body, HTTPException, Request

logger = logging.getLogger("archon.routers.documents")

router = APIRouter(tags=["documents"])


def _require_admin_or_503(request: Request):
    import main as app_main

    if hasattr(app_main, "require_admin_or_503"):
        app_main.require_admin_or_503(request)


def _resolve_parser_input(filepath: str) -> str:
    """Prueft den Parser-Eingabepfad gegen die Bibliotheks-Wurzel (D-05)."""
    if not filepath:
        raise HTTPException(status_code=400, detail="Gültiger 'filepath' erforderlich.")
    from utils.batch_library_importer import resolve_raw_docs_dir
    from utils.path_jail import PathJailError, safe_path_within

    try:
        return safe_path_within(
            filepath,
            [resolve_raw_docs_dir()],
            must_exist=True,
            allow_dirs=False,
        )
    except PathJailError as e:
        raise HTTPException(status_code=403, detail=f"Pfad nicht erlaubt: {e}")


@router.post("/api/documents/parse")
@router.post("/api/v1/documents/parse")
def api_parse_document(request: Request, payload: Dict[str, Any] = Body(...)):
    _require_admin_or_503(request)
    from backend.document_parser import DocumentParserEngine

    import main as app_main

    resolve_fn = getattr(app_main, "_resolve_parser_input", _resolve_parser_input)
    real_path = resolve_fn(payload.get("filepath", ""))
    res = DocumentParserEngine.parse_file(real_path)
    return {"status": "success", "result": res}


@router.post("/api/documents/extract-tables")
@router.post("/api/v1/documents/extract-tables")
def api_extract_tables(request: Request, payload: Dict[str, Any] = Body(...)):
    _require_admin_or_503(request)
    from backend.document_parser import DocumentParserEngine

    import main as app_main

    resolve_fn = getattr(app_main, "_resolve_parser_input", _resolve_parser_input)
    real_path = resolve_fn(payload.get("filepath", ""))
    res = DocumentParserEngine.parse_file(real_path)
    tables = res.get("tables") or res.get("tables_by_sheet") or []
    return {"status": "success", "tables": tables, "format": res.get("format")}
