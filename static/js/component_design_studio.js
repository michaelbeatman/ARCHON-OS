// =========================================================================
// ARCHON OS — 15-COMPONENT DESIGN STUDIO & DUAL-THEME ENGINE (Light + Dark)
// =========================================================================

// --- i18n-Helfer (Tranche t5) ---------------------------------------------
// cdsT() liefert den Katalogtext mit PFLICHT-Fallback: fehlt der Key in der
// aktiven Sprache und in de, bleibt der deutsche Text stehen - nie "".
// {platzhalter} werden aus params gefuellt (Zahlen stehen nie im Key).
function cdsT(key, fallback, params) {
  const i18n = window.archonI18n;
  let text = i18n ? i18n.t(key, fallback) : fallback;
  if (params) {
    Object.keys(params).forEach(name => {
      text = text.split(`{${name}}`).join(String(params[name]));
    });
  }
  return text;
}
// cdsCompKey() bildet die Baustein-ID (os-workspace) auf ein Key-Segment ab
// (os_workspace): das Katalog-Schema erlaubt nur [a-z0-9_] als Schluessel.
function cdsCompKey(compId, suffix) {
  return 'ui.component_design_studio.comp_' + String(compId).replace(/-/g, '_') + '_' + suffix;
}

const ARCHON_15_COMPONENTS = [
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
    where: "Alle großen Arbeits-Karten (.shadcn-card, .prof-panel-card, .theme-card, .os-island) in MC, Kader, Inbox, Library, Showroom, Research, Mastermind & Comm",
    selectors: {
      normal: ".shadcn-card, .prof-panel-card, .theme-card, .os-island, #ops-view-comm, #view-showroom .os-island, #view-research .os-island, #view-ai-mastermind .os-island",
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
    where: "Agenten-Liste links (.prof-list-item), Webhook-/E-Mail-/Messenger-Einträge in Inbox & Sub-Cards",
    selectors: {
      normal: ".prof-list-item, .shadcn-card-subtle, .daw-card, #inbox-list-webhook > div, #inbox-list-intern > div, #inbox-list-email > div, #inbox-list-messenger > div, #inbox-list-telegram > div, .os-card",
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
    where: "Live-Audit-Stream im Cockpit (#mc-audit-stream), Master-Chat-Verlauf, Interne Kommunikation & Boardroom Stream",
    selectors: {
      normal: "#mc-audit-stream, #agent-tab-chat-messages, #master-chat-messages, #ops-comm-messages, #boardroom-thread, .os-console",
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
    where: "Zentrale Popups (#system-settings-modal-card), Digitale Personalakte (.pa-modal-shell) & Neue autonome Aufgabe (#ops-new-task-modal)",
    selectors: {
      normal: ".pa-modal-shell, #system-settings-modal-card, #ops-new-task-modal .os-modal, #ops-detail-modal .os-modal, .os-modal",
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
];

const KANBAN_COLUMN_KEYS = [
  { key: "todo", label: "1. To-Do / Geplant" },
  { key: "in_progress", label: "2. In Bearbeitung" },
  { key: "review", label: "3. Review & QA" },
  { key: "blocked", label: "4. Blockiert" },
  { key: "done", label: "5. Abgeschlossen" }
];

let cdsStore = {
  active_theme_id: "archon_current",
  active_mode: "light",
  themes: {}
};

let cdsSelectedComp = "os-workspace";
let cdsSelectedState = "normal"; // "normal" | "hover" | "active"
let cdsIsDocked = false;
let cdsAutoSaveTimer = null;

function cdsGetDefaultStore() {
  return {
    active_theme_id: "archon_current",
    active_mode: document.documentElement.classList.contains("dark") ? "dark" : "light",
    themes: {
      archon_current: {
        id: "archon_current",
        name: "Archon Aktuell (Stand Heute)",
        light: {
          kanban_columns: {
            todo: { label: "To-Do / Geplant", bg: "rgba(243, 232, 222, 0.10)", border: "#F3E8DE", header: "#F3E8DE", text: "#6b5d4f" },
            in_progress: { label: "In Bearbeitung", bg: "rgba(238, 214, 91, 0.10)", border: "#EED65B", header: "#EED65B", text: "#6b5c10" },
            review: { label: "Review & QA", bg: "rgba(124, 169, 130, 0.10)", border: "#7CA982", header: "#7CA982", text: "#2f4a33" },
            blocked: { label: "Blockiert", bg: "rgba(193, 92, 83, 0.10)", border: "#C15C53", header: "#C15C53", text: "#ffffff" },
            done: { label: "Abgeschlossen", bg: "rgba(74, 109, 136, 0.10)", border: "#4A6D88", header: "#4A6D88", text: "#ffffff" }
          },
          components: {}
        },
        dark: {
          kanban_columns: {
            todo: { label: "To-Do / Geplant", bg: "rgba(243, 232, 222, 0.08)", border: "rgba(243, 232, 222, 0.35)", header: "#3b332b", text: "#f3e8de" },
            in_progress: { label: "In Bearbeitung", bg: "rgba(238, 214, 91, 0.08)", border: "rgba(238, 214, 91, 0.35)", header: "#423b16", text: "#eed65b" },
            review: { label: "Review & QA", bg: "rgba(124, 169, 130, 0.10)", border: "rgba(124, 169, 130, 0.40)", header: "#1f3524", text: "#a3cfa9" },
            blocked: { label: "Blockiert", bg: "rgba(193, 92, 83, 0.12)", border: "rgba(193, 92, 83, 0.45)", header: "#52231f", text: "#fca5a5" },
            done: { label: "Abgeschlossen", bg: "rgba(74, 109, 136, 0.12)", border: "rgba(74, 109, 136, 0.45)", header: "#1e3142", text: "#bae6fd" }
          },
          components: {}
        }
      }
    }
  };
}

function cdsEnsureThemeStructure(theme) {
  if (!theme) return;
  ["light", "dark"].forEach(mode => {
    if (!theme[mode]) theme[mode] = { kanban_columns: {}, components: {} };
    if (!theme[mode].kanban_columns) theme[mode].kanban_columns = {};
    if (!theme[mode].components) theme[mode].components = {};
    ARCHON_15_COMPONENTS.forEach(c => {
      if (!theme[mode].components[c.id]) {
        theme[mode].components[c.id] = { normal: {}, hover: {}, active: {} };
      } else {
        if (!theme[mode].components[c.id].normal) theme[mode].components[c.id].normal = {};
        if (!theme[mode].components[c.id].hover) theme[mode].components[c.id].hover = {};
        if (!theme[mode].components[c.id].active) theme[mode].components[c.id].active = {};
      }
    });
  });
}

let _cdsInitPromise = null;

async function initArchonComponentDesign(force = false) {
  if (_cdsInitPromise && !force) return _cdsInitPromise;
  _cdsInitPromise = (async () => {
    let hadCache = false;
    try {
      const customTheme = localStorage.getItem("archon_theme_custom");
      if (customTheme && (customTheme.includes("'Inter'") || customTheme.includes("'Space Grotesk'"))) {
        const fixed = customTheme.replace(/'Inter',\s*sans-serif/g, "'Outfit', sans-serif")
                                 .replace(/'Space Grotesk',\s*sans-serif/g, "'Outfit', sans-serif");
        localStorage.setItem("archon_theme_custom", fixed);
      }
      const cached = localStorage.getItem("archon_cds_store_v1");
      if (cached) {
        const migrated = cached.replace(/'Inter',\s*sans-serif/g, "'Outfit', sans-serif")
                               .replace(/'Space Grotesk',\s*sans-serif/g, "'Outfit', sans-serif");
        if (migrated !== cached) {
          localStorage.setItem("archon_cds_store_v1", migrated);
        }
        const parsed = JSON.parse(migrated);
        if (parsed && parsed.themes && Object.keys(parsed.themes).length > 0) {
          cdsStore = parsed;
          hadCache = true;
        }
      }
    } catch (e) {}

    if (hadCache) {
      Object.values(cdsStore.themes).forEach(cdsEnsureThemeStructure);
      cdsApplyActiveThemeToDOM();
      cdsRenderUI();
    }

    try {
      const res = await fetch("/api/design/themes");
      if (res.ok) {
        const serverData = await res.json();
        if (serverData && serverData.themes && Object.keys(serverData.themes).length > 0) {
          const newJson = JSON.stringify(serverData);
          const oldJson = JSON.stringify(cdsStore);
          if (newJson !== oldJson || !hadCache) {
            cdsStore = serverData;
            localStorage.setItem("archon_cds_store_v1", newJson);
            Object.values(cdsStore.themes).forEach(cdsEnsureThemeStructure);
            if (!cdsStore.themes[cdsStore.active_theme_id]) {
              cdsStore.active_theme_id = Object.keys(cdsStore.themes)[0];
            }
            cdsApplyActiveThemeToDOM();
            cdsRenderUI();
          }
          return;
        }
      }
    } catch (e) {
      console.warn("[CDS] Server-Themes konnten nicht geladen werden, nutze Cache:", e);
    }

    if (!cdsStore.themes || Object.keys(cdsStore.themes).length === 0) {
      cdsStore = cdsGetDefaultStore();
    }
    Object.values(cdsStore.themes).forEach(cdsEnsureThemeStructure);
    if (!cdsStore.themes[cdsStore.active_theme_id]) {
      cdsStore.active_theme_id = Object.keys(cdsStore.themes)[0];
    }

    cdsApplyActiveThemeToDOM();
    cdsRenderUI();
  })();
  return _cdsInitPromise;
}

function cdsGetActiveTheme() {
  return cdsStore.themes[cdsStore.active_theme_id] || Object.values(cdsStore.themes)[0];
}

function cdsGetActiveModeBlock() {
  const t = cdsGetActiveTheme();
  const mode = cdsStore.active_mode === "dark" ? "dark" : "light";
  return t[mode];
}

function cdsGetActiveProps() {
  const block = cdsGetActiveModeBlock();
  if (!block.components[cdsSelectedComp]) {
    block.components[cdsSelectedComp] = { normal: {}, hover: {}, active: {} };
  }
  return block.components[cdsSelectedComp][cdsSelectedState];
}

// Compiling and injecting the active theme + mode into a single clean <style id="archon-cds-compiled">
function cdsApplyActiveThemeToDOM() {
  const theme = cdsGetActiveTheme();
  if (!theme) return;
  const mode = cdsStore.active_mode === "dark" ? "dark" : "light";
  const block = theme[mode];
  if (!block) return;

  // 1. Set HTML / Body data-theme & class
  if (mode === "dark") {
    document.documentElement.setAttribute("data-theme", "dark");
    document.documentElement.classList.add("dark");
    document.body.classList.add("dark");
  } else {
    document.documentElement.setAttribute("data-theme", "light");
    document.documentElement.classList.remove("dark");
    document.body.classList.remove("dark");
  }
  localStorage.setItem("archon_theme_mode", mode);

  // 2. Apply Kanban Column CSS Variables to :root
  const rootStyle = document.documentElement.style;
  const kCols = block.kanban_columns || {};
  KANBAN_COLUMN_KEYS.forEach(({ key }) => {
    const colCfg = kCols[key];
    if (colCfg) {
      if (colCfg.bg) rootStyle.setProperty(`--kanban-${key}-bg`, colCfg.bg);
      if (colCfg.border) rootStyle.setProperty(`--kanban-${key}-border`, colCfg.border);
      if (colCfg.header) rootStyle.setProperty(`--kanban-${key}-header`, colCfg.header);
      if (colCfg.text) rootStyle.setProperty(`--kanban-${key}-text`, colCfg.text);
    }
  });

  // Also sync base CSS variables for compatibility with existing views
  const wsNormal = (block.components["os-workspace"] && block.components["os-workspace"].normal) || {};
  const sbNormal = (block.components["os-sidebar"] && block.components["os-sidebar"].normal) || {};
  const islNormal = (block.components["os-island"] && block.components["os-island"].normal) || {};
  const inpNormal = (block.components["os-input"] && block.components["os-input"].normal) || {};

  if (wsNormal["background-color"]) {
    rootStyle.setProperty("--page-bg", wsNormal["background-color"]);
    rootStyle.setProperty("--background", wsNormal["background-color"]);
  }
  if (wsNormal["color"]) {
    rootStyle.setProperty("--text-primary", wsNormal["color"]);
    rootStyle.setProperty("--foreground", wsNormal["color"]);
  }
  if (wsNormal["font-family"]) rootStyle.setProperty("--font-family", wsNormal["font-family"]);
  if (wsNormal["font-size"]) rootStyle.setProperty("--font-size", wsNormal["font-size"]);
  if (sbNormal["background-color"]) rootStyle.setProperty("--sidebar-bg", sbNormal["background-color"]);
  if (islNormal["background-color"]) {
    rootStyle.setProperty("--card-bg", islNormal["background-color"]);
    rootStyle.setProperty("--card", islNormal["background-color"]);
  }
  if (islNormal["border-color"]) rootStyle.setProperty("--border", islNormal["border-color"]);
  if (inpNormal["background-color"]) rootStyle.setProperty("--input-bg", inpNormal["background-color"]);

  const kColNormal = (block.components["os-kanban-col"] && block.components["os-kanban-col"].normal) || {};
  if (kColNormal["border-width"]) {
    rootStyle.setProperty("--kanban-col-border-width", kColNormal["border-width"]);
  }

  // 3. Build compiled CSS rules for the 15 components
  const cssChunks = ["/* Archon OS 15-Component Compiled Theme */\n"];
  ARCHON_15_COMPONENTS.forEach(comp => {
    const compStates = block.components[comp.id] || {};
    ["normal", "hover", "active"].forEach(st => {
      const props = compStates[st] || {};
      const entries = Object.entries(props).filter(([_, v]) => v !== undefined && v !== null && String(v).trim() !== "");
      if (entries.length === 0) return;

      // Special handling for gap on workspace or kanban-col
      const regularEntries = [];
      entries.forEach(([k, v]) => {
        if (k === "gap" && comp.selectors.gapTarget) {
          cssChunks.push(`${comp.selectors.gapTarget} {\n  gap: ${v} !important;\n}\n`);
        } else {
          regularEntries.push([k, v]);
        }
      });

      if (regularEntries.length > 0 && comp.selectors[st]) {
        cssChunks.push(`${comp.selectors[st]} {`);
        regularEntries.forEach(([k, v]) => {
          cssChunks.push(`  ${k}: ${v} !important;`);
        });
        cssChunks.push(`}\n`);
      }
    });
  });

  let styleEl = document.getElementById("archon-cds-compiled");
  if (!styleEl) {
    styleEl = document.createElement("style");
    styleEl.id = "archon-cds-compiled";
    document.head.appendChild(styleEl);
  }
  const nextCss = cssChunks.join("\n");
  if (styleEl.textContent !== nextCss) {
    styleEl.textContent = nextCss;
  }

  cdsUpdateLivePreview();
}

// Switch between Light and Dark mode
function cdsSetMode(mode) {
  cdsStore.active_mode = mode === "dark" ? "dark" : "light";
  cdsApplyActiveThemeToDOM();
  cdsRenderUI();
  cdsScheduleSave();
}
window.setThemeMode = cdsSetMode;

// Select one of the 15 components
function cdsSelectComponent(compId) {
  cdsSelectedComp = compId;
  cdsRenderUI();
}

// Select state (normal | hover | active)
function cdsSelectState(state) {
  cdsSelectedState = state;
  cdsRenderUI();
}

// Update a single CSS property on the active component + state
function cdsSetProp(prop, value) {
  const props = cdsGetActiveProps();
  if (value === "" || value === null || value === undefined) {
    delete props[prop];
  } else {
    props[prop] = String(value).trim();
  }
  if (prop === "font-family" && typeof window.ensureGoogleFontLoaded === "function") {
    window.ensureGoogleFontLoaded(value);
  }
  cdsApplyActiveThemeToDOM();
  cdsSyncControlsFromState();
  cdsScheduleSave();
}

// Update a Kanban column color (manual control for each of the 5 columns)
function cdsSetKanbanColColor(colKey, field, value) {
  const block = cdsGetActiveModeBlock();
  if (!block.kanban_columns[colKey]) {
    block.kanban_columns[colKey] = { label: colKey, bg: "", border: "", header: "", text: "" };
  }
  block.kanban_columns[colKey][field] = value;
  cdsApplyActiveThemeToDOM();
  cdsRenderKanbanColorsPanel();
  cdsScheduleSave();
}

// Helper: convert hex + alpha% to rgba() for easy Kanban column background tinting if desired
function cdsSetKanbanColBgAlpha(colKey, hexColor, alphaPercent) {
  const cleanHex = (hexColor || "#cccccc").replace("#", "");
  const r = parseInt(cleanHex.substring(0, 2), 16) || 200;
  const g = parseInt(cleanHex.substring(2, 4), 16) || 200;
  const b = parseInt(cleanHex.substring(4, 6), 16) || 200;
  const a = Math.max(0, Math.min(100, parseFloat(alphaPercent) || 10)) / 100;
  const rgba = `rgba(${r}, ${g}, ${b}, ${a.toFixed(2)})`;
  cdsSetKanbanColColor(colKey, "bg", rgba);
}

// Reset only the currently selected component in current mode
function cdsResetCurrentComponent() {
  const block = cdsGetActiveModeBlock();
  block.components[cdsSelectedComp] = { normal: {}, hover: {}, active: {} };
  cdsApplyActiveThemeToDOM();
  cdsRenderUI();
  cdsScheduleSave();
  if (typeof showNotification === "function") {
    showNotification(cdsT('ui.component_design_studio.notif_reset_title', 'Baustein zurückgesetzt'), cdsT('ui.component_design_studio.notif_reset_body', '{component} wurde im aktuellen Modus geleert.', { component: cdsSelectedComp }), "info");
  }
}

// Auto-save to localStorage & backend
function cdsScheduleSave() {
  try {
    localStorage.setItem("archon_cds_store_v1", JSON.stringify(cdsStore));
  } catch (e) {}
  clearTimeout(cdsAutoSaveTimer);
  cdsAutoSaveTimer = setTimeout(() => {
    cdsSaveToServer(true);
  }, 450);
}

async function cdsSaveToServer(silent = false) {
  try {
    localStorage.setItem("archon_cds_store_v1", JSON.stringify(cdsStore));
    const res = await fetch("/api/design/themes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(cdsStore)
    });
    if (res.ok && !silent && typeof showNotification === "function") {
      showNotification(cdsT('ui.component_design_studio.notif_saved_title', 'Design gespeichert'), cdsT('ui.component_design_studio.notif_saved_body', 'Theme "{name}" wurde dauerhaft gesichert.', { name: cdsGetActiveTheme().name }), "success");
    }
  } catch (e) {
    console.error("[CDS] Fehler beim Speichern:", e);
  }
}

// Switch active theme from dropdown
function cdsSelectTheme(themeId) {
  if (!cdsStore.themes[themeId]) return;
  cdsStore.active_theme_id = themeId;
  cdsEnsureThemeStructure(cdsStore.themes[themeId]);
  cdsApplyActiveThemeToDOM();
  cdsRenderUI();
  cdsSaveToServer(true);
  if (typeof showNotification === "function") {
    showNotification(cdsT('ui.component_design_studio.notif_theme_loaded_title', 'Theme geladen'), cdsT('ui.component_design_studio.notif_theme_loaded_body', 'Theme "{name}" ist jetzt aktiv.', { name: cdsStore.themes[themeId].name }), "success");
  }
}

// Save current state as a new named theme
async function cdsSaveAsNewTheme() {
  const inp = document.getElementById("cds-new-theme-name");
  const name = inp ? inp.value.trim() : "";
  if (!name) {
    if (typeof showNotification === "function") {
      showNotification(cdsT('ui.component_design_studio.notif_hint_title', 'Hinweis'), cdsT('ui.component_design_studio.notif_name_required', 'Bitte gib einen Namen für das neue Theme ein.'), "error");
    }
    return;
  }
  const id = "theme_" + name.toLowerCase().replace(/[^a-z0-9]+/g, "_") + "_" + Date.now().toString().slice(-4);
  const currentTheme = JSON.parse(JSON.stringify(cdsGetActiveTheme()));
  currentTheme.id = id;
  currentTheme.name = name;
  currentTheme.created_at = new Date().toISOString();

  cdsStore.themes[id] = currentTheme;
  cdsStore.active_theme_id = id;
  if (inp) inp.value = "";

  cdsApplyActiveThemeToDOM();
  cdsRenderUI();
  await cdsSaveToServer(false);
}

// Delete active theme (if more than 1 exists)
async function cdsDeleteActiveTheme() {
  const ids = Object.keys(cdsStore.themes);
  if (ids.length <= 1) {
    if (typeof showNotification === "function") {
      showNotification(cdsT('ui.component_design_studio.notif_not_possible_title', 'Nicht möglich'), cdsT('ui.component_design_studio.notif_last_theme', 'Das letzte verbleibende Theme kann nicht gelöscht werden.'), "error");
    }
    return;
  }
  const active = cdsGetActiveTheme();
  if (!confirm(cdsT('ui.component_design_studio.confirm_delete_theme', 'Theme "{name}" wirklich löschen?', { name: active.name }))) return;
  const delId = active.id;
  delete cdsStore.themes[delId];
  cdsStore.active_theme_id = Object.keys(cdsStore.themes)[0];
  try {
    await fetch(`/api/design/themes/${encodeURIComponent(delId)}`, { method: "DELETE" });
  } catch (e) {}
  cdsApplyActiveThemeToDOM();
  cdsRenderUI();
  await cdsSaveToServer(true);
}

// Export active theme as JSON file
function cdsExportThemeJson() {
  const active = cdsGetActiveTheme();
  const blob = new Blob([JSON.stringify(active, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${active.id || "archon_theme"}.json`;
  a.click();
  URL.revokeObjectURL(url);
}

// Import theme from JSON file
function cdsImportThemeJson(inputEl) {
  const file = inputEl && inputEl.files && inputEl.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = async (e) => {
    try {
      const imported = JSON.parse(e.target.result);
      if (!imported || (!imported.light && !imported.dark)) {
        throw new Error("Ungültiges Theme-Format");
      }
      const id = imported.id || ("imported_" + Date.now());
      imported.id = id;
      imported.name = imported.name || file.name.replace(".json", "");
      cdsEnsureThemeStructure(imported);
      cdsStore.themes[id] = imported;
      cdsStore.active_theme_id = id;
      cdsApplyActiveThemeToDOM();
      cdsRenderUI();
      await cdsSaveToServer(false);
    } catch (err) {
      alert(cdsT('ui.component_design_studio.import_failed', 'Theme-Import fehlgeschlagen: {message}', { message: err.message }));
    }
  };
  reader.readAsText(file);
}

// Toggle Dock Mode ("Rechts andocken (Live-Blick)")
function toggleSettingsDockMode() {
  const modalBackdrop = document.getElementById("system-settings-modal");
  const modalCard = document.getElementById("system-settings-modal-card");
  const dockBtn = document.getElementById("cds-dock-btn");
  const headerDockBtn = document.getElementById("modal-header-dock-btn");
  if (!modalBackdrop || !modalCard) return;

  cdsIsDocked = !cdsIsDocked;
  if (cdsIsDocked) {
    modalBackdrop.classList.remove("bg-black/75", "backdrop-blur-xs", "items-center", "justify-center", "p-4");
    modalBackdrop.classList.add("pointer-events-none", "items-stretch", "justify-end", "p-2");
    modalCard.classList.remove("w-[94vw]", "max-w-6xl", "h-[92vh]", "max-h-[92vh]");
    modalCard.classList.add("pointer-events-auto", "w-[500px]", "max-w-[96vw]", "h-[96vh]", "max-h-[96vh]", "border-2", "border-zinc-900", "dark:border-zinc-200");
    if (dockBtn) dockBtn.innerHTML = `<i data-lucide="maximize-2" class="w-3.5 h-3.5"></i> ${cdsT('ui.component_design_studio.dock_expand', 'Großes Fenster')}`;
    if (headerDockBtn) headerDockBtn.innerHTML = `<i data-lucide="maximize-2" class="w-3.5 h-3.5"></i> ${cdsT('ui.component_design_studio.dock_expand_short', 'Groß')}`;
  } else {
    modalBackdrop.classList.add("bg-black/75", "backdrop-blur-xs", "items-center", "justify-center", "p-4");
    modalBackdrop.classList.remove("pointer-events-none", "items-stretch", "justify-end", "p-2");
    modalCard.classList.add("w-[94vw]", "max-w-6xl", "h-[92vh]", "max-h-[92vh]");
    modalCard.classList.remove("pointer-events-auto", "w-[500px]", "max-w-[96vw]", "h-[96vh]", "max-h-[96vh]", "border-2", "border-zinc-900", "dark:border-zinc-200");
    if (dockBtn) dockBtn.innerHTML = `<i data-lucide="panel-right" class="w-3.5 h-3.5"></i> ${cdsT('ui.component_design_studio.dock_collapse', '🗗 Rechts andocken (Live-Blick)')}`;
    if (headerDockBtn) headerDockBtn.innerHTML = `<i data-lucide="panel-right" class="w-3.5 h-3.5"></i> ${cdsT('ui.component_design_studio.dock_live', 'Live-Dock')}`;
  }
  if (window.lucide) lucide.createIcons();
}
window.toggleSettingsDockMode = toggleSettingsDockMode;

// Upload background image for current component
async function cdsUploadBgImage(fileInput) {
  const file = fileInput && fileInput.files && fileInput.files[0];
  if (!file) return;
  const formData = new FormData();
  formData.append("file", file);
  try {
    const res = await fetch("/api/theme/upload-background", { method: "POST", body: formData });
    if (res.ok) {
      const data = await res.json();
      if (data.url) {
        cdsSetProp("background-image", `url('${data.url}')`);
        cdsSetProp("background-size", "cover");
      }
    }
  } catch (e) {
    console.error("[CDS] Bild-Upload fehlgeschlagen:", e);
  }
}

// Render the 15-Component List, Theme Dropdown, Mode Buttons, Kanban Colors, and Sync Controls
function cdsRenderUI() {
  // 1. Mode Buttons
  const btnLight = document.getElementById("cds-mode-light");
  const btnDark = document.getElementById("cds-mode-dark");
  const isDark = cdsStore.active_mode === "dark";
  if (btnLight && btnDark) {
    btnLight.className = `flex-1 flex items-center justify-center gap-1.5 py-1.5 px-3 rounded-lg border text-xs font-bold transition cursor-pointer ${!isDark ? "bg-zinc-900 text-white border-zinc-900 shadow-sm" : "bg-[var(--card)] text-[var(--muted-foreground)] border-[var(--border)]"}`;
    btnDark.className = `flex-1 flex items-center justify-center gap-1.5 py-1.5 px-3 rounded-lg border text-xs font-bold transition cursor-pointer ${isDark ? "bg-zinc-100 text-zinc-900 border-zinc-100 shadow-sm" : "bg-[var(--card)] text-[var(--muted-foreground)] border-[var(--border)]"}`;
  }

  // 2. Theme Select Dropdown
  const sel = document.getElementById("cds-theme-select");
  if (sel) {
    sel.innerHTML = Object.values(cdsStore.themes).map(t =>
      `<option value="${t.id}" ${t.id === cdsStore.active_theme_id ? "selected" : ""}>${t.name}</option>`
    ).join("");
  }

  // 3. 15 Component List
  const listEl = document.getElementById("cds-component-list");
  if (listEl) {
    const block = cdsGetActiveModeBlock();
    listEl.innerHTML = ARCHON_15_COMPONENTS.map(c => {
      const isSel = c.id === cdsSelectedComp;
      const stObj = (block.components && block.components[c.id]) || {};
      const count = Object.keys(stObj.normal || {}).length + Object.keys(stObj.hover || {}).length + Object.keys(stObj.active || {}).length;
      return `
        <button type="button" onclick="cdsSelectComponent('${c.id}')"
          class="w-full text-left px-2.5 py-2 rounded-xl border transition flex items-center justify-between gap-2 cursor-pointer ${isSel ? "bg-[var(--secondary)] border-2 border-zinc-900 dark:border-zinc-100 font-bold shadow-sm" : "bg-[var(--card)] border-[var(--border)] hover:bg-[var(--secondary)]/60"}">
          <div class="flex items-center gap-2 min-w-0">
            <span class="text-[10px] font-mono px-1.5 py-0.5 rounded bg-[var(--background)] border border-[var(--border)] text-[var(--muted-foreground)] shrink-0">${c.num}</span>
            <div class="truncate">
              <div class="text-xs text-[var(--foreground)] truncate">${cdsT(cdsCompKey(c.id, 'name'), c.name)}</div>
              <div class="text-[10px] text-[var(--muted-foreground)] font-mono truncate">.${c.id}</div>
            </div>
          </div>
          <span class="text-[10px] font-mono px-1.5 py-0.5 rounded-full ${count > 0 ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 font-bold" : "text-[var(--muted-foreground)]"} shrink-0">${count}</span>
        </button>
      `;
    }).join("");
  }

  // 4. Selected Component Header & State Buttons
  const activeCompObj = ARCHON_15_COMPONENTS.find(c => c.id === cdsSelectedComp) || ARCHON_15_COMPONENTS[0];
  const titleEl = document.getElementById("cds-active-comp-title");
  const descEl = document.getElementById("cds-active-comp-desc");
  const selEl = document.getElementById("cds-active-comp-selector");
  const usageEl = document.getElementById("cds-active-comp-usage");
  if (titleEl) titleEl.textContent = `${activeCompObj.num}. ${cdsT(cdsCompKey(activeCompObj.id, 'name'), activeCompObj.name)}`;
  if (descEl) descEl.textContent = cdsT(cdsCompKey(activeCompObj.id, 'desc'), activeCompObj.desc);
  if (selEl) selEl.textContent = activeCompObj.selectors[cdsSelectedState] || `.${activeCompObj.id}`;
  if (usageEl) usageEl.textContent = activeCompObj.where ? cdsT(cdsCompKey(activeCompObj.id, 'where'), activeCompObj.where) : cdsT('ui.component_design_studio.comp_usage_fallback', 'Systemweiter Baustein');

  ["normal", "hover", "active"].forEach(st => {
    const b = document.getElementById(`cds-state-btn-${st}`);
    if (b) {
      const active = st === cdsSelectedState;
      b.className = `flex-1 py-1.5 px-2.5 rounded-lg border text-xs font-mono font-bold transition cursor-pointer ${active ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900 border-zinc-900 dark:border-zinc-100 shadow-xs" : "bg-[var(--card)] text-[var(--muted-foreground)] border-[var(--border)] hover:text-[var(--foreground)]"}`;
    }
  });

  // 5. Show/Hide Special Panels (Kanban Columns #07 & Firmenlogo #16)
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
  }

  cdsSyncControlsFromState();
  cdsUpdateLivePreview();
  if (window.lucide) lucide.createIcons();
}

function cdsHexFromAnyColor(val, fallback = "#ffffff") {
  if (!val) return fallback;
  const s = String(val).trim();
  if (/^#[0-9a-fA-F]{6}$/.test(s)) return s;
  const m = s.match(/rgba?\((\d+)\s*,\s*(\d+)\s*,\s*(\d+)/);
  if (m) {
    const toH = n => Math.max(0, Math.min(255, parseInt(n, 10))).toString(16).padStart(2, "0");
    return `#${toH(m[1])}${toH(m[2])}${toH(m[3])}`;
  }
  return fallback;
}

function cdsRenderKanbanColorsPanel() {
  const container = document.getElementById("cds-kanban-cols-grid");
  if (!container) return;
  const block = cdsGetActiveModeBlock();
  const cols = block.kanban_columns || {};

  container.innerHTML = KANBAN_COLUMN_KEYS.map(({ key, label }) => {
    const c = cols[key] || { bg: "rgba(243,232,222,0.10)", border: "#F3E8DE", header: "#F3E8DE", text: "#6b5d4f" };
    const bgHex = cdsHexFromAnyColor(c.bg, "#f3e8de");
    const borderHex = cdsHexFromAnyColor(c.border, "#f3e8de");
    const headerHex = cdsHexFromAnyColor(c.header, "#f3e8de");
    const textHex = cdsHexFromAnyColor(c.text, "#334155");
    const alphaMatch = String(c.bg).match(/rgba\([^,]+,[^,]+,[^,]+,\s*([0-9.]+)\)/);
    const alphaPct = alphaMatch ? Math.round(parseFloat(alphaMatch[1]) * 100) : 10;

    return `
      <div class="p-2.5 rounded-xl border border-[var(--border)] bg-[var(--card)] space-y-2">
        <div class="flex items-center justify-between border-b border-[var(--border)] pb-1.5">
          <span class="font-mono font-bold text-xs text-[var(--foreground)]">${cdsT('ui.component_design_studio.kanban_' + key + '_label', label)}</span>
          <span class="px-2 py-0.5 rounded text-[10px] font-bold" style="background:${c.header};color:${c.text};border:1px solid ${c.border}">${cdsT('ui.component_design_studio.panel_preview', 'Vorschau')}</span>
        </div>
        <div class="grid grid-cols-2 gap-2 text-[11px] font-mono">
          <div>
            <label class="block text-[10px] text-[var(--muted-foreground)] mb-0.5">${cdsT('ui.component_design_studio.panel_col_bg', 'Spalten-Hintergrund (bg)')}</label>
            <div class="flex items-center gap-1">
              <input type="color" value="${bgHex}" onchange="cdsSetKanbanColBgAlpha('${key}', this.value, ${alphaPct})" class="w-6 h-6 rounded border border-[var(--border)] cursor-pointer p-0 shrink-0">
              <input type="text" value="${c.bg}" onchange="cdsSetKanbanColColor('${key}', 'bg', this.value)" class="w-full bg-[var(--background)] border border-[var(--border)] rounded px-1.5 py-0.5 text-[10px] text-[var(--foreground)]">
            </div>
          </div>
          <div>
            <label class="block text-[10px] text-[var(--muted-foreground)] mb-0.5">${cdsT('ui.component_design_studio.panel_bg_alpha', 'Bg-Intensität ({percent}%)', { percent: alphaPct })}</label>
            <input type="range" min="0" max="100" value="${alphaPct}" oninput="cdsSetKanbanColBgAlpha('${key}', '${bgHex}', this.value)" class="w-full cursor-pointer">
          </div>
          <div>
            <label class="block text-[10px] text-[var(--muted-foreground)] mb-0.5">${cdsT('ui.component_design_studio.panel_col_border', 'Spalten-Rahmen (border)')}</label>
            <div class="flex items-center gap-1">
              <input type="color" value="${borderHex}" onchange="cdsSetKanbanColColor('${key}', 'border', this.value)" class="w-6 h-6 rounded border border-[var(--border)] cursor-pointer p-0 shrink-0">
              <input type="text" value="${c.border}" onchange="cdsSetKanbanColColor('${key}', 'border', this.value)" class="w-full bg-[var(--background)] border border-[var(--border)] rounded px-1.5 py-0.5 text-[10px] text-[var(--foreground)]">
            </div>
          </div>
          <div>
            <label class="block text-[10px] text-[var(--muted-foreground)] mb-0.5">${cdsT('ui.component_design_studio.panel_header_color', 'Header-Farbe & Text')}</label>
            <div class="flex items-center gap-1">
              <input type="color" value="${headerHex}" title="${cdsT('ui.component_design_studio.panel_header_bg_title', 'Header-Hintergrund')}" onchange="cdsSetKanbanColColor('${key}', 'header', this.value)" class="w-6 h-6 rounded border border-[var(--border)] cursor-pointer p-0 shrink-0">
              <input type="color" value="${textHex}" title="${cdsT('ui.component_design_studio.panel_header_text_title', 'Header-Schriftfarbe')}" onchange="cdsSetKanbanColColor('${key}', 'text', this.value)" class="w-6 h-6 rounded border border-[var(--border)] cursor-pointer p-0 shrink-0">
              <input type="text" value="${c.header}" onchange="cdsSetKanbanColColor('${key}', 'header', this.value)" class="w-full bg-[var(--background)] border border-[var(--border)] rounded px-1.5 py-0.5 text-[10px] text-[var(--foreground)]">
            </div>
          </div>
        </div>
      </div>
    `;
  }).join("");
}

function cdsSyncControlsFromState() {
  const props = cdsGetActiveProps();
  const setVal = (id, v) => {
    const el = document.getElementById(id);
    if (el) el.value = v !== undefined && v !== null ? v : "";
  };
  const setTxt = (id, v) => {
    const el = document.getElementById(id);
    if (el) el.textContent = v;
  };
  const numPx = (v, def = 0) => {
    if (!v) return def;
    const n = parseFloat(String(v).replace("px", ""));
    return isNaN(n) ? def : n;
  };

  // 1. Typography
  setVal("cds-font-family", props["font-family"] || "inherit");
  setVal("cds-color-hex", props["color"] || "");
  setVal("cds-color-picker", cdsHexFromAnyColor(props["color"], "#0f172a"));
  const fs = numPx(props["font-size"], 14);
  setVal("cds-font-size-range", fs);
  setVal("cds-font-size-input", props["font-size"] || "");
  setTxt("cds-font-size-val", props["font-size"] || cdsT('ui.component_design_studio.value_default', 'Standard'));
  setVal("cds-font-weight", props["font-weight"] || "");
  setVal("cds-line-height", props["line-height"] || "");
  setVal("cds-text-align", props["text-align"] || "");
  setVal("cds-text-transform", props["text-transform"] || "");
  setVal("cds-letter-spacing", props["letter-spacing"] || "");
  setVal("cds-text-decoration", props["text-decoration"] || "");

  // 2. Background & Opacity
  setVal("cds-bg-hex", props["background-color"] || "");
  setVal("cds-bg-picker", cdsHexFromAnyColor(props["background-color"], "#ffffff"));
  setVal("cds-bg-image", props["background-image"] || "");
  setVal("cds-bg-size", props["background-size"] || "auto");
  setVal("cds-bg-repeat", props["background-repeat"] || "no-repeat");
  setVal("cds-opacity", props["opacity"] !== undefined ? props["opacity"] : "1");
  setVal("cds-backdrop-filter", props["backdrop-filter"] || "");

  // 3. Border & Radius
  setVal("cds-border-color-hex", props["border-color"] || "");
  setVal("cds-border-color-picker", cdsHexFromAnyColor(props["border-color"], "#e2e8f0"));
  const bw = numPx(props["border-width"], 1);
  setVal("cds-border-width-range", bw);
  setTxt("cds-border-width-val", props["border-width"] || "1px");
  setVal("cds-border-style", props["border-style"] || "solid");
  const br = numPx(props["border-radius"], 8);
  setVal("cds-border-radius-range", br);
  setTxt("cds-border-radius-val", props["border-radius"] || cdsT('ui.component_design_studio.value_default', 'Standard'));
  setVal("cds-radius-tl", props["border-top-left-radius"] || "");
  setVal("cds-radius-tr", props["border-top-right-radius"] || "");
  setVal("cds-radius-br", props["border-bottom-right-radius"] || "");
  setVal("cds-radius-bl", props["border-bottom-left-radius"] || "");

  // 4. Box Model (Margin, Padding, Dimensions)
  setVal("cds-mt", props["margin-top"] || "");
  setVal("cds-mr", props["margin-right"] || "");
  setVal("cds-mb", props["margin-bottom"] || "");
  setVal("cds-ml", props["margin-left"] || "");
  setVal("cds-pt", props["padding-top"] || "");
  setVal("cds-pr", props["padding-right"] || "");
  setVal("cds-pb", props["padding-bottom"] || "");
  setVal("cds-pl", props["padding-left"] || "");
  setVal("cds-width", props["width"] || "");
  setVal("cds-height", props["height"] || "");
  setVal("cds-min-width", props["min-width"] || "");
  setVal("cds-max-width", props["max-width"] || "");

  // 5. Layout, Flexbox & Gap
  setVal("cds-display", props["display"] || "");
  setVal("cds-position", props["position"] || "");
  setVal("cds-flex-direction", props["flex-direction"] || "");
  const gapVal = numPx(props["gap"], 12);
  setVal("cds-gap-range", gapVal);
  setVal("cds-gap-input", props["gap"] || "");
  setTxt("cds-gap-val", props["gap"] || cdsT('ui.component_design_studio.value_default', 'Standard'));
  setVal("cds-align-items", props["align-items"] || "");
  setVal("cds-justify-content", props["justify-content"] || "");
  setVal("cds-overflow", props["overflow"] || "");
  setVal("cds-z-index", props["z-index"] || "");

  // 6. Shadows & Effects
  setVal("cds-box-shadow-select", props["box-shadow"] || "");
  setVal("cds-box-shadow-input", props["box-shadow"] || "");
  setVal("cds-cursor", props["cursor"] || "");
  setVal("cds-transition", props["transition"] || "");
  setVal("cds-transform", props["transform"] || "");
}

// Render interactive live preview of the currently selected component
function cdsUpdateLivePreview() {
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
          <span>${cdsT('ui.component_design_studio.preview_workspace_title', '🖥️ Workspace-Hintergrund & Grundraster')}</span>
          <span class="text-[10px] opacity-75">${cdsT('ui.component_design_studio.preview_layout_hint', 'Layout-Vorschau')}</span>
        </div>
        <div class="grid grid-cols-3 gap-2">
          <div class="os-island p-2 rounded border text-[11px] text-center font-medium">${cdsT('ui.component_design_studio.preview_island_n', 'Insel {index} (Raster)', { index: 1 })}</div>
          <div class="os-island p-2 rounded border text-[11px] text-center font-medium">${cdsT('ui.component_design_studio.preview_island_n', 'Insel {index} (Raster)', { index: 2 })}</div>
          <div class="os-island p-2 rounded border text-[11px] text-center font-medium">${cdsT('ui.component_design_studio.preview_island_n', 'Insel {index} (Raster)', { index: 3 })}</div>
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
              <div class="os-nav-btn text-[10px] px-2 py-1 rounded">${cdsT('ui.component_design_studio.preview_nav_cockpit', 'Cockpit')}</div>
              <div class="os-nav-btn is-active text-[10px] px-2 py-1 rounded font-bold">${cdsT('ui.component_design_studio.preview_nav_cadre', 'Kader')}</div>
            </div>
          </div>
          <div class="text-[9px] opacity-60 font-mono">Sidebar v2.0</div>
        </div>
        <div class="flex-1 p-3 bg-[var(--card)]/40 flex items-center justify-center text-xs opacity-70">
          ${cdsT('ui.component_design_studio.preview_main_area', 'Haupt-Arbeitsbereich')}
        </div>
      </div>
    `;
  }
  // Modul 03: Navigations- & Tab-Buttons
  else if (comp === "os-nav-btn") {
    box.innerHTML = `
      <div class="flex flex-col gap-2 w-full max-w-md select-none">
        <div class="text-[10px] font-mono text-[var(--muted-foreground)]">${cdsT('ui.component_design_studio.preview_states_hint', '3 Zustände: Inaktiv, Hover (Maus drüber) & Aktiv')}</div>
        <div class="flex items-center gap-2">
          <button type="button" class="os-nav-btn archon-nav-item flex-1 py-1.5 px-3 rounded-lg text-xs font-semibold border flex items-center gap-1.5">
            <span>${cdsT('ui.component_design_studio.preview_state_inactive', '⚙️ Inaktiv')}</span>
          </button>
          <button type="button" class="os-nav-btn archon-nav-item flex-1 py-1.5 px-3 rounded-lg text-xs font-semibold border flex items-center gap-1.5 hover:shadow-xs">
            <span>${cdsT('ui.component_design_studio.preview_state_hover', '✨ Hover-Test')}</span>
          </button>
          <button type="button" class="os-nav-btn archon-nav-item is-active nav-item-active flex-1 py-1.5 px-3 rounded-lg text-xs font-bold border flex items-center gap-1.5 shadow-xs">
            <span>${cdsT('ui.component_design_studio.preview_state_active', '📌 Aktiv')}</span>
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
          <span class="text-xs font-bold">${cdsT('ui.component_design_studio.preview_island_title', 'Haupt-Insel (Container-Panel)')}</span>
          <span class="text-[10px] font-mono px-2 py-0.5 rounded bg-[var(--secondary)]">${cdsT('ui.component_design_studio.preview_card_shell', 'Karten-Hülle')}</span>
        </div>
        <p class="text-[11px] text-[var(--muted-foreground)] leading-relaxed">
          ${cdsT('ui.component_design_studio.preview_island_desc', 'Dies ist der Außenrahmen, der alle Dashboards, Ansichten und Bereiche in Archon OS umschließt.')}
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
          <div class="text-[10px] font-mono opacity-80">${cdsT('ui.component_design_studio.preview_live_telemetry', 'Live Telemetrie')}</div>
        </div>
        <div class="p-3 text-[11px] text-[var(--muted-foreground)] bg-[var(--card)]/30">
          ${cdsT('ui.component_design_studio.preview_island_body', 'Insel-Inhalt unterhalb der Kopfzeile')}
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
            <div class="text-[10px] text-[var(--muted-foreground)] truncate">${cdsT('ui.component_design_studio.preview_entry_normal', 'Normaler Eintrag')}</div>
          </div>
        </div>
        <div class="os-card prof-list-item is-active selected-item p-2.5 rounded-xl border flex items-center gap-2 shadow-xs">
          <div class="w-7 h-7 rounded-full bg-emerald-500/20 text-emerald-500 font-bold flex items-center justify-center text-xs">A</div>
          <div class="min-w-0">
            <div class="text-xs font-bold truncate">Archon Guard</div>
            <div class="text-[10px] text-emerald-600 dark:text-emerald-400 font-bold truncate">${cdsT('ui.component_design_studio.preview_entry_selected', 'Ausgewählt (Aktiv)')}</div>
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
              <div class="px-1.5 py-1 rounded-lg text-[9.5px] font-bold truncate text-center" style="background:${c.header};color:${c.text}">${cdsT('ui.component_design_studio.kanban_' + key + '_label', label).split(". ")[1]}</div>
              <div class="os-kanban-card p-1 rounded-md border text-[9.5px] text-center font-medium bg-[var(--card)]/90">${cdsT('ui.component_design_studio.preview_kanban_task', 'Task')}</div>
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
            <span class="text-[9px] px-1 py-0.2 rounded bg-emerald-500/10 text-emerald-500 font-mono">${cdsT('ui.component_design_studio.preview_badge_active', 'Aktiv')}</span>
          </div>
          <div class="text-xs font-bold text-[var(--foreground)] truncate">E-Mail Sync Daemon</div>
          <div class="text-[10px] text-emerald-600 dark:text-emerald-400 font-bold">${cdsT('ui.component_design_studio.status_in_progress', 'In Bearbeitung')}</div>
        </div>
      </div>
    `;
  }
  // Modul 09: Primär- & Aktions-Buttons
  else if (comp === "os-btn-primary") {
    box.innerHTML = `
      <div class="flex items-center gap-3 w-full max-w-md justify-center select-none">
        <button type="button" class="os-btn-primary shadcn-btn-primary px-4 py-2 rounded-xl text-xs font-bold shadow-sm flex items-center gap-1.5 cursor-pointer">
          <span>${cdsT('ui.component_design_studio.preview_btn_save', '💾 Einstellungen Speichern')}</span>
        </button>
        <button type="button" class="os-btn-primary shadcn-btn-primary is-active px-4 py-2 rounded-xl text-xs font-bold shadow-md flex items-center gap-1.5 cursor-pointer">
          <span>${cdsT('ui.component_design_studio.preview_btn_run', '⚡ Aktion Ausführen')}</span>
        </button>
      </div>
    `;
  }
  // Modul 10: Sekundär- & Icon-Buttons
  else if (comp === "os-btn-secondary") {
    box.innerHTML = `
      <div class="flex items-center gap-2.5 w-full max-w-md justify-center select-none">
        <button type="button" class="os-btn-secondary shadcn-btn-outline px-3 py-1.5 rounded-lg border text-xs font-medium flex items-center gap-1.5 cursor-pointer">
          <span>${cdsT('ui.component_design_studio.preview_btn_sync', '🔄 Sync')}</span>
        </button>
        <button type="button" class="os-btn-secondary shadcn-btn-outline px-3 py-1.5 rounded-lg border text-xs font-medium flex items-center gap-1.5 cursor-pointer">
          <span>${cdsT('ui.component_design_studio.preview_btn_cancel', '❌ Abbrechen')}</span>
        </button>
        <button type="button" class="os-btn-secondary shadcn-btn-outline is-active px-3 py-1.5 rounded-lg border text-xs font-bold flex items-center gap-1.5 cursor-pointer">
          <span>${cdsT('ui.component_design_studio.preview_btn_filter', '🔍 Filter')}</span>
        </button>
      </div>
    `;
  }
  // Modul 11: Eingabefelder & Dropdowns
  else if (comp === "os-input") {
    box.innerHTML = `
      <div class="grid grid-cols-2 gap-2.5 w-full max-w-md select-none">
        <input type="text" value="${cdsT('ui.component_design_studio.preview_search_placeholder', '🔍 Agenten oder Skills suchen...')}" class="os-input shadcn-input px-3 py-2 rounded-lg border text-xs w-full bg-[var(--background)]" />
        <select class="os-input shadcn-input px-3 py-2 rounded-lg border text-xs w-full bg-[var(--background)] cursor-pointer">
          <option>${cdsT('ui.component_design_studio.preview_dropdown_placeholder', 'Dropdown-Auswahl...')}</option>
          <option>${cdsT('ui.component_design_studio.preview_option_a', 'Option A')}</option>
          <option>${cdsT('ui.component_design_studio.preview_option_b', 'Option B')}</option>
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
        <button type="button" class="os-pill prof-cat-btn px-3 py-1 rounded-full border text-xs font-medium cursor-pointer">${cdsT('ui.component_design_studio.preview_pill_all', 'Alle')}</button>
        <button type="button" class="os-pill prof-cat-btn is-active active-cat px-3 py-1 rounded-full border text-xs font-bold shadow-xs cursor-pointer">${cdsT('ui.component_design_studio.preview_pill_engineering', 'Engineering')}</button>
        <button type="button" class="os-pill prof-cat-btn px-3 py-1 rounded-full border text-xs font-medium cursor-pointer">${cdsT('ui.component_design_studio.preview_pill_security', 'Security')}</button>
        <button type="button" class="os-pill prof-cat-btn px-3 py-1 rounded-full border text-xs font-medium cursor-pointer">${cdsT('ui.component_design_studio.preview_pill_finance', 'Finance')}</button>
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
            <span>📋</span> ${cdsT('ui.component_design_studio.preview_modal_title', 'Dialog-Fenster & Personalakte')}
          </span>
          <span class="text-[10px] font-mono px-1.5 py-0.2 rounded bg-[var(--secondary)]">Modal</span>
        </div>
        <p class="text-[11px] text-[var(--muted-foreground)]">
          ${cdsT('ui.component_design_studio.preview_modal_desc', 'Vorschau des Modal-Körpers für Dialoge und Detailansichten.')}
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
          <span>${cdsT('ui.component_design_studio.preview_logo_title', 'FIRMENLOGO VORSCHAU')}</span>
          <span class="text-emerald-500 font-bold">${cdsT('ui.component_design_studio.preview_badge_active', 'Aktiv')}</span>
        </div>
        <div class="p-2 rounded-lg bg-black/10 dark:bg-black/40 flex items-center justify-center min-h-[50px] w-full">
          <img id="crm-modal-logo-preview" src="${currentLogo}" onerror="this.src='/static/archon_os_logo.png';" class="max-h-10 max-w-[190px] object-contain transition-transform hover:scale-105" alt="${cdsT('ui.component_design_studio.preview_logo_alt', 'Logo Vorschau')}" />
        </div>
        <span class="text-[9.5px] font-mono text-[var(--muted-foreground)]">${cdsT('ui.component_design_studio.preview_logo_hint', "Klicke unten auf 'Bild auswählen...', um das Logo zu ändern")}</span>
      </div>
    `;
  }
  else {
    box.innerHTML = `<div class="p-3 text-xs text-[var(--muted-foreground)]">${cdsT('ui.component_design_studio.preview_generic', 'Vorschau für {component}', { component: comp })}</div>`;
  }
}

// =========================================================================
// POINT & CLICK INSPECTOR (Punkt 2: Klick auf DOM fokussiert Baustein 01-15)
// =========================================================================
let cdsInspectorActive = false;
let cdsInspectorHighlightEl = null;

function cdsToggleInspectorMode() {
  cdsInspectorActive = !cdsInspectorActive;
  const btn = document.getElementById("cds-inspector-btn");
  const txt = document.getElementById("cds-inspector-btn-text");

  if (!cdsInspectorHighlightEl) {
    cdsInspectorHighlightEl = document.createElement("div");
    cdsInspectorHighlightEl.id = "cds-inspector-overlay";
    cdsInspectorHighlightEl.style.cssText = "position:fixed;pointer-events:none;z-index:999999;border:2px dashed #6366f1;background:rgba(99,102,241,0.12);transition:all 0.08s ease;display:none;border-radius:6px;";
    document.body.appendChild(cdsInspectorHighlightEl);
  }

  if (cdsInspectorActive) {
    if (btn) btn.className = "px-3 py-1.5 rounded-lg border border-amber-500 bg-amber-500/20 text-amber-600 dark:text-amber-400 font-mono font-bold text-xs transition flex items-center gap-1.5 cursor-pointer shadow-xs animate-pulse";
    if (txt) txt.textContent = cdsT('ui.component_design_studio.inspector_pick', '🔍 Klicke ein Element...');
    document.addEventListener("mousemove", cdsOnInspectorMouseMove, true);
    document.addEventListener("click", cdsOnInspectorClick, true);
  } else {
    if (btn) btn.className = "px-3 py-1.5 rounded-lg border border-indigo-500/40 bg-indigo-500/10 hover:bg-indigo-500/20 text-indigo-600 dark:text-indigo-400 font-mono font-bold text-xs transition flex items-center gap-1.5 cursor-pointer shadow-xs";
    if (txt) txt.textContent = cdsT('ui.component_design_studio.inspector_idle', '🎯 Element anklicken');
    if (cdsInspectorHighlightEl) cdsInspectorHighlightEl.style.display = "none";
    document.removeEventListener("mousemove", cdsOnInspectorMouseMove, true);
    document.removeEventListener("click", cdsOnInspectorClick, true);
  }
}

function cdsDetectComponentFromElement(target) {
  if (!target || !(target instanceof Element)) return null;
  // Ignoriere Klicks im Modal / Studio selbst
  if (target.closest("#system-settings-modal") || target.closest("#archon-15-component-studio")) {
    return null;
  }
  // Durchlaufe die 15 Komponenten in umgekehrter Spezifitäts-Reihenfolge
  for (let i = ARCHON_15_COMPONENTS.length - 1; i >= 0; i--) {
    const comp = ARCHON_15_COMPONENTS[i];
    const sel = comp.selectors.normal;
    if (!sel) continue;
    try {
      const match = target.closest(sel);
      if (match) return comp.id;
    } catch (e) {}
  }
  return "os-workspace";
}

function cdsOnInspectorMouseMove(e) {
  if (!cdsInspectorActive || !cdsInspectorHighlightEl) return;
  const target = e.target;
  if (!target || target.closest("#system-settings-modal")) {
    cdsInspectorHighlightEl.style.display = "none";
    return;
  }
  const rect = target.getBoundingClientRect();
  cdsInspectorHighlightEl.style.display = "block";
  cdsInspectorHighlightEl.style.top = rect.top + "px";
  cdsInspectorHighlightEl.style.left = rect.left + "px";
  cdsInspectorHighlightEl.style.width = rect.width + "px";
  cdsInspectorHighlightEl.style.height = rect.height + "px";
}

function cdsOnInspectorClick(e) {
  if (!cdsInspectorActive) return;
  // Wenn Klick im Studio selbst: Normales Verhalten
  if (e.target && e.target.closest("#system-settings-modal")) return;

  e.preventDefault();
  e.stopPropagation();

  const detectedCompId = cdsDetectComponentFromElement(e.target);
  if (detectedCompId) {
    cdsSelectComponent(detectedCompId);
    // Öffne das Studio / springe zum Tab falls Modal noch im Hintergrund
    if (typeof openSystemSettingsModal === "function") {
      openSystemSettingsModal();
      if (typeof switchSettingsTab === "function") switchSettingsTab("design");
    }
  }
  cdsToggleInspectorMode(); // Inspector beenden nach erfolgreichem Klick
}

window.initArchonComponentDesign = initArchonComponentDesign;
window.cdsRenderUI = cdsRenderUI;
window.cdsSetMode = cdsSetMode;
window.cdsSelectComponent = cdsSelectComponent;
window.cdsSelectState = cdsSelectState;
window.cdsSetProp = cdsSetProp;
window.cdsSetKanbanColColor = cdsSetKanbanColColor;
window.cdsSetKanbanColBgAlpha = cdsSetKanbanColBgAlpha;
window.cdsResetCurrentComponent = cdsResetCurrentComponent;
window.cdsSelectTheme = cdsSelectTheme;
window.cdsSaveAsNewTheme = cdsSaveAsNewTheme;
window.cdsSaveToServer = cdsSaveToServer;
window.cdsDeleteActiveTheme = cdsDeleteActiveTheme;
window.cdsExportThemeJson = cdsExportThemeJson;
window.cdsImportThemeJson = cdsImportThemeJson;
window.cdsUploadBgImage = cdsUploadBgImage;
window.cdsToggleInspectorMode = cdsToggleInspectorMode;


