import os
import re

file_path = r"C:\.Antigravity-projekte\AgenticOS-2026\main.py"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

bad_str = '        yield f"data: {{json.dumps({{\'type\': \'done\', \'session_id\': session_id, \'tokens\': completion_tokens}})}}\n\n"'
good_str = '        payload_done = json.dumps({"type": "done", "session_id": session_id, "tokens": completion_tokens})\n        yield f"data: {payload_done}\\n\\n"'

if bad_str in content:
    content = content.replace(bad_str, good_str)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
    print("Fixed second syntax error!")
else:
    print("Could not find the exact string. Trying regex.")
    match = re.search(r'yield f"data: \{json\.dumps\(\{\'type\': \'done\'.*?\n\n"', content)
    if match:
        content = content[:match.start()] + good_str + content[match.end():]
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        print("Fixed via regex.")
    else:
        print("Still couldn't find it.")
