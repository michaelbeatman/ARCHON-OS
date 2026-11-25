"""Serverseitiger Media-Inbox-Sync nach PocketBase.

D16/H-16-4: frueher bauten `get_existing_filenames()` und `upload_file()` ihre
urllib-Requests direkt ohne Trace-Header. Jetzt laeuft jeder PocketBase-Call
ueber `pb_request()` — mit einem echten W3C-Child-Span, injizierten
traceparent/tracestate-Headern und `trace_id` als Collection-Feld des
media_items-Records. Der Browser-PocketBase-SDK hat denselben Kontext bereits
ueber `beforeSend`; die Kausalkette ist damit auch serverseitig geschlossen.
"""

import os
import sys
import contextlib
import mimetypes
import urllib.request
import urllib.error
import json
import datetime
import logging

logger = logging.getLogger("archon.pb_sync")

_WORKSPACE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, _WORKSPACE_ROOT)

PB_URL = os.getenv("POCKETBASE_URL", "http://Pocketbase:8090")
INBOX_DIR = os.getenv("INBOX_DIR", "/opt/data/video-collection/inbox")


def _trace_ctx():
    """W3C-Brücke laden; fehlt sie, bleibt der Sync sendefähig (additiv)."""
    try:
        from backend import trace_context as tc
        return tc
    except Exception as exc:  # pragma: no cover - nur bei fehlendem Backend
        logger.warning("[PB-Sync] trace_context nicht verfügbar: %s", exc)
        return None


def init_trace_context() -> str:
    """Eingehenden Kontext (TRACEPARENT) übernehmen oder einen Root starten."""
    tc = _trace_ctx()
    if tc is None:
        return ""
    incoming = (os.getenv("TRACEPARENT") or "").strip()
    if incoming:
        tc.start_trace(incoming=incoming, tracestate=os.getenv("TRACESTATE") or None)
    else:
        tc.ensure_trace()
    return tc.current_trace_id()


def pb_request(url, *, data=None, headers=None, method="GET", json_payload=None,
               timeout=30):
    """Zentraler PocketBase-Request mit Hop-Span und W3C-Header-Injektion.

    Liefert immer ein Dict mit ``status_code``, ``data`` (geparstes JSON oder
    ``None``), ``raw``, ``error``, ``trace_id`` und ``span_id``. HTTP- und
    Netzwerkfehler werden nicht als leerer Erfolg zurueckgegeben.
    """
    tc = _trace_ctx()
    hdrs = dict(headers or {})
    body = data
    if json_payload is not None:
        traced = tc.inject_payload(json_payload) if tc is not None else dict(json_payload)
        body = json.dumps(traced, ensure_ascii=False).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")

    # injizieren MUSS im Block passieren: sonst trägt der traceparent nicht
    # die neue Hop-Span-ID (Self-Parenting der Kausalkante).
    span_ctx = tc.child_span() if tc is not None else contextlib.nullcontext(("", "", None))
    with span_ctx as (tid, sid, _parent):
        if tc is not None:
            hdrs = tc.inject_headers(hdrs)
        req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                try:
                    parsed = json.loads(raw) if raw.strip() else None
                except Exception:
                    parsed = None
                return {
                    "status_code": int(getattr(resp, "status", 0) or 0),
                    "data": parsed,
                    "raw": raw,
                    "error": "",
                    "trace_id": tid,
                    "span_id": sid,
                }
        except urllib.error.HTTPError as exc:
            err_msg = exc.read().decode("utf-8", errors="ignore")
            logger.warning("[PB-Sync] HTTP %s von %s: %s", exc.code, url, err_msg[:200])
            return {
                "status_code": int(exc.code), "data": None, "raw": err_msg,
                "error": f"HTTP {exc.code}: {err_msg[:200]}",
                "trace_id": tid, "span_id": sid,
            }
        except Exception as exc:
            logger.warning("[PB-Sync] Request fehlgeschlagen (%s): %s", url, exc)
            return {
                "status_code": 0, "data": None, "raw": "",
                "error": str(exc), "trace_id": tid, "span_id": sid,
            }


def get_existing_filenames():
    url = f"{PB_URL}/api/collections/media_items/records?perPage=500"
    res = pb_request(url, timeout=15)
    if res["status_code"] != 200 or not isinstance(res.get("data"), dict):
        print(f"[WARN] Could not fetch existing records: {res['error'] or 'invalid JSON'}")
        return set()
    items = res["data"].get("items")
    if not isinstance(items, list):
        print("[WARN] Could not fetch existing records: missing 'items' list")
        return set()
    existing = set()
    for it in items:
        orig = it.get("original_filename")
        if orig:
            existing.add(orig)
        f = it.get("file")
        if f:
            existing.add(f)
    return existing


def upload_file(filepath):
    filename = os.path.basename(filepath)
    ext = os.path.splitext(filename)[1].lower()

    if ext in ['.mp4', '.mov', '.avi', '.webm', '.mkv']:
        media_type = 'video'
    elif ext in ['.jpg', '.jpeg', '.png', '.webp', '.gif']:
        media_type = 'image'
    elif ext in ['.mp3', '.wav', '.ogg', '.m4a']:
        media_type = 'audio'
    else:
        media_type = 'sonstiges'

    size = os.path.getsize(filepath)
    mtime = datetime.datetime.fromtimestamp(os.path.getmtime(filepath)).isoformat() + "Z"

    mime_type, _ = mimetypes.guess_type(filepath)
    if not mime_type:
        mime_type = 'application/octet-stream'

    boundary = '----WebKitFormBoundary' + os.urandom(16).hex()
    body = bytearray()

    def add_field(name, value):
        body.extend(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode('utf-8'))

    add_field('media_type', media_type)
    add_field('status', 'unprocessed')
    add_field('source', 'telegram')
    add_field('original_filename', filename)
    add_field('file_size_bytes', str(size))
    add_field('received_at', mtime)
    # D16/H-16-4: trace_id als echtes Collection-Feld persistieren, damit der
    # PocketBase-Record mit dem auslösenden Agenten-Trace korrelierbar ist.
    trace_id = init_trace_context()
    if trace_id:
        add_field('trace_id', trace_id)

    body.extend(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: {mime_type}\r\n\r\n'.encode('utf-8'))
    with open(filepath, 'rb') as f:
        body.extend(f.read())
    body.extend(f'\r\n--{boundary}--\r\n'.encode('utf-8'))

    url = f"{PB_URL}/api/collections/media_items/records"
    res = pb_request(
        url, data=body, method='POST', timeout=30,
        headers={'Content-Type': f'multipart/form-data; boundary={boundary}'},
    )
    if 200 <= res["status_code"] < 300 and isinstance(res.get("data"), dict):
        print(f"[OK] Uploaded {filename} -> ID {res['data'].get('id')} "
              f"(trace_id={res['trace_id']})")
        return True
    print(f"[FAIL] Upload failed for {filename}: {res['error'] or 'invalid response'}")
    return False


def main():
    init_trace_context()
    print(f"Scanning inbox: {INBOX_DIR} targeting {PB_URL}...")
    if not os.path.exists(INBOX_DIR):
        print(f"[ERROR] Directory does not exist: {INBOX_DIR}")
        return

    existing = get_existing_filenames()
    print(f"Found {len(existing)} existing files in PocketBase media_items.")

    files = sorted(os.listdir(INBOX_DIR))
    print(f"Found {len(files)} total files in inbox.")

    success_count = 0
    skipped_count = 0
    fail_count = 0

    for f in files:
        if f.startswith('.'):
            continue
        filepath = os.path.join(INBOX_DIR, f)
        if not os.path.isfile(filepath):
            continue

        if f in existing:
            skipped_count += 1
            continue

        if upload_file(filepath):
            success_count += 1
        else:
            fail_count += 1

    print("\n--- SYNC RESULT ---")
    print(f"Uploaded: {success_count}")
    print(f"Skipped: {skipped_count}")
    print(f"Failed: {fail_count}")


if __name__ == '__main__':
    main()
