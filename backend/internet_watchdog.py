import sqlite3

class _ArchonClosingConn(sqlite3.Connection):
    def __enter__(self):
        super().__enter__()
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            super().__exit__(exc_type, exc_val, exc_tb)
        finally:
            self.close()
"""
backend/internet_watchdog.py
Säule 4 der Kognitions- & Systemarchitektur: Internet-Watchdog (Autonomer Web-Radar).

Überwacht kontinuierlich und ressourcenschonend externe Quellen (RSS-Feeds,
Google-News-Recherchen, Portale, Webseiten-Diffs) ohne teuren LLM-Token-Verbrauch.
Sobald relevante Neuerungen entdeckt werden, erzeugt der Watchdog Kanban-Tasks
und schickt optional Alerts mit Freigabe-Buttons auf Telegram.
"""

import os
import sys
import time
import json
import hashlib
import asyncio
import datetime
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Dict, Any, List, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS_FILE = os.path.join(WORKSPACE_DIR, "settings.json")
SEEN_FILE = os.path.join(WORKSPACE_DIR, "data", "watchdog_seen.json")

DEFAULT_WATCHDOG_CONFIG: Dict[str, Any] = {
    "enabled": True,
    "interval_minutes": 30,
    "auto_kanban_sync": False,
    "basket_threshold": 3,
    "priority_keywords": [
        "KfW",
        "Förderstopp",
        "BauGB",
        "GEG",
        "Groq",
        "Claude 3.7",
        "Llama 4"
    ],
    "basket": [],
    "channels": {
        "telegram": False,
        "kanban": False
    },
    "targets": [
        {
            "id": "target-bau",
            "name": "KfW & Baurechts-Änderungen",
            "category": "Markt & Bau",
            "type": "search_feed",
            "query_or_url": "BauGB OR GEG OR KfW Neubau",
            "active": True,
            "last_check": None,
            "last_status": "bereit"
        },
        {
            "id": "target-ki",
            "name": "Model Releases & Frameworks",
            "category": "Technologie & KI",
            "type": "rss",
            "query_or_url": "https://huggingface.co/blog/feed.xml",
            "active": True,
            "last_check": None,
            "last_status": "bereit"
        },
        {
            "id": "target-diff",
            "name": "Webseiten- & Portalanalyse",
            "category": "Web-Diff",
            "type": "rss",
            "query_or_url": "https://news.ycombinator.com/rss",
            "active": True,
            "last_check": None,
            "last_status": "bereit"
        }
    ],
    "last_run": None,
    "recent_findings": []
}


def _load_seen():
    """F-02: chronologisch geordnete Liste (aelteste IDs zuerst) statt set.

    Ein set hat Hash-Ordnung: `list(seen)[-2000:]` warf beliebige IDs raus und
    alte Artikel galten beim naechsten Lauf wieder als neu.
    """
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                raw = data.get("seen_ids", [])
                if isinstance(raw, list):
                    return list(raw)
                if isinstance(raw, set):
                    return list(raw)
                return list(raw) if raw else []
        except Exception:
            pass
    return []


def _save_seen(seen_ids):
    os.makedirs(os.path.dirname(SEEN_FILE), exist_ok=True)
    # F-02: nur die aeltesten Eintraege fallen raus (chronologisch).
    trimmed = seen_ids[-2000:]
    try:
        with open(SEEN_FILE, "w", encoding="utf-8") as f:
            json.dump({"seen_ids": trimmed, "updated_at": datetime.datetime.now().isoformat()}, f, indent=2)
    except Exception as e:
        print(f"[Watchdog] Fehle beim Speichern der Seen-IDs: {e}", file=sys.stderr)


def get_watchdog_config() -> Dict[str, Any]:
    cfg = json.loads(json.dumps(DEFAULT_WATCHDOG_CONFIG))
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                s = json.load(f)
                if "internet_watchdog" in s and isinstance(s["internet_watchdog"], dict):
                    cfg.update(s["internet_watchdog"])
        except Exception as e:
            print(f"[Watchdog] Fehler beim Laden der Einstellungen: {e}", file=sys.stderr)
    return cfg


def save_watchdog_config(new_cfg: Dict[str, Any]) -> bool:
    try:
        from backend.settings_json import atomic_update_settings

        def _apply(current):
            current["internet_watchdog"] = new_cfg

        atomic_update_settings(SETTINGS_FILE, _apply)
        return True
    except Exception as e:
        print(f"[Watchdog] Fehler beim Speichern der Einstellungen: {e}", file=sys.stderr)
        return False


def _fetch_rss_items(url: str, max_items: int = 10) -> List[Dict[str, str]]:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; ArchonWatchdog/2.0; +https://archon-os.local)"}
    )
    with urllib.request.urlopen(req, timeout=8.0) as resp:
        content = resp.read()

    root = ET.fromstring(content)
    items = []
    # Unterstütze RSS <item> und Atom <entry>
    xml_items = root.findall(".//item")
    if not xml_items:
        xml_items = root.findall(".//{http://www.w3.org/2005/Atom}entry")

    for node in xml_items[:max_items]:
        title_node = node.find("title")
        if title_node is None:
            title_node = node.find("{http://www.w3.org/2005/Atom}title")

        link_node = node.find("link")
        if link_node is None:
            link_node = node.find("{http://www.w3.org/2005/Atom}link")

        guid_node = node.find("guid")
        if guid_node is None:
            guid_node = node.find("id")
        if guid_node is None:
            guid_node = node.find("{http://www.w3.org/2005/Atom}id")

        pub_node = node.find("pubDate")
        if pub_node is None:
            pub_node = node.find("{http://www.w3.org/2005/Atom}updated")

        title = title_node.text.strip() if title_node is not None and title_node.text else "Ohne Titel"
        link = ""
        if link_node is not None:
            link = link_node.text.strip() if link_node.text else link_node.get("href", "")
        guid = guid_node.text.strip() if guid_node is not None and guid_node.text else link or title
        pub_date = pub_node.text.strip() if pub_node is not None and pub_node.text else datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

        items.append({
            "title": title,
            "link": link,
            "guid": guid,
            "published": pub_date
        })
    return items


def _send_telegram_notification(text: str, reply_markup: dict = None) -> bool:
    """Sendet Telegram-Nachricht via telegram_notify oder direkt per urllib Fallback."""
    # 1. Versuche telegram_notify falls verfügbar
    try:
        import telegram_notify
        if telegram_notify.send_telegram_message(text, reply_markup=reply_markup):
            return True
    except Exception:
        pass

    # 2. Standalone Fallback mit .env
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        env_path = os.path.expanduser("~/.hermes/.env")
        if os.path.exists(env_path):
            try:
                with open(env_path, "r", encoding="utf-8") as ef:
                    for line in ef:
                        line = line.strip()
                        if line.startswith("TELEGRAM_BOT_TOKEN="):
                            token = line.split("=", 1)[1].strip()
                        elif line.startswith("TELEGRAM_CHAT_ID=") or line.startswith("TELEGRAM_HOME_CHANNEL="):
                            if not chat_id:
                                chat_id = line.split("=", 1)[1].strip()
            except Exception:
                pass

    if not token or not chat_id:
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload_dict = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }
    if reply_markup:
        payload_dict["reply_markup"] = reply_markup
    payload = json.dumps(payload_dict).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=8.0) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"[Watchdog] Standalone Telegram Fallback Fehler: {e}", file=sys.stderr)
        return False


def run_watchdog_scan(force: bool = False) -> Dict[str, Any]:
    """
    Führt einen Durchlauf aller aktiven Radar-Ziele durch.
    Gibt die neu gefundenen Treffer sowie den aktuellen Status zurück.
    """
    cfg = get_watchdog_config()
    if not cfg.get("enabled", True) and not force:
        return {"status": "paused", "new_findings": 0, "findings": []}

    seen_ids = _load_seen()
    is_initial_run = (len(seen_ids) == 0)
    now_iso = datetime.datetime.now().isoformat()
    now_display = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")

    new_findings: List[Dict[str, Any]] = []
    targets = cfg.get("targets", [])

    for target in targets:
        if not target.get("active", True):
            continue

        target_id = target.get("id", "target")
        target_name = target.get("name", "Unbenannt")
        target_type = target.get("type", "rss")
        query_or_url = target.get("query_or_url", "").strip()

        if not query_or_url:
            continue

        feed_url = ""
        if target_type == "search_feed":
            feed_url = f"https://news.google.com/rss/search?q={urllib.parse.quote(query_or_url)}&hl=de&gl=DE&ceid=DE:de"
        else:
            feed_url = query_or_url

        try:
            items = _fetch_rss_items(feed_url, max_items=8)
            target["last_check"] = now_iso
            target["last_status"] = f"OK ({len(items)} Einträge)"

            for it in items:
                item_id = hashlib.sha256(f"{target_id}:{it['guid']}".encode()).hexdigest()[:16]
                if item_id in seen_ids:
                    continue

                seen_ids.append(item_id)  # F-02: Liste statt set (chronologisch)
                finding = {
                    "id": item_id,
                    "target_id": target_id,
                    "target_name": target_name,
                    "category": target.get("category", "Allgemein"),
                    "title": it["title"],
                    "link": it["link"],
                    "published": it["published"],
                    "detected_at": now_display
                }

                # Beim allerersten Start füllen wir die Seen-IDs auf, ohne 50 Alerts zu spammen (höchstens Top 2 als Muster)
                if not is_initial_run or len(new_findings) < 2:
                    new_findings.append(finding)

        except Exception as e:
            target["last_check"] = now_iso
            target["last_status"] = f"Fehler: {str(e)[:50]}"
            print(f"[Watchdog] Fehler bei Ziel '{target_name}': {e}", file=sys.stderr)

    _save_seen(seen_ids)

    # 1. Kanban Sync für neue Funde (nur wenn explizit aktiviert)
    auto_kanban = cfg.get("auto_kanban_sync", False) and cfg.get("channels", {}).get("kanban", False)
    if new_findings and auto_kanban:
        try:
            from local_memory_bridge import LocalMemoryBridge
            bridge = LocalMemoryBridge()
            for f in new_findings:
                task_id = f"watchdog-{f['id']}"
                title = f"[Radar: {f['category']}] {f['title'][:80]}"
                body = (
                    f"📡 **Internet-Watchdog Fund**\n\n"
                    f"• **Quelle:** {f['target_name']} ({f['category']})\n"
                    f"• **Titel:** {f['title']}\n"
                    f"• **Link:** {f['link']}\n"
                    f"• **Erfassungszeit:** {f['detected_at']}\n\n"
                    f"Empfehlung: Relevanz bewerten und ggf. in Projekt überführen."
                )
                bridge.sync_task(
                    task_id=task_id,
                    title=title,
                    role="research_scout",
                    status="ready"
                )

                # Zusätzlich in Hermes kanban.db eintragen falls vorhanden
                for kanban_db in [os.path.expanduser("~/.hermes/kanban.db"), "/opt/data/kanban.db"]:
                    if os.path.exists(kanban_db):
                        try:
                            import sqlite3
                            with sqlite3.connect(kanban_db, timeout=5.0, factory=_ArchonClosingConn) as kconn:
                                kconn.execute("""
                                    INSERT OR IGNORE INTO tasks (id, title, body, assignee, status, priority, created_by, created_at)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                                """, (task_id, title, body, "research_scout", "ready", "normal", "internet_watchdog", now_iso))
                                kconn.commit()
                        except Exception:
                            pass
        except Exception as e:
            print(f"[Watchdog] Kanban-Sync Fehler: {e}", file=sys.stderr)

    # 2. Priority-Keywords Sofort-Alarm (Sonder-Ping für gesuchte Schlagworte)
    prio_keywords = [k.strip().lower() for k in cfg.get("priority_keywords", []) if k.strip()]
    if new_findings and prio_keywords:
        for f in new_findings:
            title_text = f.get('title') or ''
            snippet_text = f.get('snippet') or f.get('summary') or f.get('diff') or ''
            haystack = f"{title_text} {snippet_text}".lower()
            matched_kws = [kw for kw in prio_keywords if kw in haystack]
            if matched_kws:
                f["is_priority"] = True
                f["matched_keywords"] = matched_kws
                # Sofortiger Telegram-Sonderalarm
                if cfg.get("channels", {}).get("telegram", True):
                    try:
                        clean_title = f['title'].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                        kw_str = ", ".join(matched_kws)
                        msg_lines = [
                            f"🚨 <b>PRIO-WATCHDOG SOFORT-ALARM</b>",
                            f"Treffer auf Suchbegriff(e): <code>{kw_str}</code>",
                            f"",
                            f"<b>Titel:</b> {clean_title}",
                            f"<b>Quelle:</b> {f['target_name']} ({f['category']})",
                        ]
                        if f.get("link"):
                            msg_lines.append(f"🔗 {f['link']}")
                        if f.get("snippet"):
                            clean_snip = f['snippet'][:300].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                            msg_lines.append(f"\n<i>{clean_snip}</i>")

                        btns = []
                        if f.get("link"):
                            btns.append([{"text": "↗ Originalartikel", "url": f["link"]}])
                        
                        _send_telegram_notification("\n".join(msg_lines), reply_markup={"inline_keyboard": btns} if btns else None)
                    except Exception as e:
                        print(f"[Watchdog] Prio-Alarm Fehler: {e}", file=sys.stderr)

    # 3. Sammelkorb Schwellenwert-Prüfung (Automatisches Bündeln für Content-Generierer)
    basket = cfg.get("basket", [])
    threshold = int(cfg.get("basket_threshold", 3))
    if len(basket) >= threshold:
        # Schicke Benachrichtigung oder übergebe automatisch an Ghostwriter
        print(f"[Watchdog] Sammelkorb-Schwelle erreicht ({len(basket)}/{threshold} Funde bereit für Synthese)")

    # 4. Regulärer Telegram Alert für neue Funde (mit interaktiven Buttons)
    if new_findings and cfg.get("channels", {}).get("telegram", True):
        try:
            top_findings = new_findings[:3]
            lines = [f"📡 <b>[Watchdog-Radar]</b> {len(new_findings)} neue Einträge erfasst:\n"]
            inline_buttons = []
            for tf in top_findings:
                clean_title = tf['title'].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                lines.append(f"• <b>{tf['category']}:</b> {clean_title}\n  🔗 {tf['link']}")
                # Button direkt zum Artikel oder zur Übergabe
                if tf.get("link"):
                    btn_text = f"↗ {clean_title[:28]}"
                    inline_buttons.append([{"text": btn_text, "url": tf["link"]}])
            if len(new_findings) > 3:
                lines.append(f"\n<i>... und {len(new_findings) - 3} weitere im Radar-Stream.</i>")
            
            kb = {"inline_keyboard": inline_buttons} if inline_buttons else None
            _send_telegram_notification("\n".join(lines), reply_markup=kb)
        except Exception as e:
            print(f"[Watchdog] Telegram-Alert Fehler: {e}", file=sys.stderr)

    # Aktualisiere 'recent_findings' in der Konfiguration
    existing_findings = cfg.get("recent_findings", [])
    merged_findings = (new_findings + existing_findings)[:30]
    cfg["recent_findings"] = merged_findings
    cfg["last_run"] = now_iso
    save_watchdog_config(cfg)

    return {
        "status": "success",
        "new_findings_count": len(new_findings),
        "findings": new_findings,
        "config": cfg
    }


async def internet_watchdog_background_loop():
    """Hintergrund-Task, der zyklisch die definierten Quellen abfragt."""
    # Kurzer Initial-Delay beim Systemstart
    await asyncio.sleep(15)
    while True:
        try:
            cfg = get_watchdog_config()
            if cfg.get("enabled", True):
                run_watchdog_scan(force=False)
            interval_mins = max(5, int(cfg.get("interval_minutes", 30)))
            await asyncio.sleep(interval_mins * 60)
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[Watchdog Loop] Unerwarteter Fehler: {e}", file=sys.stderr)
            await asyncio.sleep(60)
