import os
import sys

file_path = r"C:\.Antigravity-projekte\AgenticOS-2026\static_v2\index.html"
views_dir = r"C:\.Antigravity-projekte\AgenticOS-2026\static_v2\views"

with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

view_id = "view-design-system"
start_str = f'      <div id="{view_id}"'
start_idx = content.find(start_str)

if start_idx != -1:
    end_idx = content.find('    </main>', start_idx)
    actual_end_idx = content.rfind('      </div>', start_idx, end_idx) + 12
    extracted_html = content[start_idx:actual_end_idx].strip()
    
    out_file = os.path.join(views_dir, "view_design_system.html")
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(extracted_html)
        
    replacement = f'      <!-- VIEW: {view_id.upper()} (Extracted) -->\n      <div id="{view_id}-mount"></div>\n'
    content = content[:start_idx] + replacement + content[actual_end_idx:]
    
    # Inject fetch loader
    target = "fetch('/static_v2/views/inbox_view.html').then(r => r.text()).then(html => { const el = document.getElementById('view-inbox-mount'); if (el) el.outerHTML = html; }),"
    fetch_str = f"          fetch('/static_v2/views/view_design_system.html').then(r => r.text()).then(html => {{ const el = document.getElementById('{view_id}-mount'); if (el) el.outerHTML = html; }}),\n"
    
    if target in content and "view_design_system.html" not in content:
        content = content.replace(target, target + "\n" + fetch_str)
        
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"Done! Wrote {len(extracted_html)} bytes to {out_file}")
else:
    print("Already extracted!")
