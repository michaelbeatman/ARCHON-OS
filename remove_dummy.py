import re
with open("main.py", "r", encoding="utf-8") as f:
    content = f.read()
content = re.sub(r'(?s)@app\.get\("/api/operations/kanban/tasks"\).*?return \{"total_tasks": len\(tasks\), "columns": cols\}', '', content)
content = re.sub(r'(?s)class OSKanbanTaskStatusUpdate.*?return \{"success": True, "message": f"Archived \{task_id\}"\}', '', content)
content = re.sub(r'(?s)@app\.patch\("/api/operations/kanban/tasks/\{task_id\}/status"\).*?return \{"success": True\}', '', content)
with open("main.py", "w", encoding="utf-8") as f:
    f.write(content)
