import re

file_path = r"C:\.Antigravity-projekte\AgenticOS-2026\static_v2\index.html"

with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

mount_str = '<div id="view-design-system-mount"></div>'
mount_idx = content.find(mount_str)
if mount_idx == -1:
    print("Could not find mount_str")
    exit(1)

start_idx = mount_idx + len(mount_str)

end_str = '// APPSHELL ARCHITECT EXTRACTED TO js/appshell_architect.js'
end_idx = content.find(end_str, start_idx)
if end_idx == -1:
    print("Could not find end_str")
    exit(1)

end_idx = content.find('\n', end_idx)
if end_idx == -1:
    end_idx = len(content)

broken_js = content[start_idx:end_idx].strip()
content = content[:start_idx] + "\n" + content[end_idx:]

render_idx = content.find('function renderPluginConfigFields(')
if render_idx == -1:
    print("Could not find renderPluginConfigFields")
    exit(1)

target_idx = content.find('  </script>', render_idx)
if target_idx == -1:
    print("Could not find closing script tag after renderPluginConfigFields")
    exit(1)

content = content[:target_idx] + "\n        " + broken_js + "\n" + content[target_idx:]

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)

print("Successfully healed the javascript block!")
