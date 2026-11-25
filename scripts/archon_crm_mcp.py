import requests
import json
import sys
import re
import logging

logger = logging.getLogger("archon.crm_mcp")

POCKETBASE_URL = "http://127.0.0.1:8090"
COLLECTION_NAME = "kontakte"


class ContactsResult(dict):
    """D12/H-12-5: strukturiertes CRM-Ergebnis mit Listen-Kompatibilitaet.

    ``status``/``error_code``/``error`` machen Fehler von "leeres CRM"
    unterscheidbar. ``__len__``/``__iter__`` delegieren an ``contacts``, damit
    bestehende Konsumenten (``scripts/run_email_matching.py``) weiterhin eine
    Liste von Kontakten sehen, ohne dass ein Fehler als leerer Erfolg gilt.
    """

    def __len__(self):
        return len(self.get("contacts") or [])

    def __iter__(self):
        return iter(self.get("contacts") or [])

    def __getitem__(self, key):
        if isinstance(key, (int, slice)):
            return (self.get("contacts") or [])[key]
        return super().__getitem__(key)


class EmailImportResult(dict):
    """Strukturiertes Outlook-Ergebnis (status/partial/skipped_count)."""

    def __len__(self):
        return len(self.get("emails") or [])

    def __iter__(self):
        return iter(self.get("emails") or [])

    def __getitem__(self, key):
        if isinstance(key, (int, slice)):
            return (self.get("emails") or [])[key]
        return super().__getitem__(key)


def get_all_contacts():
    """Liest alle Kontakte aus PocketBase — Fehler sind nie ``[]``.

    Rueckgabe: ``ContactsResult`` mit ``status`` (``ok``/``error``),
    ``contacts``, ``error_code`` und ``error``. HTTP-Fehler, Timeouts,
    ungueltiges JSON und fehlende ``items`` sind unterschiedlich codiert.
    """
    url = f"{POCKETBASE_URL}/api/collections/{COLLECTION_NAME}/records?perPage=500"
    try:
        response = requests.get(url, timeout=10)
        raise_for_status = getattr(response, "raise_for_status", None)
        if callable(raise_for_status):
            raise_for_status()
        elif int(getattr(response, "status_code", 200)) >= 400:
            return ContactsResult(
                status="error", contacts=[], error_code="CRM_HTTP_ERROR",
                error=f"HTTP {response.status_code}",
            )
        try:
            body = response.json()
        except Exception as exc:
            logger.error("[CRMMCP] Ungueltige PocketBase-Antwort: %s", exc)
            return ContactsResult(
                status="error", contacts=[], error_code="INVALID_CRM_JSON",
                error=f"Ungueltiges JSON: {exc}",
            )
        if not isinstance(body, dict):
            return ContactsResult(
                status="error", contacts=[], error_code="INVALID_CRM_JSON",
                error="PocketBase-Antwort ist kein Objekt",
            )
        items = body.get("items")
        if not isinstance(items, list):
            return ContactsResult(
                status="error", contacts=[], error_code="MISSING_CRM_ITEMS",
                error="PocketBase-Antwort ohne 'items'-Liste",
            )
        return ContactsResult(
            status="ok", contacts=items, error_code=None, error=None,
        )
    except requests.exceptions.Timeout as exc:
        logger.error("[CRMMCP] PocketBase-Timeout: %s", exc)
        return ContactsResult(
            status="error", contacts=[], error_code="CRM_TIMEOUT", error=str(exc),
        )
    except requests.exceptions.HTTPError as exc:
        logger.error("[CRMMCP] PocketBase-HTTP-Fehler: %s", exc)
        return ContactsResult(
            status="error", contacts=[], error_code="CRM_HTTP_ERROR", error=str(exc),
        )
    except requests.exceptions.RequestException as exc:
        logger.error("[CRMMCP] PocketBase-Verbindungsfehler: %s", exc)
        return ContactsResult(
            status="error", contacts=[], error_code="CRM_CONNECTION_ERROR", error=str(exc),
        )
    except Exception as exc:
        logger.error("[CRMMCP] Unerwarteter CRM-Fehler: %s", exc)
        return ContactsResult(
            status="error", contacts=[], error_code="CRM_FETCH_FAILED", error=str(exc),
        )

def update_contact_email(contact_id, email_address):
    """Führt Auto-Enrichment aus (ergänzt fehlende E-Mail-Adresse)."""
    url = f"{POCKETBASE_URL}/api/collections/{COLLECTION_NAME}/records/{contact_id}"
    payload = {"email": email_address}
    response = requests.patch(url, json=payload, timeout=10)
    return response.status_code == 200

def append_email_to_history(contact_id, email_obj, max_retries=3):
    """Fügt E-Mail zum nachrichtenverlauf hinzu (Duplikats-Schutz + If-Match).

    W2: Read-Modify-Write ohne ETag verlor bei parallelem Mail-Sync die
    Änderungen des anderen Schreibers (Lost Update). Bei einem 409/412/400
    wird der aktuelle Stand erneut gelesen und der Merge wiederholt.
    """
    url = f"{POCKETBASE_URL}/api/collections/{COLLECTION_NAME}/records/{contact_id}"
    clean_obj = dict(email_obj)
    if "text" in clean_obj:
        clean_obj["text"] = re.sub(r'(\r?\n){2,}', '\n', clean_obj.get("text") or "").strip()

    for _attempt in range(max_retries):
        res = requests.get(url, timeout=15)
        if res.status_code != 200:
            return False
        contact = res.json()
        # PocketBase liefert ETag und/oder revision — beides ist ein
        # optimistischer Concurrency-Token für den PATCH.
        etag = res.headers.get("ETag") or contact.get("revision")
        history = contact.get("nachrichtenverlauf") or []

        existing_ids = {msg.get("messageId") for msg in history if isinstance(msg, dict) and "messageId" in msg}
        if clean_obj.get("messageId") in existing_ids:
            return True  # Bereits vorhanden

        history.append(clean_obj)
        headers = {"If-Match": str(etag)} if etag else {}
        update_res = requests.patch(
            url, json={"nachrichtenverlauf": history}, headers=headers, timeout=15
        )
        if update_res.status_code == 200:
            return True
        if update_res.status_code not in (400, 409, 412):
            return False
        # Konflikt -> neu lesen und erneut versuchen.
    return False

def fetch_local_outlook_emails(limit=200):
    """Liest Mails direkt aus Outlook — Import-/Zugriffsfehler sind kein Erfolg.

    Rueckgabe: ``EmailImportResult`` mit ``status``, ``emails``, ``partial``,
    ``skipped_count``, ``error_code`` und ``error``. Listen-Konsumenten sehen
    weiterhin die ``emails``.
    """
    try:
        import win32com.client
    except ImportError as exc:
        logger.error("[CRMMCP] pywin32 nicht installiert: %s", exc)
        return EmailImportResult(
            status="error", emails=[], partial=True, skipped_count=0,
            error_code="OUTLOOK_IMPORT_FAILED", error=str(exc),
        )

    skipped_count = 0
    try:
        outlook = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
        
        # 6 = Posteingang, 5 = Gesendete Elemente
        inbox = outlook.GetDefaultFolder(6).Items
        sent = outlook.GetDefaultFolder(5).Items
        
        emails = []
        
        # Posteingang lesen
        inbox.Sort("[ReceivedTime]", True)
        for idx, item in enumerate(inbox):
            if idx >= limit:
                break
            try:
                raw_text = getattr(item, "Body", "")[:2000]
                cleaned_text = re.sub(r'(\r?\n){2,}', '\n', raw_text).strip()
                subject_text = getattr(item, "Subject", "")
                sender_email = getattr(item, "SenderEmailAddress", "")

                sec_status = "safe"
                quarantined = False
                try:
                    import sys, os
                    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                    if root_dir not in sys.path:
                        sys.path.insert(0, root_dir)
                    from local_security_guard import scan_prompt_injection, sanitize_injection_text
                    scan_res = scan_prompt_injection(cleaned_text, subject=subject_text, sender=sender_email)
                    sec_status = scan_res.get("verdict", "safe")
                    if sec_status != "safe":
                        cleaned_text = sanitize_injection_text(cleaned_text)
                    if sec_status == "blocked":
                        quarantined = True
                        logger.warning(
                            "[CRMMCP] Mail %s: Injection-Scan verdict='blocked' — Eintrag quaraentiniert.",
                            getattr(item, "EntryID", str(idx)),
                        )
                except Exception as exc:
                    # F-048: Ein Fehler im Injection-Scan darf niemals still
                    # passieren (Fail-Open in einer Security-Pipeline).
                    logger.error(
                        "[CRMMCP] Injection-Scan fehlgeschlagen (Mail %s): %s — Inhalt wird quaraentiniert.",
                        getattr(item, "EntryID", str(idx)), exc,
                    )
                    sec_status = "unknown"
                    quarantined = True
                    cleaned_text = (
                        "[QUARANTÄNIERT — Injection-Scan nicht verfuegbar; "
                        "Inhalt nicht zur Verarbeitung freigegeben]"
                    )

                emails.append({
                    "type": "inbound",
                    "sender_name": getattr(item, "SenderName", ""),
                    "sender_email": sender_email,
                    "recipient": getattr(item, "To", ""),
                    "subject": subject_text,
                    "text": cleaned_text,
                    "security_status": sec_status,
                    "quarantined": quarantined,
                    "timestamp": str(getattr(item, "ReceivedTime", "")),
                    "messageId": f"outlook_in_{getattr(item, 'EntryID', str(idx))}"
                })
            except Exception as exc:
                # D12/MED: eine verworfene Mail darf nicht unsichtbar bleiben.
                skipped_count += 1
                logger.warning(
                    "[CRMMCP] Mail konnte nicht gelesen werden (Index %s): %s",
                    idx, exc,
                )
                continue

        # Gesendete Mails lesen
        sent.Sort("[SentOn]", True)
        for idx, item in enumerate(sent):
            if idx >= limit:
                break
            try:
                raw_text = getattr(item, "Body", "")[:2000]
                cleaned_text = re.sub(r'(\r?\n){2,}', '\n', raw_text).strip()
                emails.append({
                    "type": "outbound",
                    "sender_name": "Me",
                    "sender_email": "",
                    "recipient_name": getattr(item, "To", ""),
                    "subject": getattr(item, "Subject", ""),
                    "text": cleaned_text,
                    "timestamp": str(getattr(item, "SentOn", "")),
                    "messageId": f"outlook_sent_{getattr(item, 'EntryID', str(idx))}"
                })
            except Exception as exc:
                # D12/MED: eine verworfene Mail darf nicht unsichtbar bleiben.
                skipped_count += 1
                logger.warning(
                    "[CRMMCP] Mail konnte nicht gelesen werden (Index %s): %s",
                    idx, exc,
                )
                continue

        return EmailImportResult(
            status="ok" if skipped_count == 0 else "partial",
            emails=emails,
            partial=bool(skipped_count),
            skipped_count=skipped_count,
            error_code=None,
            error=None,
        )
    except Exception as exc:
        logger.error("[CRMMCP] Outlook-Zugriff fehlgeschlagen: %s", exc)
        return EmailImportResult(
            status="error", emails=[], partial=True,
            skipped_count=skipped_count,
            error_code="OUTLOOK_IMPORT_FAILED", error=str(exc),
        )

def save_potential_contacts(potential_list):
    with open("potenzielle_neukontakte.json", "w", encoding="utf-8") as f:
        json.dump(potential_list, f, ensure_ascii=False, indent=2)

def main(argv=None) -> int:
    """CLI: strukturierte Ergebnisse, Fehler führen zu Exit != 0.

    D12/H-12-5: der Konsument darf an ``status`` erkennen, ob PocketBase/
    Outlook erreichbar war — statt eine leere Liste als Erfolg zu lesen.
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("Verwendung: archon_crm_mcp.py --get-contacts|--fetch-mails")
        return 2
    cmd = argv[0]
    if cmd == "--get-contacts":
        result = get_all_contacts()
    elif cmd == "--fetch-mails":
        result = fetch_local_outlook_emails()
    else:
        print(f"Unbekannter Befehl: {cmd}")
        return 2
    print(json.dumps(result, ensure_ascii=False))
    if str(result.get("status") or "").lower() == "error":
        logger.error("[CRMMCP] CLI-Befehl %s fehlgeschlagen: %s", cmd, result.get("error_code"))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())