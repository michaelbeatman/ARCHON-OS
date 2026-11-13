// =========================================================================
// ARCHON OS — GLOBAL COMMAND PALETTE (Strg + K / Cmd + K)
// =========================================================================

(function() {
  // Huelle als Fabrikfunktion: beim Skript-Parsen ist der Katalog noch nicht
  // geladen, ein const-Literal wuerde dauerhaft den deutschen Fallback zeigen.
  function paletteHTML() {
    return `
    <div id="archon-command-palette-backdrop" class="fixed inset-0 bg-black/60 backdrop-blur-xs z-[99999] hidden flex items-start justify-center pt-[12vh] px-4 animate-in fade-in duration-150">
      <div id="archon-command-palette-modal" class="w-full max-w-xl bg-[var(--card)] border border-[var(--border)] rounded-2xl shadow-2xl overflow-hidden flex flex-col font-sans text-xs border-[var(--border)]">
        <!-- Search Input Bar -->
        <div class="flex items-center gap-2.5 px-4 py-3 border-b border-[var(--border)] bg-[var(--background)]">
          <i data-lucide="search" class="w-4 h-4 text-[var(--muted-foreground)] shrink-0"></i>
          <input type="text" id="palette-search-input" placeholder="${cpT('ui.command_palette.search_placeholder', "Tippe einen Befehl, Agenten (@...), Tab (#...) oder 'task: ...' ein...")}" 
            class="flex-1 bg-transparent border-none text-[13px] text-[var(--foreground)] placeholder-[var(--muted-foreground)] focus:outline-none font-medium" autocomplete="off" />
          <kbd class="px-2 py-0.5 rounded bg-[var(--secondary)] text-[10px] font-mono text-[var(--muted-foreground)] border border-[var(--border)]">ESC</kbd>
        </div>

        <!-- Quick Filter Category Chips -->
        <div class="flex items-center gap-1.5 px-3 py-1.5 border-b border-[var(--border)] bg-[var(--card)] overflow-x-auto text-[10.5px]">
          <span class="text-[9.5px] font-mono uppercase text-[var(--muted-foreground)] mr-1">${cpT('ui.command_palette.filter_label', 'Filter:')}</span>
          <button type="button" onclick="cmdPaletteSetFilter('')" class="px-2 py-0.5 rounded-full border border-[var(--border)] hover:bg-[var(--secondary)] cursor-pointer font-medium cmd-filter-btn active-filter" data-filter="">${cpT('ui.command_palette.filter_all', 'Alle')}</button>
          <button type="button" onclick="cmdPaletteSetFilter('tab')" class="px-2 py-0.5 rounded-full border border-[var(--border)] hover:bg-[var(--secondary)] cursor-pointer font-medium cmd-filter-btn" data-filter="tab">${cpT('ui.command_palette.filter_tabs', '📌 Ansichten')}</button>
          <button type="button" onclick="cmdPaletteSetFilter('agent')" class="px-2 py-0.5 rounded-full border border-[var(--border)] hover:bg-[var(--secondary)] cursor-pointer font-medium cmd-filter-btn" data-filter="agent">${cpT('ui.command_palette.filter_agents', '🤖 {count} Agenten', { count: 54 })}</button>
          <button type="button" onclick="cmdPaletteSetFilter('action')" class="px-2 py-0.5 rounded-full border border-[var(--border)] hover:bg-[var(--secondary)] cursor-pointer font-medium cmd-filter-btn" data-filter="action">${cpT('ui.command_palette.filter_actions', '⚡ Aktionen')}</button>
        </div>

        <!-- Results List -->
        <div id="palette-results-list" class="max-h-[50vh] overflow-y-auto p-2 space-y-1 custom-scrollbar"></div>

        <!-- Footer / Shortcut Hint -->
        <div class="flex items-center justify-between px-4 py-2 border-t border-[var(--border)] bg-[var(--background)] text-[10px] text-[var(--muted-foreground)] font-mono">
          <div class="flex items-center gap-3">
            <span><kbd class="px-1 py-0.2 bg-[var(--secondary)] border border-[var(--border)] rounded">↑</kbd> <kbd class="px-1 py-0.2 bg-[var(--secondary)] border border-[var(--border)] rounded">↓</kbd> ${cpT('ui.command_palette.nav_hint', 'Navigieren')}</span>
            <span><kbd class="px-1.5 py-0.2 bg-[var(--secondary)] border border-[var(--border)] rounded">↵</kbd> ${cpT('ui.command_palette.run_hint', 'Ausführen')}</span>
          </div>
          <span>Archon Omnibox v2.0</span>
        </div>
      </div>
    </div>
  `;
  }

  // --- i18n-Helfer (Tranche 7) -------------------------------------------
  // cpT() liefert den Katalogtext mit PFLICHT-Fallback: fehlt der Key in der
  // aktiven Sprache und in de, bleibt der deutsche Text stehen - nie "".
  // {platzhalter} werden aus params gefuellt (Zahlen stehen nie im Key).
  function cpT(key, fallback, params) {
    const i18n = window.archonI18n;
    let text = i18n ? i18n.t(key, fallback) : fallback;
    if (params) {
      Object.keys(params).forEach(name => {
        text = text.split(`{${name}}`).join(String(params[name]));
      });
    }
    return text;
  }

  let activeIndex = 0;
  let currentFilter = '';
  let itemsCache = [];

  // Fabrikfunktionen statt const: die Titel/Untertitel werden beim Aufruf
  // (Palette oeffnen, Filter setzen) lokalisiert, nicht beim Skript-Parsen.
  function getAllTabs() {
    return [
      { id: 'mission-control', title: cpT('ui.command_palette.tab_mission_control_title', 'Mission Control'), desc: cpT('ui.command_palette.tab_mission_control_desc', 'System-Cockpit, Status & Metriken'), icon: 'layout-dashboard', cat: 'tab', action: () => setTab('mission-control') },
      { id: 'operations', title: cpT('ui.command_palette.tab_operations_title', 'Operations (Projekte)'), desc: cpT('ui.command_palette.tab_operations_desc', 'Projekt-Zentrale, Fortschritt & Vault-Artefakte'), icon: 'folder-kanban', cat: 'tab', action: () => setTab('operations', 'projects') },
      { id: 'kanban', title: cpT('ui.command_palette.tab_kanban_title', 'Operations (Kanban)'), desc: cpT('ui.command_palette.tab_kanban_desc', 'Hermes Kanban-Board, Sprints & Aufgaben'), icon: 'kanban', cat: 'tab', action: () => setTab('operations', 'kanban') },
      { id: 'agent-profiles', title: cpT('ui.command_palette.tab_agents_title', 'Agenten-Kader'), desc: cpT('ui.command_palette.tab_agents_desc', '{count} Spezialistenprofile & Disposition', { count: 54 }), icon: 'users', cat: 'tab', action: () => setTab('agent-profiles') },
      { id: 'inbox', title: cpT('ui.command_palette.tab_inbox_title', 'Eingang (Intake)'), desc: cpT('ui.command_palette.tab_inbox_desc', 'Triage, E-Mail- & Telegram-Sync'), icon: 'inbox', cat: 'tab', action: () => setTab('inbox') },
      { id: 'automation', title: cpT('ui.command_palette.tab_automation_title', 'Workflow-Engine'), desc: cpT('ui.command_palette.tab_automation_desc', 'n8n Automations-Pipelines'), icon: 'workflow', cat: 'tab', action: () => setTab('automation') },
      { id: 'showroom', title: cpT('ui.command_palette.tab_showroom_title', 'Showroom (Apps)'), desc: cpT('ui.command_palette.tab_showroom_desc', 'Micro-Apps & Generierte Werkzeuge'), icon: 'layout', cat: 'tab', action: () => setTab('showroom') },
      { id: 'library', title: cpT('ui.command_palette.tab_library_title', 'Bibliothek & Vault'), desc: cpT('ui.command_palette.tab_library_desc', 'AnythingLLM RAG, Dokumenten-Erfasser & Obsidian Notes'), icon: 'book-open', cat: 'tab', action: () => setTab('library') },
      { id: 'research', title: cpT('ui.command_palette.tab_research_title', 'Research Vault'), desc: cpT('ui.command_palette.tab_research_desc', 'Markt- & Wettbewerbs-Dossiers'), icon: 'globe', cat: 'tab', action: () => setTab('research') },
      { id: 'token-guard', title: cpT('ui.command_palette.tab_guardian_title', 'Token Guard & Limits'), desc: cpT('ui.command_palette.tab_guardian_desc', 'Raten- & Budgetwächter Telemetrie'), icon: 'gauge', cat: 'tab', action: () => setTab('guardian') },
      { id: 'log-stream', title: cpT('ui.command_palette.tab_logs_title', 'Telemetrie & Logs'), desc: cpT('ui.command_palette.tab_logs_desc', 'Echtzeit Audit-Logs & Traces'), icon: 'activity', cat: 'tab', action: () => setTab('log-stream') }
    ];
  }

  function getSystemActions() {
    return [
      { id: 'act-settings', title: cpT('ui.command_palette.act_settings_title', 'System-Einstellungen öffnen'), desc: cpT('ui.command_palette.act_settings_desc', 'OmniRoute, Docker & Backend konfigurieren'), icon: 'settings', cat: 'action', action: () => openSystemSettingsModal() },
      { id: 'act-css-live-studio', title: cpT('ui.command_palette.act_css_studio_title', 'CSS Live Studio öffnen (Alt + S)'), desc: cpT('ui.command_palette.act_css_studio_desc', 'Interaktiver In-Place Inspector, Drag Gizmo & Live CSS-Regeln'), icon: 'palette', cat: 'action', action: () => { if (typeof toggleCssStudio === 'function') toggleCssStudio(); } },
      { id: 'act-design-studio', title: cpT('ui.command_palette.act_design_studio_title', '{count}-Komponenten Design Studio öffnen', { count: 15 }), desc: cpT('ui.command_palette.act_design_studio_desc', 'Farben, Abstände, Schatten & Dual-Themes'), icon: 'sliders', cat: 'action', action: () => { openSystemSettingsModal(); if (typeof switchSettingsTab === 'function') switchSettingsTab('design'); } },
      { id: 'act-inspector', title: cpT('ui.command_palette.act_inspector_title', 'Design-Studio Inspector aktivieren'), desc: cpT('ui.command_palette.act_inspector_desc', 'Klicke beliebiges DOM-Element zur Baustein-Auswahl'), icon: 'crosshair', cat: 'action', action: () => { if (typeof cdsToggleInspectorMode === 'function') cdsToggleInspectorMode(); } },
      { id: 'act-theme-toggle', title: cpT('ui.command_palette.act_theme_title', 'Theme wechseln (Hell / Dunkel)'), desc: cpT('ui.command_palette.act_theme_desc', 'Schaltet Farbmodus um'), icon: 'sun', cat: 'action', action: () => toggleTheme() },
      { id: 'act-email-sync', title: cpT('ui.command_palette.act_email_sync_title', 'E-Mail & CRM Sync ausführen'), desc: cpT('ui.command_palette.act_email_sync_desc', 'Synchronisiert Kontakte & Posteingang'), icon: 'mail', cat: 'action', action: () => { if (typeof runEmailSync === 'function') runEmailSync(); else if (typeof showArchonToast === 'function') showArchonToast(cpT('ui.command_palette.toast_sync_started', 'Sync gestartet'), 'info'); } }
    ];
  }

  function getAgentItems() {
    if (window._CACHED_AGENT_PROFILES && Array.isArray(window._CACHED_AGENT_PROFILES)) {
      return window._CACHED_AGENT_PROFILES.map(p => ({
        id: 'agent-' + p.id,
        title: `@${p.person_name || p.id} (${p.name || cpT('ui.command_palette.agent_role_fallback', 'Spezialist')})`,
        desc: `${p.model || 'Claude'} · ${p.category || cpT('ui.command_palette.agent_category_fallback', 'Fachbereich')} · ${cpT('ui.command_palette.agent_click', 'Klick zum Profil')}`,
        icon: 'bot',
        avatar: p.avatar,
        cat: 'agent',
        action: () => {
          setTab('agent-profiles');
          setTimeout(() => {
            if (typeof selectAgentProfile === 'function') selectAgentProfile(p.id);
          }, 150);
        }
      }));
    }
    return [];
  }

  function getAllItems() {
    return [...getAllTabs(), ...getSystemActions(), ...getAgentItems()];
  }

  function renderResults(query = '') {
    const list = document.getElementById('palette-results-list');
    if (!list) return;

    const q = query.trim().toLowerCase();
    let all = getAllItems();

    if (currentFilter) {
      all = all.filter(item => item.cat === currentFilter);
    }

    let filtered = all;
    if (q) {
      if (q.startsWith('@')) {
        const namePart = q.slice(1);
        filtered = all.filter(it => it.cat === 'agent' && (it.title.toLowerCase().includes(namePart) || it.id.toLowerCase().includes(namePart)));
      } else if (q.startsWith('#')) {
        const tabPart = q.slice(1);
        filtered = all.filter(it => it.cat === 'tab' && it.title.toLowerCase().includes(tabPart));
      } else if (q.startsWith('task:')) {
        const taskTitle = q.slice(5).trim();
        filtered = [{
          id: 'quick-capture-task',
          title: cpT('ui.command_palette.capture_title', '📝 Aufgabe anlegen: "{query}"', { query: taskTitle || '...' }),
          desc: cpT('ui.command_palette.capture_desc', 'Drücke Enter, um diese Aufgabe direkt in Mission Control zu erfassen'),
          icon: 'plus-circle',
          cat: 'action',
          action: () => {
            if (!taskTitle) return;
            fetch('/api/mission-control/tasks/capture', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ title: taskTitle })
            }).then(r => r.json()).then(() => {
              if (typeof showArchonToast === 'function') showArchonToast(cpT('ui.command_palette.capture_success', 'Aufgabe "{title}" erfasst!', { title: taskTitle }), 'success');
              if (typeof fetchMissionControlData === 'function') fetchMissionControlData(true);
            });
          }
        }];
      } else {
        filtered = all.filter(it => 
          it.title.toLowerCase().includes(q) || 
          (it.desc && it.desc.toLowerCase().includes(q)) || 
          it.id.toLowerCase().includes(q)
        );
      }
    }

    itemsCache = filtered;
    activeIndex = Math.min(activeIndex, Math.max(0, filtered.length - 1));

    if (!filtered.length) {
      list.innerHTML = `<div class="p-6 text-center text-[var(--muted-foreground)]">${cpT('ui.command_palette.no_results', 'Keine Treffer für "{query}" gefunden.', { query: opsEscapeHtml(query) })}</div>`;
      return;
    }

    list.innerHTML = filtered.map((it, idx) => {
      const isSel = idx === activeIndex;
      const avatarHtml = it.avatar 
        ? `<img src="${it.avatar}" class="w-6 h-6 rounded-full object-cover shrink-0 border border-[var(--border)]" />`
        : `<div class="w-6 h-6 rounded-lg bg-[var(--secondary)] flex items-center justify-center text-[var(--foreground)] shrink-0 border border-[var(--border)]"><i data-lucide="${it.icon || 'circle'}" class="w-3.5 h-3.5"></i></div>`;
      const catBadge = it.cat === 'tab'
        ? cpT('ui.command_palette.badge_tab', '📌 Ansicht')
        : (it.cat === 'agent' ? cpT('ui.command_palette.badge_agent', '🤖 Agent') : cpT('ui.command_palette.badge_action', '⚡ Aktion'));

      return `
        <div onclick="cmdPaletteExecute(${idx})" onmouseenter="cmdPaletteHover(${idx})"
          class="flex items-center justify-between gap-2.5 px-3 py-2 rounded-xl cursor-pointer transition select-none ${isSel ? 'bg-[var(--secondary)] border border-[var(--border)] font-semibold shadow-xs' : 'hover:bg-[var(--secondary)]/50 border border-transparent'}">
          <div class="flex items-center gap-2.5 min-w-0">
            ${avatarHtml}
            <div class="truncate">
              <div class="text-[12px] text-[var(--foreground)] truncate">${opsEscapeHtml(it.title)}</div>
              ${it.desc ? `<div class="text-[10px] text-[var(--muted-foreground)] truncate">${opsEscapeHtml(it.desc)}</div>` : ''}
            </div>
          </div>
          <span class="text-[9.5px] font-mono px-2 py-0.5 rounded-full bg-[var(--background)] border border-[var(--border)] text-[var(--muted-foreground)] shrink-0">${catBadge}</span>
        </div>
      `;
    }).join('');

    if (window.lucide) lucide.createIcons();
    scrollActiveIntoView();
  }

  function scrollActiveIntoView() {
    const list = document.getElementById('palette-results-list');
    if (!list) return;
    const activeEl = list.children[activeIndex];
    if (activeEl) {
      activeEl.scrollIntoView({ block: 'nearest' });
    }
  }

  window.openCommandPalette = function() {
    const backdrop = document.getElementById('archon-command-palette-backdrop');
    const input = document.getElementById('palette-search-input');
    if (!backdrop || !input) return;
    backdrop.classList.remove('hidden');
    input.value = '';
    activeIndex = 0;
    renderResults('');
    setTimeout(() => input.focus(), 50);
  };

  window.closeCommandPalette = function() {
    const backdrop = document.getElementById('archon-command-palette-backdrop');
    if (backdrop) backdrop.classList.add('hidden');
  };

  window.cmdPaletteExecute = function(idx) {
    if (itemsCache[idx] && typeof itemsCache[idx].action === 'function') {
      closeCommandPalette();
      try {
        itemsCache[idx].action();
      } catch (e) {
        console.error('[CommandPalette] Action error:', e);
      }
    }
  };

  window.cmdPaletteHover = function(idx) {
    activeIndex = idx;
    const list = document.getElementById('palette-results-list');
    if (!list) return;
    Array.from(list.children).forEach((child, i) => {
      if (i === idx) {
        child.classList.add('bg-[var(--secondary)]', 'border-[var(--border)]');
      } else {
        child.classList.remove('bg-[var(--secondary)]', 'border-[var(--border)]');
      }
    });
  };

  window.cmdPaletteSetFilter = function(f) {
    currentFilter = f;
    document.querySelectorAll('.cmd-filter-btn').forEach(b => {
      if (b.dataset.filter === f) {
        b.className = 'px-2 py-0.5 rounded-full border border-zinc-900 bg-zinc-900 text-white dark:border-zinc-100 dark:bg-zinc-100 dark:text-zinc-900 cursor-pointer font-bold cmd-filter-btn active-filter';
      } else {
        b.className = 'px-2 py-0.5 rounded-full border border-[var(--border)] hover:bg-[var(--secondary)] cursor-pointer font-medium cmd-filter-btn';
      }
    });
    const input = document.getElementById('palette-search-input');
    renderResults(input ? input.value : '');
  };

  // Huelle einfuegen; Inhalt kommt aus paletteHTML() (aktive Sprache).
  function mountPalette() {
    const wrapper = document.createElement('div');
    wrapper.innerHTML = paletteHTML();
    document.body.appendChild(wrapper.firstElementChild);
  }

  // Handler werden nach jedem (Neu-)Einfuegen der Huelle gebunden.
  function bindPaletteHandlers() {
    const input = document.getElementById('palette-search-input');
    if (input) {
      input.addEventListener('input', (e) => {
        activeIndex = 0;
        renderResults(e.target.value);
      });
      input.addEventListener('keydown', (e) => {
        if (e.key === 'ArrowDown') {
          e.preventDefault();
          if (itemsCache.length > 0) {
            activeIndex = (activeIndex + 1) % itemsCache.length;
            renderResults(input.value);
          }
        } else if (e.key === 'ArrowUp') {
          e.preventDefault();
          if (itemsCache.length > 0) {
            activeIndex = (activeIndex - 1 + itemsCache.length) % itemsCache.length;
            renderResults(input.value);
          }
        } else if (e.key === 'Enter') {
          e.preventDefault();
          cmdPaletteExecute(activeIndex);
        } else if (e.key === 'Escape') {
          e.preventDefault();
          closeCommandPalette();
        }
      });
    }

    const backdrop = document.getElementById('archon-command-palette-backdrop');
    if (backdrop) {
      backdrop.addEventListener('click', (e) => {
        if (e.target === backdrop) closeCommandPalette();
      });
    }
  }

  // Setup DOM Injection & Key Listeners
  document.addEventListener('DOMContentLoaded', () => {
    if (!document.getElementById('archon-command-palette-backdrop')) {
      mountPalette();
    }
    bindPaletteHandlers();
  });

  // Sprachwechsel: Huelle neu aufbauen (Texte stehen in Template-Strings,
  // nicht in data-i18n-Ankern); offener Zustand bleibt erhalten.
  window.addEventListener('archon:language-changed', () => {
    const existing = document.getElementById('archon-command-palette-backdrop');
    if (!existing) return;
    const wasOpen = !existing.classList.contains('hidden');
    existing.remove();
    mountPalette();
    bindPaletteHandlers();
    if (wasOpen) window.openCommandPalette();
  });

  // Global Keyboard Shortcut: Strg + K / Cmd + K
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K')) {
      e.preventDefault();
      const backdrop = document.getElementById('archon-command-palette-backdrop');
      if (backdrop && !backdrop.classList.contains('hidden')) {
        closeCommandPalette();
      } else {
        openCommandPalette();
      }
    }
  });
})();
