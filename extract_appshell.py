import os
import re

file_path = r"C:\.Antigravity-projekte\AgenticOS-2026\static_v2\index.html"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

match1 = re.search(r'\s*// =+\s*\n\s*// APPSHELL ARCHITECT & LAYOUT EDITOR CONTROLLER\s*\n\s*// =+', content)

if not match1:
    print("Could not find start")
else:
    start_idx = match1.start()
    
    # We want to extract until the end of the script tag, which is `    </script>\n  </body>`
    end_idx = content.rfind('    </script>')
    
    js_code = content[start_idx:end_idx]
    
    js_dir = r"C:\.Antigravity-projekte\AgenticOS-2026\static_v2\js"
    with open(os.path.join(js_dir, "appshell_architect.js"), "w", encoding="utf-8") as f:
        f.write(js_code)
        
    replacement = '\n      // APPSHELL ARCHITECT EXTRACTED TO js/appshell_architect.js\n'
    new_content = content[:start_idx] + replacement + content[end_idx:]
    
    script_start = new_content.rfind('<script>', 0, new_content.find('ARCHON OS GLOBAL NOTIFICATION'))
    if script_start != -1:
        new_content = new_content[:script_start] + '<script src="/static_v2/js/appshell_architect.js"></script>\n  ' + new_content[script_start:]
        
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(new_content)
        
    print(f"Extracted appshell_architect.js! Lines removed: {js_code.count(chr(10))}")
