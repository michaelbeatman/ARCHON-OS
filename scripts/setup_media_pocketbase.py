"""
Initializes collections and schemas for the separate Media-PocketBase instance on port 8092.
Collections:
  - video_batches
  - media_items
  - linkedin_content
"""

import json
import urllib.request
import urllib.error
import sys

import os

BASE_URL = os.getenv("POCKETBASE_URL", "http://127.0.0.1:8090")
ADMIN_EMAIL = "admin@agenticos.local"
ADMIN_PASS = "admin1234567890"

def api_request(endpoint, data=None, method="GET", token=None):
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = token
    
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    
    try:
        with urllib.request.urlopen(req) as resp:
            content = resp.read().decode("utf-8")
            return json.loads(content) if content else {}
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8")
        try:
            err_json = json.loads(err_body)
        except Exception:
            err_json = {"raw": err_body}
        raise RuntimeError(f"HTTP {e.code} on {endpoint}: {err_json}")

def login_superuser():
    auth_data = api_request("/api/collections/_superusers/auth-with-password", {
        "identity": ADMIN_EMAIL,
        "password": ADMIN_PASS
    }, method="POST")
    token = auth_data.get("token")
    print(f"[OK] Authenticated as superuser: {ADMIN_EMAIL}")
    return token

def setup_collections(token):
    existing = api_request("/api/collections?perPage=100", token=token).get("items", [])
    existing_names = {c["name"]: c for c in existing}

    # 1. video_batches collection
    batches_fields = [
        {"name": "title", "type": "text", "required": False},
        {
            "name": "batch_type",
            "type": "select",
            "required": True,
            "values": ["shorts_9_16", "longform_16_9", "sonstiges"]
        },
        {"name": "target_duration_seconds", "type": "number", "required": False},
        {"name": "current_duration_seconds", "type": "number", "required": False},
        {"name": "clip_count", "type": "number", "required": False},
        {
            "name": "status",
            "type": "select",
            "required": True,
            "values": ["collecting", "ready_to_render", "rendering", "completed", "failed"]
        },
        {"name": "output_video_file", "type": "file", "maxSelect": 1, "maxSize": 524288000},
        {"name": "rendered_at", "type": "date", "required": False}
    ]

    if "video_batches" not in existing_names:
        res = api_request("/api/collections", {
            "name": "video_batches",
            "type": "base",
            "fields": batches_fields,
            "listRule": "",
            "viewRule": "",
            "createRule": "",
            "updateRule": "",
            "deleteRule": ""
        }, method="POST", token=token)
        print("[OK] Created collection: video_batches")
    else:
        print("[INFO] Collection video_batches already exists.")

    # 2. media_items collection
    media_fields = [
        {"name": "file", "type": "file", "maxSelect": 1, "maxSize": 524288000},
        {
            "name": "media_type",
            "type": "select",
            "required": True,
            "values": ["video", "image", "audio", "sonstiges"]
        },
        {
            "name": "format",
            "type": "select",
            "required": False,
            "values": ["hochkant_9_16", "breitbild_16_9", "quadratisch_1_1", "sonstiges"]
        },
        {"name": "aspect_ratio", "type": "text", "required": False},
        {"name": "width", "type": "number", "required": False},
        {"name": "height", "type": "number", "required": False},
        {"name": "duration_seconds", "type": "number", "required": False},
        {"name": "file_size_bytes", "type": "number", "required": False},
        {"name": "original_filename", "type": "text", "required": False},
        {
            "name": "source",
            "type": "select",
            "required": False,
            "values": ["telegram", "manual_upload", "whatsapp", "sonstiges"]
        },
        {
            "name": "status",
            "type": "select",
            "required": True,
            "values": ["unprocessed", "assigned_to_batch", "rendered", "archived"]
        },
        {"name": "batch_id", "type": "text", "required": False},
        {"name": "metadata_json", "type": "json", "required": False},
        {"name": "received_at", "type": "date", "required": False}
    ]

    if "media_items" not in existing_names:
        res = api_request("/api/collections", {
            "name": "media_items",
            "type": "base",
            "fields": media_fields,
            "listRule": "",
            "viewRule": "",
            "createRule": "",
            "updateRule": "",
            "deleteRule": ""
        }, method="POST", token=token)
        print("[OK] Created collection: media_items")
    else:
        print("[INFO] Collection media_items already exists.")

    # 3. linkedin_content collection
    linkedin_fields = [
        {"name": "url", "type": "url", "required": False},
        {"name": "title", "type": "text", "required": False},
        {"name": "raw_content", "type": "text", "required": False},
        {"name": "user_note", "type": "text", "required": False},
        {"name": "summary", "type": "text", "required": False},
        {"name": "draft_post", "type": "text", "required": False},
        {
            "name": "status",
            "type": "select",
            "required": True,
            "values": ["inbox", "drafted", "scheduled", "published", "archived"]
        },
        {"name": "received_at", "type": "date", "required": False}
    ]

    if "linkedin_content" not in existing_names:
        res = api_request("/api/collections", {
            "name": "linkedin_content",
            "type": "base",
            "fields": linkedin_fields,
            "listRule": "",
            "viewRule": "",
            "createRule": "",
            "updateRule": "",
            "deleteRule": ""
        }, method="POST", token=token)
        print("[OK] Created collection: linkedin_content")
    else:
        print("[INFO] Collection linkedin_content already exists.")

    # 4. studio_settings collection
    settings_fields = [
        {"name": "key", "type": "text", "required": True},
        {"name": "data_json", "type": "json", "required": False},
        {"name": "description", "type": "text", "required": False}
    ]

    if "studio_settings" not in existing_names:
        res = api_request("/api/collections", {
            "name": "studio_settings",
            "type": "base",
            "fields": settings_fields,
            "listRule": "",
            "viewRule": "",
            "createRule": "",
            "updateRule": "",
            "deleteRule": ""
        }, method="POST", token=token)
        print("[OK] Created collection: studio_settings")
    else:
        print("[INFO] Collection studio_settings already exists.")

if __name__ == "__main__":
    print(f"Connecting to Media-PocketBase at {BASE_URL}...")
    token = login_superuser()
    setup_collections(token)
    print("\n[OK] Media-PocketBase schema setup complete!")

