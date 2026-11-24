"""Router fuer Dokumenten-Parsing und Tabellenextraktion."""
from __future__ import annotations
from fastapi import Depends as _ArchonDepends
from archon.routers._rbac import forbid_viewer_writes as _forbid_viewer_writes

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("archon.routers.documents")

router = APIRouter(dependencies=[_ArchonDepends(_forbid_viewer_writes)], tags=["documents"])


class DocumentParseRequest(BaseModel):
    """Payload fuer /parse und /extract-tables (D-05: Pfad-Jail im Handler)."""
    model_config = ConfigDict(extra="ignore")
    filepath: str = Field(default="", max_length=1024)


def _require_admin_or_503(request: Request):
    # Zentraler Rollenzaun: eine Pruefung, ein Injectionspunkt, fail-closed.
    from archon.routers._rbac import require_admin_or_503

    require_admin_or_503(request)


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
        raise HTTPException(status_code=403, detail={"code": "documents_path_not_allowed", "params": {"error": str(e)}})


@router.post("/api/documents/parse")
@router.post("/api/v1/documents/parse")
def api_parse_document(request: Request, payload: DocumentParseRequest):
    _require_admin_or_503(request)
    from backend.document_parser import DocumentParserEngine

    import main as app_main

    if isinstance(payload, dict):  # direkte Aufrufe (Tests/Interop) weiterhin moeglich
        payload = DocumentParseRequest.model_validate(payload)
    resolve_fn = getattr(app_main, "_resolve_parser_input", _resolve_parser_input)
    real_path = resolve_fn(payload.filepath)
    res = DocumentParserEngine.parse_file(real_path)
    return {"status": "success", "result": res}


@router.post("/api/documents/extract-tables")
@router.post("/api/v1/documents/extract-tables")
def api_extract_tables(request: Request, payload: DocumentParseRequest):
    _require_admin_or_503(request)
    from backend.document_parser import DocumentParserEngine

    import main as app_main

    if isinstance(payload, dict):  # direkte Aufrufe (Tests/Interop) weiterhin moeglich
        payload = DocumentParseRequest.model_validate(payload)
    resolve_fn = getattr(app_main, "_resolve_parser_input", _resolve_parser_input)
    real_path = resolve_fn(payload.filepath)
    res = DocumentParserEngine.parse_file(real_path)
    tables = res.get("tables") or res.get("tables_by_sheet") or []
    return {"status": "success", "tables": tables, "format": res.get("format")}
