"""
backend/email_service.py
Nativer E-Mail-Dienst (IMAP & SMTP) für Archon OS:
- Ruft E-Mails via SSL von imap.gmail.com ab (180s Taktung oder manuell per Button)
- Speichert Nachrichten strukturiert in /opt/data/inbox/emails/
- Versorgt das Archon OS Postfach mit Volltext und Status
"""

import os
import sys
import json
import time
import email
import imaplib
import smtplib
import logging
import datetime
from pathlib import Path
from email.header import decode_header
from typing import Dict, Any, List, Optional

logger = logging.getLogger("email_service")

BASE_DIR = Path(__file__).resolve().parent.parent

def _decode_mime_str(header_val: Any) -> str:
    if not header_val:
        return ""
    decoded_fragments = []
    try:
        parts = decode_header(header_val)
        for part, encoding in parts:
            if isinstance(part, bytes):
                encoding = encoding or "utf-8"
                try:
                    decoded_fragments.append(part.decode(encoding, errors="replace"))
                except Exception:
                    decoded_fragments.append(part.decode("utf-8", errors="replace"))
            else:
                decoded_fragments.append(str(part))
        return "".join(decoded_fragments).strip()
    except Exception:
        return str(header_val).strip()


def get_email_storage_dirs() -> List[Path]:
    candidates = [
        Path("/opt/data/inbox/emails"),
        BASE_DIR / "data" / "inbox" / "emails",
        Path("./data/inbox/emails")
    ]
    dirs = []
    for d in candidates:
        try:
            d.mkdir(parents=True, exist_ok=True)
            dirs.append(d)
        except Exception:
            pass
    return dirs if dirs else [Path("./data/inbox/emails")]


def sync_imap_inbox(limit: int = 50) -> Dict[str, Any]:
    """
    Holt die neuesten E-Mails via IMAP ab und speichert sie lokal ab.
    """
    try:
        from backend.post_task_pipeline import get_smtp_config
        cfg = get_smtp_config()
    except Exception as e:
        logger.error(f"Konnte SMTP/IMAP Konfiguration nicht laden: {e}")
        return {"status": "error", "message": str(e), "synced": 0}

    user = cfg.get("username")
    pwd = cfg.get("password")
    imap_host = "imap.gmail.com"
    imap_port = 993

    if not user or not pwd:
        return {"status": "error", "message": "Keine Zugangsdaten hinterlegt.", "synced": 0}

    storage_dirs = get_email_storage_dirs()
    synced_count = 0
    errors = []

    mail = None
    try:
        mail = imaplib.IMAP4_SSL(imap_host, imap_port, timeout=20)
        mail.login(user, pwd)
        status, select_data = mail.select("INBOX", readonly=True)
        if status != "OK":
            return {"status": "error", "message": f"INBOX Auswahl fehlgeschlagen: {status}", "synced": 0}

        status, search_data = mail.search(None, "ALL")
        if status != "OK" or not search_data or not search_data[0]:
            return {"status": "success", "message": "Postfach ist leer.", "synced": 0}

        msg_ids = search_data[0].split()
        target_ids = msg_ids[-limit:] if len(msg_ids) > limit else msg_ids
        target_ids.reverse()  # Neueste zuerst

        for msg_id_bytes in target_ids:
            msg_id_str = msg_id_bytes.decode("ascii", errors="ignore")
            # Prüfen ob bereits lokal vorhanden
            found = False
            for sdir in storage_dirs:
                if (sdir / f"msg_imap_{msg_id_str}.json").exists():
                    found = True
                    break
            if found:
                continue

            try:
                res, data = mail.fetch(msg_id_bytes, "(RFC822)")
                if res != "OK" or not data:
                    continue

                raw_email = None
                for part in data:
                    if isinstance(part, tuple) and len(part) >= 2:
                        raw_email = part[1]
                        break

                if not raw_email:
                    continue

                msg = email.message_from_bytes(raw_email)
                subject = _decode_mime_str(msg.get("Subject", "Kein Betreff"))
                sender = _decode_mime_str(msg.get("From", "Unbekannt"))
                to_addr = _decode_mime_str(msg.get("To", user))
                date_str = msg.get("Date", "")

                # Datums-Parsing defensiv
                parsed_ts = datetime.datetime.now().timestamp()
                formatted_date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
                try:
                    parsed_dt = email.utils.parsedate_to_datetime(date_str)
                    if parsed_dt:
                        parsed_ts = parsed_dt.timestamp()
                        formatted_date = parsed_dt.strftime("%Y-%m-%d %H:%M")
                except Exception:
                    pass

                # Body extrahieren (Text & HTML)
                body_plain = ""
                body_html = ""

                if msg.is_multipart():
                    for part in msg.walk():
                        ctype = part.get_content_type()
                        cdisp = str(part.get("Content-Disposition", ""))
                        if "attachment" in cdisp:
                            continue
                        try:
                            payload_bytes = part.get_payload(decode=True)
                            if not payload_bytes:
                                continue
                            charset = part.get_content_charset() or "utf-8"
                            text = payload_bytes.decode(charset, errors="replace")
                            if ctype == "text/plain" and not body_plain:
                                body_plain = text
                            elif ctype == "text/html" and not body_html:
                                body_html = text
                        except Exception:
                            pass
                else:
                    try:
                        payload_bytes = msg.get_payload(decode=True)
                        charset = msg.get_content_charset() or "utf-8"
                        text = payload_bytes.decode(charset, errors="replace") if payload_bytes else ""
                        if msg.get_content_type() == "text/html":
                            body_html = text
                        else:
                            body_plain = text
                    except Exception:
                        body_plain = str(msg.get_payload() or "")

                final_text = body_plain or (body_html if body_html else "")

                # Sicherheitsprüfung auf Prompt Injections
                sec_verdict = "safe"
                sec_flags = []
                try:
                    from local_security_guard import scan_prompt_injection
                    scan_res = scan_prompt_injection(final_text, subject=subject, sender=sender)
                    sec_verdict = scan_res.get("verdict", "safe")
                    sec_flags = scan_res.get("pattern_matches", [])
                except Exception:
                    pass

                doc = {
                    "id": f"mail_imap_{msg_id_str}",
                    "imap_id": msg_id_str,
                    "sender": sender,
                    "from": sender,
                    "to": to_addr,
                    "subject": subject,
                    "title": subject,
                    "date": formatted_date,
                    "timestamp": formatted_date,
                    "mtime": parsed_ts,
                    "body": final_text,
                    "content": final_text,
                    "html": body_html,
                    "preview": (final_text[:160] + "...") if len(final_text) > 160 else final_text,
                    "source": "email",
                    "security_status": sec_verdict,
                    "security_flags": sec_flags
                }

                # In alle Speicher-Pfade schreiben
                for sdir in storage_dirs:
                    target_file = sdir / f"msg_imap_{msg_id_str}.json"
                    with open(target_file, "w", encoding="utf-8") as f:
                        json.dump(doc, f, ensure_ascii=False, indent=2)

                synced_count += 1
            except Exception as e_inner:
                errors.append(f"Fehler bei Msg {msg_id_str}: {e_inner}")

        return {
            "status": "success",
            "synced": synced_count,
            "errors": errors,
            "last_sync": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

    except Exception as e:
        logger.error(f"IMAP Fehler: {e}")
        return {"status": "error", "message": str(e), "synced": synced_count}
    finally:
        if mail:
            try:
                mail.close()
            except Exception:
                pass
            try:
                mail.logout()
            except Exception:
                pass
