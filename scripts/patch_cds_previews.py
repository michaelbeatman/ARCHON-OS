import re

with open("static/js/component_design_studio.js", "r", encoding="utf-8") as f:
    js = f.read()

# 1. Update ARCHON_15_COMPONENTS to include 'where' property
old_comps_start = 'const ARCHON_15_COMPONENTS = ['
old_comps_end = 'const KANBAN_COLUMN_KEYS = ['

new_comps_code = """const ARCHON_15_COMPONENTS = [
  {
    id: "os-workspace",
    num: "01",
    name: "Workspace & Insel-Raster",
    icon: "layout-grid",
    desc: "Seitenhintergrund, äußerer Abstand, Insel-Abstand (gap) & Grundschrift",
    where: "Gesamte Arbeitsfläche, Viewport-Hintergrund (#main-viewport-scroll) & Spalten-Abstände",
    selectors: {
      normal: "body, #main-viewport-scroll, .os-workspace",
      hover: ".os-workspace:hover",
      active: ".os-workspace.is-active",
      gapTarget: "#view-mission-control .grid, #view-agent-profiles > .grid, #view-inbox .grid, #view-library .grid, .os-island-grid"
    }
  },
  {
    id: "os-sidebar",
    num: "02",
    name: "Sidebar & Hauptmenü",
    icon: "panel-left",
    desc: "Linke Navigationsleiste: Breite, Hintergrund, Rahmen & Trennlinien",
    where: "Linke Menüleiste (aside.theme-sidebar) inkl. Logo-Header und Trennlinie zum Content",
    selectors: {
      normal: "aside.theme-sidebar, #main-sidebar, .os-sidebar",
      hover: "aside.theme-sidebar:hover, .os-sidebar:hover",
      active: ".os-sidebar.is-active"
    }
  },
  {
    id: "os-nav-btn",
    num: "03",
    name: "Navigations- & Tab-Buttons",
    icon: "mouse-pointer-click",
    desc: "Menü-Einträge & Sub-Tabs (Normal, Hover & Aktiver Kasten mit Rahmen/Schatten)",
    where: "Sidebar-Menüpunkte (.archon-nav-item), Kader-Header-Kacheln & Operations Sub-Tabs",
    selectors: {
      normal: ".archon-nav-item, .agent-header-tile > div.tile-icon-wrap, .ops-subtab-btn, .os-nav-btn",
      hover: ".archon-nav-item:not(.nav-item-active):hover, .agent-header-tile:not(.active-cadre-tab) > div.tile-icon-wrap:hover, .ops-subtab-btn:hover, .os-nav-btn:hover",
      active: ".archon-nav-item.nav-item-active, .agent-header-tile.active-cadre-tab > div.tile-icon-wrap, .agent-header-tile > div.tile-icon-wrap.active-tile, .ops-subtab-btn.active-ops-tab, .os-nav-btn.is-active"
    }
  },
  {
    id: "os-island",
    num: "04",
    name: "Haupt-Insel / Container-Panel",
    icon: "box",
    desc: "Große Inhalts-Inseln & Container-Boxen auf allen Seiten",
    where: "Alle großen Arbeits-Karten (.shadcn-card, .prof-panel-card, .theme-card) in MC, Kader, Inbox & Library",
    selectors: {
      normal: ".shadcn-card, .prof-panel-card, .theme-card, .os-island",
      hover: ".shadcn-card:hover, .prof-panel-card:hover, .theme-card:hover, .os-island:hover",
      active: ".os-island.is-active"
    }
  },
  {
    id: "os-island-header",
    num: "05",
    name: "Insel-Header & Topbars",
    icon: "heading",
    desc: "Kopfzeilen der Ansichten und Inseln inkl. Titel & Trennlinie",
    where: "Kopfzeilen aller 3 Säulen (#mission-control-header-bar, #ops-header-bar, #inbox-header-bar, #master-chat-header-bar)",
    selectors: {
      normal: "#mission-control-header-bar, #ops-header-bar, #inbox-header-bar, #master-chat-header-bar, .os-island-header",
      hover: ".os-island-header:hover",
      active: ".os-island-header.is-active"
    }
  },
  {
    id: "os-card",
    num: "06",
    name: "Innere Karte / Listen-Element",
    icon: "credit-card",
    desc: "Karten innerhalb einer Insel (Agenten-Karten, Inbox-Einträge, Sub-Cards)",
    where: "Agenten-Liste links (.prof-list-item), E-Mail-/Telegram-Einträge in Inbox & Sub-Cards",
    selectors: {
      normal: ".prof-list-item, .shadcn-card-subtle, .daw-card, #inbox-list-intern > div, #inbox-list-email > div, #inbox-list-telegram > div, .os-card",
      hover: ".prof-list-item:hover, .shadcn-card-subtle:hover, .daw-card:hover, .os-card:hover",
      active: ".prof-list-item.selected-item, .os-card.is-active"
    }
  },
  {
    id: "os-kanban-col",
    num: "07",
    name: "Kanban-Spalten (+ 5 Spaltenfarben)",
    icon: "columns",
    desc: "Spalten-Geometrie, Zwischenraum (gap) & manuelle Farben für alle 5 Spalten",
    where: "Die 5 Status-Spalten im Mission Control & Operations Kanban (#mc-kanban-col-*, #ops-kanban-columns-container)",
    selectors: {
      normal: ".os-kanban-col, #ops-kanban-columns-container > div.w-80, #mc-kanban-col-todo, #mc-kanban-col-inprogress, #mc-kanban-col-review, #mc-kanban-col-blocked, #mc-kanban-col-done",
      hover: ".os-kanban-col:hover",
      active: ".os-kanban-col.is-active",
      gapTarget: "#ops-kanban-columns-container, #mc-kanban-grid"
    }
  },
  {
    id: "os-kanban-card",
    num: "08",
    name: "Kanban-Ticket",
    icon: "CheckSquare",
    desc: "Aufgaben-Tickets in Mission Control & Operations Kanban",
    where: "Aufgaben-Karten innerhalb aller Kanban-Spalten (#mc-col-* > div, #ops-kanban-columns-container .group)",
    selectors: {
      normal: ".os-kanban-card, #ops-kanban-columns-container .group, #mc-col-todo > div, #mc-col-inprogress > div, #mc-col-review > div, #mc-col-blocked > div, #mc-col-done > div",
      hover: ".os-kanban-card:hover, #ops-kanban-columns-container .group:hover",
      active: ".os-kanban-card.is-active"
    }
  },
  {
    id: "os-btn-primary",
    num: "09",
    name: "Primär- & Aktions-Buttons",
    icon: "zap",
    desc: "Haupt-Buttons (Speichern, + Neu, Ausführen)",
    where: "Wichtigste CTA-Buttons im System (.shadcn-btn-primary, Speichern-Buttons, Neue Aufgabe erstellen)",
    selectors: {
      normal: ".shadcn-btn-primary, .os-btn-primary",
      hover: ".shadcn-btn-primary:hover, .os-btn-primary:hover",
      active: ".shadcn-btn-primary:active, .os-btn-primary.is-active"
    }
  },
  {
    id: "os-btn-secondary",
    num: "10",
    name: "Sekundär- & Icon-Buttons",
    icon: "square",
    desc: "Outline-Buttons, Sync-Buttons & Werkzeug-Buttons",
    where: "Outline-Buttons (.shadcn-btn-outline), Werkzeug-Buttons, Filter-Trigger & Sync-Buttons",
    selectors: {
      normal: ".shadcn-btn-outline, .os-btn-secondary",
      hover: ".shadcn-btn-outline:hover, .os-btn-secondary:hover",
      active: ".shadcn-btn-outline:active, .os-btn-secondary.is-active"
    }
  },
  {
    id: "os-input",
    num: "11",
    name: "Eingabefelder & Dropdowns",
    icon: "text-cursor-input",
    desc: "Suchfelder, Textfelder, Textareas & Select-Menüs",
    where: "Suchleiste im Agenten-Kader, Formularfelder, Filter-Dropdowns, Textfelder & Prompts",
    selectors: {
      normal: ".shadcn-input, .os-input, input:not([type='checkbox']):not([type='radio']):not([type='range']):not([type='color']), select, textarea",
      hover: ".shadcn-input:hover, .os-input:hover",
      active: ".shadcn-input:focus, .os-input:focus, input:focus, select:focus, textarea:focus"
    }
  },
  {
    id: "os-badge",
    num: "12",
    name: "Tags & Status-Badges",
    icon: "tag",
    desc: "Skill-Tags, Rollen-Badges & Status-Kennzeichnungen",
    where: "Skill-Tags im Agenten-Profil (.archon-tag, .prof-skill-tag), Status-Chips & Kategorie-Markierungen",
    selectors: {
      normal: ".shadcn-badge, .archon-tag, .prof-skill-badge, .prof-skill-tag, .os-badge",
      hover: ".archon-tag:hover, .os-badge:hover",
      active: ".os-badge.is-active"
    }
  },
  {
    id: "os-pill",
    num: "13",
    name: "Filter-Pills & Domänen-Filter",
    icon: "filter",
    desc: "Domänen-Filter-Buttons (Inaktiv, Hover & Aktiv)",
    where: "Domänen-Filterleiste über der Agentenliste (.prof-cat-btn: Inaktiv, Hover & Ausgewählt)",
    selectors: {
      normal: ".prof-cat-btn, .os-pill",
      hover: ".prof-cat-btn:hover, .os-pill:hover",
      active: ".prof-cat-btn.active-cat, .prof-cat-btn[data-active='true'], .os-pill.is-active"
    }
  },
  {
    id: "os-console",
    num: "14",
    name: "Chat- & Stream-Konsole",
    icon: "terminal",
    desc: "Master-Chat, Agenten-Chat, Live-Audit & Terminal-Fenster",
    where: "Live-Audit-Stream im Cockpit (#mc-audit-stream), Master-Chat-Verlauf & Konsolenbereiche",
    selectors: {
      normal: "#mc-audit-stream, #agent-tab-chat-messages, #master-chat-messages, .os-console",
      hover: ".os-console:hover",
      active: ".os-console.is-active"
    }
  },
  {
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
];\n\n"""

# Replace ARCHON_15_COMPONENTS definition
start_idx = js.find(old_comps_start)
end_idx = js.find(old_comps_end)
if start_idx != -1 and end_idx != -1:
    js = js[:start_idx] + new_comps_code + js[end_idx:]
    print("Updated ARCHON_15_COMPONENTS definition with 'where' metadata")
else:
    print("ERROR finding ARCHON_15_COMPONENTS range")

# 2. Update cdsRenderUI to set #cds-active-comp-usage
usage_target = """  const descEl = document.getElementById("cds-active-comp-desc");
  const selEl = document.getElementById("cds-active-comp-selector");
  if (titleEl) titleEl.textContent = `${activeCompObj.num}. ${activeCompObj.name}`;
  if (descEl) descEl.textContent = activeCompObj.desc;
  if (selEl) selEl.textContent = activeCompObj.selectors[cdsSelectedState] || `.${activeCompObj.id}`;"""

usage_replacement = """  const descEl = document.getElementById("cds-active-comp-desc");
  const selEl = document.getElementById("cds-active-comp-selector");
  const usageEl = document.getElementById("cds-active-comp-usage");
  if (titleEl) titleEl.textContent = `${activeCompObj.num}. ${activeCompObj.name}`;
  if (descEl) descEl.textContent = activeCompObj.desc;
  if (selEl) selEl.textContent = activeCompObj.selectors[cdsSelectedState] || `.${activeCompObj.id}`;
  if (usageEl) usageEl.textContent = activeCompObj.where || "Systemweiter Baustein";"""

if usage_target in js:
    js = js.replace(usage_target, usage_replacement, 1)
    print("Updated cdsRenderUI to populate #cds-active-comp-usage")
else:
    print("ERROR finding usage_target in js")

# 3. Replace cdsUpdateLivePreview with specialized templates for all 15 modules
preview_func_start = "function cdsUpdateLivePreview() {"
preview_func_end = "// ========================================================================="

new_preview_func = """function cdsUpdateLivePreview() {
  const box = document.getElementById("cds-live-preview-stage");
  if (!box) return;
  const block = cdsGetActiveModeBlock();
  const wsProps = (block.components["os-workspace"] && block.components["os-workspace"].normal) || {};
  box.style.backgroundColor = wsProps["background-color"] || (cdsStore.active_mode === "dark" ? "#090d16" : "#f8fafc");
  box.style.color = wsProps["color"] || (cdsStore.active_mode === "dark" ? "#f8fafc" : "#0f172a");

  const comp = cdsSelectedComp;

  // Modul 01: Workspace & Insel-Raster
  if (comp === "os-workspace") {
    box.innerHTML = `
      <div class="os-workspace p-3 rounded-lg border w-full flex flex-col gap-2 select-none">
        <div class="flex items-center justify-between text-xs font-mono font-bold">
          <span>🖥️ Workspace-Hintergrund & Grundraster</span>
          <span class="text-[10px] opacity-75">Layout-Vorschau</span>
        </div>
        <div class="grid grid-cols-3 gap-2">
          <div class="os-island p-2 rounded border text-[11px] text-center font-medium">Insel 1 (Raster)</div>
          <div class="os-island p-2 rounded border text-[11px] text-center font-medium">Insel 2 (Raster)</div>
          <div class="os-island p-2 rounded border text-[11px] text-center font-medium">Insel 3 (Raster)</div>
        </div>
      </div>
    `;
  }
  // Modul 02: Sidebar & Hauptmenü
  else if (comp === "os-sidebar") {
    box.innerHTML = `
      <div class="flex items-stretch border rounded-xl overflow-hidden w-full max-w-sm mx-auto h-[120px] select-none shadow-sm">
        <div class="os-sidebar theme-sidebar w-36 p-2 flex flex-col justify-between border-r shrink-0">
          <div>
            <div class="font-bold text-[11px] tracking-wider text-rose-500 font-cinzel mb-2">ARCHON OS</div>
            <div class="space-y-1">
              <div class="os-nav-btn text-[10px] px-2 py-1 rounded">Cockpit</div>
              <div class="os-nav-btn is-active text-[10px] px-2 py-1 rounded font-bold">Kader</div>
            </div>
          </div>
          <div class="text-[9px] opacity-60 font-mono">Sidebar v2.0</div>
        </div>
        <div class="flex-1 p-3 bg-[var(--card)]/40 flex items-center justify-center text-xs opacity-70">
          Haupt-Arbeitsbereich
        </div>
      </div>
    `;
  }
  // Modul 03: Navigations- & Tab-Buttons
  else if (comp === "os-nav-btn") {
    box.innerHTML = `
      <div class="flex flex-col gap-2 w-full max-w-md select-none">
        <div class="text-[10px] font-mono text-[var(--muted-foreground)]">3 Zustände: Inaktiv, Hover (Maus drüber) & Aktiv</div>
        <div class="flex items-center gap-2">
          <button type="button" class="os-nav-btn archon-nav-item flex-1 py-1.5 px-3 rounded-lg text-xs font-semibold border flex items-center gap-1.5">
            <span>⚙️ Inaktiv</span>
          </button>
          <button type="button" class="os-nav-btn archon-nav-item flex-1 py-1.5 px-3 rounded-lg text-xs font-semibold border flex items-center gap-1.5 hover:shadow-xs">
            <span>✨ Hover-Test</span>
          </button>
          <button type="button" class="os-nav-btn archon-nav-item is-active nav-item-active flex-1 py-1.5 px-3 rounded-lg text-xs font-bold border flex items-center gap-1.5 shadow-xs">
            <span>📌 Aktiv</span>
          </button>
        </div>
      </div>
    `;
  }
  // Modul 04: Haupt-Insel / Container-Panel
  else if (comp === "os-island") {
    box.innerHTML = `
      <div class="os-island shadcn-card p-3 rounded-xl border w-full max-w-md space-y-2 select-none shadow-sm">
        <div class="flex items-center justify-between pb-1.5 border-b border-[var(--border)]">
          <span class="text-xs font-bold">Haupt-Insel (Container-Panel)</span>
          <span class="text-[10px] font-mono px-2 py-0.5 rounded bg-[var(--secondary)]">Karten-Hülle</span>
        </div>
        <p class="text-[11px] text-[var(--muted-foreground)] leading-relaxed">
          Dies ist der Außenrahmen, der alle Dashboards, Ansichten und Bereiche in Archon OS umschließt.
        </p>
      </div>
    `;
  }
  // Modul 05: Insel-Header & Topbars
  else if (comp === "os-island-header") {
    box.innerHTML = `
      <div class="os-island p-0 rounded-xl border w-full max-w-md overflow-hidden select-none shadow-sm">
        <div class="os-island-header p-3 border-b flex items-center justify-between">
          <div class="flex items-center gap-2">
            <span class="w-2.5 h-2.5 rounded-full bg-emerald-500"></span>
            <span class="text-xs font-bold tracking-wide">MISSION CONTROL HEADER</span>
          </div>
          <div class="text-[10px] font-mono opacity-80">Live Telemetrie</div>
        </div>
        <div class="p-3 text-[11px] text-[var(--muted-foreground)] bg-[var(--card)]/30">
          Insel-Inhalt unterhalb der Kopfzeile
        </div>
      </div>
    `;
  }
  // Modul 06: Innere Karte / Listen-Element
  else if (comp === "os-card") {
    box.innerHTML = `
      <div class="grid grid-cols-2 gap-2.5 w-full max-w-md select-none">
        <div class="os-card prof-list-item p-2.5 rounded-xl border flex items-center gap-2">
          <div class="w-7 h-7 rounded-full bg-indigo-500/20 text-indigo-500 font-bold flex items-center justify-center text-xs">M</div>
          <div class="min-w-0">
            <div class="text-xs font-bold truncate">Micha (Chief)</div>
            <div class="text-[10px] text-[var(--muted-foreground)] truncate">Normaler Eintrag</div>
          </div>
        </div>
        <div class="os-card prof-list-item is-active selected-item p-2.5 rounded-xl border flex items-center gap-2 shadow-xs">
          <div class="w-7 h-7 rounded-full bg-emerald-500/20 text-emerald-500 font-bold flex items-center justify-center text-xs">A</div>
          <div class="min-w-0">
            <div class="text-xs font-bold truncate">Archon Guard</div>
            <div class="text-[10px] text-emerald-600 dark:text-emerald-400 font-bold truncate">Ausgewählt (Aktiv)</div>
          </div>
        </div>
      </div>
    `;
  }
  // Modul 07: Kanban-Spalten (+ 5 Spaltenfarben)
  else if (comp === "os-kanban-col") {
    const cols = block.kanban_columns || {};
    box.innerHTML = `
      <div class="grid grid-cols-5 gap-1.5 w-full select-none">
        ${KANBAN_COLUMN_KEYS.map(({ key, label }) => {
          const c = cols[key] || {};
          return `
            <div class="os-kanban-col rounded-xl p-1.5 border flex flex-col gap-1.5 shadow-2xs" style="background:${c.bg};border-color:${c.border}">
              <div class="px-1.5 py-1 rounded-lg text-[9.5px] font-bold truncate text-center" style="background:${c.header};color:${c.text}">${label.split(". ")[1]}</div>
              <div class="os-kanban-card p-1 rounded-md border text-[9.5px] text-center font-medium bg-[var(--card)]/90">Task</div>
            </div>
          `;
        }).join("")}
      </div>
    `;
  }
  // Modul 08: Kanban-Ticket
  else if (comp === "os-kanban-card") {
    box.innerHTML = `
      <div class="flex items-center gap-2.5 w-full max-w-md select-none">
        <div class="os-kanban-card p-2.5 rounded-xl border flex-1 space-y-1 bg-[var(--card)] shadow-xs">
          <div class="flex items-center justify-between text-[10px]">
            <span class="font-mono font-bold text-rose-500">TASK-104</span>
            <span class="text-[9px] px-1 py-0.2 rounded bg-amber-500/10 text-amber-500 font-mono">P1</span>
          </div>
          <div class="text-xs font-bold text-[var(--foreground)] truncate">Kernel Watchdog Loop</div>
          <div class="text-[10px] text-[var(--muted-foreground)]">30s Heartbeat Check</div>
        </div>
        <div class="os-kanban-card is-active p-2.5 rounded-xl border flex-1 space-y-1 bg-[var(--card)] shadow-sm">
          <div class="flex items-center justify-between text-[10px]">
            <span class="font-mono font-bold text-emerald-500">TASK-105</span>
            <span class="text-[9px] px-1 py-0.2 rounded bg-emerald-500/10 text-emerald-500 font-mono">Aktiv</span>
          </div>
          <div class="text-xs font-bold text-[var(--foreground)] truncate">E-Mail Sync Daemon</div>
          <div class="text-[10px] text-emerald-600 dark:text-emerald-400 font-bold">In Bearbeitung</div>
        </div>
      </div>
    `;
  }
  // Modul 09: Primär- & Aktions-Buttons
  else if (comp === "os-btn-primary") {
    box.innerHTML = `
      <div class="flex items-center gap-3 w-full max-w-md justify-center select-none">
        <button type="button" class="os-btn-primary shadcn-btn-primary px-4 py-2 rounded-xl text-xs font-bold shadow-sm flex items-center gap-1.5 cursor-pointer">
          <span>💾 Einstellungen Speichern</span>
        </button>
        <button type="button" class="os-btn-primary shadcn-btn-primary is-active px-4 py-2 rounded-xl text-xs font-bold shadow-md flex items-center gap-1.5 cursor-pointer">
          <span>⚡ Aktion Ausführen</span>
        </button>
      </div>
    `;
  }
  // Modul 10: Sekundär- & Icon-Buttons
  else if (comp === "os-btn-secondary") {
    box.innerHTML = `
      <div class="flex items-center gap-2.5 w-full max-w-md justify-center select-none">
        <button type="button" class="os-btn-secondary shadcn-btn-outline px-3 py-1.5 rounded-lg border text-xs font-medium flex items-center gap-1.5 cursor-pointer">
          <span>🔄 Sync</span>
        </button>
        <button type="button" class="os-btn-secondary shadcn-btn-outline px-3 py-1.5 rounded-lg border text-xs font-medium flex items-center gap-1.5 cursor-pointer">
          <span>❌ Abbrechen</span>
        </button>
        <button type="button" class="os-btn-secondary shadcn-btn-outline is-active px-3 py-1.5 rounded-lg border text-xs font-bold flex items-center gap-1.5 cursor-pointer">
          <span>🔍 Filter</span>
        </button>
      </div>
    `;
  }
  // Modul 11: Eingabefelder & Dropdowns
  else if (comp === "os-input") {
    box.innerHTML = `
      <div class="grid grid-cols-2 gap-2.5 w-full max-w-md select-none">
        <input type="text" value="🔍 Agenten oder Skills suchen..." class="os-input shadcn-input px-3 py-2 rounded-lg border text-xs w-full bg-[var(--background)]" />
        <select class="os-input shadcn-input px-3 py-2 rounded-lg border text-xs w-full bg-[var(--background)] cursor-pointer">
          <option>Dropdown-Auswahl...</option>
          <option>Option A</option>
          <option>Option B</option>
        </select>
      </div>
    `;
  }
  // Modul 12: Tags & Status-Badges
  else if (comp === "os-badge") {
    box.innerHTML = `
      <div class="flex flex-wrap items-center gap-2 justify-center w-full max-w-md select-none">
        <span class="os-badge archon-tag shadcn-badge px-2.5 py-1 rounded-md text-[11px] font-mono border">python</span>
        <span class="os-badge archon-tag shadcn-badge px-2.5 py-1 rounded-md text-[11px] font-mono border">docker</span>
        <span class="os-badge archon-tag shadcn-badge px-2.5 py-1 rounded-md text-[11px] font-mono border">nlp-rag</span>
        <span class="os-badge archon-tag shadcn-badge is-active px-2.5 py-1 rounded-md text-[11px] font-mono font-bold border shadow-xs">aktiv-tag</span>
      </div>
    `;
  }
  // Modul 13: Filter-Pills & Domänen-Filter
  else if (comp === "os-pill") {
    box.innerHTML = `
      <div class="flex items-center gap-1.5 justify-center w-full max-w-md select-none">
        <button type="button" class="os-pill prof-cat-btn px-3 py-1 rounded-full border text-xs font-medium cursor-pointer">Alle</button>
        <button type="button" class="os-pill prof-cat-btn is-active active-cat px-3 py-1 rounded-full border text-xs font-bold shadow-xs cursor-pointer">Engineering</button>
        <button type="button" class="os-pill prof-cat-btn px-3 py-1 rounded-full border text-xs font-medium cursor-pointer">Security</button>
        <button type="button" class="os-pill prof-cat-btn px-3 py-1 rounded-full border text-xs font-medium cursor-pointer">Finance</button>
      </div>
    `;
  }
  // Modul 14: Chat- & Stream-Konsole
  else if (comp === "os-console") {
    box.innerHTML = `
      <div class="os-console p-2.5 rounded-xl border w-full max-w-md font-mono text-[10.5px] space-y-1 select-none shadow-inner bg-black/5 dark:bg-black/30">
        <div class="flex items-center justify-between pb-1 border-b border-[var(--border)] opacity-70">
          <span>TERMINAL AUDIT STREAM</span>
          <span>PORT 8420</span>
        </div>
        <div class="text-emerald-500">[19:35:10] DISPATCHER: Task #104 dispatched to subagent</div>
        <div class="text-[var(--foreground)] opacity-90">[19:35:12] MEMORY: LRU-K cache synchronized with SQLite WAL</div>
        <div class="text-indigo-400">[19:35:14] OMNIROUTE: Routing to Claude 3.5 Sonnet (Local fallback ready)</div>
      </div>
    `;
  }
  // Modul 15: Modals & Personalakte
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
  else {
    box.innerHTML = `<div class="p-3 text-xs text-[var(--muted-foreground)]">Vorschau für ${comp}</div>`;
  }
}
\n"""

p_start = js.find(preview_func_start)
p_end = js.find(preview_func_end, p_start)
if p_start != -1 and p_end != -1:
    js = js[:p_start] + new_preview_func + js[p_end:]
    print("Replaced cdsUpdateLivePreview successfully")
else:
    print("ERROR finding cdsUpdateLivePreview function range")

with open("static/js/component_design_studio.js", "w", encoding="utf-8") as f:
    f.write(js)
print("Saved static/js/component_design_studio.js successfully!")
