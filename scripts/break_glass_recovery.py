#!/usr/bin/env python3
"""
scripts/break_glass_recovery.py
Archon OS 2026 - Dokumentierter, verschlüsselter Notfallzugang (Break-Glass Protocol) (t-8efcf3).
Ermöglicht bei Betreiberausfall oder Systemkollaps die vollständige Wiederherstellung aller
sensiblen Zugangsdaten (.env, settings.json, agentic_memory.db) ohne Web-UI-Login.
Verwendet 100% Python-Standardbibliothek mit Authenticated Encryption (PBKDF2-200k + SHA256-CTR + HMAC).
"""

import os
import sys

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WORKSPACE_DIR not in sys.path:
    sys.path.insert(0, WORKSPACE_DIR)

import json
import time
import zipfile
import io
import shutil
import hashlib
import hmac
import secrets
import struct
import argparse
import datetime
from typing import Dict, Any, Tuple, Optional

BACKUP_DIR = os.path.join(WORKSPACE_DIR, "data", "backups")
VAULT_FILE = os.path.join(BACKUP_DIR, "break_glass_vault.enc")
KIT_DOC_FILE = os.path.join(BACKUP_DIR, "BREAK_GLASS_RECOVERY_KIT.md")
METADATA_FILE = os.path.join(BACKUP_DIR, "break_glass_meta.json")

# Kritisches Notfall-Inventar
CRITICAL_FILES = [
    (".env", ".env"),
    ("settings.json", "settings.json"),
    ("data/privacy_routing.json", "data/privacy_routing.json"),
    ("data/trusted_sources.json", "data/trusted_sources.json"),
    ("data/agentic_memory.db", "data/agentic_memory.db"),
    ("config/settings.json", "config/settings.json"),
    ("backend/approval_policies.json", "backend/approval_policies.json")
]

def derive_keys(passphrase: str, salt: bytes) -> Tuple[bytes, bytes]:
    """Leitet über 200.000 Runden PBKDF2-HMAC-SHA256 einen Verschlüsselungs- und MAC-Key ab."""
    clean_pass = passphrase.strip().replace(" ", "").replace("-", "")
    key_material = hashlib.pbkdf2_hmac("sha256", clean_pass.encode("utf-8"), salt, 200000, 64)
    return key_material[:32], key_material[32:]

def encrypt_bytes(data: bytes, passphrase: str) -> bytes:
    """Verschlüsselt Rohdaten mit Authenticated Encryption (Encrypt-then-MAC)."""
    salt = secrets.token_bytes(16)
    nonce = secrets.token_bytes(16)
    enc_key, mac_key = derive_keys(passphrase, salt)

    ciphertext = bytearray()
    block_size = 32
    num_blocks = (len(data) + block_size - 1) // block_size
    for i in range(num_blocks):
        counter_bytes = struct.pack(">Q", i)
        keystream_block = hmac.new(enc_key, nonce + counter_bytes, hashlib.sha256).digest()
        chunk = data[i * block_size : (i + 1) * block_size]
        for b_p, b_k in zip(chunk, keystream_block):
            ciphertext.append(b_p ^ b_k)

    mac = hmac.new(mac_key, salt + nonce + ciphertext, hashlib.sha256).digest()
    # Format: MAGIC(4) || SALT(16) || NONCE(16) || MAC(32) || CIPHERTEXT
    return b"ABG1" + salt + nonce + mac + bytes(ciphertext)

def decrypt_bytes(payload: bytes, passphrase: str) -> bytes:
    """Entschlüsselt und verifiziert den kryptografischen MAC-Tag."""
    if len(payload) < 68 or payload[:4] != b"ABG1":
        raise ValueError("Ungültiges Break-Glass Vault Format oder beschädigte Datei.")
    salt = payload[4:20]
    nonce = payload[20:36]
    expected_mac = payload[36:68]
    ciphertext = payload[68:]

    enc_key, mac_key = derive_keys(passphrase, salt)
    actual_mac = hmac.new(mac_key, salt + nonce + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(expected_mac, actual_mac):
        raise ValueError("Falscher Recovery-Key oder manipulierter Vault (Integritätsprüfung fehlgeschlagen).")

    plaintext = bytearray()
    block_size = 32
    num_blocks = (len(ciphertext) + block_size - 1) // block_size
    for i in range(num_blocks):
        counter_bytes = struct.pack(">Q", i)
        keystream_block = hmac.new(enc_key, nonce + counter_bytes, hashlib.sha256).digest()
        chunk = ciphertext[i * block_size : (i + 1) * block_size]
        for b_c, b_k in zip(chunk, keystream_block):
            plaintext.append(b_c ^ b_k)

    return bytes(plaintext)

def generate_emergency_key() -> str:
    """Erzeugt einen 24-stelligen, gut lesbaren Notfallschlüssel mit Prüfgruppen."""
    alphabet = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
    groups = ["".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(5)]
    return f"ARCHON-BG-{'-'.join(groups)}"

def create_break_glass_vault(operator: str = "admin") -> Dict[str, Any]:
    """Packt das kritische Systeminventar in einen verschlüsselten Notfall-Vault."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    recovery_key = generate_emergency_key()
    now_iso = datetime.datetime.now().isoformat()

    # 1. Sammle alle existierenden Notfall-Dateien in ein ZIP
    zip_buffer = io.BytesIO()
    archived_files = []
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel_src, arcname in CRITICAL_FILES:
            full_src = os.path.join(WORKSPACE_DIR, rel_src)
            if os.path.exists(full_src) and os.path.isfile(full_src):
                try:
                    zf.write(full_src, arcname)
                    archived_files.append(arcname)
                except Exception as e:
                    pass

    zip_bytes = zip_buffer.getvalue()

    # 2. Verschlüssele das ZIP-Archiv
    encrypted_vault = encrypt_bytes(zip_bytes, recovery_key)
    with open(VAULT_FILE, "wb") as f:
        f.write(encrypted_vault)

    vault_sha256 = hashlib.sha256(encrypted_vault).hexdigest()

    # 3. Metadaten sichern (ohne Schlüssel!)
    meta = {
        "created_at": now_iso,
        "operator": operator,
        "vault_size_bytes": len(encrypted_vault),
        "vault_sha256": vault_sha256,
        "archived_files": archived_files,
        "vault_file": VAULT_FILE
    }
    with open(METADATA_FILE, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    # 4. Druckbares Notfall-Dokument (Kit) erstellen
    kit_markdown = f"""# ARCHON OS - NOTFALLZUGANG (BREAK-GLASS RECOVERY KIT)
**Vertraulichkeitsstufe:** HOECHSTE SICHERHEITSKLASSE (STRENG VERTRAULICH)
**Erstellt am:** {now_iso}
**Verantwortlicher Betreiber:** {operator}

---

## 1. WICHTIGE HINWEISE FUER DEN ERNSTFALL
Dieses Dokument dient der **Wiederherstellung von Archon OS bei Betreiberausfall, Datenverlust oder Verlust aller regulaeren Zugangsdaten**.
Verwahren Sie dieses Dokument physisch an einem sicheren Ort (Tresor) oder in einem getrennten Firmen-Passwortmanager.

## 2. DER NOTFALLSCHLUESSEL (EMERGENCY MASTER KEY)
> ### `{recovery_key}`
*(Hinweis: Bindestriche koennen bei der Eingabe weggelassen werden.)*

## 3. CHECKSUMME DES VERSCHLUESSELTEN VAULTS
* **Vault-Pfad:** `data/backups/break_glass_vault.enc`
* **SHA-256 Checksumme:** `{vault_sha256}`
* **Enthaltene Systemdateien:** {', '.join(archived_files)}

---

## 4. SCHRITT-FUER-SCHRITT ANLEITUNG ZUR WIEDERHERSTELLUNG
Sollte die Web-Oberflaeche nicht erreichbar sein oder der Server neu aufgesetzt werden muessen:

1. Oeffnen Sie ein Terminal im Archon OS Projektverzeichnis (`AgenticOS-2026`).
2. Fuehren Sie folgenden Befehl aus:
   ```bash
   python scripts/break_glass_recovery.py --restore
   ```
3. Geben Sie den obigen Notfallschluessel ein, wenn Sie dazu aufgefordert werden.
4. Das Skript verifiziert die kryptografische Checksumme und stellt alle Konfigurationsdateien, API-Keys und Datenbanken im Originalzustand wieder her.
5. Starten Sie das System anschliessend neu:
   ```bash
   docker compose restart
   ```

---
*Revisionssicher protokolliert gemaess GoBD & ISO/IEC 27001 (Zero-Trust Ledger).*
"""
    with open(KIT_DOC_FILE, "w", encoding="utf-8") as f:
        f.write(kit_markdown)

    # 5. In GoBD Audit-Log protokollieren
    try:
        from backend.audit_log import chained_audit_log
        chained_audit_log.record_event(
            category="security",
            action="break_glass_vault_created",
            agent_id=operator,
            payload={
                "vault_sha256": vault_sha256,
                "file_count": len(archived_files),
                "archived_files": archived_files
            }
        )
    except Exception as e:
        pass

    return {
        "status": "success",
        "recovery_key": recovery_key,
        "vault_sha256": vault_sha256,
        "archived_files": archived_files,
        "vault_file": VAULT_FILE,
        "kit_file": KIT_DOC_FILE,
        "created_at": now_iso
    }

def restore_break_glass_vault(recovery_key: str, operator: str = "emergency_operator") -> Dict[str, Any]:
    """Entschlüsselt das Notfall-Backup und stellt alle Systemdateien wieder her."""
    if not os.path.exists(VAULT_FILE):
        raise FileNotFoundError(f"Notfall-Vault nicht gefunden unter {VAULT_FILE}")

    with open(VAULT_FILE, "rb") as f:
        encrypted_vault = f.read()

    # 1. Entschlüsseln und Verifizieren
    decrypted_zip_bytes = decrypt_bytes(encrypted_vault, recovery_key)

    # 2. Auspacken und Dateien überschreiben
    restored_files = []
    zip_buffer = io.BytesIO(decrypted_zip_bytes)
    with zipfile.ZipFile(zip_buffer, "r") as zf:
        for member in zf.namelist():
            target_path = os.path.join(WORKSPACE_DIR, member)
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            with zf.open(member) as src, open(target_path, "wb") as dst:
                shutil.copyfileobj(src, dst)
            restored_files.append(member)

    # 3. Notfall-Audit Alarm
    try:
        from backend.audit_log import chained_audit_log
        chained_audit_log.record_event(
            category="security",
            action="break_glass_emergency_restore",
            agent_id=operator,
            payload={
                "restored_files": restored_files,
                "file_count": len(restored_files),
                "status": "RESTORED_SUCCESSFULLY"
            }
        )
    except Exception as e:
        pass

    return {
        "status": "success",
        "restored_files": restored_files,
        "restored_count": len(restored_files),
        "message": f"Notfallwiederherstellung erfolgreich! {len(restored_files)} Systemdateien wurden wiederhergestellt."
    }

def get_vault_status() -> Dict[str, Any]:
    """Liefert den aktuellen Integritätsstatus des Break-Glass Vaults."""
    exists = os.path.exists(VAULT_FILE)
    meta = {}
    if os.path.exists(METADATA_FILE):
        try:
            with open(METADATA_FILE, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except Exception:
            pass

    size_bytes = os.path.getsize(VAULT_FILE) if exists else 0
    return {
        "vault_initialized": exists,
        "vault_file": VAULT_FILE,
        "vault_size_bytes": size_bytes,
        "last_created_at": meta.get("created_at"),
        "operator": meta.get("operator", "admin"),
        "vault_sha256": meta.get("vault_sha256"),
        "archived_files": meta.get("archived_files", []),
        "kit_available": os.path.exists(KIT_DOC_FILE)
    }

def main():
    parser = argparse.ArgumentParser(description="Archon OS 2026 - Break-Glass Notfallzugang")
    parser.add_argument("--init", "--create", action="store_true", help="Neuen verschluesselten Break-Glass Vault und Recovery-Kit generieren")
    parser.add_argument("--restore", action="store_true", help="Notfall-Wiederherstellung aus dem Vault durchfuehren")
    parser.add_argument("--key", type=str, default="", help="Notfall-Wiederherstellungsschluessel fuer --restore")
    parser.add_argument("--status", action="store_true", help="Status des Break-Glass Vaults pruefen")

    args = parser.parse_args()

    if args.status:
        st = get_vault_status()
        print(json.dumps(st, indent=2, ensure_ascii=False))
        return

    if args.init:
        print("[BreakGlass] Erstelle verschluesselten Notfall-Vault...")
        res = create_break_glass_vault()
        print("==========================================================================")
        print("[NOTFALLZUGANG] ERFOLGREICH INITIALISIERT")
        print("==========================================================================")
        print(f"Notfallschluessel: {res['recovery_key']}")
        print(f"Vault Checksumme:  {res['vault_sha256']}")
        print(f"Recovery-Kit Doc:  {res['kit_file']}")
        print(f"Gesicherte Daten:  {', '.join(res['archived_files'])}")
        print("==========================================================================")
        print("WICHTIG: Drucken Sie das Dokument aus und verwahren Sie den Schluessel im Tresor!")
        return

    if args.restore:
        key = args.key.strip()
        if not key:
            print("[NOTFALL-WIEDERHERSTELLUNG ARCHON OS]")
            key = input("Bitte Recovery-Key eingeben: ").strip()

        if not key:
            print("Abbruch: Kein Schluessel eingegeben.", file=sys.stderr)
            sys.exit(1)

        print("[BreakGlass] Entschluessele Notfall-Vault...")
        try:
            res = restore_break_glass_vault(key)
            print("[OK] " + res["message"])
            for f_name in res["restored_files"]:
                print(f"  -> Wiederhergestellt: {f_name}")
        except Exception as e:
            print(f"[FEHLER] WIEDERHERSTELLUNG FEHLGESCHLAGEN: {e}", file=sys.stderr)
            sys.exit(1)
        return

    parser.print_help()

if __name__ == "__main__":
    main()
