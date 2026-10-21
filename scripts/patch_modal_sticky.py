with open("static/views/system_settings_modal.html", "r", encoding="utf-8") as f:
    html = f.read()

target = """              <!-- Right Column: Active Component Inspector & Full CSS Studio -->
              <div class="lg:col-span-8 border border-[var(--border)] rounded-xl p-3 bg-[var(--background)] space-y-3 max-h-[68vh] overflow-y-auto custom-scrollbar">
                <!-- Selected Component Info + Reset Button -->
                <div class="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--border)] pb-2.5">
                  <div>
                    <div class="flex items-center gap-2">
                      <h5 id="cds-active-comp-title" class="text-sm font-bold text-[var(--foreground)]">04. Insel-Container (Außenkarte)</h5>
                      <code id="cds-active-comp-selector" class="px-2 py-0.5 rounded bg-[var(--secondary)] border border-[var(--border)] text-[10px] font-mono text-[var(--muted-foreground)]">.os-island</code>
                    </div>
                    <p id="cds-active-comp-desc" class="text-[11px] text-[var(--muted-foreground)]">Äußere Haupt-Container für Bereiche, Filterleisten und Sektionen</p>
                  </div>
                  <button type="button" onclick="cdsResetCurrentComponent()" class="px-2.5 py-1 rounded-lg border border-[var(--border)] bg-[var(--card)] hover:bg-red-500/10 hover:border-red-500/40 text-xs font-mono text-[var(--muted-foreground)] hover:text-red-500 transition flex items-center gap-1 cursor-pointer">
                    <i data-lucide="rotate-ccw" class="w-3 h-3"></i> Baustein zurücksetzen
                  </button>
                </div>

                <!-- Live Preview Box -->
                <div class="space-y-1">
                  <div class="flex items-center justify-between">
                    <span class="text-[10px] font-mono font-bold uppercase text-[var(--muted-foreground)]">Interaktive Live-Vorschau (Echtzeit)</span>
                    <span class="text-[10px] font-mono text-[var(--muted-foreground)]">Bewege die Maus über Elemente zum Testen von :hover</span>
                  </div>
                  <div id="cds-live-preview-stage" class="p-3 rounded-xl border border-[var(--border)] transition-all flex items-center justify-center min-h-[115px]"></div>
                </div>

                <!-- State Switcher: Normal | Hover (:hover) | Aktiv (.is-active) -->
                <div class="p-2 rounded-xl bg-[var(--secondary)]/60 border border-[var(--border)] space-y-1.5">
                  <div class="flex items-center justify-between">
                    <span class="text-[10px] font-mono font-bold uppercase text-[var(--foreground)]">Zustands-Editor (State-Switcher)</span>
                    <span class="text-[10px] font-mono text-[var(--muted-foreground)]">Wähle, für welchen Zustand die unteren Regler gelten</span>
                  </div>
                  <div class="flex items-center gap-2">
                    <button type="button" id="cds-state-btn-normal" onclick="cdsSelectState('normal')" class="flex-1 py-1.5 px-2.5 rounded-lg border text-xs font-mono font-bold transition cursor-pointer">
                      [ Normal ]
                    </button>
                    <button type="button" id="cds-state-btn-hover" onclick="cdsSelectState('hover')" class="flex-1 py-1.5 px-2.5 rounded-lg border text-xs font-mono font-bold transition cursor-pointer">
                      [ Hover (:hover) ]
                    </button>
                    <button type="button" id="cds-state-btn-active" onclick="cdsSelectState('active')" class="flex-1 py-1.5 px-2.5 rounded-lg border text-xs font-mono font-bold transition cursor-pointer">
                      [ Aktiv (.is-active) ]
                    </button>
                  </div>
                </div>"""

replacement = """              <!-- Right Column: Active Component Inspector & Full CSS Studio -->
              <div class="lg:col-span-8 border border-[var(--border)] rounded-xl p-3 bg-[var(--background)] space-y-3 max-h-[68vh] overflow-y-auto custom-scrollbar relative">
                
                <!-- STICKY TOP CONTAINER: Component Header, Live Preview & State Switcher (bleibt immer oben sichtbar beim Scrollen) -->
                <div class="sticky -top-3 z-20 bg-[var(--background)] pt-1 pb-2 border-b border-[var(--border)] space-y-2.5 shadow-sm backdrop-blur-md">
                  <!-- Selected Component Info + Where Used + Reset Button -->
                  <div class="flex flex-wrap items-center justify-between gap-2">
                    <div class="min-w-0 flex-1">
                      <div class="flex items-center gap-2 flex-wrap">
                        <h5 id="cds-active-comp-title" class="text-sm font-bold text-[var(--foreground)]">04. Insel-Container (Außenkarte)</h5>
                        <code id="cds-active-comp-selector" class="px-2 py-0.5 rounded bg-[var(--secondary)] border border-[var(--border)] text-[10px] font-mono text-[var(--muted-foreground)]">.os-island</code>
                      </div>
                      <p id="cds-active-comp-desc" class="text-[11px] text-[var(--muted-foreground)] truncate mt-0.5">Äußere Haupt-Container für Bereiche, Filterleisten und Sektionen</p>
                      <!-- Wo wird das angewendet? Kontext-Badge -->
                      <div class="flex items-center gap-1.5 mt-1">
                        <span class="text-[9.5px] font-mono uppercase font-bold text-indigo-500 dark:text-indigo-400 bg-indigo-500/10 border border-indigo-500/20 px-1.5 py-0.2 rounded shrink-0">Wird angewendet in:</span>
                        <span id="cds-active-comp-usage" class="text-[10px] font-medium text-[var(--foreground)] truncate">Alle Inhalts-Karten, Filter-Container, Dialoge & Listen</span>
                      </div>
                    </div>
                    <button type="button" onclick="cdsResetCurrentComponent()" class="px-2.5 py-1 rounded-lg border border-[var(--border)] bg-[var(--card)] hover:bg-red-500/10 hover:border-red-500/40 text-xs font-mono text-[var(--muted-foreground)] hover:text-red-500 transition flex items-center gap-1 cursor-pointer shrink-0">
                      <i data-lucide="rotate-ccw" class="w-3 h-3"></i> Zurücksetzen
                    </button>
                  </div>

                  <!-- Live Preview Box (Individuelle Baustein-Vorschau) -->
                  <div class="space-y-1">
                    <div class="flex items-center justify-between">
                      <span class="text-[10px] font-mono font-bold uppercase text-[var(--muted-foreground)] flex items-center gap-1">
                        <span class="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
                        Interaktive Baustein-Vorschau (Echtzeit)
                      </span>
                      <span class="text-[9.5px] font-mono text-[var(--muted-foreground)]">Maus drüberfahren (:hover) oder klicken</span>
                    </div>
                    <div id="cds-live-preview-stage" class="p-2.5 rounded-xl border border-[var(--border)] transition-all flex items-center justify-center min-h-[90px] max-h-[160px] overflow-hidden bg-[var(--card)]/50 shadow-inner"></div>
                  </div>

                  <!-- State Switcher: Normal | Hover (:hover) | Aktiv (.is-active) -->
                  <div class="p-1.5 rounded-xl bg-[var(--secondary)]/60 border border-[var(--border)] space-y-1">
                    <div class="flex items-center justify-between px-1">
                      <span class="text-[9.5px] font-mono font-bold uppercase text-[var(--foreground)]">Zustands-Editor</span>
                      <span class="text-[9.5px] font-mono text-[var(--muted-foreground)]">Wähle Zustand für die Regler unten:</span>
                    </div>
                    <div class="flex items-center gap-1.5">
                      <button type="button" id="cds-state-btn-normal" onclick="cdsSelectState('normal')" class="flex-1 py-1 px-2 rounded-lg border text-xs font-mono font-bold transition cursor-pointer">
                        Normal
                      </button>
                      <button type="button" id="cds-state-btn-hover" onclick="cdsSelectState('hover')" class="flex-1 py-1 px-2 rounded-lg border text-xs font-mono font-bold transition cursor-pointer">
                        Hover (:hover)
                      </button>
                      <button type="button" id="cds-state-btn-active" onclick="cdsSelectState('active')" class="flex-1 py-1 px-2 rounded-lg border text-xs font-mono font-bold transition cursor-pointer">
                        Aktiv (.is-active)
                      </button>
                    </div>
                  </div>
                </div>"""

# Test direct or normalized replacement
norm_html = html.replace("\r\n", "\n")
norm_target = target.replace("\r\n", "\n")
norm_replacement = replacement.replace("\r\n", "\n")

if norm_target in norm_html:
    norm_html = norm_html.replace(norm_target, norm_replacement, 1)
    with open("static/views/system_settings_modal.html", "w", encoding="utf-8") as f:
        f.write(norm_html)
    print("SUCCESS: system_settings_modal.html updated with sticky header and usage badge!")
else:
    print("ERROR: Target not found in system_settings_modal.html")
