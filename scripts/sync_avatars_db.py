import os
import glob
import hashlib
import time
import sqlite3
import base64
import yaml

def get_avatar_index(p_id):
    h = 0
    for ch in p_id:
        h = ((h << 5) - h) + ord(ch)
        h &= 0xFFFFFFFF
        if h >= 0x80000000:
            h -= 0x100000000
    idx = (abs(h) % 108) + 1
    return idx

def main():
    db_path = '/opt/data/webui/avatars.db'
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute('''
    CREATE TABLE IF NOT EXISTS avatars (
        profile    TEXT PRIMARY KEY,
        mime       TEXT NOT NULL,
        bytes      BLOB NOT NULL,
        etag       TEXT NOT NULL,
        updated_at REAL NOT NULL
    )
    ''')

    profiles = [os.path.basename(p) for p in glob.glob('/opt/data/profiles/*') if os.path.isdir(p)]
    for extra in ['micha', 'hermes_default', 'default']:
        if extra not in profiles:
            profiles.append(extra)

    now = time.time()
    custom_count = 0
    fallback_count = 0

    for pid in profiles:
        p_yaml = f'/opt/data/profiles/{pid}/profile.yaml'
        blob = None
        mime = None

        if os.path.exists(p_yaml):
            try:
                with open(p_yaml, 'r', encoding='utf-8') as f:
                    y = yaml.safe_load(f)
                av = y.get('avatar', '') if y else ''
                if av and av.startswith('data:image'):
                    header, b64 = av.split(',', 1)
                    mime = header.split(';')[0].replace('data:', '')
                    blob = base64.b64decode(b64)
                    custom_count += 1
                elif av and av.startswith('/static/avatars/'):
                    fname = os.path.basename(av)
                    img_path = f'/opt/data/webui/static_avatars/avatars/{fname}'
                    if not os.path.exists(img_path):
                        img_path = f'/opt/data/webui/static_avatars/{fname}'
                    if os.path.exists(img_path):
                        with open(img_path, 'rb') as f:
                            blob = f.read()
                        mime = 'image/jpeg'
                        custom_count += 1
            except Exception as e:
                print(f'Error reading profile.yaml for {pid}: {e}')

        if not blob:
            idx = get_avatar_index(pid)
            candidates = [
                f'/opt/data/webui/static_avatars/avatars/avatar_{idx:03d}.jpg',
                f'/opt/data/webui/static_avatars/avatar_{idx:03d}.jpg'
            ]
            img_path = next((p for p in candidates if os.path.exists(p)), None)
            if not img_path:
                continue

            with open(img_path, 'rb') as f:
                blob = f.read()
            mime = 'image/jpeg'
            fallback_count += 1

        etag = '"' + hashlib.sha256(blob).hexdigest()[:32] + '"'
        cur.execute(
            'INSERT OR REPLACE INTO avatars (profile, mime, bytes, etag, updated_at) VALUES (?, ?, ?, ?, ?)',
            (pid, mime, blob, etag, now)
        )

    conn.commit()
    conn.close()
    print(f'Synchronized {custom_count} custom avatars and {fallback_count} catalog fallbacks into avatars.db!')

if __name__ == '__main__':
    main()
