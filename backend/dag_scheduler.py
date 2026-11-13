"""
DAG-Scheduler für Archon OS (Pillar 2 / Prozessmodell & Parallele Multi-Agenten-Ausführung)
Zerlegt komplexe Großaufgaben (Epics) in Directed Acyclic Graphs (DAGs), führt unabhängige
Teilaufgaben parallel aus und fasst die Ergebnisse in einer abschließenden Synthese zusammen.
"""

import os
import sys
import json
import uuid
import asyncio
import datetime
import sqlite3
from typing import List, Dict, Optional, Any

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KANBAN_DB = "/opt/data/kanban.db" if os.path.exists("/opt/data/kanban.db") else os.path.expanduser("~/.hermes/kanban.db")

class DAGScheduler:
    def __init__(self):
        self.workspace_dir = WORKSPACE_DIR

    def _get_kanban_conn(self):
        conn = sqlite3.connect(KANBAN_DB, timeout=10.0)
        conn.execute("PRAGMA busy_timeout=5000;")
        conn.row_factory = sqlite3.Row
        return conn

    async def decompose_task(self, parent_title: str, parent_body: str, assignee: str = "orchestrator", task_id: Optional[str] = None) -> dict:
        """
        Zerlegt eine komplexe Aufgabe über den Orchestrator in 2-4 Teilaufgaben mit Abhängigkeiten.
        """
        import core_dispatcher
        decompose_prompt = f"""Du bist der System-Architekt & DAG-Planer von Archon OS.
Zerlege folgende Gesamtaufgabe in 2 bis maximal 4 logische, spezialisierte Teilaufgaben:
TITEL: {parent_title}
BESCHREIBUNG: {parent_body}

Regeln:
1. Erstelle 2-3 unabhängige Recherche- oder Umsetzungsaufgaben (Tier 1, keine Abhängigkeiten).
2. Erstelle 1 finale Synthese-/Integrationsaufgabe (Tier 2), die von den vorherigen Aufgaben abhängt.
3. Weise jede Aufgabe einem passenden Agenten zu (z.B. 'hermes-researcher', 'hermes-coder', 'executive_decision_architect').
4. Antworte AUSSCHLIESSLICH als valides JSON-Array im folgenden Format:
[
  {{"id_suffix": "1", "title": "...", "body": "...", "assignee": "hermes-researcher", "depends_on": []}},
  {{"id_suffix": "2", "title": "...", "body": "...", "assignee": "hermes-coder", "depends_on": []}},
  {{"id_suffix": "syn", "title": "Synthese & Endbericht", "body": "...", "assignee": "hermes-orchestrator", "depends_on": ["1", "2"]}}
]"""

        tid = task_id or f"decomp-{uuid.uuid4().hex[:8]}"
        res = await core_dispatcher.dispatch_to_omniroute_or_container(
            agent_id=assignee or "orchestrator",
            agent_name="Master Orchestrator",
            prompt=decompose_prompt,
            role="System-Architekt",
            system_prompt="Du bist der Chefplaner. Gib nur JSON aus.",
            model="deepseek/deepseek-chat",
            task_id=tid
        )

        content = res.get("content", "")
        clean_json = content
        if "```json" in clean_json:
            clean_json = clean_json.split("```json")[1].split("```")[0].strip()
        elif "```" in clean_json:
            clean_json = clean_json.split("```")[1].split("```")[0].strip()

        try:
            subtasks_spec = json.loads(clean_json)
        except Exception:
            subtasks_spec = [
                {"id_suffix": "1", "title": f"Recherche & Voranalyse zu '{parent_title}'", "body": parent_body, "assignee": "hermes-researcher", "depends_on": []},
                {"id_suffix": "syn", "title": f"Synthese & Umsetzung für '{parent_title}'", "body": "Führe die Ergebnisse zusammen.", "assignee": "hermes-orchestrator", "depends_on": ["1"]}
            ]

        # In kanban.db eintragen
        parent_id = f"dag-{datetime.datetime.now().strftime('%m%d%H%M%S')}-{uuid.uuid4().hex[:4]}"
        created_subtasks = []

        conn = self._get_kanban_conn()
        try:
            now_iso = datetime.datetime.now().isoformat()
            # 1. Parent Task
            conn.execute("""
                INSERT INTO tasks (id, title, body, assignee, status, priority, created_by, created_at)
                VALUES (?, ?, ?, ?, 'in_progress', 3, 'DAG-Scheduler', ?)
            """, (parent_id, f"[DAG-EPIC] {parent_title}", parent_body, assignee or "orchestrator", now_iso))

            # 2. Subtasks
            for spec in subtasks_spec:
                cid = f"{parent_id}-{spec.get('id_suffix', 'sub')}"
                deps = spec.get("depends_on", [])
                full_deps = [f"{parent_id}-{d}" for d in deps]
                task_body = spec.get("body", "") + f"\n\n[Parent: {parent_id}] [DependsOn: {json.dumps(full_deps)}]"
                
                conn.execute("""
                    INSERT INTO tasks (id, title, body, assignee, status, priority, created_by, created_at)
                    VALUES (?, ?, ?, ?, 'todo', 2, 'DAG-Scheduler', ?)
                """, (cid, spec.get("title"), task_body, spec.get("assignee", "hermes-researcher"), now_iso))

                created_subtasks.append({
                    "id": cid,
                    "title": spec.get("title"),
                    "assignee": spec.get("assignee"),
                    "depends_on": full_deps
                })

            conn.commit()
        finally:
            conn.close()

        return {
            "status": "success",
            "parent_id": parent_id,
            "title": parent_title,
            "subtasks": created_subtasks,
            "count": len(created_subtasks)
        }

    async def execute_dag(self, parent_id: str) -> dict:
        """
        Führt einen DAG aus: Unabhängige Tasks parallel, danach abhängige Tasks und abschließende Synthese.
        """
        import core_dispatcher
        conn = self._get_kanban_conn()
        subtasks = []
        try:
            cur = conn.cursor()
            cur.execute("SELECT id, title, body, assignee, status FROM tasks WHERE id LIKE ? AND id != ?", (f"{parent_id}-%", parent_id))
            subtasks = [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

        if not subtasks:
            return {"status": "error", "message": f"Keine Teilaufgaben für {parent_id} gefunden."}

        # Trenne in Stufen (Stufe 1: ohne Abhängigkeiten, Stufe 2: mit Abhängigkeiten)
        tier1 = []
        tier2 = []
        for t in subtasks:
            body = t.get("body", "")
            if "[DependsOn:" in body and "[DependsOn: []" not in body:
                tier2.append(t)
            else:
                tier1.append(t)

        results = {}

        # 1. Stufe 1: Parallele Ausführung
        async def _run_task(task_item):
            t_id = task_item["id"]
            res = await core_dispatcher.dispatch_to_omniroute_or_container(
                agent_id=task_item.get("assignee", "hermes-researcher"),
                agent_name=task_item.get("assignee", "Agent"),
                prompt=f"Führe folgende Teilaufgabe präzise aus:\nTITEL: {task_item['title']}\nAUFTRAG: {task_item['body']}",
                role="Fach-Spezialist",
                model="deepseek/deepseek-chat",
                task_id=t_id
            )
            out_text = res.get("content", "")
            # Update kanban task status
            c = self._get_kanban_conn()
            try:
                c.execute("UPDATE tasks SET status = 'done', result = ? WHERE id = ?", (out_text, t_id))
                c.commit()
            finally:
                c.close()
            return t_id, out_text

        tier1_runs = await asyncio.gather(*[_run_task(t) for t in tier1])
        for tid, tout in tier1_runs:
            results[tid] = tout

        # M-09: final_report ist nur in der tier2-Schleife gebunden. Besteht ein
        # DAG nur aus Stufe-1-Tasks, warf die Variable danach UnboundLocalError —
        # Ergebnisse wurden verworfen, der Eltern-Task blieb in_progress.
        final_report = ""
        # 2. Stufe 2: Synthese mit den Ergebnissen aus Stufe 1
        tier1_context = "\n\n".join([f"### [ERGEBNIS {tid}]:\n{tout}" for tid, tout in results.items()])
        for t in tier2:
            t_id = t["id"]
            synth_prompt = (
                f"Führe die finale Synthese für die Gesamtaufgabe aus:\n"
                f"AUFTRAG: {t['title']}\n\n"
                f"VORLIEGENDE ERGEBNISSE DER TEILAUFGABEN:\n{tier1_context}\n\n"
                f"Erstelle einen vollständigen, fundierten Abschlussbericht im Markdown-Format."
            )
            res_synth = await core_dispatcher.dispatch_to_omniroute_or_container(
                agent_id=t.get("assignee", "hermes-orchestrator"),
                agent_name="Master Orchestrator",
                prompt=synth_prompt,
                role="System-Architekt & Synthesizer",
                model="deepseek/deepseek-chat",
                task_id=f"{parent_id}-syn"
            )
            final_report = res_synth.get("content", "")
            results[t_id] = final_report

            c = self._get_kanban_conn()
            try:
                c.execute("UPDATE tasks SET status = 'done', result = ? WHERE id = ?", (final_report, t_id))
                c.execute("UPDATE tasks SET status = 'done', result = ? WHERE id = ?", (final_report, parent_id))
                c.commit()
            finally:
                c.close()

        # M-09: Besteht der DAG nur aus Stufe-1-Tasks, ist die Synthese aus den
        # gesammelten Stufe-1-Ergebnissen der Abschlussbericht — sonst wuerden
        # die bezahlten Ergebnisse verworfen.
        if not final_report and results:
            final_report = "\n\n".join(f"### [ERGEBNIS {tid}]:\n{tout}" for tid, tout in results.items())

        # In Obsidian Vault sichern
        if final_report:
            try:
                vault_dir = os.path.join(self.workspace_dir, "agent_workspace", "obsidian_vault", "01_PROJEKTE", parent_id)
                os.makedirs(vault_dir, exist_ok=True)
                report_file = os.path.join(vault_dir, "03_Endprodukte", f"Abschlussbericht_{parent_id}.md")
                os.makedirs(os.path.dirname(report_file), exist_ok=True)
                with open(report_file, "w", encoding="utf-8") as rf:
                    rf.write(final_report)
            except Exception:
                pass
            # Eltern-Task auch ohne Stufe-2-Synthese als done markieren (M-09):
            # vorher passierte das nur in der tier2-Schleife.
            try:
                c = self._get_kanban_conn()
                try:
                    c.execute("UPDATE tasks SET status = 'done', result = ? WHERE id = ?", (final_report, parent_id))
                    c.commit()
                finally:
                    c.close()
            except Exception:
                pass

        return {
            "status": "success",
            "parent_id": parent_id,
            "total_tasks_completed": len(subtasks),
            "final_report_preview": final_report[:500] + "..." if len(final_report) > 500 else final_report
        }

dag_scheduler_instance = DAGScheduler()


dag_scheduler = dag_scheduler_instance
