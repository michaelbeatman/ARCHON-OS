import re

def patch_file(path, replacements):
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    
    modified = content
    for target, repl in replacements:
        if target in modified:
            modified = modified.replace(target, repl, 1)
            print(f"Patched in {path}: {target[:30]}...")
        else:
            print(f"WARNING: Target not found in {path}: {target[:30]}...")
            
    with open(path, "w", encoding="utf-8") as f:
        f.write(modified)

# 1. Patch static/js/prompt_studio.js
js_replacements = [
    (
        "    // =========================================================================\n"
        "    // SUREPROMPTS FORMULAR-BAUKASTEN & STUDIO (324 TEMPLATES)\n"
        "    // =========================================================================",
        "    // =========================================================================\n"
        "    // ARCHON PROMPT STUDIO (824 ENTERPRISE TEMPLATES + 255 FABRIC SOPS = 1.079)\n"
        "    // ========================================================================="
    ),
    (
        'const stored = localStorage.getItem("archon_fav_sureprompts");',
        'const stored = localStorage.getItem("archon_fav_prompts") || localStorage.getItem("archon_fav_sureprompts");'
    ),
    (
        'localStorage.setItem("archon_fav_sureprompts", JSON.stringify(favs));',
        'localStorage.setItem("archon_fav_prompts", JSON.stringify(favs)); localStorage.setItem("archon_fav_sureprompts", JSON.stringify(favs));'
    ),
    (
        "    function closeSurePromptsModal() {\n"
        '      const modal = document.getElementById("sureprompts-modal");\n'
        '      if (modal) modal.classList.add("hidden");\n'
        "    }",
        "    function closeSurePromptsModal() {\n"
        '      const modal = document.getElementById("sureprompts-modal");\n'
        '      if (modal) modal.classList.add("hidden");\n'
        "    }\n"
        "    // Aliases fuer Archon Prompt Studio\n"
        "    window.openPromptStudioModal = openSurePromptsModal;\n"
        "    window.closePromptStudioModal = closeSurePromptsModal;\n"
        "    window.openSurePromptsModal = openSurePromptsModal;\n"
        "    window.closeSurePromptsModal = closeSurePromptsModal;"
    )
]
patch_file("static/js/prompt_studio.js", js_replacements)

# 2. Patch static/views/master_chat_view.html
view1_replacements = [
    (
        '<!-- Archon Prompt Studio Button (579+ Vorlagen: Enterprise & Fabric SOP) -->',
        '<!-- Archon Prompt Studio Button (1.079 Vorlagen: Enterprise & Fabric SOP) -->'
    ),
    (
        'title="Archon Prompt Studio (579+ Vorlagen: Enterprise-Baukasten &amp; Fabric SOP-Muster)"',
        'title="Archon Prompt Studio (1.079 Vorlagen: Enterprise &amp; Fabric SOP)"'
    )
]
patch_file("static/views/master_chat_view.html", view1_replacements)

# 3. Patch static/views/agent_profiles_view.html
view2_replacements = [
    (
        '<!-- Archon Prompt Studio Button (579+ Vorlagen) -->',
        '<!-- Archon Prompt Studio Button (1.079 Vorlagen) -->'
    ),
    (
        'title="Archon Prompt Studio (579+ Vorlagen: Enterprise-Baukasten &amp; Fabric SOP-Muster)"',
        'title="Archon Prompt Studio (1.079 Vorlagen: Enterprise &amp; Fabric SOP)"'
    )
]
patch_file("static/views/agent_profiles_view.html", view2_replacements)

# 4. Patch static/index.html
index_replacements = [
    (
        '<!-- MODAL: SUREPROMPTS FORMULAR-BAUKASTEN (324 TEMPLATES MIT DYNAMISCHEN FELDERN) -->',
        '<!-- MODAL: ARCHON PROMPT STUDIO (824 ENTERPRISE TEMPLATES + 255 FABRIC SOPS = 1.079) -->'
    ),
    (
        'title="Archon Prompt Studio (1.079 Vorlagen: Enterprise &amp; Fabric SOP)"',
        'title="Archon Prompt Studio (1.079 Vorlagen: Enterprise &amp; Fabric SOP)"'
    )
]
patch_file("static/index.html", index_replacements)
print("ALL PATCHES APPLIED.")
