"""
backend/post_task_pipeline.py
Zentraler Post-Task Hook für Archon OS & Paperclip & Obsidian & Hermes:
1. Projektordner-Struktur (01_Zwischenberichte, 02_Medien, 03_Endprodukte) in Obsidian & Showroom
2. Rückkopplung in die Personalakte des Agenten (Tasks completed, Tabellen-Historie)
3. Automatische Self-Improvement-Schleife (LocalMemoryBridge Learning-Extraktion)
4. Paperclip-Disposition (Status completed / in_review, issue_work_products)
5. E-Mail-Benachrichtigung (Natives SMTP via settings)
"""

import os
import re
import sys
import json
import time
import smtplib
import sqlite3
import datetime
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from typing import Dict, Any, Optional, List

# Basispfade
BASE_DIR = Path(__file__).resolve().parent.parent

def get_vault_dir() -> Path:
    env_p = os.environ.get("OBSIDIAN_VAULT_PATH")
    if env_p and Path(env_p).exists():
        return Path(env_p)
    for cand in [Path("/opt/data/obsidian"), Path(r"C:\Mein Obsidian"), Path("C:/.Mein Obsidian")]:
        if cand.exists():
            return cand
    return Path(r"C:\Mein Obsidian")

def get_hermes_dir() -> Path:
    for cand in [Path("/opt/data"), Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / ".hermes"]:
        if cand.exists():
            return cand
    return Path("/opt/data")

VAULT_DIR = get_vault_dir()
HERMES_DIR = get_hermes_dir()

# LocalMemoryBridge importieren
try:
    from local_memory_bridge import LocalMemoryBridge
except ImportError:
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    from local_memory_bridge import LocalMemoryBridge


def slugify(text: str, max_len: int = 50) -> str:
    """ASCII-sicherer Slug für Ordner und Dateinamen."""
    text = (text or "").lower()
    for k, v in {'ä': 'ae', 'ö': 'oe', 'ü': 'ue', 'ß': 'ss'}.items():
        text = text.replace(k, v)
    text = re.sub(r'[^a-z0-9_-]+', '-', text)
    text = re.sub(r'-+', '-', text).strip('-')
    if len(text) > max_len:
        text = text[:max_len].rstrip('-')
    return text or "task"


def get_smtp_config() -> Dict[str, Any]:
    """Liest SMTP-Konfiguration aus der SQLite-KV-Tabelle."""
    db_candidates = [
        HERMES_DIR / "agentic_memory.db",
        BASE_DIR / "data" / "agentic_memory.db"
    ]
    for db in db_candidates:
        if db.exists():
            try:
                conn = sqlite3.connect(str(db))
                cur = conn.cursor()
                cur.execute("SELECT value FROM kv_store WHERE key = 'smtp_config'")
                row = cur.fetchone()
                conn.close()
                if row and row[0]:
                    return json.loads(row[0])
            except Exception:
                pass
    return {
        "enabled": False,
        "auto_send": False,
        "host": "",
        "port": 587,
        "username": "",
        "password": "",
        "from_email": "",
        "to_email": "",
        "use_tls": True
    }


def save_smtp_config(cfg: Dict[str, Any]) -> bool:
    """Speichert SMTP-Konfiguration in beiden SQLite-Datenbanken."""
    val = json.dumps(cfg, ensure_ascii=False)
    db_candidates = [
        HERMES_DIR / "agentic_memory.db",
        BASE_DIR / "data" / "agentic_memory.db"
    ]
    saved = False
    for db in db_candidates:
        try:
            db.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(db))
            conn.execute("CREATE TABLE IF NOT EXISTS kv_store (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            conn.execute("INSERT OR REPLACE INTO kv_store (key, value, updated_at) VALUES ('smtp_config', ?, CURRENT_TIMESTAMP)", (val,))
            conn.commit()
            conn.close()
            saved = True
        except Exception as e:
            print(f"[PostTaskPipeline] Fehler beim Speichern der SMTP-Config in {db}: {e}")
    return saved


def send_smtp_email(subject: str, text_content: str, html_content: Optional[str] = None, attachment_path: Optional[str] = None) -> Dict[str, Any]:
    """Sendet eine E-Mail über die konfigurierten SMTP-Parameter."""
    cfg = get_smtp_config()
    if not cfg.get("enabled"):
        return {"status": "skipped", "message": "SMTP ist nicht aktiviert."}

    host = cfg.get("host")
    port = int(cfg.get("port") or 587)
    user = cfg.get("username")
    pwd = cfg.get("password")
    from_addr = cfg.get("from_email") or user
    to_addr = cfg.get("to_email") or user

    if not host or not user or not to_addr:
        return {"status": "error", "message": "Unvollständige SMTP-Konfiguration."}

    try:
        msg = MIMEMultipart("mixed")
        msg["Subject"] = subject
        msg["From"] = from_addr
        msg["To"] = to_addr

        alt_part = MIMEMultipart("alternative")
        alt_part.attach(MIMEText(text_content, "plain", "utf-8"))
        if html_content:
            alt_part.attach(MIMEText(html_content, "html", "utf-8"))
        msg.attach(alt_part)

        if attachment_path and os.path.exists(attachment_path):
            with open(attachment_path, "rb") as f:
                part = MIMEApplication(f.read(), Name=os.path.basename(attachment_path))
                part['Content-Disposition'] = f'attachment; filename="{os.path.basename(attachment_path)}"'
                msg.attach(part)

        if cfg.get("use_tls", True):
            server = smtplib.SMTP(host, port, timeout=10)
            server.starttls()
        else:
            server = smtplib.SMTP_SSL(host, port, timeout=10)

        if pwd:
            server.login(user, pwd)
        server.send_message(msg)
        server.quit()
        return {"status": "success", "message": f"E-Mail erfolgreich an {to_addr} gesendet."}
    except Exception as e:
        return {"status": "error", "message": f"SMTP-Fehler: {str(e)}"}


def project_folder_name(task: dict) -> str:
    """ORDNERNAME-QUELLE DER WAHRHEIT (12.10.2026, User-Fix 'ein Projekt = ein Ordner').

    - Delegationskinder MIT parent_project_id TEILEN sich den EINEN
      Eltern-Ordner (sonst: ein Projektordner pro Subtask -> Ordnerflut).
    - Ohne parent (Einzel-Delegation): weiterhin eigener Task-Ordner.
    """
    date_prefix = datetime.date.today().strftime("%Y%m%d")
    parent_pid = str(task.get("parent_project_id") or "").strip()
    if parent_pid:
        ptitle = str(task.get("parent_project_title") or parent_pid)
        return f"{date_prefix}-{parent_pid}-{slugify(ptitle)}"
    task_id = str(task.get("id") or "task-0").strip()
    raw_title = task.get("title") or "task"
    tid_core = task_id.replace("task-", "")
    return f"{date_prefix}-{tid_core}-{slugify(raw_title)}"


def write_project_folder_artifact(task: dict) -> Dict[str, str]:
    """
    Erstellt die 3-Ordner-Struktur in C:\Mein Obsidian\Projects\<folder_name>:
    - 01_Zwischenberichte/
    - 02_Medien/
    - 03_Endprodukte/<file_name>.md
    - PROJEKT.md
    Spiegelt außerdem nach agent_workspace/builds/reports/ für den Showroom.
    """
    task_id = str(task.get("id") or "task-0").strip()
    raw_title = task.get("title") or "task"
    task_slug = slugify(raw_title)
    # User-Vorgabe 09.10.2026: "task-" wird durch das Datum (YYYYMMDD-) ersetzt,
    # Datum als Orientierungspräfix im Projektnamen (wie in Obsidian üblich).
    date_prefix = datetime.datetime.now().strftime("%Y%m%d")
    tid_core = task_id.replace("task-", "")
    # 12.10.2026 (User-Fix Ordnerflut): EIN Ordner pro Projekt - Subtasks
    # mit parent_project_id teilen sich den Eltern-Ordner.
    folder_name = project_folder_name(task)
    file_name = f"{date_prefix}-{tid_core}-{task_slug}.md"

    # User-Vorgabe 09.10.2026: Mission-Projekte gehören in 01_PROJEKTE (wie
    # Delegations-Projekte), nicht in das alte Projects/-Verzeichnis.
    proj_dir = VAULT_DIR / "01_PROJEKTE" / folder_name
    z_dir = proj_dir / "01_Zwischenberichte"
    m_dir = proj_dir / "02_Medien"
    e_dir = proj_dir / "03_Endprodukte"

    for d in (z_dir, m_dir, e_dir):
        d.mkdir(parents=True, exist_ok=True)

    today = datetime.date.today().isoformat()
    agent_id = task.get("agent_id", "hermes_default")
    agent_name = task.get("agent_name", "Hermes Agent")
    model = task.get("model", "Universal")
    tokens = task.get("estimated_tokens", 0)
    cost = task.get("estimated_cost_eur", 0.0)
    summary = task.get("result_summary") or "Erfolgreich von Archon OS ausgeführt."
    capture = task.get("capture_input") or raw_title

    doc_content = f"""---
project_id: {task_id}
date: {today}
agent: {agent_name}
agent_id: {agent_id}
model: {model}
tokens_used: {tokens}
cost_usd: ${cost:.2f}
status: completed
---
# {raw_title}

## Ursprüngliche Anforderung
{capture}

## Umsetzungsplan & Ergebnisse
{summary}

## Generierte Artefakte
- Endprodukt: [[{task_id}_{task_slug}]]
- Verzeichnis: `Projects/{folder_name}/03_Endprodukte/`

---
[[PROJEKT]] | [[00_VAULT_KNOWLEDGE]]
"""

    end_doc_path = e_dir / file_name
    end_doc_path.write_text(doc_content, encoding="utf-8")

    # PROJEKT.md anlegen
    proj_md = proj_dir / "PROJEKT.md"
    proj_content = f"""---
project_id: "{task_id}"
title: "{raw_title}"
agent: "{agent_name}"
date: "{today}"
status: "completed"
primary_document: "[[{task_id}_{task_slug}]]"
---

# 📂 Projekt: {raw_title}

- **Lead-Agent:** {agent_name} (`{agent_id}`)
- **Status:** 🟢 Abgeschlossen ({today})
- **Hauptdokument:** [[{task_id}_{task_slug}]]

### 📁 Verzeichnis-Inhalte:
- `01_Zwischenberichte/`: Arbeitsprotokolle und Entwürfe
- `02_Medien/`: Bild-, Video- und Datenquellen
- `03_Endprodukte/`: [[{task_id}_{task_slug}]]

---
[[00_VAULT_KNOWLEDGE]] | [[Archiv-Hubs]]
"""
    proj_md.write_text(proj_content, encoding="utf-8")

    # SIDE-CAR (User-Entscheidung Option A, 11.10.2026): task <-> Obsidian-
    # Projekt verknuepfen in config/kanban_meta.json (neben due/tags).
    # Die Engine-DB bleibt unberuehrt; relativer Vault-Pfad, damit die API
    # bei variabler Vault-Lage (get_vault_dir) aufloesen kann.
    try:
        meta_path = Path(__file__).resolve().parents[1] / "config" / "kanban_meta.json"
        meta = {}
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta.setdefault("tasks", {}).setdefault(task_id, {})["obsidian"] = f"01_PROJEKTE/{folder_name}"
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as meta_err:
        print(f"[PostTask] Obsidian-Sidecar fehlgeschlagen: {meta_err}", file=sys.stderr)

    # Spiegelung in Showroom-Verzeichnis
    showroom_dir = BASE_DIR / "agent_workspace" / "builds" / "reports"
    showroom_dir.mkdir(parents=True, exist_ok=True)
    showroom_file = showroom_dir / file_name
    try:
        showroom_file.write_text(doc_content, encoding="utf-8")
    except Exception as e:
        print(f"[PostTaskPipeline] Warning: Could not mirror to showroom: {e}")

    # Spiegelung in Einzelberichte (Format: YYYY-MM-DD_<agent>_<task>.md)
    einzel_dir = VAULT_DIR / "Projects" / "Einzelberichte" / "03_Endprodukte"
    einzel_dir.mkdir(parents=True, exist_ok=True)
    einzel_file_name = f"{today}_{agent_id}_{task_id}_{task_slug}.md" if task_slug != "task" else f"{today}_{agent_id}_{task_id}.md"
    einzel_file = einzel_dir / einzel_file_name
    try:
        einzel_file.write_text(doc_content, encoding="utf-8")
    except Exception as e:
        print(f"[PostTaskPipeline] Warning: Could not mirror to Einzelberichte: {e}")

    return {
        "final_doc_path": str(end_doc_path),
        "project_dir": str(proj_dir),
        "file_stem": f"{task_id}_{task_slug}",
        "file_name": file_name,
        "einzel_path": str(einzel_file)
    }


def update_agent_personalakte(agent_id: str, task_id: str, raw_title: str, file_stem: str) -> bool:
    """
    Aktualisiert die Personalakte unter C:\Mein Obsidian\00_HR_Agenten\Personalakten\{agent_id}.md:
    - Inkrementiert tasks_completed
    - Setzt last_evaluation auf heute
    - Fügt die Tabellen-Zeile unter Abschnitt 5 ein
    """
    akten_dir = VAULT_DIR / "00_HR_Agenten" / "Personalakten"
    akte_file = akten_dir / f"{agent_id}.md"

    if not akte_file.exists():
        # Fallback falls Profilname anders geschrieben ist
        candidates = list(akten_dir.glob(f"*{agent_id}*.md"))
        if candidates:
            akte_file = candidates[0]
        else:
            print(f"[PostTaskPipeline] Personalakte für '{agent_id}' nicht gefunden.")
            return False

    try:
        content = akte_file.read_text(encoding="utf-8")
        today = datetime.date.today().isoformat()

        # 1. tasks_completed hochzählen
        tc_match = re.search(r"tasks_completed:\s*(\d+)", content)
        if tc_match:
            current_tc = int(tc_match.group(1))
            # Prüfen ob der Task schon erwähnt ist
            if task_id not in content:
                new_tc = current_tc + 1
                content = re.sub(r"tasks_completed:\s*\d+", f"tasks_completed: {new_tc}", content)
        
        # 2. last_evaluation aktualisieren
        content = re.sub(r"last_evaluation:\s*[\d-]+", f"last_evaluation: {today}", content)

        # 3. Tabelleneintrag oder Linkliste in Abschnitt 5
        entry_line = f"- [[{file_stem}]] ({today} – {raw_title[:60]})"
        if task_id not in content:
            if "## 5. 📁 Erstellte Artefakte & Projekt-Historie" in content:
                parts = content.split("## 5. 📁 Erstellte Artefakte & Projekt-Historie")
                header_part = parts[0] + "## 5. 📁 Erstellte Artefakte & Projekt-Historie\n*Verknüpfte Arbeitsdokumente und Protokolle im Workspace:*\n" + entry_line + "\n"
                # Entferne doppelte Überschrift-Einleitungen
                sub_part = parts[1]
                if "*Verknüpfte Arbeitsdokumente und Protokolle im Workspace:*" in sub_part:
                    sub_part = sub_part.replace("*Verknüpfte Arbeitsdokumente und Protokolle im Workspace:*\n", "")
                content = header_part + sub_part
            else:
                content += f"\n\n## 5. 📁 Erstellte Artefakte & Projekt-Historie\n{entry_line}\n"

        akte_file.write_text(content, encoding="utf-8")
        print(f"[PostTaskPipeline] Personalakte {akte_file.name} erfolgreich aktualisiert.")
        return True
    except Exception as e:
        print(f"[PostTaskPipeline] Fehler beim Aktualisieren der Personalakte: {e}")
        return False


def extract_and_record_learning(task: dict, file_stem: str) -> Optional[dict]:
    """
    Extrahiert eine kompakte Lektion und speichert sie über die LocalMemoryBridge.
    """
    agent_id = task.get("agent_id", "hermes_default")
    raw_title = task.get("title") or "Unbenannte Aufgabe"
    summary = task.get("result_summary") or ""
    task_id = str(task.get("id") or "task-0")

    lesson_summary = f"Task #{task_id}: {raw_title[:60]} erfolgreich abgeschlossen"
    detailed_note = f"""Ergebnis und Lerneffekt aus Task #{task_id}:
- Titel: {raw_title}
- Agent: {agent_id}
- Kern-Ergebnis: {summary[:300]}

Verknüpftes Projekt:
- [[{file_stem}]]
"""

    try:
        bridge = LocalMemoryBridge(
            db_path=str(HERMES_DIR / "agentic_memory.db"),
            vault_path=str(VAULT_DIR)
        )
        res = bridge.record_learning(
            agent_id=agent_id,
            category="Projekt-Execution",
            summary=lesson_summary,
            detailed_note=detailed_note
        )

        # Auch in lokaler DB spiegeln
        local_db = BASE_DIR / "data" / "agentic_memory.db"
        if local_db.exists():
            try:
                conn = sqlite3.connect(str(local_db))
                conn.execute("""
                    INSERT INTO learnings (agent_id, category, summary, obsidian_link)
                    VALUES (?, ?, ?, ?)
                """, (agent_id, "Projekt-Execution", lesson_summary, res.get("obsidian_link")))
                conn.commit()
                conn.close()
            except Exception:
                pass

        print(f"[PostTaskPipeline] Learning erfasst: {res.get('obsidian_link')}")
        return res
    except Exception as e:
        print(f"[PostTaskPipeline] Fehler bei Learning-Extraktion: {e}")
        return None


def sync_paperclip_completion(task: dict, artifact_path: str) -> bool:
    """
    Setzt in Paperclip den Issue-Status auf completed und hängt das Endprodukt an.
    """
    pc_issue = task.get("paperclip_issue") or {}
    issue_id = pc_issue.get("id") or ""
    title = (task.get("title") or "")[:30].replace("'", "").replace('"', "")
    clean_art_path = artifact_path.replace("\\", "/")

    # Node-Skript via docker exec ausführen
    script = f"""
const postgres = require('/app/node_modules/.pnpm/postgres@3.4.9/node_modules/postgres');
async function run() {{
  const sql = postgres('postgresql://paperclip:paperclip@127.0.0.1:54329/paperclip');
  let targetId = '{issue_id}';
  
  if (!targetId) {{
    const rows = await sql.unsafe("SELECT id FROM issues WHERE title LIKE '%{title}%' LIMIT 1");
    if (rows.length > 0) targetId = rows[0].id;
  }}
  
  if (targetId) {{
    await sql.unsafe("UPDATE issues SET status = 'completed', updated_at = NOW() WHERE id = '" + targetId + "'");
    try {{
      await sql.unsafe("INSERT INTO issue_work_products (id, issue_id, kind, label, path, created_at) VALUES (gen_random_uuid(), '" + targetId + "', 'document', 'Finales Endprodukt', '{clean_art_path}', NOW())");
    }} catch(e) {{}}
    await sql.unsafe("INSERT INTO issue_comments (id, issue_id, author_type, body, created_at, updated_at) VALUES (gen_random_uuid(), '" + targetId + "', 'system', 'Post-Task-Pipeline: Auftrag erfolgreich abgeschlossen und in Obsidian Projects abgelegt.', NOW(), NOW())");
    console.log('Paperclip issue ' + targetId + ' marked completed.');
  }} else {{
    console.log('No matching Paperclip issue found.');
  }}
  process.exit(0);
}}
run();
"""
    try:
        import base64
        import httpx
        import json
        b64 = base64.b64encode(script.encode("utf-8")).decode("utf-8")
        payload = {
            "AttachStdout": True,
            "AttachStderr": True,
            "Cmd": ["node", "-e", f"eval(Buffer.from('{b64}', 'base64').toString('utf8'))"]
        }
        resp = httpx.post("http://docker-socket-proxy:2375/containers/paperclip-orchestrator/exec", json=payload, timeout=5.0)
        if resp.status_code == 201:
            exec_id = resp.json().get("Id")
            if exec_id:
                start_resp = httpx.post(f"http://docker-socket-proxy:2375/exec/{exec_id}/start", json={"Detach": False, "Tty": False}, timeout=10.0)
                return "marked completed" in start_resp.text
        return False
    except Exception as e:
        pass  # print(f"[PostTaskPipeline] Paperclip-Sync Warnung: {e}")
        return False


def execute_post_task_pipeline(task: dict) -> Dict[str, Any]:
    """
    Führt die gesamte Kette nach Task-Fertigstellung aus:
    1. Obsidian 3-Ordner-Struktur + PROJEKT.md + Showroom Mirror
    2. Personalakten-Aktualisierung
    3. Self-Improvement Lerneffekt
    4. Paperclip-Status-Schließung
    5. E-Mail-Versand (sofern aktiv)
    """
    raw_title = task.get("title") or "Ohne Titel"
    agent_id = task.get("agent_id", "hermes_default")
    agent_name = task.get("agent_name", "Hermes Agent")

    # 1. Datei- und Projektstruktur anlegen
    file_info = write_project_folder_artifact(task)
    final_path = file_info["final_doc_path"]
    file_stem = file_info["file_stem"]

    # 2. Personalakte aktualisieren
    update_agent_personalakte(agent_id, str(task.get("id")), raw_title, file_stem)

    # 3. Learning extrahieren
    learning_res = extract_and_record_learning(task, file_stem)

    # 4. Paperclip synchronisieren
    sync_paperclip_completion(task, final_path)

    # 5. E-Mail prüfen und versenden
    smtp_cfg = get_smtp_config()
    email_res = None
    if smtp_cfg.get("enabled") and smtp_cfg.get("auto_send"):
        subject = f"✅ Archon OS: Task abgeschlossen – {raw_title[:50]}"
        text_body = f"""Hallo Michael,

der Agent {agent_name} ({agent_id}) hat folgenden Task erfolgreich abgeschlossen:

Projekt: {raw_title}
Status: 🟢 Abgeschlossen
Endprodukt: {final_path}

Zusammenfassung:
{task.get('result_summary', 'Keine Zusammenfassung')}

---
Archon OS Autonomous Engine
"""
        html_body = f"""
        <div style="font-family: sans-serif; line-height: 1.5; color: #1e293b;">
            <h2 style="color: #0f172a;">✅ Task erfolgreich abgeschlossen</h2>
            <p><strong>Projekt:</strong> {raw_title}</p>
            <p><strong>Verantwortlicher Agent:</strong> {agent_name} (<code>{agent_id}</code>)</p>
            <div style="background: #f8fafc; border: 1px solid #e2e8f0; padding: 15px; border-radius: 8px; margin: 15px 0;">
                <h3 style="margin-top: 0;">Ergebnis-Zusammenfassung:</h3>
                <p style="white-space: pre-wrap;">{task.get('result_summary', 'Keine Zusammenfassung')}</p>
            </div>
            <p style="font-size: 12px; color: #64748b;">Gespeichert im Obsidian Vault unter <code>{final_path}</code></p>
        </div>
        """
        email_res = send_smtp_email(subject, text_body, html_body, final_path)

    return {
        "status": "success",
        "final_path": final_path,
        "project_dir": file_info["project_dir"],
        "file_stem": file_stem,
        "learning": learning_res,
        "email": email_res
    }
