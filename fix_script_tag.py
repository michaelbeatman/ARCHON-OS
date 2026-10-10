import os

file_path = r"C:\.Antigravity-projekte\AgenticOS-2026\static_v2\index.html"
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Replace the broken > with </script>
target = """      // APPSHELL ARCHITECT EXTRACTED TO js/appshell_architect.js
>
  <script src="/static_v2/js/chat_engine.js"></script>"""

replacement = """      // APPSHELL ARCHITECT EXTRACTED TO js/appshell_architect.js
  </script>
  <script src="/static_v2/js/chat_engine.js"></script>"""

if target in content:
    content = content.replace(target, replacement)
    print("Fixed broken > tag.")
else:
    print("Could not find the target string.")

# Remove the extra </script> that is just above <!-- ARCHON OS NATIVE GATEWAY MANAGER MODAL
target2 = """  <script src="/static_v2/js/skill_markt.js"></script>
  </script>
    <!-- ========================================================================= -->"""

replacement2 = """  <script src="/static_v2/js/skill_markt.js"></script>
    <!-- ========================================================================= -->"""

if target2 in content:
    content = content.replace(target2, replacement2)
    print("Removed extra </script> tag.")
else:
    print("Could not find the extra </script> tag.")

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
