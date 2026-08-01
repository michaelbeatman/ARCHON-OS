import os
import shutil
import asyncio
import json
from typing import Dict, Any, List, Optional

class VirtualBranchFS:
    def __init__(self, base_dir: str, branch_id: str, sandbox_parent: str = "./agent_workspace/sandbox"):
        self.base_dir = os.path.abspath(base_dir)
        self.branch_id = branch_id
        self.sandbox_dir = os.path.abspath(os.path.join(sandbox_parent, f"branch_{branch_id}"))
        
        os.makedirs(self.base_dir, exist_ok=True)
        os.makedirs(self.sandbox_dir, exist_ok=True)

    def read_file(self, rel_path: str) -> str:
        """
        Lese-Operation mit Fallback-Logik (CoW).
        """
        sandbox_path = os.path.join(self.sandbox_dir, rel_path)
        base_path = os.path.join(self.base_dir, rel_path)

        # 1. Delta-Layer hat Vorrang
        if os.path.exists(sandbox_path):
            with open(sandbox_path, "r", encoding="utf-8") as f:
                return f.read()

        # 2. Fallback auf Hauptverzeichnis
        if os.path.exists(base_path):
            with open(base_path, "r", encoding="utf-8") as f:
                return f.read()

        raise FileNotFoundError(f"Datei {rel_path} weder im Delta-Layer noch im Hauptverzeichnis gefunden.")

    def write_file(self, rel_path: str, content: str):
        """
        Schreib-Operation isoliert im Delta-Layer (CoW).
        """
        sandbox_path = os.path.join(self.sandbox_dir, rel_path)
        os.makedirs(os.path.dirname(sandbox_path), exist_ok=True)
        
        with open(sandbox_path, "w", encoding="utf-8") as f:
            f.write(content)

    def commit(self):
        """
        Mergt alle Änderungen aus dem Delta-Layer atomar in das Hauptverzeichnis.
        """
        if not os.path.exists(self.sandbox_dir):
            return

        for root, dirs, files in os.walk(self.sandbox_dir):
            for file in files:
                sandbox_file = os.path.join(root, file)
                rel_path = os.path.relpath(sandbox_file, self.sandbox_dir)
                base_file = os.path.join(self.base_dir, rel_path)
                
                os.makedirs(os.path.dirname(base_file), exist_ok=True)
                shutil.copy2(sandbox_file, base_file)

        self.abort()

    def abort(self):
        """
        Löscht das Delta-Verzeichnis rückstandslos (Rollback).
        """
        if os.path.exists(self.sandbox_dir):
            shutil.rmtree(self.sandbox_dir)


class BranchManager:
    def __init__(self, base_dir: str, storage):
        self.base_dir = base_dir
        self.storage = storage

    def fork_siblings(self, parent_task_id: str, count: int) -> List[str]:
        """
        Erstellt N parallele Geschwister-Zweige (Delta-Ebenen).
        Speichert die Mappings im KV-Store ab.
        """
        sibling_ids = []
        for i in range(count):
            branch_id = f"{parent_task_id}_branch_{i}"
            sibling_ids.append(branch_id)
            
            # VirtualBranchFS initialisieren
            VirtualBranchFS(self.base_dir, branch_id)

        # Registriere Sibling-Verweise im KV-Store
        self.storage.set_kv(f"siblings_{parent_task_id}", {"branches": sibling_ids})
        return sibling_ids

    def commit_first_wins(self, parent_task_id: str, winning_branch_id: str, scheduler) -> bool:
        """
        Erster Zweig, der committet, gewinnt.
        Alle anderen Zweige (Siblings) werden invalidiert, deren Tasks beendet und Deltas gelöscht.
        """
        lock_key = f"committed_{parent_task_id}"
        
        # 1. Prüfe Lock (First-Commit-Wins)
        already_committed = self.storage.get_kv(lock_key)
        if already_committed:
            print(f"[BranchFS] Commit rejected for {winning_branch_id}. Sibling {already_committed} already won.")
            return False

        # 2. Lock setzen und Commit ausführen
        self.storage.set_kv(lock_key, winning_branch_id)
        
        winner_fs = VirtualBranchFS(self.base_dir, winning_branch_id)
        winner_fs.commit()
        print(f"[BranchFS] Sibling {winning_branch_id} committed successfully. Sibling Invalidation triggered...")

        # 3. Sibling Invalidation
        siblings_data = self.storage.get_kv(f"siblings_{parent_task_id}")
        sibling_ids = siblings_data.get("branches", []) if siblings_data else []

        for b_id in sibling_ids:
            if b_id == winning_branch_id:
                continue

            # a. Breche Delta-Layer ab
            sibling_fs = VirtualBranchFS(self.base_dir, b_id)
            sibling_fs.abort()

            # b. Breche asynchrone Tasks im Scheduler ab
            if scheduler and b_id in scheduler.active_tasks:
                task_obj = scheduler.active_tasks.get(b_id)
                if task_obj:
                    try:
                        # Thread-sicherer Abbruch
                        loop = task_obj.get_loop()
                        loop.call_soon_threadsafe(task_obj.cancel)
                    except Exception:
                        task_obj.cancel()
                    print(f"[BranchFS] Cancelled sibling task process: {b_id}")

            # c. Setze Status in DB auf failed (Rollback)
            self.storage.save_task(
                task_id=b_id,
                agent_id="system",
                status="failed",
                result={"error": "SIBLING_INVALIDATION_ROLLBACK"}
            )
            print(f"[BranchFS] Invalidated sibling task database entry: {b_id}")

        return True
