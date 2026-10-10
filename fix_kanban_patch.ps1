$path = "c:\.Antigravity-projekte\AgenticOS-2026\main.py"
$content = Get-Content $path -Raw
# Strip the patch route
$content = $content -replace '(?s)@app\.patch\("/api/operations/kanban/tasks/\{task_id\}/status"\).*?return \{"status": "ok", "task_id": task_id, "new_status": status_update\.status\}', ''

[IO.File]::WriteAllText($path, $content)
