import os
import subprocess
import json

base_dir = "/app/project_root" if os.path.exists("/app/project_root") else r"C:\.Antigravity-projekte\AgenticOS-2026"
index_html_path = os.path.join(base_dir, "static", "index.html")

# Get HEAD content via git show
git_res = subprocess.run(["git", "show", "HEAD:static/index.html"], capture_output=True, text=True, cwd=base_dir)
head_content = git_res.stdout

with open(index_html_path, "r", encoding="utf-8") as f:
    current_content = f.read()

# Locate missing block in HEAD
start_marker = "function handleSidebarPresetSelected"
end_marker = "function updateCardBackground"

start_idx = head_content.find(start_marker)
end_idx = head_content.find(end_marker)
end_of_last_fn = head_content.find("    }", end_idx) + 5

head_block = head_content[start_idx:end_of_last_fn]

# Remove overlapping functions from head_block so current implementations are preserved
import re
overlapping_fns = [
    "resetRolesToDefault",
    "loadRolesFromServer",
    "loadModelsFromServer",
    "loadKanbanFromServer",
    "loadVaultFiles",
    "applyCustomizerSetting",
    "hexToRgba"
]

clean_block = head_block
for fn in overlapping_fns:
    # Match function definition
    pattern = rf"(async\s+)?function\s+{fn}\s*\([^)]*\)\s*\{{[\s\S]*?\n    \}}"
    clean_block = re.sub(pattern, f"/* {fn} preserved from current version */", clean_block)

# Insert the clean block before `function updateLogo` or at the end of the script before `</script>`
insert_pos = current_content.find("function updateLogo")
if insert_pos != -1:
    new_html = current_content[:insert_pos] + clean_block + "\n\n    " + current_content[insert_pos:]
else:
    # Insert before closing script tag
    last_script_end = current_content.rfind("</script>")
    new_html = current_content[:last_script_end] + "\n\n" + clean_block + "\n\n" + current_content[last_script_end:]

with open(index_html_path, "w", encoding="utf-8") as f:
    f.write(new_html)

print("Successfully restored all missing core UI and navigation functions!")
