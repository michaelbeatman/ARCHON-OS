#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sync_telegram_sessions.py — Archon OS & Hermes Telegram Session Synchronizer & Diagnostic Tool.

Funktion:
  - Prüft den Verbindungsstatus des Hermes Telegram Gateways.
  - Erkennt und behebt Session-Splitting (Doppel-Sessions zwischen Root state.db und profiles/telegram_bot/state.db).
  - Bereinigt Phantom-Sessions in der Root-Datenbank, damit Archon OS Web-UI immer den echten Live-Verlauf anzeigt.
  - Listet alle Telegram-Sessions mit ID, letzter Aktivität und Nachrichtenzähler auf.

Aufruf:
  python scripts/sync_telegram_sessions.py --check
  python scripts/sync_telegram_sessions.py --fix
"""

import os
import sys
import json
import sqlite3
import argparse
import datetime
from pathlib import Path


def get_hermes_paths():
    base_candidates = [
        Path(os.environ.get("HERMES_HOME", "")),
        Path("/home/micha/.hermes"),
        Path("/opt/data"),
        Path.home() / ".hermes",
    ]
    hermes_dir = None
    for c in base_candidates:
        if c and c.is_dir() and (c / "state.db").exists():
            hermes_dir = c
            break

    if not hermes_dir:
        hermes_dir = Path("/home/micha/.hermes")

    root_db = hermes_dir / "state.db"
    profile_db = hermes_dir / "profiles" / "telegram_bot" / "state.db"
    gw_state_file = hermes_dir / "gateway_state.json"

    return hermes_dir, root_db, profile_db, gw_state_file


def check_gateway_status(gw_state_file: Path):
    if not gw_state_file.is_file():
        return "unbekannt (gateway_state.json fehlt)", {}
    try:
        with open(gw_state_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        platforms = data.get("platforms", {})
        tg_info = platforms.get("telegram", {})
        state = tg_info.get("state", "unknown")
        err = tg_info.get("error_message")
        return state, {"state": state, "error": err, "updated_at": tg_info.get("updated_at")}
    except Exception as e:
        return f"Fehler beim Lesen ({e})", {}


def get_sessions(db_path: Path):
    if not db_path.is_file():
        return {}
    sessions = {}
    try:
        conn = sqlite3.connect(str(db_path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT id, title, profile_name, model, started_at, last_activity_at, message_count, source
            FROM sessions
            WHERE profile_name = 'telegram_bot' OR source = 'telegram'
            ORDER BY COALESCE(last_activity_at, started_at) DESC
        """).fetchall()
        for r in rows:
            sessions[r["id"]] = dict(r)
        conn.close()
    except Exception as e:
        print(f"  [!] Fehler beim Lesen von {db_path}: {e}")
    return sessions


def get_recent_messages(db_path: Path, session_id: str, limit: int = 3):
    if not db_path.is_file():
        return []
    try:
        conn = sqlite3.connect(str(db_path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT id, role, content, timestamp
            FROM messages
            WHERE session_id = ? AND active = 1 AND role != 'session_meta'
            ORDER BY id DESC LIMIT ?
        """, (session_id, limit)).fetchall()
        conn.close()
        return [dict(r) for r in reversed(rows)]
    except Exception:
        return []


def run_sync(fix_mode: bool = False):
    hermes_dir, root_db, profile_db, gw_state_file = get_hermes_paths()
    print("=" * 70)
    print(" ARCHON OS · TELEGRAM SESSION SYNCHRONIZER & DIAGNOSTICS")
    print("=" * 70)
    print(f"Basis-Verzeichnis:   {hermes_dir}")
    print(f"Root-Datenbank:      {root_db} (existiert: {root_db.exists()})")
    print(f"Profil-Datenbank:    {profile_db} (existiert: {profile_db.exists()})")

    gw_state, gw_meta = check_gateway_status(gw_state_file)
    state_icon = "🟢" if gw_state == "connected" else "🔴"
    print(f"Telegram Gateway:    {state_icon} {gw_state}")
    if gw_meta.get("error"):
        print(f"  Letzter Fehler:    {gw_meta['error']}")
    print("-" * 70)

    root_sessions = get_sessions(root_db)
    prof_sessions = get_sessions(profile_db)

    print(f"Gefundene Telegram-Sessions in Profil-DB: {len(prof_sessions)}")
    print(f"Gefundene Telegram-Sessions in Root-DB:   {len(root_sessions)}")
    print("-" * 70)

    # Prüfe auf Doppelgänger / Session-Splitting
    duplicates = set(prof_sessions.keys()) & set(root_sessions.keys())

    if duplicates:
        print(f"⚠️  GEFUNDENE DUPLIKATE / SESSION-SPLITS ({len(duplicates)}):")
        for sid in duplicates:
            p_s = prof_sessions[sid]
            r_s = root_sessions[sid]
            p_cnt = p_s.get("message_count", 0)
            r_cnt = r_s.get("message_count", 0)
            print(f"  - Session ID: {sid}")
            print(f"      Profil-DB: {p_cnt} Nachrichten, Titel: '{p_s.get('title')}', Quelle: {p_s.get('source')}")
            print(f"      Root-DB:   {r_cnt} Nachrichten, Titel: '{r_s.get('title')}', Quelle: {r_s.get('source')}")

            if fix_mode:
                if p_cnt >= r_cnt:
                    # Root DB enthält nur Phantomkopie -> löschen
                    try:
                        conn = sqlite3.connect(str(root_db), timeout=5.0)
                        conn.execute("DELETE FROM messages WHERE session_id = ?", (sid,))
                        conn.execute("DELETE FROM sessions WHERE id = ?", (sid,))
                        conn.commit()
                        conn.close()
                        print(f"      -> Phantom-Kopie aus Root-DB gelöscht. Profil-DB bleibt Master.")
                    except Exception as e:
                        print(f"      -> Fehler beim Bereinigen der Root-DB: {e}")
                else:
                    print(f"      -> Manuelle Prüfung empfohlen: Root-DB hat mehr Nachrichten.")
    else:
        print("✅ Keine doppelten Session-IDs zwischen Root- und Profil-DB gefunden.")

    print("-" * 70)
    print("AKTUELLE TELEGRAM-SESSIONS (Profil-DB Master):")
    sorted_prof = sorted(
        prof_sessions.values(),
        key=lambda x: x.get("last_activity_at") or x.get("started_at") or 0,
        reverse=True
    )

    if not sorted_prof:
        print("  (Keine Sessions in Profil-DB vorhanden)")
    else:
        for idx, s in enumerate(sorted_prof[:5], 1):
            sid = s["id"]
            title = s.get("title") or "Ohne Titel"
            count = s.get("message_count", 0)
            act_ts = s.get("last_activity_at") or s.get("started_at")
            act_str = datetime.datetime.fromtimestamp(act_ts).strftime("%d.%m.%Y %H:%M:%S") if act_ts else "unbekannt"
            is_active = " [AKTIV / ZULETZT]" if idx == 1 else ""
            print(f"  {idx}. ID: {sid}{is_active}")
            print(f"     Titel: {title} | Nachrichten: {count} | Letzte Aktivität: {act_str}")

            msgs = get_recent_messages(profile_db, sid, limit=2)
            if msgs:
                for m in msgs:
                    role = m.get("role", "")
                    content = (m.get("content") or "").strip().replace("\n", " ")
                    if len(content) > 80:
                        content = content[:77] + "..."
                    print(f"       [{role}] {content}")
            print()

    print("=" * 70)
    if not fix_mode and duplicates:
        print("TIPP: Führe den Befehl mit '--fix' aus, um Duplikate automatisch zu bereinigen.")
    else:
        print("Synchronisations-Prüfung abgeschlossen.")
    print("=" * 70)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Telegram Session Synchronizer für Archon OS")
    parser.add_argument("--fix", action="store_true", help="Bereinigt Phantom-Sessions in der Root-DB automatisch")
    parser.add_argument("--check", action="store_true", help="Führt nur eine Prüfung durch (Standard)")
    args = parser.parse_args()

    run_sync(fix_mode=args.fix)
