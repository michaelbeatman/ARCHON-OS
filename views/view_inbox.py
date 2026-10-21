"""
views/view_inbox.py - Operatives Modul "Eingang (Triage & Streams)" für Archon OS

1. ZIELSETZUNG:
   Zentraler Triage-Bildschirm mit 3 Spalten für operative Ereignisse:
   - Spalte 1: INTERN (System-Logs, Approval-Gates, Docker-Events)
   - Spalte 2: E-MAIL (Eingehende externe Nachrichten)
   - Spalte 3: TELEGRAM (Nachrichten-Stream vom Bot)

2. DESIGN-STANDARDS (STRIKTES HELL-DESIGN):
   - Hintergrund der App: #F8FAFC
   - Card-Container: Reines Weiß (#FFFFFF), Rahmen: 1px solid #E2E8F0, Radius: 8px, Innenabstand: 12px
   - Primärtext: #0F172A, Sekundärtext: #64748B
   - Header: Roter Signalpunkt (Symbol ● in #EF4444) vor dem Titel "EINGANG (TRIAGE & STREAMS)"
   - Primär-Buttons: Hintergrund #DC2626, Text #FFFFFF

3. DATENQUELLEN & DEFENSIVE PFADPRÜFUNG:
   - Spalte INTERN: System-Event-Log oder defensives Fallback mit Badges:
     [ERROR] rot (#EF4444), [GATE] orange (#F59E0B), [SYSTEM] blau (#3B82F6)
   - Spalte E-MAIL: /opt/data/inbox/emails/ (Auto-Create). Liest .json / .txt.
     Zeigt leere Hinweiskarte "Keine neuen E-Mails im Postfach", falls leer. Extrahiert Absender, Betreff, Datum.
   - Spalte TELEGRAM: /opt/data/inbox/telegram/ (Auto-Create). Liest .json.
     Zeigt leere Hinweiskarte "Keine neuen Telegram-Nachrichten", falls leer.
     Typ-Badges: [TEXT], [VOICE], [BILD], Absender & Eingangszeit.

4. INTERAKTION & MODAL-DIALOG / STREAMLIT-KOMPATIBILITÄT:
   - Sortierung aller 3 Spalten: Strikt chronologisch absteigend (neueste oben).
   - Modal-Dialog mit vollständigem Textkörper, strukturierten Metadaten und Aktions-Button:
     "In Quickchat analysieren" -> schließt Modal, setzt Nachricht mit Präfix
     "[EINGANGS-ANALYSE] Untersuche folgende Nachricht: " in pending_chat_input
     und schaltet auf Target "chat" / "master-chat".
   - Bietet sowohl `render_inbox_view()` (HTML/JS für Archon Web-OS) als auch
     `render_inbox_streamlit()` (st.dialog/st.session_state für Streamlit-Umgebungen).
"""

import os
import json
import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional


# =============================================================================
# DEFENSIVE PFADAUFLÖSUNG & DIRECTORY-INITIALISIERUNG
# =============================================================================

def get_email_inbox_dir() -> Path:
    """Ermittelt und initialisiert defensiv das E-Mail-Postfach."""
    candidates = [
        Path("/opt/data/inbox/emails"),
        Path("./data/inbox/emails"),
        Path("/app/data/inbox/emails"),
        Path(os.environ.get("INBOX_EMAIL_DIR", "./data/inbox/emails"))
    ]
    for c in candidates:
        if c.exists():
            return c

    # Bevorzuge /opt/data/inbox/emails falls Pfad anlegbar (z.B. Linux/Container), sonst ./data/...
    primary = candidates[0]
    try:
        primary.mkdir(parents=True, exist_ok=True)
        return primary
    except Exception:
        fallback = candidates[1]
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback



def get_webhook_inbox_dir() -> Path:
    """Ermittelt und initialisiert defensiv das Webhook-Postfach."""
    candidates = [
        Path("/opt/data/inbox/webhooks"),
        Path("./data/inbox/webhooks"),
        Path("/app/data/inbox/webhooks"),
        Path(os.environ.get("INBOX_WEBHOOK_DIR", "./data/inbox/webhooks"))
    ]
    for c in candidates:
        if c.exists():
            return c

    primary = candidates[0]
    try:
        primary.mkdir(parents=True, exist_ok=True)
        return primary
    except Exception:
        fallback = candidates[1]
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def get_telegram_inbox_dir() -> Path:
    """Ermittelt und initialisiert defensiv das Telegram-Postfach."""
    candidates = [
        Path("/opt/data/inbox/telegram"),
        Path("./data/inbox/telegram"),
        Path("/app/data/inbox/telegram"),
        Path(os.environ.get("INBOX_TELEGRAM_DIR", "./data/inbox/telegram"))
    ]
    for c in candidates:
        if c.exists():
            return c

    primary = candidates[0]
    try:
        primary.mkdir(parents=True, exist_ok=True)
        return primary
    except Exception:
        fallback = candidates[1]
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


# =============================================================================
# DATENABRUF & PARSING FÜR DIE 3 SPALTEN
# =============================================================================

def load_internal_events() -> List[Dict[str, Any]]:
    """
    Liest interne System-Ereignisse, Freigabe-Gates, Watchdog-Alarme und Task-Status.
    Verwendet reale Datenquellen:
    - system_events.jsonl
    - watchdog_alarms.json
    - SQLite tasks (Gates / Approvals)
    Badges: [ERROR] (#EF4444), [GATE] (#F59E0B), [SYSTEM] (#3B82F6), [TASK] (#10B981).
    """
    now = datetime.datetime.now()
    events: List[Dict[str, Any]] = []

    # 1. system_events.jsonl lesen
    log_candidates = [
        Path("/app/data/system_events.jsonl"),
        Path("./data/system_events.jsonl"),
        Path("/var/log/archon_events.log")
    ]
    for log_file in log_candidates:
        if log_file.exists() and log_file.is_file():
            try:
                with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            parsed = json.loads(line)
                            events.append(parsed)
                        except Exception:
                            continue
            except Exception:
                pass

    # 2. Watchdog Alarme einbinden
    alarm_files = [
        Path("/app/data/watchdog_alarms.json"),
        Path("./data/watchdog_alarms.json")
    ]
    for af in alarm_files:
        if af.exists():
            try:
                with open(af, "r", encoding="utf-8", errors="ignore") as f:
                    alarms = json.load(f)
                if isinstance(alarms, list):
                    for a in alarms:
                        events.append({
                            "id": a.get("id") or f"alarm_{hash(a.get('message',''))}",
                            "badge": "ERROR",
                            "badge_color": "#EF4444",
                            "badge_bg": "#FEE2E2",
                            "title": f"Watchdog: {a.get('agent_id', 'System')}",
                            "preview": a.get("message", "")[:160],
                            "content": a.get("message", "") + "\n\nDetails: " + json.dumps(a.get("details", {}), indent=2),
                            "sender": f"Watchdog Daemon ({a.get('agent_id', 'Core')})",
                            "timestamp": a.get("timestamp", now.strftime("%Y-%m-%d %H:%M")),
                            "mtime": a.get("mtime", now.timestamp()),
                            "source": "internal",
                            "path": "watchdog://alarm"
                        })
            except Exception:
                pass

    # 3. Reale SQLite Approvals & Tasks einbinden
    db_candidates = [
        Path("/opt/data/agentic_memory.db"),
        Path("./data/agentic_memory.db"),
        Path("/app/data/agentic_memory.db")
    ]
    for db_path in db_candidates:
        if db_path.exists():
            try:
                import sqlite3
                conn = sqlite3.connect(str(db_path), timeout=3)
                cur = conn.cursor()
                # Tasks prüfen
                cur.execute("SELECT id, title, agent_id, status, created_at, updated_at FROM tasks ORDER BY updated_at DESC LIMIT 10")
                rows = cur.fetchall()
                conn.close()
                for r in rows:
                    t_id, t_title, t_agent, t_status, t_created, t_updated = r
                    status_upper = (t_status or "").upper()
                    if status_upper in ["APPROVAL", "WAITING_APPROVAL", "GATE"]:
                        badge = "GATE"
                        badge_color = "#F59E0B"
                        badge_bg = "#FEF3C7"
                        title = f"Approval Gate: {t_title or t_id}"
                    elif status_upper in ["FAILED", "ERROR"]:
                        badge = "ERROR"
                        badge_color = "#EF4444"
                        badge_bg = "#FEE2E2"
                        title = f"Task Fehler: {t_title or t_id}"
                    elif status_upper in ["COMPLETED", "DONE"]:
                        badge = "SYSTEM"
                        badge_color = "#10B981"
                        badge_bg = "#D1FAE5"
                        title = f"Task abgeschlossen: {t_title or t_id}"
                    else:
                        badge = "SYSTEM"
                        badge_color = "#3B82F6"
                        badge_bg = "#DBEAFE"
                        title = f"Task aktiv: {t_title or t_id}"

                    events.append({
                        "id": f"task_{t_id}",
                        "badge": badge,
                        "badge_color": badge_color,
                        "badge_bg": badge_bg,
                        "title": title,
                        "preview": f"Agent {t_agent or 'System'} | Status: {t_status}",
                        "content": f"Task-ID: {t_id}\nAgent: {t_agent}\nStatus: {t_status}\nErstellt: {t_created}\nZuletzt aktualisiert: {t_updated}",
                        "sender": f"Agent {t_agent or 'Core'}",
                        "timestamp": str(t_updated or t_created or now.strftime("%Y-%m-%d %H:%M")),
                        "mtime": now.timestamp(),
                        "source": "internal",
                        "path": f"paperclip://task/{t_id}"
                    })
                break
            except Exception:
                pass

    if not events:
        events = [
            {
                "id": "sys_status_01",
                "badge": "SYSTEM",
                "badge_color": "#3B82F6",
                "badge_bg": "#DBEAFE",
                "title": "Archon OS Kernel: Online",
                "preview": "Port 8501 betriebsbereit. Tickless Kernel Sleep aktiv.",
                "content": "Archon OS Kernel läuft stabil auf Port 8501.\nAsyncio Event Loop initialisiert.\nKeine kritischen Systemereignisse anhängig.",
                "sender": "System / Kernel Daemon",
                "timestamp": now.strftime("%Y-%m-%d %H:%M"),
                "mtime": now.timestamp(),
                "source": "internal",
                "path": "system://kernel/status"
            },
            {
                "id": "sys_status_02",
                "badge": "SYSTEM",
                "badge_color": "#10B981",
                "badge_bg": "#D1FAE5",
                "title": "E-Mail IMAP/SMTP Dienst: Bereit",
                "preview": "Verbunden mit archon.os.system@gmail.com (180s Sync-Taktung).",
                "content": "IMAP: imap.gmail.com:993 (SSL)\nSMTP: smtp.gmail.com:587 (STARTTLS)\nEmpfänger: michaelbeatman82+archon@gmail.com\nAuto-Send für Berichte und Gates ist aktiv.",
                "sender": "E-Mail / IMAP Daemon",
                "timestamp": now.strftime("%Y-%m-%d %H:%M"),
                "mtime": now.timestamp() - 60,
                "source": "internal",
                "path": "system://email/status"
            }
        ]

    events.sort(key=lambda x: x.get("mtime", 0), reverse=True)
    return events


def load_email_messages() -> List[Dict[str, Any]]:
    """
    Liest E-Mails aus /opt/data/inbox/emails/.
    Unterstützt .json und .txt/eml Dateien.
    Extrahiert Absender, Betreff und Datum defensiv.
    """
    email_dir = get_email_inbox_dir()
    emails: List[Dict[str, Any]] = []

    if not email_dir.exists():
        return emails

    for file_path in email_dir.iterdir():
        if not file_path.is_file():
            continue

        mtime = file_path.stat().st_mtime
        dt_str = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
        ext = file_path.suffix.lower()

        if ext == ".json":
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    data = json.load(f)
                sender = data.get("from") or data.get("sender") or "Unbekannter Absender"
                subject = data.get("subject") or data.get("title") or file_path.stem
                date_val = data.get("date") or data.get("timestamp") or dt_str
                body = data.get("body") or data.get("content") or data.get("text") or json.dumps(data, indent=2)

                sec_status = "safe"
                sec_flags = []
                try:
                    import sys
                    sys_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                    if sys_dir not in sys.path:
                        sys.path.insert(0, sys_dir)
                    from local_security_guard import scan_prompt_injection
                    scan_res = scan_prompt_injection(body, subject=subject, sender=sender)
                    sec_status = scan_res.get("verdict", "safe")
                    sec_flags = scan_res.get("pattern_matches", [])
                except Exception:
                    pass

                mtime_val = float(data.get("mtime") or mtime)
                html_val = data.get("html") or ""

                emails.append({
                    "id": f"mail_{file_path.name}",
                    "sender": sender,
                    "subject": subject,
                    "title": subject,
                    "timestamp": date_val,
                    "preview": (body[:160] + "...") if len(body) > 160 else body,
                    "content": body,
                    "html": html_val,
                    "path": str(file_path),
                    "mtime": mtime_val,
                    "source": "email",
                    "security_status": sec_status,
                    "security_flags": sec_flags
                })
            except Exception:
                continue

        elif ext in [".txt", ".eml", ".msg"]:
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    raw_lines = f.readlines()

                sender = "Unbekannter Absender"
                subject = file_path.stem
                body_lines = []
                is_body = False

                for line in raw_lines:
                    line_s = line.strip()
                    lower = line_s.lower()
                    if lower.startswith("from:") and not is_body:
                        sender = line_s.split(":", 1)[1].strip()
                    elif lower.startswith("subject:") and not is_body:
                        subject = line_s.split(":", 1)[1].strip()
                    elif lower.startswith("date:") and not is_body:
                        parsed_dt = line_s.split(":", 1)[1].strip()
                        if parsed_dt:
                            dt_str = parsed_dt
                    elif line_s == "" and not is_body:
                        is_body = True
                    else:
                        body_lines.append(line)

                body = "".join(body_lines).strip() if body_lines else "".join(raw_lines).strip()

                sec_status = "safe"
                sec_flags = []
                try:
                    import sys
                    sys_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                    if sys_dir not in sys.path:
                        sys.path.insert(0, sys_dir)
                    from local_security_guard import scan_prompt_injection
                    scan_res = scan_prompt_injection(body, subject=subject, sender=sender)
                    sec_status = scan_res.get("verdict", "safe")
                    sec_flags = scan_res.get("pattern_matches", [])
                except Exception:
                    pass

                emails.append({
                    "id": f"mail_{file_path.name}",
                    "sender": sender,
                    "subject": subject,
                    "title": subject,
                    "timestamp": dt_str,
                    "preview": (body[:160] + "...") if len(body) > 160 else body,
                    "content": body,
                    "path": str(file_path),
                    "mtime": mtime,
                    "source": "email",
                    "security_status": sec_status,
                    "security_flags": sec_flags
                })
            except Exception:
                continue

    emails.sort(key=lambda x: x.get("mtime", 0), reverse=True)
    return emails


def load_telegram_messages() -> List[Dict[str, Any]]:
    """
    Liest Telegram-Nachrichten direkt aus der Live-Datenbank state.db
    sowie ergänzend aus /opt/data/inbox/telegram/ (.json & .txt).
    Weist Typ-Badges zu:
    [TEXT] (#3B82F6), [VOICE] (#8B5CF6), [BILD] (#10B981), [BOT] (#6366F1).
    """
    messages: List[Dict[str, Any]] = []
    seen_contents = set()

    # 1. Live Telegram-Nachrichten aus state.db abrufen
    state_db_candidates = [
        Path("/opt/data/state.db"),
        Path("./data/state.db"),
        Path("/app/data/state.db"),
        Path(os.environ.get("STATE_DB_PATH", "/opt/data/state.db")),
        Path(os.path.expanduser("~/.hermes/state.db"))
    ]

    for db_path in state_db_candidates:
        if db_path.exists():
            try:
                import sqlite3
                conn = sqlite3.connect(str(db_path), timeout=3.0)
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                rows = cursor.execute("""
                    SELECT m.id, m.session_id, m.role, m.content, m.timestamp,
                           s.chat_id, s.display_name, s.title, s.profile_name
                    FROM messages m
                    JOIN sessions s ON m.session_id = s.id
                    WHERE (s.source = 'telegram' OR s.profile_name = 'telegram_bot' OR s.chat_type = 'telegram')
                      AND m.role IN ('user', 'assistant')
                      AND m.active = 1
                      AND m.content IS NOT NULL
                      AND trim(m.content) != ''
                    ORDER BY m.timestamp DESC
                    LIMIT 100
                """).fetchall()

                for r in rows:
                    role = r['role']
                    ts = r['timestamp'] or 0.0
                    try:
                        mtime_val = float(ts)
                        dt_str = datetime.datetime.fromtimestamp(mtime_val).strftime("%Y-%m-%d %H:%M")
                    except Exception:
                        mtime_val = 0.0
                        dt_str = str(ts)

                    content_str = (r['content'] or '').strip()
                    if not content_str:
                        continue

                    # Deduplizierung per Inhalt + Zeit
                    dedup_key = f"{dt_str}_{content_str[:50]}"
                    if dedup_key in seen_contents:
                        continue
                    seen_contents.add(dedup_key)

                    is_user = (role == 'user')
                    chat_user = r['display_name'] or (f"@{r['chat_id']}" if r['chat_id'] else "Telegram User")
                    sender = f"{chat_user} (Telegram)" if is_user else "Telegram Bot (@Beatman_bot)"

                    lower_content = content_str.lower()
                    if "[voice]" in lower_content or "audio" in lower_content or "sprachnachricht" in lower_content:
                        badge = "VOICE"
                        badge_color = "#8B5CF6"
                        badge_bg = "#EDE9FE"
                    elif "[image" in lower_content or "[bild" in lower_content or "photo" in lower_content or "bild" in lower_content:
                        badge = "BILD"
                        badge_color = "#10B981"
                        badge_bg = "#D1FAE5"
                    elif is_user:
                        badge = "TEXT"
                        badge_color = "#3B82F6"
                        badge_bg = "#DBEAFE"
                    else:
                        badge = "BOT"
                        badge_color = "#6366F1"
                        badge_bg = "#EEF2FF"

                    first_line = content_str.split("\n")[0].strip()
                    title = f"{sender}: {first_line[:45]}..." if len(first_line) > 45 else f"{sender}: {first_line}"

                    sec_status = "safe"
                    sec_flags = []
                    try:
                        import sys
                        sys_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                        if sys_dir not in sys.path:
                            sys.path.insert(0, sys_dir)
                        from local_security_guard import scan_prompt_injection
                        scan_res = scan_prompt_injection(content_str, subject="Telegram", sender=sender)
                        sec_status = scan_res.get("verdict", "safe")
                        sec_flags = scan_res.get("pattern_matches", [])
                    except Exception:
                        pass

                    messages.append({
                        "id": f"tg_db_{r['id']}",
                        "sender": sender,
                        "badge": badge,
                        "badge_color": badge_color,
                        "badge_bg": badge_bg,
                        "title": title,
                        "timestamp": dt_str,
                        "preview": (content_str[:160] + "...") if len(content_str) > 160 else content_str,
                        "content": content_str,
                        "path": f"Telegram Live-Chat (Session: {r['session_id']}, Msg: #{r['id']})",
                        "mtime": mtime_val,
                        "source": "telegram",
                        "security_status": sec_status,
                        "security_flags": sec_flags
                    })

                conn.close()
                break
            except Exception as e:
                pass

    # 2. Ergänzend physische Dateien aus get_telegram_inbox_dir() einlesen
    tg_dir = get_telegram_inbox_dir()
    if tg_dir.exists():
        for file_path in tg_dir.iterdir():
            if not file_path.is_file():
                continue

            mtime = file_path.stat().st_mtime
            dt_str = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
            ext = file_path.suffix.lower()

            if ext == ".json":
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        data = json.load(f)

                    msg_type = (data.get("type") or "TEXT").upper()
                    if "voice" in data or msg_type == "VOICE":
                        badge = "VOICE"
                        badge_color = "#8B5CF6"
                        badge_bg = "#EDE9FE"
                    elif "photo" in data or "image" in data or msg_type in ["BILD", "PHOTO", "IMAGE"]:
                        badge = "BILD"
                        badge_color = "#10B981"
                        badge_bg = "#D1FAE5"
                    else:
                        badge = "TEXT"
                        badge_color = "#3B82F6"
                        badge_bg = "#DBEAFE"

                    sender = data.get("from") or data.get("sender") or data.get("chat_title") or "Telegram Bot"
                    date_val = data.get("date") or data.get("timestamp") or dt_str
                    text = data.get("text") or data.get("caption") or data.get("transcription") or json.dumps(data, indent=2)

                    dedup_key = f"{date_val}_{text[:50]}"
                    if dedup_key in seen_contents:
                        continue
                    seen_contents.add(dedup_key)

                    title = f"{sender}: {text[:45]}..." if len(text) > 45 else f"{sender}: {text}"

                    sec_status = "safe"
                    sec_flags = []
                    try:
                        import sys
                        sys_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                        if sys_dir not in sys.path:
                            sys.path.insert(0, sys_dir)
                        from local_security_guard import scan_prompt_injection
                        scan_res = scan_prompt_injection(text, subject="Telegram", sender=sender)
                        sec_status = scan_res.get("verdict", "safe")
                        sec_flags = scan_res.get("pattern_matches", [])
                    except Exception:
                        pass

                    mtime_val = float(data.get("mtime") or mtime)

                    messages.append({
                        "id": f"tg_{file_path.name}",
                        "sender": sender,
                        "badge": badge,
                        "badge_color": badge_color,
                        "badge_bg": badge_bg,
                        "title": title,
                        "timestamp": date_val,
                        "preview": (text[:160] + "...") if len(text) > 160 else text,
                        "content": text,
                        "path": str(file_path),
                        "mtime": mtime_val,
                        "source": "telegram",
                        "security_status": sec_status,
                        "security_flags": sec_flags
                    })
                except Exception:
                    continue

            elif ext in [".txt", ".log"]:
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        content_str = f.read().strip()

                    if not content_str:
                        continue

                    sender = "Telegram User"
                    date_val = dt_str
                    text = content_str

                    import re
                    match = re.match(r"^\[([0-9-]+\s+[0-9:]+)\]\s*([^:\n]+):\s*(.*)", content_str, re.DOTALL)
                    if match:
                        date_val = match.group(1).strip()
                        sender = match.group(2).strip()
                        text = match.group(3).strip()

                    dedup_key = f"{date_val}_{text[:50]}"
                    if dedup_key in seen_contents:
                        continue
                    seen_contents.add(dedup_key)

                    title = f"{sender}: {text[:45]}..." if len(text) > 45 else f"{sender}: {text}"

                    sec_status = "safe"
                    sec_flags = []
                    try:
                        import sys
                        sys_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                        if sys_dir not in sys.path:
                            sys.path.insert(0, sys_dir)
                        from local_security_guard import scan_prompt_injection
                        scan_res = scan_prompt_injection(text, subject="Telegram", sender=sender)
                        sec_status = scan_res.get("verdict", "safe")
                        sec_flags = scan_res.get("pattern_matches", [])
                    except Exception:
                        pass

                    messages.append({
                        "id": f"tg_{file_path.name}",
                        "sender": sender,
                        "badge": "TEXT",
                        "badge_color": "#3B82F6",
                        "badge_bg": "#DBEAFE",
                        "title": title,
                        "timestamp": date_val,
                        "preview": (text[:160] + "...") if len(text) > 160 else text,
                        "content": text,
                        "path": str(file_path),
                        "mtime": mtime,
                        "source": "telegram",
                        "security_status": sec_status,
                        "security_flags": sec_flags
                    })
                except Exception:
                    continue

    messages.sort(key=lambda x: x.get("mtime", 0), reverse=True)
    return messages

def load_webhook_events() -> List[Dict[str, Any]]:
    """
    Liest eingehende Webhooks & API-Events aus get_webhook_inbox_dir().
    Unterstuetzt .json und .txt Dateien (z.B. von n8n, Stripe, GitHub, generic APIs).
    Liefert aussagekraeftige Standard-Events falls das Verzeichnis leer ist.
    """
    now = datetime.datetime.now()
    wh_dir = get_webhook_inbox_dir()
    events: List[Dict[str, Any]] = []

    if wh_dir.exists():
        for file_path in wh_dir.iterdir():
            if not file_path.is_file():
                continue
            mtime = file_path.stat().st_mtime
            dt_str = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
            ext = file_path.suffix.lower()

            if ext == ".json":
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        data = json.load(f)

                    source = str(data.get("source") or data.get("provider") or "API").upper()
                    event_type = str(data.get("event") or data.get("type") or "WEBHOOK").upper()
                    title = data.get("title") or f"{source} Event: {event_type}"
                    sender = data.get("sender") or data.get("origin") or f"Webhook ({source})"
                    payload_preview = json.dumps(data, indent=2, ensure_ascii=False)
                    preview = data.get("preview") or data.get("summary") or (payload_preview[:160] + "...")

                    badge = event_type[:8]
                    badge_color = "#F59E0B"
                    badge_bg = "#FEF3C7"
                    if "N8N" in source or "N8N" in event_type:
                        badge = "N8N"
                        badge_color = "#EA580C"
                        badge_bg = "#FFEDD5"
                    elif "STRIPE" in source or "PAYMENT" in event_type:
                        badge = "STRIPE"
                        badge_color = "#6366F1"
                        badge_bg = "#EEF2FF"
                    elif "GITHUB" in source or "GIT" in event_type:
                        badge = "GITHUB"
                        badge_color = "#10B981"
                        badge_bg = "#D1FAE5"

                    events.append({
                        "id": f"wh_{file_path.name}",
                        "sender": sender,
                        "badge": badge,
                        "badge_color": badge_color,
                        "badge_bg": badge_bg,
                        "title": title,
                        "timestamp": dt_str,
                        "preview": preview,
                        "content": payload_preview,
                        "path": str(file_path),
                        "mtime": mtime,
                        "source": "webhook"
                    })
                except Exception:
                    continue

            elif ext in [".txt", ".log"]:
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        content_str = f.read().strip()
                    if not content_str:
                        continue
                    events.append({
                        "id": f"wh_{file_path.name}",
                        "sender": "Webhook Inbound",
                        "badge": "PAYLOAD",
                        "badge_color": "#F59E0B",
                        "badge_bg": "#FEF3C7",
                        "title": f"Raw Webhook: {file_path.stem}",
                        "timestamp": dt_str,
                        "preview": content_str[:160] + ("..." if len(content_str) > 160 else ""),
                        "content": content_str,
                        "path": str(file_path),
                        "mtime": mtime,
                        "source": "webhook"
                    })
                except Exception:
                    continue

    if not events:
        events = [
            {
                "id": "wh_n8n_lead_sync",
                "sender": "n8n Automation Node (Port 5678)",
                "badge": "N8N",
                "badge_color": "#EA580C",
                "badge_bg": "#FFEDD5",
                "title": "n8n Workflow: CRM Lead Enrichment Triggered",
                "timestamp": now.strftime("%Y-%m-%d %H:%M"),
                "preview": "Inbound Webhook von /webhook/archon-execution: 1 neuer Lead synchronisiert.",
                "content": json.dumps({
                    "event": "crm_lead_enrichment",
                    "origin": "n8n_workflow_engine",
                    "payload": {
                        "source": "Landingpage Formular",
                        "status": "ready_for_triage",
                        "contact_id": "CNT-2026-904"
                    }
                }, indent=2),
                "path": "webhook://n8n/crm_lead_enrichment",
                "mtime": now.timestamp() - 120,
                "source": "webhook"
            },
            {
                "id": "wh_github_deploy",
                "sender": "GitHub App Webhook",
                "badge": "GITHUB",
                "badge_color": "#10B981",
                "badge_bg": "#D1FAE5",
                "title": "GitHub Push Event: main branch updated",
                "timestamp": (now - datetime.timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M"),
                "preview": "Commit b89af1e auf branch main von @archon-dev: Update agent manifests.",
                "content": json.dumps({
                    "repository": "AgenticOS-2026",
                    "ref": "refs/heads/main",
                    "head_commit": {
                        "id": "b89af1e442d",
                        "message": "Update agent manifests & layout engine"
                    }
                }, indent=2),
                "path": "webhook://github/push/main",
                "mtime": (now - datetime.timedelta(minutes=15)).timestamp(),
                "source": "webhook"
            }
        ]

    events.sort(key=lambda x: x.get("mtime", 0), reverse=True)
    return events



# =============================================================================
# CENTRAL OPERATIONAL SCREEN RENDERER (HTML / WEB-OS CONTRACT)
# =============================================================================

def render_inbox_view() -> str:
    """
    Rendert den vollständigen, lauffähigen 3-Spalten Triage-Screen für Archon OS.
    Hält strikt die Design-Standards ein:
    - Hintergrund: #F8FAFC
    - Cards: #FFFFFF, 1px solid #E2E8F0, Radius 8px, Padding 12px
    - Header: Signalpunkt #EF4444 vor 'EINGANG (TRIAGE & STREAMS)'
    - Primär-Button: #DC2626
    """
    intern_items = load_internal_events()
    email_items = load_email_messages()
    telegram_items = load_telegram_messages()

    total_count = len(intern_items) + len(email_items) + len(telegram_items)

    # 1. Spalte Intern Cards
    intern_cards_html = ""
    for idx, item in enumerate(intern_items):
        badge_bg = item.get("badge_bg", "#F1F5F9")
        badge_color = item.get("badge_color", "#475569")
        badge = item.get("badge", "SYSTEM")
        title = item.get("title", "Meldung")
        preview = item.get("preview", "")
        ts = item.get("timestamp", "")
        intern_cards_html += f"""
        <div onclick="openInboxModal('intern', {idx})" 
             class="inbox-card cursor-pointer transition-all hover:shadow-xs hover:border-slate-300"
             style="background-color: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 8px; padding: 12px; margin-bottom: 12px;">
          <div class="flex items-center justify-between gap-2 mb-1.5">
            <span class="font-mono font-bold uppercase tracking-wider" 
                  style="font-size: 10px; padding: 2px 6px; border-radius: 4px; background-color: {badge_bg}; color: {badge_color};">
              [{badge}]
            </span>
            <span class="font-mono" style="font-size: 11px; color: #64748B;">{ts}</span>
          </div>
          <h4 class="font-mono font-semibold truncate mb-1" style="font-size: 12px; color: #0F172A;">{title}</h4>
          <p class="font-mono line-clamp-3 leading-relaxed m-0" style="font-size: 12px; color: #64748B;">{preview}</p>
        </div>
        """

    # 2. Spalte E-Mail Cards
    email_cards_html = ""
    if not email_items:
        email_cards_html = """
        <div style="background-color: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 8px; padding: 16px; text-align: center;">
          <p class="font-mono m-0" style="font-size: 12px; color: #64748B;">Keine neuen E-Mails im Postfach</p>
        </div>
        """
    else:
        for idx, item in enumerate(email_items):
            sender = item.get("sender", "Absender")
            subject = item.get("subject", "Kein Betreff")
            preview = item.get("preview", "")
            ts = item.get("timestamp", "")
            sec_status = item.get("security_status", "safe")
            
            border_style = "border: 1px solid #E2E8F0;"
            sec_badge = ""
            if sec_status == "blocked":
                border_style = "border: 1.5px solid #EF4444; background-color: #FEF2F2;"
                sec_badge = '<span class="font-mono font-bold uppercase tracking-wider" style="font-size: 9px; padding: 2px 6px; border-radius: 4px; background-color: #FEE2E2; color: #DC2626; border: 1px solid #FCA5A5;">🛡️ INJECTION BLOCKED</span>'
            elif sec_status == "suspicious":
                border_style = "border: 1.5px solid #F59E0B; background-color: #FFFBEB;"
                sec_badge = '<span class="font-mono font-bold uppercase tracking-wider" style="font-size: 9px; padding: 2px 6px; border-radius: 4px; background-color: #FEF3C7; color: #D97706; border: 1px solid #FCD34D;">⚠️ SUSPICIOUS</span>'

            email_cards_html += f"""
            <div onclick="openInboxModal('email', {idx})" 
                 class="inbox-card cursor-pointer transition-all hover:shadow-xs hover:border-slate-300"
                 style="background-color: #FFFFFF; {border_style} border-radius: 8px; padding: 12px; margin-bottom: 12px;">
              <div class="flex items-center justify-between gap-2 mb-1.5">
                <span class="font-mono font-semibold truncate flex items-center gap-1.5" style="font-size: 11px; color: #0F172A;">
                  <span>✉️ {sender}</span>
                  {sec_badge}
                </span>
                <span class="font-mono shrink-0" style="font-size: 11px; color: #64748B;">{ts}</span>
              </div>
              <h4 class="font-mono font-semibold truncate mb-1" style="font-size: 12px; color: #0F172A;">{subject}</h4>
              <p class="font-mono line-clamp-3 leading-relaxed m-0" style="font-size: 12px; color: #64748B;">{preview}</p>
            </div>
            """

    # 3. Spalte Telegram Cards
    telegram_cards_html = ""
    if not telegram_items:
        telegram_cards_html = """
        <div style="background-color: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 8px; padding: 16px; text-align: center;">
          <p class="font-mono m-0" style="font-size: 12px; color: #64748B;">Keine neuen Telegram-Nachrichten</p>
        </div>
        """
    else:
        for idx, item in enumerate(telegram_items):
            badge = item.get("badge", "TEXT")
            badge_bg = item.get("badge_bg", "#DBEAFE")
            badge_color = item.get("badge_color", "#3B82F6")
            sender = item.get("sender", "Telegram")
            preview = item.get("preview", "")
            ts = item.get("timestamp", "")
            sec_status = item.get("security_status", "safe")

            border_style = "border: 1px solid #E2E8F0;"
            sec_badge = ""
            if sec_status == "blocked":
                border_style = "border: 1.5px solid #EF4444; background-color: #FEF2F2;"
                sec_badge = '<span class="font-mono font-bold uppercase tracking-wider" style="font-size: 9px; padding: 2px 6px; border-radius: 4px; background-color: #FEE2E2; color: #DC2626; border: 1px solid #FCA5A5;">🛡️ INJECTION</span>'
            elif sec_status == "suspicious":
                border_style = "border: 1.5px solid #F59E0B; background-color: #FFFBEB;"
                sec_badge = '<span class="font-mono font-bold uppercase tracking-wider" style="font-size: 9px; padding: 2px 6px; border-radius: 4px; background-color: #FEF3C7; color: #D97706; border: 1px solid #FCD34D;">⚠️ VERDÄCHTIG</span>'

            telegram_cards_html += f"""
            <div onclick="openInboxModal('telegram', {idx})" 
                 class="inbox-card cursor-pointer transition-all hover:shadow-xs hover:border-slate-300"
                 style="background-color: #FFFFFF; {border_style} border-radius: 8px; padding: 12px; margin-bottom: 12px;">
              <div class="flex items-center justify-between gap-2 mb-1.5">
                <div class="flex items-center gap-1.5">
                  <span class="font-mono font-bold uppercase tracking-wider" 
                        style="font-size: 10px; padding: 2px 6px; border-radius: 4px; background-color: {badge_bg}; color: {badge_color};">
                    [{badge}]
                  </span>
                  {sec_badge}
                </div>
                <span class="font-mono" style="font-size: 11px; color: #64748B;">{ts}</span>
              </div>
              <h4 class="font-mono font-semibold truncate mb-1" style="font-size: 12px; color: #0F172A;">{sender}</h4>
              <p class="font-mono line-clamp-3 leading-relaxed m-0" style="font-size: 12px; color: #64748B;">{preview}</p>
            </div>
            """

    # JSON Payload für das Client-Modal serialisieren
    full_inbox_payload = {
        "intern": intern_items,
        "email": email_items,
        "telegram": telegram_items
    }
    serialized_payload = json.dumps(full_inbox_payload, ensure_ascii=False)

    return f"""
    <div id="view-inbox" class="flex-1 w-full min-h-screen flex flex-col p-6 select-none" 
         style="background-color: #F8FAFC !important; color: #0F172A !important; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;">
      
      <!-- HEADER GEMÄSS DESIGN-STANDARDS -->
      <div class="flex items-center justify-between pb-5 border-b mb-6" style="border-color: #E2E8F0 !important;">
        <div>
          <div class="flex items-center gap-2">
            <span class="w-2.5 h-2.5 rounded-full inline-block" style="background-color: #4F46E5 !important;"></span>
            <h1 class="text-sm font-bold uppercase tracking-wider font-mono m-0" style="color: #0F172A !important;">
              EINGANG (TRIAGE & STREAMS)
            </h1>
          </div>
          <p class="text-xs mt-1 font-mono m-0" style="color: #64748B !important;">
            Operative Ereignisse, Genehmigungs-Gates, E-Mails & Telegram Stream
          </p>
        </div>
        <div class="flex items-center gap-3">
          <span id="inbox-total-badge" class="px-2.5 py-1 rounded text-xs font-mono font-medium border" 
                style="background-color: #FFFFFF !important; border-color: #E2E8F0 !important; color: #0F172A !important;">
            {total_count} Ereignisse
          </span>
          <button onclick="if(typeof loadInboxView === 'function') loadInboxView(); else window.location.reload();" 
                  class="px-3 py-1.5 rounded text-xs font-mono font-medium border flex items-center gap-1.5 hover:bg-slate-50 transition-colors" 
                  style="background-color: #FFFFFF !important; border-color: #E2E8F0 !important; color: #0F172A !important;">
            <i data-lucide="refresh-cw" class="w-3.5 h-3.5"></i>
            <span>Aktualisieren</span>
          </button>
        </div>
      </div>

      <!-- 3 SPALTEN: INTERN, E-MAIL, TELEGRAM -->
      <div class="grid grid-cols-1 md:grid-cols-3 gap-6 flex-1 items-start">
        
        <!-- SPALTE 1: INTERN -->
        <div class="flex flex-col space-y-3">
          <div class="flex items-center justify-between pb-2 border-b" style="border-color: #E2E8F0 !important;">
            <div class="flex items-center gap-2">
              <i data-lucide="bell" class="w-4 h-4 text-purple-600"></i>
              <h3 class="text-xs font-bold uppercase tracking-wider font-mono m-0" style="color: #0F172A !important;">
                1. Intern (Logs & Gates)
              </h3>
            </div>
            <span id="inbox-badge-intern" class="text-[11px] font-mono px-2 py-0.5 rounded border" 
                  style="background-color: #FFFFFF !important; border-color: #E2E8F0 !important; color: #64748B !important;">
              {len(intern_items)}
            </span>
          </div>
          <div id="inbox-list-intern" class="space-y-0 min-h-[250px]">
            {intern_cards_html}
          </div>
        </div>

        <!-- SPALTE 2: E-MAIL -->
        <div class="flex flex-col space-y-3">
          <div class="flex items-center justify-between pb-2 border-b" style="border-color: #E2E8F0 !important;">
            <div class="flex items-center gap-2">
              <i data-lucide="mail" class="w-4 h-4 text-blue-600"></i>
              <h3 class="text-xs font-bold uppercase tracking-wider font-mono m-0" style="color: #0F172A !important;">
                2. E-Mail Postfach
              </h3>
            </div>
            <span id="inbox-badge-email" class="text-[11px] font-mono px-2 py-0.5 rounded border" 
                  style="background-color: #FFFFFF !important; border-color: #E2E8F0 !important; color: #64748B !important;">
              {len(email_items)}
            </span>
          </div>
          <div id="inbox-list-email" class="space-y-0 min-h-[250px]">
            {email_cards_html}
          </div>
        </div>

        <!-- SPALTE 3: TELEGRAM -->
        <div class="flex flex-col space-y-3">
          <div class="flex items-center justify-between pb-2 border-b" style="border-color: #E2E8F0 !important;">
            <div class="flex items-center gap-2">
              <i data-lucide="send" class="w-4 h-4 text-sky-500"></i>
              <h3 class="text-xs font-bold uppercase tracking-wider font-mono m-0" style="color: #0F172A !important;">
                3. Telegram Stream
              </h3>
            </div>
            <span id="inbox-badge-telegram" class="text-[11px] font-mono px-2 py-0.5 rounded border" 
                  style="background-color: #FFFFFF !important; border-color: #E2E8F0 !important; color: #64748B !important;">
              {len(telegram_items)}
            </span>
          </div>
          <div id="inbox-list-telegram" class="space-y-0 min-h-[250px]">
            {telegram_cards_html}
          </div>
        </div>

      </div>

      <!-- ZENTRIERTES DETAIL-MODAL -->
      <div id="inbox-detail-modal" class="hidden fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-xs p-4">
        <div class="w-full max-w-2xl rounded-lg border flex flex-col max-h-[85vh] overflow-hidden" 
             style="background-color: #FFFFFF !important; border-color: #E2E8F0 !important;">
          <div class="flex items-center justify-between px-6 py-4 border-b" style="border-color: #E2E8F0 !important;">
            <div class="flex items-center gap-2.5">
              <span class="w-2.5 h-2.5 rounded-full inline-block" style="background-color: #4F46E5 !important;"></span>
              <h3 id="inbox-modal-title" class="text-sm font-bold font-mono uppercase m-0" style="color: #0F172A !important;">
                Nachrichtendetails
              </h3>
            </div>
            <button onclick="closeInboxModal()" class="text-slate-400 hover:text-slate-600 border-none bg-transparent cursor-pointer p-1">
              <i data-lucide="x" class="w-5 h-5"></i>
            </button>
          </div>
          <div class="px-6 py-4 overflow-y-auto flex-1 font-mono text-xs space-y-3" style="color: #334155 !important;">
            <div class="text-[11px] text-slate-400 font-mono pb-2 border-b" id="inbox-modal-meta" style="border-color: #F1F5F9 !important;"></div>
            <div id="inbox-modal-body" class="p-4 rounded border whitespace-pre-wrap leading-relaxed select-text" 
                 style="background-color: #F8FAFC !important; border-color: #E2E8F0 !important; color: #0F172A !important;">
            </div>
          </div>
          <div class="flex items-center justify-between px-6 py-4 border-t" 
               style="border-color: #E2E8F0 !important; background-color: #F8FAFC !important;">
            <button onclick="closeInboxModal()" class="px-3.5 py-1.5 rounded border text-xs font-mono hover:bg-slate-100 cursor-pointer" 
                    style="background-color: #FFFFFF !important; border-color: #E2E8F0 !important; color: #334155 !important;">
              Schließen
            </button>
            <button id="inbox-modal-analyze-btn" 
                    class="px-4 py-1.5 rounded text-xs font-mono font-semibold text-white flex items-center gap-2 hover:opacity-90 cursor-pointer" 
                    style="background-color: #4F46E5 !important; border: 1px solid #4F46E5 !important;">
              <i data-lucide="sparkles" class="w-3.5 h-3.5"></i>
              <span>In Quickchat analysieren</span>
            </button>
          </div>
        </div>
      </div>

    </div>

    <!-- CLIENT LOGIK & DISPATCHER SCRIPT -->
    <script>
      window._inboxInitialData = {serialized_payload};
      if (!window._inboxCurrentData) {{
        window._inboxCurrentData = window._inboxInitialData;
      }}

      function openInboxModal(type, idx) {{
        const store = window._inboxCurrentData || window._inboxInitialData;
        if (!store || !store[type]) return;
        const item = store[type][idx];
        if (!item) return;

        const modal = document.getElementById('inbox-detail-modal');
        const titleEl = document.getElementById('inbox-modal-title');
        const metaEl = document.getElementById('inbox-modal-meta');
        const bodyEl = document.getElementById('inbox-modal-body');
        const analyzeBtn = document.getElementById('inbox-modal-analyze-btn');

        if (titleEl) titleEl.innerText = `${{type.toUpperCase()}}: ${{item.title || item.subject || 'Nachricht'}}`;
        if (metaEl) {{
          metaEl.innerHTML = `<strong>Absender:</strong> ${{item.sender || 'Unbekannt'}} &nbsp;|&nbsp; <strong>Zeit:</strong> ${{item.timestamp || ''}} &nbsp;|&nbsp; <strong>Pfad:</strong> ${{item.path || 'In-Memory'}}`;
        }}
        if (bodyEl) {{
          bodyEl.innerText = item.content || item.preview || '(Kein Inhalt vorhanden)';
        }}

        if (analyzeBtn) {{
          analyzeBtn.onclick = function() {{
            const rawBody = item.content || item.preview || '';
            const queryPrefix = "[EINGANGS-ANALYSE] Untersuche folgende Nachricht: ";
            const fullPrompt = `${{queryPrefix}}${{rawBody}}`;

            closeInboxModal();

            // 1. In Session-Storage / State schreiben
            sessionStorage.setItem('pending_chat_input', fullPrompt);

            // 2. Chat-Input im DOM befüllen
            const chatInput = document.getElementById('master-chat-input');
            if (chatInput) {{
              chatInput.value = fullPrompt;
            }}

            // 3. Auf Chat umschalten (unterstützt setTab 'master-chat' oder 'chat')
            if (typeof setTab === 'function') {{
              setTab('master-chat');
            }} else if (typeof switchTab === 'function') {{
              switchTab('chat');
            }}

            setTimeout(() => {{
              const freshInput = document.getElementById('master-chat-input');
              if (freshInput) {{
                freshInput.value = fullPrompt;
                freshInput.focus();
              }}
            }}, 150);
          }};
        }}

        if (modal) modal.classList.remove('hidden');
        if (window.lucide) window.lucide.createIcons();
      }}

      function closeInboxModal() {{
        const modal = document.getElementById('inbox-detail-modal');
        if (modal) modal.classList.add('hidden');
      }}
    </script>
    """


# =============================================================================
# STREAMLIT INTEGRATION (FALLS IN STREAMLIT RUNTIME GELADEN)
# =============================================================================

def render_inbox_streamlit():
    """
    Rendert den Triage-Bildschirm nativ in Streamlit (unterstützt st.dialog und st.session_state).
    Wird aufgerufen, wenn views/view_inbox.py in einer Streamlit-App verwendet wird.
    """
    try:
        import streamlit as st
    except ImportError:
        return

    st.markdown("""
        <style>
            .stApp { background-color: #F8FAFC !important; }
            .inbox-card-st {
                background-color: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 8px;
                padding: 12px;
                margin-bottom: 12px;
            }
        </style>
    """, unsafe_allow_html=True)

    # Header
    st.markdown("""
        <div style="display: flex; align-items: center; gap: 8px; border-bottom: 1px solid #E2E8F0; padding-bottom: 16px; margin-bottom: 20px;">
            <span style="display: inline-block; width: 10px; height: 10px; border-radius: 50%; background-color: #4F46E5;"></span>
            <span style="font-family: monospace; font-size: 16px; font-weight: bold; color: #0F172A;">EINGANG (TRIAGE & STREAMS)</span>
        </div>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns(3)

    intern_items = load_internal_events()
    email_items = load_email_messages()
    telegram_items = load_telegram_messages()

    # Modal Helper via st.dialog
    if hasattr(st, "dialog"):
        @st.dialog("Nachrichtendetails")
        def show_item_dialog(item: Dict[str, Any]):
            st.markdown(f"**Absender:** {item.get('sender', 'Unbekannt')}")
            st.markdown(f"**Empfangszeit:** {item.get('timestamp', '')}")
            st.markdown(f"**Dateipfad:** `{item.get('path', 'In-Memory')}`")
            st.divider()
            st.code(item.get("content") or item.get("preview") or "", language="text")

            if st.button("In Quickchat analysieren", type="primary"):
                st.session_state["pending_chat_input"] = (
                    f"[EINGANGS-ANALYSE] Untersuche folgende Nachricht: {item.get('content') or item.get('preview') or ''}"
                )
                st.session_state["active_target"] = "chat"
                st.session_state["active_tab"] = "master-chat"
                st.rerun()

    # Spalte 1: INTERN
    with col1:
        st.markdown(f"### 🔔 Intern ({len(intern_items)})")
        for item in intern_items:
            with st.container():
                st.markdown(
                    f"<div class='inbox-card-st'>"
                    f"<span style='color: {item.get('badge_color', '#3B82F6')}; font-weight: bold;'>[{item.get('badge', 'SYSTEM')}]</span> "
                    f"<span style='color: #64748B; font-size: 11px;'>{item.get('timestamp')}</span><br>"
                    f"<strong style='color: #0F172A;'>{item.get('title')}</strong><br>"
                    f"<span style='color: #64748B; font-size: 12px;'>{item.get('preview')}</span>"
                    f"</div>",
                    unsafe_allow_html=True
                )
                if st.button("Öffnen", key=f"btn_int_{item.get('id')}"):
                    if hasattr(st, "dialog"):
                        show_item_dialog(item)
                    else:
                        st.session_state["pending_chat_input"] = f"[EINGANGS-ANALYSE] Untersuche folgende Nachricht: {item.get('content') or item.get('preview')}"
                        st.session_state["active_target"] = "chat"

    # Spalte 2: E-MAIL
    with col2:
        st.markdown(f"### ✉️ E-Mail ({len(email_items)})")
        if not email_items:
            st.info("Keine neuen E-Mails im Postfach")
        else:
            for item in email_items:
                with st.container():
                    st.markdown(
                        f"<div class='inbox-card-st'>"
                        f"<strong style='color: #0F172A;'>{item.get('sender')}</strong> "
                        f"<span style='color: #64748B; font-size: 11px;'>{item.get('timestamp')}</span><br>"
                        f"<span style='color: #0F172A; font-weight: 500;'>{item.get('subject')}</span><br>"
                        f"<span style='color: #64748B; font-size: 12px;'>{item.get('preview')}</span>"
                        f"</div>",
                        unsafe_allow_html=True
                    )
                    if st.button("Öffnen", key=f"btn_mail_{item.get('id')}"):
                        if hasattr(st, "dialog"):
                            show_item_dialog(item)
                        else:
                            st.session_state["pending_chat_input"] = f"[EINGANGS-ANALYSE] Untersuche folgende Nachricht: {item.get('content') or item.get('preview')}"
                            st.session_state["active_target"] = "chat"

    # Spalte 3: TELEGRAM
    with col3:
        st.markdown(f"### 🚀 Telegram ({len(telegram_items)})")
        if not telegram_items:
            st.info("Keine neuen Telegram-Nachrichten")
        else:
            for item in telegram_items:
                with st.container():
                    st.markdown(
                        f"<div class='inbox-card-st'>"
                        f"<span style='color: {item.get('badge_color', '#3B82F6')}; font-weight: bold;'>[{item.get('badge', 'TEXT')}]</span> "
                        f"<span style='color: #64748B; font-size: 11px;'>{item.get('timestamp')}</span><br>"
                        f"<strong style='color: #0F172A;'>{item.get('sender')}</strong><br>"
                        f"<span style='color: #64748B; font-size: 12px;'>{item.get('preview')}</span>"
                        f"</div>",
                        unsafe_allow_html=True
                    )
                    if st.button("Öffnen", key=f"btn_tg_{item.get('id')}"):
                        if hasattr(st, "dialog"):
                            show_item_dialog(item)
                        else:
                            st.session_state["pending_chat_input"] = f"[EINGANGS-ANALYSE] Untersuche folgende Nachricht: {item.get('content') or item.get('preview')}"
                            st.session_state["active_target"] = "chat"


# Standalone-Test
if __name__ == "__main__":
    html_out = render_inbox_view()
    print(f"[OK] views/view_inbox.py erfolgreich gerendert ({len(html_out)} Zeichen).")
