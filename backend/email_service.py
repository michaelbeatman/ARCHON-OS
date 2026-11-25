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
import email.utils
import imaplib
import smtplib
import logging
import datetime
from pathlib import Path
from email.header import decode_header
from typing import Dict, Any, List, Optional, cast

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
        except Exception as exc:
            logger.debug(f"Inbox-Verzeichnis {d} nicht erstellbar, übersprungen: {exc}")
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
    imap_host = str(cfg.get("imap_host") or os.environ.get("IMAP_HOST") or "imap.gmail.com").strip()
    try:
        imap_port = int(cfg.get("imap_port") or os.environ.get("IMAP_PORT") or 993)
    except (TypeError, ValueError):
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
                except Exception as exc:
                    logger.debug(f"IMAP-Date-Parsing fehlgeschlagen, Rohwert übernommen: {exc}")

                # Body extrahieren (Text & HTML)
                body_plain = ""
                body_html = ""

                if msg.is_multipart():
                    # Eigener Name: `part` oben ist ein IMAP-Rohantwort-Tupel
                    # (bytes | tuple | None), hier ist es ein Message-Objekt.
                    for msg_part in msg.walk():
                        ctype = msg_part.get_content_type()
                        cdisp = str(msg_part.get("Content-Disposition", ""))
                        if "attachment" in cdisp:
                            continue
                        try:
                            part_payload = msg_part.get_payload(decode=True)
                            if not part_payload:
                                continue
                            charset = msg_part.get_content_charset() or "utf-8"
                            # typeshed: get_payload(decode=True) -> Message | bytes | None.
                            # decode=True auf einem nicht-multipart Part liefert bytes;
                            # cast ist zur Laufzeit ein No-op.
                            text = cast(bytes, part_payload).decode(charset, errors="replace")
                            if ctype == "text/plain" and not body_plain:
                                body_plain = text
                            elif ctype == "text/html" and not body_html:
                                body_html = text
                        except Exception as exc:
                            logger.debug(f"Mail-Body-Part nicht dekodierbar, übersprungen: {exc}")
                else:
                    try:
                        payload_bytes = msg.get_payload(decode=True)
                        charset = msg.get_content_charset() or "utf-8"
                        text = cast(bytes, payload_bytes).decode(charset, errors="replace") if payload_bytes else ""
                        if msg.get_content_type() == "text/html":
                            body_html = text
                        else:
                            body_plain = text
                    except Exception:
                        body_plain = str(msg.get_payload() or "")

                final_text = body_plain or (body_html if body_html else "")

                # Sicherheitsprüfung auf Prompt Injections (local_security_guard + dual_llm_sanitizer)
                sec_verdict = "safe"
                sec_flags = []
                sanitized_text = final_text
                try:
                    from local_security_guard import scan_prompt_injection
                    scan_res = scan_prompt_injection(final_text, subject=subject, sender=sender)
                    sec_verdict = scan_res.get("verdict", "safe")
                    sec_flags = list(scan_res.get("pattern_matches", []))
                except Exception as exc:
                    logger.debug(f"Security-Scan (IMAP-Mail) fehlgeschlagen, Fallback 'safe': {exc}")
                try:
                    from backend.dual_llm_sanitizer import sanitize_external_input
                    dl_res = sanitize_external_input(final_text, source_id=sender, source_type="email")
                    if not dl_res.get("is_safe", True):
                        if dl_res.get("threat_level") == "critical":
                            sec_verdict = "blocked"
                        elif sec_verdict == "safe":
                            sec_verdict = "suspicious"
                        sec_flags = sorted(set(sec_flags + list(dl_res.get("detected_patterns", []))))
                        sanitized_text = dl_res.get("clean_summary") or "[INHALT WEGEN SICHERHEITSRISIKEN GEFILTERT]"
                except Exception as exc:
                    logger.debug(f"Dual-LLM-Sanitizer fehlgeschlagen, Originaltext übernommen: {exc}")

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
                    "body": sanitized_text,
                    "content": sanitized_text,
                    "raw_quarantined": sec_verdict == "blocked",
                    "html": body_html,
                    "preview": (sanitized_text[:160] + "...") if len(sanitized_text) > 160 else sanitized_text,
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
            except Exception as exc:
                logger.debug(f"IMAP close fehlgeschlagen: {exc}")
            try:
                mail.logout()
            except Exception as exc:
                logger.debug(f"IMAP logout fehlgeschlagen: {exc}")


def send_email(
    to_email: str,
    subject: str,
    body_text: str,
    from_email: Optional[str] = None,
    html_body: Optional[str] = None,
) -> Dict[str, Any]:
    """Sendet eine E-Mail über den konfigurierten SMTP-Server."""
    from email.message import EmailMessage

    recipient = str(to_email or "").strip()
    if not recipient or "@" not in recipient:
        return {"status": "error", "message": "Ungültige Empfänger-Adresse."}

    cfg: Dict[str, Any] = {}
    try:
        from backend.post_task_pipeline import get_smtp_config
        cfg = get_smtp_config() or {}
    except Exception:
        cfg = {}

    smtp_host = str(cfg.get("smtp_host") or cfg.get("host") or os.environ.get("SMTP_HOST") or "").strip()
    try:
        smtp_port = int(cfg.get("smtp_port") or cfg.get("port") or os.environ.get("SMTP_PORT") or 587)
    except (TypeError, ValueError):
        smtp_port = 587
    user = str(cfg.get("username") or os.environ.get("SMTP_USER") or "").strip()
    pwd = str(cfg.get("password") or os.environ.get("SMTP_PASSWORD") or "").strip()
    sender = str(from_email or cfg.get("from_email") or user or "noreply@archon.local").strip()

    if not smtp_host or not user or not pwd:
        return {
            "status": "skipped",
            "reason": "no_smtp_credentials",
            "message": "SMTP-Zugangsdaten nicht konfiguriert.",
        }

    msg = EmailMessage()
    msg["Subject"] = str(subject or "").replace("\r", " ").replace("\n", " ")
    msg["From"] = sender.replace("\r", " ").replace("\n", " ")
    msg["To"] = recipient.replace("\r", " ").replace("\n", " ")
    msg.set_content(body_text or "")
    if html_body:
        msg.add_alternative(html_body, subtype="html")

    try:
        if smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=15) as server:
                server.login(user, pwd)
                server.send_message(msg)
        else:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
                server.ehlo()
                try:
                    server.starttls()
                    server.ehlo()
                except smtplib.SMTPException as exc:
                    logger.debug(f"STARTTLS nicht verfügbar, Login ohne TLS fortgesetzt: {exc}")
                server.login(user, pwd)
                server.send_message(msg)
        return {"status": "sent", "recipient": recipient, "host": smtp_host}
    except Exception as exc:
        logger.error("SMTP-Versand fehlgeschlagen: %s", exc)
        return {"status": "error", "message": str(exc), "recipient": recipient}
