import re

with open(r"C:\.Antigravity-projekte\AgenticOS-2026\static_v2\index.html", "r", encoding="utf-8") as f:
    c = f.read()

out = []
out.append("=== HEADERS ===")
matches = re.finditer(r'^\s*// =+\s*\n\s*// (.*?)\s*\n\s*// =+', c, re.MULTILINE)
for m in matches:
    out.append(f"Pos: {m.start()} | Text: {m.group(1)}")

out.append("\n--- HEADERS ---")
matches2 = re.finditer(r'^\s*// ---\s+(.*?)\s+---', c, re.MULTILINE)
for m in matches2:
    out.append(f"Pos: {m.start()} | Text: {m.group(1)}")

with open(r"C:\.Antigravity-projekte\AgenticOS-2026\js_map.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out))
