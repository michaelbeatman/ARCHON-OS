import os

file_path = r"C:\.Antigravity-projekte\AgenticOS-2026\static_v2\index.html"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

start_str = '      // ==========================================\n      // NATIVE MASTER CHAT & MISSIONS-MODUS ENGINE'
start_idx = content.find(start_str)

if start_idx == -1:
    print("Could not find start.")
else:
    # Find the next section boundary
    end_idx = content.find('      // ==========================================\n      // AGENTEN-TERMINAL', start_idx)
    if end_idx == -1:
        # Let's just find the next '// ======' that has some text
        next_section = content.find('      // ==========================================\n      // ', start_idx + 100)
        end_idx = next_section
        
    if end_idx == -1:
        print("Could not find end.")
    else:
        print(f"Start: {start_idx}, End: {end_idx}")
        print(f"End block text: {content[end_idx:end_idx+200]}")
