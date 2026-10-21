import re

with open('static/index.html', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add view_app_frame_studio.html fetch to Promise.all in initArchonApp
fetch_target = "fetch('/static/views/system_settings_modal.html?v=202610161358').then(r => r.text()).then(html => { const el = document.getElementById('system-settings-mount'); if (el) el.outerHTML = html; }),"
fetch_replacement = "fetch('/static/views/view_app_frame_studio.html?v=202610161925').then(r => r.text()).then(html => { const el = document.getElementById('view-app-frame-studio-mount'); if (el) el.outerHTML = html; if (typeof lucide !== 'undefined') lucide.createIcons(); }),\n          fetch('/static/views/system_settings_modal.html?v=202610161358').then(r => r.text()).then(html => { const el = document.getElementById('system-settings-mount'); if (el) el.outerHTML = html; }),"

if fetch_target in content:
    content = content.replace(fetch_target, fetch_replacement, 1)
    print("Added studio mount fetch successfully")
else:
    print("WARNING: fetch_target not found")

# 2. Add button in Quick Links section
quick_target = """      <!-- Quick Links (Hermes Dashboard) -->
      <div class="space-y-0.5">
        <button id="nav-hermes-dashboard" onclick="setTab('hermes-dashboard')" class="archon-nav-item w-full flex items-center px-2.5 py-1 rounded text-left transition-all duration-150 text-xs font-medium text-muted-custom hover:text-primary-custom hover:bg-[var(--item-hover-bg)] mb-0.5">
          <span class="truncate font-semibold">Hermes Dashboard</span>
          <span class="ml-auto flex-shrink-0 active-arrow hidden"><i data-lucide="chevron-right" class="w-3 h-3 text-black dark:text-white"></i></span>
        </button>
      </div>"""

quick_replacement = """      <!-- Quick Links (Hermes Dashboard & CSS Studio) -->
      <div class="space-y-1">
        <button id="nav-hermes-dashboard" onclick="setTab('hermes-dashboard')" class="archon-nav-item w-full flex items-center px-2.5 py-1 rounded text-left transition-all duration-150 text-xs font-medium text-muted-custom hover:text-primary-custom hover:bg-[var(--item-hover-bg)]">
          <span class="truncate font-semibold">Hermes Dashboard</span>
          <span class="ml-auto flex-shrink-0 active-arrow hidden"><i data-lucide="chevron-right" class="w-3 h-3 text-black dark:text-white"></i></span>
        </button>
        <button id="nav-toggle-css-studio" type="button" onclick="toggleCssStudio()" class="w-full flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-left transition-all duration-150 text-xs font-semibold text-indigo-600 dark:text-indigo-400 bg-indigo-500/10 hover:bg-indigo-500/20 border border-indigo-500/30 cursor-pointer shadow-2xs">
          <i data-lucide="palette" class="w-3.5 h-3.5 shrink-0"></i>
          <span class="truncate font-medium">CSS Live Studio</span>
          <span class="ml-auto text-[9.5px] font-mono opacity-70 bg-indigo-500/20 px-1 py-0.2 rounded">Alt+S</span>
        </button>
      </div>"""

if quick_target in content:
    content = content.replace(quick_target, quick_replacement, 1)
    print("Added CSS Live Studio button to sidebar")
else:
    # Try normalizing CRLF / LF
    normalized_content = content.replace("\r\n", "\n")
    normalized_quick_target = quick_target.replace("\r\n", "\n")
    if normalized_quick_target in normalized_content:
        normalized_content = normalized_content.replace(normalized_quick_target, quick_replacement.replace("\r\n", "\n"), 1)
        content = normalized_content
        print("Added CSS Live Studio button with normalized newlines")
    else:
        print("WARNING: quick_target not found")

with open('static/index.html', 'w', encoding='utf-8') as f:
    f.write(content)
print("Updated static/index.html successfully!")
