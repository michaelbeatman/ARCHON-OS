with open("static/js/component_design_studio.js", "r", encoding="utf-8") as f:
    js = f.read()

# 1. Add os-logo to ARCHON_15_COMPONENTS
target_comp_15 = """  {
    id: "os-modal",
    num: "15",
    name: "Modals & Personalakte",
    icon: "app-window",
    desc: "Dialog-Fenster, Systemeinstellungen & Digitale Personalakte",
    where: "Zentrale Popups (#system-settings-modal-card) und Digitale Personalakte (.pa-modal-shell)",
    selectors: {
      normal: ".pa-modal-shell, #system-settings-modal-card, .os-modal",
      hover: ".os-modal:hover",
      active: ".os-modal.is-active"
    }
  }
];"""

new_comp_15_16 = """  {
    id: "os-modal",
    num: "15",
    name: "Modals & Personalakte",
    icon: "app-window",
    desc: "Dialog-Fenster, Systemeinstellungen & Digitale Personalakte",
    where: "Zentrale Popups (#system-settings-modal-card) und Digitale Personalakte (.pa-modal-shell)",
    selectors: {
      normal: ".pa-modal-shell, #system-settings-modal-card, .os-modal",
      hover: ".os-modal:hover",
      active: ".os-modal.is-active"
    }
  },
  {
    id: "os-logo",
    num: "16",
    name: "Firmenlogo (Oben Links)",
    icon: "image",
    desc: "Logo & Branding der linken Sidebar (Bilddatei, Größe, Polsterung & Reset)",
    where: "Linke Sidebar oben (#sidebar-logo-header, #sidebar-logo-img, #sidebar-logo-wrapper)",
    selectors: {
      normal: "#sidebar-logo-header, #sidebar-logo-wrapper, #sidebar-logo-img, .os-logo",
      hover: "#sidebar-logo-header:hover, .os-logo:hover",
      active: ".os-logo.is-active"
    }
  }
];"""

# 2. Add logo panel toggle in cdsRenderUI
target_render_kanban = """  // 5. Show/Hide Special Kanban 5-Column Manual Editor when os-kanban-col is selected
  const kanbanPanel = document.getElementById("cds-kanban-columns-special");
  if (kanbanPanel) {
    kanbanPanel.classList.toggle("hidden", cdsSelectedComp !== "os-kanban-col");
    if (cdsSelectedComp === "os-kanban-col") {
      cdsRenderKanbanColorsPanel();
    }
  }"""

new_render_special = """  // 5. Show/Hide Special Panels (Kanban Columns #07 & Firmenlogo #16)
  const kanbanPanel = document.getElementById("cds-kanban-columns-special");
  if (kanbanPanel) {
    kanbanPanel.classList.toggle("hidden", cdsSelectedComp !== "os-kanban-col");
    if (cdsSelectedComp === "os-kanban-col") {
      cdsRenderKanbanColorsPanel();
    }
  }

  const logoPanel = document.getElementById("cds-logo-special");
  if (logoPanel) {
    logoPanel.classList.toggle("hidden", cdsSelectedComp !== "os-logo");
  }"""

# 3. Add preview for os-logo in cdsUpdateLivePreview
target_preview_modal = """  // Modul 15: Modals & Personalakte
  else if (comp === "os-modal") {
    box.innerHTML = `
      <div class="os-modal pa-modal-shell p-3 rounded-2xl border w-full max-w-sm mx-auto space-y-2 select-none shadow-lg bg-[var(--card)]">
        <div class="flex items-center justify-between pb-1.5 border-b border-[var(--border)]">
          <span class="text-xs font-bold flex items-center gap-1.5">
            <span>📋</span> Dialog-Fenster & Personalakte
          </span>
          <span class="text-[10px] font-mono px-1.5 py-0.2 rounded bg-[var(--secondary)]">Modal</span>
        </div>
        <p class="text-[11px] text-[var(--muted-foreground)]">
          Vorschau des Modal-Körpers für Dialoge und Detailansichten.
        </p>
      </div>
    `;
  }"""

new_preview_modal_logo = """  // Modul 15: Modals & Personalakte
  else if (comp === "os-modal") {
    box.innerHTML = `
      <div class="os-modal pa-modal-shell p-3 rounded-2xl border w-full max-w-sm mx-auto space-y-2 select-none shadow-lg bg-[var(--card)]">
        <div class="flex items-center justify-between pb-1.5 border-b border-[var(--border)]">
          <span class="text-xs font-bold flex items-center gap-1.5">
            <span>📋</span> Dialog-Fenster & Personalakte
          </span>
          <span class="text-[10px] font-mono px-1.5 py-0.2 rounded bg-[var(--secondary)]">Modal</span>
        </div>
        <p class="text-[11px] text-[var(--muted-foreground)]">
          Vorschau des Modal-Körpers für Dialoge und Detailansichten.
        </p>
      </div>
    `;
  }
  // Modul 16: Firmenlogo (Oben Links)
  else if (comp === "os-logo") {
    const currentLogo = localStorage.getItem("archon_logo_url") || "/static/archon_os_logo.png?v=20261007";
    box.innerHTML = `
      <div class="os-logo p-3 rounded-xl border flex flex-col items-center justify-center gap-2 max-w-xs mx-auto select-none bg-[var(--card)] shadow-xs w-full">
        <div class="w-full flex items-center justify-between text-[10px] font-mono text-[var(--muted-foreground)] border-b border-[var(--border)] pb-1">
          <span>FIRMENLOGO VORSCHAU</span>
          <span class="text-emerald-500 font-bold">Aktiv</span>
        </div>
        <div class="p-2 rounded-lg bg-black/10 dark:bg-black/40 flex items-center justify-center min-h-[50px] w-full">
          <img id="crm-modal-logo-preview" src="${currentLogo}" onerror="this.src='/static/archon_os_logo.png';" class="max-h-10 max-w-[190px] object-contain transition-transform hover:scale-105" alt="Logo Vorschau" />
        </div>
        <span class="text-[9.5px] font-mono text-[var(--muted-foreground)]">Klicke unten auf 'Bild auswählen...', um das Logo zu ändern</span>
      </div>
    `;
  }"""

# Execute substitutions
norm_js = js.replace("\r\n", "\n")
norm_target_comp = target_comp_15.replace("\r\n", "\n")
norm_new_comp = new_comp_15_16.replace("\r\n", "\n")

if norm_target_comp in norm_js:
    norm_js = norm_js.replace(norm_target_comp, norm_new_comp, 1)
    print("Added os-logo (Modul 16) to ARCHON_15_COMPONENTS")
else:
    print("WARNING: target_comp_15 not found")

norm_target_kanban = target_render_kanban.replace("\r\n", "\n")
norm_new_special = new_render_special.replace("\r\n", "\n")
if norm_target_kanban in norm_js:
    norm_js = norm_js.replace(norm_target_kanban, norm_new_special, 1)
    print("Added special panel toggle for os-logo")
else:
    print("WARNING: target_render_kanban not found")

norm_target_modal = target_preview_modal.replace("\r\n", "\n")
norm_new_modal_logo = new_preview_modal_logo.replace("\r\n", "\n")
if norm_target_modal in norm_js:
    norm_js = norm_js.replace(norm_target_modal, norm_new_modal_logo, 1)
    print("Added preview for os-logo (Modul 16)")
else:
    print("WARNING: target_preview_modal not found")

with open("static/js/component_design_studio.js", "w", encoding="utf-8") as f:
    f.write(norm_js)
print("Updated static/js/component_design_studio.js successfully!")
