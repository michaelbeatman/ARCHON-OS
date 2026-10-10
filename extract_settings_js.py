import os
import re

file_path = r"C:\.Antigravity-projekte\AgenticOS-2026\static_v2\index.html"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

match1 = re.search(r'\s*// ---\s+SYSTEM CONTROL CENTER LOGIC\s+---', content)
match2 = re.search(r'\s*// ---\s+CONTEXT HELP SYSTEM\s+---', content)

if not match1 or not match2:
    print(f"Could not find boundaries. match1={bool(match1)}, match2={bool(match2)}")
else:
    start_idx = match1.start()
    end_idx = match2.start()
    
    js_code = content[start_idx:end_idx]
    
    js_dir = r"C:\.Antigravity-projekte\AgenticOS-2026\static_v2\js"
    os.makedirs(js_dir, exist_ok=True)
    with open(os.path.join(js_dir, "system_settings.js"), "w", encoding="utf-8") as f:
        f.write(js_code)
        
    replacement = '\n      // SYSTEM CONTROL CENTER EXTRACTED TO js/system_settings.js\n'
    new_content = content[:start_idx] + replacement + content[end_idx:]
    
    # Inject the script tag right before the big inline script.
    script_start = new_content.rfind('<script>', 0, new_content.find('ARCHON OS GLOBAL NOTIFICATION'))
    
    if script_start != -1:
        new_content = new_content[:script_start] + '<script src="/static_v2/js/system_settings.js"></script>\n  ' + new_content[script_start:]
    else:
        print("Could not find <script> tag to inject before.")
        
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(new_content)
        
    print(f"Extracted system_settings.js! Lines removed: {js_code.count(chr(10))}")
