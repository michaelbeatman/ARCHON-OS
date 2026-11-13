import os
import json
import re
import sys

from build_mastermind_v2 import CATEGORIZED_FRAMEWORKS, FRAMEWORK_SLOT_DEFAULTS

# Verify counts
total_cats = len(CATEGORIZED_FRAMEWORKS)
total_fws_cat = sum(len(v) for v in CATEGORIZED_FRAMEWORKS.values())
total_fws_slots = len(FRAMEWORK_SLOT_DEFAULTS)

print(f"Categories: {total_cats}, Frameworks in Cat: {total_fws_cat}, Slots mapped: {total_fws_slots}")
assert total_cats == 9
assert total_fws_cat == 55
assert total_fws_slots == 55

base_dir = "/app/project_root" if os.path.exists("/app/project_root") else r"."

# 1. Update core_dispatcher.py
core_dispatcher_path = os.path.join(base_dir, "core_dispatcher.py")
with open(core_dispatcher_path, "r", encoding="utf-8") as f:
    cd_content = f.read()

# Locate start of CATEGORIZED_FRAMEWORKS
cat_start = cd_content.find("CATEGORIZED_FRAMEWORKS = {")
if cat_start == -1:
    raise Exception("CATEGORIZED_FRAMEWORKS not found in core_dispatcher.py")

# Locate end before DEFAULT_CATEGORIZED_FRAMEWORKS
def_cat_start = cd_content.find("DEFAULT_CATEGORIZED_FRAMEWORKS = copy.deepcopy(CATEGORIZED_FRAMEWORKS)", cat_start)
if def_cat_start == -1:
    def_cat_start = cd_content.find("import copy\nDEFAULT_CATEGORIZED_FRAMEWORKS", cat_start)

if def_cat_start == -1:
    raise Exception("DEFAULT_CATEGORIZED_FRAMEWORKS anchor not found")

cat_code = "CATEGORIZED_FRAMEWORKS = " + json.dumps(CATEGORIZED_FRAMEWORKS, indent=4, ensure_ascii=False) + "\n\n"
slots_code = "FRAMEWORK_SLOT_DEFAULTS = " + json.dumps(FRAMEWORK_SLOT_DEFAULTS, indent=4, ensure_ascii=False) + "\n\nimport copy\n"

# Replace section
new_cd_content = cd_content[:cat_start] + cat_code + slots_code + cd_content[def_cat_start:]

with open(core_dispatcher_path, "w", encoding="utf-8") as f:
    f.write(new_cd_content)

print(f"Successfully updated {core_dispatcher_path}")

# 2. Update static/index.html
index_html_path = os.path.join(base_dir, "static", "index.html")
with open(index_html_path, "r", encoding="utf-8") as f:
    html_content = f.read()

# Replace FRAMEWORK_SLOT_DEFAULTS in JS
js_slots_code = "    const FRAMEWORK_SLOT_DEFAULTS = " + json.dumps(FRAMEWORK_SLOT_DEFAULTS, indent=6, ensure_ascii=False) + ";"
js_slots_pattern = r"const FRAMEWORK_SLOT_DEFAULTS = \{.*?\n    \};"
html_content = re.sub(js_slots_pattern, js_slots_code, html_content, flags=re.DOTALL)

with open(index_html_path, "w", encoding="utf-8") as f:
    f.write(html_content)

print(f"Successfully updated {index_html_path}")

# 3. Generate clean mastermind_audit_export.md
# Load roles for name lookup
roles_file = os.path.join(base_dir, "roles.json")
roles_map = {}
if os.path.exists(roles_file):
    try:
        with open(roles_file, "r", encoding="utf-8") as rf:
            r_data = json.load(rf)
            for r in r_data:
                roles_map[r.get("id")] = r.get("name", r.get("id"))
    except Exception as ex:
        print("Note: could not load roles.json for names:", ex)

output = []
output.append("# AI MASTERMIND FRAMEWORKS & REAL-PROFILE SUBAGENT SLOTS (55 SYSTEME) — AUDIT & EXPORT\n")
output.append("Vollständige technische Extraktion aller 55 Methodik-Frameworks in 9 Kategorien und System-Prompts aus `core_dispatcher.py` / `main.py` von Archon OS mit exakter Zuweisung zu den 50 realen Profil-Handles.\n\n---\n")

idx = 1
for cat_name, frameworks in CATEGORIZED_FRAMEWORKS.items():
    output.append(f"## {cat_name}\n")
    for fw_name, fw_prompt in frameworks.items():
        cfg = FRAMEWORK_SLOT_DEFAULTS.get(fw_name, {})
        chair_id = cfg.get("chair", "executive_decision_architect")
        chair_name = roles_map.get(chair_id, chair_id)
        slots = cfg.get("slots", [])
        
        output.append(f"# [{idx:02d}] {fw_name}")
        output.append(f"- **Kategorie:** {cat_name}")
        output.append(f"- **Standard-Runden:** 2")
        output.append(f"- **Chairman:** `{chair_id}` ({chair_name})")
        output.append(f"- **Empfohlene Subagenten-Slots ({len(slots)}):**")
        for s_idx, s in enumerate(slots, 1):
            p_id = s.get("default_profile", "senior_fullstack_engineer")
            p_name = roles_map.get(p_id, p_id)
            r_name = s.get("role_name", f"Slot {s_idx}")
            output.append(f"  * Slot {s_idx}: `{p_id}` ({p_name}) — *{r_name}*")
        output.append("")
        output.append("### Framework-Spezifikation (System-Prompt):")
        output.append("```text")
        output.append(fw_prompt.strip())
        output.append("```\n\n---\n")
        idx += 1

export_path = os.path.join(base_dir, "mastermind_audit_export.md")
with open(export_path, "w", encoding="utf-8") as f:
    f.write("\n".join(output))

print(f"Successfully generated {export_path} with all {idx-1} frameworks")
