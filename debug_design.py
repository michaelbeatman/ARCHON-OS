import os
import sys
sys.stdout.reconfigure(encoding='utf-8')

file_path = r"C:\.Antigravity-projekte\AgenticOS-2026\static_v2\index.html"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

view_id = "view-design-system"
start_str = f'      <div id="{view_id}"'
start_idx = content.find(start_str)

if start_idx != -1:
    end_idx = content.find('    </main>', start_idx)
    actual_end_idx = content.rfind('      </div>', start_idx, end_idx) + 12
    extracted_html = content[start_idx:actual_end_idx].strip()
    
    print(f"Start: {start_idx}, End: {actual_end_idx}, Length: {len(extracted_html)}")
else:
    print("Not found")
