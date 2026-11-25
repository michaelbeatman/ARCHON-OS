"""Root-Wrapper fuer den PocketBase-CRM-Abgleich.

D16/H-16-4: alle PocketBase-Calls laufen ueber `pb_request()` mit einem
W3C-Child-Span, injizierten Headern und `trace_id` als Collection-Feld.
D12/W2-B-Eskalation: Fehler werden nie als leere Kontaktliste zurueckgegeben,
sondern als strukturiertes `ContactsResult` mit status/error_code.
"""

import os
import sys
import json
import logging
import contextlib

import requests

logger = logging.getLogger("archon.crm_mcp")

POCKETBASE_URL = os.getenv("POCKETBASE_URL", "http://127.0.0.1:8090")
COLLECTION_NAME = "kontakte"

_WORKSPACE_ROOT = os.path.dirname(os.path.abspath(__file__))
if _WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, _WORKSPACE_ROOT)


class ContactsResult(dict):
    """Strukturiertes CRM-Ergebnis mit Listen-Kompatibilitaet (W2-B-Vertrag).

    ``status``/``error_code``/``error`` trennen Fehler von "leerem CRM".
    ``__len__``/``__iter__`` delegieren an ``contacts``, damit bestehende
    Konsumenten weiterhin eine Liste sehen, ohne einen Fehler als Erfolg zu lesen.
    """

    def __len__(self):
        return len(self.get("contacts") or [])

    def __iter__(self):
        return iter(self.get("contacts") or [])

    def __getitem__(self, key):
        if isinstance(key, (int, slice)):
            return (self.get("contacts") or [])[key]
        return super().__getitem__(key)


def _trace_ctx():
    try:
        from backend import trace_context as tc
        return tc
    except Exception as exc:  # pragma: no cover - nur bei fehlendem Backend
        logger.warning("[CRMMCP] trace_context nicht verfügbar: %s", exc)
        return None


def pb_request(method, url, *, json_payload=None, headers=None, timeout=10):
    """Zentraler PocketBase-Request mit Hop-Span und W3C-Injektion.

    Gibt ein Dict mit ``status_code``, ``response``, ``error``, ``error_code``,
    ``trace_id`` und ``span_id`` zurueck — auch bei Netzwerkfehlern.
    """
    tc = _trace_ctx()
    hdrs = dict(headers or {})
    kwargs = {}
    if json_payload is not None:
        traced = tc.inject_payload(json_payload) if tc is not None else dict(json_payload)
        # `inject_payload` setzt auch span_id/tracestate; das sind keine
        # Collection-Felder. Nur trace_id bleibt als Korrelationsfeld stehen.
        traced.pop("span_id", None)
        traced.pop("tracestate", None)
        tid = tc.current_trace_id() if tc is not None else ""
        if tid:
            traced.setdefault("trace_id", tid)
        kwargs["json"] = traced

    span_ctx = tc.child_span() if tc is not None else contextlib.nullcontext(("", "", None))
    with span_ctx as (tid, sid, _parent):
        if tc is not None:
            hdrs = tc.inject_headers(hdrs)
        try:
            resp = requests.request(method, url, headers=hdrs, timeout=timeout, **kwargs)
            return {
                "status_code": int(getattr(resp, "status_code", 0) or 0),
                "response": resp,
                "headers": dict(getattr(resp, "headers", {}) or {}),
                "error": "",
                "error_code": "",
                "trace_id": tid,
                "span_id": sid,
            }
        except requests.exceptions.Timeout as exc:
            logger.error("[CRMMCP] PocketBase-Timeout: %s", exc)
            return {"status_code": 0, "response": None, "headers": {},
                    "error": str(exc), "error_code": "CRM_TIMEOUT",
                    "trace_id": tid, "span_id": sid}
        except requests.exceptions.RequestException as exc:
            logger.error("[CRMMCP] PocketBase-Verbindungsfehler: %s", exc)
            return {"status_code": 0, "response": None, "headers": {},
                    "error": str(exc), "error_code": "CRM_CONNECTION_ERROR",
                    "trace_id": tid, "span_id": sid}
        except Exception as exc:
            logger.error("[CRMMCP] Unerwarteter PocketBase-Fehler: %s", exc)
            return {"status_code": 0, "response": None, "headers": {},
                    "error": str(exc), "error_code": "CRM_FETCH_FAILED",
                    "trace_id": tid, "span_id": sid}


def get_all_contacts():
    """Liest alle Kontakte — Fehler sind nie ``[]`` (W2-B-Eskalation)."""
    url = f"{POCKETBASE_URL}/api/collections/{COLLECTION_NAME}/records?perPage=500"
    res = pb_request("GET", url, timeout=10)
    if res["error_code"]:
        return ContactsResult(status="error", contacts=[], error_code=res["error_code"],
                              error=res["error"], trace_id=res["trace_id"])
    if res["status_code"] != 200:
        return ContactsResult(status="error", contacts=[], error_code="CRM_HTTP_ERROR",
                              error=f"HTTP {res['status_code']}", trace_id=res["trace_id"])
    try:
        body = res["response"].json()
    except Exception as exc:
        logger.error("[CRMMCP] Ungueltige PocketBase-Antwort: %s", exc)
        return ContactsResult(status="error", contacts=[], error_code="INVALID_CRM_JSON",
                              error=f"Ungueltiges JSON: {exc}", trace_id=res["trace_id"])
    if not isinstance(body, dict):
        return ContactsResult(status="error", contacts=[], error_code="INVALID_CRM_JSON",
                              error="PocketBase-Antwort ist kein Objekt", trace_id=res["trace_id"])
    items = body.get("items")
    if not isinstance(items, list):
        return ContactsResult(status="error", contacts=[], error_code="MISSING_CRM_ITEMS",
                              error="PocketBase-Antwort ohne 'items'-Liste", trace_id=res["trace_id"])
    return ContactsResult(status="ok", contacts=items, error_code=None, error=None,
                          trace_id=res["trace_id"])


def update_contact_email(contact_id, email_address):
    """Führt das Auto-Enrichment durch, falls die E-Mail-Adresse fehlt."""
    url = f"{POCKETBASE_URL}/api/collections/{COLLECTION_NAME}/records/{contact_id}"
    res = pb_request("PATCH", url, json_payload={"email": email_address}, timeout=10)
    return res["status_code"] == 200 and not res["error_code"]


def append_email_to_history(contact_id, email_obj):
    """Fügt eine E-Mail zum nachrichtenverlauf hinzu (If-Match + Dup-Schutz)."""
    url = f"{POCKETBASE_URL}/api/collections/{COLLECTION_NAME}/records/{contact_id}"
    clean_obj = dict(email_obj)
    for _attempt in range(3):
        res = pb_request("GET", url, timeout=15)
        if res["status_code"] != 200 or res["error_code"]:
            logger.error("[CRMMCP] Kontakt %s nicht lesbar: %s", contact_id, res["error"] or res["status_code"])
            return False
        contact = res["response"].json()
        etag = res["headers"].get("ETag") or contact.get("revision")
        history = contact.get("nachrichtenverlauf") or []

        existing_ids = {msg.get("messageId") for msg in history if isinstance(msg, dict) and "messageId" in msg}
        if clean_obj.get("messageId") in existing_ids:
            print(f"[-] E-Mail {clean_obj.get('messageId')} existiert bereits bei Kontakt {contact_id}. Übersprungen.")
            return True

        history.append(clean_obj)
        headers = {"If-Match": str(etag)} if etag else {}
        # trace_id als Collection-Feld: der PATCH traegt die Korrelations-ID.
        update_res = pb_request(
            "PATCH", url,
            json_payload={"nachrichtenverlauf": history, "trace_id": res["trace_id"]},
            headers=headers, timeout=15,
        )
        if update_res["status_code"] == 200:
            return True
        if update_res["status_code"] not in (400, 409, 412):
            logger.error("[CRMMCP] PATCH fehlgeschlagen: %s", update_res["error"] or update_res["status_code"])
            return False
    return False


def save_potential_contacts(potential_list):
    """Speichert nicht zuordenbare, relevante E-Mails in eine Berichtsdatei."""
    with open("potenzielle_neukontakte.json", "w", encoding="utf-8") as f:
        json.dump(potential_list, f, ensure_ascii=False, indent=2)
    print(f"[+] {len(potential_list)} potenzielle Neukontakte in 'potenzielle_neukontakte.json' gespeichert.")


def main(argv=None) -> int:
    """CLI: strukturiertes Ergebnis; Fehler fuehren zu Exit != 0."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] != "--get-contacts":
        print("Verwendung: archon_crm_mcp.py --get-contacts")
        return 2
    result = get_all_contacts()
    print(json.dumps(result, ensure_ascii=False))
    if str(result.get("status") or "").lower() == "error":
        logger.error("[CRMMCP] CLI fehlgeschlagen: %s", result.get("error_code"))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
