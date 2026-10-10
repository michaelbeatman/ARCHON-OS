import os

file_path = r"C:\.Antigravity-projekte\AgenticOS-2026\static_v2\index.html"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

start_str = '      <div id="view-inbox"'
start_idx = content.find(start_str)

if start_idx == -1:
    print("Could not find start of view-inbox.")
else:
    next_view_idx = content.find('      <div id="view-', start_idx + 10)
    end_idx = next_view_idx
    
    if end_idx == -1:
        print("Could not find end of view.")
    else:
        actual_end_idx = content.rfind('      </div>', start_idx, end_idx) + 12
        extracted_html = content[start_idx:actual_end_idx].strip()
        
        views_dir = r"C:\.Antigravity-projekte\AgenticOS-2026\static_v2\views"
        with open(os.path.join(views_dir, "inbox_view.html"), "w", encoding="utf-8") as f:
            f.write(extracted_html)
            
        replacement = '      <!-- VIEW: INBOX (Extracted) -->\n      <div id="view-inbox-mount"></div>\n'
        new_content = content[:start_idx] + replacement + content[actual_end_idx:]
        
        init_str = '// Load System Settings Modal Component'
        init_replacement = '''
      // Load Inbox View Component
      try {
        const res = await fetch('/static_v2/views/inbox_view.html');
        const html = await res.text();
        const mount = document.getElementById('view-inbox-mount');
        if(mount) mount.outerHTML = html;
      } catch(e) { console.error("Failed to load inbox view", e); }
      
      ''' + init_str
        
        if init_str in new_content:
            new_content = new_content.replace(init_str, init_replacement)
            
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(new_content)
            
        print(f"Extracted view-inbox! Lines removed: {extracted_html.count(chr(10))}")
