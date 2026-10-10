import os

file_path = r'C:\.Antigravity-projekte\AgenticOS-2026\static_v2\index.html'
with open(file_path, 'r', encoding='utf8') as f:
    content = f.read()

anchor = "fetch('/static_v2/views/view_brain.html').then(r => r.text()).then(html => { const el = document.getElementById('view-brain-mount'); if (el) el.outerHTML = html; })"
if anchor in content:
    replacement = anchor + """,
          fetch('/static_v2/views/view_design_system.html').then(r => r.text()).then(html => { const el = document.getElementById('view-design-system-mount'); if (el) el.outerHTML = html; }),
          fetch('/static_v2/views/view_app_frame_studio.html').then(r => r.text()).then(html => { const el = document.getElementById('view-app-frame-studio-mount'); if (el) el.outerHTML = html; })
"""
    content = content.replace(anchor, replacement)
    with open(file_path, 'w', encoding='utf8') as f:
        f.write(content)
    print("Injected fetches.")
else:
    print("Anchor not found.")
