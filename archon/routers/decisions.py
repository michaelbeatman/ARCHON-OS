"""Router & Engine fuer Permission-Gates und zentralen Entscheidungs-Service."""
from __future__ import annotations
from fastapi import Depends as _ArchonDepends
from archon.routers._rbac import forbid_viewer_writes as _forbid_viewer_writes

import asyncio
import datetime
import json
import logging
import os
import threading
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel

from archon.core.constants import _DECISION_TYPEN
from archon.core.permissions import (
    load_permission_gates as _load_permission_gates,
    save_permission_gates as _save_permission_gates,
)

logger = logging.getLogger("archon.routers.decisions")

from archon.routers._validated_body import PassthroughBody, as_payload
router = APIRouter(dependencies=[_ArchonDepends(_forbid_viewer_writes)], tags=["decisions"])

_FOLGE_OK = "Folgeaktion ausgeführt"

# Vorgabe 4: prozessweiter Lock gegen das Decide-Race (zwei parallele Decides auf denselben Task).
# WICHTIG: Der Lock wird NUR innerhalb eines einzigen sync-to_thread-Blocks gehalten — niemals
# ueber await-Hinweg, sonst wuerde er die Event-Loop blockieren.
_DECIDE_RACE_LOCK = threading.RLock()


def _require_admin(request: Request):
    # Zentraler Rollenzaun: eine Pruefung, ein Injectionspunkt, fail-closed.
    from archon.routers._rbac import require_admin_or_503

    require_admin_or_503(request)


# =========================================================================
# PERMISSION-GATE (Owner-Bestaetigung per Telegram)
# =========================================================================


@router.post("/api/permission-gates/{gate_id}/decide")
def api_decide_permission_gate(request: Request, gate_id: str, body: PassthroughBody = Body(...)):
    """Owner-Entscheidung ueber Telegram (Buttons gate:approve/reject oder
    Textbefehl 'Erlauben/Verbieten <gate_id>' via Skill).
    12.10: bewusst SYNCHRON (fastapi-Threadpool) - als async blockierte
    das sync-Innenleben (Save+Telegram) die Event-Loop der ganzen App."""
    import main as app_main

    fn_admin = getattr(app_main, "require_admin", _require_admin)
    fn_admin(request)
    body = as_payload(body)

    decision = str(body.get("decision") or "").lower().strip()
    if decision not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="decision muss approve oder reject sein")

    fn_load_gates = getattr(app_main, "_load_permission_gates", _load_permission_gates)
    fn_save_gates = getattr(app_main, "_save_permission_gates", _save_permission_gates)

    with _DECIDE_RACE_LOCK:
        gates = fn_load_gates()
        gate = next((g for g in gates.get("gates", []) if g.get("id") == gate_id), None)
        if not gate:
            raise HTTPException(status_code=404, detail={"code": "decisions_gate_not_found", "params": {"gate_id": gate_id}})
        if gate.get("status") != "pending":
            return {"status": "already_decided", "decision": gate.get("status"), "gate_id": gate_id}

        # C04: HITL-Gate auch bei der Owner-Entscheidung selbst. Die Telegram-
        # Freigabe bleibt bestehen; ist fuer die Kategorie ein Passkey
        # konfiguriert, zusaetzlich einen gueltigen Proof verlangen. Ohne
        # registrierte Credentials ist `is_passkey_required()` False (unveraendert).
        if decision == "approve":
            try:
                from backend.passkey_hitl import consume_hitl_proof_token, is_passkey_required
                _user = getattr(request.state, "user", None) or {}
                uid = str(_user.get("id") or _user.get("username") or "")
                if not uid:
                    # A (HITL-Bypass): der Decision-Followup ruft per Service-Token
                    # ohne Session an. Nur fuer diesen internen Fall darf er die
                    # uid des Menschen mitgeben, damit der weitergeleitete Proof
                    # gegen dieselbe Identitaet geprueft wird. Externe Aufrufer
                    # koennen die Identitaet nicht ueber den Body ueberschreiben.
                    _has_svc = getattr(app_main, "_request_has_service_token", None)
                    if callable(_has_svc) and _has_svc(request):
                        uid = str(body.get("user_id") or "").strip()
                uid = uid or "owner"
                category = (
                    "destructive_actions" if gate.get("kind") == "profil_loeschen" else "system"
                )
                if is_passkey_required(uid, category):
                    proof = str(
                        body.get("passkey_proof_token")
                        or request.headers.get("x-passkey-proof")
                        or ""
                    ).strip()
                    if not proof or not consume_hitl_proof_token(
                        proof, uid, category,
                        action=f"Gate-Freigabe {gate_id}", resource=gate_id,
                    ):
                        raise HTTPException(
                            status_code=403,
                            detail="Passkey-Verifizierung erforderlich, um dieses Gate freizugeben.",
                        )
            except HTTPException:
                raise
            except Exception as htl_err:
                logger.error(f"[Gate] HITL-Pruefung fehlgeschlagen (fail-closed): {htl_err}")
                raise HTTPException(status_code=503, detail="HITL-Pruefung nicht verfuegbar")

        ergebnis = ""
        ausgefuehrt = False
        ausfuehrungsfehler = None

        if decision == "approve":
            payload = dict(gate.get("payload") or {})
            try:
                fn_save_profile = getattr(app_main, "save_profile", None)
                if not fn_save_profile:
                    from archon.services.profiles_service import save_profile as fn_save_profile
                fn_delete_profile = getattr(app_main, "delete_profile", None)
                if not fn_delete_profile:
                    from archon.services.profiles_service import delete_profile as fn_delete_profile

                if gate.get("kind") == "tools_erweiterung":
                    payload["_approved_gate_id"] = gate_id
                    res = fn_save_profile(payload)
                    ergebnis = f"Tools gespeichert fuer '{payload.get('id')}': " + str(res)
                    ausgefuehrt = True
                elif gate.get("kind") == "profil_loeschen":
                    res = fn_delete_profile(payload.get("profile_id", ""), approved_gate_id=gate_id)
                    ergebnis = f"Profil '{payload.get('profile_id')}' archiviert/geloescht: " + str(res)[:120]
                    ausgefuehrt = True
                else:
                    ergebnis = "Unbekanntes Gate-Kind - nichts ausgefuehrt"
            except Exception as dec_err:
                logger.error(f"[Gate] Ausfuehrung nach Freigabe fehlgeschlagen: {dec_err}")
                ergebnis = f"FEHLER bei der Ausfuehrung: {dec_err}"
                ausfuehrungsfehler = str(dec_err)

            if ausgefuehrt:
                gate["status"] = "approved"
                gate["decided_at"] = datetime.datetime.now().isoformat()
                fn_save_gates(gates)
        else:
            gate["status"] = "rejected"
            gate["decided_at"] = datetime.datetime.now().isoformat()
            fn_save_gates(gates)
            ergebnis = "Abgelehnt - NICHTS wurde geaendert."

    try:
        from telegram_notify import send_telegram_message as _stg

        _stg(f"{'✅' if decision == 'approve' else '❌'} Rechte-Gate {gate_id}\n{ergebnis[:800]}")
    except Exception as tg2:
        logger.warning(f"[Gate] Bestaetigungs-Ping fehlgeschlagen: {tg2}")

    fn_ticker = getattr(app_main, "add_ticker", None)
    if fn_ticker:
        fn_ticker("Rechte-Gate", f"{gate_id}: {'erteilt' if decision == 'approve' else 'abgelehnt'}")
    logger.info(f"[Gate] {gate_id} -> {decision}: {ergebnis[:200]}")

    antwort = {"status": "ok", "decision": decision, "gate_id": gate_id, "ergebnis": ergebnis}
    if ausfuehrungsfehler:
        antwort["status"] = "error"
        antwort["error"] = ausfuehrungsfehler
    return antwort


# =========================================================================
# ZENTRALER ENTSCHEIDUNGS-SERVICE
# =========================================================================


def _decision_kanban_status(typ: str, decision: str) -> str:
    """Semantik der Entscheidung -> Kanban-Zielstatus (review = offen)."""
    approve = decision == "approve"
    return {
        "delegation_review": "todo" if approve else "archived",
        "synthesis_freigabe": "done" if approve else "archived",
        "mission_freigabe": "in_progress" if approve else "archived",
        "permission_gate": "done" if approve else "archived",
        "workflow_hitl_gate": "done" if approve else "blocked",
    }.get(typ, "todo" if approve else "archived")


def _decision_self_api(method: str, path: str, payload: dict = None, timeout: float = 15.0):
    """Selbstaufruf der eigenen API."""
    import main as app_main

    if hasattr(app_main, "_decision_self_api") and app_main._decision_self_api != _decision_self_api:
        return app_main._decision_self_api(method, path, payload=payload, timeout=timeout)

    import urllib.request

    url = f"{os.environ.get('ARCHON_INTERNAL_API_URL', 'http://127.0.0.1:8501')}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"}
    try:
        svc_tok = app_main._get_service_token() if hasattr(app_main, "_get_service_token") else ""
        if svc_tok:
            headers["X-Archon-Service-Token"] = svc_tok
    except Exception as exc:
        # HIGH_SECURITY: Selbstaufrufe laufen ohne Service-Token dann ggf. ohne Auth-Header — sichtbar machen.
        logger.error(f"[Decision] FEHLER (HIGH_SECURITY) _decision_self_api: Service-Token konnte nicht geladen werden: {exc}")
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8") or "{}"
        return json.loads(raw)


def register_decision(
    task_id: str,
    typ: str,
    titel: str,
    kurzfassung: str = "",
    ref_id: str = "",
    dossier: str = None,
    body: str = "",
    extra: dict = None,
    obsidian: str = None,
    created_by: str = "",
) -> dict:
    """Haengt den Entscheidungs-Block an einen BESTEHENDEN Kanban-Task und pingt den Owner mit ✅/❌."""
    import main as app_main

    if typ not in _DECISION_TYPEN or not task_id:
        logger.warning(f"[Decision] register_decision ohne gueltigen Typ/Task ({typ}, {task_id})")
        return {}
    try:
        dec = {
            "typ": typ,
            "ref_id": ref_id,
            "titel": titel,
            "kurzfassung": (kurzfassung or "")[:600],
            "dossier": dossier or "",
            "status": "offen",
            "kanal": "telegram+kanban",
            # Audit D14: Ersteller mitführen, damit api_decide_decision das
            # Vier-Augen-Prinzip hart prüfen kann (leer = nicht zuordenbar).
            "created_by": (created_by or "").strip(),
        }
        if extra:
            dec.update(extra)
        _meta_payload = {"kind": "task", "task_id": task_id, "decision": dec}
        if obsidian and str(obsidian).strip():
            _meta_payload["obsidian"] = str(obsidian).strip()

        fn_self_api = getattr(app_main, "_decision_self_api", _decision_self_api)
        fn_self_api("POST", "/api/operations/kanban/meta", _meta_payload)
        markup = {
            "inline_keyboard": [
                [
                    {"text": "✅ Freigeben", "callback_data": f"app:approve:{task_id}"},
                    {"text": "❌ Ablehnen", "callback_data": f"app:reject:{task_id}"},
                ]
            ]
        }
        _ex = extra or {}
        _zahlen = []
        if _ex.get("teilberichte"):
            _zahlen.append(f"Teilberichte {_ex['teilberichte']}")
        if _ex.get("offene_punkte") is not None:
            _zahlen.append(f"Offene Punkte {_ex['offene_punkte']}")
        _anhang = None
        if dossier and os.path.basename(dossier):
            _bn = os.path.basename(dossier)
            try:
                _kb = max(1, round(os.path.getsize(dossier) / 1024))
            except Exception:
                _kb = 0
            _anhang = _bn + (f" · HTML · {_kb} KB" if _kb else "")
        _projekt = _ex.get("projekt") or (str(obsidian).split("/")[-1] if obsidian else "")
        sent = False
        try:
            from telegram_notify import decision_message, send_telegram_document, send_telegram_message

            caption = decision_message(
                typ=typ,
                titel=titel,
                projekt=_projekt,
                von=_ex.get("von", ""),
                ref=ref_id,
                kurzfassung=(kurzfassung or "")[:600],
                zahlen=_zahlen or None,
                anhang=_anhang,
                fallback_ref=task_id,
                zeit=datetime.datetime.now().strftime("%d.%m.%Y %H:%M"),
            )
            if dossier:
                sent = send_telegram_document(dossier, caption=caption, reply_markup=markup, parse_mode="HTML")
            if not sent:
                sent = send_telegram_message(caption, reply_markup=markup)
        except Exception as tg_err:
            logger.warning(f"[Decision] Telegram-Ping fehlgeschlagen: {tg_err}")
        logger.info(f"[Decision] {typ} registriert: Kanban {task_id} (ref={ref_id}), Ping={sent}")
        return {"task_id": task_id, "decision": dec}
    except Exception as e:
        logger.warning(f"[Decision] Konnte Entscheidung nicht registrieren: {e}")
        return {}


def create_decision(
    typ: str,
    titel: str,
    kurzfassung: str = "",
    ref_id: str = "",
    dossier: str = None,
    body: str = "",
    extra: dict = None,
    obsidian: str = None,
    created_by: str = "",
) -> dict:
    """Legt einen NEUEN Entscheidungs-Task im Kanban an und registriert die Entscheidung darauf."""
    import main as app_main

    if typ not in _DECISION_TYPEN:
        logger.warning(f"[Decision] Unbekannter Typ '{typ}'")
        return {}
    try:
        fn_self_api = getattr(app_main, "_decision_self_api", _decision_self_api)
        res = fn_self_api(
            "POST",
            "/api/operations/kanban/tasks",
            {
                "title": (titel or "Entscheidung")[:180],
                "body": body or kurzfassung,
                "assignee": "executive_decision_architect",
                "column": "review",
                "priority": 1,
            },
        )
        task_id = res.get("task_id")
        if not task_id:
            logger.warning(f"[Decision] Task-Anlage lieferte keine ID: {res}")
            return {}
    except Exception as e:
        logger.warning(f"[Decision] Konnte Entscheidungs-Task nicht anlegen: {e}")
        return {}
    fn_reg = getattr(app_main, "register_decision", register_decision)
    return fn_reg(task_id, typ, titel, kurzfassung, ref_id, dossier, body, extra, obsidian, created_by)


def _folge_nicht(aktion: str, grund: str) -> str:
    """Ehrliche Meldung: nichts ausgefuehrt, Grund aus der Antwort."""
    return f"Folgeaktion nicht ausgeführt: {aktion} — {grund}"


def _antwort_grund(antwort: Any) -> str:
    """Kurzgrund aus einer Fehlerantwort, ohne den Body zu verschlucken."""
    if not isinstance(antwort, dict):
        return f"Antwort ist kein JSON-Objekt ({type(antwort).__name__})"
    detail = antwort.get("error") or antwort.get("detail") or antwort.get("ergebnis")
    return str(detail or antwort.get("status") or "ohne Begründung")[:300]


def _pruefe_move_antwort(antwort: Any, ref: str) -> str:
    """Vertrag von POST /api/mission-control/tasks/move: {"status": "ok", "task": {...}}"""
    if not isinstance(antwort, dict) or antwort.get("status") != "ok":
        return _antwort_grund(antwort)
    task = antwort.get("task")
    if not isinstance(task, dict):
        return "Antwort ohne Task-Objekt"
    if str(task.get("id") or "") != str(ref):
        return f"Antwort betrifft Task '{task.get('id')}' statt '{ref}'"
    if task.get("status") != "in_progress":
        return f"Task-Status '{task.get('status')}' statt 'in_progress'"
    return ""


def _pruefe_gate_persistiert(ref: str) -> str:
    """Persistierter Gate-Status: nur ein 'approved'-Gate gilt als ausgefuehrt."""
    import main as app_main

    fn_load_gates = getattr(app_main, "_load_permission_gates", _load_permission_gates)
    try:
        gates = fn_load_gates() or {}
    except Exception as e:
        return f"Gate-Status nicht lesbar ({e})"
    gate = next((g for g in gates.get("gates", []) if str(g.get("id")) == str(ref)), None)
    if gate is None:
        return f"Gate '{ref}' nicht im Gate-Store gefunden"
    if gate.get("status") != "approved":
        return f"Gate-Status '{gate.get('status')}' statt 'approved'"
    return ""


def _pruefe_gate_antwort(antwort: Any, ref: str) -> str:
    """Vertrag von POST /api/permission-gates/{id}/decide: status ok|error|already_decided."""
    if not isinstance(antwort, dict) or antwort.get("status") != "ok":
        return _antwort_grund(antwort)
    if str(antwort.get("gate_id") or "") != str(ref):
        return f"Antwort betrifft Gate '{antwort.get('gate_id')}' statt '{ref}'"
    if str(antwort.get("decision") or "").lower() != "approve":
        return f"Antwort meldet Entscheidung '{antwort.get('decision')}' statt 'approve'"
    return _pruefe_gate_persistiert(ref)


# A (Audit 23.11.2026): Decision-Freigaben dieser Typen duerfen niemals ohne
# verifizierten, an die ref_id gebundenen Passkey-Proof ausgefuehrt werden.
_DECISION_HITL_TYPEN = {"permission_gate", "mission_freigabe"}


def _decision_session_actor_uid(request: Request) -> str:
    """Einzige Autoritaet fuer die Proof-Identitaet: der Session-Actor.

    WICHTIG (User-Entscheidung 24.11.2026): Der externe Decision-Endpoint
    akzeptiert NIEMALS eine Client-UID aus dem Body (``user_id``, ``username``
    o. a.) als Proof-Identitaet. Body-``user_id`` wird ausschliesslich vom
    internen Service-Token-Followup an den Gate-Endpoint weitergegeben
    (siehe ``_followup_permission_gate``). Diese Funktion liest bewusst nur
    den Request (Session/Cookie/Header) — nie den Body.
    """
    try:
        from archon.routers.auth import get_current_user_from_request
        actor = get_current_user_from_request(request)
    except Exception as exc:
        logger.error(f"[Decision] HITL-Actor nicht ermittelbar (fail-closed): {exc}")
        raise HTTPException(status_code=503, detail="HITL-Actor nicht verfuegbar")
    uid = str(actor.get("id") or actor.get("username") or "").strip()
    if not uid or str(actor.get("role") or "") == "anonymous":
        raise HTTPException(status_code=403, detail="Kein authentifizierter Session-Actor fuer den Passkey-Proof.")
    return uid


def _decision_hitl_proof(request: Request, body: dict, typ: str, ref: str) -> tuple:
    """Prueft den HITL-Proof einer Decision-Freigabe (fail-closed).

    Liefert ``(proof_token, uid)`` zurueck. Der Proof wird bewusst NICHT
    konsumiert (``consume=False``): derselbe Token wird vom Followup an den
    Gate-Endpoint weitergeleitet und dort genau einmal verbraucht.

    Die Bindung an ``resource=ref`` stellt sicher, dass ein Proof fuer Gate A
    keine Mission B oder Gate B freigeben kann.

    Identitaet: ausschliesslich ``_decision_session_actor_uid(request)``. Der
    ``body``-Parameter existiert nur fuer den Proof-Token; eine dort mitgelieferte
    UID wird ignoriert (siehe ``_decision_session_actor_uid``).
    """
    import main as app_main
    from backend.passkey_hitl import consume_hitl_proof_token, is_passkey_required

    # Ohne ref_id gibt es keine Zielbindung fuer den Proof -> fail-closed.
    if not str(ref or "").strip():
        raise HTTPException(status_code=403, detail="Entscheidung ohne ref_id — kein HITL-Proof moeglich.")

    uid = _decision_session_actor_uid(request)

    if typ == "permission_gate":
        fn_load_gates = getattr(app_main, "_load_permission_gates", _load_permission_gates)
        try:
            gates = fn_load_gates() or {}
        except Exception:
            gates = {}  # Kategorie bleibt 'system' (Hochrisiko) -> fail-closed
        gate = next((g for g in gates.get("gates", []) if str(g.get("id")) == str(ref)), None)
        category = "destructive_actions" if gate and gate.get("kind") == "profil_loeschen" else "system"
        action = f"Gate-Freigabe {ref}"
    else:
        category = "system"
        action = f"Mission-Freigabe {ref}"

    # Kompatibilitaet: der direkte Gate-Endpoint verlangt ebenfalls NUR dann
    # einen Proof, wenn fuer die Identitaet/Kategorie ein Passkey konfiguriert
    # ist. Ohne diese Prüfung blockierte der Härtungs-Fix alle UI-Freigaben,
    # auch in Installationen ohne registrierte Credentials.
    try:
        if not is_passkey_required(uid, category):
            return "", uid
    except Exception as exc:
        logger.error(f"[Decision] Passkey-Konfiguration nicht lesbar (fail-closed): {exc}")
        raise HTTPException(status_code=503, detail="HITL-Konfiguration nicht verfuegbar")

    proof = str(body.get("passkey_proof_token") or "").strip()
    if not proof:
        proof = str(request.headers.get("x-passkey-proof") or "").strip()
    if not proof:
        raise HTTPException(
            status_code=403,
            detail="Passkey-Verifizierung erforderlich, um diese Entscheidung freizugeben.",
        )

    try:
        ok = consume_hitl_proof_token(
            proof, uid, category, action=action, resource=ref, consume=False
        )
    except Exception as exc:
        logger.error(f"[Decision] HITL-Pruefung fehlgeschlagen (fail-closed): {exc}")
        raise HTTPException(status_code=503, detail="HITL-Pruefung nicht verfuegbar")
    if not ok:
        logger.warning(f"[Decision] Ungueltiger/abweichend gebundener HITL-Proof fuer {typ} {ref} (uid={uid}).")
        raise HTTPException(
            status_code=403,
            detail="Ungueltiger oder nicht an diese Entscheidung gebundener Passkey-Proof.",
        )
    return proof, uid


def _pruefe_synthese_beleg(task: Any) -> str:
    """Persistierter Parent-Task der Synthese: finalized UND completed."""
    if task is None:
        return "Parent-Task nicht in Mission Control gefunden"
    if not task.get("synthesis_finalized"):
        return "synthesis_finalized nicht gesetzt"
    if task.get("status") != "completed":
        return f"Parent-Status '{task.get('status')}' statt 'completed'"
    return ""


async def _synthese_parent(pid: str):
    """(lesbar, task) aus dem persistierten Mission-Control-Store."""
    import main as app_main

    fn_load_mc = getattr(app_main, "_load_mission_control_data", None)
    try:
        if fn_load_mc:
            data = await asyncio.to_thread(fn_load_mc) or {}
        else:
            from archon.core.mission_control import _load_mission_control_data as _def_load_mc

            data = await asyncio.to_thread(_def_load_mc) or {}
    except Exception as e:
        logger.warning(f"[Decision] Mission-Control-Store nicht lesbar: {e}")
        return False, None
    task = next((t for t in data.get("tasks", []) if str(t.get("id")) == str(pid)), None)
    return True, task


async def _followup_synthesis(pid: str, dossier: str, dec: dict) -> str:
    import main as app_main

    aktion = f"Synthese für {pid}"
    lesbar, vorher = await _synthese_parent(pid)
    if not lesbar:
        return _folge_nicht(aktion, "Mission-Control-Store nicht lesbar — nicht verifizierbar")
    if vorher is not None and vorher.get("synthesis_finalized"):
        return _folge_nicht(aktion, "bereits finalisiert (synthesis_finalized=true)")
    try:
        full_synth = ""
        if dossier and os.path.isfile(dossier):
            try:
                with open(dossier, "r", encoding="utf-8") as df:
                    full_synth = df.read()
            except Exception:
                full_synth = ""
        if not full_synth:
            full_synth = dec.get("kurzfassung") or ""

        fn_finalize = getattr(app_main, "_finalize_synthesis_after_approval", None)
        if fn_finalize:
            await fn_finalize(
                pid, dossier, full_synth, "Owner-Freigabe über den Entscheidungs-Service"
            )
        else:
            from archon.core.orchestration import _finalize_synthesis_after_approval as _def_fin

            await _def_fin(pid, dossier, full_synth, "Owner-Freigabe über den Entscheidungs-Service")
    except Exception as e:
        return _folge_nicht(aktion, f"Aufruf fehlgeschlagen: {e}")
    lesbar, nachher = await _synthese_parent(pid)
    if not lesbar:
        return _folge_nicht(aktion, "Mission-Control-Store nicht lesbar — nicht verifizierbar")
    grund = _pruefe_synthese_beleg(nachher)
    if grund:
        return _folge_nicht(aktion, grund)
    return f"{_FOLGE_OK}: Synthese {pid} finalisiert (belegt: synthesis_finalized=true, status=completed)."


async def _followup_mission_start(ref: str) -> str:
    import main as app_main

    aktion = f"Ausführung für Mission {ref or '(ohne ref_id)'}"
    if not ref:
        return _folge_nicht(aktion, "Entscheidungs-Block trägt keine ref_id")
    try:
        fn_self_api = getattr(app_main, "_decision_self_api", _decision_self_api)
        antwort = await asyncio.to_thread(
            fn_self_api, "POST", "/api/mission-control/tasks/move", {"task_id": ref, "target_status": "in_progress"}
        )
    except Exception as e:
        return _folge_nicht(aktion, f"Aufruf fehlgeschlagen: {e}")
    grund = _pruefe_move_antwort(antwort, ref)
    if grund:
        return _folge_nicht(aktion, grund)
    return (
        f"{_FOLGE_OK}: Mission {ref} auf 'in_progress' verschoben und Ausführung "
        "angestoßen (belegt: move status=ok, task.status=in_progress)."
    )


async def _followup_permission_gate(ref: str, proof_token: str = "", proof_uid: str = "") -> str:
    import main as app_main

    aktion = f"Rechte-Gate {ref or '(ohne ref_id)'}"
    if not ref:
        return _folge_nicht(aktion, "Entscheidungs-Block trägt keine ref_id")
    # A (HITL-Bypass): Ist fuer die Identitaet ein Passkey konfiguriert, darf der
    # Service-Token-Aufruf das Gate ohne Proof NEVER freigeben. Ohne konfigurierte
    # Credentials bleibt das bestehende (dokumentierte) Verhalten erhalten.
    proof = str(proof_token or "").strip()
    if not proof:
        try:
            from backend.passkey_hitl import is_passkey_required
            _uid = str(proof_uid or "owner").strip() or "owner"
            if is_passkey_required(_uid, "system") or is_passkey_required(_uid, "destructive_actions"):
                logger.error(f"[Gate] Kein HITL-Proof für {ref} — Freigabe NICHT ausgeführt, Decision bleibt pending.")
                return _folge_nicht(aktion, "kein verifizierter Passkey-Proof — Decision bleibt pending")
        except Exception as exc:
            logger.error(f"[Gate] Passkey-Konfiguration nicht lesbar (fail-closed) für {ref}: {exc}")
            return _folge_nicht(aktion, "HITL-Konfiguration nicht verfuegbar — Decision bleibt pending")
    payload = {
        "decision": "approve",
    }
    if proof:
        # Zielfeldname des Gate-Endpoints (decisions.py:91): passkey_proof_token.
        payload["passkey_proof_token"] = proof
    # Der Followup läuft per Service-Token ohne Session: die uid des Menschen
    # aus der Decision wird nur für diesen internen Aufruf mitgegeben, damit
    # der Gate-Endpoint denselben Proof gegen dieselbe Identität prüft.
    if str(proof_uid or "").strip():
        payload["user_id"] = str(proof_uid).strip()
    try:
        fn_self_api = getattr(app_main, "_decision_self_api", _decision_self_api)
        antwort = await asyncio.to_thread(
            fn_self_api, "POST", f"/api/permission-gates/{ref}/decide", payload
        )
    except Exception as e:
        return _folge_nicht(aktion, f"Aufruf fehlgeschlagen: {e}")
    grund = _pruefe_gate_antwort(antwort, ref)
    if grund:
        return _folge_nicht(aktion, grund)
    return f"{_FOLGE_OK}: Rechte-Gate {ref} freigegeben (belegt: status=ok, Gate persistiert als 'approved')."


async def _decision_followup(typ: str, dec: dict, decision: str, proof_token: str = "", proof_uid: str = "") -> str:
    """Fuehrt nach der Statusaenderung die typ-spezifische Folgeaktion aus."""
    import main as app_main

    ref = dec.get("ref_id") or ""
    dossier = dec.get("dossier") or ""
    if decision != "approve":
        return "Abgelehnt — keine Folgeaktion ausgeführt."
    if typ == "synthesis_freigabe":
        fn_fs = getattr(app_main, "_followup_synthesis", _followup_synthesis)
        return await fn_fs(ref or "projekt", dossier, dec)
    if typ == "mission_freigabe":
        if str(ref).startswith("evt-"):
            try:
                from backend.workflow_scheduler import approve_and_replay_hitl_event
                res = await asyncio.to_thread(approve_and_replay_hitl_event, ref)
                trig = len(res.get("triggered") or [])
                return f"{_FOLGE_OK}: Event-Bus HITL-Event {ref} freigegeben ({res.get('status')}, {trig} Workflow-Runs gestartet)."
            except Exception as exc:
                return _folge_nicht(f"Event-Bus HITL-Freigabe {ref}", str(exc))
        fn_fm = getattr(app_main, "_followup_mission_start", _followup_mission_start)
        return await fn_fm(ref)
    if typ == "permission_gate":
        fn_fp = getattr(app_main, "_followup_permission_gate", _followup_permission_gate)
        return await fn_fp(ref, proof_token, proof_uid)
    return "Keine Folgeaktion nötig (Statusänderung genügt)."


@router.post("/api/decisions/decide", dependencies=[_ArchonDepends(_require_admin)])
async def api_decide_decision(request: Request, body: PassthroughBody = Body(...)):
    body = as_payload(body)
    """EINZIGER Schreibpfad für Entscheidungen — Telegram UND Kanban rufen ihn."""
    import main as app_main

    task_id = str(body.get("task_id") or "").strip()
    decision = str(body.get("decision") or "").lower().strip()
    # Audit D14: ApproverIdentity NIE aus dem Body — sonst kann ein Client
    # beliebige "von"-Werte simulieren und Vier-Augen vortäuschen.
    from archon.routers._rbac import require_session_actor

    von = require_session_actor(request)
    if decision not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="decision muss approve oder reject sein")
    if not task_id:
        raise HTTPException(status_code=400, detail="task_id fehlt")

    fn_self_api = getattr(app_main, "_decision_self_api", _decision_self_api)

    # A (HITL-Bypass): Proof wird VOR dem CAS-Marker geprüft. Bei Fehlschlag
    # bleibt der Decision-Block 'offen' (pending) und es läuft keine Folgeaktion.
    # Session-Actor ist einzige Autorität: proof_uid kommt ausschließlich aus
    # _decision_hitl_proof() -> _decision_session_actor_uid(request). Eine
    # Client-UID aus `body` wird bewusst nicht übernommen (auch nicht als
    # Fallback) und fließt damit nie in den Service-Token-Followup.
    proof_token, proof_uid = "", ""

    # Vorgabe 4: Compare-And-Set atomar in EINEM to_thread-Block unter prozessweitem Lock:
    # Sidecar-Status-Read -> already_decided-Check -> 'in_bearbeitung'-Marker vor dem Followup.
    # Wer 'offen' nicht mehr antrifft, bekommt already_decided (kein doppeltes Followup).
    def _cas_claim() -> dict:
        nonlocal proof_token, proof_uid
        with _DECIDE_RACE_LOCK:
            meta = fn_self_api("GET", "/api/operations/kanban/meta")
            dec_local = (meta.get("tasks", {}).get(task_id, {}) or {}).get("decision")
            if not dec_local:
                return {"_error": "no_decision"}
            if (dec_local.get("status") or "offen") != "offen":
                return {"_error": "already_decided", "dec": dec_local}
            creator = str(dec_local.get("created_by") or "").strip()
            if creator and creator == von:
                logger.warning(
                    "[Decision] Vier-Augen-Verletzung: Task %s wurde von '%s' erstellt "
                    "und soll von derselben Person freigegeben werden.", task_id, von
                )
                return {"_error": "four_eyes_violation", "detail": "Ersteller darf nicht selbst freigeben (Vier-Augen-Prinzip)."}
            if decision == "approve" and str(dec_local.get("typ") or "") in _DECISION_HITL_TYPEN:
                try:
                    proof_token, proof_uid = _decision_hitl_proof(
                        request, body, str(dec_local.get("typ")), str(dec_local.get("ref_id") or "")
                    )
                except HTTPException as proof_err:
                    logger.error(
                        f"[Decision] HITL-Proof fehlt/ungueltig für Task {task_id} "
                        f"(typ={dec_local.get('typ')}): {proof_err.detail} — Decision bleibt pending."
                    )
                    return {
                        "_error": "hitl_proof_required",
                        "status": proof_err.status_code,
                        "detail": proof_err.detail,
                    }
            try:
                fn_self_api(
                    "POST",
                    "/api/operations/kanban/meta",
                    {
                        "kind": "task",
                        "task_id": task_id,
                        "decision": {"status": "in_bearbeitung", "decided_by": von, "decision": decision},
                    },
                )
            except Exception as e:
                logger.warning(f"[Decision] CAS-Marker ('in_bearbeitung') konnte nicht gesetzt werden: {e}")
                return {"_error": "cas_write_failed", "detail": str(e)}
            return {"_ok": True, "dec": dec_local}

    try:
        claim = await asyncio.to_thread(_cas_claim)
    except Exception as e:
        raise HTTPException(status_code=502, detail={"code": "decisions_sidecar_unreadable", "params": {"error": str(e)}})
    if claim.get("_error") == "cas_write_failed":
        raise HTTPException(status_code=502, detail={"code": "decisions_cas_write_failed", "params": {"error": claim.get("detail", "")}})
    if claim.get("_error") == "no_decision":
        raise HTTPException(status_code=404, detail={"code": "decisions_no_decision_block", "params": {"task_id": task_id}})
    if claim.get("_error") == "hitl_proof_required":
        raise HTTPException(status_code=int(claim.get("status") or 403), detail=claim.get("detail") or "Passkey-Verifizierung erforderlich.")
    if claim.get("_error") == "four_eyes_violation":
        raise HTTPException(status_code=403, detail=claim.get("detail") or "Vier-Augen-Prinzip verletzt.")
    if claim.get("_error") == "already_decided":
        dec = claim.get("dec") or {}
        return {
            "status": "already_decided",
            "task_id": task_id,
            "decision": decision,
            "kanban_status": dec.get("status"),
            "ergebnis": "Bereits entschieden — nicht erneut ausgeführt.",
        }
    dec = claim["dec"]

    fn_stat = getattr(app_main, "_decision_kanban_status", _decision_kanban_status)
    typ = dec.get("typ")
    ziel = fn_stat(typ, decision)

    try:
        await asyncio.to_thread(
            fn_self_api,
            "PATCH",
            f"/api/operations/kanban/tasks/{task_id}/status",
            {"status": ziel, "source": "decision"},
        )
    except Exception as e:
        logger.warning(f"[Decision] Kanban-Statusupdate fehlgeschlagen: {e}")

    try:
        fn_followup = getattr(app_main, "_decision_followup", _decision_followup)
        ergebnis = await fn_followup(typ, dec, decision, proof_token, proof_uid)
    except Exception as e:
        logger.error(f"[Decision] Folgeaktion fehlgeschlagen: {e}")
        ergebnis = f"FEHLER bei der Folgeaktion: {e}"

    # Workflow-HITL-Gate: Freigabe UND Ablehnung resume den Run (False = downstream wird skipped).
    if typ == "workflow_hitl_gate":
        ref = str(dec.get("ref_id") or "")
        run_id, _, node_id = ref.partition(":")
        if run_id and node_id:
            try:
                # DEFERRED-Import: Helper wird parallel in Paket B (backend/workflow_dag_runner.py) gebaut.
                # schedule_workflow_resume ist ein sync-Caller (legt nur den Hintergrund-Task an) — direkt rufen.
                from backend.workflow_dag_runner import schedule_workflow_resume

                schedule_workflow_resume(
                    run_id=run_id,
                    gate_approvals={node_id: decision == "approve"},
                )
                ergebnis += f" | Workflow-Run `{run_id}` wird am Knoten `{node_id}` fortgesetzt."
            except ImportError:
                # FALLBACK (Helper noch nicht gemerged): direkter Hintergrund-Task — markiert als Uebergang.
                try:
                    from backend.workflow_dag_runner import resume_workflow_run

                    asyncio.create_task(resume_workflow_run(
                        run_id=run_id,
                        gate_approvals={node_id: decision == "approve"},
                    ))
                    ergebnis += f" | Workflow-Run `{run_id}` wird am Knoten `{node_id}` fortgesetzt (Fallback-Pfad)."
                except Exception as e:
                    logger.error(f"[Decision] Workflow-Resume-Fallback fehlgeschlagen: {e}")
                    ergebnis += f" | Workflow-Resume nicht gestartet: {e}"
            except Exception as e:
                logger.error(f"[Decision] Workflow-Resume-Scheduling fehlgeschlagen: {e}")
                ergebnis += f" | Workflow-Resume nicht gestartet: {e}"
        else:
            ergebnis += " | Workflow-Resume übersprungen: ref_id enthält keine run_id:node_id-Kombination."

    # HITL-Sackgasse schliessen: der DAG-Resume allein setzt die Content-Assets
    # nicht auf approved/scheduled. Sie blieben auf 'review' und wurden nie
    # publiziert. Idempotent: nur review/draft werden umgesetzt.
    if typ == "workflow_hitl_gate" and run_id:
        try:
            from backend.content_machine import finalize_assets_for_workflow_run

            fin = finalize_assets_for_workflow_run(run_id, approved=(decision == "approve"))
            if fin.get("status") == "ok" and fin.get("updated"):
                ergebnis += f" | {fin['updated']} Content-Assets → {fin['target_status']}."
        except Exception as fin_exc:
            logger.error(f"[Decision] Content-Asset-Abschluss fehlgeschlagen: {fin_exc}")

    try:
        await asyncio.to_thread(
            fn_self_api,
            "POST",
            "/api/operations/kanban/meta",
            {
                "kind": "task",
                "task_id": task_id,
                "decision": {
                    "status": "freigegeben" if decision == "approve" else "abgelehnt",
                    "entschieden_von": von,
                    "entschieden_am": datetime.datetime.now().isoformat(),
                },
            },
        )
    except Exception as e:
        logger.warning(f"[Decision] Sidecar-Update fehlgeschlagen: {e}")

    if typ != "permission_gate":
        try:
            from telegram_notify import send_telegram_message, tg_escape

            _e = tg_escape
            send_telegram_message(
                f"{'✅' if decision == 'approve' else '❌'} <b>{_e(dec.get('titel') or task_id)}</b>\n"
                f"Kanban: <code>{_e(ziel)}</code>\n{_e(ergebnis[:700])}"
            )
        except Exception as e:
            logger.warning(f"[Decision] Bestätigungs-Ping fehlgeschlagen: {e}")

    fn_ticker = getattr(app_main, "add_ticker", None)
    if fn_ticker:
        fn_ticker("Entscheidung", f"{task_id} ({typ}) -> {decision}")
    logger.info(f"[Decision] {task_id} ({typ}) -> {decision}: {ergebnis[:200]}")
    return {"status": "ok", "task_id": task_id, "decision": decision, "kanban_status": ziel, "ergebnis": ergebnis}


def _sync_org_hierarchy_node(
    p_id: str,
    name: Optional[str] = None,
    person_name: Optional[str] = None,
    avatar: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    reasoning_level: Optional[str] = None,
):
    """Synchronisiert Änderungen eines Agenten-Profils direkt in config/org_hierarchy.json und leert den Operations-Cache."""
    import main as app_main

    try:
        root_dir = (
            os.path.dirname(os.path.abspath(app_main.__file__))
            if hasattr(app_main, "__file__")
            else os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        )
        org_file = os.path.join(root_dir, "config", "org_hierarchy.json")
        if os.path.exists(org_file):
            with open(org_file, "r", encoding="utf-8") as f:
                org_data = json.load(f)
            changed = False
            for node in org_data.get("nodes", []):
                if isinstance(node, dict) and node.get("id") == p_id:
                    if name:
                        node["name"] = name
                        node["role"] = name
                    if person_name:
                        node["person_name"] = person_name
                    if avatar:
                        node["avatar"] = avatar
                    if provider:
                        node["provider"] = provider
                    if model:
                        node["model"] = model
                    if reasoning_level:
                        node["reasoning_level"] = reasoning_level
                    changed = True
            if changed:
                with open(org_file, "w", encoding="utf-8") as f:
                    json.dump(org_data, f, indent=2, ensure_ascii=False)
        try:
            import backend.operations_api as _ops_api

            _ops_api._PROFILES_MAP_CACHE["mtime"] = 0.0
        except Exception as exc:
            logger.debug(f"[SSOT] _sync_org_hierarchy_node: Profile-Cache-Invalidierung uebersprungen (Fallback): {exc}")
    except Exception as e:
        logger.warning(f"[SSOT] Could not sync org_hierarchy.json for {p_id}: {e}")
