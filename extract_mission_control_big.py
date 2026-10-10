import os
import re

file_path = r"C:\.Antigravity-projekte\AgenticOS-2026\static_v2\index.html"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

def extract_section(start_regex, end_regex, filename, fallback_end_idx=None):
    global content
    match1 = re.search(start_regex, content)
    
    if not match1:
        print(f"Could not find start for {filename}")
        return
        
    start_idx = match1.start()
    
    if end_regex:
        match2 = re.search(end_regex, content)
        if not match2:
            print(f"Could not find end for {filename}")
            return
        end_idx = match2.start()
    else:
        end_idx = fallback_end_idx
        
    if end_idx <= start_idx:
        print(f"End idx {end_idx} is before start idx {start_idx} for {filename}")
        return
        
    js_code = content[start_idx:end_idx]
    
    js_dir = r"C:\.Antigravity-projekte\AgenticOS-2026\static_v2\js"
    with open(os.path.join(js_dir, filename), "w", encoding="utf-8") as f:
        f.write(js_code)
        
    replacement = f'\n      // {filename.upper()} EXTRACTED\n'
    content = content[:start_idx] + replacement + content[end_idx:]
    
    script_start = content.rfind('<script>', 0, content.find('ARCHON OS GLOBAL NOTIFICATION'))
    if script_start != -1:
        content = content[:script_start] + f'<script src="/static_v2/js/{filename}"></script>\n  ' + content[script_start:]
        
    print(f"Extracted {filename}! Lines removed: {js_code.count(chr(10))}")

# 1. Mission Control Cockpit
extract_section(
    r'\s*// =+\s*\n\s*// 🚀 MISSION CONTROL 3-ZONEN-COCKPIT CONTROLLER & LOGIK\s*\n\s*// =+',
    r'\s*// =+\s*\n\s*// RESEARCH LAB \(SÄULE 2: KOGNITION & WISSEN\)\s*\n\s*// =+',
    "mission_control_cockpit.js"
)

# 2. Research Lab
extract_section(
    r'\s*// =+\s*\n\s*// RESEARCH LAB \(SÄULE 2: KOGNITION & WISSEN\)\s*\n\s*// =+',
    r'\s*// =+\s*\n\s*// OPERATIONS CONTROL CENTER \(KANBAN, ORG-CHART & INTER-AGENT COMM\)\s*\n\s*// =+',
    "research_lab.js"
)

# 3. Operations Kanban & Org Chart
# This goes until APPSHELL ARCHITECT
extract_section(
    r'\s*// =+\s*\n\s*// OPERATIONS CONTROL CENTER \(KANBAN, ORG-CHART & INTER-AGENT COMM\)\s*\n\s*// =+',
    r'\s*// =+\s*\n\s*// APPSHELL ARCHITECT & LAYOUT EDITOR CONTROLLER\s*\n\s*// =+',
    "operations_kanban.js"
)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)

