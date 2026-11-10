
    function togglePasswordVisibility(inputId, btnEl) {
      const input = document.getElementById(inputId);
      if (!input) return;
      input.type = input.type === "password" ? "text" : "password";
    }
    window.togglePasswordVisibility = togglePasswordVisibility;


    // --- SYSTEM CONTROL CENTER LOGIC ---
    let currentEditingRoleSettingsId = "";
    // Fix 2026-10-09 (Race Condition): #system-settings-mount existiert erst in
    // view_design_system.html, die erst NACH dem Settings-Fetch in initArchonApp()
    // montiert wird. Dieser Guard holt das Modal nach, wo immer es fehlt.
    async function ensureSettingsModalMounted() {
      if (document.getElementById("system-settings-modal")) return true;
      try {
        const res = await fetch("/static/views/system_settings_modal.html?v=202610241330");
        if (!res.ok) { return false; }
        const html = await res.text();
        let target = document.getElementById("system-settings-mount");
        if (target) { target.outerHTML = html; } else {
          const div = document.createElement("div");
          div.innerHTML = html;
          document.body.appendChild(div);
        }
        return !!document.getElementById("system-settings-modal");
      } catch (e) {
        return false;
      }
    }
    window.ensureSettingsModalMounted = ensureSettingsModalMounted;
    async function openSystemSettingsModal(defaultTab = "kernel") {
      try {
        await ensureSettingsModalMounted();
        const res = await fetch("/api/settings");
        const settings = await res.json();
        const gwEl = document.getElementById("setting-gateway-url");
        if (gwEl) gwEl.value = settings.gateway_url || "http://localhost:20128/v1";
        const wsEl = document.getElementById("setting-workspace-dir");
        if (wsEl) wsEl.value = settings.workspace_dir || "";
        // JEV Settings laden
        const jev = settings.jev || {};
        const jevEnabledEl = document.getElementById("setting-jev-enabled");
        if (jevEnabledEl) {
          jevEnabledEl.checked = !!jev.enabled;
          const lbl = document.getElementById("setting-jev-toggle-label");
          if (lbl) lbl.innerText = jev.enabled ? "Aktiviert" : "Inaktiv";
        }
        const jevProviderEl = document.getElementById("setting-jev-provider");
        const jevModelEl = document.getElementById("setting-jev-model");
        if (jevProviderEl && jev.provider) jevProviderEl.value = jev.provider;
        if (jevModelEl && jev.model) jevModelEl.value = jev.model;
        const jevUrlEl = document.getElementById("setting-jev-url");
        if (jevUrlEl) jevUrlEl.value = jev.base_url || "https://openrouter.ai/api/v1";
        const jevKeyEl = document.getElementById("setting-jev-key");
        if (jevKeyEl) jevKeyEl.value = jev.api_key || "";
        const jevFastpathEl = document.getElementById("setting-jev-fastpath");
        if (jevFastpathEl) jevFastpathEl.checked = jev.fast_path_enabled !== false;
        const jevPruningEl = document.getElementById("setting-jev-pruning");
        if (jevPruningEl) jevPruningEl.checked = jev.tool_pruning_enabled !== false;
        const jevRoutingEl = document.getElementById("setting-jev-routing");
        if (jevRoutingEl) jevRoutingEl.checked = jev.agent_routing_enabled !== false;
        updateJevStatusPill(!!jev.enabled);
        // Memory Settings laden
        const mem = settings.memory || {};
        const memEnabledEl = document.getElementById("setting-memory-enabled");
        if (memEnabledEl) {
          memEnabledEl.checked = mem.enabled !== false;
          const lbl = document.getElementById("setting-memory-toggle-label");
          if (lbl) lbl.innerText = (mem.enabled !== false) ? "Aktiv" : "Inaktiv";
        }
        const memAutoLearnEl = document.getElementById("setting-memory-autolearn");
        if (memAutoLearnEl) memAutoLearnEl.checked = mem.auto_learn !== false;
        const memApplyEl = document.getElementById("setting-memory-apply-lessons");
        if (memApplyEl) memApplyEl.checked = mem.apply_lessons !== false;
        const memMaxLessonsEl = document.getElementById("setting-memory-max-lessons");
        if (memMaxLessonsEl) memMaxLessonsEl.value = mem.max_injected_lessons || 3;
        const memHalfLifeEl = document.getElementById("setting-memory-halflife");
        if (memHalfLifeEl) memHalfLifeEl.value = mem.half_life_days || 14;
        const memThresholdEl = document.getElementById("setting-memory-threshold");
        if (memThresholdEl) memThresholdEl.value = mem.eviction_threshold || 0.1;
        const memAutoEvictEl = document.getElementById("setting-memory-auto-evict");
        if (memAutoEvictEl) memAutoEvictEl.checked = !!mem.auto_evict;
        const memVaultEl = document.getElementById("setting-memory-vault");
        if (memVaultEl) memVaultEl.value = mem.vault_path || "C:\\Mein Obsidian";
        const memHoursEl = document.getElementById("setting-memory-hours");
        if (memHoursEl) memHoursEl.value = mem.hours_back || 24;
        refreshMemoryStats();
        // Email Guard Settings laden
        const eg = settings.email_guard || {};
        const egEnabledEl = document.getElementById("setting-email-guard-enabled");
        if (egEnabledEl) {
          egEnabledEl.checked = eg.enabled !== false;
          const lbl = document.getElementById("setting-email-guard-toggle-label");
          if (lbl) lbl.innerText = (eg.enabled !== false) ? "Aktiv" : "Inaktiv";
        }
        const egMailEl = document.getElementById("setting-guard-protect-email");
        if (egMailEl) egMailEl.checked = eg.protect_email !== false;
        const egTgEl = document.getElementById("setting-guard-protect-telegram");
        if (egTgEl) egTgEl.checked = eg.protect_telegram !== false;
        const egCrmEl = document.getElementById("setting-guard-protect-crm");
        if (egCrmEl) egCrmEl.checked = eg.protect_crm !== false;
        const egSensEl = document.getElementById("setting-guard-sensitivity");
        if (egSensEl && eg.sensitivity) egSensEl.value = eg.sensitivity;
        refreshSecurityStats();
        // Validate Settings laden
        const valCfg = settings.validate || {};
        const valEnabledEl = document.getElementById("setting-validate-enabled");
        if (valEnabledEl) {
          valEnabledEl.checked = valCfg.enabled !== false;
          const lbl = document.getElementById("setting-validate-toggle-label");
          if (lbl) lbl.innerText = (valCfg.enabled !== false) ? "Aktiv" : "Inaktiv";
        }
        const valMinEl = document.getElementById("setting-validate-min-score");
        if (valMinEl) valMinEl.value = valCfg.min_score || 7;
        const valFailEl = document.getElementById("setting-validate-on-failure");
        if (valFailEl && valCfg.on_failure) valFailEl.value = valCfg.on_failure;
        const valHalluEl = document.getElementById("setting-validate-check-hallucination");
        if (valHalluEl) valHalluEl.checked = valCfg.check_hallucinations !== false;
        const valCutoffEl = document.getElementById("setting-validate-check-cutoff");
        if (valCutoffEl) valCutoffEl.checked = valCfg.check_cutoff !== false;
        const valLlmEl = document.getElementById("setting-validate-use-llm");
        if (valLlmEl) valLlmEl.checked = !!valCfg.use_llm;
      } catch (e) {
        console.error("Failed to load settings:", e);
      }
      
      const gwKeyEl = document.getElementById("setting-gateway-key");
      // Gateway key is loaded from backend environment or settings
      if (gwKeyEl && !gwKeyEl.value) gwKeyEl.value = "";
      try {
        const res = await fetch("/api/v1/services");
        servicesList = await res.json();
      } catch (e) {
        console.error("Failed to load services:", e);
      }
      try {
        await loadThemeFromServer();
        initLogoUpload();
        syncInputsWithSettings();
      } catch (e) {
        console.error("Failed to load theme in settings modal:", e);
      }
      try {
        populateSettingsRoleDropdown();
        if (typeof roles !== 'undefined' && roles.length > 0) {
          loadRoleIntoSettingsEditor(roles[0].id);
        }
      } catch (e) {
        console.error("Failed to load roles in settings modal:", e);
      }
      try {
        await loadFrameworksFromServer();
        populateSettingsFrameworkDropdown();
        const fwSelect = document.getElementById("setting-framework-select");
        if (fwSelect && fwSelect.options.length > 0) {
          loadFrameworkIntoSettingsEditor(fwSelect.options[0].value);
        }
      } catch (e) {
        console.error("Failed to load frameworks in settings modal:", e);
      }
      try {
        renderSettingsServices();
      } catch (e) {
        console.error("Failed to render services:", e);
      }
      try {
        setSettingsTab(defaultTab);
      } catch (e) {
        console.error("Failed to set settings tab:", e);
      }
      const modal = document.getElementById("system-settings-modal");
      if (modal) {
        modal.classList.remove("hidden");
        if (window.buildSettingsSearchIndex) {
          setTimeout(window.buildSettingsSearchIndex, 250);
        }
      }
    }
    function closeSystemSettingsModal() {
      if (window.clearSettingsGlobalSearch) {
        window.clearSettingsGlobalSearch();
      }
      document.getElementById("system-settings-modal").classList.add("hidden");
    }
    function setSettingsTab(tabName) {
      // Wenn Suchergebnis aktiv war, beim Tab-Klick Suche sauber zurücksetzen
      const searchPane = document.getElementById("settings-tab-search-results");
      if (searchPane && !searchPane.classList.contains("hidden")) {
        searchPane.classList.add("hidden");
        const sInput = document.getElementById("settings-global-search-input");
        if (sInput) sInput.value = "";
        const sClear = document.getElementById("settings-global-search-clear-btn");
        if (sClear) sClear.classList.add("hidden");
      }
      // Normalisiere Legacy- oder Subtab-Namen
      let targetTab = tabName;
      let targetSubTab = null;
      if (tabName === "roles") {
        targetTab = "kernel";
      } else if (["jev", "memory", "email-guard", "validate", "cost"].includes(tabName)) {
        targetTab = "plugins";
        targetSubTab = tabName;
      } else if (["smtp", "telegram", "n8n"].includes(tabName)) {
        targetTab = "comm";
        targetSubTab = tabName;
      }

      activeSettingsTab = targetTab;
      const tabs = ["kernel", "autonomy", "services", "routing", "keys", "frameworks", "plugins", "comm", "design", "update", "users"];
      tabs.forEach(t => {
        const pane = document.getElementById(`settings-tab-${t}`);
        const btn = document.getElementById(`btn-tab-${t}`);
        if (!pane || !btn) return;
        if (t === targetTab) {
          pane.classList.remove("hidden");
          btn.style.borderColor = "var(--border)";
          btn.style.backgroundColor = "var(--card)";
          btn.style.color = "var(--foreground)";
          btn.style.fontWeight = "bold";
          btn.style.zIndex = "2";
          btn.style.borderBottom = "1.5px solid var(--card)";
        } else {
          pane.classList.add("hidden");
          btn.style.borderColor = "transparent";
          btn.style.backgroundColor = "transparent";
          btn.style.color = "var(--muted-foreground)";
          btn.style.fontWeight = "normal";
          btn.style.zIndex = "1";
          btn.style.borderBottom = "1px solid transparent";
        }
      });

      if (targetTab === "users") {
        if (window.authManager) {
          window.authManager.renderSettingsUsersTable();
        }
      }
      if (targetTab === "keys") {
        if (typeof loadApiKeys === "function") {
          loadApiKeys();
        }
      }
      if (targetTab === "update") {
        if (typeof checkSystemUpdateStatus === "function") {
          checkSystemUpdateStatus();
          loadSystemSnapshots();
        }
      }
      if (targetTab === "kernel") {
        if (typeof loadHermesFormSettings === "function") {
          loadHermesFormSettings();
        }
      } else if (targetTab === "autonomy") {
        if (typeof loadMemoryConsolidationSettings === "function") {
          loadMemoryConsolidationSettings();
        }
        if (typeof loadAutonomyModulesSettings === "function") {
          loadAutonomyModulesSettings();
        }
        if (typeof enrichAutonomyCardsAndThresholds === "function") {
          enrichAutonomyCardsAndThresholds();
        }
      } else if (targetTab === "services") {
        if (typeof renderSettingsServices === "function") {
          renderSettingsServices();
        }
      } else if (targetTab === "routing") {
        if (typeof loadLLMProvidersSettings === "function") {
          loadLLMProvidersSettings();
        }
        if (typeof loadModelRoutingSettings === "function") {
          loadModelRoutingSettings();
        }
      } else if (targetTab === "plugins") {
        if (targetSubTab) {
          setPluginSubTab(targetSubTab);
        } else {
          setPluginSubTab("registry");
        }
      } else if (targetTab === "comm") {
        if (targetSubTab) {
          setCommSubTab(targetSubTab);
        } else {
          setCommSubTab("smtp");
        }
      } else if (targetTab === "design") {
        if (typeof window.cdsRenderUI === "function") {
          window.cdsRenderUI();
        }
      }
      lucide.createIcons();
    }

    function setPluginSubTab(subTab) {
      const subTabs = ["registry", "jev", "memory", "email-guard", "validate", "cost"];
      subTabs.forEach(st => {
        const pane = document.getElementById(`plugin-subtab-${st}`);
        const btn = document.getElementById(`btn-plugin-sub-${st}`);
        if (!pane || !btn) return;
        if (st === subTab) {
          pane.classList.remove("hidden");
          btn.className = "px-3 py-1.5 rounded-lg border font-mono text-xs font-bold transition flex items-center gap-1.5 cursor-pointer whitespace-nowrap bg-[var(--card)] text-[var(--foreground)] border-[var(--border)]";
        } else {
          pane.classList.add("hidden");
          btn.className = "px-3 py-1.5 rounded-lg border font-mono text-xs font-normal transition flex items-center gap-1.5 cursor-pointer whitespace-nowrap bg-transparent text-[var(--muted-foreground)] border-transparent hover:text-[var(--foreground)]";
        }
      });
      if (subTab === "registry") {
        loadPluginSettingsRegistry();
      } else if (subTab === "memory") {
        if (typeof loadMemoryStats === "function") loadMemoryStats();
      } else if (subTab === "email-guard") {
        if (typeof loadEmailGuardStats === "function") loadEmailGuardStats();
      }
      lucide.createIcons();
    }

    let settingsPluginsData = [];
    const SETTINGS_PLUGIN_CAT_META = {
      "Sicherheit & Wächter": { icon: "shield-alert", color: "text-rose-500", desc: "Budgetgrenzen, Session-Wächter und Injection-Abwehr" },
      "Performance & Cache": { icon: "zap", color: "text-amber-500", desc: "Token-Optimierung, lokales Caching und Fast-Routing" },
      "Agenten-Intelligenz": { icon: "cpu", color: "text-indigo-500", desc: "Autonomie-Schleifen, Multi-Modell-Debatten und Reflexion" },
      "Planung & Tasks": { icon: "calendar-check", color: "text-emerald-500", desc: "Zielplanung, OKR-Aufteilung und Cron-Trigger" },
      "Brücken & Schnittstellen": { icon: "network", color: "text-blue-500", desc: "MQTT, Telegram, Claude Code Bridge, GitHub und Webhooks" },
      "Gedächtnis & Wissen": { icon: "brain", color: "text-purple-500", desc: "Adaptiver Langzeitspeicher, RAG-Vektordatenbank und Konsolidierung" },
      "Tools & Recherche": { icon: "search", color: "text-sky-500", desc: "Tiefenrecherche, News-Feeds und automatisierte Zusammenfassungen" },
      "Tools & Execution": { icon: "box", color: "text-orange-500", desc: "Sichere Sandbox-Ausführung und isolierte Dateisystem-Werkzeuge" },
      "Monitoring & Analytics": { icon: "gauge", color: "text-teal-500", desc: "Systemtelemetrie, Delegations-Scores und Healthchecks" },
      "Finanzen & Web3": { icon: "wallet", color: "text-yellow-500", desc: "Krypto-Wallet-Monitoring und Salden-Überwachung" },
      "Qualität & Ausführung": { icon: "check-check", color: "text-cyan-500", desc: "Quality Gates, Validierung und Mehrfach-Prüfungen" },
      "System-Wartung": { icon: "trash-2", color: "text-zinc-500", desc: "Log-Bereinigung und persistente Speicherhygiene" },
      "Weitere Module": { icon: "layers", color: "text-zinc-400", desc: "Erweiterte Module und Hintergrund-Agenten" }
    };

    async function loadPluginSettingsRegistry() {
      const container = document.getElementById("settings-plugins-registry-list");
      if (!container) return;
      try {
        const res = await fetch("/api/guardian/config");
        if (!res.ok) throw new Error("HTTP " + res.status);
        const data = await res.json();
        settingsPluginsData = data.plugins || [];
        updatePluginSettingsCounters();
        renderPluginSettingsRegistry();
      } catch (err) {
        console.error("Fehler beim Laden der Plugin-Registry:", err);
        container.innerHTML = `<div class="p-6 text-center text-xs font-mono text-rose-500 border border-rose-500/20 rounded-xl">Fehler beim Laden der Plugins: ${err.message}</div>`;
      }
    }

    function updatePluginSettingsCounters() {
      const badge = document.getElementById("settings-plugins-stats-badge");
      if (!badge) return;
      const total = settingsPluginsData.length;
      const active = settingsPluginsData.filter(p => p.enabled).length;
      badge.innerText = `${active} von ${total} aktiv`;
    }

    function filterPluginSettingsRegistry() {
      renderPluginSettingsRegistry();
    }

    function renderPluginSettingsRegistry() {
      const container = document.getElementById("settings-plugins-registry-list");
      if (!container) return;
      const searchInput = document.getElementById("settings-plugins-search");
      const q = (searchInput ? searchInput.value : "").trim().toLowerCase();

      let list = settingsPluginsData;
      if (q) {
        list = list.filter(p => {
          const nameMatch = (p.name || "").toLowerCase().includes(q);
          const idMatch = (p.id || "").toLowerCase().includes(q);
          const catMatch = (p.category || "").toLowerCase().includes(q);
          const descMatch = (p.desc || p.description || "").toLowerCase().includes(q);
          const toolMatch = Array.isArray(p.tools) && p.tools.some(t => String(t).toLowerCase().includes(q));
          return nameMatch || idMatch || catMatch || descMatch || toolMatch;
        });
      }

      if (!list.length) {
        container.innerHTML = `
          <div class="p-8 text-center text-xs font-mono text-[var(--muted-foreground)] border border-dashed border-[var(--border)] rounded-xl">
            Keine Plugins oder Tools passend zu "${q}" gefunden.
          </div>
        `;
        return;
      }

      // Group by category maintaining canonical category order
      const categoriesOrder = Object.keys(SETTINGS_PLUGIN_CAT_META);
      const groups = {};
      list.forEach(p => {
        const cat = p.category || "Weitere Module";
        if (!groups[cat]) groups[cat] = [];
        groups[cat].push(p);
      });

      const sortedCats = Object.keys(groups).sort((a, b) => {
        const idxA = categoriesOrder.indexOf(a);
        const idxB = categoriesOrder.indexOf(b);
        return (idxA === -1 ? 999 : idxA) - (idxB === -1 ? 999 : idxB);
      });

      let html = "";
      sortedCats.forEach(cat => {
        const plugins = groups[cat];
        const meta = SETTINGS_PLUGIN_CAT_META[cat] || SETTINGS_PLUGIN_CAT_META["Weitere Module"];
        const activeCount = plugins.filter(p => p.enabled).length;

        html += `
          <div class="space-y-3 pt-3 first:pt-0">
            <!-- Category Divider Bar -->
            <div class="flex items-center gap-3 pb-2 border-b border-[var(--border)]">
              <div class="w-7 h-7 rounded-lg bg-[var(--secondary)] border border-[var(--border)] flex items-center justify-center shrink-0">
                <i data-lucide="${meta.icon}" class="w-3.5 h-3.5 ${meta.color}"></i>
              </div>
              <div class="flex items-center gap-2 flex-wrap">
                <h4 class="font-bold text-xs font-mono uppercase tracking-wider text-[var(--foreground)]">${cat}</h4>
                <span class="text-[10.5px] font-mono text-[var(--muted-foreground)] hidden sm:inline">• ${meta.desc}</span>
              </div>
              <div class="ml-auto flex items-center gap-2 shrink-0">
                <span class="px-2 py-0.5 rounded-full text-[10px] font-mono font-bold bg-[var(--secondary)] text-[var(--foreground)] border border-[var(--border)]">
                  ${activeCount} / ${plugins.length} aktiv
                </span>
              </div>
            </div>

            <!-- Cards Grid -->
            <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
              ${plugins.map(p => {
                const isEnabled = !!p.enabled;
                const tools = Array.isArray(p.tools) ? p.tools : [];
                return `
                  <div class="border border-[var(--border)] rounded-xl p-3.5 bg-[var(--card)] flex flex-col justify-between gap-3 shadow-2xs hover:border-zinc-400 dark:hover:border-zinc-700 transition">
                    <div class="space-y-2">
                      <div class="flex items-start justify-between gap-2">
                        <div class="flex items-center gap-2.5 min-w-0">
                          <div class="w-8 h-8 rounded-xl bg-[var(--secondary)] border border-[var(--border)] flex items-center justify-center shrink-0 text-[var(--foreground)]">
                            <i data-lucide="${p.icon || 'puzzle'}" class="w-4 h-4"></i>
                          </div>
                          <div class="min-w-0">
                            <div class="font-bold font-mono text-xs text-[var(--foreground)] flex items-center gap-1.5 truncate">
                              <span class="truncate">${p.name || p.id}</span>
                              <span class="text-[9px] font-mono px-1 py-0.2 rounded bg-[var(--secondary)] text-[var(--muted-foreground)] shrink-0">v${p.version || '1.0.0'}</span>
                            </div>
                            <div class="text-[10px] font-mono text-[var(--muted-foreground)] uppercase">${p.category || 'Plugin'}</div>
                          </div>
                        </div>

                        <!-- Actions: Gear Button + Toggle Switch -->
                        <div class="flex items-center gap-2 shrink-0">
                          <button type="button" onclick="openPluginConfigModal('${p.id}', '${(p.name || p.id).replace(/'/g, "\\'")}')" title="Plugin-Einstellungen anpassen" class="w-7 h-7 rounded-lg border border-[var(--border)] bg-[var(--background)] hover:bg-[var(--secondary)] text-[var(--muted-foreground)] hover:text-[var(--foreground)] flex items-center justify-center transition cursor-pointer shadow-2xs">
                            <i data-lucide="settings" class="w-3.5 h-3.5"></i>
                          </button>
                          
                          <label class="relative inline-flex items-center cursor-pointer shrink-0" title="${isEnabled ? 'Aktiviert - Klicken zum Deaktivieren' : 'Deaktiviert - Klicken zum Aktivieren'}">
                            <input type="checkbox" id="setting-pl-chk-${p.id}" ${isEnabled ? 'checked' : ''} onchange="togglePluginInSettings('${p.id}', this.checked)" class="sr-only peer">
                            <div class="w-9 h-5 bg-zinc-300 peer-focus:outline-none rounded-full peer dark:bg-zinc-700 peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-zinc-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all dark:border-zinc-600 peer-checked:bg-emerald-600"></div>
                          </label>
                        </div>
                      </div>

                      <!-- Elastische Problem / Lösung / Preis & Schattenseite Box -->
                      ${p.problem ? `
                        <div class="space-y-1.5 pt-1 text-[11px] leading-relaxed">
                          <div class="p-2 rounded-lg bg-[var(--background)] border border-[var(--border)]/70">
                            <span class="font-mono font-bold text-rose-500 uppercase text-[10px] block">Problem (Ohne Modul):</span>
                            <span class="text-[var(--foreground)]">${p.problem}</span>
                          </div>
                          <div class="p-2 rounded-lg bg-emerald-500/5 border border-emerald-500/20">
                            <span class="font-mono font-bold text-emerald-600 dark:text-emerald-400 uppercase text-[10px] block">Lösung (Wie es greift):</span>
                            <span class="text-[var(--foreground)]">${p.solution}</span>
                          </div>
                          <div class="p-2 rounded-lg bg-amber-500/10 border border-amber-500/30">
                            <span class="font-mono font-bold text-amber-600 dark:text-amber-400 uppercase text-[10px] block">Preis &amp; Schattenseite (Trade-off):</span>
                            <span class="text-[var(--foreground)]">${p.tradeoff}</span>
                            ${p.when_to_disable ? `<div class="mt-1 pt-1 border-t border-amber-500/20 text-[10.5px] text-[var(--muted-foreground)]"><strong class="font-mono text-[var(--foreground)]">Wann ausschalten?</strong> ${p.when_to_disable}</div>` : ''}
                          </div>
                        </div>
                      ` : `
                        <p class="text-[11px] text-[var(--muted-foreground)] leading-relaxed">${p.desc || p.description || 'Erweiterung für den Archon Kernel.'}</p>
                      `}
                    </div>

                    <!-- Bottom: Tools & Status -->
                    <div class="flex flex-col gap-2 pt-2 border-t border-[var(--border)]/60">
                      <div class="flex flex-wrap items-center gap-1.5 min-h-[22px]">
                        ${tools.length > 0 
                          ? tools.map(t => `<span class="px-2 py-0.5 rounded-md bg-[var(--secondary)] text-[var(--foreground)] text-[9.5px] font-mono border border-[var(--border)] flex items-center gap-1"><i data-lucide="wrench" class="w-2.5 h-2.5 text-[var(--muted-foreground)]"></i> ${t}</span>`).join('')
                          : `<span class="text-[9.5px] text-[var(--muted-foreground)] font-mono italic">Hintergrund-Dienst (Keine MCP-Tools)</span>`
                        }
                      </div>
                      <div class="flex items-center justify-between text-[10px] font-mono pt-1">
                        <span class="text-[var(--muted-foreground)] font-mono">ID: @${p.id}</span>
                        <span id="setting-pl-badge-${p.id}" class="${isEnabled ? 'text-emerald-500 font-bold' : 'text-[var(--muted-foreground)]'}">${isEnabled ? '● Aktiv' : '○ Deaktiviert'}</span>
                      </div>
                    </div>
                  </div>
                `;
              }).join("")}
            </div>
          </div>
        `;
      });

      container.innerHTML = html;
      if (window.lucide) lucide.createIcons();
    }

    async function togglePluginInSettings(pluginId, enable) {
      const pl = settingsPluginsData.find(p => p.id === pluginId);
      if (pl) pl.enabled = enable;
      
      const badge = document.getElementById(`setting-pl-badge-${pluginId}`);
      if (badge) {
        badge.className = enable ? "text-emerald-500 font-bold" : "text-[var(--muted-foreground)]";
        badge.innerText = enable ? "● Aktiv" : "○ Deaktiviert";
      }
      updatePluginSettingsCounters();

      try {
        const res = await fetch("/api/guardian/plugin/toggle", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ plugin_id: pluginId, enabled: enable })
        });
        const data = await res.json();
        if (data.status === "success") {
          showNotification("Plugin-Manager", `Modul '${pluginId}' wurde ${enable ? 'aktiviert' : 'deaktiviert'} (mit Autonomie-Settings synchronisiert).`, "success");
          if (typeof loadAutonomyModulesSettings === "function") loadAutonomyModulesSettings();
          if (typeof loadMemoryConsolidationSettings === "function") loadMemoryConsolidationSettings();
        } else {
          showNotification("Fehler", data.message || "Fehler beim Umschalten", "error");
          if (pl) pl.enabled = !enable;
          const chk = document.getElementById(`setting-pl-chk-${pluginId}`);
          if (chk) chk.checked = !enable;
          if (badge) {
            badge.className = !enable ? "text-emerald-500 font-bold" : "text-[var(--muted-foreground)]";
            badge.innerText = !enable ? "● Aktiv" : "○ Deaktiviert";
          }
          updatePluginSettingsCounters();
        }
      } catch (err) {
        showNotification("Fehler", String(err), "error");
        if (pl) pl.enabled = !enable;
        const chk = document.getElementById(`setting-pl-chk-${pluginId}`);
        if (chk) chk.checked = !enable;
        if (badge) {
          badge.className = !enable ? "text-emerald-500 font-bold" : "text-[var(--muted-foreground)]";
          badge.innerText = !enable ? "● Aktiv" : "○ Deaktiviert";
        }
        updatePluginSettingsCounters();
      }
    }

    function setCommSubTab(subTab) {
      const subTabs = ["smtp", "telegram", "n8n"];
      subTabs.forEach(st => {
        const pane = document.getElementById(`comm-subtab-${st}`);
        const btn = document.getElementById(`btn-comm-sub-${st}`);
        if (!pane || !btn) return;
        if (st === subTab) {
          pane.classList.remove("hidden");
          btn.className = "px-3 py-1.5 rounded-lg border font-mono text-xs font-bold transition flex items-center gap-1.5 cursor-pointer whitespace-nowrap bg-[var(--card)] text-[var(--foreground)] border-[var(--border)]";
        } else {
          pane.classList.add("hidden");
          btn.className = "px-3 py-1.5 rounded-lg border font-mono text-xs font-normal transition flex items-center gap-1.5 cursor-pointer whitespace-nowrap bg-transparent text-[var(--muted-foreground)] border-transparent hover:text-[var(--foreground)]";
        }
      });
      if (subTab === "smtp") {
        loadSmtpSettings();
      }
      lucide.createIcons();
    }

    function setHermesQuickModel(model, provider) {
      const modelInput = document.getElementById("hermes-cfg-model-default");
      const provSelect = document.getElementById("hermes-cfg-model-provider");
      if (modelInput) modelInput.value = model;
      if (provSelect) provSelect.value = provider;
    }

    async function loadHermesFormSettings(requestedPath = null) {
      const selectEl = document.getElementById("hermes-cfg-select");
      const pathDisplay = document.getElementById("hermes-active-cfg-path-display");
      const badge = document.getElementById("hermes-yaml-status-badge");
      const rawEditorEl = document.getElementById("hermes-raw-yaml-editor");
      
      let url = "/api/hermes/settings";
      if (requestedPath) {
        url += "?path=" + encodeURIComponent(requestedPath);
      } else if (selectEl && selectEl.value) {
        url += "?path=" + encodeURIComponent(selectEl.value);
      }
      
      try {
        if (badge) {
          badge.className = "text-[10px] font-mono px-2 py-1 rounded-md bg-zinc-200 dark:bg-zinc-800 text-[var(--muted-foreground)]";
          badge.innerText = "Lade Profil...";
        }
        const res = await fetch(url);
        if (!res.ok) throw new Error("HTTP " + res.status);
        const data = await res.json();
        
        const activePath = data.loaded_path || data.active_path || "";
        if (pathDisplay) {
          pathDisplay.value = activePath;
        }

        // Dropdown Optionen befüllen
        if (selectEl && data.available_configs && data.available_configs.length > 0) {
          selectEl.innerHTML = data.available_configs.map(cfg => {
            let label = cfg;
            if (cfg.includes("config.yaml") && !cfg.includes("profiles")) {
              label = "Standard (Basis-Konfiguration)";
            } else if (cfg.includes("profiles/")) {
              const parts = cfg.split("profiles/");
              const profName = parts[1].replace("/config.yaml", "");
              label = `Profil: ${profName}`;
            } else {
              label = cfg.split("/").pop();
            }
            const isSel = (cfg === activePath) ? "selected" : "";
            return `<option value="${cfg}" ${isSel}>${label}</option>`;
          }).join("");
        }

        // Formular-Felder befüllen (Alle 14 Sektionen / ~55 Felder)
        const s = data.settings || {};
        const el = (id) => document.getElementById(id);
        const setVal = (id, val, defVal) => { if (el(id)) el(id).value = (val !== undefined && val !== null) ? val : defVal; };
        const setChk = (id, val, defVal = true) => { if (el(id)) el(id).checked = (val !== undefined && val !== null) ? !!val : defVal; };

        // Sektion 1: Modell & Provider
        setVal("hermes-cfg-model-default", s.model_default, "z-ai/glm-5.3");
        setVal("hermes-cfg-model-provider", s.model_provider, "openrouter");
        setVal("hermes-cfg-base-url", s.base_url, "");

        // Sektion 2: Agenten-Ausführung, Thinking & Runden-Limits
        setVal("hermes-cfg-reasoning-effort", s.reasoning_effort, "medium");
        setVal("hermes-cfg-max-context-tokens", s.max_context_tokens, 32000);
        setVal("hermes-cfg-max-history", s.max_history_messages, 20);
        setVal("hermes-cfg-task-timeout", s.task_timeout_seconds, 60);
        setVal("hermes-cfg-max-turns", s.max_turns, 60);
        setChk("hermes-cfg-verify-on-stop", s.verify_on_stop, false);
        setChk("hermes-cfg-verbose", s.verbose, false);

        // Sektion 3: Anzeige, Streaming & Dashboard
        setVal("hermes-cfg-language", s.language, "de");
        setVal("hermes-cfg-busy-input-mode", s.busy_input_mode, "interrupt");
        setVal("hermes-cfg-tool-progress", s.tool_progress, "all");
        setVal("hermes-cfg-bg-notifications", s.background_process_notifications, "all");
        setVal("hermes-cfg-timestamp-format", s.timestamp_format, "%H:%M:%S");
        setVal("hermes-cfg-skin", s.skin, "coffee-shop");
        setVal("hermes-cfg-dashboard-theme", s.dashboard_theme, "boring-light");
        setChk("hermes-cfg-reasoning-full", s.reasoning_full, true);
        setChk("hermes-cfg-show-cost", s.show_cost, true);
        setChk("hermes-cfg-timestamps", s.timestamps, true);
        setChk("hermes-cfg-bell-complete", s.bell_on_complete, true);
        setChk("hermes-cfg-streaming", s.streaming_enabled, true);
        setChk("hermes-cfg-compact", s.compact, true);
        setChk("hermes-cfg-interim-msg", s.interim_assistant_messages, true);
        setChk("hermes-cfg-long-running-notif", s.long_running_notifications, true);
        setChk("hermes-cfg-cleanup-progress", s.cleanup_progress, false);

        // Sektion 4: Gateway, Multiplexing & Plattform-Kanäle
        setChk("hermes-cfg-multiplex-profiles", s.multiplex_profiles, true);
        setChk("hermes-cfg-a2a-enabled", s.a2a_enabled, true);
        setChk("hermes-cfg-telegram-enabled", s.telegram_enabled, true);
        setChk("hermes-cfg-webhook-enabled", s.webhook_enabled, true);
        setChk("hermes-cfg-api-server-enabled", s.api_server_enabled, false);
        setChk("hermes-cfg-group-sessions", s.group_sessions_per_user, true);

        // Sektion 5: Allowlist & Code-Execution
        const allowlist = s.command_allowlist || [];
        if (el("hermes-allow-heredoc")) el("hermes-allow-heredoc").checked = allowlist.includes("script execution via heredoc");
        if (el("hermes-allow-execute-code")) el("hermes-allow-execute-code").checked = allowlist.includes("execute_code");
        if (el("hermes-allow-bash")) el("hermes-allow-bash").checked = allowlist.includes("terminal_bash");
        setVal("hermes-cfg-code-max-calls", s.code_max_tool_calls, 50);
        setVal("hermes-cfg-code-timeout", s.code_timeout, 300);

        // Sektion 6: Terminal-Backend & Container-Ressourcen
        setVal("hermes-cfg-term-backend", s.terminal_backend, "local");
        setVal("hermes-cfg-term-homemode", s.terminal_home_mode, "auto");
        setVal("hermes-cfg-term-cwd", s.terminal_cwd, ".");
        setVal("hermes-cfg-term-timeout", s.terminal_timeout, 180);
        setVal("hermes-cfg-term-cpu", s.terminal_container_cpu, 1);
        setVal("hermes-cfg-term-ram", s.terminal_container_memory, 5120);
        setVal("hermes-cfg-term-disk", s.terminal_container_disk, 51200);
        setVal("hermes-cfg-term-lifetime", s.terminal_lifetime_seconds, 300);
        setChk("hermes-cfg-term-persistent", s.terminal_container_persistent, true);
        setChk("hermes-cfg-term-mount-cwd", s.terminal_docker_mount_cwd, false);

        // Sektion 7: Native Tool-Loop-Guardrails
        setChk("hermes-cfg-loop-warn-enabled", s.loop_warnings_enabled, true);
        setChk("hermes-cfg-loop-stop-enabled", s.loop_hard_stop_enabled, false);
        setVal("hermes-cfg-warn-exact", s.warn_exact_failure, 2);
        setVal("hermes-cfg-warn-same", s.warn_same_tool_failure, 3);
        setVal("hermes-cfg-warn-noprog", s.warn_idempotent_no_progress, 2);
        setVal("hermes-cfg-stop-exact", s.stop_exact_failure, 5);
        setVal("hermes-cfg-stop-same", s.stop_same_tool_failure, 8);
        setVal("hermes-cfg-stop-noprog", s.stop_idempotent_no_progress, 5);

        // Sektion 8: Kontext-Kompression & Prompt-Caching
        setChk("hermes-cfg-comp-enabled", s.compression_enabled, true);
        setChk("hermes-cfg-comp-autoraise", s.compression_codex_autoraise, true);
        setVal("hermes-cfg-comp-threshold", s.compression_threshold, 0.5);
        setVal("hermes-cfg-comp-ratio", s.compression_target_ratio, 0.2);
        setVal("hermes-cfg-comp-last-n", s.compression_protect_last_n, 20);
        setVal("hermes-cfg-comp-first-n", s.compression_protect_first_n, 3);
        setVal("hermes-cfg-prompt-cache-ttl", s.prompt_cache_ttl, "5m");

        // Sektion 9: Hermes Gedächtnis, Session-Reset & Skill-Synthese
        setChk("hermes-cfg-mem-enabled", s.memory_enabled, true);
        setChk("hermes-cfg-user-prof-enabled", s.user_profile_enabled, true);
        setVal("hermes-cfg-mem-char-limit", s.memory_char_limit, 2200);
        setVal("hermes-cfg-user-char-limit", s.user_char_limit, 1375);
        setVal("hermes-cfg-mem-flush-turns", s.memory_flush_min_turns, 6);
        setVal("hermes-cfg-mem-nudge", s.memory_nudge_interval, 10);
        setVal("hermes-cfg-sreset-mode", s.session_reset_mode, "both");
        setVal("hermes-cfg-sreset-hour", s.session_reset_at_hour, 4);
        setVal("hermes-cfg-sreset-idle", s.session_reset_idle_minutes, 1440);
        setVal("hermes-cfg-skill-nudge", s.skills_creation_nudge_interval, 15);

        // Sektion 10: Subagenten-Delegation & Mixture-of-Agents (MoA)
        setVal("hermes-cfg-deleg-children", s.delegation_max_concurrent_children, 5);
        setVal("hermes-cfg-deleg-iterations", s.delegation_max_iterations, 50);
        setChk("hermes-cfg-moa-enabled", s.moa_enabled, true);
        setVal("hermes-cfg-moa-fanout", s.moa_fanout, "user_turn");
        setVal("hermes-cfg-moa-tokens", s.moa_max_tokens, 4096);
        setVal("hermes-cfg-moa-degraded", s.moa_degraded_policy, "loud");
        setVal("hermes-cfg-moa-agg-prov", s.moa_aggregator_provider, "custom:omniroute:20128");
        setVal("hermes-cfg-moa-agg-model", s.moa_aggregator_model, "auto/best-free");

        // Sektion 11: Hilfsmodelle (Vision & Web-Extraktion)
        setVal("hermes-cfg-aux-vis-prov", s.aux_vision_provider, "custom:Omniroute:20128");
        setVal("hermes-cfg-aux-vis-model", s.aux_vision_model, "");
        setVal("hermes-cfg-aux-web-prov", s.aux_web_provider, "auto");
        setVal("hermes-cfg-aux-web-model", s.aux_web_model, "");

        // Sektion 12: Browser-Engine & Dynamische Tool-Suche
        setVal("hermes-cfg-brow-timeout", s.browser_inactivity_timeout, 120);
        setVal("hermes-cfg-brow-provider", s.browser_cloud_provider, "local");
        setChk("hermes-cfg-brow-gateway", s.browser_use_gateway, false);
        setVal("hermes-cfg-tsearch-enabled", s.tool_search_enabled, "on");
        setVal("hermes-cfg-tsearch-limit", s.tool_search_limit, 5);
        setVal("hermes-cfg-tsearch-pct", s.tool_search_threshold_pct, 0);
        setVal("hermes-cfg-tsearch-listing", s.tool_search_listing, "off");

        // Sektion 13: Spracherkennung (STT) & Sprachausgabe (Voice / TTS)
        setChk("hermes-cfg-stt-enabled", s.stt_enabled, true);
        setChk("hermes-cfg-voice-tts", s.voice_auto_tts, false);
        setVal("hermes-cfg-stt-provider", s.stt_provider, "groq");
        setVal("hermes-cfg-stt-language", s.stt_language, "de");
        setVal("hermes-cfg-stt-groq-model", s.stt_groq_model, "whisper-large-v3");
        setVal("hermes-cfg-stt-openai-model", s.stt_openai_model, "whisper-1");
        setVal("hermes-cfg-stt-local-model", s.stt_local_model, "base");

        // Sektion 14: Update-Sicherheit & Konfigurations-Backups
        setChk("hermes-cfg-upd-backup", s.updates_pre_backup, false);
        setVal("hermes-cfg-upd-keep", s.updates_backup_keep, 5);
        setVal("hermes-cfg-upd-changes", s.updates_local_changes, "stash");

        // Raw Editor im Accordion
        if (rawEditorEl) {
          rawEditorEl.value = data.raw_yaml || "";
        }

        // Lade zusätzlich Sleep-Cycle Konsolidierung und alle 36 Autonomie-Module + Erklärungsboxen
        if (typeof loadMemoryConsolidationSettings === "function") {
          loadMemoryConsolidationSettings();
        }
        if (typeof loadAutonomyModulesSettings === "function") {
          loadAutonomyModulesSettings();
        }
        if (typeof enrichAutonomyCardsAndThresholds === "function") {
          enrichAutonomyCardsAndThresholds();
        }

        if (badge) {
          badge.className = "text-[10px] font-mono px-2 py-1 rounded-md bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20 font-bold";
          badge.innerText = "Synchronisiert";
        }
      } catch (err) {
        console.error("Fehler beim Laden der Hermes-Konfiguration:", err);
        if (badge) {
          badge.className = "text-[10px] font-mono px-2 py-1 rounded-md bg-rose-500/10 text-rose-600 border border-rose-500/20 font-bold";
          badge.innerText = "Ladefehler";
        }
      }
    }

    async function saveHermesFormSettings(notify = true) {
      const selectEl = document.getElementById("hermes-cfg-select");
      const badge = document.getElementById("hermes-yaml-status-badge");
      const statusMsg = document.getElementById("hermes-form-status-msg");
      const configPath = selectEl ? selectEl.value : "";
      const el = (id) => document.getElementById(id);

      const allowlist = [];
      if (el("hermes-allow-heredoc") && el("hermes-allow-heredoc").checked) allowlist.push("script execution via heredoc");
      if (el("hermes-allow-execute-code") && el("hermes-allow-execute-code").checked) allowlist.push("execute_code");
      if (el("hermes-allow-bash") && el("hermes-allow-bash").checked) allowlist.push("terminal_bash");

      const payload = {
        config_path: configPath,
        settings: {
          // Sektion 1
          model_default: el("hermes-cfg-model-default") ? el("hermes-cfg-model-default").value.trim() : "z-ai/glm-5.3",
          model_provider: el("hermes-cfg-model-provider") ? el("hermes-cfg-model-provider").value : "openrouter",
          base_url: el("hermes-cfg-base-url") ? el("hermes-cfg-base-url").value.trim() : "",
          // Sektion 2
          reasoning_effort: el("hermes-cfg-reasoning-effort") ? el("hermes-cfg-reasoning-effort").value : "medium",
          max_context_tokens: el("hermes-cfg-max-context-tokens") ? parseInt(el("hermes-cfg-max-context-tokens").value, 10) : 32000,
          max_history_messages: el("hermes-cfg-max-history") ? parseInt(el("hermes-cfg-max-history").value, 10) : 20,
          task_timeout_seconds: el("hermes-cfg-task-timeout") ? parseInt(el("hermes-cfg-task-timeout").value, 10) : 60,
          max_turns: el("hermes-cfg-max-turns") ? parseInt(el("hermes-cfg-max-turns").value, 10) : 60,
          verify_on_stop: el("hermes-cfg-verify-on-stop") ? el("hermes-cfg-verify-on-stop").checked : false,
          verbose: el("hermes-cfg-verbose") ? el("hermes-cfg-verbose").checked : false,
          // Sektion 3
          language: el("hermes-cfg-language") ? el("hermes-cfg-language").value : "de",
          busy_input_mode: el("hermes-cfg-busy-input-mode") ? el("hermes-cfg-busy-input-mode").value : "interrupt",
          tool_progress: el("hermes-cfg-tool-progress") ? el("hermes-cfg-tool-progress").value : "all",
          background_process_notifications: el("hermes-cfg-bg-notifications") ? el("hermes-cfg-bg-notifications").value : "all",
          timestamp_format: el("hermes-cfg-timestamp-format") ? el("hermes-cfg-timestamp-format").value.trim() : "%H:%M:%S",
          skin: el("hermes-cfg-skin") ? el("hermes-cfg-skin").value.trim() : "coffee-shop",
          dashboard_theme: el("hermes-cfg-dashboard-theme") ? el("hermes-cfg-dashboard-theme").value.trim() : "boring-light",
          reasoning_full: el("hermes-cfg-reasoning-full") ? el("hermes-cfg-reasoning-full").checked : true,
          show_cost: el("hermes-cfg-show-cost") ? el("hermes-cfg-show-cost").checked : true,
          timestamps: el("hermes-cfg-timestamps") ? el("hermes-cfg-timestamps").checked : true,
          bell_on_complete: el("hermes-cfg-bell-complete") ? el("hermes-cfg-bell-complete").checked : true,
          streaming_enabled: el("hermes-cfg-streaming") ? el("hermes-cfg-streaming").checked : true,
          compact: el("hermes-cfg-compact") ? el("hermes-cfg-compact").checked : true,
          interim_assistant_messages: el("hermes-cfg-interim-msg") ? el("hermes-cfg-interim-msg").checked : true,
          long_running_notifications: el("hermes-cfg-long-running-notif") ? el("hermes-cfg-long-running-notif").checked : true,
          cleanup_progress: el("hermes-cfg-cleanup-progress") ? el("hermes-cfg-cleanup-progress").checked : false,
          // Sektion 4
          multiplex_profiles: el("hermes-cfg-multiplex-profiles") ? el("hermes-cfg-multiplex-profiles").checked : true,
          a2a_enabled: el("hermes-cfg-a2a-enabled") ? el("hermes-cfg-a2a-enabled").checked : true,
          telegram_enabled: el("hermes-cfg-telegram-enabled") ? el("hermes-cfg-telegram-enabled").checked : true,
          webhook_enabled: el("hermes-cfg-webhook-enabled") ? el("hermes-cfg-webhook-enabled").checked : true,
          api_server_enabled: el("hermes-cfg-api-server-enabled") ? el("hermes-cfg-api-server-enabled").checked : false,
          group_sessions_per_user: el("hermes-cfg-group-sessions") ? el("hermes-cfg-group-sessions").checked : true,
          // Sektion 5
          command_allowlist: allowlist,
          code_max_tool_calls: el("hermes-cfg-code-max-calls") ? parseInt(el("hermes-cfg-code-max-calls").value, 10) : 50,
          code_timeout: el("hermes-cfg-code-timeout") ? parseInt(el("hermes-cfg-code-timeout").value, 10) : 300,
          // Sektion 6
          terminal_backend: el("hermes-cfg-term-backend") ? el("hermes-cfg-term-backend").value : "local",
          terminal_home_mode: el("hermes-cfg-term-homemode") ? el("hermes-cfg-term-homemode").value : "auto",
          terminal_cwd: el("hermes-cfg-term-cwd") ? el("hermes-cfg-term-cwd").value.trim() : ".",
          terminal_timeout: el("hermes-cfg-term-timeout") ? parseInt(el("hermes-cfg-term-timeout").value, 10) : 180,
          terminal_container_cpu: el("hermes-cfg-term-cpu") ? parseFloat(el("hermes-cfg-term-cpu").value) : 1.0,
          terminal_container_memory: el("hermes-cfg-term-ram") ? parseInt(el("hermes-cfg-term-ram").value, 10) : 5120,
          terminal_container_disk: el("hermes-cfg-term-disk") ? parseInt(el("hermes-cfg-term-disk").value, 10) : 51200,
          terminal_lifetime_seconds: el("hermes-cfg-term-lifetime") ? parseInt(el("hermes-cfg-term-lifetime").value, 10) : 300,
          terminal_container_persistent: el("hermes-cfg-term-persistent") ? el("hermes-cfg-term-persistent").checked : true,
          terminal_docker_mount_cwd: el("hermes-cfg-term-mount-cwd") ? el("hermes-cfg-term-mount-cwd").checked : false,
          // Sektion 7
          loop_warnings_enabled: el("hermes-cfg-loop-warn-enabled") ? el("hermes-cfg-loop-warn-enabled").checked : true,
          loop_hard_stop_enabled: el("hermes-cfg-loop-stop-enabled") ? el("hermes-cfg-loop-stop-enabled").checked : false,
          warn_exact_failure: el("hermes-cfg-warn-exact") ? parseInt(el("hermes-cfg-warn-exact").value, 10) : 2,
          warn_same_tool_failure: el("hermes-cfg-warn-same") ? parseInt(el("hermes-cfg-warn-same").value, 10) : 3,
          warn_idempotent_no_progress: el("hermes-cfg-warn-noprog") ? parseInt(el("hermes-cfg-warn-noprog").value, 10) : 2,
          stop_exact_failure: el("hermes-cfg-stop-exact") ? parseInt(el("hermes-cfg-stop-exact").value, 10) : 5,
          stop_same_tool_failure: el("hermes-cfg-stop-same") ? parseInt(el("hermes-cfg-stop-same").value, 10) : 8,
          stop_idempotent_no_progress: el("hermes-cfg-stop-noprog") ? parseInt(el("hermes-cfg-stop-noprog").value, 10) : 5,
          // Sektion 8
          compression_enabled: el("hermes-cfg-comp-enabled") ? el("hermes-cfg-comp-enabled").checked : true,
          compression_codex_autoraise: el("hermes-cfg-comp-autoraise") ? el("hermes-cfg-comp-autoraise").checked : true,
          compression_threshold: el("hermes-cfg-comp-threshold") ? parseFloat(el("hermes-cfg-comp-threshold").value) : 0.5,
          compression_target_ratio: el("hermes-cfg-comp-ratio") ? parseFloat(el("hermes-cfg-comp-ratio").value) : 0.2,
          compression_protect_last_n: el("hermes-cfg-comp-last-n") ? parseInt(el("hermes-cfg-comp-last-n").value, 10) : 20,
          compression_protect_first_n: el("hermes-cfg-comp-first-n") ? parseInt(el("hermes-cfg-comp-first-n").value, 10) : 3,
          prompt_cache_ttl: el("hermes-cfg-prompt-cache-ttl") ? el("hermes-cfg-prompt-cache-ttl").value : "5m",
          // Sektion 9
          memory_enabled: el("hermes-cfg-mem-enabled") ? el("hermes-cfg-mem-enabled").checked : true,
          user_profile_enabled: el("hermes-cfg-user-prof-enabled") ? el("hermes-cfg-user-prof-enabled").checked : true,
          memory_char_limit: el("hermes-cfg-mem-char-limit") ? parseInt(el("hermes-cfg-mem-char-limit").value, 10) : 2200,
          user_char_limit: el("hermes-cfg-user-char-limit") ? parseInt(el("hermes-cfg-user-char-limit").value, 10) : 1375,
          memory_flush_min_turns: el("hermes-cfg-mem-flush-turns") ? parseInt(el("hermes-cfg-mem-flush-turns").value, 10) : 6,
          memory_nudge_interval: el("hermes-cfg-mem-nudge") ? parseInt(el("hermes-cfg-mem-nudge").value, 10) : 10,
          session_reset_mode: el("hermes-cfg-sreset-mode") ? el("hermes-cfg-sreset-mode").value : "both",
          session_reset_at_hour: el("hermes-cfg-sreset-hour") ? parseInt(el("hermes-cfg-sreset-hour").value, 10) : 4,
          session_reset_idle_minutes: el("hermes-cfg-sreset-idle") ? parseInt(el("hermes-cfg-sreset-idle").value, 10) : 1440,
          skills_creation_nudge_interval: el("hermes-cfg-skill-nudge") ? parseInt(el("hermes-cfg-skill-nudge").value, 10) : 15,
          // Sektion 10
          delegation_max_concurrent_children: el("hermes-cfg-deleg-children") ? parseInt(el("hermes-cfg-deleg-children").value, 10) : 5,
          delegation_max_iterations: el("hermes-cfg-deleg-iterations") ? parseInt(el("hermes-cfg-deleg-iterations").value, 10) : 50,
          moa_enabled: el("hermes-cfg-moa-enabled") ? el("hermes-cfg-moa-enabled").checked : true,
          moa_fanout: el("hermes-cfg-moa-fanout") ? el("hermes-cfg-moa-fanout").value : "user_turn",
          moa_max_tokens: el("hermes-cfg-moa-tokens") ? parseInt(el("hermes-cfg-moa-tokens").value, 10) : 4096,
          moa_degraded_policy: el("hermes-cfg-moa-degraded") ? el("hermes-cfg-moa-degraded").value : "loud",
          moa_aggregator_provider: el("hermes-cfg-moa-agg-prov") ? el("hermes-cfg-moa-agg-prov").value.trim() : "custom:omniroute:20128",
          moa_aggregator_model: el("hermes-cfg-moa-agg-model") ? el("hermes-cfg-moa-agg-model").value.trim() : "auto/best-free",
          // Sektion 11
          aux_vision_provider: el("hermes-cfg-aux-vis-prov") ? el("hermes-cfg-aux-vis-prov").value.trim() : "custom:Omniroute:20128",
          aux_vision_model: el("hermes-cfg-aux-vis-model") ? el("hermes-cfg-aux-vis-model").value.trim() : "",
          aux_web_provider: el("hermes-cfg-aux-web-prov") ? el("hermes-cfg-aux-web-prov").value.trim() : "auto",
          aux_web_model: el("hermes-cfg-aux-web-model") ? el("hermes-cfg-aux-web-model").value.trim() : "",
          // Sektion 12
          browser_inactivity_timeout: el("hermes-cfg-brow-timeout") ? parseInt(el("hermes-cfg-brow-timeout").value, 10) : 120,
          browser_cloud_provider: el("hermes-cfg-brow-provider") ? el("hermes-cfg-brow-provider").value : "local",
          browser_use_gateway: el("hermes-cfg-brow-gateway") ? el("hermes-cfg-brow-gateway").checked : false,
          tool_search_enabled: el("hermes-cfg-tsearch-enabled") ? el("hermes-cfg-tsearch-enabled").value : "on",
          tool_search_limit: el("hermes-cfg-tsearch-limit") ? parseInt(el("hermes-cfg-tsearch-limit").value, 10) : 5,
          tool_search_threshold_pct: el("hermes-cfg-tsearch-pct") ? parseInt(el("hermes-cfg-tsearch-pct").value, 10) : 0,
          tool_search_listing: el("hermes-cfg-tsearch-listing") ? el("hermes-cfg-tsearch-listing").value : "off",
          // Sektion 13
          stt_enabled: el("hermes-cfg-stt-enabled") ? el("hermes-cfg-stt-enabled").checked : true,
          voice_auto_tts: el("hermes-cfg-voice-tts") ? el("hermes-cfg-voice-tts").checked : false,
          stt_provider: el("hermes-cfg-stt-provider") ? el("hermes-cfg-stt-provider").value : "groq",
          stt_language: el("hermes-cfg-stt-language") ? el("hermes-cfg-stt-language").value.trim() : "de",
          stt_groq_model: el("hermes-cfg-stt-groq-model") ? el("hermes-cfg-stt-groq-model").value.trim() : "whisper-large-v3",
          stt_openai_model: el("hermes-cfg-stt-openai-model") ? el("hermes-cfg-stt-openai-model").value.trim() : "whisper-1",
          stt_local_model: el("hermes-cfg-stt-local-model") ? el("hermes-cfg-stt-local-model").value.trim() : "base",
          // Sektion 14
          updates_pre_backup: el("hermes-cfg-upd-backup") ? el("hermes-cfg-upd-backup").checked : false,
          updates_backup_keep: el("hermes-cfg-upd-keep") ? parseInt(el("hermes-cfg-upd-keep").value, 10) : 5,
          updates_local_changes: el("hermes-cfg-upd-changes") ? el("hermes-cfg-upd-changes").value : "stash"
        }
      };

      try {
        if (badge) {
          badge.className = "text-[10px] font-mono px-2 py-1 rounded-md bg-amber-500/10 text-amber-600 border border-amber-500/20 font-bold";
          badge.innerText = "Speichere...";
        }
        const res = await fetch("/api/hermes/settings", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (typeof loadAutonomyModulesSettings === "function") {
          await loadAutonomyModulesSettings();
        }
        if (data.status === "success") {
          if (notify && typeof showNotification === "function") {
            showNotification("Hermes Core", data.message || "Einstellungen erfolgreich gespeichert (inkl. Auto-Sync mit Archon-Modulen).", "success");
          }
          if (badge) {
            badge.className = "text-[10px] font-mono px-2 py-1 rounded-md bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20 font-bold";
            badge.innerText = "Gespeichert";
          }
          if (statusMsg) {
            statusMsg.innerText = "Zuletzt gespeichert: " + new Date().toLocaleTimeString();
          }
          loadHermesFormSettings(configPath);
          if (typeof window.loadHermesProfilesView === "function") {
            window.loadHermesProfilesView();
          }
          if (typeof loadLLMProvidersSettings === "function") {
            loadLLMProvidersSettings();
          }
          if (typeof loadMasterChatModels === "function") {
            loadMasterChatModels();
          }
        } else {
          showNotification("Fehler", data.detail || data.message || "Speichern fehlgeschlagen.", "error");
          if (badge) {
            badge.className = "text-[10px] font-mono px-2 py-1 rounded-md bg-rose-500/10 text-rose-600 border border-rose-500/20 font-bold";
            badge.innerText = "Fehler";
          }
        }
      } catch (err) {
        showNotification("Fehler", String(err), "error");
        if (badge) {
          badge.className = "text-[10px] font-mono px-2 py-1 rounded-md bg-rose-500/10 text-rose-600 border border-rose-500/20 font-bold";
          badge.innerText = "Fehler";
        }
      }
    }

    // Aliase für Abwärtskompatibilität
    function loadHermesRawConfig(path = null) { return loadHermesFormSettings(path); }
    function saveHermesRawConfig() { return saveHermesFormSettings(); }
    function switchHermesProfileInEditor(profileName) {
      setSettingsTab("kernel");
      const selectEl = document.getElementById("hermes-cfg-select");
      if (selectEl) {
        for (let i = 0; i < selectEl.options.length; i++) {
          if (selectEl.options[i].value.includes(profileName)) {
            selectEl.selectedIndex = i;
            loadHermesFormSettings(selectEl.options[i].value);
            return;
          }
        }
      }
    }    window.openSystemSettingsModal = openSystemSettingsModal;
    window.closeSystemSettingsModal = closeSystemSettingsModal;
    window.setSettingsTab = setSettingsTab;
    // GUARD (10.10.2026, korrigiert): Diese Funktionen leben in ANDEREN
    // Dateien, die NACH system_settings.js laden. Die harte Zuweisung warf
    // einen ReferenceError und brach den REST DER DATEI ab (Zeilen bis 822:
    // Plugin-/Hermes-Settings-Exports, Kanban-Palette).
    // WICHTIG: typeof-Muss DIREKT pro Name stehen - ein Array-Literal
    // [fn] wertet die Variable aus und wirft selbst den ReferenceError.
    if (typeof saveSystemSettings === "function") window.saveSystemSettings = saveSystemSettings;
    if (typeof toggleJevSettings === "function") window.toggleJevSettings = toggleJevSettings;
    if (typeof toggleMemorySettings === "function") window.toggleMemorySettings = toggleMemorySettings;
    if (typeof loadRolesToSettingsDropdown === "function") window.loadRolesToSettingsDropdown = loadRolesToSettingsDropdown;
    if (typeof loadThemeFromServer === "function") window.loadThemeFromServer = loadThemeFromServer;
    if (typeof initLogoUpload === "function") window.initLogoUpload = initLogoUpload;
    if (typeof populateSettingsRoleDropdown === "function") window.populateSettingsRoleDropdown = populateSettingsRoleDropdown;
    if (typeof saveAgentSettings === "function") window.saveAgentSettings = saveAgentSettings;
    if (typeof openHermesProfileSettings === "function") window.openHermesProfileSettings = openHermesProfileSettings;
    window.openSystemSettingsModal = openSystemSettingsModal;
    window.closeSystemSettingsModal = closeSystemSettingsModal;
    window.setSettingsTab = setSettingsTab;
    window.setPluginSubTab = setPluginSubTab;
    window.loadPluginSettingsRegistry = loadPluginSettingsRegistry;
    window.updatePluginSettingsCounters = updatePluginSettingsCounters;
    window.filterPluginSettingsRegistry = filterPluginSettingsRegistry;
    window.renderPluginSettingsRegistry = renderPluginSettingsRegistry;
    window.togglePluginInSettings = togglePluginInSettings;
    window.setCommSubTab = setCommSubTab;
    window.setHermesQuickModel = setHermesQuickModel;
    window.loadHermesFormSettings = loadHermesFormSettings;
    window.saveHermesFormSettings = saveHermesFormSettings;
    window.loadHermesRawConfig = loadHermesRawConfig;
    window.saveHermesRawConfig = saveHermesRawConfig;
    window.switchHermesProfileInEditor = switchHermesProfileInEditor;

    // ==========================================
    // KANBAN-FARBPALETTE (User-Wunsch 10.10.2026 — Design-Tab)
    // ==========================================
    // (var statt const: Hoisting verhindert TDZ-Fehler beim fruehen Tab-Aufruf)
    var KANBAN_PALETTE_COLUMNS = [
      { id: "triage", label: "Triage" },
      { id: "todo", label: "To-Do" },
      { id: "ready", label: "Ready" },
      { id: "in_progress", label: "In Bearbeitung" },
      { id: "review", label: "Review & QA" },
      { id: "blocked", label: "Blockiert / Eskalation" },
      { id: "done", label: "Abgeschlossen" }
    ];
    async function loadKanbanPaletteSettings() {
      const editor = document.getElementById("kanban-palette-editor");
      const source = document.getElementById("kanban-palette-source");
      if (!editor) return;
      try {
        // Robust gegen Scope-/Cache-Effekte: eigene Fallback-Liste
        const paletteColumns = (typeof KANBAN_PALETTE_COLUMNS !== "undefined" && Array.isArray(KANBAN_PALETTE_COLUMNS)) ? KANBAN_PALETTE_COLUMNS : [
          { id: "triage", label: "Triage" },
          { id: "todo", label: "To-Do" },
          { id: "ready", label: "Ready" },
          { id: "in_progress", label: "In Bearbeitung" },
          { id: "review", label: "Review & QA" },
          { id: "blocked", label: "Blockiert / Eskalation" },
          { id: "done", label: "Abgeschlossen" }
        ];
        const res = await fetch("/api/operations/kanban/palette");
        const data = await res.json();
        const cols = data.columns || {};
        if (source) source.textContent = data.custom ? "(eigene Palette aktiv)" : "(Posteo-Standard)";
        editor.innerHTML = paletteColumns.map(c => {
          const header = (cols[c.id] && cols[c.id].header) || "#cccccc";
          const text = (cols[c.id] && cols[c.id].text) || "#000000";
          return `
            <div class="flex items-center gap-2 border border-[var(--border)] rounded-lg p-1.5 bg-[var(--card)]">
              <span id="kanban-pal-prev-${c.id}" class="w-24 h-7 rounded-md border border-[var(--border)] shrink-0 flex items-center justify-center text-[8.5px] font-mono font-bold truncate" style="background-color: ${header}; color: ${text};">${c.label}</span>
              <div class="flex-1 grid grid-cols-2 gap-1.5 min-w-0">
                <label class="flex items-center gap-1 text-[9px] font-mono text-[var(--muted-foreground)]">BG
                  <input type="color" id="kanban-pal-${c.id}-header" value="${header}" oninput="updateKanbanPalettePreview('${c.id}')" class="w-6 h-5 rounded border border-[var(--border)] cursor-pointer p-0 bg-transparent shrink-0">
                </label>
                <label class="flex items-center gap-1 text-[9px] font-mono text-[var(--muted-foreground)]">Text
                  <input type="color" id="kanban-pal-${c.id}-text" value="${text}" oninput="updateKanbanPalettePreview('${c.id}')" class="w-6 h-5 rounded border border-[var(--border)] cursor-pointer p-0 bg-transparent shrink-0">
                </label>
              </div>
            </div>`;
        }).join("");
      } catch (e) {
        editor.innerHTML = `<div class="text-[11px] text-rose-500 font-mono">⚠ Palette konnte nicht geladen werden: ${e.message}</div>`;
      }
    }
    function updateKanbanPalettePreview(colId) {
      const h = document.getElementById(`kanban-pal-${colId}-header`);
      const t = document.getElementById(`kanban-pal-${colId}-text`);
      const prev = document.getElementById(`kanban-pal-prev-${colId}`);
      if (h && t && prev) {
        prev.style.backgroundColor = h.value;
        prev.style.color = t.value;
      }
    }
    async function saveKanbanPaletteFromSettings() {
      const paletteColumns = (typeof KANBAN_PALETTE_COLUMNS !== "undefined" && Array.isArray(KANBAN_PALETTE_COLUMNS)) ? KANBAN_PALETTE_COLUMNS : [
        { id: "triage" }, { id: "todo" }, { id: "ready" }, { id: "in_progress" },
        { id: "review" }, { id: "blocked" }, { id: "done" }
      ];
      const columns = {};
      paletteColumns.forEach(c => {
        const h = document.getElementById(`kanban-pal-${c.id}-header`);
        const t = document.getElementById(`kanban-pal-${c.id}-text`);
        if (h && t) columns[c.id] = { header: h.value, text: t.value };
      });
      try {
        const res = await fetch("/api/operations/kanban/palette", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ columns })
        });
        const data = await res.json();
        if (!res.ok || data.status !== "ok") throw new Error(data.detail || `HTTP ${res.status}`);
        if (typeof showArchonToast === "function") showArchonToast("Kanban-Farbpalette gespeichert — wirksam beim nächsten Kanban-Refresh.", "success");
        const source = document.getElementById("kanban-palette-source");
        if (source) source.textContent = "(eigene Palette aktiv)";
      } catch (e) {
        if (typeof showArchonToast === "function") showArchonToast(`Fehler beim Speichern der Palette: ${e.message}`, "error");
      }
    }
    async function resetKanbanPaletteInSettings() {
      try {
        const res = await fetch("/api/operations/kanban/palette", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ reset: true })
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        await loadKanbanPaletteSettings();
        if (typeof showArchonToast === "function") showArchonToast("Kanban-Farbpalette auf Posteo-Standard zurückgesetzt.", "success");
      } catch (e) {
        if (typeof showArchonToast === "function") showArchonToast(`Reset fehlgeschlagen: ${e.message}`, "error");
      }
    }
    window.loadKanbanPaletteSettings = loadKanbanPaletteSettings;
    window.updateKanbanPalettePreview = updateKanbanPalettePreview;
    window.saveKanbanPaletteFromSettings = saveKanbanPaletteFromSettings;
    window.resetKanbanPaletteInSettings = resetKanbanPaletteInSettings;


    // ==========================================
    // NÄCHTLICHE GEDÄCHTNIS-KONSOLIDIERUNG (Sleep-Cycle)
    // ==========================================
    async function loadMemoryConsolidationSettings() {
      try {
        const res = await fetch('/api/settings/memory-consolidation');
        if (!res.ok) return;
        const d = await res.json();
        const cfg = d.config || {};

        const enabledEl = document.getElementById('cfg-memory-consolidation-enabled');
        const timeEl = document.getElementById('cfg-memory-consolidation-time');
        const retEl = document.getElementById('cfg-memory-consolidation-retention');
        const simEl = document.getElementById('cfg-memory-consolidation-similarity');
        const pruneEl = document.getElementById('cfg-memory-consolidation-prune-logs');
        const badge = document.getElementById('memory-consolidation-last-run-badge');

        if (enabledEl) enabledEl.checked = !!cfg.enabled;
        if (timeEl && cfg.schedule_time) timeEl.value = cfg.schedule_time;
        if (retEl && cfg.retention_days) retEl.value = cfg.retention_days;
        if (simEl && cfg.archive_threshold_similarity) simEl.value = String(cfg.archive_threshold_similarity);
        if (pruneEl) pruneEl.checked = cfg.auto_prune_temporary_logs !== false;

        if (badge && cfg.last_run) {
          badge.textContent = `Letzter Lauf: ${cfg.last_run} (${cfg.last_pruned_records_count || 0} bereinigt)`;
          badge.className = "text-[10px] font-mono px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20 font-bold";
        }
      } catch (e) {
        console.warn("[SystemSettings] Fehler beim Laden der Konsolidierungs-Settings:", e);
      }
    }

    async function saveMemoryConsolidationSettings() {
      try {
        const payload = {
          enabled: !!document.getElementById('cfg-memory-consolidation-enabled')?.checked,
          schedule_time: document.getElementById('cfg-memory-consolidation-time')?.value || "03:00",
          retention_days: parseInt(document.getElementById('cfg-memory-consolidation-retention')?.value || "14", 10),
          archive_threshold_similarity: parseFloat(document.getElementById('cfg-memory-consolidation-similarity')?.value || "0.92"),
          auto_prune_temporary_logs: !!document.getElementById('cfg-memory-consolidation-prune-logs')?.checked
        };
        await fetch('/api/settings/memory-consolidation', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
      } catch (e) {
        console.warn("[SystemSettings] Fehler beim Speichern der Konsolidierungs-Settings:", e);
      }
    }

    async function triggerManualMemoryConsolidation() {
      const btn = document.getElementById('btn-manual-consolidation');
      if (btn) btn.innerHTML = '<i data-lucide="loader-2" class="w-3.5 h-3.5 animate-spin"></i> Konsolidiere...';
      try {
        const res = await fetch('/api/system/consolidate-memory', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ force: true })
        });
        const d = await res.json();
        if (typeof showArchonToast === 'function') {
          showArchonToast(d.summary || "Gedächtnis-Konsolidierung erfolgreich!", "success");
        } else if (typeof showNotification === 'function') {
          showNotification("Konsolidierung", d.summary || "Erfolgreich durchgeführt", "success");
        }
        await loadMemoryConsolidationSettings();
      } catch (err) {
        alert("Konsolidierungs-Fehler: " + err);
      } finally {
        if (btn) btn.innerHTML = '<i data-lucide="sparkles" class="w-3.5 h-3.5"></i> Jetzt manuell konsolidieren';
        if (window.lucide) lucide.createIcons();
      }
    }

    window.loadMemoryConsolidationSettings = loadMemoryConsolidationSettings;
    window.saveMemoryConsolidationSettings = saveMemoryConsolidationSettings;
    window.triggerManualMemoryConsolidation = triggerManualMemoryConsolidation;

    // ==========================================
    // ALLE 10 AUTONOMIE- & RESILIENZ-GRUPPEN (Settings-Paket A & B)
    // ==========================================
    async function loadAutonomyModulesSettings() {
      try {
        const res = await fetch('/api/settings/autonomy-modules');
        if (!res.ok) return;
        const d = await res.json();
        const s = d.settings || {};
        const el = (id) => document.getElementById(id);

        // Gruppe 1: Concurrency & Deadlock-Supervisor
        const conc = s.concurrency || {};
        if (el('aut-deadlock-enabled')) el('aut-deadlock-enabled').checked = conc.auto_deadlock_recovery !== false;
        if (el('aut-conc-max-agents') && conc.max_concurrent_agents) el('aut-conc-max-agents').value = conc.max_concurrent_agents;
        if (el('aut-conc-queue-timeout') && conc.queue_timeout_seconds) el('aut-conc-queue-timeout').value = conc.queue_timeout_seconds;
        if (el('aut-deadlock-stagnation') && conc.stagnation_threshold_seconds) el('aut-deadlock-stagnation').value = conc.stagnation_threshold_seconds;

        // Gruppe 2: Circuit Breaker, Loop-Killer & Token-Clipper
        const cb = s.circuit_breaker || {};
        if (el('aut-cb-loop-enabled')) el('aut-cb-loop-enabled').checked = cb.loop_detection_enabled !== false;
        if (el('aut-cb-clipper-enabled')) el('aut-cb-clipper-enabled').checked = cb.token_clipper_enabled !== false;
        if (el('aut-cb-identical-turns') && cb.max_identical_turns) el('aut-cb-identical-turns').value = cb.max_identical_turns;
        if (el('aut-cb-jaccard') && cb.jaccard_similarity_threshold) el('aut-cb-jaccard').value = cb.jaccard_similarity_threshold;
        if (el('aut-cb-max-steps') && cb.max_steps_per_task) el('aut-cb-max-steps').value = cb.max_steps_per_task;

        // Gruppe 3: Task-Selbstheilung & Git-Rollback
        const heal = s.task_self_healer || {};
        if (el('aut-healer-enabled')) el('aut-healer-enabled').checked = heal.enabled !== false;
        if (el('aut-healer-git-rollback')) el('aut-healer-git-rollback').checked = heal.auto_git_rollback !== false;
        if (el('aut-healer-max-attempts') && heal.max_attempts) el('aut-healer-max-attempts').value = heal.max_attempts;
        if (el('aut-healer-model') && heal.escalation_model) el('aut-healer-model').value = heal.escalation_model;

        // Gruppe 4: Ephemeral Docker Sandbox
        const sb = s.ephemeral_sandbox || {};
        if (el('aut-sandbox-enabled')) el('aut-sandbox-enabled').checked = sb.enabled !== false;
        if (el('aut-sandbox-network')) el('aut-sandbox-network').checked = !!sb.network_enabled;
        if (el('aut-sandbox-ram') && sb.memory_limit_mb) el('aut-sandbox-ram').value = sb.memory_limit_mb;
        if (el('aut-sandbox-cpu') && sb.cpu_limit) el('aut-sandbox-cpu').value = sb.cpu_limit;
        if (el('aut-sandbox-timeout') && sb.timeout_seconds) el('aut-sandbox-timeout').value = sb.timeout_seconds;

        // Gruppe 5: Time-Travel Debugger & Pre-Write Snapshots
        const tt = s.time_travel_snapshots || {};
        if (el('aut-tt-tracing-enabled')) el('aut-tt-tracing-enabled').checked = tt.tracing_enabled !== false;
        if (el('aut-tt-snapshots-enabled')) el('aut-tt-snapshots-enabled').checked = tt.auto_pre_write_snapshots !== false;
        if (el('aut-tt-max-snapshots') && tt.max_snapshots) el('aut-tt-max-snapshots').value = tt.max_snapshots;
        if (el('aut-tt-max-steps') && tt.max_trace_steps) el('aut-tt-max-steps').value = tt.max_trace_steps;

        // Gruppe 6: Konsens-Gate & Tri-Agent Schiedsgericht
        const cons = s.consensus_gate || {};
        if (el('aut-cons-enabled')) el('aut-cons-enabled').checked = cons.enabled !== false;
        if (el('aut-cons-min-prio') && cons.min_priority) el('aut-cons-min-prio').value = String(cons.min_priority);
        if (el('aut-cons-mode') && cons.mode) el('aut-cons-mode').value = cons.mode;
        if (el('aut-cons-majority') && cons.majority_rule) el('aut-cons-majority').value = cons.majority_rule;

        // Gruppe 7: War-Room & Pre-Mortem Simulation
        const wr = s.war_room || {};
        if (el('aut-war-enabled')) el('aut-war-enabled').checked = wr.enabled !== false;
        if (el('aut-war-auto')) el('aut-war-auto').checked = !!wr.auto_pre_mortem;
        if (el('aut-war-threshold') && wr.block_threshold) el('aut-war-threshold').value = wr.block_threshold;
        if (el('aut-war-model') && wr.default_model) el('aut-war-model').value = wr.default_model;

        // Gruppe 8: SLA-Verträge & Handoff-Desk
        const sla = s.sla_contracts || {};
        if (el('aut-sla-enabled')) el('aut-sla-enabled').checked = sla.enabled !== false;
        if (el('aut-sla-autoreject')) el('aut-sla-autoreject').checked = sla.auto_reject_incomplete !== false;
        if (el('aut-sla-min-len') && sla.min_content_length) el('aut-sla-min-len').value = sla.min_content_length;
        if (el('aut-sla-turnaround') && sla.max_turnaround_minutes) el('aut-sla-turnaround').value = sla.max_turnaround_minutes;

        // Gruppe 9: Inbox-Watcher & Morgen-Standup
        const inb = s.inbox_watcher || {};
        if (el('aut-inbox-enabled')) el('aut-inbox-enabled').checked = inb.enabled !== false;
        if (el('aut-standup-enabled')) el('aut-standup-enabled').checked = inb.standup_enabled !== false;
        if (el('aut-inbox-interval') && inb.interval_seconds) el('aut-inbox-interval').value = inb.interval_seconds;
        if (el('aut-standup-time') && inb.standup_time) el('aut-standup-time').value = inb.standup_time;

        // Gruppe 10: Fleet Self-Healing, DB-Backups, Secret-Masking & Browser-Audit
        const fl = s.fleet_and_hygiene || {};
        if (el('aut-fleet-autorestart')) el('aut-fleet-autorestart').checked = fl.auto_container_restart !== false;
        if (el('aut-fleet-secret-mask')) el('aut-fleet-secret-mask').checked = fl.secret_masking_enabled !== false;
        if (el('aut-fleet-browser-audit')) el('aut-fleet-browser-audit').checked = fl.visual_browser_audit !== false;
        if (el('aut-fleet-backup-days') && fl.db_backup_keep_days) el('aut-fleet-backup-days').value = fl.db_backup_keep_days;

        // Paket 1 (Features 1–5): Performance-Core, Durchsatz-Skalierung & Token-Effizienz
        const sc = s.semantic_cache || {};
        if (el('perf-semcache-enabled')) el('perf-semcache-enabled').checked = sc.enabled !== false;
        if (el('perf-semcache-similarity') && sc.similarity_threshold) el('perf-semcache-similarity').value = sc.similarity_threshold;
        if (el('perf-semcache-ttl') && sc.ttl_hours) el('perf-semcache-ttl').value = sc.ttl_hours;
        if (el('perf-semcache-max') && sc.max_entries) el('perf-semcache-max').value = sc.max_entries;

        const mr = s.map_reduce || {};
        if (el('perf-mapreduce-enabled')) el('perf-mapreduce-enabled').checked = mr.enabled !== false;
        if (el('perf-mapreduce-workers') && mr.max_parallel_workers) el('perf-mapreduce-workers').value = mr.max_parallel_workers;
        if (el('perf-mapreduce-timeout') && mr.chunk_timeout_seconds) el('perf-mapreduce-timeout').value = mr.chunk_timeout_seconds;
        if (el('perf-mapreduce-min-items') && mr.auto_fan_out_min_items) el('perf-mapreduce-min-items').value = mr.auto_fan_out_min_items;

        const sh = s.speculative_hedger || {};
        if (el('perf-hedge-enabled')) el('perf-hedge-enabled').checked = sh.enabled !== false;
        if (el('perf-hedge-delay') && sh.hedge_delay_seconds) el('perf-hedge-delay').value = sh.hedge_delay_seconds;
        if (el('perf-hedge-model') && sh.fallback_model) el('perf-hedge-model').value = sh.fallback_model;

        const cc = s.context_compactor || {};
        if (el('perf-compact-enabled')) el('perf-compact-enabled').checked = cc.enabled !== false;
        if (el('perf-compact-threshold') && cc.trigger_token_threshold) el('perf-compact-threshold').value = cc.trigger_token_threshold;
        if (el('perf-compact-keep') && cc.keep_recent_turns) el('perf-compact-keep').value = cc.keep_recent_turns;

        const wb = s.write_batcher || {};
        if (el('perf-batch-enabled')) el('perf-batch-enabled').checked = wb.enabled !== false;
        if (el('perf-batch-size') && wb.batch_size) el('perf-batch-size').value = wb.batch_size;
        if (el('perf-batch-interval') && wb.flush_interval_seconds) el('perf-batch-interval').value = wb.flush_interval_seconds;

        // Paket 2 (Features 6–10): Moderne Gedächtnis- & RAG-Architektur
        const hs = s.hybrid_search || {};
        if (el('mem2-hybrid-enabled')) el('mem2-hybrid-enabled').checked = hs.enabled !== false;
        if (el('mem2-hybrid-rrfk') && hs.rrf_k) el('mem2-hybrid-rrfk').value = hs.rrf_k;
        if (el('mem2-hybrid-bm25w') && hs.bm25_weight !== undefined) el('mem2-hybrid-bm25w').value = hs.bm25_weight;
        if (el('mem2-hybrid-topk') && hs.top_k) el('mem2-hybrid-topk').value = hs.top_k;

        const kg = s.knowledge_graph || {};
        if (el('mem2-kg-enabled')) el('mem2-kg-enabled').checked = kg.enabled !== false;
        if (el('mem2-kg-autoextract')) el('mem2-kg-autoextract').checked = kg.auto_extract_triples !== false;
        if (el('mem2-kg-hops') && kg.max_traversal_hops) el('mem2-kg-hops').value = kg.max_traversal_hops;
        if (el('mem2-kg-conf') && kg.min_confidence !== undefined) el('mem2-kg-conf').value = kg.min_confidence;

        const cr = s.corrective_rag || {};
        if (el('mem2-crag-enabled')) el('mem2-crag-enabled').checked = cr.enabled !== false;
        if (el('mem2-crag-rewrite')) el('mem2-crag-rewrite').checked = cr.auto_query_rewrite !== false;
        if (el('mem2-crag-threshold') && cr.relevance_threshold !== undefined) el('mem2-crag-threshold').value = cr.relevance_threshold;
        if (el('mem2-crag-attempts') && cr.max_rewrite_attempts !== undefined) el('mem2-crag-attempts').value = cr.max_rewrite_attempts;

        const cm = s.core_memory_tier || {};
        if (el('mem2-core-enabled')) el('mem2-core-enabled').checked = cm.enabled !== false;
        if (el('mem2-core-inject')) el('mem2-core-inject').checked = cm.auto_inject_into_system_prompt !== false;
        if (el('mem2-core-maxblocks') && cm.max_pinned_blocks) el('mem2-core-maxblocks').value = cm.max_pinned_blocks;
        if (el('mem2-core-maxchars') && cm.max_chars_per_block) el('mem2-core-maxchars').value = cm.max_chars_per_block;

        const cp = s.citation_pinning || {};
        if (el('mem2-cit-enabled')) el('mem2-cit-enabled').checked = cp.enabled !== false;
        if (el('mem2-cit-inline')) el('mem2-cit-inline').checked = cp.require_inline_citations !== false;
        if (el('mem2-cit-footer')) el('mem2-cit-footer').checked = cp.auto_append_sources_footer !== false;
        if (el('mem2-cit-coverage') && cp.min_citation_coverage_pct !== undefined) el('mem2-cit-coverage').value = cp.min_citation_coverage_pct;

        // Paket 3 (Features 11–15): Zuverlässige Ausführung & Determinismus (Durable Execution)
        const so = s.structured_outputs || {};
        if (el('dur3-json-enabled')) el('dur3-json-enabled').checked = so.enabled !== false;
        if (el('dur3-json-repair')) el('dur3-json-repair').checked = so.auto_repair_json !== false;
        if (el('dur3-json-strict')) el('dur3-json-strict').value = String(so.strict_schema_validation !== false);
        if (el('dur3-json-attempts') && so.max_repair_attempts) el('dur3-json-attempts').value = so.max_repair_attempts;

        const dc = s.durable_checkpointing || {};
        if (el('dur3-cp-enabled')) el('dur3-cp-enabled').checked = dc.enabled !== false;
        if (el('dur3-cp-autoresume')) el('dur3-cp-autoresume').checked = dc.auto_resume_on_boot !== false;
        if (el('dur3-cp-steps') && dc.checkpoint_every_n_steps) el('dur3-cp-steps').value = dc.checkpoint_every_n_steps;
        if (el('dur3-cp-retention') && dc.retention_days) el('dur3-cp-retention').value = dc.retention_days;

        const ig = s.idempotency_guard || {};
        if (el('dur3-idem-enabled')) el('dur3-idem-enabled').checked = ig.enabled !== false;
        if (el('dur3-idem-block')) el('dur3-idem-block').checked = ig.block_duplicate_side_effects !== false;
        if (el('dur3-idem-ttl') && ig.ttl_hours) el('dur3-idem-ttl').value = ig.ttl_hours;

        const dr = s.dry_run_shadow || {};
        if (el('dur3-shadow-enabled')) el('dur3-shadow-enabled').checked = !!dr.enabled;
        if (el('dur3-shadow-writes')) el('dur3-shadow-writes').checked = dr.intercept_write_tools !== false;
        if (el('dur3-shadow-apis')) el('dur3-shadow-apis').checked = dr.intercept_external_apis !== false;

        const dlq = s.dead_letter_queue || {};
        if (el('dur3-dlq-enabled')) el('dur3-dlq-enabled').checked = dlq.enabled !== false;
        if (el('dur3-dlq-autoreplay')) el('dur3-dlq-autoreplay').checked = dlq.auto_replay_enabled !== false;
        if (el('dur3-dlq-retries') && dlq.max_replay_retries) el('dur3-dlq-retries').value = dlq.max_replay_retries;
        if (el('dur3-dlq-backoff') && dlq.backoff_base_seconds) el('dur3-dlq-backoff').value = dlq.backoff_base_seconds;

        // Paket 4 (Features 16–20): Sicherheit, Datenschutz & Enterprise-Governance
        const pii = s.pii_scrubber || {};
        if (el('sec4-pii-enabled')) el('sec4-pii-enabled').checked = pii.enabled !== false;
        if (el('sec4-pii-rehydrate')) el('sec4-pii-rehydrate').checked = pii.auto_rehydrate_response !== false;
        if (el('sec4-pii-emails')) el('sec4-pii-emails').checked = pii.scrub_emails !== false;
        if (el('sec4-pii-phones')) el('sec4-pii-phones').checked = pii.scrub_phones !== false;
        if (el('sec4-pii-ibans')) el('sec4-pii-ibans').checked = pii.scrub_ibans !== false;

        const egf = s.egress_firewall || {};
        if (el('sec4-egress-enabled')) el('sec4-egress-enabled').checked = egf.enabled !== false;
        if (el('sec4-egress-blockip')) el('sec4-egress-blockip').checked = egf.block_raw_ip_egress !== false;
        if (el('sec4-egress-domains') && Array.isArray(egf.allowed_domains)) {
          el('sec4-egress-domains').value = egf.allowed_domains.join(', ');
        }

        const rbj = s.agent_rbac_jail || {};
        if (el('sec4-rbac-enabled')) el('sec4-rbac-enabled').checked = rbj.enabled !== false;
        if (el('sec4-rbac-jail')) el('sec4-rbac-jail').checked = rbj.enforce_path_jail !== false;
        if (el('sec4-rbac-dotenv')) el('sec4-rbac-dotenv').checked = rbj.block_dotenv_access !== false;
        if (el('sec4-rbac-sysdirs')) el('sec4-rbac-sysdirs').checked = rbj.block_system_dirs !== false;

        const opl = s.output_policy_linter || {};
        if (el('sec4-lint-enabled')) el('sec4-lint-enabled').checked = opl.enabled !== false;
        if (el('sec4-lint-slop')) el('sec4-lint-slop').checked = opl.strip_ai_slop_phrases !== false;
        if (el('sec4-lint-destr')) el('sec4-lint-destr').checked = opl.block_destructive_commands !== false;
        if (el('sec4-lint-autoclean')) el('sec4-lint-autoclean').checked = opl.auto_clean_output !== false;

        const rcpt = s.execution_receipts || {};
        if (el('sec4-rcpt-enabled')) el('sec4-rcpt-enabled').checked = rcpt.enabled !== false;
        if (el('sec4-rcpt-chain')) el('sec4-rcpt-chain').checked = rcpt.chain_receipts !== false;
        if (el('sec4-rcpt-cost')) el('sec4-rcpt-cost').checked = rcpt.include_cost_breakdown !== false;

        // Paket 5 (Features 21–25): Selbst-Optimierung, Evaluation & Schwarm-Intelligenz
        const popt = s.prompt_optimizer || {};
        if (el('evo5-popt-enabled')) el('evo5-popt-enabled').checked = popt.enabled !== false;
        if (el('evo5-popt-autoapply')) el('evo5-popt-autoapply').checked = !!popt.auto_apply_patches;
        if (el('evo5-popt-minfail') && popt.min_failures_to_trigger) el('evo5-popt-minfail').value = popt.min_failures_to_trigger;
        if (el('evo5-popt-maxrules') && popt.max_rules_appended) el('evo5-popt-maxrules').value = popt.max_rules_appended;

        const evl = s.eval_regression_suite || {};
        if (el('evo5-eval-enabled')) el('evo5-eval-enabled').checked = evl.enabled !== false;
        if (el('evo5-eval-block')) el('evo5-eval-block').checked = evl.block_deploy_on_regression !== false;
        if (el('evo5-eval-passrate') && evl.min_pass_rate_pct !== undefined) el('evo5-eval-passrate').value = evl.min_pass_rate_pct;

        const bnd = s.bandit_router || {};
        if (el('evo5-bandit-enabled')) el('evo5-bandit-enabled').checked = bnd.enabled !== false;
        if (el('evo5-bandit-eps') && bnd.exploration_epsilon !== undefined) el('evo5-bandit-eps').value = bnd.exploration_epsilon;
        if (el('evo5-bandit-succw') && bnd.success_weight !== undefined) el('evo5-bandit-succw').value = bnd.success_weight;
        if (el('evo5-bandit-latw') && bnd.latency_weight !== undefined) el('evo5-bandit-latw').value = bnd.latency_weight;

        const etm = s.ephemeral_teams || {};
        if (el('evo5-team-enabled')) el('evo5-team-enabled').checked = etm.enabled !== false;
        if (el('evo5-team-dissolve')) el('evo5-team-dissolve').checked = etm.auto_dissolve_on_complete !== false;
        if (el('evo5-team-maxsize') && etm.max_team_size) el('evo5-team-maxsize').value = etm.max_team_size;

        const rbp = s.resource_backpressure || {};
        if (el('evo5-bp-enabled')) el('evo5-bp-enabled').checked = rbp.enabled !== false;
        if (el('evo5-bp-cpu') && rbp.max_cpu_pct) el('evo5-bp-cpu').value = rbp.max_cpu_pct;
        if (el('evo5-bp-ram') && rbp.max_ram_pct) el('evo5-bp-ram').value = rbp.max_ram_pct;
        if (el('evo5-bp-disk') && rbp.min_free_disk_gb !== undefined) el('evo5-bp-disk').value = rbp.min_free_disk_gb;
      } catch (e) {
        console.warn("[SystemSettings] Fehler beim Laden der Autonomie-Modul-Settings:", e);
      }
    }

    async function saveAutonomyModulesSettings(notify = true) {
      const el = (id) => document.getElementById(id);
      const payload = {
        concurrency: {
          auto_deadlock_recovery: !!el('aut-deadlock-enabled')?.checked,
          max_concurrent_agents: parseInt(el('aut-conc-max-agents')?.value || "4", 10),
          queue_timeout_seconds: parseInt(el('aut-conc-queue-timeout')?.value || "60", 10),
          stagnation_threshold_seconds: parseInt(el('aut-deadlock-stagnation')?.value || "45", 10)
        },
        circuit_breaker: {
          loop_detection_enabled: !!el('aut-cb-loop-enabled')?.checked,
          token_clipper_enabled: !!el('aut-cb-clipper-enabled')?.checked,
          max_identical_turns: parseInt(el('aut-cb-identical-turns')?.value || "3", 10),
          jaccard_similarity_threshold: parseFloat(el('aut-cb-jaccard')?.value || "0.90"),
          max_steps_per_task: parseInt(el('aut-cb-max-steps')?.value || "15", 10)
        },
        task_self_healer: {
          enabled: !!el('aut-healer-enabled')?.checked,
          auto_git_rollback: !!el('aut-healer-git-rollback')?.checked,
          max_attempts: parseInt(el('aut-healer-max-attempts')?.value || "3", 10),
          escalation_model: el('aut-healer-model')?.value || "deepseek/deepseek-chat"
        },
        ephemeral_sandbox: {
          enabled: !!el('aut-sandbox-enabled')?.checked,
          network_enabled: !!el('aut-sandbox-network')?.checked,
          memory_limit_mb: parseInt(el('aut-sandbox-ram')?.value || "512", 10),
          cpu_limit: parseFloat(el('aut-sandbox-cpu')?.value || "1.0"),
          timeout_seconds: parseInt(el('aut-sandbox-timeout')?.value || "30", 10)
        },
        time_travel_snapshots: {
          tracing_enabled: !!el('aut-tt-tracing-enabled')?.checked,
          auto_pre_write_snapshots: !!el('aut-tt-snapshots-enabled')?.checked,
          max_snapshots: parseInt(el('aut-tt-max-snapshots')?.value || "50", 10),
          max_trace_steps: parseInt(el('aut-tt-max-steps')?.value || "100", 10)
        },
        consensus_gate: {
          enabled: !!el('aut-cons-enabled')?.checked,
          min_priority: parseInt(el('aut-cons-min-prio')?.value || "3", 10),
          mode: el('aut-cons-mode')?.value || "tri_agent_council",
          majority_rule: el('aut-cons-majority')?.value || "two_thirds"
        },
        war_room: {
          enabled: !!el('aut-war-enabled')?.checked,
          auto_pre_mortem: !!el('aut-war-auto')?.checked,
          block_threshold: el('aut-war-threshold')?.value || "HIGH",
          default_model: el('aut-war-model')?.value || "deepseek/deepseek-chat"
        },
        sla_contracts: {
          enabled: !!el('aut-sla-enabled')?.checked,
          auto_reject_incomplete: !!el('aut-sla-autoreject')?.checked,
          min_content_length: parseInt(el('aut-sla-min-len')?.value || "100", 10),
          max_turnaround_minutes: parseInt(el('aut-sla-turnaround')?.value || "60", 10)
        },
        inbox_watcher: {
          enabled: !!el('aut-inbox-enabled')?.checked,
          standup_enabled: !!el('aut-standup-enabled')?.checked,
          interval_seconds: parseInt(el('aut-inbox-interval')?.value || "5", 10),
          standup_time: el('aut-standup-time')?.value || "08:00"
        },
        fleet_and_hygiene: {
          auto_container_restart: !!el('aut-fleet-autorestart')?.checked,
          secret_masking_enabled: !!el('aut-fleet-secret-mask')?.checked,
          visual_browser_audit: !!el('aut-fleet-browser-audit')?.checked,
          db_backup_keep_days: parseInt(el('aut-fleet-backup-days')?.value || "7", 10)
        },
        semantic_cache: {
          enabled: !!el('perf-semcache-enabled')?.checked,
          similarity_threshold: parseFloat(el('perf-semcache-similarity')?.value || "0.95"),
          ttl_hours: parseInt(el('perf-semcache-ttl')?.value || "24", 10),
          max_entries: parseInt(el('perf-semcache-max')?.value || "500", 10)
        },
        map_reduce: {
          enabled: !!el('perf-mapreduce-enabled')?.checked,
          max_parallel_workers: parseInt(el('perf-mapreduce-workers')?.value || "4", 10),
          chunk_timeout_seconds: parseInt(el('perf-mapreduce-timeout')?.value || "30", 10),
          auto_fan_out_min_items: parseInt(el('perf-mapreduce-min-items')?.value || "3", 10)
        },
        speculative_hedger: {
          enabled: !!el('perf-hedge-enabled')?.checked,
          hedge_delay_seconds: parseFloat(el('perf-hedge-delay')?.value || "2.5"),
          fallback_model: el('perf-hedge-model')?.value || "deepseek/deepseek-chat"
        },
        context_compactor: {
          enabled: !!el('perf-compact-enabled')?.checked,
          trigger_token_threshold: parseInt(el('perf-compact-threshold')?.value || "6000", 10),
          keep_recent_turns: parseInt(el('perf-compact-keep')?.value || "4", 10)
        },
        write_batcher: {
          enabled: !!el('perf-batch-enabled')?.checked,
          batch_size: parseInt(el('perf-batch-size')?.value || "25", 10),
          flush_interval_seconds: parseFloat(el('perf-batch-interval')?.value || "2.0")
        },
        hybrid_search: {
          enabled: !!el('mem2-hybrid-enabled')?.checked,
          rrf_k: parseInt(el('mem2-hybrid-rrfk')?.value || "60", 10),
          bm25_weight: parseFloat(el('mem2-hybrid-bm25w')?.value || "0.5"),
          vector_weight: parseFloat((1.0 - parseFloat(el('mem2-hybrid-bm25w')?.value || "0.5")).toFixed(2)),
          top_k: parseInt(el('mem2-hybrid-topk')?.value || "5", 10)
        },
        knowledge_graph: {
          enabled: !!el('mem2-kg-enabled')?.checked,
          auto_extract_triples: !!el('mem2-kg-autoextract')?.checked,
          max_traversal_hops: parseInt(el('mem2-kg-hops')?.value || "2", 10),
          min_confidence: parseFloat(el('mem2-kg-conf')?.value || "0.70")
        },
        corrective_rag: {
          enabled: !!el('mem2-crag-enabled')?.checked,
          auto_query_rewrite: !!el('mem2-crag-rewrite')?.checked,
          relevance_threshold: parseFloat(el('mem2-crag-threshold')?.value || "0.45"),
          max_rewrite_attempts: parseInt(el('mem2-crag-attempts')?.value || "2", 10)
        },
        core_memory_tier: {
          enabled: !!el('mem2-core-enabled')?.checked,
          auto_inject_into_system_prompt: !!el('mem2-core-inject')?.checked,
          max_pinned_blocks: parseInt(el('mem2-core-maxblocks')?.value || "10", 10),
          max_chars_per_block: parseInt(el('mem2-core-maxchars')?.value || "800", 10)
        },
        citation_pinning: {
          enabled: !!el('mem2-cit-enabled')?.checked,
          require_inline_citations: !!el('mem2-cit-inline')?.checked,
          auto_append_sources_footer: !!el('mem2-cit-footer')?.checked,
          min_citation_coverage_pct: parseInt(el('mem2-cit-coverage')?.value || "60", 10)
        },
        structured_outputs: {
          enabled: !!el('dur3-json-enabled')?.checked,
          auto_repair_json: !!el('dur3-json-repair')?.checked,
          strict_schema_validation: (el('dur3-json-strict')?.value || "true") === "true",
          max_repair_attempts: parseInt(el('dur3-json-attempts')?.value || "2", 10)
        },
        durable_checkpointing: {
          enabled: !!el('dur3-cp-enabled')?.checked,
          auto_resume_on_boot: !!el('dur3-cp-autoresume')?.checked,
          checkpoint_every_n_steps: parseInt(el('dur3-cp-steps')?.value || "1", 10),
          retention_days: parseInt(el('dur3-cp-retention')?.value || "14", 10)
        },
        idempotency_guard: {
          enabled: !!el('dur3-idem-enabled')?.checked,
          block_duplicate_side_effects: !!el('dur3-idem-block')?.checked,
          ttl_hours: parseInt(el('dur3-idem-ttl')?.value || "24", 10)
        },
        dry_run_shadow: {
          enabled: !!el('dur3-shadow-enabled')?.checked,
          intercept_write_tools: !!el('dur3-shadow-writes')?.checked,
          intercept_external_apis: !!el('dur3-shadow-apis')?.checked,
          log_simulated_diffs: true
        },
        dead_letter_queue: {
          enabled: !!el('dur3-dlq-enabled')?.checked,
          auto_replay_enabled: !!el('dur3-dlq-autoreplay')?.checked,
          max_replay_retries: parseInt(el('dur3-dlq-retries')?.value || "3", 10),
          backoff_base_seconds: parseInt(el('dur3-dlq-backoff')?.value || "10", 10)
        },
        pii_scrubber: {
          enabled: !!el('sec4-pii-enabled')?.checked,
          auto_rehydrate_response: !!el('sec4-pii-rehydrate')?.checked,
          scrub_emails: !!el('sec4-pii-emails')?.checked,
          scrub_phones: !!el('sec4-pii-phones')?.checked,
          scrub_ibans: !!el('sec4-pii-ibans')?.checked
        },
        egress_firewall: {
          enabled: !!el('sec4-egress-enabled')?.checked,
          block_raw_ip_egress: !!el('sec4-egress-blockip')?.checked,
          default_policy: "allowlist_only",
          allowed_domains: (el('sec4-egress-domains')?.value || "").split(',').map(d => d.trim()).filter(Boolean)
        },
        agent_rbac_jail: {
          enabled: !!el('sec4-rbac-enabled')?.checked,
          enforce_path_jail: !!el('sec4-rbac-jail')?.checked,
          block_dotenv_access: !!el('sec4-rbac-dotenv')?.checked,
          block_system_dirs: !!el('sec4-rbac-sysdirs')?.checked
        },
        output_policy_linter: {
          enabled: !!el('sec4-lint-enabled')?.checked,
          strip_ai_slop_phrases: !!el('sec4-lint-slop')?.checked,
          block_destructive_commands: !!el('sec4-lint-destr')?.checked,
          auto_clean_output: !!el('sec4-lint-autoclean')?.checked
        },
        execution_receipts: {
          enabled: !!el('sec4-rcpt-enabled')?.checked,
          hash_algorithm: "sha256",
          chain_receipts: !!el('sec4-rcpt-chain')?.checked,
          include_cost_breakdown: !!el('sec4-rcpt-cost')?.checked
        },
        prompt_optimizer: {
          enabled: !!el('evo5-popt-enabled')?.checked,
          auto_apply_patches: !!el('evo5-popt-autoapply')?.checked,
          min_failures_to_trigger: parseInt(el('evo5-popt-minfail')?.value || "3", 10),
          max_rules_appended: parseInt(el('evo5-popt-maxrules')?.value || "5", 10)
        },
        eval_regression_suite: {
          enabled: !!el('evo5-eval-enabled')?.checked,
          block_deploy_on_regression: !!el('evo5-eval-block')?.checked,
          min_pass_rate_pct: parseInt(el('evo5-eval-passrate')?.value || "90", 10)
        },
        bandit_router: {
          enabled: !!el('evo5-bandit-enabled')?.checked,
          exploration_epsilon: parseFloat(el('evo5-bandit-eps')?.value || "0.15"),
          success_weight: parseFloat(el('evo5-bandit-succw')?.value || "0.60"),
          latency_weight: parseFloat(el('evo5-bandit-latw')?.value || "0.40")
        },
        ephemeral_teams: {
          enabled: !!el('evo5-team-enabled')?.checked,
          auto_dissolve_on_complete: !!el('evo5-team-dissolve')?.checked,
          max_team_size: parseInt(el('evo5-team-maxsize')?.value || "4", 10)
        },
        resource_backpressure: {
          enabled: !!el('evo5-bp-enabled')?.checked,
          max_cpu_pct: parseInt(el('evo5-bp-cpu')?.value || "85", 10),
          max_ram_pct: parseInt(el('evo5-bp-ram')?.value || "85", 10),
          min_free_disk_gb: parseFloat(el('evo5-bp-disk')?.value || "2.0"),
          throttle_action: "pause_low_priority"
        }
      };

      try {
        const res = await fetch('/api/settings/autonomy-modules', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const d = await res.json();
        if (typeof loadPluginSettingsRegistry === "function") {
          loadPluginSettingsRegistry();
        }
        if (typeof loadHermesFormSettings === "function") {
          loadHermesFormSettings();
        }
        if (notify && d.status === 'success') {
          if (typeof showArchonToast === 'function') {
            showArchonToast("Alle 36 Autonomie-, Resilienz- & Enterprise-Module gespeichert!", "success");
          } else if (typeof showNotification === 'function') {
            showNotification("System Control Center", "Alle 36 Autonomie- & Enterprise-Module erfolgreich gespeichert.", "success");
          }
        }
      } catch (e) {
        console.warn("[SystemSettings] Fehler beim Speichern der Autonomie-Modul-Settings:", e);
      }
    }

    window.loadAutonomyModulesSettings = loadAutonomyModulesSettings;
    window.saveAutonomyModulesSettings = saveAutonomyModulesSettings;

    // =========================================================================
    // ELASTISCHE 3-TEILIGE MODUL-ERKLÄRUNGEN (PROBLEM / LÖSUNG / PREIS & SCHATTENSEITE)
    // + SCHWELLENWERT-KIPPPUNKTE FÜR ALLE 36 AUTONOMIE-MODULE & PLUGIN-MODALS
    // =========================================================================
    const AUTONOMY_MODULE_TRADEOFFS = {
      "cfg-memory-consolidation-enabled": {
        problem: "Temporäre Traces, Heartbeat-Logs und redundante Einzelfakten blähen SQLite- und Vektorspeicher über Wochen auf und verlangsamen jede Abfrage.",
        solution: "Führt nachts (Standard 03:00 Uhr) einen Sleep-Cycle aus, dedupliziert ähnliche Erinnerungen per Cosine-Schwellenwert und bereinigt abgelaufene Roh-Logs.",
        tradeoff: "Während des Konsolidierungslaufs (~10–30 Sek.) entsteht kurze CPU-/Disk-Last; eine zu niedrige Pruning-Schwelle (< 0.88) kann verwandte, aber eigenständige Fakten zusammenfassen.",
        when_to_disable: "Ausschalten, wenn lückenlose Roh-Traces für ein forensisches Audit dauerhaft ungefiltert erhalten bleiben müssen."
      },
      "aut-deadlock-enabled": {
        problem: "Wenn zu viele Subagenten gleichzeitig starten oder ein Worker auf eine hängende externe API wartet, friert die gesamte Task-Queue per Deadlock ein.",
        solution: "Begrenzt aktive Worker strikt per Semaphor und bricht stagnierende Agenten nach Ablauf der Stagnations-Schwelle samt automatischem Re-Queueing ab.",
        tradeoff: "Knappe Stagnations-Limits (< 30 Sek.) brechen langsame Deep-Reasoning-Modelle (z. B. o3/R1) fälschlich mitten im Denkprozess ab; mehr Worker erhöhen RAM- und API-Spitzenlast.",
        when_to_disable: "Ausschalten bei extrem langlaufenden Einzel-Analysen oder lokalen LLM-Läufen auf langsamer Hardware."
      },
      "aut-cb-loop-enabled": {
        problem: "Agenten verfangen sich bei hartnäckigen Tool-Fehlern in Endlosschleifen, rufen denselben Befehl dutzende Male auf und verbrennen in Minuten das Tagesbudget.",
        solution: "Erkennt identische oder semantisch fast gleiche Züge (Jaccard-Ähnlichkeit) sowie Schritt-Überschreitungen und kappt die Schleife sofort per Circuit-Breaker.",
        tradeoff: "Zu scharfe Grenzwerte (z. B. Max Identisch = 2 oder Jaccard < 0.80) stoppen legitime iterative Aufgaben wie schrittweises Test-Fixing oder Paginierung zu früh.",
        when_to_disable: "Kurzzeitig ausschalten, wenn ein Agent bewusst viele gleichförmige Schleifen-Schritte (z. B. Massen-Migration von 50 Dateien) abarbeiten soll."
      },
      "aut-healer-enabled": {
        problem: "Ein einziger Syntaxfehler oder fehlender Import nach einem Datei-Edit lässt den gesamten Task scheitern und hinterlässt oft kaputten Code im Repository.",
        solution: "Analysiert den Traceback autonom mit einem Reparatur-Modell, spielt bis zu N gezielte Patches ein und führt bei endgültigem Scheitern ein sauberes Git-Rollback aus.",
        tradeoff: "Jeder Selbstheilungsversuch kostet 1 zusätzlichen LLM-Call (+3 bis +12 Sek. Latenz & Token-Kosten). Ein automatisches Git-Rollback verwirft bei Fehlschlag auch nützliche Teilerfolge.",
        when_to_disable: "Git-Rollback ausschalten, wenn unfertige Code-Entwürfe zur manuellen Weiterarbeit im Arbeitsverzeichnis stehen bleiben sollen."
      },
      "aut-sandbox-enabled": {
        problem: "Direkte Ausführung von KI-generiertem Python- oder Bash-Code auf dem Host-System kann Dateien beschädigen, Prozesse blockieren oder Speicherlecks verursachen.",
        solution: "Kapselt jede Code-Ausführung in einen kurzlebigen Docker-Container mit hartem RAM-, CPU- und Timeout-Deckel sowie optionaler Netzwerksperre.",
        tradeoff: "Container-Kaltstart kostet ~300–800 ms Zusatzlatenz pro Tool-Call. Ist das Netzwerk deaktiviert, schlagen `pip install` oder externe API-Abrufe im Skript sofort fehl.",
        when_to_disable: "Ausschalten (oder Netzwerk aktivieren), wenn vertrauenswürdige lokale Skripte direkten Host-Zugriff oder schnelle Paketinstallationen benötigen."
      },
      "aut-tt-tracing-enabled": {
        problem: "Überschreibt ein Agent eine wichtige Datei fehlerhaft oder trifft im 8. Zwischenschritt eine falsche Entscheidung, lässt sich der Zustand ohne Backup nicht mehr rekonstruieren.",
        solution: "Zeichnet jeden Agenten-Zwischenschritt im Time-Travel-Trace auf und legt vor jedem schreibenden Dateizugriff automatisch eine Pre-Write-Schattenkopie an.",
        tradeoff: "Erhöht Disk-I/O um ~5–15 ms pro Datei-Edit und belegt je nach Snapshot-Limit ~50–250 MB zusätzlichen Speicherplatz auf der Festplatte.",
        when_to_disable: "Ausschalten auf Systemen mit extrem knappem Disk-Speicher oder bei massenhaften Datei-Generierungen (z. B. Build-Artefakte)."
      },
      "aut-cons-enabled": {
        problem: "Ein einzelnes LLM unterliegt bei kritischen Architektur-, Lösch- oder Finanzentscheidungen oft einem Bestätigungsfehler (Confirmation Bias).",
        solution: "Schaltet ab der gewählten Aufgaben-Priorität automatisch ein Tri-Agent-Schiedsgericht (Proposer, Kritiker, Richter) vor, das per Mehrheitsregel abstimmt.",
        tradeoff: "Verdreifacht (3x) den Token-Verbrauch und erhöht die Antwortzeit um +6 bis +20 Sek. Bei Einstimmigkeits-Zwang droht Entscheidungs-Stillstand (Deadlock).",
        when_to_disable: "Ausschalten (oder erst ab Priorität 4 = Kritisch aktivieren), wenn Geschwindigkeit und niedrige API-Kosten Vorrang haben."
      },
      "aut-war-enabled": {
        problem: "Riskante Befehle (Datenbank-Migrationen, Produktions-Deploys, Löschoperationen) werden ohne vorherige Folgenabschätzung direkt ausgeführt.",
        solution: "Simuliert vorab im War-Room ein Pre-Mortem ('Was kann im schlimmsten Fall kaputtgehen?') und blockiert die Ausführung ab der eingestellten Risikostufe.",
        tradeoff: "Kostet ~1.500–3.000 zusätzliche Tokens und +4 bis +10 Sek. Wartezeit vor dem eigentlichen Task. Bei Block-Schwelle MEDIUM entstehen häufiger Fehlalarme.",
        when_to_disable: "Auto-Pre-Mortem im normalen Entwicklungsalltag ausschalten und nur für produktionskritische Eingriffe (HIGH/CRITICAL) nutzen."
      },
      "aut-sla-enabled": {
        problem: "Subagenten liefern bei komplexen Delegationen manchmal halbfertige Antworten, leere Platzhalter (`// TODO`) oder überschreiten stillschweigend ihr Zeitfenster.",
        solution: "Prüft jedes Subagenten-Ergebnis gegen einen formellen SLA-Vertrag (Mindestlänge, Pflichtfelder, Turnaround-Zeit) und weist unvollständige Abgaben automatisch zurück.",
        tradeoff: "Wird die Mindestlänge zu hoch angesetzt (> 300 Zeichen), werden präzise Kurzantworten (z. B. ein einzelner Konfigurationswert) abgelehnt und lösen teure Nacharbeits-Schleifen aus.",
        when_to_disable: "Auto-Reject ausschalten, wenn Subagenten auch knappe Status- oder Ja/Nein-Antworten zurückgeben dürfen."
      },
      "aut-inbox-enabled": {
        problem: "Externe Dokumente, PDFs oder Aufgaben-Drops im Eingangsordner bleiben unbeachtet liegen, bis ein Nutzer sie manuell im Chat hochlädt.",
        solution: "Überwacht den Drop-Ordner im Sekundentakt auf neue Dateien, verarbeitet sie automatisch und erstellt morgens zur Wunschzeit ein kompaktes Standup-Briefing.",
        tradeoff: "Sehr kurze Scan-Intervalle (< 3 Sek.) erzeugen kontinuierliche Dateisystem-Polls; das tägliche Morgen-Standup verbraucht ~1.500–3.000 Tokens pro Lauf.",
        when_to_disable: "Ausschalten, wenn der lokale Inbox-Ordner nicht aktiv genutzt wird oder kein morgendlicher Briefing-Bericht gewünscht ist."
      },
      "aut-fleet-autorestart": {
        problem: "Abgestürzte Hilfs-Container, ungeschützte Datenbanken ohne aktuelles Backup oder versehentlich geloggte API-Keys gefährden den unbeaufsichtigten 24/7-Betrieb.",
        solution: "Startet ausgefallene Container automatisch neu, rotiert tägliche SQLite-Backups, maskiert Secrets in Logs und prüft UI-Änderungen optional per Headless-Browser.",
        tradeoff: "Ein defekter Container kann durch Auto-Restart in eine Crash-Loop geraten; der visuelle Browser-Audit startet Chromium (+300 MB RAM, +4 Sek. Dauer).",
        when_to_disable: "Auto-Restart während manueller Container-Wartung ausschalten; Browser-Audit bei reinem Backend-Betrieb deaktivieren."
      },
      "perf-semcache-enabled": {
        problem: "Wiederkehrende oder fast gleich formulierte Fragen lösen jedes Mal einen vollen, teuren LLM-API-Aufruf mit mehreren Sekunden Wartezeit aus.",
        solution: "Vergleicht neue Prompts per Cosine-Ähnlichkeit mit dem lokalen Antwort-Cache und liefert bei einem Treffer die Antwort in unter 15 ms zum Nulltarif.",
        tradeoff: "Ist die Cosine-Schwelle zu niedrig (< 0.92), übersieht der Cache feine Bedeutungsunterschiede (z. B. 'lösche Test-DB' vs. 'lösche Prod-DB') und liefert falsche oder veraltete Antworten.",
        when_to_disable: "Ausschalten bei Aufgaben mit Echtzeit-Daten (Börsenkurse, Live-Logs, Systemstatus) oder wenn jede Antwort frisch generiert werden muss."
      },
      "perf-mapreduce-enabled": {
        problem: "Große Sammelaufgaben (z. B. 15 Dateien prüfen oder 10 Wettbewerber analysieren) dauern sequenziell extrem lange und sprengen oft das Kontextfenster eines einzelnen Agenten.",
        solution: "Teilt Listen-Aufgaben ab N Elementen automatisch auf parallele Map-Worker auf (Fan-Out) und führt die Teilergebnisse am Ende sauber zusammen (Fan-In).",
        tradeoff: "Erzeugt N-fache gleichzeitige API-Last (Gefahr von HTTP-429 Rate-Limits beim Provider) und ~20–35 % Token-Overhead durch die anschließende Reduce-Synthese.",
        when_to_disable: "Ausschalten bei strikten API-Rate-Limits oder wenn die Teilaufgaben eng voneinander abhängen und sequenziell aufeinander aufbauen müssen."
      },
      "perf-hedge-enabled": {
        problem: "Wenn der primäre Cloud-LLM-Provider unter Last steht oder trödelt (Tail-Latency > 10 Sek.), blockiert die gesamte Benutzeroberfläche.",
        solution: "Feuert nach Ablauf der Hedge-Verzögerung (z. B. 2,5 Sek.) automatisch einen parallelen Zweit-Request an das schnelle Fallback-Modell ab und nutzt die erste eintreffende Antwort.",
        tradeoff: "Wenn das Primärmodell kurz nach dem Hedge-Start doch noch antwortet, werden beide Requests abgerechnet (bis zu 2x Token-Kosten bei langsamen Prompts).",
        when_to_disable: "Ausschalten bei knappem API-Budget oder wenn langsame Reasoning-Modelle genutzt werden, die regulär > 10 Sek. Denkzeit benötigen."
      },
      "perf-compact-enabled": {
        problem: "Lange Chat- und Agenten-Sitzungen überschreiten irgendwann das Token-Limit oder werden durch riesige alte Tool-Ausgaben extrem teuer und träge.",
        solution: "Komprimiert ältere Gesprächsrunden ab der eingestellten Token-Schwelle automatisch zu einer kompakten Zusammenfassung, während die letzten N Runden im Original erhalten bleiben.",
        tradeoff: "Der Komprimierungslauf kostet einmalig ~1.000 Tokens; exakte Code-Zeilen oder kleine Detailwerte aus weit zurückliegenden Nachrichten können in der Zusammenfassung verloren gehen.",
        when_to_disable: "Ausschalten, wenn der Agent wortwörtlich auf sehr frühe Nachrichten derselben Sitzung zurückgreifen muss."
      },
      "perf-batch-enabled": {
        problem: "Dutzende gleichzeitige Einzel-Schreibzugriffe (Logs, Metriken, Zwischenstände) führen bei SQLite unter Last zu `database is locked`-Fehlern und hohen I/O-Wartezeiten.",
        solution: "Sammelt nicht-kritische Schreiboperationen im RAM-Puffer und schreibt sie gebündelt alle N Sekunden oder ab N Einträgen in einer einzigen WAL-Transaktion auf die Disk.",
        tradeoff: "Im Falle eines harten Stromausfalls oder `kill -9` vor dem nächsten Flush-Intervall gehen die im RAM gepufferten Einträge der letzten 1–5 Sekunden verloren.",
        when_to_disable: "Ausschalten, wenn jeder einzelne Log-Eintrag sofort und ohne Sekundenverzögerung synchron auf der Festplatte liegen muss."
      },
      "mem2-hybrid-enabled": {
        problem: "Reine Vektorsuche versteht zwar Synonyme, scheitert aber oft kläglich bei exakten Fehlercodes, Funktionsnamen, Seriennummern oder Akronymen.",
        solution: "Kombiniert lexikalische Volltextsuche (BM25) mit semantischer Vektorsuche und verschmilzt beide Trefferlisten über Reciprocal Rank Fusion (RRF).",
        tradeoff: "Doppelte Index-Abfrage erhöht die Such-Latenz um ~15–40 ms; ein zu hohes Top-K (> 10) füllt den Agenten-Prompt mit tausenden Zusatz-Tokens und verwässert den Fokus.",
        when_to_disable: "Fast nie — höchstens Top-K auf 3–5 reduzieren, wenn Token-Kosten pro Anfrage minimiert werden sollen."
      },
      "mem2-kg-enabled": {
        problem: "Klassisches RAG findet nur isolierte Textabschnitte, erkennt aber keine mehrstufigen Zusammenhänge über mehrere Dokumente hinweg (z. B. 'Wer leitet das Projekt, das Modul X nutzt?').",
        solution: "Extrahiert Entitäten und Beziehungen als Subjekt-Prädikat-Objekt-Tripel in einen Knowledge-Graph und traversiert Nachbarknoten über mehrere Hops.",
        tradeoff: "Automatische Tripel-Extraktion kostet beim Speichern ~500 Zusatz-Tokens. Ab > 2 Traversal-Hops explodiert die Anzahl der Nachbarknoten und flutet den Prompt mit Randinformationen.",
        when_to_disable: "Auto-Extraktion ausschalten bei reinem Kurzzeit-Chat ohne langfristigen Wissensaufbau; Hops auf maximal 2 begrenzen."
      },
      "mem2-crag-enabled": {
        problem: "Liefert die Dokumentensuche unpassende Textstellen, halluziniert das LLM trotzdem eine scheinbar plausible Antwort aus dem unbrauchbaren Kontext.",
        solution: "Bewertet die Relevanz der gefundenen Chunks vorab (CRAG-Grader) und formuliert die Suchanfrage bei schlechtem Score automatisch bis zu N-mal um.",
        tradeoff: "Jede Query-Umformulierung kostet 1 zusätzlichen LLM-Call (+1,5 bis +4 Sek. Latenz). Ist die Relevanz-Schwelle zu hoch (> 0.70), dreht CRAG unnötige Extrarunden.",
        when_to_disable: "Ausschalten, wenn die Wissensdatenbank klein und sauber gepflegt ist oder schnelle Antwortzeiten unter 2 Sekunden gefordert sind."
      },
      "mem2-core-enabled": {
        problem: "Wichtige Grundfakten über den Nutzer, aktive Projektziele oder Systemregeln rutschen bei langen Gesprächen aus dem Kontextfenster und werden vergessen.",
        solution: "Hält bis zu N angepinnte Core-Memory-Blöcke (wie RAM-Register im Betriebssystem) dauerhaft direkt im System-Prompt jedes Agenten präsent.",
        tradeoff: "Jeder angepinnte Block belegt bei absolut jedem LLM-Aufruf dauerhaft Prompt-Tokens (z. B. 10 Blöcke × 800 Zeichen ≈ 2.000 Tokens Grundlast pro Nachricht).",
        when_to_disable: "Ausschalten oder Block-Anzahl auf 3–5 reduzieren, wenn kleine Modelle mit engem Kontextfenster oder knappe Token-Budgets genutzt werden."
      },
      "mem2-cit-enabled": {
        problem: "KI-Antworten mischen oft echte Fakten aus Dokumenten mit frei erfundenem Modellwissen, ohne dass erkennbar ist, welcher Satz woher stammt.",
        solution: "Zwingt den Agenten zu Inline-Quellenbelegen (`[Quelle: Datei, S. X]`), hängt eine Quellen-Fußzeile an und prüft die prozentuale Zitat-Abdeckung.",
        tradeoff: "Erhöht den Output-Token-Verbrauch um ~10–15 %; eine zu hohe Mindest-Abdeckung (> 80 %) führt bei kreativen oder zusammenfassenden Fragen zu Fehlwarnungen.",
        when_to_disable: "Ausschalten bei freiem Brainstorming, Code-Generierung oder lockerem Alltags-Chat ohne Dokumentenbezug."
      },
      "dur3-json-enabled": {
        problem: "Wenn LLMs vor oder nach einem JSON-Objekt Höflichkeitsfloskeln ausgeben oder ein Komma vergessen, stürzen nachfolgende Workflows und Parser sofort ab.",
        solution: "Validiert strukturierte Ausgaben strikt gegen das erwartete Schema und repariert kaputtes JSON automatisch in bis zu N Korrekturschleifen.",
        tradeoff: "Jede Auto-Reparatur-Schleife kostet +1 bis +3 Sek. Latenz und zusätzliche Tokens. Strikte Schema-Validierung lehnt Antworten auch wegen harmloser Zusatzfelder ab.",
        when_to_disable: "Strikte Validierung ausschalten, wenn API-Endpunkte oder Skripte auch mit flexiblen oder teilweisen JSON-Feldern umgehen können."
      },
      "dur3-cp-enabled": {
        problem: "Stürzt der Server oder Container bei Schritt 9 einer 10-schrittigen Recherche ab, ist die gesamte bisherige Arbeit samt verbrauchter Tokens verloren.",
        solution: "Speichert nach jedem N-ten Schritt den kompletten Ausführungszustand transaktional in SQLite und nimmt unterbrochene Tasks beim Neustart automatisch wieder auf.",
        tradeoff: "Checkpointing bei jedem einzelnen Schritt (`N = 1`) erzeugt spürbare SQLite-Schreiblast. Auto-Resume beim Booten kann veraltete Tasks vom Vortag ungewollt wieder anfeuern.",
        when_to_disable: "Auto-Resume ausschalten, wenn unterbrochene Aufgaben nach einem Neustart erst manuell geprüft und freigegeben werden sollen."
      },
      "dur3-idem-enabled": {
        problem: "Wird ein Schritt nach einem Netzwerk-Wackler automatisch wiederholt, verschickt der Agent dieselbe E-Mail zweimal, bucht doppelt oder legt Duplikate an.",
        solution: "Berechnet aus Tool-Name und Parametern einen deterministischen Idempotenz-Schlüssel und blockiert doppelte schreibende Ausführungen innerhalb der TTL-Frist.",
        tradeoff: "Wenn der Nutzer exakt denselben Befehl (z. B. 'Sende Test-Mail an mich') innerhalb der Sperrfrist (Standard 24 h) absichtlich ein zweites Mal ausführen will, blockiert der Guard.",
        when_to_disable: "TTL-Stunden auf 1 h senken oder kurzzeitig ausschalten, wenn identische Aktionen im Testbetrieb mehrfach hintereinander ausgeführt werden müssen."
      },
      "dur3-shadow-enabled": {
        problem: "Neue Agenten-Workflows oder umgebaute System-Prompts lassen sich kaum gefahrlos an echten Produktionsdaten und externen APIs testen.",
        solution: "Fängt im aktivierten Shadow-Modus alle schreibenden Datei-Tools und externen API-Calls ab, simuliert den Erfolg und protokolliert nur den geplanten Diff.",
        tradeoff: "SOLANGE AKTIV, WERDEN KEINE ECHTEN DATEIEN GESCHRIEBEN UND KEINE ECHTEN APIS AUSGEFÜHRT! Vergisst man den Schalter, wirkt das System nach außen hin 'tot'.",
        when_to_disable: "Im normalen Produktivbetrieb zwingend AUSGESCHALTET lassen! Nur gezielt für Trockenübungen (Dry-Runs) und Sicherheits-Audits einschalten."
      },
      "dur3-dlq-enabled": {
        problem: "Wenn eine externe Schnittstelle (z. B. CRM, SMTP oder Webhook) kurzzeitig für 2 Minuten nicht erreichbar ist, geht der fehlgeschlagene Auftrag endgültig verloren.",
        solution: "Fängt gescheiterte Aufträge in einer Dead-Letter-Queue (DLQ) auf und wiederholt sie zeitversetzt mit exponentiellem Backoff bis zu N-mal.",
        tradeoff: "Bei dauerhaft fehlerhaften Aufträgen (z. B. ungültiger API-Key) verbrauchen die Wiederholungsversuche unnötig Ressourcen; zeitversetzte Replays können Aktionen verspätet auslösen.",
        when_to_disable: "Auto-Replay ausschalten, wenn fehlgeschlagene Aufträge ausschließlich manuell gesichtet und einzeln freigegeben werden sollen."
      },
      "sec4-pii-enabled": {
        problem: "Klarnamen, E-Mail-Adressen, Telefonnummern und IBANs aus internen Dokumenten wandern bei jedem Prompt ungeschützt an externe Cloud-LLM-Anbieter.",
        solution: "Ersetzt sensible personenbezogene Daten (PII) vor dem API-Versand lokal durch Platzhalter (`[EMAIL_1]`, `[IBAN_1]`) und setzt die echten Werte in der Antwort wieder ein.",
        tradeoff: "Wenn das LLM den Platzhalter im Antworttext leicht abwandelt, schlägt die Rückübersetzung (Rehydrierung) fehl. Zudem kann Regex-Maskierung manchmal Code-Strings oder IDs verfälschen.",
        when_to_disable: "Ausschalten, wenn ausschließlich lokale Modelle (Ollama) genutzt werden oder das LLM zwingend die echten E-Mail-Domains/Namen analysieren muss."
      },
      "sec4-egress-enabled": {
        problem: "Ein durch Prompt-Injection kompromittierter Agent könnte interne Dateien oder API-Keys per HTTP-Request an einen fremden Angreifer-Server exfiltrieren.",
        solution: "Prüft jeden ausgehenden Netzwerkaufruf gegen die Domain-Allowlist und blockiert unbekannte Ziel-Domains sowie direkte Roh-IP-Verbindungen sofort.",
        tradeoff: "Solange `allowlist_only` aktiv ist, wird jede neue Webseite, API oder Dokumentation, die nicht explizit in der Domain-Liste steht, bei Web-Recherchen hart blockiert.",
        when_to_disable: "Ausschalten (oder benötigte Domains ergänzen), wenn der Research-Agent frei im offenen Web recherchieren soll."
      },
      "sec4-rbac-enabled": {
        problem: "Ohne Dateisystem-Schranken kann jedes Agenten-Profil per Pfad-Traversal (`../../`) auf `.env`-Passwortdateien oder geschützte Systemordner (`/etc`, `/root`) zugreifen.",
        solution: "Sperrt Agenten strikt in ihr erlaubtes Workspace-Verzeichnis (Path-Jail) ein und verweigert jeden Lese-/Schreibzugriff auf `.env`-Dateien und Systempfade.",
        tradeoff: "Verhindert, dass ein Administrator-Agent legitim Konfigurationsdateien außerhalb des Projektordners wartet oder `.env`-Vorlagen direkt überprüft.",
        when_to_disable: "Nur für dedizierte Systemwartungs-Aufgaben kurzzeitig lockern; der `.env`-Schutz sollte im Normalbetrieb immer aktiv bleiben."
      },
      "sec4-lint-enabled": {
        problem: "LLMs verfallen oft in aufgeblähte KI-Floskeln ('Gerne helfe ich dir dabei!') oder schlagen in Code-Blöcken unbedacht gefährliche Löschbefehle (`rm -rf /`, `DROP TABLE`) vor.",
        solution: "Scannt jede Antwort vor der Anzeige, entfernt typische KI-Floskeln automatisch und blockiert destruktive Shell- oder SQL-Befehle.",
        tradeoff: "Der Destruktiv-Filter kann auch harmlose Aufräum-Skripte oder gewollte Datenbank-Migrationen blockieren, wenn darin Befehle wie `DROP` oder `rm -rf` als Beispiel vorkommen.",
        when_to_disable: "Destruktiv-Blocker kurzzeitig ausschalten, wenn gezielt Server-Aufräumskripte oder SQL-Reset-Migrationen erstellt werden."
      },
      "sec4-rcpt-enabled": {
        problem: "Bei autonomen Agentenläufen lässt sich im Nachhinein oft nicht mehr revisionssicher beweisen, wer wann welches Modell mit welchen Kosten und welchem Ergebnis ausgeführt hat.",
        solution: "Erzeugt für jeden Lauf eine kryptografisch verkettete SHA-256-Quittung (Hash-Chain) inklusive Zeitstempel, Tool-Spur und exakter Kostenaufstellung.",
        tradeoff: "Verursacht minimalen Rechen- und Speicher-Overhead (~2 ms und ~2 KB SQLite-Speicher pro Task); die Hash-Kette wächst über Monate kontinuierlich an.",
        when_to_disable: "Kann im Produktivbetrieb dauerhaft aktiviert bleiben; nur auf extrem speicherlimitierten Kleinstsystemen ausschalten."
      },
      "evo5-popt-enabled": {
        problem: "Wenn ein Agent bei bestimmten Aufgaben immer wieder denselben Fehler macht, muss der Nutzer den System-Prompt jedes Mal mühsam von Hand nachbessern.",
        solution: "Analysiert wiederkehrende Fehlermuster ab N Fehlschlägen automatisch und generiert präzise Korrekturregeln (Prompt-Patches) für den Agenten.",
        tradeoff: "Ist `Auto-Apply` aktiv, kann eine fehlerhaft abgeleitete Regel das Verhalten des Agenten dauerhaft verzerren (Prompt-Drift) und den System-Prompt aufblähen.",
        when_to_disable: "`Auto-Apply` im Produktivbetrieb ausgeschaltet lassen, damit vorgeschlagene Prompt-Patches erst nach menschlicher Prüfung übernommen werden."
      },
      "evo5-eval-enabled": {
        problem: "Nach einem Modellwechsel oder einer Prompt-Änderung merkt man oft erst im Live-Betrieb, dass wichtige Kernfunktionen plötzlich schlechtere Ergebnisse liefern.",
        solution: "Prüft Änderungen automatisch gegen einen Satz hinterlegter Referenz-Testfälle (Golden Dataset) und blockiert die Aktivierung, wenn die Bestehensquote unter X % fällt.",
        tradeoff: "Jeder komplette Eval-Durchlauf feuert alle hinterlegten Test-Prompts gegen die LLM-API (kostet je nach Testumfang ~5.000–25.000 Tokens und 15–60 Sek. Laufzeit).",
        when_to_disable: "Deploy-Blockade ausschalten, wenn schnelle experimentelle Prompt-Tests ohne Wartezeit durchgeführt werden."
      },
      "evo5-bandit-enabled": {
        problem: "Statische Modell-Zuweisungen nutzen weiter ein teures oder aktuell gestörtes LLM, obwohl ein anderes Modell dieselbe Aufgabenklasse schneller und zuverlässiger löst.",
        solution: "Lernt per Multi-Armed-Bandit-Algorithmus laufend aus Erfolgsquote, Latenz und Kosten und routet Aufträge dynamisch zum besten Modell.",
        tradeoff: "Durch die Explorationsrate (`Epsilon`, z. B. 0.15 = 15 %) testet der Router absichtlich immer wieder alternative Modelle aus, die im Einzelfall langsamer oder schwächer sein können.",
        when_to_disable: "Ausschalten (oder Epsilon auf 0.00 setzen), wenn für jeden Lauf ein 100 % festes, vorhersagbares Modell erzwungen werden soll."
      },
      "evo5-team-enabled": {
        problem: "Für einmalige Spezialprojekte (z. B. Sicherheits-Audit + Frontend-Umbau) existiert oft kein passendes Standard-Team, oder alte Spezial-Agenten bleiben als Karteileichen übrig.",
        solution: "Stellt für komplexe Aufträge ad-hoc eine temporäre Task-Force aus bis zu N Spezialisten zusammen und löst das Team nach Abschluss automatisch wieder auf.",
        tradeoff: "Ein 4-köpfiges Ad-hoc-Team vervielfacht den Token-Verbrauch (3x bis 5x) und benötigt zusätzlichen Koordinations-Overhead zwischen den Teammitgliedern.",
        when_to_disable: "Ausschalten bei einfachen Einzelaufgaben oder knappem Token-Budget; Max. Teamgröße im Alltag auf 3–4 begrenzen."
      },
      "evo5-bp-enabled": {
        problem: "Starten mehrere Hintergrund-Jobs, Browser-Instanzen und Indexierungen gleichzeitig, läuft der Server in 100 % CPU-Last oder einen Out-of-Memory-Absturz (OOM).",
        solution: "Überwacht CPU-, RAM- und Disk-Reserven in Echtzeit und pausiert niedrig priorisierte Hintergrund-Jobs automatisch, sobald ein Schwellenwert überschritten wird.",
        tradeoff: "Sind die Schwellenwerte zu niedrig eingestellt (z. B. CPU < 70 % oder RAM < 70 %), werden Hintergrund-Aufgaben schon bei normalen kurzen Lastspitzen ständig ausgebremst.",
        when_to_disable: "Nicht komplett ausschalten — stattdessen bei starker Hardware die CPU-/RAM-Schwellen auf 90 % anheben."
      }
    };

    const AUTONOMY_THRESHOLD_HINTS = {
      // Section 6: Sleep-Cycle
      "cfg-memory-consolidation-time": "Vor Arbeitsbeginn = 02:00–04:00 | Tagsüber = bremst aktive Chats kurz aus (Std: 03:00)",
      "cfg-memory-consolidation-retention": "Zu niedrig (< 7d) = Verlust wichtiger Audit-Spuren | Zu hoch (> 60d) = große SQLite-DB (Std: 14)",
      "cfg-memory-consolidation-similarity": "0.95 = fast keine Zusammenfassung | 0.88 = verschmilzt auch ähnlich klingende Fakten (Std: 0.92)",
      // Section 7: Paket A (Gruppen 1–5)
      "aut-conc-max-agents": "Zu niedrig (1–2) = Rückstau in der Queue | Zu hoch (> 8) = RAM-Spitzen & API-429-Fehler (Std: 4)",
      "aut-conc-queue-timeout": "Zu niedrig (< 20s) = Tasks brechen vor Start ab | Zu hoch (> 300s) = lange Wartezeit (Std: 60s)",
      "aut-deadlock-stagnation": "Zu niedrig (< 30s) = bricht langsame Denker (o3/R1) ab | Zu hoch (> 180s) = späte Heilung (Std: 45s)",
      "aut-cb-identical-turns": "Zu niedrig (2) = stoppt legitime Retries | Zu hoch (> 5) = teure Endlosschleifen (Std: 3)",
      "aut-cb-jaccard": "Zu niedrig (< 0.80) = Fehlalarme bei ähnlichen Schritten | Zu hoch (> 0.96) = erkennt Schleifen spät (Std: 0.90)",
      "aut-cb-max-steps": "Zu niedrig (< 8) = komplexe Tasks scheitern unfertig | Zu hoch (> 35) = hohe Token-Kosten (Std: 15)",
      "aut-healer-max-attempts": "Zu niedrig (1) = gibt bei Folgefehlern sofort auf | Zu hoch (> 5) = teure Reparatur-Kaskade (Std: 3)",
      "aut-healer-model": "Schnelles Code-Modell empfohlen (z. B. deepseek/deepseek-chat oder claude-sonnet-4-6)",
      "aut-sandbox-ram": "Zu niedrig (< 256 MB) = OOM-Kill bei Pandas/NumPy | Zu hoch (> 2048 MB) = Host-RAM-Risiko (Std: 512)",
      "aut-sandbox-cpu": "Zu niedrig (< 0.5) = langsame Skripte | Zu hoch (> 2.0) = Container kann Host-CPU auslasten (Std: 1.0)",
      "aut-sandbox-timeout": "Zu niedrig (< 10s) = bricht größere Builds ab | Zu hoch (> 120s) = hängende Skripte blockieren (Std: 30s)",
      "aut-tt-max-snapshots": "Zu niedrig (< 10) = kurze Rollback-Historie | Zu hoch (> 200) = höherer Disk-Verbrauch (Std: 50)",
      "aut-tt-max-steps": "Zu niedrig (< 30) = ältere Schritte fehlen im Replay | Zu hoch (> 500) = große Trace-Dateien (Std: 100)",
      // Section 8: Paket B (Gruppen 6–10)
      "aut-cons-min-prio": "Prio 2 = fast jeder Task kostet 3x Tokens | Prio 4 = nur kritische Tasks im Schiedsgericht (Std: Prio 3)",
      "aut-cons-mode": "Tri-Agent = 3x Tokens, beste Qualität | Dual-Verifier = 2x Tokens, schneller (Std: Tri-Agent)",
      "aut-cons-majority": "2/3-Mehrheit = robust & flüssig | Einstimmig = höchste Sicherheit, aber Deadlock-Gefahr (Std: 2/3)",
      "aut-war-threshold": "MEDIUM = blockiert oft vorsorglich | CRITICAL = stoppt nur katastrophale Risiken (Std: HIGH)",
      "aut-war-model": "Reasoning-starkes Modell für zuverlässige Risikoanalyse wählen (Std: deepseek/deepseek-chat)",
      "aut-sla-min-len": "Zu niedrig (< 30) = lässt Platzhalter durch | Zu hoch (> 300) = lehnt knappe Faktenantworten ab (Std: 100)",
      "aut-sla-turnaround": "Zu niedrig (< 10m) = bricht tiefe Recherchen ab | Zu hoch (> 180m) = späte Eskalation (Std: 60m)",
      "aut-inbox-interval": "Zu niedrig (1–2s) = unnötige Disk-Polls | Zu hoch (> 30s) = verzögerte Datei-Erkennung (Std: 5s)",
      "aut-standup-time": "Idealerweise 15–30 Min. vor Arbeitsbeginn einstellen (Std: 08:00)",
      "aut-fleet-backup-days": "Zu niedrig (< 3d) = knappe Wiederherstellung | Zu hoch (> 30d) = ~500 MB+ Backup-Speicher (Std: 7d)",
      // Section 9: Paket 1 (Features 1–5)
      "perf-semcache-similarity": "Zu niedrig (< 0.92) = falsche Antworten aus Cache! | Zu hoch (> 0.98) = kaum Cache-Treffer (Std: 0.95)",
      "perf-semcache-ttl": "Zu niedrig (< 2h) = geringer Spareffekt | Zu hoch (> 72h) = Risiko veralteter Antworten (Std: 24h)",
      "perf-semcache-max": "500 Einträge ≈ 5 MB RAM | > 5.000 Einträge = langsamere Ähnlichkeitssuche (Std: 500)",
      "perf-mapreduce-workers": "Zu niedrig (1–2) = kaum Tempo-Gewinn | Zu hoch (> 8) = Provider Rate-Limit (HTTP 429) (Std: 4)",
      "perf-mapreduce-timeout": "Zu niedrig (< 15s) = Teilaufgaben fehlen im Ergebnis | Zu hoch (> 120s) = langsotster Worker bremst (Std: 30s)",
      "perf-mapreduce-min-items": "Zu niedrig (2) = Fan-Out-Overhead lohnt kaum | Zu hoch (> 8) = selten parallele Beschleunigung (Std: 3)",
      "perf-hedge-delay": "Zu niedrig (< 1.5s) = fast immer doppelte API-Kosten! | Zu hoch (> 8s) = kaum Latenz-Schutz (Std: 2.5s)",
      "perf-hedge-model": "Schnelles, zuverlässiges Modell mit niedriger Time-to-First-Token wählen (Std: deepseek/deepseek-chat)",
      "perf-compact-threshold": "Zu niedrig (< 3000) = vergisst Details zu früh | Zu hoch (> 24000) = hohe Prompt-Kosten (Std: 6000)",
      "perf-compact-keep": "Zu niedrig (1–2) = direkter Gesprächsfaden reißt ab | Zu hoch (> 10) = kaum Token-Ersparnis (Std: 4)",
      "perf-batch-size": "Zu niedrig (< 5) = viele Disk-Writes | Zu hoch (> 100) = mehr Datenverlust bei Crash (Std: 25)",
      "perf-batch-interval": "Zu niedrig (< 0.5s) = kaum Bündelung | Zu hoch (> 10s) = Logs erscheinen verzögert (Std: 2.0s)",
      // Section 10: Paket 2 (Features 6–10)
      "mem2-hybrid-rrfk": "Niedrig (10–30) = Top-1-Treffer dominiert stark | Hoch (60–100) = ausgewogene Mischung (Std: 60)",
      "mem2-hybrid-bm25w": "0.0 = nur Semantik (Vektor) | 0.5 = perfekte Balance | 1.0 = nur exakte Stichworte (Std: 0.50)",
      "mem2-hybrid-topk": "Zu niedrig (1–2) = übersieht Kontext | Zu hoch (> 10) = bläht Prompt um tausende Tokens auf (Std: 5)",
      "mem2-kg-hops": "1 Hop = nur direkte Nachbarn | 2 Hops = optimal | >= 3 Hops = exponentielle Knoten-Explosion! (Std: 2)",
      "mem2-kg-conf": "Zu niedrig (< 0.50) = speichert unsichere Gerüchte | Zu hoch (> 0.90) = verwirft nützliche Fakten (Std: 0.70)",
      "mem2-crag-threshold": "Zu niedrig (< 0.30) = lässt schwache Quellen durch | Zu hoch (> 0.70) = endlose Such-Schleifen (Std: 0.45)",
      "mem2-crag-attempts": "1–2 = schneller Kompromiss | > 3 = bis zu +10 Sek. Wartezeit pro Frage (Std: 2)",
      "mem2-core-maxblocks": "Jeder Block kostet bei JEDEM Call Tokens! > 15 Blöcke = dauerhaft hoher Grundverbrauch (Std: 10)",
      "mem2-core-maxchars": "Zu niedrig (< 300) = schneidet Regeln ab | Zu hoch (> 1500) = verstopft den System-Prompt (Std: 800)",
      "mem2-cit-coverage": "Zu niedrig (< 30%) = unbelegte Aussagen | Zu hoch (> 85%) = Fehlwarnungen bei Zusammenfassungen (Std: 60%)",
      // Section 11: Paket 3 (Features 11–15)
      "dur3-json-strict": "Strikt = maximale Typsicherheit | Tolerant = akzeptiert auch optionale Zusatzfelder (Std: Strikt)",
      "dur3-json-attempts": "1–2 = repariert 98 % aller Tippfehler | > 3 = verschwendet Tokens bei falschem Schema (Std: 2)",
      "dur3-cp-steps": "1 = absolut absturzsicher, mehr Disk-I/O | 3–5 = schont SSD, verliert max. 4 Schritte bei Crash (Std: 1)",
      "dur3-cp-retention": "Zu niedrig (< 3d) = alte Läufe nicht fortsetzbar | Zu hoch (> 30d) = wächst in SQLite an (Std: 14d)",
      "dur3-idem-ttl": "Zu niedrig (< 1h) = schützt nur kurz vor Duplikaten | Zu hoch (> 48h) = blockiert gewollte Wiederholungen (Std: 24h)",
      "dur3-dlq-retries": "Zu niedrig (1) = bricht bei kurzem Netzausfall ab | Zu hoch (> 5) = staut tote Jobs an (Std: 3)",
      "dur3-dlq-backoff": "Basis für exponentielle Wartezeit (10s -> 20s -> 40s). Zu kurz (< 3s) = flutet gestörte APIs (Std: 10s)",
      // Section 12: Paket 4 (Features 16–20)
      "sec4-egress-domains": "Kommagetrennte Whitelist. Fehlt hier eine Domain, wird der Abruf im Allowlist-Modus blockiert!",
      // Section 13: Paket 5 (Features 21–25)
      "evo5-popt-minfail": "Zu niedrig (1) = reagiert über auf Einzelfehler | Zu hoch (> 8) = lernt sehr träge (Std: 3)",
      "evo5-popt-maxrules": "Zu hoch (> 10) = bläht System-Prompt mit widersprüchlichen Sonderregeln auf (Std: 5)",
      "evo5-eval-passrate": "Zu niedrig (< 75%) = lässt Verschlechterungen durch | 100% = blockiert schon bei kleinsten Abweichungen (Std: 90%)",
      "evo5-bandit-eps": "0.00 = nutzt stur das bisher beste Modell | > 0.30 = probiert zu oft schwächere Modelle aus (Std: 0.15)",
      "evo5-bandit-succw": "Gewichtung der Erfolgsquote (0.0–1.0). Sollte zusammen mit Latenz-Gewicht = 1.00 ergeben (Std: 0.60)",
      "evo5-bandit-latw": "Gewichtung der Geschwindigkeit (0.0–1.0). Höher = bevorzugt schnelle Modelle (Std: 0.40)",
      "evo5-team-maxsize": "2–4 = ideale Teamgröße | > 5 = hoher Kommunikations-Overhead & 5x Token-Verbrauch (Std: 4)",
      "evo5-bp-cpu": "Zu niedrig (< 70%) = drosselt bei normaler Arbeit | Zu hoch (> 95%) = System wird träge (Std: 85%)",
      "evo5-bp-ram": "Zu niedrig (< 70%) = pausiert Jobs unnötig früh | Zu hoch (> 92%) = Gefahr von Linux OOM-Kills (Std: 85%)",
      "evo5-bp-disk": "Unter diesem Wert (GB) werden Snapshots & Logs gestoppt, um einen Disk-Full-Crash zu verhindern (Std: 2.0 GB)",
      // HERMES CORE (Sektionen 1–14)
      "hermes-cfg-model-default": "Flaggschiff-Modelle (Claude Opus/Sonnet 4.6) = höchste Code-Qualität | Flash/DeepSeek = ~80% günstiger & schneller",
      "hermes-cfg-model-provider": "openrouter = Zugriff auf 200+ Modelle | custom/ollama = lokal & datenschutzkonform ohne Cloud-Abfluss",
      "hermes-cfg-base-url": "Leer lassen für Provider-Standard | Für lokalen Ollama/vLLM-Server z. B. http://host.docker.internal:11434/v1",
      "hermes-cfg-reasoning-effort": "low = schnell & günstig | high/xhigh = tiefe Denkschritte (+3x bis +5x Thinking-Tokens & +5–20s Latenz) (Std: medium)",
      "hermes-cfg-max-context-tokens": "0 = Modell-Maximum | Zu niedrig (< 16k) = häufiges Abschneiden | Zu hoch (> 128k) = teure Langzeit-Calls (Std: 0)",
      "hermes-cfg-max-history": "0 = unbegrenzt (bis Compaction greift) | Zu niedrig (< 10) = Agent vergisst frühere Nachrichten sofort (Std: 0)",
      "hermes-cfg-task-timeout": "⇄ Sync mit Archon Queue-Timeout! Zu niedrig (< 60s) = bricht tiefe Analysen ab | Zu hoch (> 900s) = Hänger blockieren (Std: 300s)",
      "hermes-cfg-max-turns": "Zu niedrig (< 15) = komplexe mehrstufige Tasks brechen unfertig ab | Zu hoch (> 100) = Risiko hoher Token-Kosten (Std: 60)",
      "hermes-cfg-busy-input-mode": "steer = neue Nachricht lenkt laufenden Agenten sofort um | interrupt = bricht aktuellen Lauf hart ab (Std: steer)",
      "hermes-cfg-tool-progress": "all/new = volle Transparenz im Chat | off = sauberer Chat, aber keine Zwischenschritt-Anzeige (Std: all)",
      "hermes-cfg-bg-notifications": "all = jede Hintergrund-Info | result = nur Endergebnis | off = keine Push-Meldungen (Std: all)",
      "hermes-cfg-code-max-calls": "Zu niedrig (< 10) = komplexe Datenanalysen brechen ab | Zu hoch (> 100) = Endlosschleifen im Skript möglich (Std: 50)",
      "hermes-cfg-code-timeout": "Zu niedrig (< 30s) = bricht größere Python-Läufe ab | Zu hoch (> 600s) = blockiert Worker-Thread (Std: 300s)",
      "hermes-cfg-term-backend": "⇄ Sync mit Archon Sandbox! local = 0ms Overhead, aber voller Container-Zugriff | docker = streng isoliert (+400ms Start)",
      "hermes-cfg-term-homemode": "isolated = jeder Task im eigenen Ordner | shared = gemeinsame Dateien zwischen Tasks (Std: isolated)",
      "hermes-cfg-term-timeout": "⇄ Sync mit Archon Sandbox! Zu niedrig (< 30s) = bricht `npm/pip install` ab | Zu hoch (> 300s) = Hänger (Std: 180s)",
      "hermes-cfg-term-cpu": "⇄ Sync mit Archon Sandbox! Zu niedrig (< 0.5) = träge Kompilierung | Zu hoch (> 4) = Host-CPU-Spitzen (Std: 1)",
      "hermes-cfg-term-ram": "⇄ Sync mit Archon Sandbox! Zu niedrig (< 512 MB) = OOM-Kill bei Node/Pandas | Zu hoch (> 8192 MB) = Host-RAM-Risiko (Std: 5120)",
      "hermes-cfg-term-disk": "Schützt die Host-SSD vor volllaufenden Log- oder Build-Dateien im Sandbox-Container (Std: 51200 MB)",
      "hermes-cfg-term-lifetime": "Nach dieser Ruhezeit (Sek.) wird ein ungenutzter Sandbox-Container abgeräumt (Std: 300s)",
      "hermes-cfg-warn-exact": "Ab N exakt gleichen Tool-Aufrufen erhält das LLM eine System-Warnung im Prompt (Std: 3)",
      "hermes-cfg-warn-same": "Warnt, wenn dasselbe Tool mit demselben Fehler immer wieder aufgerufen wird (Std: 5)",
      "hermes-cfg-warn-noprog": "Warnt ab N Runden ohne messbaren Fortschritt (Std: 8)",
      "hermes-cfg-stop-exact": "⇄ Sync mit Archon Circuit-Breaker! Harter Abbruch bei exakt identischen Tool-Schleifen (Std: 6)",
      "hermes-cfg-stop-same": "Harter Abbruch, wenn derselbe Fehler trotz Warnung weiter wiederholt wird (Std: 10)",
      "hermes-cfg-stop-noprog": "⇄ Sync mit Archon Circuit-Breaker! Maximale Schrittzahl ohne Fortschritt vor Zwangsabbruch (Std: 16)",
      "hermes-cfg-comp-threshold": "Ab welchem Füllstand des Kontextfensters (0.50–0.95) die Komprimierung startet (Std: 0.50 = 50%)",
      "hermes-cfg-comp-ratio": "Wie stark der alte Kontext zusammengedampft wird (0.20 = auf 20% der Ursprungsgröße) (Std: 0.20)",
      "hermes-cfg-comp-last-n": "⇄ Sync mit Archon Compactor! Anzahl der jüngsten Nachrichten, die ungekürzt im Original bleiben (Std: 20)",
      "hermes-cfg-comp-first-n": "Schützt die ersten N Nachrichten (Ursprungs-Auftrag) vor dem Überschreiben (Std: 3)",
      "hermes-cfg-prompt-cache-ttl": "5m = ideal für schnelle Dialoge | 1h = spart bis zu 75% Input-Tokens bei längeren Arbeitspausen (Std: 5m)",
      "hermes-cfg-mem-char-limit": "Zu niedrig (< 800) = vergisst Projektfakten | Zu hoch (> 5000) = kostet bei jedem Aufruf extra Prompt-Tokens (Std: 2200)",
      "hermes-cfg-user-char-limit": "Größe des dauerhaft im System-Prompt mitgeführten Nutzerprofils in Zeichen (Std: 1375)",
      "hermes-cfg-mem-flush-turns": "Ab wie vielen Gesprächsrunden vor einem Reset automatisch Erinnerungen extrahiert werden (Std: 6)",
      "hermes-cfg-mem-nudge": "Alle N Runden wird der Agent leise erinnert, wichtige neue Erkenntnisse abzuspeichern (Std: 10)",
      "hermes-cfg-sreset-mode": "both = Reset nachts ODER nach Leerlauf | idle = nur nach Pause | none = endlose Sitzung (Std: both)",
      "hermes-cfg-sreset-hour": "Uhrzeit (0–23 Uhr) für den täglichen automatischen Sitzungs-Neustart (Std: 4 = 04:00 Uhr)",
      "hermes-cfg-sreset-idle": "Zu niedrig (< 30m) = verliert Gesprächsfaden in der Mittagspause | Zu hoch (> 480m) = teure Riesensitzungen (Std: 1440m)",
      "hermes-cfg-skill-nudge": "Alle N Runden prüft der Agent, ob ein gelöstes Muster als wiederverwendbarer Skill gespeichert werden sollte (Std: 15)",
      "hermes-cfg-deleg-children": "⇄ Sync mit Archon Max-Agents! Zu niedrig (1) = keine Parallelität | Zu hoch (> 8) = hohe API-&-RAM-Spitzen (Std: 3)",
      "hermes-cfg-deleg-iterations": "Maximale Arbeitsschritte pro Subagent. Zu hoch (> 80) = Subagenten können teuer abdriften (Std: 50)",
      "hermes-cfg-moa-fanout": "Anzahl paralleler MoA-Experten-Modelle (2–5). 3 = 3x Token-Kosten pro Anfrage! (Std: 3)",
      "hermes-cfg-moa-tokens": "Maximale Output-Tokens für das zusammenfassende Aggregator-Modell (Std: 4096)",
      "hermes-cfg-brow-timeout": "Maximale Wartezeit (Sek.) beim Laden langsamer Webseiten im Headless-Browser (Std: 30s)",
      "hermes-cfg-tsearch-limit": "Wie viele passende Tools pro dynamischer Tool-Suche maximal nachgeladen werden (Std: 5)",
      "hermes-cfg-tsearch-pct": "Maximale Prozentzahl des Kontextfensters, die Tool-Schemata belegen dürfen (Std: 5%)",
      "hermes-cfg-upd-keep": "Anzahl gespeicherter Versions-Backups für sofortiges Rollback bei Update-Fehlern (Std: 10)"
    };

    const HERMES_SECTION_TRADEOFFS = {
      "hermes-sec-1": {
        problem: "Ein fest verdrahtetes Einzelmodell ist entweder für komplexe Architektur-Aufgaben zu schwach oder für einfache Alltagsfragen viel zu teuer und langsam.",
        solution: "Definiert das primäre Leitmodell, den API-Provider (OpenRouter, Anthropic, OpenAI, Custom/Ollama) und ermöglicht dynamisches Smart-Model-Routing für günstige Teilaufgaben.",
        tradeoff: "Premium-Modelle (z. B. Claude Opus/Sonnet 4.6) kosten 5x–15x mehr pro 1M Tokens als Flash-/DeepSeek-Modelle. Smart-Routing spart bis zu 60 % Kosten, kann aber bei grenzwertigen Fragen versehentlich ein zu kleines Modell wählen.",
        when_to_disable: "Smart-Model-Routing ausschalten, wenn jede einzelne Antwort kompromisslos mit dem Hauptmodell generiert werden soll."
      },
      "hermes-sec-2": {
        problem: "Ohne klare Denk-, Runden- und Zeitlimits bricht ein Agent komplexe Aufgaben entweder zu früh ab oder läuft bei schwierigen Problemen minutenlang ins Leere.",
        solution: "Steuert die Reasoning-Tiefe (Thinking-Tokens), maximale Gesprächsrunden (`max_turns`), Kontextfenster-Größe und den globalen Task-Timeout (synchronisiert mit Archon Concurrency).",
        tradeoff: "Reasoning Effort `high`/`xhigh` verbessert Logik und Code-Qualität massiv, verbraucht aber 3x–5x mehr Output-Tokens und verzögert den Antwortbeginn um 5–20 Sekunden.",
        when_to_disable: "Reasoning auf `low`/`medium` senken, wenn schnelle Dialog-Reaktionszeiten wichtiger sind als tiefe mathematische oder architektonische Herleitungen."
      },
      "hermes-sec-3": {
        problem: "Ungefilterte Tool-Ausgaben überfluten den Chat, fehlende Streaming-Anzeigen lassen das System wie eingefroren wirken, oder neue Eingaben während eines Laufs gehen verloren.",
        solution: "Regelt Echtzeit-Token-Streaming, das Verhalten bei neuen Nachrichten während eines laufenden Tasks (`steer` vs. `interrupt`), Tool-Fortschrittsanzeigen und Systemsprache.",
        tradeoff: "Volle Tool-Progress-Anzeige (`all`) und Reasoning-Anzeige machen jeden Denk- und Zwischenschritt transparent, erzeugen bei langen Recherchen aber sehr lange Chat-Verläufe.",
        when_to_disable: "Reasoning-Anzeige und Tool-Progress auf `new`/`off` stellen, wenn im Chat nur das saubere Endergebnis sichtbar sein soll."
      },
      "hermes-sec-4": {
        problem: "Ohne Gateway-Anbindung ist der Agent nur im lokalen Browser erreichbar; umgekehrt öffnen ungeschützte Messenger-Brücken ohne Allowlist jedem Fremden Zugriff auf das System.",
        solution: "Verbindet den Hermes-Kernel direkt mit Telegram, Discord, Slack und WhatsApp und erzwingt über strikte User-ID-Allowlists, dass nur autorisierte Personen Befehle senden dürfen.",
        tradeoff: "Jede aktive Messenger-Bridge hält eine dauerhafte Hintergrund-Verbindung (Polling/WebSocket) offen. Ist die Allowlist leer, kann im schlimmsten Fall jeder den Bot anschreiben!",
        when_to_disable: "Unbenutzte Messenger-Bridges deaktiviert lassen und bei aktiven Bots zwingend die eigene User-ID in die Allowlist eintragen."
      },
      "hermes-sec-5": {
        problem: "Wenn ein Agent für jeden Shell-Befehl einzeln um Erlaubnis fragt, stockt jeder autonome Workflow; darf er hingegen alles blind ausführen, drohen fatale Systemschäden.",
        solution: "Erlaubt sichere Standardbefehle über eine präzise Command-Allowlist und begrenzt in der Code-Execution-Engine die maximale Anzahl von Tool-Calls und die Laufzeit pro Skript.",
        tradeoff: "Befehle, die nicht auf der Allowlist stehen, erfordern im interaktiven Betrieb eine Freigabe oder werden blockiert; zu hohe Skript-Timeouts (> 300s) können Worker bei Endlosschleifen lange binden.",
        when_to_disable: "Allowlist nur um wirklich benötigte Entwickler-Tools (`git`, `pytest`, `docker`) erweitern; niemals destruktive Befehle (`rm`, `mkfs`) pauschal freigeben."
      },
      "hermes-sec-6": {
        problem: "Führt der Agent Shell-Kommandos direkt im Haupt-Container (`local`) aus, kann ein fehlerhaftes Skript Pakete überschreiben, Prozesse abschießen oder den gesamten Server lahmlegen.",
        solution: "Kapselt Terminal-Befehle wahlweise in eigene Docker-/Singularity-/Modal-Sandboxes mit festem CPU-, RAM-, Disk- und Timeout-Kontingent (bidirektional synchronisiert mit Archon Ephemeral Sandbox).",
        tradeoff: "Das `docker`-Backend bietet echte Prozess-Isolation, kostet aber ~300–800 ms Startzeit und zusätzlichen RAM pro Container. Das `local`-Backend ist sofort da (0 ms), teilt sich aber die Umgebung mit Archon OS.",
        when_to_disable: "Auf `local` belassen für maximale Geschwindigkeit bei vertrauenswürdigen Skripten; auf `docker` schalten, wenn fremder oder riskanter Code getestet wird."
      },
      "hermes-sec-7": {
        problem: "Scheitert ein Tool-Aufruf (z. B. Datei nicht gefunden oder API-Fehler), versuchen LLMs oft stur 20-mal hintereinander exakt denselben Befehl und verbrennen dabei tausende Tokens.",
        solution: "Überwacht Tool-Aufrufe zweistufig: Erst erhält das Modell ab der Warn-Schwelle einen gezielten System-Hinweis zur Kurskorrektur; ab der Stopp-Schwelle greift der harte Abbruch (synchronisiert mit Archon Circuit-Breaker).",
        tradeoff: "Sind die Schwellenwerte zu niedrig eingestellt (z. B. Stopp bei 3), werden legitime mehrstufige Reparatur- oder Polling-Schleifen vorzeitig abgebrochen.",
        when_to_disable: "Nicht komplett ausschalten — bei komplexen Debugging-Aufgaben stattdessen die Stopp-Schwellen moderat auf 8–12 anheben."
      },
      "hermes-sec-8": {
        problem: "Ab ~20–30 Gesprächsrunden wächst der Prompt durch alte Nachrichten und Tool-Outputs auf zehntausende Tokens an — jede weitere Antwort wird dadurch extrem langsam und teuer.",
        solution: "Komprimiert ältere Gesprächsteile automatisch ab dem Schwellenwert (z. B. 50 % Kontextfüllung) auf 20 % ihrer Größe, schützt die ersten und letzten N Runden und nutzt Anthropic/OpenRouter Prompt-Caching.",
        tradeoff: "Die Zusammenfassung spart massiv Folge-Tokens, glättet aber feine Details aus sehr frühen Gesprächsrunden weg. Prompt-Caching (`1h` TTL) spart bis zu 75 % Input-Kosten bei Folgerunden.",
        when_to_disable: "Komprimierung nur ausschalten, wenn der exakte Wortlaut aller frühen Nachrichten einer langen Sitzung ungefiltert im Prompt bleiben muss."
      },
      "hermes-sec-9": {
        problem: "Ohne permanentes Gedächtnis fängt jede neue Sitzung bei Null an; ohne Sitzungs-Reset wiederum sammeln sich über Tage hinweg veraltete Kontext-Reste im aktiven Arbeitsgedächtnis an.",
        solution: "Pflegt ein permanentes Agenten- & Nutzer-Gedächtnis (`MEMORY.md` / `USER.md`), sichert wichtige Erkenntnisse vor dem Reset automatisch (`flush`) und setzt Sitzungen nachts oder nach Leerlauf sauber zurück.",
        tradeoff: "Ein großes permanentes Gedächtnis (z. B. > 4.000 Zeichen) wird bei jedem einzelnen LLM-Aufruf im System-Prompt mitgeschickt. Ein zu kurzer Idle-Reset (< 60 Min.) löscht den aktiven Gesprächsfaden in kurzen Arbeitspausen.",
        when_to_disable: "Session-Reset auf `none` stellen, wenn ein durchgehender Endlos-Chat über mehrere Tage hinweg ohne automatischen Neustart gewünscht ist."
      },
      "hermes-sec-10": {
        problem: "Ein einzelner Agent arbeitet Teilaufgaben nur nacheinander ab und unterliegt bei schwierigen Fragen den blinden Flecken seines jeweiligen Sprachmodells.",
        solution: "Erlaubt parallele Subagenten-Delegation (`max_concurrent_children`, synchronisiert mit Archon Concurrency) sowie Mixture-of-Agents (MoA), bei dem mehrere Experten-Modelle parallel antworten und ein Aggregator die beste Synthese bildet.",
        tradeoff: "Aktiviertes MoA (z. B. Fan-Out = 3) vervielfacht die Token-Kosten pro Anfrage sofort um den Faktor 3x–4x und erhöht die Antwortzeit auf das Tempo des langsamsten Experten-Modells!",
        when_to_disable: "MoA im normalen Tagesbetrieb AUSGESCHALTET lassen und nur für hochkritische Architektur-, Strategie- oder Prüfungsfragen gezielt einschalten."
      },
      "hermes-sec-11": {
        problem: "Wenn das teure Hauptmodell auch jede einfache Bildbeschreibung (Vision) oder das Zusammenfassen riesiger Webseiten übernimmt, explodieren die Token-Kosten unnötig.",
        solution: "Lagert Hilfsaufgaben wie Bild-/Screenshot-Analyse (Vision) und das Extrahieren großer Webseiten/PDFs an spezialisierte, schnelle und günstige Auxiliary-Modelle aus.",
        tradeoff: "Wird hier ein zu schwaches Hilfsmodell eingetragen, können kleine Details auf Screenshots oder in komplexen Tabellen bei der Vorverarbeitung übersehen werden.",
        when_to_disable: "Auf `auto` belassen, damit Hermes automatisch das optimale Preis-Leistungs-Hilfsmodell des aktiven Providers wählt."
      },
      "hermes-sec-12": {
        problem: "Wenn alle 80+ verfügbaren MCP- und System-Tools gleichzeitig im System-Prompt liegen, belegen allein die Tool-Beschreibungen 15.000+ Tokens bei jedem einzelnen Aufruf.",
        solution: "Steuert den Headless-Browser (inkl. automatischer Screenshot-Analyse) und aktiviert Dynamic Tool Search, sodass der Agent bei Bedarf nur die 5 relevantesten Tools dynamisch in den Kontext nachlädt.",
        tradeoff: "Dynamic Tool Search spart bis zu 80 % Tool-Schema-Tokens, erfordert aber manchmal einen kurzen Zwischenschritt, in dem der Agent das passende Tool erst sucht. Browser-Auto-Vision kostet Vision-Tokens pro Seitenaufruf.",
        when_to_disable: "Dynamic Tool Search ausschalten, wenn nur wenige Tools aktiv sind und alle sofort ohne Suchschritt im Prompt sichtbar sein sollen."
      },
      "hermes-sec-13": {
        problem: "Sprachnachrichten (z. B. über Telegram oder Mikrofon) können von Text-LLMs nicht direkt verarbeitet werden, und reine Text-Antworten sind unterwegs unpraktisch.",
        solution: "Transkribiert eingehende Sprachnachrichten automatisch per Speech-to-Text (Groq Whisper Turbo, OpenAI oder lokal) und wandelt Antworten auf Wunsch per Text-to-Speech in natürlich gesprochene Audio-Nachrichten um.",
        tradeoff: "Cloud-STT/TTS (OpenAI/ElevenLabs) verursacht geringe Zusatzkosten pro Audiominute; lokales Whisper (`local`) ist kostenlos, benötigt aber spürbar CPU/RAM im Container.",
        when_to_disable: "Voice/TTS auf `off` lassen, wenn keine Sprachausgabe benötigt wird; STT bei Nutzung von Telegram-Sprachnachrichten auf `groq` (extrem schnell & günstig) stellen."
      },
      "hermes-sec-14": {
        problem: "Manuelle System-Updates werden oft vergessen, während unkontrollierte Auto-Updates ohne Backup bei Fehlern das laufende System lahmlegen können.",
        solution: "Prüft regelmäßig auf neue Hermes-Versionen, legt vor jedem Update automatisch bis zu N Versions-Backups an und informiert über einspielbare Neuerungen.",
        tradeoff: "Ist `auto_update` aktiv, kann ein automatisches Update im Hintergrund kurzzeitig laufende Dienste neu starten. Zu viele gespeicherte Backups (> 15) belegen zusätzlichen Disk-Speicher.",
        when_to_disable: "`auto_update` im produktiven Serverbetrieb ausgeschaltet lassen (`check_enabled` aktiv lassen), um Updates kontrolliert zum Wunschzeitpunkt einzuspielen."
      }
    };

    const PLUGIN_MODAL_THRESHOLD_HINTS = {
      "daily_budget": "Zu niedrig (< 0.50 $) = stoppt Agenten mitten am Tag | Zu hoch = geringerer Kostenschutz (Std: 2.00 $)",
      "task_budget": "Zu niedrig (< 0.10 $) = bricht komplexe Analysen ab | Zu hoch = teure Einzelläufe möglich (Std: 0.50 $)",
      "alert_threshold_percent": "Frühwarnung vor Erreichen des Hard-Stops (Std: 85 %)",
      "cache_ttl_hours": "Zu niedrig (< 2h) = geringer Spareffekt | Zu hoch (> 72h) = Risiko veralteter Antworten (Std: 24h)",
      "max_cache_entries": "Zu niedrig (< 50) = häufiges Überschreiben | Zu hoch (> 2000) = mehr RAM-Bedarf (Std: 100)",
      "cooldown_minutes": "Zu niedrig (< 10m) = hohe Dauerlast & Token-Kosten | Zu hoch (> 120m) = träge Reaktion (Std: 30m)",
      "max_cycles_per_day": "Deckelt die maximale Anzahl autonomer Aufwach-Zyklen pro Tag (Std: 24)",
      "silent_threshold_minutes": "Zu niedrig (< 30m) = Fehlalarme in ruhigen Phasen | Zu hoch (> 240m) = erkennt Hänger spät (Std: 120m)",
      "max_messages_per_day": "Zu hoch (> 15) = nervige Benachrichtigungs-Flut (Notification Fatigue) (Std: 5)",
      "max_exec_seconds": "Zu niedrig (< 15s) = bricht größere Skripte ab | Zu hoch (> 180s) = blockiert Worker (Std: 60s)",
      "max_attachment_mb": "Schützt den Parser vor Speicherüberlauf durch riesige E-Mail-Anhänge (Std: 15 MB)",
      "max_session_hours": "Nach dieser Dauer wird eine durchlaufende Hintergrund-Sitzung zwangsweise rotiert (Std: 24h)",
      "idle_timeout_minutes": "Zu niedrig (< 15m) = verwirft Kontext in kurzen Pausen | Zu hoch (> 180m) = belegt RAM (Std: 60m)",
      "max_tokens_per_session": "Zu niedrig (< 16k) = häufiger Kontextverlust | Zu hoch (> 128k) = teure API-Calls (Std: 64000)",
      "healthcheck_interval_seconds": "Zu niedrig (< 10s) = unnötige CPU-Polls | Zu hoch (> 120s) = späte Ausfall-Erkennung (Std: 30s)",
      "cpu_threshold_percent": "Ab dieser CPU-Auslastung schlägt der System-Monitor Alarm (Std: 85 %)",
      "min_confidence_score": "Zu niedrig (< 0.50) = delegiert an unsichere Worker | Zu hoch (> 0.90) = blockiert fast jede Delegation (Std: 0.75)",
      "penalty_factor": "Wie stark ein Fehler den Vertrauenswert eines Subagenten absenkt (Std: 0.5)",
      "debate_rounds": "1 Runde = schnell | 2 Runden = optimal | >= 3 Runden = 3x–5x Token-Kosten & lange Wartezeit (Std: 2)",
      "reflect_frequency_tasks": "1 = nach jedem Task (+Token-Overhead) | 5 = ausgewogen | > 20 = langsames Lernen (Std: 5)",
      "min_quality_score": "Zu niedrig (< 0.70) = speichert mittelmäßige Regeln | Zu hoch (> 0.95) = übernimmt kaum Learnings (Std: 0.85)",
      "max_active_okrs": "Mehr als 5–7 gleichzeitige OKRs führen zu Fokusverlust bei der Aufgaben-Priorisierung (Std: 5)",
      "worker_concurrency": "Zu niedrig (1) = Jobs warten aufeinander | Zu hoch (> 8) = hohe CPU-/API-Spitzen (Std: 4)",
      "max_retry_attempts": "Anzahl automatischer Wiederholungen bei fehlgeschlagenen Cron-Jobs (Std: 3)",
      "search_depth": "Tiefe 1–2 = schnell & günstig | Tiefe 4–5 = gründlich, aber +15–30 Sek. Dauer & hohe Token-Last (Std: 3)",
      "max_sources": "Zu niedrig (< 3) = einseitige Quellenlage | Zu hoch (> 12) = flutet Kontextfenster (Std: 8)",
      "top_k_results": "Zu niedrig (1–2) = übersieht Details | Zu hoch (> 10) = hohe Prompt-Token-Kosten (Std: 5)",
      "similarity_threshold": "Zu niedrig (< 0.55) = irrelevante Textstellen | Zu hoch (> 0.85) = findet oft keine Treffer (Std: 0.70)",
      "half_life_days": "Nach dieser Tagesanzahl halbiert sich das Gewicht einer ungenutzten Erinnerung (Std: 14d)",
      "eviction_threshold": "Fällt die Relevanz unter diesen Wert, wird der Eintrag beim Aufräumen archiviert (Std: 0.10)",
      "max_injected_lessons": "Zu hoch (> 5) = bläht jeden System-Prompt dauerhaft auf (Std: 3)",
      "max_latency_ms": "Antwortet ein Modell langsamer als dieser Schwellenwert (ms), stuft der Router es herab (Std: 5000 ms)",
      "log_retention_days": "Zu niedrig (< 3d) = erschwert Fehlersuche | Zu hoch (> 30d) = belegt mehr Speicherplatz (Std: 7d)",
      "max_disk_usage_percent": "Ab diesem Festplatten-Füllstand startet die automatische Notfall-Bereinigung (Std: 85 %)",
      "timeout_seconds": "Maximale Wartezeit pro Browser-/Bridge-Aktion vor Abbruch (Std: 30s)",
      "max_steps_per_run": "Verhindert, dass sich der Browser-Agent auf komplexen Webseiten endlos verklickt (Std: 20)"
    };

    function buildTradeoffBoxHtml(info) {
      if (!info || !info.problem) return "";
      return `
        <div class="aut-tradeoff-box space-y-1.5 pt-1 pb-1 text-[10.5px] leading-relaxed">
          <div class="p-2 rounded-lg bg-[var(--background)] border border-[var(--border)]/70">
            <span class="font-mono font-bold text-rose-500 uppercase text-[9.5px] block">Problem (Ohne Modul):</span>
            <span class="text-[var(--foreground)]">${info.problem}</span>
          </div>
          <div class="p-2 rounded-lg bg-emerald-500/5 border border-emerald-500/20">
            <span class="font-mono font-bold text-emerald-600 dark:text-emerald-400 uppercase text-[9.5px] block">Lösung (Wie es greift):</span>
            <span class="text-[var(--foreground)]">${info.solution}</span>
          </div>
          <div class="p-2 rounded-lg bg-amber-500/10 border border-amber-500/30">
            <span class="font-mono font-bold text-amber-600 dark:text-amber-400 uppercase text-[9.5px] block">Preis &amp; Schattenseite (Trade-off):</span>
            <span class="text-[var(--foreground)]">${info.tradeoff}</span>
            ${info.when_to_disable ? `<div class="mt-1 pt-1 border-t border-amber-500/20 text-[10px] text-[var(--muted-foreground)]"><strong class="font-mono text-[var(--foreground)]">Wann ausschalten?</strong> ${info.when_to_disable}</div>` : ''}
          </div>
        </div>
      `;
    }

    function enrichAutonomyCardsAndThresholds() {
      try {
        // 1. Alle 36 Modul-Cards im Tab AUTONOMIE & MODULE (36) mit Problem / Lösung / Preis & Schattenseite anreichern
        Object.keys(AUTONOMY_MODULE_TRADEOFFS).forEach(chkId => {
          const chk = document.getElementById(chkId);
          if (!chk) return;
          const info = AUTONOMY_MODULE_TRADEOFFS[chkId];

          if (chkId === "cfg-memory-consolidation-enabled") {
            const sec = document.getElementById("section-memory-consolidation");
            if (sec && !sec.querySelector(".aut-tradeoff-box")) {
              const descP = sec.querySelector("p");
              if (descP) {
                descP.insertAdjacentHTML("afterend", buildTradeoffBoxHtml(info));
              }
            }
            return;
          }

          const headerDiv = chk.closest(".border-b");
          if (headerDiv && headerDiv.parentElement && !headerDiv.parentElement.querySelector(".aut-tradeoff-box")) {
            headerDiv.insertAdjacentHTML("afterend", buildTradeoffBoxHtml(info));
          }
        });

        // 1b. Alle 14 HERMES CORE Sektionen (#hermes-sec-1 bis #hermes-sec-14) mit Problem / Lösung / Preis & Schattenseite anreichern
        Object.keys(HERMES_SECTION_TRADEOFFS).forEach(secId => {
          const sec = document.getElementById(secId);
          if (!sec || sec.querySelector(".aut-tradeoff-box")) return;
          const info = HERMES_SECTION_TRADEOFFS[secId];
          const headerDiv = sec.querySelector(".border-b");
          if (headerDiv) {
            headerDiv.insertAdjacentHTML("afterend", buildTradeoffBoxHtml(info));
          }
        });

        // 2. Alle Schwellenwert-Inputs im Tab AUTONOMIE & MODULE (36) + HERMES CORE mit Kipppunkt-Hinweisen versehen
        Object.keys(AUTONOMY_THRESHOLD_HINTS).forEach(inputId => {
          const inp = document.getElementById(inputId);
          if (!inp) return;
          const hintText = AUTONOMY_THRESHOLD_HINTS[inputId];
          const fieldWrapper = inp.parentElement.classList.contains("flex") ? inp.parentElement.parentElement : inp.parentElement;
          if (fieldWrapper && !fieldWrapper.querySelector(".aut-threshold-hint")) {
            fieldWrapper.insertAdjacentHTML(
              "beforeend",
              `<div class="aut-threshold-hint text-[9.5px] font-mono text-amber-600 dark:text-amber-400/90 mt-1 leading-snug">⚖️ ${hintText}</div>`
            );
          }
        });
      } catch (e) {
        console.warn("[SystemSettings] Fehler bei enrichAutonomyCardsAndThresholds:", e);
      }
    }

    function enrichPluginModalWithTradeoffs(pluginId) {
      try {
        const container = document.getElementById("plugin-cfg-fields-container");
        if (!container) return;

        // 1. Plugin-Metadaten (Problem / Lösung / Trade-off / Wann ausschalten) oben ins Zahnrad-Modal einfügen
        const allList = (Array.isArray(settingsPluginsData) && settingsPluginsData.length > 0)
          ? settingsPluginsData
          : (typeof pluginCenterData !== "undefined" && Array.isArray(pluginCenterData) && pluginCenterData.length > 0
            ? pluginCenterData
            : (Array.isArray(window.allPluginsData) ? window.allPluginsData : []));
        const pl = allList.find(p => p.id === pluginId);

        if (pl && pl.problem && !container.querySelector(".aut-tradeoff-box")) {
          container.insertAdjacentHTML("afterbegin", `<div class="mb-3">${buildTradeoffBoxHtml(pl)}</div>`);
        }

        // 2. Schwellenwert-Kipppunkte unter alle [data-cfg-key] Felder im Zahnrad-Modal setzen
        const inputs = container.querySelectorAll("[data-cfg-key]");
        inputs.forEach(inp => {
          if (inp.type === "checkbox") return;
          const key = inp.getAttribute("data-cfg-key");
          const hint = PLUGIN_MODAL_THRESHOLD_HINTS[key];
          if (hint && inp.parentElement && !inp.parentElement.querySelector(".aut-threshold-hint")) {
            inp.insertAdjacentHTML(
              "afterend",
              `<div class="aut-threshold-hint text-[9.5px] font-mono text-amber-600 dark:text-amber-400/90 mt-1 leading-snug">⚖️ ${hint}</div>`
            );
          }
        });
      } catch (e) {
        console.warn("[SystemSettings] Fehler bei enrichPluginModalWithTradeoffs:", e);
      }
    }

    window.enrichAutonomyCardsAndThresholds = enrichAutonomyCardsAndThresholds;
    window.enrichPluginModalWithTradeoffs = enrichPluginModalWithTradeoffs;
    window.buildTradeoffBoxHtml = buildTradeoffBoxHtml;


    // =========================================================================
    // SYSTEM UPDATE & RELEASE-LIFECYCLE (MEILENSTEIN 1)
    // =========================================================================
    async function checkSystemUpdateStatus(force = false) {
      const badge = document.getElementById("update-status-badge");
      const curCommit = document.getElementById("update-current-commit");
      const branchEl = document.getElementById("update-current-branch");
      const dirtyEl = document.getElementById("update-dirty-status");
      const incomingBox = document.getElementById("update-incoming-box");
      const incomingTitle = document.getElementById("update-incoming-title");
      const incomingList = document.getElementById("update-incoming-list");

      if (badge) {
        badge.innerText = "Prüfe GitHub...";
        badge.className = "px-2.5 py-0.5 rounded text-[10px] font-mono font-bold bg-neutral-500/10 text-[var(--foreground)] border border-[var(--border)]";
      }

      try {
        const res = await fetch(force ? "/api/v1/system/update/check?force=true" : "/api/v1/system/update/check");
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();

        const versionBadge = document.getElementById("update-system-version-badge");
        const versionEl = document.getElementById("update-current-version");
        if (versionBadge && data.version) versionBadge.innerText = data.version;
        if (versionEl && data.version) versionEl.innerText = `${data.version}${data.version_codename ? " · " + data.version_codename : ""}`;

        window._systemVersionSteps = data.version_steps || {
          none: data.version || "v0.3.8",
          subpatch: data.next_version || "v0.3.8.1",
          patch: "v0.3.9",
          minor: "v0.4.0"
        };
        window._activeVersionStep = "subpatch";

        const stepNone = document.getElementById("step-label-none");
        const stepSub = document.getElementById("step-label-subpatch");
        const stepPatch = document.getElementById("step-label-patch");
        const stepMinor = document.getElementById("step-label-minor");
        if (stepNone && window._systemVersionSteps.none) stepNone.innerText = window._systemVersionSteps.none;
        if (stepSub && window._systemVersionSteps.subpatch) stepSub.innerText = window._systemVersionSteps.subpatch;
        if (stepPatch && window._systemVersionSteps.patch) stepPatch.innerText = window._systemVersionSteps.patch;
        if (stepMinor && window._systemVersionSteps.minor) stepMinor.innerText = window._systemVersionSteps.minor;

        const targetVerInput = document.getElementById("push-target-version");
        if (targetVerInput && !targetVerInput.dataset.userEdited) {
          targetVerInput.value = window._systemVersionSteps.subpatch || data.next_version || "v0.3.8.1";
        }

        const btnVerLabel = document.getElementById("btn-push-version-label");
        if (btnVerLabel) btnVerLabel.innerText = targetVerInput ? targetVerInput.value : (data.next_version || "v0.3.8.1");

        // Auth Role & Master Push Permission
        const roleBadge = document.getElementById("push-role-badge");
        const pushBtn = document.getElementById("btn-push-github");
        const authHint = document.getElementById("push-auth-hint");
        const isAllowed = data.auth ? data.auth.can_push : true;

        if (roleBadge && data.auth) {
          roleBadge.innerText = data.auth.role_label;
          if (data.auth.can_push) {
            roleBadge.className = "px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20";
          } else {
            roleBadge.className = "px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-neutral-500/10 text-neutral-500 border border-neutral-500/20";
          }
        }
        if (pushBtn) {
          pushBtn.disabled = !isAllowed;
          if (!isAllowed) {
            pushBtn.classList.add("opacity-50", "cursor-not-allowed");
          } else {
            pushBtn.classList.remove("opacity-50", "cursor-not-allowed");
          }
        }
        if (authHint) {
          if (!isAllowed) {
            authHint.classList.remove("hidden");
          } else {
            authHint.classList.add("hidden");
          }
        }

        if (curCommit) curCommit.innerText = `${data.current_commit || "-"} (${data.last_commit_info || ""})`;
        if (branchEl) branchEl.innerText = `${data.branch || "main"} · Remote: ${data.remote_commit || "-"}`;
        window._localChangesList = data.changed_files || [];
        if (dirtyEl) {
          if (data.has_local_changes) {
            dirtyEl.innerHTML = `<span class="inline-flex items-center gap-1.5 cursor-pointer underline underline-offset-2 hover:opacity-80">⚠️ ${data.changed_files_count} modifizierte Dateien</span>`;
            dirtyEl.className = "font-mono font-bold text-xs text-amber-500 truncate mt-0.5 cursor-pointer";
          } else {
            dirtyEl.innerHTML = "<span>✅ Keine lokalen Konflikte</span>";
            dirtyEl.className = "font-mono font-bold text-xs text-emerald-500 truncate mt-0.5";
          }
        }
        const dirtyCard = document.getElementById("update-dirty-card");
        if (dirtyCard) {
          if (data.has_local_changes) {
            dirtyCard.classList.add("cursor-pointer");
            dirtyCard.title = "Klicken, um modifizierte Dateien im Dialog aufzulisten";
          } else {
            dirtyCard.title = "Lokaler Arbeitsstand ist sauber";
          }
        }

        const errorBox = document.getElementById("update-error-box");
        const errorHint = document.getElementById("update-error-hint");

        if (data.status === "offline_or_error" || data.status === "error") {
          if (badge) {
            badge.innerText = "GitHub-Verbindungsfehler";
            badge.className = "px-2.5 py-0.5 rounded text-[10px] font-mono font-bold bg-rose-500/10 text-rose-600 dark:text-rose-400 border border-rose-500/30";
            badge.title = data.message || "Authentifizierung oder Netzwerk fehlgeschlagen";
          }
          if (incomingBox) incomingBox.classList.add("hidden");
          if (errorBox) {
            errorBox.classList.remove("hidden");
            if (errorHint) {
              errorHint.innerText = data.message || "Authentifizierung fehlgeschlagen: Private Repositories erfordern ein GITHUB_TOKEN in der .env-Datei.";
            }
          }
          return;
        }

        if (errorBox) errorBox.classList.add("hidden");

        if (data.update_available) {
          if (badge) {
            badge.innerText = `${data.commits_behind} Update(s) verfügbar`;
            badge.className = "px-2.5 py-0.5 rounded text-[10px] font-mono font-bold bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/20";
          }
          if (incomingBox) incomingBox.classList.remove("hidden");
          if (incomingTitle) incomingTitle.innerText = `${data.commits_behind} neue Commits auf origin/main`;
          if (incomingList) {
            incomingList.innerHTML = (data.incoming_commits || []).map(c => `<div>• ${escapeHtml(c)}</div>`).join("");
          }
        } else {
          if (badge) {
            badge.innerText = "Archon OS ist aktuell";
            badge.className = "px-2.5 py-0.5 rounded text-[10px] font-mono font-bold bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20";
          }
          if (incomingBox) incomingBox.classList.add("hidden");
        }
      } catch (err) {
        if (badge) {
          badge.innerText = "Offline / Prüffehler";
          badge.className = "px-2.5 py-0.5 rounded text-[10px] font-mono font-bold bg-rose-500/10 text-rose-600 border border-rose-500/20";
        }
        console.warn("[SystemUpdater] Fehler bei checkSystemUpdateStatus:", err);
      }
    }

    async function applySystemUpdate() {
      const btn = document.getElementById("btn-apply-update");
      if (!confirm("Möchtest du das Update jetzt anwenden?\n\nEs wird vorab automatisch ein Sicherheits-Snapshot aller Datenbanken und Einstellungen erstellt.")) {
        return;
      }
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<i data-lucide="loader-2" class="w-3.5 h-3.5 animate-spin"></i> Aktualisiere System...';
      }
      try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 60000);
        const res = await fetch("/api/v1/system/update/apply", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ backup: true }),
          signal: controller.signal
        });
        clearTimeout(timeoutId);
        const data = await res.json();
        if (data.status === "success") {
          alert(`Update erfolgreich installiert!\nNeuer Commit: ${data.new_commit}\n\nDie Seite wird nun neu geladen.`);
          window.location.reload();
        } else {
          alert(`Update fehlgeschlagen: ${data.message || "Unbekannter Fehler"}`);
        }
      } catch (err) {
        alert("Netzwerkfehler beim Anwenden des Updates: " + err.message);
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = '<i data-lucide="download" class="w-3.5 h-3.5"></i> Update jetzt installieren & anwenden';
        }
      }
    }

    async function createManualSnapshot() {
      try {
        const res = await fetch("/api/v1/system/update/backup", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ tag: "manual" })
        });
        const data = await res.json();
        if (data.status === "success") {
          alert(`Sicherheits-Snapshot '${data.snapshot_id}' erfolgreich angelegt!`);
          await loadSystemSnapshots();
        } else {
          alert("Fehler beim Anlegen des Snapshots.");
        }
      } catch (err) {
        alert("Fehler: " + err.message);
      }
    }

    async function loadSystemSnapshots() {
      const listEl = document.getElementById("update-snapshots-list");
      if (!listEl) return;
      try {
        const res = await fetch("/api/v1/system/update/snapshots");
        const data = await res.json();
        const items = data.snapshots || [];
        if (items.length === 0) {
          listEl.innerHTML = '<div class="text-[11px] text-[var(--muted-foreground)] italic p-2">Noch keine Snapshots vorhanden.</div>';
          return;
        }
        listEl.innerHTML = items.map(s => {
          const dbs = (s.databases || []).map(d => `${d.name} (${Math.round(d.size_bytes/1024)} KB)`).join(", ");
          return `
            <div class="p-2.5 rounded-lg border border-[var(--border)] bg-[var(--background)] flex items-center justify-between gap-2">
              <div>
                <div class="font-mono font-bold text-xs text-[var(--foreground)] flex items-center gap-2">
                  <span class="px-1.5 py-0.5 rounded bg-neutral-500/10 text-[10px] uppercase font-bold">${escapeHtml(s.tag || 'snapshot')}</span>
                  ${escapeHtml(s.snapshot_id || 'ID')}
                  <span class="text-[10px] font-normal text-[var(--muted-foreground)]">· ${escapeHtml(s.created_at || '')}</span>
                </div>
                <div class="text-[10.5px] font-mono text-[var(--muted-foreground)] mt-0.5 truncate max-w-md">
                  DBs: ${escapeHtml(dbs || 'keine')} · Commit: ${escapeHtml(s.git_commit || '-')}
                </div>
              </div>
              <button type="button" onclick="rollbackSystemSnapshot('${s.snapshot_id}')" class="px-2.5 py-1 rounded text-[11px] font-mono border border-rose-500/30 text-rose-600 dark:text-rose-400 hover:bg-rose-500/10 transition cursor-pointer">
                Rollback
              </button>
            </div>
          `;
        }).join("");
      } catch (err) {
        listEl.innerHTML = `<div class="text-[11px] text-rose-500 p-2">Konnte Snapshots nicht laden: ${escapeHtml(err.message)}</div>`;
      }
    }

    async function rollbackSystemSnapshot(snapshotId) {
      if (!confirm(`Möchtest du den Zustand aus Snapshot '${snapshotId}' wirklich wiederherstellen?\n\nAlle Datenbanken und Konfigurationsdateien werden auf diesen Stand zurückgesetzt.`)) {
        return;
      }
      try {
        const res = await fetch("/api/v1/system/update/rollback", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ snapshot_id: snapshotId })
        });
        const data = await res.json();
        if (data.status === "success") {
          alert(`Rollback erfolgreich!\n${data.message}\n\nDie Seite wird neu geladen.`);
          window.location.reload();
        } else {
          alert(`Rollback fehlgeschlagen: ${data.message || "Unbekannter Fehler"}`);
        }
      } catch (err) {
        alert("Fehler beim Rollback: " + err.message);
      }
    }

    window.checkSystemUpdateStatus = checkSystemUpdateStatus;
    window.applySystemUpdate = applySystemUpdate;
    window.createManualSnapshot = createManualSnapshot;
    window.loadSystemSnapshots = loadSystemSnapshots;
    window.rollbackSystemSnapshot = rollbackSystemSnapshot;
        function selectVersionStep(step) {
      window._activeVersionStep = step;
      const targetInput = document.getElementById("push-target-version");
      const btnVerLabel = document.getElementById("btn-push-version-label");
      const steps = window._systemVersionSteps || {};
      const val = steps[step] || targetInput.value;
      if (targetInput) {
        targetInput.value = val;
        targetInput.dataset.userEdited = "";
      }
      if (btnVerLabel) btnVerLabel.innerText = val;

      const pillIds = ["none", "subpatch", "patch", "minor"];
      pillIds.forEach(id => {
        const btn = document.getElementById(`step-btn-${id}`);
        if (!btn) return;
        if (id === step) {
          btn.className = "px-2 py-1 rounded text-[10px] font-mono font-bold bg-indigo-500/15 text-indigo-600 border border-indigo-500/40 shadow-2xs transition cursor-pointer";
        } else {
          btn.className = "px-2 py-1 rounded text-[10px] font-mono font-semibold border border-[var(--border)] hover:bg-[var(--secondary)] transition cursor-pointer";
        }
      });
    }
    window.selectVersionStep = selectVersionStep;

    function onCustomVersionInput() {
      const targetInput = document.getElementById("push-target-version");
      const btnVerLabel = document.getElementById("btn-push-version-label");
      if (!targetInput) return;
      targetInput.dataset.userEdited = "true";
      window._activeVersionStep = "custom";
      if (btnVerLabel) btnVerLabel.innerText = targetInput.value.trim() || "v...";

      const pillIds = ["none", "subpatch", "patch", "minor"];
      pillIds.forEach(id => {
        const btn = document.getElementById(`step-btn-${id}`);
        if (btn) btn.className = "px-2 py-1 rounded text-[10px] font-mono font-semibold border border-[var(--border)] hover:bg-[var(--secondary)] transition cursor-pointer";
      });
    }
    window.onCustomVersionInput = onCustomVersionInput;

    async function pushChangesToGitHub() {
      const btn = document.getElementById("btn-push-github");
      const badge = document.getElementById("push-status-badge");
      const msgInput = document.getElementById("push-commit-message");
      const msg = msgInput ? msgInput.value.trim() : "";

      if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<i data-lucide="loader-2" class="w-3.5 h-3.5 animate-spin"></i> Übertrage zu GitHub...';
      }
      if (badge) {
        badge.innerText = "Pushe Änderungen...";
        badge.className = "px-2.5 py-0.5 rounded text-[10px] font-mono font-bold bg-amber-500/10 text-amber-600 border border-amber-500/20";
      }

      try {
        const targetInput = document.getElementById("push-target-version");
        const customVer = targetInput ? targetInput.value.trim() : "";
        const stepVal = window._activeVersionStep || "custom";

        const res = await fetch("/api/v1/system/update/push", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            message: msg,
            version: customVer,
            step: stepVal
          })
        });
        const data = await res.json();
        if (data.status === "success") {
          alert(`Release ${data.version || ""} erfolgreich auf GitHub veröffentlicht!\n\nCommit: ${data.commit}\nGit-Tag: ${data.version || ""}\n${data.message}`);
          if (badge) {
            badge.innerText = `Release ${data.version || ""} live`;
            badge.className = "px-2.5 py-0.5 rounded text-[10px] font-mono font-bold bg-emerald-500/10 text-emerald-600 border border-emerald-500/20";
          }
          if (msgInput) msgInput.value = "";
          await checkSystemUpdateStatus(true);
        } else if (data.status === "nothing_to_commit") {
          alert(data.message);
          if (badge) {
            badge.innerText = "Alles aktuell";
            badge.className = "px-2.5 py-0.5 rounded text-[10px] font-mono font-bold bg-emerald-500/10 text-emerald-600 border border-emerald-500/20";
          }
        } else {
          alert(`Push fehlgeschlagen: ${data.message || "Unbekannter Fehler"}`);
          if (badge) {
            badge.innerText = "Fehler";
            badge.className = "px-2.5 py-0.5 rounded text-[10px] font-mono font-bold bg-rose-500/10 text-rose-600 border border-rose-500/20";
          }
        }
      } catch (err) {
        alert("Netzwerkfehler beim Pushen: " + err.message);
        if (badge) {
          badge.innerText = "Netzwerkfehler";
          badge.className = "px-2.5 py-0.5 rounded text-[10px] font-mono font-bold bg-rose-500/10 text-rose-600 border border-rose-500/20";
        }
      } finally {
        if (btn) {
          btn.disabled = false;
          const curNext = document.getElementById("push-next-version-badge")?.innerText || "v0.3.7";
          btn.innerHTML = `<i data-lucide="upload-cloud" class="w-3.5 h-3.5"></i> <span id="btn-push-label">Release <span id="btn-push-version-label">${curNext}</span> zu GitHub pushen</span>`;
          if (window.lucide) window.lucide.createIcons();
        }
      }
    }

    
    // --- LOKALE AENDERUNGEN MODAL (GIT STATUS INSPECTOR) ---
    async function openLocalChangesModal() {
      const modal = document.getElementById("modal-local-changes");
      if (!modal) return;
      modal.classList.remove("hidden");
      await refreshLocalChangesModal();
    }

    async function refreshLocalChangesModal() {
      const listEl = document.getElementById("local-changes-list");
      const badgeEl = document.getElementById("local-changes-count-badge");
      if (listEl) {
        listEl.innerHTML = '<div class="flex items-center justify-center p-6 text-[var(--muted-foreground)] text-xs"><i data-lucide="loader-2" class="w-4 h-4 animate-spin mr-2"></i> Lade geänderte Dateien...</div>';
        if (window.lucide) window.lucide.createIcons();
      }

      try {
        const res = await fetch("/api/v1/system/update/local-changes?force=true");
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        window._localChangesList = data.files || [];
        renderLocalChangesList(window._localChangesList);
        if (badgeEl) badgeEl.innerText = `${data.total || window._localChangesList.length} Dateien`;
      } catch (e) {
        console.warn("Fehler beim Abrufen der lokalen Änderungen:", e);
        renderLocalChangesList(window._localChangesList || []);
      }
    }

    function renderLocalChangesList(files) {
      const listEl = document.getElementById("local-changes-list");
      const searchInput = document.getElementById("local-changes-search");
      const query = (searchInput ? searchInput.value : "").trim().toLowerCase();
      if (!listEl) return;

      const filtered = query 
        ? files.filter(f => (f.path || "").toLowerCase().includes(query) || (f.code || "").toLowerCase().includes(query))
        : files;

      if (!filtered || filtered.length === 0) {
        if (query) {
          listEl.innerHTML = `<div class="p-6 text-center text-[var(--muted-foreground)]">Keine Dateien passend zu "${escapeHtml(query)}" gefunden.</div>`;
        } else {
          listEl.innerHTML = '<div class="p-6 text-center text-emerald-500 font-bold">✅ Keine ungespeicherten lokalen Änderungen vorhanden. Der Stand ist sauber.</div>';
        }
        return;
      }

      const badgeStyles = {
        amber: "bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/30",
        sky: "bg-sky-500/10 text-sky-600 dark:text-sky-400 border-sky-500/30",
        emerald: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/30",
        rose: "bg-rose-500/10 text-rose-600 dark:text-rose-400 border-rose-500/30",
        purple: "bg-purple-500/10 text-purple-600 dark:text-purple-400 border-purple-500/30"
      };

      listEl.innerHTML = filtered.map(f => {
        const style = badgeStyles[f.color] || "bg-neutral-500/10 text-[var(--foreground)] border-[var(--border)]";
        return `
          <div class="flex items-center justify-between gap-3 py-2 px-2.5 rounded-lg hover:bg-[var(--secondary)] transition group">
            <div class="flex items-center gap-2.5 min-w-0">
              <span class="px-1.5 py-0.5 rounded text-[10px] font-bold font-mono border shrink-0 ${style}">
                ${escapeHtml(f.code || "M")}
              </span>
              <span class="truncate text-xs font-mono text-[var(--foreground)]" title="${escapeHtml(f.path)}">
                ${escapeHtml(f.path)}
              </span>
            </div>
            <span class="text-[10px] text-[var(--muted-foreground)] font-mono shrink-0">${escapeHtml(f.label || "Geändert")}</span>
          </div>
        `;
      }).join("");

      if (window.lucide) window.lucide.createIcons();
    }

    function filterLocalChangesList() {
      renderLocalChangesList(window._localChangesList || []);
    }

    function closeLocalChangesModal() {
      const modal = document.getElementById("modal-local-changes");
      if (modal) modal.classList.add("hidden");
    }

    window.openLocalChangesModal = openLocalChangesModal;
    window.closeLocalChangesModal = closeLocalChangesModal;
    window.refreshLocalChangesModal = refreshLocalChangesModal;
    window.filterLocalChangesList = filterLocalChangesList;

    window.pushChangesToGitHub = pushChangesToGitHub;

    // =========================================================================
    // API-KEYS & SCOPES ACCESS MANAGEMENT (t-6fad7a)
    // =========================================================================
    let lastGeneratedRawKey = "";

    async function loadApiKeys() {
      const tbody = document.getElementById("api-keys-table-body");
      const badge = document.getElementById("api-keys-count-badge");
      if (!tbody) return;

      tbody.innerHTML = '<tr><td colspan="8" class="py-6 text-center text-[var(--muted-foreground)] font-sans">Lade API-Keys...</td></tr>';

      try {
        const res = await fetch("/api/operations/keys");
        const data = await res.json();
        const keys = (data.status === "success" && data.keys) ? data.keys : [];

        if (badge) badge.innerText = `${keys.length} Key${keys.length === 1 ? "" : "s"}`;

        if (keys.length === 0) {
          tbody.innerHTML = `
            <tr>
              <td colspan="8" class="py-8 text-center text-[var(--muted-foreground)] font-sans">
                <div class="flex flex-col items-center justify-center gap-1.5">
                  <i data-lucide="key" class="w-6 h-6 text-zinc-400 mb-1"></i>
                  <span class="font-bold text-xs">Noch keine API-Keys vorhanden</span>
                  <span class="text-[11px]">Klicke oben rechts auf "+ Neuen API-Key generieren", um n8n oder Clients anzubinden.</span>
                </div>
              </td>
            </tr>
          `;
          if (typeof lucide !== "undefined") lucide.createIcons();
          return;
        }

        tbody.innerHTML = keys.map(k => {
          const isActive = k.is_active;
          const statusBadge = isActive
            ? '<span class="px-2 py-0.5 rounded-full text-[9.5px] font-mono font-bold bg-emerald-500/10 text-emerald-600 border border-emerald-500/20">AKTIV</span>'
            : '<span class="px-2 py-0.5 rounded-full text-[9.5px] font-mono font-bold bg-zinc-500/10 text-zinc-500 border border-zinc-500/20">WIDERRUFEN</span>';

          const scopesBadges = (k.scopes || []).map(s => {
            let col = "bg-sky-500/10 text-sky-600 border-sky-500/20";
            if (s === "kanban_rw") col = "bg-amber-500/10 text-amber-600 border-amber-500/20";
            if (s === "agent_execute") col = "bg-emerald-500/10 text-emerald-600 border-emerald-500/20";
            if (s === "admin_full") col = "bg-rose-500/10 text-rose-600 border-rose-500/20";
            return `<span class="px-1.5 py-0.2 rounded text-[9.5px] font-mono font-bold border ${col}">${s}</span>`;
          }).join(" ");

          const createdDate = k.created_at ? new Date(k.created_at).toLocaleString("de-DE", { dateStyle: "short", timeStyle: "short" }) : "-";
          const lastUsed = k.last_used_at ? new Date(k.last_used_at).toLocaleString("de-DE", { dateStyle: "short", timeStyle: "short" }) : "Nie";

          const rpmText = k.rate_limit_rpm ? `${k.rate_limit_rpm} / Min` : "∞";
          const rpdText = k.rate_limit_rpd ? `${k.rate_limit_rpd} / Tag` : "∞";

          const actionBtn = isActive
            ? `<button type="button" onclick="revokeApiKey('${k.key_id}', '${escapeHtml(k.name)}')" class="px-2 py-1 rounded text-[10px] font-mono font-bold bg-amber-500/10 hover:bg-amber-500/20 text-amber-600 border border-amber-500/30 transition cursor-pointer" title="Key sperren">Widerrufen</button>`
            : `<button type="button" onclick="deleteApiKey('${k.key_id}', '${escapeHtml(k.name)}')" class="px-2 py-1 rounded text-[10px] font-mono font-bold bg-rose-500/10 hover:bg-rose-500/20 text-rose-600 border border-rose-500/30 transition cursor-pointer" title="Key endgültig entfernen">Löschen</button>`;

          return `
            <tr class="hover:bg-[var(--secondary)]/20 transition-colors">
              <td class="py-2.5 px-4 font-sans font-bold text-[var(--foreground)]">${escapeHtml(k.name)}</td>
              <td class="py-2.5 px-3 font-mono text-[var(--muted-foreground)]">${escapeHtml(k.key_prefix)}</td>
              <td class="py-2.5 px-3"><div class="flex flex-wrap gap-1">${scopesBadges}</div></td>
              <td class="py-2.5 px-3 text-[10px] text-[var(--muted-foreground)]">${rpmText} | ${rpdText}</td>
              <td class="py-2.5 px-3 text-[10px] text-[var(--muted-foreground)]">${createdDate}</td>
              <td class="py-2.5 px-3 text-[10px] text-[var(--muted-foreground)]">${lastUsed}</td>
              <td class="py-2.5 px-3">${statusBadge}</td>
              <td class="py-2.5 px-4 text-right">${actionBtn}</td>
            </tr>
          `;
        }).join("");

        if (typeof lucide !== "undefined") lucide.createIcons();
      } catch (err) {
        tbody.innerHTML = `<tr><td colspan="8" class="py-4 text-center text-rose-500 font-sans">Fehler beim Laden: ${err.message}</td></tr>`;
      }
    }

    function openCreateApiKeyModal() {
      const modal = document.getElementById("modal-create-api-key");
      if (modal) {
        modal.classList.remove("hidden");
        const nameInput = document.getElementById("new-key-name");
        if (nameInput) {
          nameInput.value = "";
          setTimeout(() => nameInput.focus(), 50);
        }
      }
    }

    function closeCreateApiKeyModal() {
      const modal = document.getElementById("modal-create-api-key");
      if (modal) modal.classList.add("hidden");
    }

    async function submitCreateApiKey() {
      const nameInput = document.getElementById("new-key-name");
      const name = nameInput ? nameInput.value.trim() : "";
      if (!name) {
        alert("Bitte gib einen Namen oder Verwendungszweck an (z. B. 'n8n Automation').");
        if (nameInput) nameInput.focus();
        return;
      }

      const scopes = [];
      ["read_only", "kanban_rw", "agent_execute", "admin_full"].forEach(s => {
        const cb = document.getElementById(`scope-${s}`);
        if (cb && cb.checked) scopes.push(s);
      });

      if (scopes.length === 0) {
        alert("Bitte wähle mindestens eine Berechtigung (Scope) aus.");
        return;
      }

      const rpmInput = document.getElementById("new-key-rpm");
      const rpdInput = document.getElementById("new-key-rpd");
      const rpm = rpmInput ? parseInt(rpmInput.value) || 0 : 60;
      const rpd = rpdInput ? parseInt(rpdInput.value) || 0 : 5000;

      try {
        const res = await fetch("/api/operations/keys", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: name,
            scopes: scopes,
            rate_limit_rpm: rpm,
            rate_limit_rpd: rpd,
            created_by: "admin"
          })
        });

        const data = await res.json();
        if (data.status === "success" && data.result) {
          closeCreateApiKeyModal();
          lastGeneratedRawKey = data.result.raw_token;

          // Einmalanzeige-Banner aufklappen
          const alertBox = document.getElementById("api-key-new-token-alert");
          const tokenInput = document.getElementById("api-key-new-token-input");
          if (alertBox && tokenInput) {
            tokenInput.value = lastGeneratedRawKey;
            alertBox.classList.remove("hidden");
            alertBox.scrollIntoView({ behavior: "smooth" });
          }

          await loadApiKeys();
        } else {
          alert(`Fehler beim Erstellen: ${data.detail || data.message || "Unbekannter Fehler"}`);
        }
      } catch (err) {
        alert(`Netzwerkfehler: ${err.message}`);
      }
    }

    async function copyNewGeneratedKey() {
      const tokenInput = document.getElementById("api-key-new-token-input");
      const btn = document.getElementById("btn-copy-new-key");
      if (!tokenInput || !tokenInput.value) return;

      try {
        await navigator.clipboard.writeText(tokenInput.value);
        if (btn) {
          const orig = btn.innerHTML;
          btn.innerHTML = '<i data-lucide="check" class="w-3.5 h-3.5"></i> Kopiert!';
          if (typeof lucide !== "undefined") lucide.createIcons();
          setTimeout(() => {
            btn.innerHTML = orig;
            if (typeof lucide !== "undefined") lucide.createIcons();
          }, 2000);
        }
      } catch (e) {
        tokenInput.select();
        document.execCommand("copy");
        alert("API-Key in die Zwischenablage kopiert!");
      }
    }

    async function revokeApiKey(keyId, name) {
      if (!confirm(`Möchtest du den API-Key "${name}" wirklich unwiderruflich sperren? Bereits angebundene Dienste (n8n, Telegram) haben danach keinen Zugriff mehr.`)) {
        return;
      }

      try {
        const res = await fetch(`/api/operations/keys/${encodeURIComponent(keyId)}/revoke`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ revoked_by: "admin" })
        });
        const data = await res.json();
        if (data.status === "success") {
          await loadApiKeys();
        } else {
          alert(`Fehler: ${data.detail || "Konnte Key nicht sperren."}`);
        }
      } catch (err) {
        alert(`Netzwerkfehler: ${err.message}`);
      }
    }

    async function deleteApiKey(keyId, name) {
      if (!confirm(`Soll der inaktive Key "${name}" endgültig aus der Übersicht entfernt werden? (Das SHA-256 Audit-Log bleibt rechtssicher erhalten)`)) {
        return;
      }

      try {
        const res = await fetch(`/api/operations/keys/${encodeURIComponent(keyId)}`, {
          method: "DELETE",
          headers: { "Content-Type": "application/json" }
        });
        const data = await res.json();
        if (data.status === "success") {
          await loadApiKeys();
        } else {
          alert(`Fehler: ${data.detail || "Konnte Key nicht löschen."}`);
        }
      } catch (err) {
        alert(`Netzwerkfehler: ${err.message}`);
      }
    }

    window.loadApiKeys = loadApiKeys;
    window.openCreateApiKeyModal = openCreateApiKeyModal;
    window.closeCreateApiKeyModal = closeCreateApiKeyModal;
    window.submitCreateApiKey = submitCreateApiKey;
    window.copyNewGeneratedKey = copyNewGeneratedKey;
    window.revokeApiKey = revokeApiKey;
    window.deleteApiKey = deleteApiKey;

// ---------------------------------------------------------------------------
// Modell-Routing pro Aufgabe (Eigentümer-Entscheidung)
// ---------------------------------------------------------------------------
let _mrConfig = { enabled: false, routes: [], autonomy: { operations: "approval", orchestrator: "approval" } };
const MR_PROVIDERS = ["openrouter", "omniroute", "google", "openai", "groq", "mistral", "nvidia"];

function _mrEsc(v) {
  return String(v == null ? "" : v).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
}

async function loadModelRoutingSettings() {
  try {
    const res = await fetch("/api/settings/model-routing");
    const data = await res.json();
    if (data && data.config) {
      _mrConfig = data.config;
      renderModelRoutingRows();
    }
  } catch (e) {
    console.warn("[ModelRouting] load failed", e);
  }
}

function renderModelRoutingRows() {
  const box = document.getElementById("mr-rows");
  if (!box) return;
  const en = document.getElementById("mr-enabled");
  if (en) en.checked = !!_mrConfig.enabled;
  const ao = document.getElementById("mr-autonomy-operations");
  const ar = document.getElementById("mr-autonomy-orchestrator");
  if (ao) ao.value = (_mrConfig.autonomy || {}).operations || "approval";
  if (ar) ar.value = (_mrConfig.autonomy || {}).orchestrator || "approval";

  box.innerHTML = (_mrConfig.routes || []).map((r, i) => `
    <div class="grid grid-cols-12 gap-2 items-center" data-mr-row="${i}">
      <input class="col-span-3 bg-[var(--background)] border border-[var(--border)] rounded-lg px-2 py-1.5 text-[11px] font-mono" data-field="label" value="${_mrEsc(r.label)}" placeholder="Aufgabe">
      <input class="col-span-2 bg-[var(--background)] border border-[var(--border)] rounded-lg px-2 py-1.5 text-[10px] font-mono" data-field="task" value="${_mrEsc(r.task)}" placeholder="key">
      <select class="col-span-2 bg-[var(--background)] border border-[var(--border)] rounded-lg px-1 py-1.5 text-[10px] font-mono" data-field="provider">
        ${MR_PROVIDERS.map(p => `<option value="${p}" ${p === r.provider ? "selected" : ""}>${p}</option>`).join("")}
      </select>
      <input class="col-span-4 bg-[var(--background)] border border-[var(--border)] rounded-lg px-2 py-1.5 text-[10px] font-mono" data-field="model" value="${_mrEsc(r.model)}" placeholder="provider/model">
      <button type="button" class="col-span-1 text-[var(--muted-foreground)] hover:text-rose-500" onclick="removeModelRouteRow(${i})" title="Entfernen">✕</button>
    </div>`).join("");
}

function addModelRouteRow() {
  _mrConfig.routes = _mrConfig.routes || [];
  _mrConfig.routes.push({ task: "", label: "", provider: "openrouter", model: "" });
  renderModelRoutingRows();
}

function removeModelRouteRow(index) {
  if (!_mrConfig.routes) return;
  _mrConfig.routes.splice(index, 1);
  renderModelRoutingRows();
}

function collectModelRoutingRows() {
  return Array.from(document.querySelectorAll("[data-mr-row]")).map(el => {
    const get = f => {
      const node = el.querySelector('[data-field="' + f + '"]');
      return node ? node.value.trim() : "";
    };
    return { task: get("task"), label: get("label") || get("task"), provider: get("provider"), model: get("model") };
  }).filter(r => r.task && r.model);
}

async function saveModelRoutingSettings() {
  const status = document.getElementById("mr-status");
  const payload = {
    enabled: !!(document.getElementById("mr-enabled") || {}).checked,
    routes: collectModelRoutingRows(),
    autonomy: {
      operations: (document.getElementById("mr-autonomy-operations") || {}).value || "approval",
      orchestrator: (document.getElementById("mr-autonomy-orchestrator") || {}).value || "approval"
    }
  };
  try {
    const res = await fetch("/api/settings/model-routing", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      if (status) status.textContent = "Fehler: " + (data.detail || res.status);
      return;
    }
    _mrConfig = data.config;
    renderModelRoutingRows();
    if (status) status.textContent = "Gespeichert " + new Date().toLocaleTimeString();
  } catch (e) {
    if (status) status.textContent = "Netzwerkfehler";
  }
}

window.loadModelRoutingSettings = loadModelRoutingSettings;
window.renderModelRoutingRows = renderModelRoutingRows;
window.addModelRouteRow = addModelRouteRow;
window.removeModelRouteRow = removeModelRouteRow;
window.collectModelRoutingRows = collectModelRoutingRows;
window.saveModelRoutingSettings = saveModelRoutingSettings;
