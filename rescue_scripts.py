import os

file_path = r"C:\.Antigravity-projekte\AgenticOS-2026\static_v2\index.html"
view_file = r"C:\.Antigravity-projekte\AgenticOS-2026\static_v2\views\view_design_system.html"

with open(view_file, "r", encoding="utf-8") as f:
    view_content = f.read()

# Find where the script tags start
script_start = view_content.find('<script src="/static_v2/js/chat_engine.js"></script>')

if script_start != -1:
    # We must backtrack to close the div for view-design-system correctly?
    # Actually, the view_content is `<div id="view-design-system" ...> ... </div>` followed by scripts.
    # Let's find the last `</div>` before the scripts.
    div_end = view_content.rfind('</div>', 0, script_start) + 6
    
    actual_html = view_content[:div_end].strip()
    scripts_and_rest = view_content[script_start:]
    
    with open(view_file, "w", encoding="utf-8") as f:
        f.write(actual_html)
        
    with open(file_path, "r", encoding="utf-8") as f:
        idx_content = f.read()
        
    # Append scripts_and_rest back to index.html
    # wait, index.html might have some trailing spaces.
    idx_content = idx_content.rstrip() + "\n  " + scripts_and_rest
    
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(idx_content)
        
    print("Fixed! Restored scripts to index.html.")
else:
    print("Could not find script start in view.")
