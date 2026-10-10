import os

file_path = r"C:\.Antigravity-projekte\AgenticOS-2026\static_v2\index.html"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

start_str = '      <div id="view-agent-profiles"'
start_idx = content.find(start_str)

if start_idx == -1:
    print("Could not find start of view-agent-profiles.")
else:
    # Find the next view to determine the end.
    next_view_str = '      <div id="view-ai-mastermind"'
    end_idx = content.find(next_view_str, start_idx)
    
    if end_idx == -1:
        print("Could not find end of view.")
    else:
        # Extract the HTML
        # We need to find the exact closing tag of view-agent-profiles. 
        # Usually it ends with a closing `</div>` just before the next view.
        # Let's just find the last `</div>` before next_view_str.
        actual_end_idx = content.rfind('      </div>', start_idx, end_idx) + 12
        
        extracted_html = content[start_idx:actual_end_idx].strip()
        
        views_dir = r"C:\.Antigravity-projekte\AgenticOS-2026\static_v2\views"
        with open(os.path.join(views_dir, "agent_profiles_view.html"), "w", encoding="utf-8") as f:
            f.write(extracted_html)
            
        replacement = '      <!-- VIEW: AGENT PROFILES (Extracted) -->\n      <div id="view-agent-profiles-mount"></div>\n'
        new_content = content[:start_idx] + replacement + content[actual_end_idx:]
        
        # Add fetch logic
        init_str = '// Load System Settings Modal Component'
        init_replacement = '''
      // Load Agent Profiles View Component
      try {
        const res = await fetch('/static_v2/views/agent_profiles_view.html');
        const html = await res.text();
        const mount = document.getElementById('view-agent-profiles-mount');
        if(mount) mount.outerHTML = html; // replace mount completely to keep original ID active
      } catch(e) { console.error("Failed to load agent profiles view", e); }
      
      ''' + init_str
        
        if init_str in new_content:
            new_content = new_content.replace(init_str, init_replacement)
            
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(new_content)
            
        print(f"Extracted view-agent-profiles! Lines removed from main file: {extracted_html.count(chr(10))}")
