"""
tests/test_w2_d_dispatch_proof.py — W2-D: lückenlose ``llm_dispatch``-Proofs.

D05-H1: Jeder echte LLM-Call (Voice-Transkription, Injection-Klassifikator,
Output-Judge, Research-Synthese v1/v2) schreibt direkt nach der HTTP-Response
einen signierten Dispatch-Proof — auch bei HTTP-Fehler, Transportfehler oder
leerer Antwort (geblockter Proof).

D05-M1: Audit-Schreibfehler aus dem zentralen Helper eskalieren hart als
``RuntimeError`` und werden von keinem Aufrufer verschluckt.

Es werden ausschließlich gemockte HTTP-Responses und gemockte Audit-Writes
verwendet — kein Netzwerk, kein Replay, keine Postgres-/SQLite-Abhängigkeit.
"""

import ast
import asyncio
import json
import os
import sys
import types
from pathlib import Path

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import backend.llm_egress_guard as eg  # noqa: E402
import backend.voice_pipeline as vp  # noqa: E402
import local_security_guard as lsg  # noqa: E402
import research_engine as re1  # noqa: E402
import research_engine_v2 as re2  # noqa: E402


class _FakeResp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


def _capture(target):
    """Monkeypatch-Helper: zeichnet kwargs auf und gibt ein dict-artiges Ergebnis zurück."""
    def _inner(**kwargs):
        target.append(kwargs)
        return {"ok": True}
    return _inner


def _install_fake_httpx(monkeypatch, payload, status_code=200, error=None):
    class _Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **kw):
            if error is not None:
                raise error
            return _FakeResp(payload, status_code)

    monkeypatch.setitem(sys.modules, "httpx", types.SimpleNamespace(AsyncClient=_Client))


def _install_urllib_reply(monkeypatch, module, payload):
    class _Resp:
        def read(self):
            return json.dumps(payload).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(module.urllib.request, "urlopen", lambda *a, **kw: _Resp())


def _patch_voice_env(monkeypatch):
    monkeypatch.setattr(vp, "GROQ_API_KEY", "test-key")
    monkeypatch.setattr(vp, "OPENAI_API_KEY", "")
    monkeypatch.setattr(vp, "GOOGLE_API_KEY", "")
    monkeypatch.setattr(vp, "_gate_cloud_voice_dispatch", lambda url, **kw: {})
    monkeypatch.setattr(
        "backend.privacy_router.get_privacy_config",
        lambda: {"zero_egress_strict": False},
    )


def _patch_security_env(monkeypatch, payload):
    monkeypatch.setattr(lsg, "_enforce_egress_or_block", lambda *a, **kw: None)
    monkeypatch.setattr(
        eg,
        "evaluate_and_gate_llm_dispatch",
        lambda **kw: {"allowed": True, "routed_to_local": False},
    )
    _install_urllib_reply(monkeypatch, lsg, payload)


def _patch_v2_env(monkeypatch):
    import utils.safe_http as safe_http

    monkeypatch.setattr(re2, "OMNIROUTE_KEY", "test-key")
    monkeypatch.setattr(
        re2, "_validate_omniroute_url", lambda url: "http://omniroute:20128/v1"
    )
    monkeypatch.setattr(
        eg, "enforce_egress_firewall_for_url", lambda *a, **kw: {"allowed": True}
    )
    return safe_http


# ---------------------------------------------------------------------------
# Zentraler Helper (D05-H1 + D05-M1)
# ---------------------------------------------------------------------------


def test_audit_dispatch_sync_success_writes_complete_proof(monkeypatch):
    captured = []  # type: ignore[var-annotated]
    monkeypatch.setattr(eg, "log_completed_llm_dispatch", _capture(captured))

    result = eg.audit_dispatch_sync(
        agent_id="voice_pipeline",
        provider="groq",
        model="whisper-large-v3",
        target_endpoint="https://api.groq.com/openai/v1/audio/transcriptions",
        http_status=200,
        completed=True,
        data_category="voice_transcription",
    )

    assert result == {"ok": True}
    assert len(captured) == 1
    proof = captured[0]
    assert proof["provider"] == "groq"
    assert proof["model"] == "whisper-large-v3"
    assert proof["data_category"] == "voice_transcription"
    assert proof["http_status"] == 200
    assert proof["extra"]["target_host"] == "api.groq.com"
    assert proof["extra"]["egress_zone"] == "EXTERNAL_CLOUD"


def test_audit_dispatch_sync_empty_and_http_error_are_blocked_proofs(monkeypatch):
    captured = []  # type: ignore[var-annotated]
    monkeypatch.setattr(eg, "_record_blocked_proof", _capture(captured))

    eg.audit_dispatch_sync(
        provider="groq",
        model="m",
        target_endpoint="https://api.groq.com/v1/x",
        http_status=200,
        completed=False,
        error_code="LLM_EMPTY_RESPONSE",
        reason="empty body",
    )
    eg.audit_dispatch_sync(
        provider="groq",
        model="m",
        target_endpoint="https://api.groq.com/v1/x",
        http_status=503,
        completed=False,
    )

    assert len(captured) == 2
    assert captured[0]["action"] == "llm_dispatch_empty_response"
    assert captured[0]["error_code"] == "LLM_EMPTY_RESPONSE"
    assert captured[0]["extra"]["egress_zone"] == "EXTERNAL_CLOUD"
    assert captured[1]["action"] == "llm_dispatch_failed"
    assert captured[1]["error_code"] == "LLM_HTTP_503"


def test_audit_dispatch_sync_audit_error_escalates_runtime_error(monkeypatch):
    def boom(**kwargs):
        raise OSError("db locked")

    monkeypatch.setattr(eg, "log_completed_llm_dispatch", boom)

    with pytest.raises(RuntimeError, match="audit_write_failed"):
        eg.audit_dispatch_sync(
            provider="openai",
            model="whisper-1",
            target_endpoint="https://api.openai.com/v1/audio/transcriptions",
            completed=True,
        )


def test_audit_dispatch_async_audit_error_escalates_runtime_error(monkeypatch):
    def boom(**kwargs):
        raise OSError("db locked")

    monkeypatch.setattr(eg, "log_completed_llm_dispatch", boom)

    with pytest.raises(RuntimeError, match="audit_write_failed"):
        asyncio.run(
            eg.audit_dispatch_async(
                provider="openai",
                model="whisper-1",
                target_endpoint="https://api.openai.com/v1/audio/transcriptions",
            )
        )


# ---------------------------------------------------------------------------
# Voice-Pipeline (D05-H1)
# ---------------------------------------------------------------------------


def test_voice_groq_success_writes_dispatch_proof(monkeypatch):
    _patch_voice_env(monkeypatch)
    _install_fake_httpx(monkeypatch, {"text": "hallo welt"})
    proofs = []  # type: ignore[var-annotated]
    monkeypatch.setattr(eg, "audit_dispatch_sync", _capture(proofs))

    out = asyncio.run(vp.transcribe_audio_bytes(b"ogg", filename="a.ogg"))

    assert out == "hallo welt"
    assert len(proofs) == 1
    assert proofs[0]["provider"] == "groq"
    assert proofs[0]["model"] == "whisper-large-v3"
    assert proofs[0]["completed"] is True
    assert proofs[0]["data_category"] == "voice_transcription"
    assert proofs[0]["target_endpoint"].startswith("https://api.groq.com/")


def test_voice_empty_body_writes_blocked_proof(monkeypatch):
    _patch_voice_env(monkeypatch)
    _install_fake_httpx(monkeypatch, {"text": ""})
    proofs = []  # type: ignore[var-annotated]
    monkeypatch.setattr(eg, "audit_dispatch_sync", _capture(proofs))

    out = asyncio.run(vp.transcribe_audio_bytes(b"ogg", filename="a.ogg"))

    assert "kein" in out.lower() or "zero-egress" in out.lower()
    assert proofs
    assert proofs[0]["completed"] is False
    assert proofs[0]["error_code"] == "LLM_EMPTY_RESPONSE"


def test_voice_transport_error_writes_blocked_proof(monkeypatch):
    _patch_voice_env(monkeypatch)
    _install_fake_httpx(monkeypatch, {}, error=OSError("offline"))
    proofs = []  # type: ignore[var-annotated]
    monkeypatch.setattr(eg, "audit_dispatch_sync", _capture(proofs))

    asyncio.run(vp.transcribe_audio_bytes(b"ogg", filename="a.ogg"))

    assert proofs
    assert proofs[0]["completed"] is False
    assert proofs[0]["error_code"] == "LLM_TRANSPORT_ERROR"
    assert "offline" in proofs[0]["reason"]


def test_voice_audit_failure_is_not_swallowed(monkeypatch):
    _patch_voice_env(monkeypatch)
    _install_fake_httpx(monkeypatch, {"text": "hallo"})

    def boom(**kwargs):
        raise eg.AuditDispatchError("audit_write_failed: llm_dispatch")

    monkeypatch.setattr(eg, "audit_dispatch_sync", boom)

    with pytest.raises(RuntimeError, match="audit_write_failed"):
        asyncio.run(vp.transcribe_audio_bytes(b"ogg", filename="a.ogg"))


# ---------------------------------------------------------------------------
# Injection-Klassifikator / Output-Judge (D05-H1)
# ---------------------------------------------------------------------------


def test_security_classifier_success_and_empty_body_both_write_proofs(monkeypatch):
    proofs = []  # type: ignore[var-annotated]
    monkeypatch.setattr(eg, "audit_dispatch_sync", _capture(proofs))

    _patch_security_env(
        monkeypatch, {"choices": [{"message": {"content": "SAFE"}}]}
    )
    safe = lsg.scan_prompt_injection(
        "harmless text", sensitivity="strict", use_llm=True,
        omniroute_url="http://127.0.0.1:20128/v1",
    )
    assert safe["verdict"] == "safe"
    assert any(
        p["completed"] is True and p["data_category"] == "security_classification"
        for p in proofs
    )

    proofs.clear()
    _patch_security_env(
        monkeypatch, {"choices": [{"message": {"content": ""}}]}
    )
    blocked = lsg.scan_prompt_injection(
        "harmless text", sensitivity="strict", use_llm=True,
        omniroute_url="http://127.0.0.1:20128/v1",
    )
    assert blocked["verdict"] == "blocked"
    assert any(
        p["completed"] is False and p["error_code"] == "LLM_CLASSIFIER_ERROR"
        for p in proofs
    )


def test_security_judge_success_writes_proof(monkeypatch):
    proofs = []  # type: ignore[var-annotated]
    monkeypatch.setattr(eg, "audit_dispatch_sync", _capture(proofs))
    _patch_security_env(
        monkeypatch, {"choices": [{"message": {"content": "SCORE: 8 | REASON: ok"}}]}
    )

    out = lsg.validate_ai_output(
        "task", "result", min_score=7, use_llm=True,
        judge_model="omniroute/free-forever",
    )

    assert out["passed"] is True
    assert any(
        p["completed"] is True and p["data_category"] == "security_judge"
        for p in proofs
    )


def test_security_guard_audit_failure_is_not_swallowed(monkeypatch):
    _patch_security_env(
        monkeypatch, {"choices": [{"message": {"content": "SAFE"}}]}
    )

    def boom(**kwargs):
        raise eg.AuditDispatchError("audit_write_failed: llm_dispatch")

    monkeypatch.setattr(eg, "audit_dispatch_sync", boom)

    with pytest.raises(RuntimeError, match="audit_write_failed"):
        lsg.scan_prompt_injection(
            "harmless text", sensitivity="strict", use_llm=True,
            omniroute_url="http://127.0.0.1:20128/v1",
        )


# ---------------------------------------------------------------------------
# Research-Synthese v1 / Reflexion v2 (D05-H1)
# ---------------------------------------------------------------------------


def test_research_v1_synthesis_success_and_empty_body_both_write_proofs(monkeypatch):
    proofs = []  # type: ignore[var-annotated]
    monkeypatch.setattr(re1, "audit_dispatch_sync", _capture(proofs))

    _install_urllib_reply(
        monkeypatch, re1, {"choices": [{"message": {"content": "Dossier"}}]}
    )
    ok = re1.query_omniroute_synthesis("frage", [])
    assert ok["synthesis"] == "Dossier"
    assert any(
        p["completed"] is True and p["data_category"] == "research_synthesis"
        for p in proofs
    )

    proofs.clear()
    _install_urllib_reply(
        monkeypatch, re1, {"choices": [{"message": {"content": ""}}]}
    )
    fallback = re1.query_omniroute_synthesis("frage", [])
    assert "Heuristische" in fallback["synthesis"]
    assert any(
        p["completed"] is False and p["error_code"] == "LLM_SYNTHESIS_ERROR"
        for p in proofs
    )


def test_research_v1_audit_failure_is_not_swallowed(monkeypatch):
    _install_urllib_reply(
        monkeypatch, re1, {"choices": [{"message": {"content": "Dossier"}}]}
    )

    def boom(**kwargs):
        raise re1.AuditDispatchError("audit_write_failed: llm_dispatch")

    monkeypatch.setattr(re1, "audit_dispatch_sync", boom)

    with pytest.raises(RuntimeError, match="audit_write_failed"):
        re1.query_omniroute_synthesis("frage", [])


def test_research_v2_reflection_success_writes_proof(monkeypatch):
    proofs = []  # type: ignore[var-annotated]
    monkeypatch.setattr(re2, "audit_dispatch_sync", _capture(proofs))
    safe_http = _patch_v2_env(monkeypatch)
    monkeypatch.setattr(
        safe_http,
        "safe_http_json",
        lambda *a, **kw: {"choices": [{"message": {"content": "ok"}}]},
    )

    out = re2._chat("model", "system", "user", 10)

    assert out == "ok"
    assert any(
        p["completed"] is True and p["data_category"] == "research_reflection"
        for p in proofs
    )


def test_research_v2_reflection_error_writes_blocked_proof(monkeypatch):
    proofs = []  # type: ignore[var-annotated]
    monkeypatch.setattr(re2, "audit_dispatch_sync", _capture(proofs))
    safe_http = _patch_v2_env(monkeypatch)

    def boom(*a, **kw):
        raise OSError("netz weg")

    monkeypatch.setattr(safe_http, "safe_http_json", boom)

    with pytest.raises(OSError):
        re2._chat("model", "system", "user", 10)

    assert any(
        p["completed"] is False and p["error_code"] == "LLM_REFLECTION_ERROR"
        for p in proofs
    )


# ---------------------------------------------------------------------------
# Statische Chokepoint-Verifikation (kein HTTP-Call ohne Proof im Scope)
# ---------------------------------------------------------------------------

_HTTP_CALLS = {"post", "urlopen", "safe_http_json"}
_PROOF_CALLS = {"_audit_voice_dispatch", "_audit_classifier_dispatch", "audit_dispatch_sync"}

_CHECK_FUNCTIONS = {
    "backend/voice_pipeline.py": ("transcribe_audio_bytes",),
    "local_security_guard.py": ("scan_prompt_injection", "validate_ai_output"),
    "research_engine.py": ("query_omniroute_synthesis",),
    "research_engine_v2.py": ("_chat",),
}


def _called_names(node):
    names = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            func = sub.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
    return names


@pytest.mark.parametrize("rel,functions", _CHECK_FUNCTIONS.items())
def test_every_llm_http_call_has_proof_in_same_function(rel, functions):
    tree = ast.parse((Path(BASE_DIR) / rel).read_text(encoding="utf-8"))
    by_name = {
        n.name: n
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    for name in functions:
        assert name in by_name, f"{rel}: {name} fehlt"
        names = _called_names(by_name[name])
        assert names & _HTTP_CALLS, f"{rel}:{name} hat keinen HTTP-Call (Testfehler)"
        assert names & _PROOF_CALLS, (
            f"{rel}:{name} führt einen LLM-HTTP-Call ohne Dispatch-Proof aus"
        )


def test_tts_dispatch_path_has_proof():
    tree = ast.parse(
        (Path(BASE_DIR) / "backend/voice_pipeline.py").read_text(encoding="utf-8")
    )
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "synthesize_speech"
    )
    assert "_audit_voice_dispatch" in _called_names(fn)
