import os
import re

file_path = r"C:\.Antigravity-projekte\AgenticOS-2026\main.py"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

bad_block = '''        tier = "High" if provider == "openrouter" else "Low"
                transparency_tag = f"\\n\\n*- Routed to: `{model}` | Tier: `{tier}` | Est. Cost: `{cost_str}$`*"
        
        payload = json.dumps({"type": "delta", "delta": transparency_tag}, ensure_ascii=False)
        yield f"data: {payload}\\n\\n"
        full_assistant_text += transparency_tag'''

good_block = '''        tier = "High" if provider == "openrouter" else "Low"
        transparency_tag = f"\\n\\n*- Routed to: `{model}` | Tier: `{tier}` | Est. Cost: `{cost_str}$`*"
        
        payload = json.dumps({"type": "delta", "delta": transparency_tag}, ensure_ascii=False)
        yield f"data: {payload}\\n\\n"
        full_assistant_text += transparency_tag'''

content = content.replace(bad_block, good_block)
with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)
print("Indentation fixed.")
