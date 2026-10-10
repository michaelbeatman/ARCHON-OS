
    // --- SYSTEM CONTROL CENTER LOGIC ---
    let currentEditingRoleSettingsId = "";
    // Fix 2026-10-09 (Race Condition): #system-settings-mount existiert erst in
    // view_design_system.html, die erst NACH dem Settings-Fetch in initArchonApp()
    // montiert wird. Dieser Guard holt das Modal nach, wo immer es fehlt.
    async function ensureSettingsModalMounted() {
      if (document.getElementById("system-settings-modal")) return true;
      try {
        const res = await fetch("/static/views/system_settings_modal.html");
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
      if (gwKeyEl) gwKeyEl.value = "sk-949ea8f3766d6490-f9ab38-33bea980";
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
      }
    }
    function closeSystemSettingsModal() {
      document.getElementById("system-settings-modal").classList.add("hidden");
    }
    function setSettingsTab(tabName) {
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
      const tabs = ["kernel", "services", "routing", "frameworks", "plugins", "comm", "design"];
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

      if (targetTab === "kernel") {
        if (typeof loadHermesFormSettings === "function") {
          loadHermesFormSettings();
        }
      } else if (targetTab === "services") {
        if (typeof renderSettingsServices === "function") {
          renderSettingsServices();
        }
      } else if (targetTab === "routing") {
        if (typeof loadLLMProvidersSettings === "function") {
          loadLLMProvidersSettings();
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
        if (typeof loadKanbanPaletteSettings === "function") {
          loadKanbanPaletteSettings();
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

                      <!-- Description -->
                      <p class="text-[11px] text-[var(--muted-foreground)] leading-relaxed line-clamp-2">${p.desc || p.description || 'Erweiterung für den Archon Kernel.'}</p>
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
          showNotification("Plugin-Manager", `Plugin '${pluginId}' wurde ${enable ? 'aktiviert' : 'deaktiviert'}.`, "success");
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

        // Formular-Felder befüllen
        const s = data.settings || {};
        const el = (id) => document.getElementById(id);
        if (el("hermes-cfg-model-default")) el("hermes-cfg-model-default").value = s.model_default || "z-ai/glm-5.3";
        if (el("hermes-cfg-model-provider")) el("hermes-cfg-model-provider").value = s.model_provider || "openrouter";
        if (el("hermes-cfg-base-url")) el("hermes-cfg-base-url").value = s.base_url || "";
        if (el("hermes-cfg-reasoning-effort")) el("hermes-cfg-reasoning-effort").value = s.reasoning_effort || "medium";
        if (el("hermes-cfg-max-context-tokens")) el("hermes-cfg-max-context-tokens").value = s.max_context_tokens || 32000;
        if (el("hermes-cfg-max-history")) el("hermes-cfg-max-history").value = s.max_history_messages || 20;
        if (el("hermes-cfg-task-timeout")) el("hermes-cfg-task-timeout").value = s.task_timeout_seconds || 60;
        if (el("hermes-cfg-language")) el("hermes-cfg-language").value = s.language || "de";
        if (el("hermes-cfg-reasoning-full")) el("hermes-cfg-reasoning-full").checked = s.reasoning_full !== false;
        if (el("hermes-cfg-show-cost")) el("hermes-cfg-show-cost").checked = s.show_cost !== false;
        if (el("hermes-cfg-timestamps")) el("hermes-cfg-timestamps").checked = s.timestamps !== false;
        if (el("hermes-cfg-bell-complete")) el("hermes-cfg-bell-complete").checked = s.bell_on_complete !== false;
        if (el("hermes-cfg-multiplex-profiles")) el("hermes-cfg-multiplex-profiles").checked = s.multiplex_profiles !== false;
        if (el("hermes-cfg-a2a-enabled")) el("hermes-cfg-a2a-enabled").checked = s.a2a_enabled !== false;
        if (el("hermes-cfg-stt-provider")) el("hermes-cfg-stt-provider").value = s.stt_provider || "groq";
        if (el("hermes-cfg-stt-language")) el("hermes-cfg-stt-language").value = s.stt_language || "de";

        // Allowlist
        const allowlist = s.command_allowlist || [];
        if (el("hermes-allow-heredoc")) el("hermes-allow-heredoc").checked = allowlist.includes("script execution via heredoc");
        if (el("hermes-allow-execute-code")) el("hermes-allow-execute-code").checked = allowlist.includes("execute_code");
        if (el("hermes-allow-bash")) el("hermes-allow-bash").checked = allowlist.includes("terminal_bash");

        // Raw Editor im Accordion
        if (rawEditorEl) {
          rawEditorEl.value = data.raw_yaml || "";
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

    async function saveHermesFormSettings() {
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
          model_default: el("hermes-cfg-model-default") ? el("hermes-cfg-model-default").value.trim() : "z-ai/glm-5.3",
          model_provider: el("hermes-cfg-model-provider") ? el("hermes-cfg-model-provider").value : "openrouter",
          base_url: el("hermes-cfg-base-url") ? el("hermes-cfg-base-url").value.trim() : "",
          reasoning_effort: el("hermes-cfg-reasoning-effort") ? el("hermes-cfg-reasoning-effort").value : "medium",
          max_context_tokens: el("hermes-cfg-max-context-tokens") ? parseInt(el("hermes-cfg-max-context-tokens").value, 10) : 32000,
          max_history_messages: el("hermes-cfg-max-history") ? parseInt(el("hermes-cfg-max-history").value, 10) : 20,
          task_timeout_seconds: el("hermes-cfg-task-timeout") ? parseInt(el("hermes-cfg-task-timeout").value, 10) : 60,
          language: el("hermes-cfg-language") ? el("hermes-cfg-language").value : "de",
          reasoning_full: el("hermes-cfg-reasoning-full") ? el("hermes-cfg-reasoning-full").checked : true,
          show_cost: el("hermes-cfg-show-cost") ? el("hermes-cfg-show-cost").checked : true,
          timestamps: el("hermes-cfg-timestamps") ? el("hermes-cfg-timestamps").checked : true,
          bell_on_complete: el("hermes-cfg-bell-complete") ? el("hermes-cfg-bell-complete").checked : true,
          multiplex_profiles: el("hermes-cfg-multiplex-profiles") ? el("hermes-cfg-multiplex-profiles").checked : true,
          a2a_enabled: el("hermes-cfg-a2a-enabled") ? el("hermes-cfg-a2a-enabled").checked : true,
          stt_provider: el("hermes-cfg-stt-provider") ? el("hermes-cfg-stt-provider").value : "groq",
          stt_language: el("hermes-cfg-stt-language") ? el("hermes-cfg-stt-language").value.trim() : "de",
          command_allowlist: allowlist
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
        if (data.status === "success") {
          showNotification("Hermes Core", data.message || "Einstellungen erfolgreich gespeichert.", "success");
          if (badge) {
            badge.className = "text-[10px] font-mono px-2 py-1 rounded-md bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20 font-bold";
            badge.innerText = "Gespeichert";
          }
          if (statusMsg) {
            statusMsg.innerText = "Zuletzt gespeichert: " + new Date().toLocaleTimeString();
          }
          loadHermesFormSettings(configPath);
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
