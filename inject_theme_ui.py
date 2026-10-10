import os

file_path = r'C:\.Antigravity-projekte\AgenticOS-2026\static_v2\views\view_app_frame_studio.html'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

theme_manager_html = '''
      <!-- THEME MANAGER BAR -->
      <div class="p-2 bg-zinc-950/80 border-b border-zinc-800 flex items-center justify-between gap-2 shrink-0">
        <div class="flex items-center gap-1.5 flex-1">
          <i data-lucide="layers" class="w-3.5 h-3.5 text-zinc-400"></i>
          <select id="studio-theme-select" onchange="loadSelectedThemeProfile(this.value)" class="flex-1 bg-zinc-900 border border-zinc-700 rounded px-2 py-1 text-[11px] font-mono text-white focus:outline-none">
            <option value="">-- Theme w&auml;hlen --</option>
          </select>
        </div>
        <div class="flex items-center gap-1">
          <button type="button" onclick="saveThemeProfile()" class="px-2 py-1 rounded bg-indigo-600 hover:bg-indigo-500 text-white font-bold text-[10px] transition shadow-sm flex items-center gap-1">
            <i data-lucide="save" class="w-3 h-3"></i> Speichern
          </button>
          <button type="button" onclick="deleteThemeProfile()" class="px-2 py-1 rounded bg-rose-900/50 hover:bg-rose-800 border border-rose-800 text-rose-200 font-bold text-[10px] transition shadow-sm">
            <i data-lucide="trash-2" class="w-3 h-3"></i>
          </button>
        </div>
      </div>
'''

# Find the header bar
idx = content.find('<!-- TARGET SELECTOR')
if idx != -1:
    content = content[:idx] + theme_manager_html + content[idx:]
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print("Injected Theme Manager HTML.")
else:
    print("Could not find anchor.")
