import os

code_to_add = '''
from pydantic import BaseModel
class OSKanbanTaskStatusUpdate(BaseModel):
    status: str

@app.get("/api/operations/kanban/tasks")
async def get_operations_kanban_tasks():
    mc_data = _load_mission_control_data()
    tasks = mc_data.get("tasks", []) if mc_data else []
    
    cols = {
        "triage": [],
        "todo": [],
        "ready": [],
        "in_progress": [],
        "review": [],
        "done": []
    }
    
    for t in tasks:
        st = t.get("status", "pending")
        col_id = "todo"
        if st == "pending": col_id = "todo"
        elif st == "approval": col_id = "review"
        elif st == "in_progress": col_id = "in_progress"
        elif st in ("done", "completed"): col_id = "done"
        elif st == "failed": col_id = "triage"
        
        pri = 2
        p_str = str(t.get("priority", "normal")).lower()
        if "high" in p_str: pri = 3
        elif "low" in p_str: pri = 1
        
        kt = {
            "id": t.get("id", "task-???"),
            "title": t.get("title", "Untitled Task"),
            "priority": pri,
            "assignee_name": t.get("agent_name", "System"),
            "assignee_avatar": t.get("avatar", "/static/avatars/avatar_001.jpg"),
            "model_override": t.get("model", "")
        }
        cols[col_id].append(kt)
        
    return {
        "total_tasks": len(tasks),
        "columns": cols
    }

@app.patch("/api/operations/kanban/tasks/{task_id}/status")
async def patch_operations_kanban_task(task_id: str, req: OSKanbanTaskStatusUpdate):
    if req.status == "archived":
        archive_file = os.path.join(MEMORY_DIR, "archived_tasks.json")
        archived = []
        if os.path.exists(archive_file):
            try:
                with open(archive_file, "r") as f:
                    archived = json.load(f)
            except: pass
        if task_id not in archived:
            archived.append(task_id)
        with open(archive_file, "w") as f:
            json.dump(archived, f)
        return {"status": "success"}
    return {"status": "ignored"}
'''

p = 'c:\\.Antigravity-projekte\\AgenticOS-2026\\main.py'
with open(p, 'r', encoding='utf-8') as f:
    c = f.read()

target = "def _load_mission_control_data() -> dict:"
if target in c:
    c = c.replace(target, code_to_add + "\n" + target)
    with open(p, 'w', encoding='utf-8') as f:
        f.write(c)
    print("Kanban API restored!")
else:
    print("Target not found")
