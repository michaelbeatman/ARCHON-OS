import re

file_path = r"C:\.Antigravity-projekte\AgenticOS-2026\static_v2\index.html"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

scripts = re.findall(r'<script>(.*?)</script>', content, re.DOTALL)
with open("test_syntax.js", "w", encoding="utf-8") as f:
    for script in scripts:
        f.write(script + "\n")
print("Extracted JS")
