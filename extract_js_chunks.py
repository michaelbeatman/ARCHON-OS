import os
import re

file_path = r"C:\.Antigravity-projekte\AgenticOS-2026\static_v2\index.html"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

# 1. HERMES AGENTENPROFILE & SKILL-MANAGER LOGIK -> SYSTEM HEALTH TELEMETRY & RESTART CONTROLLER
match1 = re.search(r'\s*// ---\s+HERMES AGENTENPROFILE & SKILL-MANAGER LOGIK\s+---', content)
match2 = re.search(r'\s*// ---\s+SYSTEM HEALTH TELEMETRY & RESTART CONTROLLER\s+---', content)

if not match1 or not match2:
    print(f"Could not find boundaries for agent_profiles.js")
else:
    start_idx = match1.start()
    end_idx = match2.start()
    
    js_code = content[start_idx:end_idx]
    
    js_dir = r"C:\.Antigravity-projekte\AgenticOS-2026\static_v2\js"
    with open(os.path.join(js_dir, "agent_profiles.js"), "w", encoding="utf-8") as f:
        f.write(js_code)
        
    replacement = '\n      // HERMES AGENT PROFILES EXTRACTED TO js/agent_profiles.js\n'
    content = content[:start_idx] + replacement + content[end_idx:]
    print(f"Extracted agent_profiles.js! Lines removed: {js_code.count(chr(10))}")

# 2. CUSTOMIZER STEUERUNG & LIVE-UPDATE -> SYSTEM CONTROL CENTER EXTRACTED
# Wait, since we removed SYSTEM CONTROL CENTER, the text might be `// SYSTEM CONTROL CENTER EXTRACTED`
match3 = re.search(r'\s*// ---\s+CUSTOMIZER STEUERUNG & LIVE-UPDATE\s+---', content)
match4 = re.search(r'\s*// SYSTEM CONTROL CENTER EXTRACTED TO js/system_settings\.js', content)

if not match3 or not match4:
    print(f"Could not find boundaries for customizer.js")
else:
    start_idx = match3.start()
    end_idx = match4.start()
    
    js_code = content[start_idx:end_idx]
    
    with open(os.path.join(js_dir, "customizer.js"), "w", encoding="utf-8") as f:
        f.write(js_code)
        
    replacement = '\n      // CUSTOMIZER & CRM STYLE EXTRACTED TO js/customizer.js\n'
    content = content[:start_idx] + replacement + content[end_idx:]
    print(f"Extracted customizer.js! Lines removed: {js_code.count(chr(10))}")

# Inject script tags
script_start = content.rfind('<script>', 0, content.find('ARCHON OS GLOBAL NOTIFICATION'))
if script_start != -1:
    injections = '<script src="/static_v2/js/agent_profiles.js"></script>\n  <script src="/static_v2/js/customizer.js"></script>\n  '
    content = content[:script_start] + injections + content[script_start:]
else:
    print("Could not find <script> tag to inject before.")
    
with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)

