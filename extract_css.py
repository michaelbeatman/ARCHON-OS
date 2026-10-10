import os
import re

file_path = r"C:\.Antigravity-projekte\AgenticOS-2026\static_v2\index.html"
css_dir = r"C:\.Antigravity-projekte\AgenticOS-2026\static_v2\css"
os.makedirs(css_dir, exist_ok=True)

with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

start_str = "<style>"
end_str = "</style>"
start_idx = content.find(start_str)

if start_idx != -1:
    end_idx = content.find(end_str, start_idx) + len(end_str)
    
    # We strip out the actual <style> and </style> tags for the CSS file
    css_content = content[start_idx + len(start_str):end_idx - len(end_str)].strip()
    
    css_file = os.path.join(css_dir, "themes.css")
    with open(css_file, "w", encoding="utf-8") as f:
        f.write(css_content)
        
    replacement = '<link rel="stylesheet" href="/static_v2/css/themes.css">\n'
    content = content[:start_idx] + replacement + content[end_idx:]
    
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
        
    print(f"Extracted {len(css_content)} bytes of CSS!")
else:
    print("Could not find <style>")
