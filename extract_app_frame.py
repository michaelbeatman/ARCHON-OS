import os
import re

file_path = r"C:\.Antigravity-projekte\AgenticOS-2026\static_v2\index.html"
views_dir = r"C:\.Antigravity-projekte\AgenticOS-2026\static_v2\views"

with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

match1 = re.search(r'\s*<!-- =+ -->\s*\n\s*<!-- ARCHON VISUAL CSS LIVE STUDIO', content)
if not match1:
    # Try just the text
    match1 = re.search(r'\s*<!-- ARCHON VISUAL CSS LIVE STUDIO', content)

match2 = re.search(r'\s*<!-- SIDEBAR -->', content)

if match1 and match2:
    start_idx = match1.start()
    end_idx = match2.start()
    
    extracted_html = content[start_idx:end_idx].strip()
    lines_removed = extracted_html.count('\n')
    
    with open(os.path.join(views_dir, "view_app_frame_studio.html"), "w", encoding="utf-8") as f:
        f.write(extracted_html)
        
    replacement = '\n      <!-- VIEW: APP FRAME STUDIO (Extracted) -->\n      <div id="view-app-frame-studio-mount"></div>\n\n'
    content = content[:start_idx] + replacement + content[end_idx:]
    
    target = "fetch('/static_v2/views/inbox_view.html').then(r => r.text()).then(html => { const el = document.getElementById('view-inbox-mount'); if (el) el.outerHTML = html; }),"
    fetch_str = "          fetch('/static_v2/views/view_app_frame_studio.html').then(r => r.text()).then(html => { const el = document.getElementById('view-app-frame-studio-mount'); if (el) el.outerHTML = html; }),\n"
    
    if target in content and "view_app_frame_studio.html" not in content:
        content = content.replace(target, target + "\n" + fetch_str)
        
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"Extracted App Frame Studio! Removed {lines_removed} lines.")
else:
    print(f"match1: {bool(match1)}, match2: {bool(match2)}")
