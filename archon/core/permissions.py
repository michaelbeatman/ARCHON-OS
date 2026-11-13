"""Permission-Gates (Rechte-Freigaben durch den Owner).

Aus main.py ausgelagert. Zuständig für Speicherung und Anlage von Gates, die
eine menschliche Freigabe verlangen (Tools vergeben, Profil löschen, …).

Zyklusfreie Kopplung: Das Decision-Subsystem (Kanban-Task + Telegram-Buttons)
lebt weiter in main.py. Statt es zu importieren, registriert main.py beim Start
eine Factory:

    from archon.core import permissions
    permissions.set_decision_factory(create_decision)

Fehlt die Factory, faellt das Gate auf einen direkten Telegram-Ping zurück —
es geht also nie verloren.
"""

from __future__ import annotations

import datetime
import json
import os
import secrets
import threading
from typing import Callable, Dict, Optional

from archon.core.runtime import APP_ROOT, add_ticker, logger

__all__ = [
    "PERMISSION_GATES_FILE", "load_permission_gates", "save_permission_gates",
    "create_permission_gate", "set_decision_factory", "get_decision_factory",
]

PERMISSION_GATES_FILE = os.path.join(APP_ROOT, "config", "permission_gates.json")

_decision_factory: Optional[Callable[..., dict]] = None


def set_decision_factory(fn: Callable[..., dict]) -> None:
    """Registriert create_decision() aus main.py (späte Bindung)."""
    global _decision_factory
    _decision_factory = fn


def get_decision_factory() -> Optional[Callable[..., dict]]:
    return _decision_factory


# F-09: Load->Append->Save muss unter einer Sperre laufen (zwei gleichzeitige
# Gate-Anlagen oder Gate-Anlage parallel zur Freigabe sonst verlustbehaftet).
_GATES_LOCK = threading.Lock()


def load_permission_gates() -> dict:
    try:
        if os.path.exists(PERMISSION_GATES_FILE):
            with open(PERMISSION_GATES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"[Gate] Konnte permission_gates nicht laden: {e}")
    return {"gates": []}


def save_permission_gates(data: dict) -> bool:
    """Schreibt die Gates atomar.

    F-09: Rueckgabe True/False statt stiller Exception-Schluckung —
    create_permission_gate muss wissen, dass das Gate wirklich auf Platte steht,
    bevor der Owner per Telegram zur Freigabe aufgefordert wird.
    """
    try:
        os.makedirs(os.path.dirname(PERMISSION_GATES_FILE), exist_ok=True)
        target = PERMISSION_GATES_FILE
        d = os.path.dirname(os.path.abspath(target)) or "."
        import tempfile
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".permission_gates_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, target)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return True
    except Exception as e:
        logger.warning(f"[Gate] Konnte permission_gates nicht speichern: {e}")
        return False


def create_permission_gate(kind: str, detail: str, requested_by: str, payload: dict) -> dict:
    """Legt ein Pending-Gate an und benachrichtigt den Owner.

    Bevorzugt eine echte Kanban-Entscheidung (Status 'review' mit Buttons);
    ohne Decision-Factory oder bei Fehler wird direkt per Telegram gepingt.
    """
    with _GATES_LOCK:
        gates = load_permission_gates()
        gate_id = f"gate-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(2)}"
        gate = {
            "id": gate_id,
            "kind": kind,
            "detail": detail,
            "requested_by": requested_by,
            "payload": payload,
            "status": "pending",
            "created_at": datetime.datetime.now().isoformat(),
        }
        gates.setdefault("gates", []).append(gate)
        saved = save_permission_gates(gates)
        if not saved:
            # F-09: liegt das Gate nicht auf Platte, darf der Owner auch nicht
            # zur Freigabe aufgefordert werden — er wuerde eine Ablehnung sehen,
            # obwohl er freigegeben hat.
            raise RuntimeError(
                f"Permission-Gate {gate_id} konnte nicht gespeichert werden — Anlage abgebrochen."
            )

    knopf_text = {
        "tools_erweiterung": "🧰 Neue Tools vergeben",
        "profil_loeschen": "🗑️ Profil löschen",
    }.get(kind, "Rechte-Erweiterung")

    text = (
        f"🔐 RECHTE-FREIGABE NÖTIG\n\n"
        f"{knopf_text}\n"
        f"Details: {detail}\n"
        f"Angefordert von: {requested_by}\n"
        f"Gate-ID: {gate_id}\n\n"
        f'Text-Fallback: "Erlauben {gate_id}" oder "Verbieten {gate_id}"'
    )
    reply_markup = {"inline_keyboard": [[
        {"text": "✅ Erlauben", "callback_data": f"gate:approve:{gate_id}"},
        {"text": "❌ Verbieten", "callback_data": f"gate:reject:{gate_id}"},
    ]]}

    factory = get_decision_factory()
    try:
        _dec = {}
        if factory is not None:
            _dec = factory(
                "permission_gate",
                f"{knopf_text}: {str(detail)[:90]}",
                kurzfassung=detail,
                ref_id=gate_id,
                body=(f"Gate-ID: {gate_id}\n{detail}\nAngefordert von: {requested_by}\n\n"
                      f'Text-Fallback: "Erlauben {gate_id}" oder "Verbieten {gate_id}"'),
                extra={"gate_id": gate_id, "requested_by": requested_by,
                       "von": requested_by, "projekt": str(detail)[:60]},
            )
        if not _dec:
            logger.warning("[Gate] Entscheidungs-Task nicht anlegbar — Fallback auf eigenen Ping.")
            from telegram_notify import send_telegram_message
            send_telegram_message(text, reply_markup=reply_markup)
    except Exception as tg_err:
        logger.warning(f"[Gate] Entscheidungs-Ping fehlgeschlagen: {tg_err}")

    add_ticker("Rechte-Gate", f"Owner-Bestätigung offen: {knopf_text} ({gate_id})")
    logger.info(f"[Gate] {kind} fuer '{detail}' -> Warte auf Telegram-Bestätigung ({gate_id})")
    return gate