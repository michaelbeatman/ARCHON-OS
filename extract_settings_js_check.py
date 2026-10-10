import os

file_path = r"C:\.Antigravity-projekte\AgenticOS-2026\static_v2\index.html"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

start_str = '    // --- SYSTEM CONTROL CENTER LOGIC ---'
start_idx = content.find(start_str)

if start_idx == -1:
    print("Could not find start of JS.")
else:
    # Find the end of the JS block.
    # It should be before CONTEXT HELP SYSTEM
    end_str = '    // --- CONTEXT HELP SYSTEM ---'
    end_idx = content.find(end_str, start_idx)
    
    if end_idx == -1:
        print("Could not find end of JS.")
    else:
        js_code = content[start_idx:end_idx].strip()
        
        js_dir = r"C:\.Antigravity-projekte\AgenticOS-2026\static_v2\js\components"
        os.makedirs(js_dir, exist_ok=True)
        
        # Save to JS file
        with open(os.path.join(js_dir, "system_settings.js"), "w", encoding="utf-8") as f:
            f.write(js_code)
            
        # Replace in index.html with a simple comment (we will load the script via <script> tag)
        replacement = '    // --- SYSTEM CONTROL CENTER LOGIC (Extracted to js/components/system_settings.js) ---\n\n'
        new_content = content[:start_idx] + replacement + content[end_idx:]
        
        # Add the script tag to the head or body.
        # Let's add it right before <script> tag in the HTML (but the JS is currently in a huge inline <script> block, 
        # so variables like `currentEditingRoleSettingsId` and functions like `openSystemSettingsModal` were defined in the SAME scope.
        # Wait, if we move them to an EXTERNAL script, they will be globally scoped (var/function declarations at top level of script are global).
        # But `index.html` has a HUGE `<script>` tag enclosing ALL code.
        # So variables defined with `let` or `const` inside that `<script>` tag are NOT global, they are block-scoped to that script tag if it's a module, 
        # or globally scoped if it's a normal script.
        # Yes, normal `<script>` tags share the global namespace.
        # BUT if I move code OUT of the massive inline script and put it in a separate `<script src="...">`, it will still run in the global scope!
        # Wait, the massive inline script is just `<script>`, so it runs in global scope.
        # Let's insert `<script src="/static_v2/js/components/system_settings.js"></script>` right BEFORE the massive inline script.
        # Search for `<script>\n    tailwind.config`
        # Actually, let's insert it right before the `<script>` tag that contains all the JS logic.
        pass

        # Since it's easier and safer for now, I will NOT extract the JS until the user tests the HTML extraction. The HTML extraction alone is already a huge win (1900 lines). Extracting the JS has high risk of scope issues (e.g., `let agents = []` defined in the main script being accessed by the settings script). I should probably export/import variables cleanly.
        
print("JS Extraction aborted to ensure scope safety. Will do step by step.")
