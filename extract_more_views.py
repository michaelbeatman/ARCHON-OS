import os
import re

file_path = r"C:\.Antigravity-projekte\AgenticOS-2026\static_v2\index.html"
views_dir = r"C:\.Antigravity-projekte\AgenticOS-2026\static_v2\views"
os.makedirs(views_dir, exist_ok=True)

with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

views_to_extract = [
    "view-showroom",
    "view-guardian",
    "view-plugins",
    "view-research",
    "view-brain"
]

total_lines_removed = 0
init_replacements = []

for view_id in views_to_extract:
    start_str = f'      <div id="{view_id}"'
    start_idx = content.find(start_str)
    
    if start_idx == -1:
        print(f"Could not find {view_id}")
        continue
        
    next_view_idx = content.find('      <div id="view-', start_idx + 10)
    
    if next_view_idx == -1:
        print(f"Could not find next view for {view_id}")
        continue
        
    actual_end_idx = content.rfind('      </div>', start_idx, next_view_idx) + 12
    
    extracted_html = content[start_idx:actual_end_idx].strip()
    lines_removed = extracted_html.count('\n')
    total_lines_removed += lines_removed
    
    with open(os.path.join(views_dir, f"{view_id.replace('-', '_')}.html"), "w", encoding="utf-8") as f:
        f.write(extracted_html)
        
    replacement = f'      <!-- VIEW: {view_id.upper()} (Extracted) -->\n      <div id="{view_id}-mount"></div>\n'
    content = content[:start_idx] + replacement + content[actual_end_idx:]
    
    init_replacements.append(f'''
          fetch('/static_v2/views/{view_id.replace('-', '_')}.html').then(r => r.text()).then(html => {{ const el = document.getElementById('{view_id}-mount'); if (el) el.outerHTML = html; }}),
''')
    
    print(f"Extracted {view_id}: {lines_removed} lines.")

# Inject all fetch loaders into Promise.all([
target = "fetch('/static_v2/views/inbox_view.html').then(r => r.text()).then(html => { const el = document.getElementById('view-inbox-mount'); if (el) el.outerHTML = html; })"
if target in content:
    content = content.replace(target, target + ",\n" + "".join(init_replacements).strip().rstrip(","))

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)

print(f"Total lines removed from HTML: {total_lines_removed}")
