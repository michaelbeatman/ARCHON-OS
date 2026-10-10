import os

file_path = r"C:\.Antigravity-projekte\AgenticOS-2026\static_v2\index.html"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

start_str = '  <!-- MODAL: SYSTEM SETTINGS CONTROL CENTER -->'
start_idx = content.find(start_str)

if start_idx == -1:
    print("Could not find start of modal.")
else:
    # Find the end of the modal. The last closing div of the modal should be followed by the next section header.
    # Let's search for 'CONTEXT HELP'
    help_idx = content.find('CONTEXT HELP & SYSTEM-ASSISTENT MODAL', start_idx)
    # The actual end of the modal is the `</div>` before the `<!-- ======...` above CONTEXT HELP.
    # Let's find the `<!-- ===` right before CONTEXT HELP
    end_idx = content.rfind('  <!-- ===', start_idx, help_idx)
    
    if end_idx == -1:
        print("Could not find end of modal.")
    else:
        modal_html = content[start_idx:end_idx].strip()
        
        views_dir = r"C:\.Antigravity-projekte\AgenticOS-2026\static_v2\views"
        os.makedirs(views_dir, exist_ok=True)
        with open(os.path.join(views_dir, "system_settings_modal.html"), "w", encoding="utf-8") as f:
            f.write(modal_html)
            
        replacement = '  <!-- MODAL: SYSTEM SETTINGS CONTROL CENTER (Extracted) -->\n  <div id="system-settings-mount"></div>\n\n'
        new_content = content[:start_idx] + replacement + content[end_idx:]
        
        init_str = '// App Initialisierung\n    document.addEventListener("DOMContentLoaded", async () => {'
        init_replacement = init_str + '''
      // Load System Settings Modal Component
      try {
        const res = await fetch('/static_v2/views/system_settings_modal.html');
        const html = await res.text();
        const mount = document.getElementById('system-settings-mount');
        if(mount) mount.innerHTML = html;
      } catch(e) { console.error("Failed to load settings modal", e); }
'''
        if init_str in new_content:
            new_content = new_content.replace(init_str, init_replacement)
            
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(new_content)
            
        print("Successfully extracted System Settings Modal HTML!")
