with open("static/views/system_settings_modal.html", "r", encoding="utf-8") as f:
    html = f.read()

# 1. Target for removing old Firmenlogo box above studio
old_logo_box = """          <!-- CRM Firmenlogo / Logo Box -->
          <div class="border border-[var(--border)] rounded-xl p-3.5 bg-[var(--background)] space-y-2.5 shadow-xs">
            <h4 class="font-bold text-[10.5px] uppercase font-mono tracking-wider text-[var(--foreground)]">CRM FIRMENLOGO (OBEN LINKS)</h4>
            <div class="flex items-center gap-4">
              <div class="flex-1 bg-slate-950 p-3 rounded-xl flex items-center justify-center min-h-[50px] border border-[var(--border)]">
                <img id="crm-modal-logo-preview" src="/static/logo.png" onerror="this.style.display='none'; document.getElementById('crm-modal-logo-fallback').style.display='flex';" class="max-h-8 max-w-[180px] object-contain">
                <div id="crm-modal-logo-fallback" class="hidden items-center gap-1.5 text-white font-bold text-sm font-sans">
                  <span class="tracking-wider">ARCHON</span><span class="text-[#EF233C]">CRM</span>
                </div>
              </div>
              <div class="flex flex-col gap-2 shrink-0">
                <label class="cursor-pointer bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900 hover:opacity-90 font-bold px-3.5 py-1.5 rounded-lg text-xs transition shadow-sm text-center">
                  Bild auswählen...
                  <input type="file" id="crm-logo-file-input" accept="image/*" class="hidden" onchange="handleCrmLogoUpload(event)">
                </label>
                <button type="button" onclick="resetCrmLogo()" class="bg-[var(--secondary)] hover:bg-[var(--secondary)]/80 text-[var(--foreground)] border border-[var(--border)] font-bold px-3.5 py-1 rounded-lg text-xs transition text-center cursor-pointer">
                  Löschen
                </button>
              </div>
            </div>
          </div>"""

# 2. Target for Top Bar cleanup:
# Remove duplicate 'Aktuelles Theme sichern' button from Top Bar row 1, clean row 2 layout
old_top_bar = """            <!-- Top Bar: Theme Manager + Light/Dark Switch + Live-Dock -->
            <div class="border border-[var(--border)] rounded-xl p-3 bg-[var(--background)] space-y-2.5 shadow-xs">
              <div class="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--border)] pb-2.5">
                <div class="flex items-center gap-2">
                  <span class="px-2 py-0.5 rounded bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900 font-mono font-bold text-[10px] uppercase">15-Bausteine Engine</span>
                  <span class="text-xs font-bold text-[var(--foreground)]">Zentrales Komponenten-Design &amp; Dual-Themes (Hell + Dunkel)</span>
                </div>
                <div class="flex items-center gap-2">
                  <button type="button" id="cds-inspector-btn" onclick="cdsToggleInspectorMode()" class="px-3 py-1.5 rounded-lg border border-indigo-500/40 bg-indigo-500/10 hover:bg-indigo-500/20 text-indigo-600 dark:text-indigo-400 font-mono font-bold text-xs transition flex items-center gap-1.5 cursor-pointer shadow-xs" title="Klicke ein beliebiges Element im Workspace an, um seinen Baustein sofort im Studio zu bearbeiten">
                    <i data-lucide="crosshair" class="w-3.5 h-3.5"></i> <span id="cds-inspector-btn-text">🎯 Element anklicken</span>
                  </button>
                  <button type="button" id="cds-dock-btn" onclick="toggleSettingsDockMode()" class="px-3 py-1.5 rounded-lg border border-zinc-900 dark:border-zinc-200 bg-[var(--secondary)] hover:bg-[var(--card)] text-[var(--foreground)] font-mono font-bold text-xs transition flex items-center gap-1.5 cursor-pointer shadow-xs">
                    <i data-lucide="panel-right" class="w-3.5 h-3.5"></i> 🗗 Rechts andocken (Live-Blick)
                  </button>
                  <button type="button" onclick="cdsSaveToServer(false)" class="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-mono font-bold text-xs transition flex items-center gap-1.5 cursor-pointer shadow-xs">
                    <i data-lucide="save" class="w-3.5 h-3.5"></i> Aktuelles Theme sichern
                  </button>
                </div>
              </div>

              <!-- Row 2: Active Theme Select, Save As New Theme, Export/Import, Mode Switcher -->
              <div class="grid grid-cols-1 lg:grid-cols-12 gap-2.5 items-center">
                <!-- Theme Select -->
                <div class="lg:col-span-4 flex items-center gap-1.5">
                  <label class="text-[10px] font-mono font-bold uppercase text-[var(--muted-foreground)] shrink-0">Theme:</label>
                  <select id="cds-theme-select" onchange="cdsSelectTheme(this.value)" class="flex-1 bg-[var(--card)] border border-[var(--border)] rounded-lg px-2.5 py-1.5 text-xs font-bold text-[var(--foreground)] cursor-pointer"></select>
                  <button type="button" onclick="cdsExportThemeJson()" title="Theme als JSON exportieren" class="p-1.5 rounded-lg border border-[var(--border)] bg-[var(--card)] hover:bg-[var(--secondary)] text-[var(--foreground)] cursor-pointer">
                    <i data-lucide="download" class="w-3.5 h-3.5"></i>
                  </button>
                  <label title="Theme aus JSON importieren" class="p-1.5 rounded-lg border border-[var(--border)] bg-[var(--card)] hover:bg-[var(--secondary)] text-[var(--foreground)] cursor-pointer">
                    <i data-lucide="upload" class="w-3.5 h-3.5"></i>
                    <input type="file" accept=".json" class="hidden" onchange="cdsImportThemeJson(this)">
                  </label>
                  <button type="button" onclick="cdsDeleteActiveTheme()" title="Aktives Theme löschen" class="p-1.5 rounded-lg border border-[var(--border)] bg-[var(--card)] hover:bg-red-500/10 text-red-500 cursor-pointer">
                    <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
                  </button>
                </div>

                <!-- Save as new theme -->
                <div class="lg:col-span-5 flex items-center gap-1.5">
                  <input type="text" id="cds-new-theme-name" placeholder="Neuer Theme-Name (speichert Hell + Dunkel als Paar)..." class="flex-1 bg-[var(--card)] border border-[var(--border)] rounded-lg px-2.5 py-1.5 text-xs text-[var(--foreground)]">
                  <button type="button" onclick="cdsSaveAsNewTheme()" class="px-3 py-1.5 rounded-lg bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900 font-bold text-xs transition cursor-pointer shrink-0 shadow-xs">
                    + Als Theme speichern
                  </button>
                </div>

                <!-- Mode Switcher (Hell / Dunkel) -->
                <div class="lg:col-span-3 flex items-center gap-1.5">
                  <button type="button" id="cds-mode-light" onclick="cdsSetMode('light')" class="flex-1 flex items-center justify-center gap-1.5 py-1.5 px-3 rounded-lg border text-xs font-bold transition cursor-pointer">
                    <span>☀️</span> Hell
                  </button>
                  <button type="button" id="cds-mode-dark" onclick="cdsSetMode('dark')" class="flex-1 flex items-center justify-center gap-1.5 py-1.5 px-3 rounded-lg border text-xs font-bold transition cursor-pointer">
                    <span>🌙</span> Dunkel
                  </button>
                </div>
              </div>
            </div>"""

new_top_bar = """            <!-- Top Bar: Theme Manager + Light/Dark Switch + Live-Dock (Clean & Simple) -->
            <div class="border border-[var(--border)] rounded-xl p-3 bg-[var(--background)] space-y-2.5 shadow-xs">
              <div class="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--border)] pb-2.5">
                <div class="flex items-center gap-2">
                  <span class="px-2 py-0.5 rounded bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900 font-mono font-bold text-[10px] uppercase">16-Bausteine Engine</span>
                  <span class="text-xs font-bold text-[var(--foreground)]">Zentrales Komponenten-Design &amp; Dual-Themes (Hell + Dunkel)</span>
                </div>
                <div class="flex items-center gap-2">
                  <button type="button" id="cds-inspector-btn" onclick="cdsToggleInspectorMode()" class="px-3 py-1.5 rounded-lg border border-indigo-500/40 bg-indigo-500/10 hover:bg-indigo-500/20 text-indigo-600 dark:text-indigo-400 font-mono font-bold text-xs transition flex items-center gap-1.5 cursor-pointer shadow-xs" title="Klicke ein beliebiges Element im Workspace an, um seinen Baustein sofort im Studio zu bearbeiten">
                    <i data-lucide="crosshair" class="w-3.5 h-3.5"></i> <span id="cds-inspector-btn-text">🎯 Element anklicken</span>
                  </button>
                  <button type="button" id="cds-dock-btn" onclick="toggleSettingsDockMode()" class="px-3 py-1.5 rounded-lg border border-zinc-900 dark:border-zinc-200 bg-[var(--secondary)] hover:bg-[var(--card)] text-[var(--foreground)] font-mono font-bold text-xs transition flex items-center gap-1.5 cursor-pointer shadow-xs">
                    <i data-lucide="panel-right" class="w-3.5 h-3.5"></i> 🗗 Rechts andocken
                  </button>
                </div>
              </div>

              <!-- Row 2: Theme Select, Save As New Theme, Mode Switcher -->
              <div class="grid grid-cols-1 lg:grid-cols-12 gap-2.5 items-center">
                <!-- Theme Select & Export/Import -->
                <div class="lg:col-span-5 flex items-center gap-1.5">
                  <label class="text-[10px] font-mono font-bold uppercase text-[var(--muted-foreground)] shrink-0">Theme:</label>
                  <select id="cds-theme-select" onchange="cdsSelectTheme(this.value)" class="flex-1 bg-[var(--card)] border border-[var(--border)] rounded-lg px-2.5 py-1.5 text-xs font-bold text-[var(--foreground)] cursor-pointer"></select>
                  <button type="button" onclick="cdsExportThemeJson()" title="Theme exportieren" class="p-1.5 rounded-lg border border-[var(--border)] bg-[var(--card)] hover:bg-[var(--secondary)] text-[var(--foreground)] cursor-pointer">
                    <i data-lucide="download" class="w-3.5 h-3.5"></i>
                  </button>
                  <label title="Theme importieren" class="p-1.5 rounded-lg border border-[var(--border)] bg-[var(--card)] hover:bg-[var(--secondary)] text-[var(--foreground)] cursor-pointer">
                    <i data-lucide="upload" class="w-3.5 h-3.5"></i>
                    <input type="file" accept=".json" class="hidden" onchange="cdsImportThemeJson(this)">
                  </label>
                  <button type="button" onclick="cdsDeleteActiveTheme()" title="Theme löschen" class="p-1.5 rounded-lg border border-[var(--border)] bg-[var(--card)] hover:bg-red-500/10 text-red-500 cursor-pointer">
                    <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
                  </button>
                </div>

                <!-- Save as new theme -->
                <div class="lg:col-span-4 flex items-center gap-1.5">
                  <input type="text" id="cds-new-theme-name" placeholder="Neuer Theme-Name..." class="flex-1 bg-[var(--card)] border border-[var(--border)] rounded-lg px-2.5 py-1.5 text-xs text-[var(--foreground)]">
                  <button type="button" onclick="cdsSaveAsNewTheme()" class="px-3 py-1.5 rounded-lg bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900 font-bold text-xs transition cursor-pointer shrink-0 shadow-xs">
                    + Speichern
                  </button>
                </div>

                <!-- Mode Switcher (Hell / Dunkel) -->
                <div class="lg:col-span-3 flex items-center gap-1.5">
                  <button type="button" id="cds-mode-light" onclick="cdsSetMode('light')" class="flex-1 flex items-center justify-center gap-1.5 py-1.5 px-3 rounded-lg border text-xs font-bold transition cursor-pointer">
                    <span>☀️</span> Hell
                  </button>
                  <button type="button" id="cds-mode-dark" onclick="cdsSetMode('dark')" class="flex-1 flex items-center justify-center gap-1.5 py-1.5 px-3 rounded-lg border text-xs font-bold transition cursor-pointer">
                    <span>🌙</span> Dunkel
                  </button>
                </div>
              </div>
            </div>"""

# 3. Add Special Panel for Logo Upload right under cds-kanban-columns-special
special_kanban_target = """                <!-- SPECIAL PANEL FOR #07 KANBAN COLUMNS (Manual 5-Column Color Picker) -->
                <div id="cds-kanban-columns-special" class="hidden p-3 rounded-xl border-2 border-zinc-900 dark:border-zinc-200 bg-[var(--secondary)]/40 space-y-2.5">
                  <div class="flex items-center justify-between">
                    <div>
                      <h6 class="text-xs font-bold uppercase font-mono text-[var(--foreground)]">🎨 Manuelle Farbsteuerung aller 5 Kanban-Spalten (Mission Control &amp; Operations)</h6>
                      <p class="text-[10px] text-[var(--muted-foreground)]">Jede der 5 Spalten ist hier einzeln in Hintergrundfarbe, Deckkraft (z.B. 10%), Rahmenfarbe und Header-Farbe steuerbar.</p>
                    </div>
                  </div>
                  <div id="cds-kanban-cols-grid" class="grid grid-cols-1 md:grid-cols-2 gap-2.5"></div>
                </div>"""

special_panels_replacement = """                <!-- SPECIAL PANEL FOR #07 KANBAN COLUMNS (Manual 5-Column Color Picker) -->
                <div id="cds-kanban-columns-special" class="hidden p-3 rounded-xl border-2 border-zinc-900 dark:border-zinc-200 bg-[var(--secondary)]/40 space-y-2.5">
                  <div class="flex items-center justify-between">
                    <div>
                      <h6 class="text-xs font-bold uppercase font-mono text-[var(--foreground)]">🎨 Manuelle Farbsteuerung aller 5 Kanban-Spalten (Mission Control &amp; Operations)</h6>
                      <p class="text-[10px] text-[var(--muted-foreground)]">Jede der 5 Spalten ist hier einzeln in Hintergrundfarbe, Deckkraft (z.B. 10%), Rahmenfarbe und Header-Farbe steuerbar.</p>
                    </div>
                  </div>
                  <div id="cds-kanban-cols-grid" class="grid grid-cols-1 md:grid-cols-2 gap-2.5"></div>
                </div>

                <!-- SPECIAL PANEL FOR #16 FIRMENLOGO (EIGENES MODUL) -->
                <div id="cds-logo-special" class="hidden p-3.5 rounded-xl border border-[var(--border)] bg-[var(--card)] space-y-3">
                  <div class="flex items-center justify-between border-b border-[var(--border)] pb-2">
                    <div>
                      <h6 class="text-xs font-bold uppercase font-mono text-[var(--foreground)]">🖼️ Firmenlogo Bilddatei &amp; Reset</h6>
                      <p class="text-[10.5px] text-[var(--muted-foreground)]">Lade hier ein eigenes Logo für Sidebar oben links hoch oder setze es auf das Archon OS Standardlogo zurück.</p>
                    </div>
                  </div>
                  <div class="flex flex-wrap items-center gap-3">
                    <label class="cursor-pointer bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900 hover:opacity-90 font-bold px-3.5 py-1.5 rounded-lg text-xs transition shadow-sm text-center flex items-center gap-1.5">
                      <i data-lucide="image" class="w-3.5 h-3.5"></i> Bild auswählen...
                      <input type="file" id="crm-logo-file-input" accept="image/*" class="hidden" onchange="handleCrmLogoUpload(event)">
                    </label>
                    <button type="button" onclick="resetCrmLogo()" class="bg-[var(--secondary)] hover:bg-red-500/10 hover:border-red-500/40 text-[var(--foreground)] hover:text-red-500 border border-[var(--border)] font-bold px-3.5 py-1.5 rounded-lg text-xs transition text-center cursor-pointer flex items-center gap-1.5">
                      <i data-lucide="rotate-ccw" class="w-3.5 h-3.5"></i> Auf Standard-Logo zurücksetzen
                    </button>
                  </div>
                </div>"""

# Normalize and execute replacements
norm_html = html.replace("\r\n", "\n")
norm_old_logo_box = old_logo_box.replace("\r\n", "\n")
norm_old_top_bar = old_top_bar.replace("\r\n", "\n")
norm_new_top_bar = new_top_bar.replace("\r\n", "\n")
norm_special_kanban = special_kanban_target.replace("\r\n", "\n")
norm_special_panels = special_panels_replacement.replace("\r\n", "\n")

if norm_old_logo_box in norm_html:
    norm_html = norm_html.replace(norm_old_logo_box, "", 1)
    print("Removed old logo box above studio")
else:
    print("WARNING: old_logo_box not found")

if norm_old_top_bar in norm_html:
    norm_html = norm_html.replace(norm_old_top_bar, norm_new_top_bar, 1)
    print("Cleaned Top Bar (removed duplicate save button & streamlined layout)")
else:
    print("WARNING: old_top_bar not found")

if norm_special_kanban in norm_html:
    norm_html = norm_html.replace(norm_special_kanban, norm_special_panels, 1)
    print("Added #cds-logo-special panel")
else:
    print("WARNING: special_kanban_target not found")

with open("static/views/system_settings_modal.html", "w", encoding="utf-8") as f:
    f.write(norm_html)
print("Updated static/views/system_settings_modal.html successfully!")
