$path = "c:\.Antigravity-projekte\AgenticOS-2026\main.py"
$content = Get-Content $path -Raw
# Strip the kanban override block from main.py
$content = $content -replace '(?s)# =====================================================================\r?\n@app\.get\("/api/operations/kanban/tasks"\).*?from pydantic import BaseModel', 'from pydantic import BaseModel'

[IO.File]::WriteAllText($path, $content)
