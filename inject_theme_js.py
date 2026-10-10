import os

js_path = r'C:\.Antigravity-projekte\AgenticOS-2026\static_v2\js\css_live_studio.js'
js_code = '''
// --- THEME MANAGER LOGIC ---
async function fetchThemeProfiles() {
    try {
        const res = await fetch('/api/themes');
        if (!res.ok) return;
        const data = await res.json();
        const select = document.getElementById('studio-theme-select');
        if (!select) return;
        
        const currentValue = select.value;
        select.innerHTML = '<option value=\"\">-- Theme w&auml;hlen --</option>';
        
        data.themes.forEach(theme => {
            const opt = document.createElement('option');
            opt.value = theme;
            opt.textContent = theme;
            select.appendChild(opt);
        });
        
        if (data.themes.includes(currentValue)) {
            select.value = currentValue;
        }
    } catch (e) {
        console.error("Fehler beim Laden der Themes:", e);
    }
}

async function loadSelectedThemeProfile(themeName) {
    if (!themeName) return;
    try {
        const res = await fetch(/api/themes/);
        if (!res.ok) return;
        const themeData = await res.json();
        
        // Use existing function to apply
        if (typeof applyDesignPreset === 'function') {
            // Apply it manually
            Object.keys(themeData).forEach(k => {
                themeSettings[k] = themeData[k];
            });
            syncInputsWithSettings(); // Update UI inputs
            
            // Reapply CSS vars
            if (themeSettings.sidebarWidth) document.documentElement.style.setProperty('--sidebar-width', themeSettings.sidebarWidth + 'px');
            if (themeSettings.borderRadius) document.documentElement.style.setProperty('--border-radius', themeSettings.borderRadius + 'px');
            if (themeSettings.colorSidebar) document.documentElement.style.setProperty('--sidebar-bg', themeSettings.colorSidebar);
            if (themeSettings.colorCard) document.documentElement.style.setProperty('--card-bg', themeSettings.colorCard);
            if (themeSettings.colorBg) document.documentElement.style.setProperty('--page-bg', themeSettings.colorBg);
            if (themeSettings.colorAccent) document.documentElement.style.setProperty('--accent-color', themeSettings.colorAccent);
            // etc... this handles the basic keys from customizer.js
            
            // We should also apply the new studio styles if they exist
            if (typeof liveApplyCustomCSS === 'function') {
                saveThemeToServer(true); // save as active theme
                showNotification("Theme geladen", Das Theme '' wurde erfolgreich geladen., "success");
            }
        }
    } catch (e) {
        console.error(e);
        showNotification("Fehler", "Theme konnte nicht geladen werden.", "error");
    }
}

async function saveThemeProfile() {
    const select = document.getElementById('studio-theme-select');
    let name = select.value;
    
    name = prompt("Unter welchem Namen soll dieses Theme gespeichert werden?", name || "Mein Custom Theme");
    if (!name) return;
    
    // Format name (remove special chars, make safe for filename)
    name = name.replace(/[^a-zA-Z0-9_-]/g, "_").toLowerCase();
    
    try {
        const res = await fetch(/api/themes/, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(themeSettings) // themeSettings is global in customizer.js
        });
        
        if (res.ok) {
            showNotification("Theme gespeichert", Theme '' erfolgreich gesichert!, "success");
            await fetchThemeProfiles();
            select.value = name;
        }
    } catch (e) {
        showNotification("Fehler", "Theme konnte nicht gespeichert werden.", "error");
    }
}

async function deleteThemeProfile() {
    const select = document.getElementById('studio-theme-select');
    const name = select.value;
    if (!name) {
        alert("Bitte zuerst ein Theme ausw&auml;hlen!");
        return;
    }
    
    if (!confirm(M&ouml;chtest du das Theme '' wirklich l&ouml;schen?)) return;
    
    try {
        const res = await fetch(/api/themes/, { method: 'DELETE' });
        if (res.ok) {
            showNotification("Theme gel&ouml;scht", Theme '' wurde entfernt., "success");
            select.value = "";
            await fetchThemeProfiles();
        }
    } catch (e) {
        showNotification("Fehler", "Konnte nicht gel&ouml;scht werden.", "error");
    }
}

// Call fetch on load
setTimeout(fetchThemeProfiles, 2000);
'''

with open(js_path, 'a', encoding='utf-8') as f:
    f.write('\n' + js_code + '\n')
print("Injected Theme Manager JS logic.")
