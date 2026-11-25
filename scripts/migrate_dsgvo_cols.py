"""DSGVO-Spalten in der PocketBase-Collection `kontakte` anlegen.

W2 (Audit 23.11.2026): die frühere Version machte ein direkter
`ALTER TABLE` auf die laufende PocketBase-DB. Das ergänzt nur die physische
SQLite-Tabelle, NICHT die Collection-Metadaten in `_collections`/auxiliary.db.
Die Felder waren damit per PocketBase-API und Admin-UI unsichtbar und wurden
beim nächsten Schema-Update von PocketBase wieder verworfen.

Neue Implementierung: ausschliesslich über die PocketBase Admin-API.
Ohne erreichbare Instanz / ohne Admin-Credentials bricht das Skript ab
(fail-closed) statt die produktive Datenbank zu beschädigen.

Benötigte ENV:
    POCKETBASE_URL             Default http://127.0.0.1:8090
    POCKETBASE_ADMIN_EMAIL
    POCKETBASE_ADMIN_PASSWORD
"""

import json
import os
import sys
import urllib.error
import urllib.request

PB_URL = os.getenv("POCKETBASE_URL", "http://127.0.0.1:8090").rstrip("/")
ADMIN_EMAIL = os.getenv("POCKETBASE_ADMIN_EMAIL", "").strip()
ADMIN_PASSWORD = os.getenv("POCKETBASE_ADMIN_PASSWORD", "").strip()
COLLECTION = "kontakte"

# Name -> PocketBase-Field-Definition (kein SQL mehr!)
NEW_FIELDS: dict[str, dict] = {
    "dsgvo_legal_basis": {"type": "text", "max": 64, "values": ["art6_1_f", "art6_1_a", "art6_1_c", "art7_1"]},
    "dsgvo_opt_email": {"type": "number"},
    "dsgvo_opt_phone": {"type": "number"},
    "dsgvo_opt_postal": {"type": "number"},
    "dsgvo_opt_source": {"type": "text", "max": 180},
    "dsgvo_opt_out": {"type": "number"},
    "dsgvo_opt_out_date": {"type": "text", "max": 32},
    "dsgvo_retention_category": {"type": "text", "max": 64},
}


def _request(method: str, path: str, payload=None, token: str = ""):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = token
    req = urllib.request.Request(PB_URL + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def migrate() -> bool:
    if not ADMIN_EMAIL or not ADMIN_PASSWORD:
        print("FEHLER: POCKETBASE_ADMIN_EMAIL / POCKETBASE_ADMIN_PASSWORD nicht gesetzt. "
              "Direkte ALTER TABLE auf die Live-DB ist nicht mehr erlaubt (Audit W2).", file=sys.stderr)
        return False

    try:
        auth = _request("POST", "/api/admins/auth-with-password",
                        {"identity": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        token = str(auth.get("token") or "")
        if not token:
            raise RuntimeError("Kein Admin-Token erhalten.")
        collection = _request("GET", f"/api/collections/{COLLECTION}", token=token)
        existing = {f.get("name") for f in (collection.get("fields") or collection.get("schema") or [])}
    except urllib.error.HTTPError as exc:
        print(f"FEHLER: PocketBase Admin-API nicht erreichbar/authorisiert: HTTP {exc.code}", file=sys.stderr)
        return False
    except Exception as exc:
        print(f"FEHLER: PocketBase Admin-API nicht erreichbar: {exc}", file=sys.stderr)
        return False

    changed = False
    for name, definition in NEW_FIELDS.items():
        if name in existing:
            print(f"  = {name}: existiert bereits")
            continue
        try:
            _request("POST", f"/api/collections/{COLLECTION}/fields",
                     {"name": name, **definition}, token=token)
            print(f"  + {name}: angelegt")
            changed = True
        except urllib.error.HTTPError as exc:
            if exc.code == 400:
                print(f"  = {name}: bereits vorhanden (400)")
            else:
                print(f"  ! {name}: HTTP {exc.code}", file=sys.stderr)
                return False
        except Exception as exc:
            print(f"  ! {name}: {exc}", file=sys.stderr)
            return False

    print(f"Fertig. {len(NEW_FIELDS)} DSGVO-Felder geprüft, {changed} neu angelegt.")
    return True


if __name__ == "__main__":
    sys.exit(0 if migrate() else 1)
