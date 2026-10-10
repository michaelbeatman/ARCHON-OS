import os
import mimetypes
import urllib.request
import urllib.error
import json
import datetime

PB_URL = os.getenv("POCKETBASE_URL", "http://Pocketbase:8090")
INBOX_DIR = os.getenv("INBOX_DIR", "/opt/data/video-collection/inbox")

def get_existing_filenames():
    try:
        url = f"{PB_URL}/api/collections/media_items/records?perPage=500"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            items = data.get('items', [])
            existing = set()
            for it in items:
                orig = it.get('original_filename')
                if orig:
                    existing.add(orig)
                f = it.get('file')
                if f:
                    existing.add(f)
            return existing
    except Exception as e:
        print(f"[WARN] Could not fetch existing records: {e}")
        return set()

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

    body.extend(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: {mime_type}\r\n\r\n'.encode('utf-8'))
    with open(filepath, 'rb') as f:
        body.extend(f.read())
    body.extend(f'\r\n--{boundary}--\r\n'.encode('utf-8'))

    url = f"{PB_URL}/api/collections/media_items/records"
    req = urllib.request.Request(
        url,
        data=body,
        headers={'Content-Type': f'multipart/form-data; boundary={boundary}'},
        method='POST'
    )

    try:
        with urllib.request.urlopen(req) as resp:
            res_data = json.loads(resp.read().decode('utf-8'))
            print(f"[OK] Uploaded {filename} -> ID {res_data.get('id')}")
            return True
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode('utf-8', errors='ignore')
        print(f"[FAIL] Upload failed for {filename}: HTTP {e.code} - {err_msg}")
        return False
    except Exception as e:
        print(f"[FAIL] Upload error for {filename}: {e}")
        return False

def main():
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
