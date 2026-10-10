import os

p = 'c:\\.Antigravity-projekte\\AgenticOS-2026\\main.py'
with open(p, 'r', encoding='utf-8') as f:
    c = f.read()

start = c.find('class OSKanbanTaskStatusUpdate(BaseModel):')
if start != -1:
    end = c.find('return {"status": "ignored"}', start)
    if end != -1:
        c = c[:start-30] + c[end+28:]
        with open(p, 'w', encoding='utf-8') as f:
            f.write(c)
        print("Removed PATCH.")
    else:
        print("End not found")
else:
    print("Start not found")
