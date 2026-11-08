"""Cluster 1 — R-09: sechs Router mit destruktiven Pfaden ohne Rollenzaun.

Rot gegen HEAD (909421d6): in ``crm.py``, ``contracts.py``, ``templates.py``,
``memory.py``, ``erp.py`` und ``corporate.py`` kommt ``require_admin`` kein
einziges Mal vor. Es greift nur der globale ``auth_gate`` (Session, keine Rolle).

Geprueft wird zweistufig:

1. **AST** — in jeder der sechs Dateien ist ``require_admin_or_503(request)``
   die *erste* Anweisung jedes Handlers mit POST/PUT/PATCH/DELETE. Damit ist
   auch ein spaeter Zaun (nach ``open()``/Service-Aufruf) ein Fehlschlag.
2. **Laufzeit** — je ein repraesentativer Handler sperrt ``operator`` mit 403,
   bevor Fachcode laeuft. Die Fachfunktionen sind gestubbt.
"""

from __future__ import annotations

import ast
import asyncio
import os

import pytest
from fastapi import HTTPException

from archon_security_support import OPERATOR, import_main, make_request

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("ARCHON_ROOT") or os.path.dirname(_HERE)

MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
GUARD_NAME = "require_admin_or_503"

ROUTER_FILES = [
    "archon/routers/crm.py",
    "archon/routers/contracts.py",
    "archon/routers/templates.py",
    "archon/routers/memory.py",
    "archon/routers/erp.py",
    "archon/routers/corporate.py",
]


def _decorator_methods(node: ast.AST) -> set[str]:
    """Liest die HTTP-Methoden aller ``@router.<method>(...)``-Dekoratoren."""
    methods: set[str] = set()
    for dec in getattr(node, "decorator_list", []):
        if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
            continue
        if not isinstance(dec.func.value, ast.Name) or dec.func.value.id != "router":
            continue
        methods.add(dec.func.attr.upper())
    return methods


def _first_statement_is_guard(func: ast.FunctionDef) -> bool:
    body = list(func.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
            and isinstance(body[0].value.value, str):
        body = body[1:]  # Docstring zaehlt nicht als Anweisung
    if not body:
        return False
    first = body[0]
    if not isinstance(first, ast.Expr) or not isinstance(first.value, ast.Call):
        return False
    call = first.value
    if not isinstance(call.func, ast.Name) or call.func.id != GUARD_NAME:
        return False
    return bool(call.args) and isinstance(call.args[0], ast.Name) and call.args[0].id == "request"


def _mutating_handlers(path: str) -> list[ast.FunctionDef]:
    with open(os.path.join(ROOT, path), "r", encoding="utf-8") as handle:
        tree = ast.parse(handle.read(), filename=path)
    handlers = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and _decorator_methods(node) & MUTATING_METHODS:
            handlers.append(node)
    return handlers


@pytest.mark.parametrize("router_file", ROUTER_FILES)
def test_every_mutating_handler_guards_first(router_file):
    handlers = _mutating_handlers(router_file)
    assert handlers, f"{router_file}: keine mutierenden Handler gefunden (Testaufbau pruefen)"
    unguarded = [h.name for h in handlers if not _first_statement_is_guard(h)]
    assert not unguarded, (
        f"{router_file}: Rollenzaun fehlt oder steht nicht an erster Stelle: {unguarded}"
    )


@pytest.mark.parametrize("router_file", ROUTER_FILES)
def test_router_imports_guard(router_file):
    with open(os.path.join(ROOT, router_file), "r", encoding="utf-8") as handle:
        source = handle.read()
    assert GUARD_NAME in source


# --------------------------------------------------------------------------
# Laufzeit: operator -> 403, bevor Fachcode laeuft
# --------------------------------------------------------------------------

@pytest.fixture()
def operator_session(monkeypatch):
    main = import_main()
    monkeypatch.setattr(main.auth_service, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(main.auth_service, "verify_session", lambda tok: dict(OPERATOR))
    return make_request("/probe", "POST", token="tok_op")


def _call(fn, request, **kwargs):
    return fn(request, **kwargs)


def test_crm_gdpr_anonymize_blocks_operator(monkeypatch, operator_session):
    import backend.crm_service as crm_module
    from archon.routers import crm

    called: list[str] = []
    monkeypatch.setattr(crm_module.crm_service, "anonymize_gdpr",
                        lambda contact_id: called.append(contact_id) or True)

    with pytest.raises(HTTPException) as exc:
        _call(crm.api_crm_gdpr_anonymize, operator_session, contact_id="c-1")

    assert exc.value.status_code == 403
    assert called == []


def test_contracts_delete_blocks_operator(monkeypatch, operator_session):
    import backend.contract_manager as contract_module
    from archon.routers import contracts

    called: list[str] = []
    monkeypatch.setattr(contract_module.ContractManager, "delete",
                        staticmethod(lambda cid: called.append(cid) or True))

    with pytest.raises(HTTPException) as exc:
        _call(contracts.api_delete_contract, operator_session, contract_id="k-1")

    assert exc.value.status_code == 403
    assert called == []


def test_templates_save_blocks_operator(monkeypatch, operator_session):
    from archon.routers import templates

    called: list[int] = []
    monkeypatch.setattr(templates, "_load_prompt_templates", lambda: {"categories": [], "templates": []})
    monkeypatch.setattr(templates, "_save_prompt_templates", lambda data: called.append(1))

    payload = templates.TemplateSaveRequest(
        category="x", title="t", description="", fields={}, raw_text="r",
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(templates.save_prompt_template(operator_session, payload))

    assert exc.value.status_code == 403
    assert called == []


def test_memory_core_block_blocks_operator(monkeypatch, operator_session):
    import backend.core_memory_manager as memory_module
    from archon.routers import memory

    called: list[str] = []
    monkeypatch.setattr(memory_module.core_memory_manager, "upsert_block",
                        lambda **kwargs: called.append("upsert") or {})

    with pytest.raises(HTTPException) as exc:
        _call(memory.api_upsert_core_memory_block, operator_session,
              payload={"block_key": "k", "content": "c"})

    assert exc.value.status_code == 403
    assert called == []


def test_erp_save_document_blocks_operator(monkeypatch, operator_session):
    import backend.erp_manager as erp_module
    from archon.routers import erp

    called: list[str] = []
    monkeypatch.setattr(erp_module.erp_manager, "save_document",
                        lambda **kwargs: called.append("save") or {})

    with pytest.raises(HTTPException) as exc:
        _call(erp.api_erp_save_document, operator_session, payload={"company_id": "c"})

    assert exc.value.status_code == 403
    assert called == []


def test_corporate_delete_blocks_operator(monkeypatch, operator_session):
    import backend.corporate_manager as corporate_module
    from archon.routers import corporate

    called: list[str] = []
    monkeypatch.setattr(corporate_module.corporate_manager, "delete_company",
                        lambda cid: called.append(cid) or True)

    with pytest.raises(HTTPException) as exc:
        _call(corporate.api_delete_corporate_company, operator_session, company_id="f-1")

    assert exc.value.status_code == 403
    assert called == []
