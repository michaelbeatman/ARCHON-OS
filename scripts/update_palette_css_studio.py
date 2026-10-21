with open('static/js/command_palette.js', 'r', encoding='utf-8') as f:
    content = f.read()

target = "{ id: 'act-design-studio', title: '15-Komponenten Design Studio öffnen', desc: 'Farben, Abstände, Schatten & Dual-Themes', icon: 'palette', cat: 'action', action: () => { openSystemSettingsModal(); if (typeof switchSettingsTab === 'function') switchSettingsTab('design'); } },"

replacement = """{ id: 'act-css-live-studio', title: 'CSS Live Studio öffnen (Alt + S)', desc: 'Interaktiver In-Place Inspector, Drag Gizmo & Live CSS-Regeln', icon: 'palette', cat: 'action', action: () => { if (typeof toggleCssStudio === 'function') toggleCssStudio(); } },
    { id: 'act-design-studio', title: '15-Komponenten Design Studio öffnen', desc: 'Farben, Abstände, Schatten & Dual-Themes', icon: 'sliders', cat: 'action', action: () => { openSystemSettingsModal(); if (typeof switchSettingsTab === 'function') switchSettingsTab('design'); } },"""

if target in content:
    content = content.replace(target, replacement, 1)
    with open('static/js/command_palette.js', 'w', encoding='utf-8') as f:
        f.write(content)
    print("Added CSS Live Studio to command palette successfully")
else:
    print("Target not found in command_palette.js")
