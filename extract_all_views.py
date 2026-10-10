import os
import re

file_path = r"C:\.Antigravity-projekte\AgenticOS-2026\static_v2\index.html"
views_dir = r"C:\.Antigravity-projekte\AgenticOS-2026\static_v2\views"
os.makedirs(views_dir, exist_ok=True)

with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

views_to_extract = [
    "view-operations",
    "view-library",
    "view-inbox",
    "view-showroom",
    "view-guardian",
    "view-plugins",
    "view-research",
    "view-brain",
    "view-design-system"
]

total_lines_removed = 0
init_replacements = []

for view_id in views_to_extract:
    start_str = f'      <div id="{view_id}"'
    start_idx = content.find(start_str)
    
    if start_idx == -1:
        print(f"Could not find {view_id}")
        continue
        
    # Find next view by looking for `<div id="view-` after start_idx + 10
    next_view_idx = content.find('      <div id="view-', start_idx + 10)
    
    if next_view_idx == -1:
        # If it's the last view, find the end of the views container or body
        next_view_idx = content.find('    </main>', start_idx)
        
    actual_end_idx = content.rfind('      </div>', start_idx, next_view_idx) + 12
    
    extracted_html = content[start_idx:actual_end_idx].strip()
    lines_removed = extracted_html.count('\n')
    total_lines_removed += lines_removed
    
    # Save to file
    with open(os.path.join(views_dir, f"{view_id.replace('-', '_')}.html"), "w", encoding="utf-8") as f:
        f.write(extracted_html)
        
    # Replace in content
    replacement = f'      <!-- VIEW: {view_id.upper()} (Extracted) -->\n      <div id="{view_id}-mount"></div>\n'
    content = content[:start_idx] + replacement + content[actual_end_idx:]
    
    init_replacements.append(f'''
      try {{
        const res = await fetch('/static_v2/views/{view_id.replace('-', '_')}.html');
        const html = await res.text();
        const mount = document.getElementById('{view_id}-mount');
        if(mount) mount.outerHTML = html;
      }} catch(e) {{ console.error("Failed to load {view_id}", e); }}
''')
    
    print(f"Extracted {view_id}: {lines_removed} lines.")

# Inject all fetch loaders
init_str = '// Load Master Chat View Component'
if init_str in content:
    content = content.replace(init_str, "".join(init_replacements) + "\n      " + init_str)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)

print(f"Total lines removed from main file: {total_lines_removed}")
