import os

appshell_path = r"C:\.Antigravity-projekte\AgenticOS-2026\static_v2\js\appshell_architect.js"
index_path = r"C:\.Antigravity-projekte\AgenticOS-2026\static_v2\index.html"

with open(appshell_path, "r", encoding="utf-8") as f:
    appshell_content = f.read()

split_idx = appshell_content.find("  </script>")

if split_idx != -1:
    js_content = appshell_content[:split_idx].strip()
    html_content = appshell_content[split_idx:]
    
    # Save the cleaned JS
    with open(appshell_path, "w", encoding="utf-8") as f:
        f.write(js_content)
        
    # Append the HTML to index.html
    with open(index_path, "r", encoding="utf-8") as f:
        index_content = f.read()
        
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(index_content.rstrip() + "\n" + html_content)
        
    print("Fixed appshell_architect.js and index.html!")
else:
    print("Could not find </script> in appshell_architect.js")
