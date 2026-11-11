
    // --- DYNAMISCHER TALENT- & SKILL-MARKTPLATZ CONTROLLER ---
    function clearSearchInput(inputId, callback) {
      const input = document.getElementById(inputId);
      if (input) {
        input.value = "";
        const clearBtn = document.getElementById(inputId + "-clear");
        if (clearBtn) clearBtn.classList.add("hidden");
        if (callback) callback("");
        input.focus();
      }
    }
    function toggleClearBtn(inputId) {
      const input = document.getElementById(inputId);
      const clearBtn = document.getElementById(inputId + "-clear");
      if (input && clearBtn) {
        if (input.value && input.value.trim().length > 0) {
          clearBtn.classList.remove("hidden");
        } else {
          clearBtn.classList.add("hidden");
        }
      }
    }
    let marketplaceTemplatesList = [];
    let currentSelectedMarketplaceTemplateId = "";
    let marketSearchDebounceTimer = null;
    async function loadMarketplaceSources() {
      const srcSelect = document.getElementById("market-source-select");
      if (!srcSelect) return;
      try {
        const res = await fetch("/api/marketplace/sources");
        if (res.ok) {
          const sources = await res.json();
          if (sources && sources.length > 0) {
            const currentVal = srcSelect.value;
            srcSelect.innerHTML = "";
            sources.forEach(s => {
              const opt = document.createElement("option");
              opt.value = s.id;
              opt.innerText = s.name;
              srcSelect.appendChild(opt);
            });
            if (currentVal && sources.some(s => s.id === currentVal)) {
              srcSelect.value = currentVal;
            } else {
              srcSelect.value = sources[0].id;
            }
          }
        }
      } catch (e) {
        console.error("Error loading marketplace sources:", e);
      }
    }
    async function loadSkillMarketplaceSources() {
      const srcSelect = document.getElementById("skill-market-source-select");
      if (!srcSelect) return;
      try {
        const res = await fetch("/api/marketplace/skills/sources");
        if (res.ok) {
          const sources = await res.json();
          if (sources && sources.length > 0) {
            const currentVal = srcSelect.value;
            srcSelect.innerHTML = "";
            sources.forEach(s => {
              const opt = document.createElement("option");
              opt.value = s.id;
              opt.innerText = s.name;
              srcSelect.appendChild(opt);
            });
            if (currentVal && sources.some(s => s.id === currentVal)) {
              srcSelect.value = currentVal;
            } else {
              srcSelect.value = sources[0].id;
            }
          }
        }
      } catch (e) {
        console.error("Error loading skill marketplace sources:", e);
      }
    }
    function switchMarketplaceTab(tab) {
      const tabTalentBtn = document.getElementById("tab-market-talent");
      const tabSkillBtn = document.getElementById("tab-market-skill");
      const contentTalent = document.getElementById("market-tab-content-talent");
      const contentSkill = document.getElementById("market-tab-content-skill");
      if (!tabTalentBtn || !tabSkillBtn || !contentTalent || !contentSkill) return;
      const activeClass = "py-1 px-2 rounded-lg text-[11px] font-bold font-mono transition text-center cursor-pointer shadow-xs bg-[var(--card)] text-[var(--foreground)] border border-[var(--border)]";
      const inactiveClass = "py-1 px-2 rounded-lg text-[11px] font-medium font-mono transition text-center cursor-pointer bg-transparent text-[var(--muted-foreground)] hover:text-[var(--foreground)] border border-transparent";
      tabTalentBtn.style.cssText = "";
      tabSkillBtn.style.cssText = "";
      if (tab === "talent") {
        tabTalentBtn.className = activeClass;
        tabSkillBtn.className = inactiveClass;
        contentTalent.classList.remove("hidden");
        contentSkill.classList.add("hidden");
        if (!marketplaceTemplatesList || marketplaceTemplatesList.length === 0) {
          loadMarketplaceTemplates();
        }
      } else {
        tabSkillBtn.className = activeClass;
        tabTalentBtn.className = inactiveClass;
        contentSkill.classList.remove("hidden");
        contentTalent.classList.add("hidden");
        loadSkillMarketplaceItems();
      }
      if (window.lucide) lucide.createIcons();
    }
    async function initTalentMarketplace() {
      await loadMarketplaceSources();
      await loadSkillMarketplaceSources();
      await loadMarketplaceTemplates();
      await loadSkillMarketplaceItems();
    }
    async function loadMarketplaceTemplates(search = "") {
      const srcSelect = document.getElementById("market-source-select");
      const tplSelect = document.getElementById("market-template-select");
      const countBadge = document.getElementById("market-templates-available-count");
      const topBadge = document.getElementById("marketplace-count-badge");
      if (!srcSelect || !tplSelect) return;
      const source = srcSelect.value || "fabric";
      try {
        let url = `/api/marketplace/templates?source=${source}`;
        if (search) url += `&search=${encodeURIComponent(search)}`;
        
        const res = await fetch(url);
        if (res.ok) {
          marketplaceTemplatesList = await res.json();
          tplSelect.innerHTML = "";
          
          if (countBadge) countBadge.innerText = `${marketplaceTemplatesList.length} Vorlagen`;
          if (topBadge && source === "fabric") topBadge.innerText = `${marketplaceTemplatesList.length} Fabric Patterns`;
          else if (topBadge) topBadge.innerText = `${marketplaceTemplatesList.length} Vorlagen`;
          if (marketplaceTemplatesList.length === 0) {
            const opt = document.createElement("option");
            opt.value = "";
            opt.innerText = "Keine Vorlagen gefunden";
            tplSelect.appendChild(opt);
            document.getElementById("market-template-preview").value = "Keine passenden Vorlagen gefunden.";
            const catEl = document.getElementById("market-template-category-badge");
            if (catEl) catEl.innerText = "-";
            return;
          }
          marketplaceTemplatesList.forEach(t => {
            const opt = document.createElement("option");
            opt.value = t.id;
            opt.innerText = t.name;
            tplSelect.appendChild(opt);
          });
          // Wähle das erste Template und lade die Vorschau
          currentSelectedMarketplaceTemplateId = marketplaceTemplatesList[0].id;
          tplSelect.value = currentSelectedMarketplaceTemplateId;
          await loadSelectedTemplateDetail(source, currentSelectedMarketplaceTemplateId);
        }
      } catch (e) {
        console.error("Error loading marketplace templates:", e);
      }
    }
    async function loadSelectedTemplateDetail(source, templateId) {
      const previewArea = document.getElementById("market-template-preview");
      const catBadge = document.getElementById("market-template-category-badge");
      if (!previewArea || !templateId) return;
      previewArea.value = "Lade Vorlage aus Repository...";
      try {
        const res = await fetch(`/api/marketplace/template?source=${source}&id=${encodeURIComponent(templateId)}`);
        if (res.ok) {
          const detail = await res.json();
          previewArea.value = detail.system_prompt || detail.description || "Kein Inhalt vorhanden.";
          if (catBadge) catBadge.innerText = detail.category || "Allgemein";
        } else {
          previewArea.value = "Vorlage konnte nicht geladen werden.";
        }
      } catch (e) {
        console.error("Error loading template detail:", e);
        previewArea.value = `Fehler beim Laden: ${e.message}`;
      }
    }
    function onMarketplaceSourceSelectChange() {
      const searchInput = document.getElementById("market-search-input");
      if (searchInput) searchInput.value = "";
      loadMarketplaceTemplates();
    }
    function onMarketplaceSearchInput() {
      clearTimeout(marketSearchDebounceTimer);
      const query = (document.getElementById("market-search-input")?.value || "").trim();
      marketSearchDebounceTimer = setTimeout(() => {
        loadMarketplaceTemplates(query);
      }, 250);
    }
    async function onMarketplaceTemplateSelectChange() {
      const srcSelect = document.getElementById("market-source-select");
      const tplSelect = document.getElementById("market-template-select");
      if (!srcSelect || !tplSelect) return;
      const source = srcSelect.value;
      const templateId = tplSelect.value;
      currentSelectedMarketplaceTemplateId = templateId;
      await loadSelectedTemplateDetail(source, templateId);
    }
    async function recruitSelectedMarketplaceTemplate() {
      const srcSelect = document.getElementById("market-source-select");
      const tplSelect = document.getElementById("market-template-select");
      if (!srcSelect || !tplSelect || !tplSelect.value) {
        alert("Bitte wähle eine Vorlage aus dem Marktplatz aus.");
        return;
      }
      const source = srcSelect.value;
      const templateId = tplSelect.value;
      const templateObj = marketplaceTemplatesList.find(t => t.id === templateId);
      const templateName = templateObj ? templateObj.name : templateId;
      const payload = {
        source: source,
        template_id: templateId,
        name: templateName
      };
      try {
        const res = await fetch("/api/marketplace/recruit", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        if (res.ok) {
          const resData = await res.json();
          await loadHermesProfilesFromServer();
          setProfileTabFilter('all');
          currentSelectedProfileId = resData.profile.id;
          renderHermesProfilesList();
          selectProfileForEditor(resData.profile.id);
          alert(`✅ Rolle '${resData.profile.name}' (${resData.profile.id}) erfolgreich aus ${source} rekrutiert und in Hermes registriert!`);
        } else {
          alert("Fehler beim Rekrutieren der Vorlage.");
        }
      } catch (e) {
        console.error("Marketplace recruit error:", e);
        alert(`Verbindungsfehler: ${e.message}`);
      }
    }
    // --- SKILL-MARKTPLATZ LOGIC ---
    let skillMarketList = [];
    let currentSelectedSkillId = null;
    let skillMarketSearchDebounce = null;
    function switchMarketplaceSubTab(tab) {
      switchMarketplaceTab(tab);
    }
    async function loadSkillMarketplaceItems(search = "") {
      const srcSelect = document.getElementById("skill-market-source-select");
      const itemSelect = document.getElementById("skill-market-item-select");
      const countBadge = document.getElementById("skill-market-available-count");
      if (!srcSelect || !itemSelect) return;
      const source = srcSelect.value || "hermes_skills";
      try {
        let url = `/api/marketplace/skills?source=${encodeURIComponent(source)}`;
        if (search) url += `&search=${encodeURIComponent(search)}`;
        
        const res = await fetch(url);
        if (res.ok) {
          skillMarketList = await res.json();
          itemSelect.innerHTML = "";
          
          if (countBadge) countBadge.innerText = `${skillMarketList.length} Skills`;
          if (skillMarketList.length === 0) {
            const opt = document.createElement("option");
            opt.value = "";
            opt.innerText = "Keine Skills gefunden";
            itemSelect.appendChild(opt);
            document.getElementById("skill-market-preview").value = "Keine passenden Skills gefunden.";
            const catEl = document.getElementById("skill-market-category-badge");
            if (catEl) catEl.innerText = "-";
            return;
          }
          skillMarketList.forEach(s => {
            const opt = document.createElement("option");
            opt.value = s.id;
            opt.innerText = s.name || s.id;
            itemSelect.appendChild(opt);
          });
          currentSelectedSkillId = skillMarketList[0].id;
          itemSelect.value = currentSelectedSkillId;
          await loadSelectedSkillDetail(source, currentSelectedSkillId);
        }
      } catch (e) {
        console.error("Error loading skill marketplace:", e);
      }
    }
    async function loadSelectedSkillDetail(source, skillId) {
      const previewArea = document.getElementById("skill-market-preview");
      const catBadge = document.getElementById("skill-market-category-badge");
      if (!previewArea || !skillId) return;
      previewArea.value = "Lade Skill-Spezifikation...";
      try {
        const res = await fetch(`/api/marketplace/skill?source=${encodeURIComponent(source)}&id=${encodeURIComponent(skillId)}`);
        if (res.ok) {
          const detail = await res.json();
          previewArea.value = detail.code_preview || detail.description || "Keine Spezifikation verfügbar.";
          if (catBadge) catBadge.innerText = detail.category || "Skill";
        } else {
          previewArea.value = "Skill konnte nicht geladen werden.";
        }
      } catch (e) {
        console.error("Error loading skill detail:", e);
        previewArea.value = `Fehler beim Laden: ${e.message}`;
      }
    }
    function onSkillMarketSourceSelectChange() {
      const searchInput = document.getElementById("skill-market-search-input");
      if (searchInput) searchInput.value = "";
      loadSkillMarketplaceItems();
    }
    function onSkillMarketSearchInput() {
      clearTimeout(skillMarketSearchDebounce);
      const query = (document.getElementById("skill-market-search-input")?.value || "").trim();
      skillMarketSearchDebounce = setTimeout(() => {
        loadSkillMarketplaceItems(query);
      }, 250);
    }
    async function onSkillMarketItemSelectChange() {
      const srcSelect = document.getElementById("skill-market-source-select");
      const itemSelect = document.getElementById("skill-market-item-select");
      if (!srcSelect || !itemSelect) return;
      const source = srcSelect.value;
      const skillId = itemSelect.value;
      currentSelectedSkillId = skillId;
      await loadSelectedSkillDetail(source, skillId);
    }
    async function assignSelectedMarketplaceSkill() {
      if (!currentSelectedProfileId) {
        alert("Bitte wähle zuerst in der linken Spalte ein Agentenprofil aus.");
        return;
      }
      const srcSelect = document.getElementById("skill-market-source-select");
      const itemSelect = document.getElementById("skill-market-item-select");
      if (!srcSelect || !itemSelect || !itemSelect.value) {
        alert("Bitte wähle einen Skill aus dem Marktplatz aus.");
        return;
      }
      const skillId = itemSelect.value;
      const skillObj = (skillMarketList && skillMarketList.length > 0) ? skillMarketList.find(s => s.id === skillId) : null;
      const skillName = skillObj ? skillObj.name : skillId;
      try {
        const res = await fetch("/api/marketplace/skills/assign", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            profile_id: currentSelectedProfileId,
            skill_name: skillId,
            skill_id: skillId
          })
        });
        if (res.ok) {
          const prof = hermesProfilesData.find(p => p.id === currentSelectedProfileId);
          if (prof) {
            if (!prof.skills) prof.skills = [];
            if (!prof.skills.includes(skillId)) {
              prof.skills.push(skillId);
            }
            renderActiveProfileSkillsTags(prof.skills);
            renderHermesProfilesList();
          }
          alert(`✅ Skill '${skillName}' (${skillId}) erfolgreich dem Profil '${currentSelectedProfileId}' zugewiesen!`);
        } else {
          alert("Fehler beim Zuweisen des Skills.");
        }
      } catch (e) {
        console.error("Skill assignment error:", e);
        alert(`Verbindungsfehler: ${e.message}`);
      }
    }
    // --- LOG POLING ---
    // --- LOG POLING ---
    let logEventSource = null;
    function startLogPolling() {
      if (logEventSource) {
        logEventSource.close();
      }
      
      const logDiv = document.getElementById("system-log-body");
      if (!logDiv) return;
      logDiv.innerHTML = "<div class='text-muted-custom italic text-center py-6'>Connecting to live telemetry logs...</div>";
      logEventSource = new EventSource("/api/v1/telemetry/logs");
      
      logEventSource.onmessage = (event) => {
        try {
          const logData = JSON.parse(event.data);
          const time = new Date(logData.timestamp).toLocaleTimeString();
          const msg = logData.message;
          let msgColorClass = "text-muted-custom";
          let nameColorClass = "text-green-500";
          
          if (msg.includes("🔧") || msg.includes("Tool") || msg.includes("mcp__")) {
            msgColorClass = "text-yellow-500 font-medium";
            nameColorClass = "text-yellow-600 font-semibold";
          } else if (msg.includes("❌") || msg.includes("failed") || msg.includes("Failed")) {
            msgColorClass = "text-red-500 font-medium";
            nameColorClass = "text-red-600 font-semibold";
          } else if (msg.includes("SYSTEM ONLINE")) {
            msgColorClass = "text-green-400 font-semibold";
            nameColorClass = "text-green-500 font-bold";
          } else if (msg.includes("Heartbeat")) {
            msgColorClass = "text-slate-500 text-[10px]";
            nameColorClass = "text-slate-600";
          }
          // S-04: Die Agenten-/Tool-Ausgabe wird NICHT als HTML interpretiert —
          // der Text geht ueber textContent in ein eigenes Element. Damit kann
          // kein Agent mehr Markup im Cockpit ausfuehren.
          // F-18: kein `innerHTML +=` (quadratisches Neuparsen des kompletten
          // Logs) und unbegrenztes DOM-Wachstum — alte Zeilen werden entfernt.
          const row = document.createElement("div");
          row.className = "flex gap-3";

          const timeEl = document.createElement("span");
          timeEl.className = "text-label-custom flex-shrink-0 font-mono";
          timeEl.textContent = time;

          const nameEl = document.createElement("span");
          nameEl.className = `${nameColorClass} font-mono flex-shrink-0 w-24 truncate`;
          nameEl.textContent = "System";

          const msgEl = document.createElement("span");
          msgEl.className = `${msgColorClass} flex-1 leading-relaxed`;
          msgEl.textContent = msg;

          row.appendChild(timeEl);
          row.appendChild(nameEl);
          row.appendChild(msgEl);

          if (logDiv.innerHTML.includes("Connecting to") || logDiv.innerHTML.includes("Heartbeat OK")) {
            logDiv.innerHTML = "";
          }
          logDiv.appendChild(row);

          // F-18: Log-Decke (200 Zeilen) — kein unbegrenztes DOM-Wachstum.
          const MAX_LOG_ROWS = 200;
          while (logDiv.childElementCount > MAX_LOG_ROWS) {
            logDiv.removeChild(logDiv.firstElementChild);
          }
          logDiv.scrollTop = logDiv.scrollHeight;
        } catch (e) {
          console.error("Error parsing log event:", e);
        }
      };
      logEventSource.onerror = (e) => {
        console.error("EventSource failed:", e);
      };
    }
    async function clearLogs() {
      const logDiv = document.getElementById("system-log-body");
      if (logDiv) logDiv.innerHTML = "";
    }
    // --- PRESET MANAGEMENT GLOBALS & FUNCTIONS ---
    let selectedPresetId = "";
    function renderPresetDropdown() {
      const select = document.getElementById("agent-preset-select");
      if (!select) return;
      select.innerHTML = "";
      
      agents.forEach(agent => {
        const opt = document.createElement("option");
        opt.value = agent.id;
        opt.innerText = agent.name;
        if (agent.id === selectedPresetId) {
          opt.selected = true;
        }
        select.appendChild(opt);
      });
      
      const optNew = document.createElement("option");
      optNew.value = "new_template";
      optNew.innerText = "➕ neue Vorlage...";
      select.appendChild(optNew);
      
      // Falls kein Preset ausgewählt ist, wähle das erste
      if (!selectedPresetId && agents.length > 0) {
        selectedPresetId = agents[0].id;
        select.value = selectedPresetId;
      }
    }
    async function handlePresetChange(value) {
      if (value === "new_template") {
        openCreateAgentModal();
        // Setze Auswahl zurück auf das vorher selektierte Preset
        const elPreset = document.getElementById("agent-preset-select");
        if (elPreset) elPreset.value = selectedPresetId;
      } else {
        selectedPresetId = value;
      }
    }
    function openEditPresetModal() {
      const agent = agents.find(a => a.id === selectedPresetId);
      if (!agent) {
        alert("Bitte wählen Sie zuerst ein gültiges Preset aus.");
        return;
      }
      if (typeof switchView === "function") switchView("agent-profiles");
      if (typeof selectAgentProfile === "function") selectAgentProfile(agent.id);
    }
    function openCreatePresetModal() {
      if (typeof switchView === "function") switchView("agent-profiles");
      if (typeof createNewAgentProfile === "function") createNewAgentProfile();
    }
    function closePresetModal() {}
    async function submitPresetModal() {
      await saveAgentsToServer();
      await loadAgentsFromServer();
    }
    // --- AGENTS MANAGEMENT & DAW SIDEBAR CONTROL ---
    let selectedSidebarPresetId = "";
    const SYSTEM_INTERNAL_IDS = ["agent-os-container", "agent-os-ui", "agent-os", "agent_os", "agent_os_ui", "agent_os_container"];
    async function loadServicesFromServer() {
      try {
        const res = await fetch("/api/v1/services");
        if (res.ok) {
          servicesList = await res.json();
          renderSidebarPresetsSelect();
          populateCreateAgentTemplatesAndContainers();
        }
      } catch (e) {
        console.error("Error loading services:", e);
      }
    }
    async function loadAgentsFromServer() {
      try {
        loadServicesFromServer();
        const res = await fetch("/api/agents");
        const loadedAgents = await res.json();
        agents = loadedAgents.filter(a => !SYSTEM_INTERNAL_IDS.includes((a.id || '').toLowerCase()));
        
        // Sicherstellen, dass standardmäßig Rollen zugewiesen sind
        agents.forEach(a => {
          if (!a.role) a.role = "Researcher";
        });
        
        renderAgentsSidebar();
        renderMasterChatAgentTabs();
        renderAgentRegistryTable();
        updateStats();
        renderSidebarPresetsSelect();
        populateBoardroomChairmanSelect();
        loadBoardroomFrameworks();
      } catch (e) { console.error("Error loading agents:", e); }
    }
    async function saveAgentsToServer() {
      await fetch("/api/agents", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(agents)
      });
      updateStats();
      renderMasterChatAgentTabs();
    }
    async function addNewAgent() {
      const agentId = `A-0${agents.length + 1}`;
      agents.push({
        id: agentId,
        name: `Agent ${agents.length + 1}`,
        model: "free-forever",
        role: "Researcher",
        prompt: "Du bist ein Deep-Research-Agent. Deine Aufgabe ist es, komplexe Themen gründlich zu recherchieren, Fakten zu strukturieren und detaillierte Zusammenfassungen zu erstellen. Nutze Tools, um Informationen aus dem Workspace zu sammeln. Belege alle Aussagen mit präzisen Quellennachweisen aus dem Workspace.",
        active: true
      });
      await saveAgentsToServer();
      renderAgentsSidebar();
      renderAgentRegistryTable();
      renderSidebarPresetsSelect();
      renderMasterChatAgentTabs();
    }
    async function deleteAgent(id) {
      agents = agents.filter(a => a.id !== id);
      await saveAgentsToServer();
      renderAgentsSidebar();
      renderAgentRegistryTable();
      renderSidebarPresetsSelect();
      renderMasterChatAgentTabs();
    }
    async function toggleAgentActive(id) {
      const agent = agents.find(a => a.id === id);
      if (agent) {
        agent.active = !agent.active;
        await saveAgentsToServer();
        renderAgentsSidebar();
        renderAgentRegistryTable();
        renderMasterChatAgentTabs();
      }
    }
    async function restartAgent(name) {
      await fetch("/api/operations/kanban/reset-zombies", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ agent_id: name })
      }).catch(() => {});
      alert(`${name} wurde neu gestartet.`);
    }
    function updateAgentField(id, field, value) {
      const agent = agents.find(a => a.id === id);
      if (agent) {
        agent[field] = value;
        saveAgentsToServer();
        if (field === 'name') {
          renderAgentsSidebar();
          renderAgentRegistryTable();
          renderSidebarPresetsSelect();
        }
        if (field === 'model') {
          const displayModel = (agent.model && !agent.model.includes('/')) ? agent.model : "free-forever";
          injectContainerConfig(agent.id, displayModel, agent.prompt || "");
        }
      }
    }
    async function updateStats() {
      if (document.hidden) return;
      try {
        const res = await fetch("/api/v1/telemetry/dashboard");
        if (!res.ok) return;
        const data = await res.json();
        
        const tasks = data.running_tasks || [];
        const runningTasks = tasks.filter(t => t.status === "in_progress");
        
        const activeCount = runningTasks.length;
        const statActiveEl = document.getElementById("stat-active-agents");
        if (statActiveEl) statActiveEl.innerText = activeCount;
        
        const footerCountEl = document.getElementById("footer-agent-count");
        if (footerCountEl) footerCountEl.innerText = `${activeCount} agents active`;
        
        const tasksRunningEl = document.getElementById("stat-tasks-running");
        if (tasksRunningEl) tasksRunningEl.innerText = tasks.length;
        
        const avgUptimeEl = document.getElementById("stat-avg-uptime");
        if (avgUptimeEl) {
          if (data.average_uptime !== undefined && data.average_uptime !== null) {
            avgUptimeEl.innerText = `${data.average_uptime}s`;
          } else if (data.avg_uptime !== undefined && data.avg_uptime !== null) {
            avgUptimeEl.innerText = `${data.avg_uptime}s`;
          } else if (data.uptime !== undefined && data.uptime !== null) {
            avgUptimeEl.innerText = `${data.uptime}`;
          } else {
            avgUptimeEl.innerText = "99.9%";
          }
        }
      } catch (e) {
        console.error("Error updating stats:", e);
      }
    }
    function renderSidebarPresetsSelect() {
      const select = document.getElementById("agent-presets-sidebar-select");
      if (!select) return;
      select.innerHTML = '<option value="" disabled selected>Presets...</option>';
      
      const SYSTEM_INTERNAL_IDS = ["agent-os-container", "agent-os-ui", "agent-os", "agent_os", "agent_os_ui", "agent_os_container"];
      servicesList.forEach(service => {
        if (!SYSTEM_INTERNAL_IDS.includes((service.id || '').toLowerCase())) {
          const opt = document.createElement("option");
          opt.value = service.id;
          opt.innerText = service.name;
          select.appendChild(opt);
        }
      });
    }
    const FRAMEWORK_SLOT_DEFAULTS = {
    "CLEAR-Model": [
        {
            "role_name": "Collaborative Alignment (Team)",
            "default_profile": "agile_scrum_master"
        },
        {
            "role_name": "Limited & Emotional Scope",
            "default_profile": "personal_life_strategist"
        },
        {
            "role_name": "Appreciable Milestones",
            "default_profile": "product_requirements_engineer"
        },
        {
            "role_name": "Refinable Delivery (Tech)",
            "default_profile": "senior_fullstack_engineer"
        }
    ],
    "CREATE-Framework": [
        {
            "role_name": "Cue & Reaction (UX/Funnel)",
            "default_profile": "gtm_launch_strategist"
        },
        {
            "role_name": "Evaluation & Ability (Offer)",
            "default_profile": "pricing_discount_governor"
        },
        {
            "role_name": "Timing & Execution (Ops)",
            "default_profile": "agile_scrum_master"
        }
    ],
    "Design Sprint (GV / Jake Knapp)": [
        {
            "role_name": "Map & Decide (Product)",
            "default_profile": "product_requirements_engineer"
        },
        {
            "role_name": "Sketch & Prototype (UX)",
            "default_profile": "brand_uiux_director"
        },
        {
            "role_name": "Tech Validation (Fullstack)",
            "default_profile": "senior_fullstack_engineer"
        },
        {
            "role_name": "Customer Feedback (Retention)",
            "default_profile": "customer_retention_specialist"
        }
    ],
    "Double Diamond (Design Council)": [
        {
            "role_name": "Discover (Research & Market)",
            "default_profile": "competitive_intelligence_scout"
        },
        {
            "role_name": "Define (Requirements & Spec)",
            "default_profile": "product_requirements_engineer"
        },
        {
            "role_name": "Develop (System Architecture)",
            "default_profile": "enterprise_solutions_architect"
        },
        {
            "role_name": "Deliver (Fullstack Engineer)",
            "default_profile": "senior_fullstack_engineer"
        }
    ],
    "Lean Startup (Eric Ries)": [
        {
            "role_name": "Build (MVP Architect)",
            "default_profile": "enterprise_solutions_architect"
        },
        {
            "role_name": "Measure (Growth & Metrics)",
            "default_profile": "growth_hacker_lead"
        },
        {
            "role_name": "Learn / Pivot (CEO Strategy)",
            "default_profile": "executive_decision_architect"
        }
    ],
    "OKRs (Objectives and Key Results)": [
        {
            "role_name": "Objective Align (CEO)",
            "default_profile": "executive_decision_architect"
        },
        {
            "role_name": "Key Results Metrics (FinOps)",
            "default_profile": "finops_cost_optimizer"
        },
        {
            "role_name": "Sprint Execution (Scrum Master)",
            "default_profile": "agile_scrum_master"
        }
    ],
    "STEEPLE / PESTEL": [
        {
            "role_name": "Social & Cultural (HR / Org)",
            "default_profile": "labor_law_hr_governance"
        },
        {
            "role_name": "Technological (System Architect)",
            "default_profile": "system_architect_orchestrator"
        },
        {
            "role_name": "Economic & Market (Finance)",
            "default_profile": "arbitrage_market_analyst"
        },
        {
            "role_name": "Environmental (ESG Efficiency)",
            "default_profile": "esg_kfw_efficiency_auditor"
        },
        {
            "role_name": "Political & Legal (Jurist)",
            "default_profile": "commercial_jurist_contracts"
        }
    ],
    "Steffi Kieffer Boardroom": [
        {
            "role_name": "Skeptiker & Risikoprüfer",
            "default_profile": "red_team_challenger"
        },
        {
            "role_name": "Innovator & Stratege",
            "default_profile": "executive_decision_architect"
        },
        {
            "role_name": "Pragmatiker & Implementierer",
            "default_profile": "enterprise_solutions_architect"
        }
    ],
    "5-Why-Methode": [
        {
            "role_name": "Symptom & Trigger Analyst",
            "default_profile": "crisis_escalation_lead"
        },
        {
            "role_name": "Root Cause Technical Auditor",
            "default_profile": "database_performance_tuner"
        },
        {
            "role_name": "Preventive Solution Engineer",
            "default_profile": "senior_fullstack_engineer"
        }
    ],
    "Cynefin-Framework (Dave Snowden)": [
        {
            "role_name": "Clear / Complicated (Engineering)",
            "default_profile": "system_architect_orchestrator"
        },
        {
            "role_name": "Complex / Probe (Innovation)",
            "default_profile": "enterprise_solutions_architect"
        },
        {
            "role_name": "Chaotic / Act (Crisis Lead)",
            "default_profile": "crisis_escalation_lead"
        }
    ],
    "First Principles Thinking": [
        {
            "role_name": "Grundannahmen-Dekonstrukteur",
            "default_profile": "red_team_challenger"
        },
        {
            "role_name": "Fundamentale Physik & Code",
            "default_profile": "system_architect_orchestrator"
        },
        {
            "role_name": "Synthese & Re-Design",
            "default_profile": "executive_decision_architect"
        }
    ],
    "Ishikawa-Diagramm (6M)": [
        {
            "role_name": "Mensch & Führung (HR)",
            "default_profile": "labor_law_hr_governance"
        },
        {
            "role_name": "Maschine & Software (DevOps)",
            "default_profile": "devops_cloud_sec_specialist"
        },
        {
            "role_name": "Methode & Prozesse (n8n Arch.)",
            "default_profile": "n8n_process_architect"
        },
        {
            "role_name": "Material & Daten (Database)",
            "default_profile": "database_performance_tuner"
        },
        {
            "role_name": "Messung & Metriken (FinOps)",
            "default_profile": "finops_cost_optimizer"
        },
        {
            "role_name": "Mitwelt & Compliance (Auditor)",
            "default_profile": "compliance_gdpr_auditor"
        }
    ],
    "Porter's Five Forces": [
        {
            "role_name": "Branchenwettbewerb (Marktforscher)",
            "default_profile": "competitive_intelligence_scout"
        },
        {
            "role_name": "Verhandlungsmacht Lieferanten",
            "default_profile": "vendor_contract_negotiator"
        },
        {
            "role_name": "Verhandlungsmacht Kunden & Churn",
            "default_profile": "customer_retention_specialist"
        },
        {
            "role_name": "Bedrohung durch Substitute (AI)",
            "default_profile": "ai_governance_officer"
        }
    ],
    "SWOT-Analyse": [
        {
            "role_name": "Stärken (Interne Kernkompetenzen)",
            "default_profile": "enterprise_solutions_architect"
        },
        {
            "role_name": "Schwächen (Tech-Debt & Bottlenecks)",
            "default_profile": "database_performance_tuner"
        },
        {
            "role_name": "Chancen (Wachstum & Neue Märkte)",
            "default_profile": "growth_hacker_lead"
        },
        {
            "role_name": "Risiken (Recht, Governance & IT)",
            "default_profile": "liability_risk_analyst"
        }
    ],
    "DMAIC (Six Sigma)": [
        {
            "role_name": "Define & Measure (Metriken & Daten)",
            "default_profile": "finops_cost_optimizer"
        },
        {
            "role_name": "Analyze & Root Cause (DB & Perf)",
            "default_profile": "database_performance_tuner"
        },
        {
            "role_name": "Improve & Automate (n8n Architect)",
            "default_profile": "n8n_process_architect"
        },
        {
            "role_name": "Control & Security (DevOps Sec)",
            "default_profile": "devops_cloud_sec_specialist"
        }
    ],
    "PDCA-Zyklus (Demingkreis)": [
        {
            "role_name": "Plan (Product Requirements)",
            "default_profile": "product_requirements_engineer"
        },
        {
            "role_name": "Do (Fullstack Engineering)",
            "default_profile": "senior_fullstack_engineer"
        },
        {
            "role_name": "Check (Compliance & Quality)",
            "default_profile": "compliance_gdpr_auditor"
        },
        {
            "role_name": "Act / Scale (DevOps Lead)",
            "default_profile": "devops_cloud_sec_specialist"
        }
    ],
    "Theory of Constraints (TOC)": [
        {
            "role_name": "Engpass-Identifizierer (DB/DBA)",
            "default_profile": "database_performance_tuner"
        },
        {
            "role_name": "Ausbeutung & Unterordnung (Ops)",
            "default_profile": "logistics_supply_chain_manager"
        },
        {
            "role_name": "Kapazitätserweiterung (Cloud Arch)",
            "default_profile": "system_architect_orchestrator"
        }
    ],
    "Eisenhower-Matrix": [
        {
            "role_name": "Dringend & Wichtig (Crisis Lead)",
            "default_profile": "crisis_escalation_lead"
        },
        {
            "role_name": "Wichtig, nicht dringend (Architect)",
            "default_profile": "enterprise_solutions_architect"
        },
        {
            "role_name": "Delegieren (n8n Automation)",
            "default_profile": "n8n_process_architect"
        },
        {
            "role_name": "Eliminieren (Kosten & FinOps)",
            "default_profile": "finops_cost_optimizer"
        }
    ],
    "Kano-Modell": [
        {
            "role_name": "Basis-Merkmale (Security & Core)",
            "default_profile": "devops_cloud_sec_specialist"
        },
        {
            "role_name": "Leistungs-Merkmale (Fullstack)",
            "default_profile": "senior_fullstack_engineer"
        },
        {
            "role_name": "Begeisterungs-Merkmale (UI/UX)",
            "default_profile": "brand_uiux_director"
        }
    ],
    "Kotter 8-Stufen-Modell": [
        {
            "role_name": "Dringlichkeit & Vision (CEO)",
            "default_profile": "executive_decision_architect"
        },
        {
            "role_name": "Führungskoalition (CHRO)",
            "default_profile": "labor_law_hr_governance"
        },
        {
            "role_name": "Kommunikation & Quick Wins",
            "default_profile": "speechwriter_keynote_designer"
        },
        {
            "role_name": "Verankerung in Kultur (Org)",
            "default_profile": "agile_scrum_master"
        }
    ],
    "McKinsey 7S": [
        {
            "role_name": "Strategy & Shared Values (CEO)",
            "default_profile": "executive_decision_architect"
        },
        {
            "role_name": "Structure & Systems (Cloud Arch)",
            "default_profile": "system_architect_orchestrator"
        },
        {
            "role_name": "Staff & Skills (CHRO Governance)",
            "default_profile": "labor_law_hr_governance"
        },
        {
            "role_name": "Style & Operations (Scrum Master)",
            "default_profile": "agile_scrum_master"
        }
    ],
    "NABC-Methode": [
        {
            "role_name": "Need (Marktbedarf & Schmerzpunkt)",
            "default_profile": "b2b_outreach_specialist"
        },
        {
            "role_name": "Approach (Technische Lösung)",
            "default_profile": "enterprise_solutions_architect"
        },
        {
            "role_name": "Benefits per Cost (FinOps Lead)",
            "default_profile": "finops_cost_optimizer"
        },
        {
            "role_name": "Competition (Markt-Scout)",
            "default_profile": "competitive_intelligence_scout"
        }
    ],
    "RICE-Priorisierung": [
        {
            "role_name": "Reach & Impact (Product Manager)",
            "default_profile": "product_requirements_engineer"
        },
        {
            "role_name": "Confidence (Data & Research)",
            "default_profile": "lead_enrichment_analyst"
        },
        {
            "role_name": "Effort Estimation (Fullstack)",
            "default_profile": "senior_fullstack_engineer"
        },
        {
            "role_name": "Finanzielle Priorität (FinOps)",
            "default_profile": "finops_cost_optimizer"
        }
    ],
    "Make-or-Buy / TCO-Scoring": [
        {
            "role_name": "TCO & Cloud-Kosten (FinOps)",
            "default_profile": "finops_cost_optimizer"
        },
        {
            "role_name": "Build Machbarkeit (Fullstack)",
            "default_profile": "senior_fullstack_engineer"
        },
        {
            "role_name": "Vendor & Lizenzprüfung (Einkauf)",
            "default_profile": "vendor_contract_negotiator"
        },
        {
            "role_name": "Compliance & IP Rights (Jurist)",
            "default_profile": "commercial_jurist_contracts"
        }
    ],
    "Ladder of Inference (Chris Argyris)": [
        {
            "role_name": "Reine Daten & Fakten (Analyst)",
            "default_profile": "lead_enrichment_analyst"
        },
        {
            "role_name": "Interpretations-Prüfer (Red Team)",
            "default_profile": "red_team_challenger"
        },
        {
            "role_name": "Handlungs-Validierung (CEO)",
            "default_profile": "executive_decision_architect"
        }
    ],
    "Pre-Mortem Analyse (Gary Klein)": [
        {
            "role_name": "Todesursachen-Analyst (Skeptiker)",
            "default_profile": "red_team_challenger"
        },
        {
            "role_name": "Haftungs- & Risikoanalyst",
            "default_profile": "liability_risk_analyst"
        },
        {
            "role_name": "Security & Ausfallschutz (DevOps)",
            "default_profile": "devops_cloud_sec_specialist"
        },
        {
            "role_name": "Liquiditäts- & Kostenrisiko (FinOps)",
            "default_profile": "finops_cost_optimizer"
        }
    ],
    "Red Teaming / Adversarial Analysis": [
        {
            "role_name": "Red Team (Offensive / Angreifer)",
            "default_profile": "red_team_challenger"
        },
        {
            "role_name": "Blue Team (Defensive & Hardening)",
            "default_profile": "devops_cloud_sec_specialist"
        },
        {
            "role_name": "Compliance & AI Safety Gate",
            "default_profile": "ai_governance_officer"
        }
    ],
    "Six Thinking Hats (Edward de Bono)": [
        {
            "role_name": "⚪ Weißer Hut (Daten & Fakten)",
            "default_profile": "lead_enrichment_analyst"
        },
        {
            "role_name": "🔴 Roter Hut (Nutzer & Emotion)",
            "default_profile": "customer_retention_specialist"
        },
        {
            "role_name": "🖤 Schwarzer Hut (Risiken & Zweifel)",
            "default_profile": "red_team_challenger"
        },
        {
            "role_name": "🟡 Gelber Hut (Chancen & Mehrwert)",
            "default_profile": "growth_hacker_lead"
        },
        {
            "role_name": "🟢 Grüner Hut (Kreative Ideen)",
            "default_profile": "pitchdeck_offer_designer"
        },
        {
            "role_name": "🔵 Blauer Hut (Prozess & Steuerung)",
            "default_profile": "executive_decision_architect"
        }
    ],
    "Game-Theoretic Mechanism Design": [
        {
            "role_name": "Incentive Alignment (Verhandlung)",
            "default_profile": "negotiation_master"
        },
        {
            "role_name": "Preis- & Arbitrage-Strategie",
            "default_profile": "pricing_discount_governor"
        },
        {
            "role_name": "Adversarial Exploitation (Red Team)",
            "default_profile": "red_team_challenger"
        }
    ],
    "Causal Loop Diagrams (System Dynamics)": [
        {
            "role_name": "Verstärkende Schleifen (Growth)",
            "default_profile": "growth_hacker_lead"
        },
        {
            "role_name": "Balancierende Schleifen (Risk)",
            "default_profile": "liability_risk_analyst"
        },
        {
            "role_name": "System-Architektur (Orchestrator)",
            "default_profile": "system_architect_orchestrator"
        }
    ],
    "Iceberg Model (Systems Thinking)": [
        {
            "role_name": "Ereignisse (Symptome & Incidents)",
            "default_profile": "crisis_escalation_lead"
        },
        {
            "role_name": "Muster & Trends (Marktanalyst)",
            "default_profile": "competitive_intelligence_scout"
        },
        {
            "role_name": "Systemstrukturen (Infrastruktur)",
            "default_profile": "enterprise_solutions_architect"
        },
        {
            "role_name": "Mentale Modelle (CEO Stratege)",
            "default_profile": "executive_decision_architect"
        }
    ],
    "Second-Order Thinking (Howard Marks)": [
        {
            "role_name": "Primäreffekt (Direkte Auswirkung)",
            "default_profile": "product_requirements_engineer"
        },
        {
            "role_name": "Sekundäreffekt (Folgekosten/Debt)",
            "default_profile": "finops_cost_optimizer"
        },
        {
            "role_name": "Tertiäreffekt (Systemreaktion/Markt)",
            "default_profile": "arbitrage_market_analyst"
        }
    ],
    "Wardley Mapping": [
        {
            "role_name": "Genesis / Custom (Innovation)",
            "default_profile": "enterprise_solutions_architect"
        },
        {
            "role_name": "Product / Rental (Software Eng)",
            "default_profile": "senior_fullstack_engineer"
        },
        {
            "role_name": "Commodity / Utility (Cloud Ops)",
            "default_profile": "devops_cloud_sec_specialist"
        },
        {
            "role_name": "Wertstrom & Value Chain (CEO)",
            "default_profile": "executive_decision_architect"
        }
    ],
    "Antifragilitäts-Analyse (Nassim Taleb)": [
        {
            "role_name": "Fragilitäts-Tester (Belastung)",
            "default_profile": "database_performance_tuner"
        },
        {
            "role_name": "Robustheits-Auditor (Security)",
            "default_profile": "devops_cloud_sec_specialist"
        },
        {
            "role_name": "Antifragiler Hebel (Growth & AI)",
            "default_profile": "executive_decision_architect"
        }
    ],
    "FMEA (Failure Mode and Effects Analysis)": [
        {
            "role_name": "Fehlerarten (Severity & Impact)",
            "default_profile": "crisis_escalation_lead"
        },
        {
            "role_name": "Auftretens-Wahrscheinlichkeit",
            "default_profile": "liability_risk_analyst"
        },
        {
            "role_name": "Entdeckungs-Wahrscheinlichkeit (QA)",
            "default_profile": "devops_cloud_sec_specialist"
        },
        {
            "role_name": "Präventiv-Architektur (Fullstack)",
            "default_profile": "senior_fullstack_engineer"
        }
    ],
    "OODA-Loop (John Boyd)": [
        {
            "role_name": "Observe (Markt-Radar & Feed)",
            "default_profile": "competitive_intelligence_scout"
        },
        {
            "role_name": "Orient (Filter & KI-Compliance)",
            "default_profile": "ai_governance_officer"
        },
        {
            "role_name": "Decide (CEO Leitstelle)",
            "default_profile": "executive_decision_architect"
        },
        {
            "role_name": "Act (n8n & Automatisierung)",
            "default_profile": "n8n_process_architect"
        }
    ],
    "Scenario Planning (Shell-Methode)": [
        {
            "role_name": "Best-Case / Bull-Market (Growth)",
            "default_profile": "growth_hacker_lead"
        },
        {
            "role_name": "Worst-Case / Krise (Escalation)",
            "default_profile": "crisis_escalation_lead"
        },
        {
            "role_name": "Regulatory & Legal Shifts (Jurist)",
            "default_profile": "commercial_jurist_contracts"
        },
        {
            "role_name": "Finanzielle Stresstests (FinOps)",
            "default_profile": "finops_cost_optimizer"
        }
    ]
};
    
    
    // --- BOARDROOM ATTACHMENT PIPELINE ---
    let currentBoardroomAttachments = [];

    function handleBoardroomFileSelected(e) {
      const files = e.target.files;
      if (!files || !files.length) return;
      addBoardroomAttachmentFiles(files);
      e.target.value = "";
    }

    function addBoardroomAttachmentFiles(files) {
      if (!files || !files.length) return;
      const fileList = Array.from(files);
      const remaining = 5 - currentBoardroomAttachments.length;
      if (remaining <= 0) {
        alert("Maximal 5 Anhänge gleichzeitig erlaubt.");
        return;
      }
      const toAdd = fileList.slice(0, remaining);
      if (fileList.length > remaining) {
        alert(`Nur ${remaining} weitere Datei(en) hinzugefügt (Limit: 5).`);
      }
      toAdd.forEach(file => {
        currentBoardroomAttachments.push({
          file: file,
          name: file.name || "datei",
          size: (file.size / 1024).toFixed(1) + " KB",
          type: file.type || "application/octet-stream"
        });
      });
      renderBoardroomAttachments();
    }

    function removeBoardroomAttachment(idx) {
      if (typeof idx === "number") {
        currentBoardroomAttachments.splice(idx, 1);
      } else {
        currentBoardroomAttachments = [];
      }
      const fileInput = document.getElementById("boardroom-file-input");
      if (fileInput) fileInput.value = "";
      renderBoardroomAttachments();
    }

    function renderBoardroomAttachments() {
      const bar = document.getElementById("boardroom-attachment-bar");
      if (!bar) return;
      if (!currentBoardroomAttachments.length) {
        bar.classList.add("hidden");
        bar.innerHTML = "";
        return;
      }
      bar.classList.remove("hidden");
      bar.innerHTML = `
        <div class="flex items-center gap-1.5 flex-wrap flex-1 min-w-0">
          <span class="text-[9.5px] font-mono text-[var(--muted-foreground)] uppercase font-bold shrink-0">Anhänge (${currentBoardroomAttachments.length}/5):</span>
          ${currentBoardroomAttachments.map((att, idx) => `
            <div class="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-[var(--card)] border border-[var(--border)] text-[10px] font-mono text-[var(--foreground)] shadow-2xs">
              <i data-lucide="file" class="w-3 h-3 text-emerald-500 shrink-0"></i>
              <span class="truncate max-w-[120px] font-medium" title="${att.name}">${att.name}</span>
              <span class="text-[8.5px] text-[var(--muted-foreground)] font-normal">${att.size}</span>
              <button type="button" onclick="removeBoardroomAttachment(${idx})" class="text-[var(--muted-foreground)] hover:text-red-500 transition p-0.5 cursor-pointer" title="Entfernen">
                <i data-lucide="x" class="w-3 h-3"></i>
              </button>
            </div>
          `).join('')}
        </div>
      `;
      if (window.lucide) window.lucide.createIcons();
    }


    const BOARDROOM_PROVIDERS = [
      { id: "openrouter", name: "OpenRouter" },
      { id: "google", name: "Google AI" },
      { id: "openai", name: "OpenAI" },
      { id: "groq", name: "Groq" },
      { id: "omniroute", name: "OmniRoute" },
      { id: "nvidia", name: "NVIDIA NIM" }
    ];

    function getBoardroomProviderOptionsHtml(selectedProv) {
      let html = "";
      const current = (selectedProv || "openrouter").toLowerCase();
      BOARDROOM_PROVIDERS.forEach(p => {
        const isSel = (p.id === current) ? "selected" : "";
        html += `<option value="${p.id}" ${isSel}>${p.name}</option>`;
      });
      return html;
    }

    async function setupBoardroomSlotModelDropdown(modelSelect, provider, preferredModel) {
      if (!modelSelect) return;
      modelSelect.disabled = true;
      modelSelect.innerHTML = `<option value="">Lade Modelle für ${provider}...</option>`;
      if (typeof window.loadAgentTabModelPrices === 'function') {
        await window.loadAgentTabModelPrices();
      }
      let models = [];
      if (typeof window.loadLlmModelsForProvider === 'function') {
        models = await window.loadLlmModelsForProvider(provider);
      } else {
        models = ["deepseek/deepseek-chat", "openai/gpt-4o", "anthropic/claude-3.5-sonnet"];
      }
      modelSelect.disabled = false;
      if (typeof window.populateModelDropdown === 'function') {
        window.populateModelDropdown(modelSelect, models, preferredModel);
      } else {
        modelSelect.innerHTML = "";
        models.forEach(m => {
          const opt = document.createElement("option");
          opt.value = m;
          opt.textContent = m;
          if (m === preferredModel) opt.selected = true;
          modelSelect.appendChild(opt);
        });
      }
      updateBoardroomSlotCost(modelSelect);
      saveBoardroomStateToLocalStorage();
    }
    window.setupBoardroomSlotModelDropdown = setupBoardroomSlotModelDropdown;

    async function onBoardroomSlotProviderChanged(provSelect) {
      const row = provSelect.closest('.boardroom-slot-row');
      if (!row) return;
      const modelSelect = row.querySelector('.boardroom-slot-model-select');
      const provider = provSelect.value;
      await setupBoardroomSlotModelDropdown(modelSelect, provider, null);
    }
    window.onBoardroomSlotProviderChanged = onBoardroomSlotProviderChanged;

    function onBoardroomSlotModelChanged(modelSelect) {
      if (!modelSelect) return;
      if (modelSelect.value === "__CUSTOM__") {
        if (typeof window.handleCustomModelOption === 'function') {
          if (!window.handleCustomModelOption(modelSelect)) {
            return;
          }
        }
      }
      updateBoardroomSlotCost(modelSelect);
      saveBoardroomStateToLocalStorage();
    }
    window.onBoardroomSlotModelChanged = onBoardroomSlotModelChanged;

    function updateBoardroomSlotCost(modelSelect) {
      if (!modelSelect) return;
      const row = modelSelect.closest('.boardroom-slot-row');
      if (!row) return;
      const costEl = row.querySelector('.boardroom-slot-cost');
      if (!costEl) return;
      const model = modelSelect.value;
      let info = null;
      if (typeof findModelPriceInfo === 'function') {
        info = findModelPriceInfo(model);
      }
      if (info && info.p) {
        const pre = info.approx ? "≈ " : "";
        const fmtPrice = typeof formatPricePer1M === "function" ? formatPricePer1M : (v => (v || 0).toFixed(2));
        const inP = fmtPrice(info.p.prompt_1m);
        const outP = fmtPrice(info.p.completion_1m);
        costEl.innerHTML = `${pre}In: <span class="text-emerald-500 font-bold">$${inP}</span> | Out: <span class="text-amber-500 font-bold">$${outP}</span> <span class="text-slate-400 font-normal">/1M Tok</span>`;
        costEl.classList.remove("hidden");
        costEl.title = info.approx
          ? `Preis des passenden Modells (${info.matched}) — Input: $${inP} / Output: $${outP} pro 1M Tokens`
          : `Input: $${inP} / Output: $${outP} pro 1 Million Tokens`;
      } else if (model && model !== "__CUSTOM__") {
        costEl.innerHTML = `In: <span class="text-emerald-500 font-bold">$0.00</span> | Out: <span class="text-amber-500 font-bold">$0.00</span> <span class="text-slate-400 font-normal">/1M Tok</span>`;
        costEl.classList.remove("hidden");
      } else {
        costEl.classList.add("hidden");
      }
      saveBoardroomStateToLocalStorage();
    }
    window.updateBoardroomSlotCost = updateBoardroomSlotCost;

    const BOARDROOM_DEFAULT_MODELS = [
      { id: "", name: "⚡ Profil-Standard (Default)" },
      { id: "anthropic/claude-3.7-sonnet", name: "Claude 3.7 Sonnet (Anthropic)" },
      { id: "anthropic/claude-3.5-sonnet", name: "Claude 3.5 Sonnet (Anthropic)" },
      { id: "openai/gpt-4o", name: "GPT-4o (OpenAI)" },
      { id: "openai/gpt-4o-mini", name: "GPT-4o Mini (OpenAI)" },
      { id: "openai/o3-mini", name: "o3-mini Reasoning (OpenAI)" },
      { id: "deepseek/deepseek-v4.1-flash", name: "DeepSeek V4.1 Flash (84% Rabatt)" },
      { id: "deepseek/deepseek-chat", name: "DeepSeek V3 (DeepSeek Chat)" },
      { id: "deepseek/deepseek-r1", name: "DeepSeek R1 Reasoning" },
      { id: "google/gemini-2.5-pro", name: "Gemini 2.5 Pro (Google)" },
      { id: "google/gemini-2.5-flash", name: "Gemini 2.5 Flash (Google)" },
      { id: "meta-llama/llama-3.3-70b-instruct", name: "Llama 3.3 70B (Meta)" },
      { id: "qwen/qwen-2.5-coder-32b-instruct", name: "Qwen 2.5 Coder 32B" }
    ];

    function getBoardroomModelOptionsHtml(selectedModel) {
      let html = "";
      BOARDROOM_DEFAULT_MODELS.forEach(m => {
        const isSel = (m.id === (selectedModel || "")) ? "selected" : "";
        html += `<option value="${m.id}" ${isSel}>${m.name}</option>`;
      });
      return html;
    }

    function getRoleOptionsHtml(selectedProfileId) {
      const sourceList = (typeof hermesProfilesData !== 'undefined' && hermesProfilesData.length > 0)
        ? hermesProfilesData
        : (typeof roles !== 'undefined' && roles.length > 0 ? roles : []);
      if (sourceList.length === 0) {
        return `<option value="${selectedProfileId}" selected>${selectedProfileId}</option>`;
      }
      
      const categories = {};
      sourceList.forEach(r => {
        const cat = r.category || "Allgemein";
        if (!categories[cat]) categories[cat] = [];
        categories[cat].push(r);
      });
      let html = "";
      for (const [catName, rList] of Object.entries(categories)) {
        html += `<optgroup label="${catName}">`;
        rList.forEach(r => {
          const isSel = (r.id === selectedProfileId) ? "selected" : "";
          const displayName = r.person_name ? `${r.person_name} – ${r.name}` : r.name;
          html += `<option value="${r.id}" ${isSel}>${displayName}</option>`;
        });
        html += `</optgroup>`;
      }
      return html;
    }
    
    // --- BOARDROOM PERSISTENCE & RESET ---
    function saveBoardroomStateToLocalStorage() {
      const fwSelect = document.getElementById("boardroom-framework-select");
      const fwName = fwSelect ? fwSelect.value : "";
      if (!fwName) return;

      const chairSelect = document.getElementById("boardroom-chairman-select");
      const chairProv = document.getElementById("boardroom-chair-provider-select");
      const chairModel = document.getElementById("boardroom-chair-model-select");

      const slotRows = document.querySelectorAll("#boardroom-slots-list .boardroom-slot-row");
      const slots = Array.from(slotRows).map((el, idx) => {
        const roleInput = el.querySelector(".boardroom-slot-role-name");
        const profSelect = el.querySelector(".boardroom-slot-profile-select");
        const provSelect = el.querySelector(".boardroom-slot-provider-select");
        const modelSelect = el.querySelector(".boardroom-slot-model-select");
        return {
          role_name: roleInput ? roleInput.value : `Slot ${idx + 1}`,
          profile_id: profSelect ? profSelect.value : "senior_coder",
          provider: provSelect ? provSelect.value : "openrouter",
          model_id: modelSelect ? modelSelect.value : "deepseek/deepseek-chat"
        };
      });

      const state = {
        chairman_id: chairSelect ? chairSelect.value : "orchestrator",
        chairman_provider: chairProv ? chairProv.value : "openrouter",
        chairman_model: chairModel ? chairModel.value : "deepseek/deepseek-chat",
        slots: slots
      };

      try {
        localStorage.setItem("archon_boardroom_custom_" + fwName, JSON.stringify(state));
      } catch (e) {}
    }

    function resetCurrentBoardroomFramework() {
      const select = document.getElementById("boardroom-framework-select");
      if (!select) return;
      const fwName = select.value;
      try {
        localStorage.removeItem("archon_boardroom_custom_" + fwName);
      } catch (e) {}

      // Reset Chairman to factory default
      const chairSelect = document.getElementById("boardroom-chairman-select");
      const chairProv = document.getElementById("boardroom-chair-provider-select");
      const chairModel = document.getElementById("boardroom-chair-model-select");
      if (chairSelect) {
        const defaultOpt = Array.from(chairSelect.options).find(o => o.value === "hermes_default" || o.value === "orchestrator");
        if (defaultOpt) {
          chairSelect.value = defaultOpt.value;
        } else if (chairSelect.options.length > 0) {
          chairSelect.selectedIndex = 0;
        }
      }
      if (chairProv) chairProv.value = "openrouter";
      if (chairModel) chairModel.value = "deepseek/deepseek-chat";
      onBoardroomChairmanChange(false);

      renderBoardroomSlots(fwName, true);
      if (typeof showArchonToast === "function") {
        showArchonToast(`Framework '${fwName}' auf Ursprung zurückgesetzt.`, "success");
      }
    }

    function renderBoardroomSlots(frameworkName, forceDefault = false) {
      const container = document.getElementById("boardroom-slots-list");
      if (!container) return;
      container.innerHTML = "";

      // Ensure price list is loaded so cost pills render with real values
      if (typeof loadAgentTabModelPrices === 'function') {
        loadAgentTabModelPrices().then(() => {
          document.querySelectorAll('#boardroom-slots-list .boardroom-slot-model-select').forEach(sel => {
            updateBoardroomSlotCost(sel);
          });
          updateBoardroomChairmanCost();
        });
      }

      // Check if user has a saved custom setup for this framework
      if (!forceDefault) {
        try {
          const savedStr = localStorage.getItem("archon_boardroom_custom_" + frameworkName);
          if (savedStr) {
            const savedState = JSON.parse(savedStr);
            if (savedState && Array.isArray(savedState.slots) && savedState.slots.length > 0) {
              // Apply saved chairman
              const chairSelect = document.getElementById("boardroom-chairman-select");
              const chairProv = document.getElementById("boardroom-chair-provider-select");
              const chairModel = document.getElementById("boardroom-chair-model-select");
              if (chairSelect && savedState.chairman_id) chairSelect.value = savedState.chairman_id;
              if (chairProv && savedState.chairman_provider) chairProv.value = savedState.chairman_provider;
              const savedChairProv = (chairProv && chairProv.value) || savedState.chairman_provider || "openrouter";
              setupBoardroomChairmanModelDropdown(savedChairProv, savedState.chairman_model);

              savedState.slots.forEach((s, idx) => {
                addBoardroomSlotElement(s.role_name, s.profile_id, idx + 1, s.model_id, s.provider);
              });
              if (window.lucide) window.lucide.createIcons();
              return;
            }
          }
        } catch (e) {}
      }

      let slotsDef = null;
      for (const [key, val] of Object.entries(FRAMEWORK_SLOT_DEFAULTS)) {
        if (frameworkName && frameworkName.toLowerCase().includes(key.toLowerCase())) {
          slotsDef = val;
          break;
        }
      }
      if (!slotsDef) {
        slotsDef = [
          { role_name: "Skeptiker & Risikoprüfer", default_profile: "liability_risk_analyst" },
          { role_name: "Innovator & Stratege", default_profile: "executive_decision_architect" },
          { role_name: "Pragmatiker & Implementierer", default_profile: "enterprise_solutions_architect" }
        ];
      }
      slotsDef.forEach((slot, index) => {
        addBoardroomSlotElement(slot.role_name, slot.default_profile, index + 1);
      });
      if (window.lucide) window.lucide.createIcons();
    }
    function updateBoardroomSlotCard(selectEl) {
      const row = selectEl.closest('.boardroom-slot-row');
      if (!row) return;
      const img = row.querySelector('.boardroom-slot-avatar');
      const descEl = row.querySelector('.boardroom-slot-desc');
      const catEl = row.querySelector('.boardroom-slot-cat');
      const personEl = row.querySelector('.boardroom-slot-person');
      const profId = selectEl.value;
      
      const foundProf = (typeof hermesProfilesData !== 'undefined' && hermesProfilesData) 
        ? hermesProfilesData.find(p => p.id === profId) 
        : null;
      let avatarUrl = '/static/avatars/avatar_001.jpg';
      if (typeof getProfileAvatarUrl === 'function') {
        avatarUrl = getProfileAvatarUrl(foundProf || { id: profId });
      }
      if (img) img.src = avatarUrl;
      if (descEl) descEl.innerText = foundProf ? (foundProf.description || '') : 'Fach-Agent für diese Debatten-Position.';
      if (catEl) catEl.innerText = foundProf ? (foundProf.category || '') : '';
      if (personEl) personEl.innerText = foundProf ? (foundProf.person_name ? foundProf.person_name.split(' ')[0] : '') : '';
      const provSelect = row.querySelector('.boardroom-slot-provider-select');
      const modelSelect = row.querySelector('.boardroom-slot-model-select');
      if (foundProf) {
        if (provSelect && foundProf.provider) provSelect.value = foundProf.provider;
        const curProv = provSelect ? provSelect.value : (foundProf.provider || "openrouter");
        setupBoardroomSlotModelDropdown(modelSelect, curProv, foundProf.model);
      }
      saveBoardroomStateToLocalStorage();
    }
    window.updateBoardroomSlotCard = updateBoardroomSlotCard;

    async function setupBoardroomChairmanModelDropdown(provider, preferredModel) {
      const modelSelect = document.getElementById("boardroom-chair-model-select");
      if (!modelSelect) return;
      modelSelect.disabled = true;
      modelSelect.innerHTML = `<option value="">Lade Modelle für ${provider}...</option>`;
      if (typeof window.loadAgentTabModelPrices === 'function') {
        await window.loadAgentTabModelPrices();
      }
      let models = [];
      if (typeof window.loadLlmModelsForProvider === 'function') {
        models = await window.loadLlmModelsForProvider(provider);
      } else {
        models = ["deepseek/deepseek-chat", "openai/gpt-4o", "anthropic/claude-3.5-sonnet"];
      }
      modelSelect.disabled = false;
      if (typeof window.populateModelDropdown === 'function') {
        window.populateModelDropdown(modelSelect, models, preferredModel);
      } else {
        modelSelect.innerHTML = "";
        models.forEach(m => {
          const opt = document.createElement("option");
          opt.value = m;
          opt.textContent = m;
          if (m === preferredModel) opt.selected = true;
          modelSelect.appendChild(opt);
        });
      }
      updateBoardroomChairmanCost();
      saveBoardroomStateToLocalStorage();
    }
    window.setupBoardroomChairmanModelDropdown = setupBoardroomChairmanModelDropdown;

    async function onBoardroomChairmanProviderChanged(provSelect) {
      const provider = provSelect.value;
      await setupBoardroomChairmanModelDropdown(provider, null);
    }
    window.onBoardroomChairmanProviderChanged = onBoardroomChairmanProviderChanged;

    function onBoardroomChairmanModelChanged(modelSelect) {
      if (!modelSelect) modelSelect = document.getElementById("boardroom-chair-model-select");
      if (!modelSelect) return;
      if (modelSelect.value === "__CUSTOM__") {
        if (typeof window.handleCustomModelOption === 'function') {
          if (!window.handleCustomModelOption(modelSelect)) {
            return;
          }
        }
      }
      updateBoardroomChairmanCost();
      saveBoardroomStateToLocalStorage();
    }
    window.onBoardroomChairmanModelChanged = onBoardroomChairmanModelChanged;

    function updateBoardroomChairmanCost() {
      const modelSelect = document.getElementById("boardroom-chair-model-select");
      const costEl = document.getElementById("boardroom-chair-cost");
      if (!modelSelect || !costEl) return;
      const model = modelSelect.value;
      let info = null;
      if (typeof findModelPriceInfo === 'function') {
        info = findModelPriceInfo(model);
      }
      if (info && info.p) {
        const pre = info.approx ? "≈ " : "";
        const fmtPrice = typeof formatPricePer1M === "function" ? formatPricePer1M : (v => (v || 0).toFixed(2));
        const inP = fmtPrice(info.p.prompt_1m);
        const outP = fmtPrice(info.p.completion_1m);
        costEl.innerHTML = `${pre}In: <span class="text-emerald-500 font-bold">$${inP}</span> | Out: <span class="text-amber-500 font-bold">$${outP}</span> <span class="text-slate-400 font-normal">/1M Tok</span>`;
        costEl.classList.remove("hidden");
        costEl.title = info.approx
          ? `Preis des passenden Modells (${info.matched}) — Input: $${inP} / Output: $${outP} pro 1M Tokens`
          : `Input: $${inP} / Output: $${outP} pro 1 Million Tokens`;
      } else if (model && model !== "__CUSTOM__") {
        costEl.innerHTML = `In: <span class="text-emerald-500 font-bold">$0.00</span> | Out: <span class="text-amber-500 font-bold">$0.00</span> <span class="text-slate-400 font-normal">/1M Tok</span>`;
        costEl.classList.remove("hidden");
      } else {
        costEl.classList.add("hidden");
      }
    }
    window.updateBoardroomChairmanCost = updateBoardroomChairmanCost;

    function onBoardroomChairmanChange(keepCustomModel = false) {
      const select = document.getElementById("boardroom-chairman-select");
      const img = document.getElementById("boardroom-chair-avatar");
      const personEl = document.getElementById("boardroom-chair-person");
      const provSelect = document.getElementById("boardroom-chair-provider-select");
      const modelSelect = document.getElementById("boardroom-chair-model-select");
      if (!select) return;
      const profId = select.value;
      
      const foundProf = (typeof hermesProfilesData !== 'undefined' && hermesProfilesData) 
        ? hermesProfilesData.find(p => p.id === profId) 
        : null;
      let avatarUrl = '/static/avatars/avatar_001.jpg';
      if (typeof getProfileAvatarUrl === 'function') {
        avatarUrl = getProfileAvatarUrl(foundProf || { id: profId });
      }
      if (img) img.src = avatarUrl;
      if (personEl) personEl.innerText = foundProf ? (foundProf.person_name ? foundProf.person_name.split(' ')[0] : 'Michael') : 'Michael';

      if (!keepCustomModel && foundProf) {
        if (provSelect && foundProf.provider) provSelect.value = foundProf.provider;
        const curProv = provSelect ? provSelect.value : (foundProf.provider || "openrouter");
        setupBoardroomChairmanModelDropdown(curProv, foundProf.model);
      } else {
        const curProv = provSelect ? provSelect.value : "openrouter";
        const curModel = modelSelect ? modelSelect.value : null;
        setupBoardroomChairmanModelDropdown(curProv, curModel);
      }
    }
    window.onBoardroomChairmanChange = onBoardroomChairmanChange;

    function reindexBoardroomSlotBadges() {
      document.querySelectorAll("#boardroom-slots-list .boardroom-slot-row").forEach((row, i) => {
        const badge = row.querySelector(".slot-number-badge");
        if (badge) badge.innerText = `Slot ${i + 1}`;
      });
    }
    window.reindexBoardroomSlotBadges = reindexBoardroomSlotBadges;

    function addBoardroomSlotElement(roleName, profileId, slotNumber, modelId, providerId) {
      const container = document.getElementById("boardroom-slots-list");
      if (!container) return;
      const foundProf = (typeof hermesProfilesData !== 'undefined' && hermesProfilesData && hermesProfilesData.length > 0)
        ? (hermesProfilesData.find(p => p.id === profileId) || hermesProfilesData.find(p => p.name === profileId) || hermesProfilesData[Math.min(slotNumber || 1, hermesProfilesData.length - 1)])
        : null;
      
      const actualId = foundProf ? foundProf.id : profileId;
      const profDefaultModel = (foundProf && foundProf.model) ? foundProf.model : "deepseek/deepseek-chat";
      const profDefaultProvider = (foundProf && foundProf.provider) ? foundProf.provider : "openrouter";
      const activeProvider = providerId || profDefaultProvider;
      const activeModel = modelId || profDefaultModel;
      const computedSlotNumber = slotNumber || (document.querySelectorAll("#boardroom-slots-list .boardroom-slot-row").length + 1);

      let avatarUrl = '/static/avatars/avatar_001.jpg';
      if (typeof getProfileAvatarUrl === 'function') {
        avatarUrl = getProfileAvatarUrl(foundProf || { id: actualId });
      }
      const firstName = foundProf && foundProf.person_name ? foundProf.person_name.split(' ')[0] : '';
      const row = document.createElement("div");
      row.className = "boardroom-slot-row p-2.5 rounded-xl border border-[var(--border)] bg-[var(--card)] space-y-2 text-xs relative group hover:border-[var(--muted-foreground)] transition shadow-xs";
      row.innerHTML = `
        <!-- Zeile Kopf: Slot-Titel & Delete -->
        <div class="flex items-center justify-between gap-1.5 border-b border-[var(--border)] pb-1.5">
          <div class="flex items-center gap-1.5 flex-1 min-w-0">
            <span class="slot-number-badge text-[10px] font-mono font-bold text-indigo-500 dark:text-indigo-400 bg-indigo-500/10 px-1.5 py-0.5 rounded border border-indigo-500/20 shrink-0 select-none">Slot ${computedSlotNumber}</span>
            <input type="text" value="${roleName}" class="boardroom-slot-role-name bg-transparent font-bold text-xs prof-title-text border-b border-dashed border-[var(--border)] focus:outline-none focus:border-[var(--foreground)] px-1 py-0.5 flex-1 truncate" placeholder="Slot-Rolle..." title="Rollen-Bezeichnung im Framework anpassen">
          </div>
          <button onclick="this.closest('.boardroom-slot-row').remove(); reindexBoardroomSlotBadges(); saveBoardroomStateToLocalStorage();" class="text-[var(--muted-foreground)] hover:text-rose-500 p-1 rounded-md cursor-pointer transition text-xs" title="Diesen Slot entfernen">
            <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
          </button>
        </div>

        <div class="flex items-start gap-2.5 pt-0.5">
          <!-- Avatar links -->
          <div class="flex flex-col items-center shrink-0">
            <img src="${avatarUrl}" alt="Avatar" class="boardroom-slot-avatar w-10 h-10 rounded-xl object-cover border border-[var(--border)] shrink-0 shadow-xs" onerror="this.src='/static/avatars/avatar_001.jpg'">
            <span class="boardroom-slot-person text-[9px] font-bold text-[var(--foreground)] mt-1 max-w-[55px] text-center truncate">${firstName}</span>
          </div>

          <!-- Rechte 3 Zeilen: Profil, Provider, Modell + Kosten (Exakt wie Chat) -->
          <div class="flex-1 min-w-0 space-y-1.5">
            <!-- 1. Zeile: Profil Dropdown -->
            <div class="flex items-center gap-1.5">
              <span class="font-mono text-[10px] font-bold text-[var(--muted-foreground)] uppercase shrink-0 w-16">PROFIL:</span>
              <select onchange="updateBoardroomSlotCard(this); saveBoardroomStateToLocalStorage();" class="boardroom-slot-profile-select flex-1 min-w-0 bg-[var(--background)] border border-[var(--border)] rounded-md px-2 py-0.5 text-xs prof-title-text focus:outline-none cursor-pointer truncate font-bold shadow-2xs">
                ${getRoleOptionsHtml(actualId)}
              </select>
            </div>

            <!-- 2. Zeile: Provider Dropdown mit Preis-Katalog Button -->
            <div class="flex items-center gap-1.5">
              <span class="font-mono text-[10px] font-bold text-[var(--muted-foreground)] uppercase shrink-0 w-16">PROVIDER:</span>
              <select onchange="onBoardroomSlotProviderChanged(this); saveBoardroomStateToLocalStorage();" class="boardroom-slot-provider-select flex-1 min-w-0 bg-[var(--background)] border border-[var(--border)] rounded-md px-2 py-0.5 text-[11px] font-mono text-[var(--foreground)] focus:outline-none cursor-pointer shadow-2xs">
                ${getBoardroomProviderOptionsHtml(activeProvider)}
              </select>
              <button type="button" onclick="openPriceCatalogForSlot(this)" class="p-1 rounded-md bg-[var(--secondary)] hover:bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-[var(--border)] cursor-pointer transition shrink-0 flex items-center justify-center shadow-2xs" title="Preise & Modell-Katalog öffnen">
                <i data-lucide="circle-dollar-sign" class="w-3.5 h-3.5"></i>
              </button>
            </div>

            <!-- 3. Zeile: Sprachmodell Dropdown (wie im Chat) -->
            <div class="flex items-center gap-1.5">
              <span class="font-mono text-[10px] font-bold text-[var(--muted-foreground)] uppercase shrink-0 w-16">MODELL:</span>
              <select onchange="onBoardroomSlotModelChanged(this)" class="boardroom-slot-model-select flex-1 min-w-0 bg-[var(--background)] border border-[var(--border)] rounded-md px-2 py-0.5 text-[11px] font-mono text-[var(--foreground)] focus:outline-none cursor-pointer shadow-2xs truncate">
                <option value="${activeModel}" selected>${activeModel}</option>
              </select>
            </div>

            <!-- 4. Zeile: Live-Kosten Pill (rechtsbündig) -->
            <div class="flex items-center justify-end pt-0.5">
              <span class="boardroom-slot-cost text-[10px] font-mono bg-amber-500/10 text-amber-600 dark:text-amber-400 px-2 py-0.5 rounded-md border border-amber-500/20 inline-block shadow-2xs">
                <!-- Live Token Kosten -->
              </span>
            </div>
          </div>
        </div>
      `;
      container.appendChild(row);
      const mSelect = row.querySelector('.boardroom-slot-model-select');
      setupBoardroomSlotModelDropdown(mSelect, activeProvider, activeModel);
      if (window.lucide) window.lucide.createIcons();
    }
    window.addBoardroomSlotElement = addBoardroomSlotElement;
    function addBoardroomCustomSlot() {
      addBoardroomSlotElement("Zusätzlicher Experte", "enterprise_solutions_architect");
    }
    function onBoardroomFrameworkChange() {
      const select = document.getElementById("boardroom-framework-select");
      if (!select) return;
      updateFrameworkSummaryTooltip();
      renderBoardroomSlots(select.value);
    }
    async function loadBoardroomFrameworks() {
      const select = document.getElementById("boardroom-framework-select");
      if (!select) return;
      try {
        const res = await fetch("/api/boardroom/frameworks");
        if (!res.ok) return;
        categorizedFrameworksData = await res.json();
        select.innerHTML = "";
        
        let isFirst = true;
        for (const [catName, frameworks] of Object.entries(categorizedFrameworksData)) {
          const group = document.createElement("optgroup");
          group.label = catName;
          for (const [fwName, fwData] of Object.entries(frameworks)) {
            const opt = document.createElement("option");
            opt.value = fwName;
            opt.innerText = fwName;
            const summaryText = typeof fwData === "string" ? fwData : (fwData.summary || fwData.system_instruction || "");
            opt.setAttribute("data-summary", summaryText);
            if (fwName === "Steffi Kieffer Boardroom" || isFirst) {
              opt.selected = true;
              isFirst = false;
            }
            group.appendChild(opt);
          }
          select.appendChild(group);
        }
        updateFrameworkSummaryTooltip();
        renderBoardroomSlots(select.value || "Steffi Kieffer Boardroom");
      } catch (e) {
        console.error("Error loading boardroom frameworks:", e);
      }
    }
    function updateFrameworkSummaryTooltip() {
      const select = document.getElementById("boardroom-framework-select");
      const summaryEl = document.getElementById("boardroom-framework-summary");
      if (!select || !summaryEl) return;
      const selectedOpt = select.options[select.selectedIndex];
      if (selectedOpt) {
        const text = selectedOpt.getAttribute("data-summary") || selectedOpt.value || "";
        summaryEl.value = text;
        summaryEl.innerText = text;
      }
    }
    function populateBoardroomChairmanSelect() {
      const select = document.getElementById("boardroom-chairman-select");
      if (!select) return;
      select.innerHTML = "";
      
      const sourceRoles = (typeof hermesProfilesData !== 'undefined' && hermesProfilesData.length > 0)
        ? hermesProfilesData
        : ((roles && roles.length > 0) ? roles : [
          { id: "hermes_default", name: "Hermes Default (Master System)", person_name: "Michael Keller", category: "1. Strategie, Führung & Lebensplanung" }
        ]);
      const categories = {};
      sourceRoles.forEach(r => {
        const cat = r.category || "Management";
        if (!categories[cat]) categories[cat] = [];
        categories[cat].push(r);
      });
      for (const [catName, rList] of Object.entries(categories)) {
        const group = document.createElement("optgroup");
        group.label = catName;
        rList.forEach(r => {
          const opt = document.createElement("option");
          opt.value = r.id;
          opt.innerText = r.person_name ? `${r.person_name} – ${r.name}` : r.name;
          if (r.id === "hermes_default" || r.id === "orchestrator" || (r.name || '').toLowerCase().includes("orchestrator") || (r.name || '').toLowerCase().includes("default")) {
            opt.selected = true;
          }
          group.appendChild(opt);
        });
        select.appendChild(group);
      }
      if (select.selectedIndex === -1 && select.options.length > 0) {
        select.options[0].selected = true;
      }
      onBoardroomChairmanChange();
    }
    // =========================================================================
    // BOARDROOM / DECISION ENGINE TAB & HISTORY CONTROLLER
    // =========================================================================
    let currentBoardroomTab = 'overview';
    let cachedBoardroomHistory = [];
    let currentViewingDebateId = null;

    const BOARDROOM_HEADER_META = {
      overview: {
        title: 'Decision Engine · Übersicht',
        subtitle: 'Historie, frühere Debatten & strategische Konsens-Ergebnisse',
        img: '/static/img/cadre_icons/overview.png'
      },
      debate: {
        title: 'Decision Engine · Debatte',
        subtitle: 'Methodik-Auswahl, Experten-Zuweisung & Aufgabenstellung',
        img: '/static/img/cadre_icons/debate.png'
      },
      live: {
        title: 'Decision Engine · Live-Debatte',
        subtitle: 'Transkription, Runden-Ablauf & finale Konsens-Synthese',
        img: '/static/img/cadre_icons/live.png'
      }
    };

    function setBoardroomTab(tab) {
      if (!tab) tab = 'overview';
      currentBoardroomTab = tab;
      const tabs = ['overview', 'debate', 'live'];

      const meta = BOARDROOM_HEADER_META[tab] || BOARDROOM_HEADER_META.overview;
      const titleEl = document.getElementById('boardroom-main-title');
      const subtitleEl = document.getElementById('boardroom-main-subtitle');
      const headerImgEl = document.getElementById('boardroom-main-header-img');
      if (titleEl) titleEl.textContent = meta.title;
      if (subtitleEl) subtitleEl.textContent = meta.subtitle;
      if (headerImgEl) headerImgEl.src = meta.img;

      tabs.forEach(t => {
        const btn = document.getElementById(`boardroom-subtab-${t}`);
        const view = document.getElementById(`boardroom-view-${t}`);
        const iconWrap = btn ? btn.querySelector('.tile-icon-wrap') : null;
        const label = btn ? btn.querySelector('.boardroom-tab-label') : null;

        if (t === tab) {
          if (btn) {
            btn.className = "boardroom-header-tile active-cadre-tab flex flex-col items-center justify-between min-w-[56px] sm:min-w-[62px] h-[72px] py-1 px-0.5 bg-transparent border-0 shadow-none opacity-100 cursor-pointer select-none transition-transform hover:scale-105 duration-150";
          }
          if (iconWrap) iconWrap.classList.add('active-tile');
          if (label) {
            label.className = "boardroom-tab-label text-[10px] font-mono tracking-tight text-center whitespace-nowrap text-red-600 font-bold leading-none";
          }
          if (view) view.classList.remove('hidden');
        } else {
          if (btn) {
            btn.className = "boardroom-header-tile flex flex-col items-center justify-between min-w-[56px] sm:min-w-[62px] h-[72px] py-1 px-0.5 bg-transparent border-0 shadow-none opacity-80 hover:opacity-100 cursor-pointer select-none transition-transform hover:scale-105 duration-150";
          }
          if (iconWrap) iconWrap.classList.remove('active-tile');
          if (label) {
            label.className = "boardroom-tab-label text-[10px] font-mono tracking-tight text-center whitespace-nowrap text-[var(--muted-foreground)] font-medium leading-none";
          }
          if (view) view.classList.add('hidden');
        }
      });

      if (tab === 'overview') {
        loadBoardroomHistory();
      } else if (tab === 'debate') {
        if (!categorizedFrameworksData) loadBoardroomFrameworks();
      }

      if (window.lucide) window.lucide.createIcons();
    }

    async function loadBoardroomHistory() {
      try {
        const res = await fetch("/api/boardroom/history");
        if (!res.ok) return;
        const data = await res.json();
        cachedBoardroomHistory = Array.isArray(data) ? data : [];
        renderBoardroomHistory(cachedBoardroomHistory);

        const badge = document.getElementById("boardroom-history-count-badge");
        const totalEl = document.getElementById("boardroom-history-total");
        if (badge) {
          badge.innerText = cachedBoardroomHistory.length;
          badge.classList.toggle("hidden", cachedBoardroomHistory.length === 0);
        }
        if (totalEl) {
          totalEl.innerText = `${cachedBoardroomHistory.length} Einträge`;
        }
      } catch (e) {
        console.error("Error loading boardroom history:", e);
      }
    }

    function filterBoardroomHistory() {
      const searchInput = document.getElementById("boardroom-history-search");
      const query = searchInput ? searchInput.value.toLowerCase().trim() : "";
      if (!query) {
        renderBoardroomHistory(cachedBoardroomHistory);
        return;
      }
      const filtered = cachedBoardroomHistory.filter(item => {
        return (item.task || '').toLowerCase().includes(query) ||
               (item.framework || '').toLowerCase().includes(query) ||
               (item.synthesis || '').toLowerCase().includes(query) ||
               (item.date_display || '').toLowerCase().includes(query);
      });
      renderBoardroomHistory(filtered);
    }

    function renderBoardroomHistory(items) {
      const container = document.getElementById("boardroom-history-list");
      if (!container) return;
      container.innerHTML = "";

      if (!items || items.length === 0) {
        container.innerHTML = `
          <div class="h-64 flex flex-col items-center justify-center text-center p-6 text-[var(--muted-foreground)]">
            <div class="w-12 h-12 rounded-full bg-[var(--card)] border border-[var(--border)] shadow-xs flex items-center justify-center mb-3">
              <i data-lucide="inbox" class="w-6 h-6"></i>
            </div>
            <p class="text-xs font-bold text-[var(--foreground)]">Keine Debatten in der Historie gefunden</p>
            <p class="text-[11px] text-[var(--muted-foreground)] mt-1 max-w-sm">Starte im Tab "Debatte" eine neue Multi-Agenten-Debatte, um hier Protokolle und Synthesen zu sehen.</p>
          </div>
        `;
        if (window.lucide) window.lucide.createIcons();
        return;
      }

      items.forEach(h => {
        const card = document.createElement("div");
        card.className = "p-3.5 bg-[var(--card)] hover:bg-[var(--secondary)]/60 border border-[var(--border)] rounded-xl transition cursor-pointer shadow-xs group";
        card.onclick = () => openBoardroomDetailModal(h.id);

        const taskText = h.task || 'Strategische Debatte';
        const synthSnippet = h.synthesis ? (h.synthesis.length > 220 ? h.synthesis.substring(0, 220) + '...' : h.synthesis) : 'Keine Synthese dokumentiert.';
        const scopeText = `${h.rounds || 2} Runden · ${(h.slots_count || 3) + 1} Experten`;

        card.innerHTML = `
          <div class="flex items-center justify-between gap-2 border-b border-[var(--border)] pb-2 mb-2">
            <div class="flex items-center gap-2 flex-wrap">
              <span class="text-[10px] font-mono text-[var(--muted-foreground)] font-bold flex items-center gap-1">
                <i data-lucide="calendar" class="w-3 h-3 text-indigo-500"></i> ${h.date_display || 'Heute'}
              </span>
              <span class="text-[9.5px] font-mono font-bold px-2 py-0.5 rounded-md bg-indigo-500/10 text-indigo-500 border border-indigo-500/20">
                ${h.framework || 'Steffi Kieffer Boardroom'}
              </span>
              <span class="text-[9.5px] font-mono font-bold px-2 py-0.5 rounded-md bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20">
                ${scopeText}
              </span>
            </div>
            <button type="button" class="text-xs font-mono font-bold text-indigo-500 group-hover:text-indigo-600 flex items-center gap-1">
              <span>Details &amp; Ergebnis</span>
              <i data-lucide="chevron-right" class="w-3.5 h-3.5 group-hover:translate-x-0.5 transition-transform"></i>
            </button>
          </div>
          <div class="space-y-1.5">
            <h4 class="text-xs font-bold text-[var(--foreground)] line-clamp-2 leading-snug">
              ${taskText}
            </h4>
            <div class="text-[11px] text-[var(--muted-foreground)] line-clamp-2 font-sans bg-[var(--background)] p-2 rounded-lg border border-[var(--border)] font-normal leading-relaxed">
              <span class="font-bold text-[var(--foreground)]">Ergebnis:</span> ${synthSnippet}
            </div>
          </div>
        `;
        container.appendChild(card);
      });

      if (window.lucide) window.lucide.createIcons();
    }

    function openBoardroomDetailModal(id) {
      const item = cachedBoardroomHistory.find(h => h.id === id);
      if (!item) return;
      currentViewingDebateId = id;

      const metaEl = document.getElementById("boardroom-detail-meta");
      const taskEl = document.getElementById("boardroom-detail-task");
      const synthEl = document.getElementById("boardroom-detail-synthesis");
      const modal = document.getElementById("boardroom-detail-modal");

      if (metaEl) {
        metaEl.innerText = `${item.date_display || 'Datum unbekannt'} · ${item.framework || 'Framework'} · ${item.rounds || 2} Runden · ${(item.slots_count || 3) + 1} Experten`;
      }
      if (taskEl) taskEl.innerText = item.task || '';
      if (synthEl) synthEl.innerText = item.synthesis || 'Keine finale Synthese vorhanden.';
      if (modal) modal.classList.remove("hidden");
      if (window.lucide) window.lucide.createIcons();
    }

    function closeBoardroomDetailModal() {
      const modal = document.getElementById("boardroom-detail-modal");
      if (modal) modal.classList.add("hidden");
    }

    function resetBoardroomFrameworkDefaults() {
      const fwSelect = document.getElementById("boardroom-framework-select");
      const fw = fwSelect ? fwSelect.value : "Steffi Kieffer Boardroom";
      try {
        localStorage.removeItem("archon_boardroom_custom_" + fw);
      } catch (e) {}
      renderBoardroomSlots(fw, true);
      if (typeof showArchonToast === "function") {
        showArchonToast(`Standard-Slots für "${fw}" wiederhergestellt.`, "success");
      }
    }
    window.resetBoardroomFrameworkDefaults = resetBoardroomFrameworkDefaults;

    function exportCurrentViewingDebate() {
      if (!currentViewingDebateId) return;
      const item = cachedBoardroomHistory.find(h => h.id === currentViewingDebateId);
      if (!item) return;

      let md = `# AI Boardroom Debatte: ${item.task || 'Strategische Debatte'}\n\n`;
      md += `**Datum:** ${item.date_display || new Date().toLocaleString("de-DE")}\n`;
      md += `**Framework:** ${item.framework || 'Framework'}\n`;
      md += `**Runden:** ${item.rounds || 2} | **Teilnehmer:** ${(item.slots_count || 3) + 1}\n\n`;
      md += `## Diskussionsverlauf\n\n${item.transcript || '(Kein Transkript vorhanden)'}\n\n`;
      md += `## Finale Synthese & Konsens\n\n${item.synthesis || '(Keine Synthese vorhanden)'}\n`;

      const blob = new Blob([md], { type: "text/markdown;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `boardroom_${item.id || 'debatte'}.md`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      if (typeof showArchonToast === "function") {
        showArchonToast("Debatte erfolgreich als Markdown exportiert.", "success");
      }
    }
    window.exportCurrentViewingDebate = exportCurrentViewingDebate;

    function openTranscriptFromDetailModal() {
      closeBoardroomDetailModal();
      if (!currentViewingDebateId) return;
      const item = cachedBoardroomHistory.find(h => h.id === currentViewingDebateId);
      if (!item) return;

      setBoardroomTab('live');
      renderPastDebateIntoLiveTab(item);
    }

    function renderPastDebateIntoLiveTab(item) {
      const threadDiv = document.getElementById("boardroom-thread");
      if (!threadDiv) return;
      threadDiv.innerHTML = "";

      const headerBanner = document.createElement("div");
      headerBanner.className = "rounded-lg p-4 bg-[var(--card)] border border-[var(--border)] text-xs space-y-1 mb-4 font-mono text-[var(--foreground)]";
      headerBanner.innerHTML = `
        <div class="flex items-center justify-between text-[var(--foreground)] font-bold uppercase tracking-wider">
          <span>📋 DEBATTE: ${item.task}</span>
          <span>${item.date_display || ''}</span>
        </div>
        <div class="text-[10px] text-[var(--muted-foreground)]">
          Framework: ${item.framework || 'Steffi Kieffer Boardroom'} | Runden: ${item.rounds || 2} | Teilnehmer: ${(item.slots_count || 3) + 1}
        </div>
      `;
      threadDiv.appendChild(headerBanner);

      if (item.transcript) {
        const transcriptCard = document.createElement("div");
        transcriptCard.className = "rounded-xl p-4 bg-[var(--card)] border border-[var(--border)] text-xs font-mono space-y-2 whitespace-pre-wrap leading-relaxed shadow-xs";
        transcriptCard.innerText = item.transcript;
        threadDiv.appendChild(transcriptCard);
      }

      if (item.synthesis) {
        const synthCard = document.createElement("div");
        synthCard.className = "rounded-xl p-5 bg-[var(--card)] border border-amber-500/30 space-y-3 my-4 shadow-md";
        synthCard.innerHTML = `
          <div class="flex items-center justify-between border-b border-[var(--border)] pb-2.5">
            <h3 class="text-xs font-bold uppercase tracking-wider text-amber-500 flex items-center gap-2">
              <i data-lucide="award" class="w-4 h-4"></i> FINALE SYNTHESE &amp; ENTSCHEIDUNGSEMPFEHLUNG
            </h3>
            <span class="text-[10px] font-mono px-2 py-0.5 rounded bg-amber-500/10 text-amber-500 font-bold">KONSENS</span>
          </div>
          <div class="text-xs leading-relaxed text-[var(--foreground)] whitespace-pre-wrap font-sans font-medium">
            ${item.synthesis}
          </div>
        `;
        threadDiv.appendChild(synthCard);
      }

      if (window.lucide) window.lucide.createIcons();
      threadDiv.scrollTop = 0;
    }

    function openBoardroomLiveModal(taskName) {
      const modal = document.getElementById("boardroom-live-dialog-modal");
      const dialogThread = document.getElementById("boardroom-dialog-thread");
      const subEl = document.getElementById("boardroom-dialog-subtitle");
      const statusEl = document.getElementById("boardroom-dialog-status-text");

      if (dialogThread) dialogThread.innerHTML = "";
      if (subEl && taskName) subEl.innerText = taskName;
      if (statusEl) statusEl.innerText = "Debatte gestartet...";
      if (modal) modal.classList.remove("hidden");
      if (window.lucide) window.lucide.createIcons();
    }

    function closeBoardroomLiveModal() {
      const modal = document.getElementById("boardroom-live-dialog-modal");
      if (modal) modal.classList.add("hidden");
    }

    function openLiveTabFromModal() {
      closeBoardroomLiveModal();
      setBoardroomTab('live');
    }

    function copyBoardroomTranscript() {
      const threadDiv = document.getElementById("boardroom-thread");
      if (!threadDiv) return;
      const text = threadDiv.innerText;
      navigator.clipboard.writeText(text).then(() => {
        if (typeof showArchonToast === "function") {
          showArchonToast("Transkript in Zwischenablage kopiert.", "success");
        } else {
          alert("Transkript kopiert!");
        }
      }).catch(() => {
        alert("Konnte Transkript nicht kopieren.");
      });
    }

    function downloadBoardroomTranscript() {
      const threadDiv = document.getElementById("boardroom-thread");
      if (!threadDiv) return;

      // Check if we are viewing a past debate
      if (currentViewingDebateId) {
        exportCurrentViewingDebate();
        return;
      }

      // If active debate with cached metadata
      const taskVal = (document.getElementById("boardroom-task") && document.getElementById("boardroom-task").value.trim()) || "AI Boardroom Debatte";
      const fwVal = (document.getElementById("boardroom-framework-select") && document.getElementById("boardroom-framework-select").value) || "Framework";
      const roundsVal = (document.getElementById("boardroom-rounds") && document.getElementById("boardroom-rounds").value) || "2";

      let md = `# AI Boardroom Debatte: ${taskVal}\n\n`;
      md += `**Datum:** ${new Date().toLocaleString("de-DE")}\n`;
      md += `**Methodik-Framework:** ${fwVal}\n`;
      md += `**Runden:** ${roundsVal}\n\n`;
      md += `## Protokoll & Transkript\n\n`;
      md += threadDiv.innerText;

      const blob = new Blob([md], { type: "text/markdown;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `boardroom_transkript_${new Date().toISOString().slice(0, 10)}.md`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      if (typeof showArchonToast === "function") {
        showArchonToast("Transkript erfolgreich heruntergeladen.", "success");
      }
    }

    function appendBothBoardroomThreads(elFactory) {
      const threadDiv = document.getElementById("boardroom-thread");
      const dialogThread = document.getElementById("boardroom-dialog-thread");
      if (threadDiv) {
        const el1 = elFactory();
        threadDiv.appendChild(el1);
        threadDiv.scrollTop = threadDiv.scrollHeight;
      }
      if (dialogThread) {
        const el2 = elFactory();
        dialogThread.appendChild(el2);
        dialogThread.scrollTop = dialogThread.scrollHeight;
      }
      if (window.lucide) window.lucide.createIcons();
    }

    let currentBoardroomAbortController = null;

    function stopBoardroomDebate() {
      if (currentBoardroomAbortController) {
        currentBoardroomAbortController.abort();
        currentBoardroomAbortController = null;
        if (typeof showArchonToast === "function") {
          showArchonToast("Debatte abgebrochen.", "info");
        } else {
          console.log("Debatte abgebrochen.");
        }
      }
      const startBtn = document.getElementById("boardroom-start-btn");
      const loadingDiv = document.getElementById("boardroom-loading");
      if (startBtn) startBtn.disabled = false;
      if (loadingDiv) loadingDiv.classList.add("hidden");
    }

    async function runBoardroomDebate() {
      const taskInput = document.getElementById("boardroom-task");
      const roundsInput = document.getElementById("boardroom-rounds");
      const chairmanSelect = document.getElementById("boardroom-chairman-select");
      const frameworkSelect = document.getElementById("boardroom-framework-select");
      const startBtn = document.getElementById("boardroom-start-btn");
      const loadingDiv = document.getElementById("boardroom-loading");
      let task = taskInput ? taskInput.value.trim() : "";
      if (currentBoardroomAttachments.length > 0) {
        for (const att of currentBoardroomAttachments) {
          if (att.file) {
            try {
              const formData = new FormData();
              formData.append("file", att.file);
              const parseRes = await fetch("/api/boardroom/parse-attachment", {
                method: "POST",
                body: formData
              });
              if (parseRes.ok) {
                const parsed = await parseRes.json();
                task += `\n\n--- ANGEHÄNGTE DATEI: ${att.name} ---\n${parsed.text}`;
              } else {
                const fileContent = await att.file.text();
                task += `\n\n--- ANGEHÄNGTE DATEI: ${att.name} ---\n${fileContent.substring(0, 15000)}`;
              }
            } catch (err) {
              console.warn("Could not parse attachment", att.name, err);
              task += `\n\n[Angehängte Datei: ${att.name} (${att.size})]`;
            }
          }
        }
      }
      const rounds = roundsInput ? parseInt(roundsInput.value) || 2 : 2;
      const chairmanId = chairmanSelect ? chairmanSelect.value : "orchestrator";
      const frameworkVal = frameworkSelect ? frameworkSelect.value : "Steffi Kieffer Boardroom";
      if (!task) {
        alert("Bitte geben Sie eine strategische Aufgabenstellung für den Boardroom ein.");
        return;
      }
      // Collect slot configurations
      const slotEls = document.querySelectorAll("#boardroom-slots-list .boardroom-slot-row");
      const slots = Array.from(slotEls).map((el, idx) => {
        const roleInput = el.querySelector(".boardroom-slot-role-name");
        const profileSelect = el.querySelector(".boardroom-slot-profile-select");
        const provSelect = el.querySelector(".boardroom-slot-provider-select");
        const modelSelect = el.querySelector(".boardroom-slot-model-select");
        const chosenModel = modelSelect ? modelSelect.value.trim() : "";
        const chosenProv = provSelect ? provSelect.value.trim() : "openrouter";
        return {
          role_name: roleInput ? (roleInput.value.trim() || `Experte ${idx + 1}`) : `Experte ${idx + 1}`,
          profile_id: profileSelect ? profileSelect.value : "senior_coder",
          model_id: chosenModel || null,
          provider: chosenProv || null
        };
      });

      // Open the Live Dialog Modal right upon starting!
      openBoardroomLiveModal(task);

      // Indicate running status
      const livePulse = document.getElementById("boardroom-live-pulse-badge");
      if (livePulse) livePulse.classList.remove("hidden");
      const statusDot = document.getElementById("boardroom-header-status-dot");
      if (statusDot) {
        statusDot.className = "absolute -bottom-1 -right-1 w-4 h-4 rounded-full bg-amber-500 border-2 border-[var(--card)] animate-ping";
        statusDot.title = "Debatte läuft...";
      }
      const totalBadge = document.getElementById("boardroom-total-badge");
      if (totalBadge) {
        totalBadge.innerText = "Debatte aktiv";
        totalBadge.className = "px-2 py-0.5 rounded-full text-[10px] font-mono font-bold bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/25 shrink-0";
      }

      if (startBtn) startBtn.disabled = true;
      if (loadingDiv) {
        loadingDiv.classList.remove("hidden");
        document.getElementById("boardroom-loading-status").innerText = `AI Boardroom Debatte wird mit ${slots.length + 1} Profilen ausgeführt (${frameworkVal}, ${rounds} Runden)...`;
      }

      currentBoardroomAbortController = new AbortController();

      try {
        const response = await fetch("/api/boardroom/stream", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          signal: currentBoardroomAbortController.signal,
          body: JSON.stringify({
            task,
            rounds,
            chairman_id: chairmanId,
            chairman_provider: (document.getElementById("boardroom-chair-provider-select") && document.getElementById("boardroom-chair-provider-select").value) || "openrouter",
            chairman_model: (document.getElementById("boardroom-chair-model-select") && document.getElementById("boardroom-chair-model-select").value) || null,
            framework: frameworkVal,
            slots,
            reasoning_level: (document.getElementById("boardroom-reasoning-select") && document.getElementById("boardroom-reasoning-select").value) || "profile",
            use_moa: Boolean(document.getElementById("boardroom-moa-toggle") && document.getElementById("boardroom-moa-toggle").checked),
            moa_reference_models: (typeof getMoAReferenceModels === "function") ? getMoAReferenceModels() : null,
            moa_aggregator: (typeof getMoAAggregatorModel === "function") ? getMoAAggregatorModel() : null
          })
        });
        if (!response.ok) {
          const errData = await response.json().catch(() => ({}));
          alert(`Fehler: ${errData.detail || 'Debatte konnte nicht gestartet werden.'}`);
          return;
        }

        const threadDiv = document.getElementById("boardroom-thread");
        if (threadDiv) threadDiv.innerHTML = "";
        
        let currentRound = 0;
        let boardMeta = { task, framework: frameworkVal, max_rounds: rounds, chairman: { name: "Moderator" } };

        const reader = response.body.getReader();
        const decoder = new TextDecoder("utf-8");
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const parts = buffer.split("\n\n");
          buffer = parts.pop();

          for (const part of parts) {
            const trimmed = part.trim();
            if (!trimmed.startsWith("data:")) continue;
            const jsonStr = trimmed.replace(/^data:\s*/, "");
            try {
              const ev = JSON.parse(jsonStr);
              if (ev.type === "moa_start") {
                appendBothBoardroomThreads(() => {
                  const b = document.createElement("div");
                  b.className = "rounded-xl p-3 bg-indigo-500/10 border border-indigo-500/30 text-xs mb-3 font-mono text-indigo-700 dark:text-indigo-300 flex items-center justify-between";
                  b.innerHTML = `
                    <div class="flex items-center gap-2">
                      <span class="w-2.5 h-2.5 rounded-full bg-indigo-500 animate-pulse"></span>
                      <span class="font-bold">⚡ MIXTURE OF AGENTS (MoA) AKTIVIERT</span>
                    </div>
                    <span class="text-[10px] font-bold">${ev.reference_models ? ev.reference_models.length : 3} Modelle parallel &rarr; Aggregator</span>
                  `;
                  return b;
                });
              } else if (ev.type === "moa_ref_done") {
                appendBothBoardroomThreads(() => {
                  const card = document.createElement("div");
                  card.className = "rounded-xl p-3 bg-[var(--card)] border border-indigo-500/20 text-xs mb-2.5 shadow-2xs font-sans";
                  card.innerHTML = `
                    <div class="flex items-center justify-between pb-1.5 border-b border-[var(--border)] mb-2 font-mono">
                      <span class="font-bold text-indigo-600 dark:text-indigo-400">🤖 MoA Layer-1: ${escapeHtml(ev.name || ev.model)}</span>
                      <span class="text-[9px] px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-600 font-bold uppercase">${ev.status || 'OK'}</span>
                    </div>
                    <div class="text-[11.5px] leading-relaxed text-[var(--foreground)] whitespace-pre-wrap select-text">${escapeHtml(ev.content || '')}</div>
                  `;
                  return card;
                });
              } else if (ev.type === "moa_aggregating") {
                appendBothBoardroomThreads(() => {
                  const aggB = document.createElement("div");
                  aggB.className = "rounded-lg p-2 bg-amber-500/10 border border-amber-500/30 text-xs mb-2 font-mono text-amber-700 dark:text-amber-300 flex items-center gap-2";
                  aggB.innerHTML = `<span class="w-2 h-2 rounded-full bg-amber-500 animate-ping"></span><span>🎯 MoA Aggregator synthetisiert Layer-1 Ergebnisse...</span>`;
                  return aggB;
                });
              } else if (ev.type === "start") {
                boardMeta = ev;
                appendBothBoardroomThreads(() => {
                  const headerBanner = document.createElement("div");
                  headerBanner.className = "rounded-lg p-3 bg-[var(--card)] border border-[var(--border)] text-xs space-y-1 mb-3 font-mono text-[var(--foreground)] shadow-xs";
                  headerBanner.innerHTML = `
                    <div class="flex items-center justify-between text-[var(--foreground)] font-bold uppercase tracking-wider">
                      <span>📋 BOARDROOM DEBATTE: ${ev.task}</span>
                      <span>CHAIRMAN: ${ev.chairman ? ev.chairman.name : 'Moderator'}</span>
                    </div>
                    <div class="text-[10px] text-[var(--muted-foreground)]">
                      Max Runden: ${ev.max_rounds} | Framework: ${ev.framework || 'Steffi Kieffer Boardroom'} | Live Streaming aktiv
                    </div>
                  `;
                  return headerBanner;
                });
              } else if (ev.type === "round_start") {
                if (ev.round && ev.round !== currentRound) {
                  currentRound = ev.round;
                  const statusDialogText = document.getElementById("boardroom-dialog-status-text");
                  if (statusDialogText) {
                    statusDialogText.innerText = `Runde ${currentRound} von ${boardMeta.max_rounds} läuft...`;
                  }
                  appendBothBoardroomThreads(() => {
                    const divider = document.createElement("div");
                    divider.className = "flex items-center gap-3 my-3 animate-fade-in";
                    divider.innerHTML = `
                      <div class="flex-1 h-[1px] bg-[var(--border)]"></div>
                      <span class="text-[10px] font-mono font-bold tracking-widest uppercase px-3 py-1 rounded bg-[var(--secondary)] border border-[var(--border)] text-indigo-500">
                        ⚡ DEBATTE RUNDE ${currentRound} VON ${boardMeta.max_rounds}
                      </span>
                      <div class="flex-1 h-[1px] bg-[var(--border)]"></div>
                    `;
                    return divider;
                  });
                }
              } else if (ev.type === "consensus_reached") {
                appendBothBoardroomThreads(() => {
                  const alertBox = document.createElement("div");
                  alertBox.className = "rounded-xl p-3 bg-[var(--secondary)] border border-emerald-500/30 text-[var(--foreground)] font-mono text-xs font-semibold flex items-center gap-2 my-2 animate-fade-in";
                  alertBox.innerHTML = `<i data-lucide="check-circle" class="w-4 h-4 text-emerald-500"></i> <span>${ev.content}</span>`;
                  return alertBox;
                });
              } else if (ev.type === "final_synthesis") {
                const statusDialogText = document.getElementById("boardroom-dialog-status-text");
                if (statusDialogText) {
                  statusDialogText.innerText = "Finale Synthese & Aktionsplan wird erstellt...";
                }
                appendBothBoardroomThreads(() => {
                  const synthCard = document.createElement("div");
                  synthCard.className = "rounded-xl p-5 bg-[var(--card)] border border-amber-500/30 space-y-3 my-4 shadow-md animate-fade-in";
                  synthCard.innerHTML = `
                    <div class="flex items-center justify-between border-b border-[var(--border)] pb-2.5">
                      <h3 class="text-xs font-bold uppercase tracking-wider text-amber-500 flex items-center gap-2">
                        <i data-lucide="award" class="w-4 h-4"></i> FINALE SYNTHESE &amp; AKTIONSPLAN
                      </h3>
                      <span class="text-[10px] font-mono px-2.5 py-0.5 rounded bg-indigo-500/10 border border-indigo-500/20 text-indigo-500 font-bold">${ev.agent_name} (${ev.role})</span>
                    </div>
                    <div class="text-xs leading-relaxed text-[var(--foreground)] whitespace-pre-wrap font-sans font-medium">
                      ${ev.content}
                    </div>
                  `;
                  return synthCard;
                });
              } else if (ev.type === "chairman_init" || ev.type === "agent_response") {
                const statusDialogText = document.getElementById("boardroom-dialog-status-text");
                if (statusDialogText) {
                  statusDialogText.innerText = `${ev.agent_name} (${ev.role}) argumentiert...`;
                }
                const isChairman = ev.type === "chairman_init" || ev.agent_id === (boardMeta.chairman ? boardMeta.chairman.id : "");
                let msgAvatarUrl = '/static/avatars/avatar_001.jpg';
                if (typeof getProfileAvatarUrl === 'function') {
                  const foundProf = (typeof hermesProfilesData !== 'undefined' && hermesProfilesData) ? hermesProfilesData.find(p => p.id === ev.agent_id || p.name === ev.agent_name) : null;
                  msgAvatarUrl = getProfileAvatarUrl(foundProf || { id: ev.agent_id || ev.agent_name });
                }
                appendBothBoardroomThreads(() => {
                  const card = document.createElement("div");
                  card.className = `rounded-xl p-3 bg-[var(--card)] border border-[var(--border)] transition-all space-y-2 my-2 animate-fade-in shadow-xs ${isChairman ? 'ring-1 ring-indigo-500/40' : ''}`;
                  card.innerHTML = `
                    <div class="flex items-center justify-between border-b border-[var(--border)] pb-1.5">
                      <div class="flex items-center gap-2.5">
                        <img src="${msgAvatarUrl}" alt="${ev.agent_name || 'Agent'}" class="w-8 h-8 rounded-full object-cover border border-[var(--border)] shadow-xs shrink-0" onerror="this.src='/static/avatars/avatar_001.jpg'">
                        <div>
                          <div class="flex items-center gap-2">
                            <span class="text-xs font-bold text-[var(--foreground)]">${ev.agent_name}</span>
                            <span class="text-[10px] font-mono px-2 py-0.5 rounded-md bg-[var(--secondary)] text-[var(--muted-foreground)] border border-[var(--border)] font-medium">${ev.role}</span>
                            ${isChairman ? '<span class="text-[9.5px] font-mono font-bold px-2 py-0.5 rounded-md bg-indigo-500/10 text-indigo-500 border border-indigo-500/20">MODERATOR</span>' : ''}
                          </div>
                          <div class="text-[9.5px] text-[var(--muted-foreground)] font-mono mt-0.5">Modell: ${ev.model || 'Standard'}</div>
                        </div>
                      </div>
                      <span class="text-[10px] font-mono text-[var(--muted-foreground)]">${new Date().toLocaleTimeString()}</span>
                    </div>
                    <div class="text-xs leading-relaxed text-[var(--foreground)] whitespace-pre-wrap font-sans font-normal pt-1">
                      ${ev.content}
                    </div>
                  `;
                  return card;
                });
              } else if (ev.type === "done") {
                const statusDialogText = document.getElementById("boardroom-dialog-status-text");
                if (statusDialogText) {
                  statusDialogText.innerText = "Debatte erfolgreich abgeschlossen!";
                }
                if (document.getElementById("boardroom-loading-status")) {
                  document.getElementById("boardroom-loading-status").innerText = "Debatte erfolgreich abgeschlossen!";
                }
                loadBoardroomHistory();
              }
            } catch (err) {
              console.error("Parse SSE chunk error:", err);
            }
          }
        }
      } catch (e) {
        if (e.name === 'AbortError') {
          console.log("Boardroom stream aborted by user.");
          if (document.getElementById("boardroom-loading-status")) {
            document.getElementById("boardroom-loading-status").innerText = "Debatte durch Nutzer gestoppt.";
          }
        } else {
          console.error("Boardroom debate error:", e);
          alert(`Verbindungsfehler: ${e.message}`);
        }
      } finally {
        currentBoardroomAbortController = null;
        if (startBtn) startBtn.disabled = false;
        if (loadingDiv) loadingDiv.classList.add("hidden");

        const livePulse = document.getElementById("boardroom-live-pulse-badge");
        if (livePulse) livePulse.classList.add("hidden");
        const statusDot = document.getElementById("boardroom-header-status-dot");
        if (statusDot) {
          statusDot.className = "absolute -bottom-1 -right-1 w-4 h-4 rounded-full bg-emerald-500 border-2 border-[var(--card)] flex items-center justify-center";
          statusDot.title = "System Bereit";
        }
        const totalBadge = document.getElementById("boardroom-total-badge");
        if (totalBadge) {
          totalBadge.innerText = "Bereit";
          totalBadge.className = "px-2 py-0.5 rounded-full text-[10px] font-mono font-bold bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/25 shrink-0";
        }
      }
    }
    function renderBoardroomThread(data) {
      const threadDiv = document.getElementById("boardroom-thread");
      if (!threadDiv) return;
      threadDiv.innerHTML = "";
      // Header Banner
      const headerBanner = document.createElement("div");
      headerBanner.className = "rounded-lg p-4 bg-[var(--card)] border border-[var(--border)] text-xs space-y-1 mb-4 font-mono text-[var(--foreground)]";
      headerBanner.innerHTML = `
        <div class="flex items-center justify-between text-[var(--foreground)] font-bold uppercase tracking-wider">
          <span>📋 BOARDROOM DEBATTE: ${data.task}</span>
          <span>CHAIRMAN: ${data.chairman ? data.chairman.name : 'Moderator'}</span>
        </div>
        <div class="text-[10px] text-muted-custom">
          Max Runden: ${data.max_rounds} | Framework: ${data.framework || 'Steffi Kieffer Boardroom'} | OmniRoute Gateway Active
        </div>
      `;
      threadDiv.appendChild(headerBanner);
      let currentRound = 0;
      data.events.forEach(ev => {
        if (ev.round && ev.round !== currentRound) {
          currentRound = ev.round;
          const divider = document.createElement("div");
          divider.className = "flex items-center gap-3 my-4";
          divider.innerHTML = `
            <div class="flex-1 h-[1px] bg-neutral-800"></div>
            <span class="text-[10px] font-mono font-bold tracking-widest uppercase px-3 py-1 rounded bg-neutral-900 border theme-border accent-color">
              ⚡ DEBATE ROUND ${currentRound} OF ${data.max_rounds}
            </span>
            <div class="flex-1 h-[1px] bg-neutral-800"></div>
          `;
          threadDiv.appendChild(divider);
        }
        if (ev.type === "consensus_reached") {
          const alertBox = document.createElement("div");
          alertBox.className = "rounded-md p-3 bg-[var(--secondary)] border border-[var(--border)] text-[var(--foreground)] font-mono text-xs font-semibold flex items-center gap-2 my-2";
          alertBox.innerHTML = `<i data-lucide="check-circle" class="w-4 h-4"></i> <span>${ev.content}</span>`;
          threadDiv.appendChild(alertBox);
          return;
        }
        if (ev.type === "final_synthesis") {
          const synthCard = document.createElement("div");
          synthCard.className = "rounded-xl p-6 bg-[var(--card)] border border-[var(--border)] space-y-4 my-6 shadow-md";
          
          synthCard.innerHTML = `
            <div class="flex items-center justify-between border-b theme-border pb-3">
              <h3 class="text-sm font-bold uppercase tracking-wider accent-color flex items-center gap-2">
                <i data-lucide="award" class="w-4 h-4 text-black dark:text-white"></i> FINALE SYNTHESE & AKTIONSPLAN
              </h3>
              <span class="text-[10px] font-mono px-2.5 py-0.5 rounded bg-indigo-500/10 border border-indigo-500/20 accent-color font-bold">${ev.agent_name} (${ev.role})</span>
            </div>
            <div class="text-xs leading-relaxed text-primary-custom whitespace-pre-wrap font-sans font-medium">
              ${ev.content}
            </div>
          `;
          threadDiv.appendChild(synthCard);
          return;
        }
        // Standard Agent Chat Message
        const card = document.createElement("div");
        const isChairman = ev.type === "chairman_init" || ev.agent_id === (data.chairman ? data.chairman.id : "");
        
        card.className = `rounded-xl p-3.5 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 transition-all space-y-2 ${isChairman ? 'ring-1 ring-indigo-500/30' : ''}`;
        let msgAvatarUrl = '/static/avatars/avatar_001.jpg';
        if (typeof getProfileAvatarUrl === 'function') {
          const foundProf = (typeof hermesProfilesData !== 'undefined' && hermesProfilesData) ? hermesProfilesData.find(p => p.id === ev.agent_id || p.name === ev.agent_name) : null;
          msgAvatarUrl = getProfileAvatarUrl(foundProf || { id: ev.agent_id || ev.agent_name });
        }
        card.innerHTML = `
          <div class="flex items-center justify-between border-b border-slate-100 dark:border-neutral-800 pb-2">
            <div class="flex items-center gap-2.5">
              <img src="${msgAvatarUrl}" alt="${ev.agent_name || 'Agent'}" class="w-8 h-8 rounded-full object-cover border border-slate-300 dark:border-neutral-700 shadow-xs shrink-0" onerror="this.src='/static/avatars/avatar_001.jpg'">
              <div>
                <div class="flex items-center gap-2">
                  <span class="text-xs font-bold text-slate-800 dark:text-slate-200">${ev.agent_name}</span>
                  <span class="text-[10px] font-mono px-2 py-0.5 rounded-md bg-slate-100 dark:bg-neutral-800 text-slate-600 dark:text-neutral-400 border border-slate-200 dark:border-neutral-700 font-medium">${ev.role}</span>
                  ${isChairman ? '<span class="text-[9.5px] font-mono font-bold px-2 py-0.5 rounded-md bg-indigo-500/10 text-indigo-500 border border-indigo-500/20">MODERATOR</span>' : ''}
                </div>
                <div class="text-[9.5px] text-slate-400 dark:text-neutral-500 font-mono mt-0.5">Modell: ${ev.model || 'free-forever'}</div>
              </div>
            </div>
          </div>
          <div class="text-xs leading-relaxed text-slate-700 dark:text-slate-300 whitespace-pre-wrap pt-1 font-sans font-medium">
            ${ev.content}
          </div>
        `;
        threadDiv.appendChild(card);
      });
      lucide.createIcons();
      threadDiv.scrollTop = threadDiv.scrollHeight;
    }
    function clearBoardroomThread() {
      const threadDiv = document.getElementById("boardroom-thread");
      if (threadDiv) {
        threadDiv.innerHTML = `
          <div class="h-full flex flex-col items-center justify-center text-center p-6 text-slate-400 dark:text-neutral-500">
            <div class="w-12 h-12 rounded-full bg-slate-100 dark:bg-neutral-800 flex items-center justify-center mb-3">
              <i data-lucide="message-square" class="w-6 h-6 text-slate-400"></i>
            </div>
            <p class="text-xs font-semibold text-slate-600 dark:text-neutral-300">Noch keine Boardroom-Debatte aktiv</p>
            <p class="text-[11px] text-slate-400 dark:text-neutral-500 mt-1 max-w-sm">Gib oben deine Fragestellung ein, wähle rechts die Methodik und klicke auf "Debatte starten".</p>
          </div>
        `;
        lucide.createIcons();
      }
    }

    // =========================================================================
    // OPENROUTER & LLM PREIS-KATALOG MODAL CONTROLLER
    // =========================================================================
    let _currentPriceModalTargetEl = null;
    let _cachedPriceModalList = [];

    function _findPriceCatalogProviderSelect(modelSelectEl) {
      if (!modelSelectEl) return null;
      const targetId = modelSelectEl.id;
      if (targetId === "prof-edit-model") {
        return document.getElementById("prof-edit-provider");
      } else if (targetId === "agent-tab-model-select") {
        return document.getElementById("agent-tab-provider-select");
      } else if (targetId === "master-chat-model-select") {
        return document.getElementById("master-chat-provider-select");
      } else if (targetId === "boardroom-chair-model-select") {
        return document.getElementById("boardroom-chair-provider-select");
      } else if (modelSelectEl.closest && modelSelectEl.closest(".boardroom-slot-row")) {
        return modelSelectEl.closest(".boardroom-slot-row").querySelector(".boardroom-slot-provider-select");
      }
      return null;
    }

    function _syncPriceModalProviderSelect(targetSelectEl) {
      const modalProvSelect = document.getElementById("llm-price-provider-select");
      if (!modalProvSelect) return;
      const callerProvSelect = _findPriceCatalogProviderSelect(targetSelectEl);
      if (callerProvSelect && callerProvSelect.options && callerProvSelect.options.length > 0) {
        const currentCallerVal = callerProvSelect.value || "openrouter";
        modalProvSelect.innerHTML = "";
        Array.from(callerProvSelect.options).forEach(opt => {
          const clone = document.createElement("option");
          clone.value = opt.value;
          clone.textContent = opt.textContent;
          if (opt.value === currentCallerVal) clone.selected = true;
          modalProvSelect.appendChild(clone);
        });
        modalProvSelect.value = currentCallerVal;
      } else if (!modalProvSelect.value) {
        modalProvSelect.value = "openrouter";
      }
    }

    function onPriceModalProviderChange(providerVal) {
      // Routing-Provider-Wechsel behält die Katalogsuche unverändert und wendet den Provider beim Klick auf "Wählen" an.
      filterPriceModalTable();
    }
    window.onPriceModalProviderChange = onPriceModalProviderChange;

    async function openPriceCatalogModal(targetSelectEl, initialFilter = "") {
      _currentPriceModalTargetEl = targetSelectEl;
      _syncPriceModalProviderSelect(targetSelectEl);
      if (typeof window.loadAgentTabModelPrices === 'function') {
        await window.loadAgentTabModelPrices();
      }
      
      let pricesMap = {};
      try {
        const res = await fetch("/api/llm-providers/prices");
        if (res.ok) {
          const d = await res.json();
          if (d && d.prices) pricesMap = d.prices;
        }
      } catch (e) {
        console.warn("Could not fetch latest prices for modal:", e);
      }

      _cachedPriceModalList = Object.entries(pricesMap).map(([id, info]) => {
        return {
          id: id,
          name: info.name || id,
          prompt_1m: info.prompt_1m || 0,
          completion_1m: info.completion_1m || 0,
          context_length: info.context_length || 0,
          vendor: id.includes('/') ? id.split('/')[0] : 'other'
        };
      });

      // Hersteller/Vendor-Dropdown befüllen (unabhängig vom Routing-Provider)
      const vendorSelect = document.getElementById("llm-price-vendor-select");
      if (vendorSelect) {
        const vendors = Array.from(new Set(_cachedPriceModalList.map(m => m.vendor))).filter(Boolean).sort();
        vendorSelect.innerHTML = '<option value="" selected>Hersteller: Alle</option>';
        vendors.forEach(v => {
          const opt = document.createElement("option");
          opt.value = v;
          opt.textContent = v.charAt(0).toUpperCase() + v.slice(1);
          vendorSelect.appendChild(opt);
        });
      }

      const modal = document.getElementById("llm-price-catalog-modal");
      const searchInput = document.getElementById("llm-price-search");
      if (searchInput) {
        // Standardmäßig leer lassen, damit alle Modelle sofort sichtbar sind
        searchInput.value = initialFilter || "";
      }
      filterPriceModalTable();
      if (modal) modal.classList.remove("hidden");
      if (window.lucide) window.lucide.createIcons();
    }
    window.openPriceCatalogModal = openPriceCatalogModal;

    function closePriceCatalogModal() {
      const modal = document.getElementById("llm-price-catalog-modal");
      if (modal) modal.classList.add("hidden");
      _currentPriceModalTargetEl = null;
    }
    window.closePriceCatalogModal = closePriceCatalogModal;

    function setPriceModalFilter(chip) {
      const searchInput = document.getElementById("llm-price-search");
      const vendorSelect = document.getElementById("llm-price-vendor-select");
      if (!searchInput) return;

      if (chip === 'all') {
        searchInput.value = "";
        if (vendorSelect) vendorSelect.value = "";
      } else if (chip === 'free') {
        searchInput.value = "free";
      } else if (chip === 'cheap') {
        searchInput.value = "cheap";
      } else {
        // Vendor-Filter gezielt ansprechen falls vorhanden
        if (vendorSelect) {
          const matchingOpt = Array.from(vendorSelect.options).find(o => o.value.toLowerCase().includes(chip.toLowerCase()));
          if (matchingOpt) {
            vendorSelect.value = matchingOpt.value;
            searchInput.value = "";
          } else {
            searchInput.value = chip;
          }
        } else {
          searchInput.value = chip;
        }
      }
      filterPriceModalTable();
    }
    window.setPriceModalFilter = setPriceModalFilter;

    function filterPriceModalTable() {
      const searchInput = document.getElementById("llm-price-search");
      const vendorSelect = document.getElementById("llm-price-vendor-select");
      const selectedVendor = vendorSelect ? vendorSelect.value.toLowerCase().trim() : "";
      const query = (searchInput ? searchInput.value : "").toLowerCase().trim();
      const tbody = document.getElementById("llm-price-table-body");
      const countEl = document.getElementById("llm-price-modal-count");
      if (!tbody) return;
      tbody.innerHTML = "";

      let filtered = _cachedPriceModalList;
      if (selectedVendor) {
        filtered = filtered.filter(m => m.vendor.toLowerCase() === selectedVendor);
      }
      if (query === "free") {
        filtered = filtered.filter(m => m.prompt_1m === 0 && m.completion_1m === 0);
      } else if (query === "cheap") {
        filtered = filtered.filter(m => m.prompt_1m > 0 && m.prompt_1m <= 0.5);
      } else if (query) {
        filtered = filtered.filter(m => 
          m.id.toLowerCase().includes(query) || 
          m.name.toLowerCase().includes(query) || 
          m.vendor.toLowerCase().includes(query)
        );
      }

      // Sort options: price_asc, price_desc, alpha_asc, context_desc
      const sortSelect = document.getElementById("llm-price-sort");
      const sortMode = sortSelect ? sortSelect.value : "price_asc";
      filtered.sort((a, b) => {
        if (sortMode === "alpha_asc") {
          return (a.id || "").localeCompare(b.id || "", undefined, { sensitivity: "base" });
        } else if (sortMode === "price_desc") {
          return (b.prompt_1m || 0) - (a.prompt_1m || 0);
        } else if (sortMode === "context_desc") {
          return (b.context_length || 0) - (a.context_length || 0);
        } else {
          // price_asc (0 / Free first)
          if (a.prompt_1m === 0 && b.prompt_1m > 0) return -1;
          if (b.prompt_1m === 0 && a.prompt_1m > 0) return 1;
          return (a.prompt_1m || 0) - (b.prompt_1m || 0);
        }
      });

      if (countEl) {
        countEl.innerText = `${filtered.length} von ${_cachedPriceModalList.length} Modellen`;
      }

      if (filtered.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6" class="py-8 text-center text-xs text-[var(--muted-foreground)]">Keine Modelle für diese Auswahl gefunden.</td></tr>`;
        return;
      }

      const fmt = typeof window.formatPricePer1M === "function" ? window.formatPricePer1M : (v => (v || 0).toFixed(4));

      filtered.slice(0, 150).forEach(m => {
        const tr = document.createElement("tr");
        tr.className = "hover:bg-[var(--secondary)]/60 border-b border-[var(--border)] transition text-xs";
        const ctx = m.context_length ? (m.context_length >= 1000000 ? `${(m.context_length/1000000).toFixed(1)}M` : `${Math.round(m.context_length/1000)}k`) : '—';
        const isFree = (m.prompt_1m === 0 && m.completion_1m === 0);
        
        tr.innerHTML = `
          <td class="py-2.5 px-3 font-mono">
            <div class="font-bold text-[var(--foreground)] truncate max-w-[280px]" title="${m.id}">${m.id}</div>
            <div class="text-[10px] text-[var(--muted-foreground)] truncate max-w-[280px]">${m.name}</div>
          </td>
          <td class="py-2.5 px-3 font-mono">
            <span class="px-2 py-0.5 rounded text-[10px] font-mono font-bold uppercase bg-[var(--secondary)] border border-[var(--border)] text-[var(--foreground)] truncate max-w-[110px] inline-block">
              ${m.vendor}
            </span>
          </td>
          <td class="py-2.5 px-3 font-mono text-[11px] text-[var(--muted-foreground)]">${ctx}</td>
          <td class="py-2.5 px-3 font-mono text-right ${isFree ? 'text-emerald-500 font-bold' : 'text-emerald-600 dark:text-emerald-400 font-bold'}">
            ${isFree ? 'Kostenlos' : '$' + fmt(m.prompt_1m)}
          </td>
          <td class="py-2.5 px-3 font-mono text-right ${isFree ? 'text-emerald-500 font-bold' : 'text-amber-500 font-bold'}">
            ${isFree ? 'Kostenlos' : '$' + fmt(m.completion_1m)}
          </td>
          <td class="py-2.5 px-3 text-right">
            <button type="button" onclick="selectModelFromPriceCatalog('${m.id}')" class="px-2.5 py-1 rounded-md bg-[var(--foreground)] text-[var(--background)] hover:opacity-90 transition font-mono text-[11px] font-bold cursor-pointer shadow-2xs">
              Wählen
            </button>
          </td>
        `;
        tbody.appendChild(tr);
      });
    }
    window.filterPriceModalTable = filterPriceModalTable;

    async function selectModelFromPriceCatalog(modelId) {
      const modalProvSelect = document.getElementById("llm-price-provider-select");
      let chosenProvider = modalProvSelect ? modalProvSelect.value : "openrouter";
      let chosenProviderLabel = modalProvSelect && modalProvSelect.selectedIndex >= 0
        ? modalProvSelect.options[modalProvSelect.selectedIndex].textContent
        : "OpenRouter";

      if (_currentPriceModalTargetEl) {
        const sel = _currentPriceModalTargetEl;
        const provSelect = _findPriceCatalogProviderSelect(sel);
        if (provSelect) {
          if (chosenProvider && Array.from(provSelect.options).some(o => o.value === chosenProvider)) {
            provSelect.value = chosenProvider;
          } else {
            chosenProvider = provSelect.value || chosenProvider;
          }
        }

        const targetId = sel.id;
        if (targetId === "prof-edit-model" && typeof window.onProfileProviderChange === "function") {
          await window.onProfileProviderChange(chosenProvider, modelId);
          if (typeof window.applyProfileModelSelection === "function") {
            await window.applyProfileModelSelection();
          }
        } else if (targetId === "agent-tab-model-select" && typeof window.onAgentTabProviderChange === "function") {
          await window.onAgentTabProviderChange(chosenProvider, modelId);
        } else if (targetId === "master-chat-model-select" && typeof window.onMasterChatProviderChanged === "function") {
          await window.onMasterChatProviderChanged(chosenProvider, modelId);
        } else if (targetId === "boardroom-chair-model-select" && typeof window.setupBoardroomChairmanModelDropdown === "function") {
          await window.setupBoardroomChairmanModelDropdown(chosenProvider, modelId);
        } else if (sel.closest && sel.closest(".boardroom-slot-row") && typeof window.setupBoardroomSlotModelDropdown === "function") {
          await window.setupBoardroomSlotModelDropdown(sel, chosenProvider, modelId);
        } else {
          let found = false;
          for (let i = 0; i < sel.options.length; i++) {
            if (sel.options[i].value === modelId) {
              sel.selectedIndex = i;
              found = true;
              break;
            }
          }
          if (!found) {
            const opt = document.createElement("option");
            opt.value = modelId;
            opt.textContent = modelId;
            sel.appendChild(opt);
            opt.selected = true;
          }
          sel.dispatchEvent(new Event("change", { bubbles: true }));
          if (provSelect) {
            provSelect.dispatchEvent(new Event("change", { bubbles: true }));
          }
        }
      }
      if (typeof showArchonToast === "function") {
        showArchonToast(`Modell '${modelId}' (${chosenProviderLabel}) übernommen.`, "success");
      }
      closePriceCatalogModal();
    }
    window.selectModelFromPriceCatalog = selectModelFromPriceCatalog;

    function openPriceCatalogForChairman() {
      const modelSelect = document.getElementById("boardroom-chair-model-select");
      openPriceCatalogModal(modelSelect, "");
    }
    window.openPriceCatalogForChairman = openPriceCatalogForChairman;

    function openPriceCatalogForSlot(btn) {
      const row = btn.closest('.boardroom-slot-row');
      if (!row) return;
      const modelSelect = row.querySelector('.boardroom-slot-model-select');
      openPriceCatalogModal(modelSelect, "");
    }
    window.openPriceCatalogForSlot = openPriceCatalogForSlot;

    function openPriceCatalogForProfileEditor() {
      const modelSelect = document.getElementById("prof-edit-model");
      openPriceCatalogModal(modelSelect, "");
    }
    window.openPriceCatalogForProfileEditor = openPriceCatalogForProfileEditor;

    function openPriceCatalogForAgentTab() {
      const modelSelect = document.getElementById("agent-tab-model-select");
      openPriceCatalogModal(modelSelect, "");
    }
    window.openPriceCatalogForAgentTab = openPriceCatalogForAgentTab;

    async function handleSidebarPresetSelected(serviceId) {
      if (!serviceId) return;
      const service = servicesList.find(s => s.id === serviceId);
      if (!service) return;
      let existing = agents.find(a => a.id === service.id);
      if (!existing) {
        const roleObj = roles.find(r => r.name === service.role) || roles[0];
        existing = {
          id: service.id,
          name: service.name,
          model: service.model || "free-forever",
          role: service.role || "Custom",
          prompt: roleObj ? roleObj.prompt : "Du bist ein hilfreicher KI-Agent.",
          active: true
        };
        agents.push(existing);
        await saveAgentsToServer();
      } else {
        existing.active = true;
        await saveAgentsToServer();
      }
      renderAgentsSidebar();
      renderAgentRegistryTable();
      // Docker-Container physisch über den Docker Socket auf dem Host starten!
      fetch("/api/docker/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ container_name: service.container_name || service.id, id: service.id })
      }).catch(e => console.error("Error starting docker container:", e));
      openTerminalForAgent(existing.id);
      const select = document.getElementById("agent-presets-sidebar-select");
      if (select) select.value = "";
    }
    function detectContainerPort(agent) {
      if (!agent) return "8082";
      if (agent.web_ui_port) return String(agent.web_ui_port);
      if (agent.dashboard_port) return String(agent.dashboard_port);
      
      const idStr = (agent.id || agent.name || agent.container_name || "").toLowerCase();
      const knownPorts = {
        "gpt-researcher": "8000",
        "researcher": "8000",
        "openhands": "3000",
        "crewai-flowise": "3001",
        "flowise": "3001",
        "crewai": "3001",
        "open-webui": "8082",
        "webui": "8082",
        "autogen-studio": "8083",
        "autogen": "8083",
        "openclaw": "18789",
        "claw": "18789",
        "hermes-dashboard-proxy": "9119",
        "hermes-dashboard": "9119",
        "hermes-dash": "9119",
        "hermes": "9119",
        "odysseus-agent": "7000",
        "odysseus-odysseus-1": "7000",
        "odysseus-1": "7000",
        "odysseus": "7000",
        "omniroute": "20128",
        "espocrm": "8081",
        "agent-os-container": "8501"
      };
      for (const [key, port] of Object.entries(knownPorts)) {
        if (idStr.includes(key)) return port;
      }
      if (agent.port && String(agent.port) !== "0") {
        return String(agent.port);
      }
      return "8082";
    }
    function populateCreateAgentTemplatesAndContainers() {
      const SYSTEM_INTERNAL_IDS = ["agent-os-container", "agent-os-ui", "agent-os", "agent_os", "agent_os_ui", "agent_os_container"];
      // 1. Agent ID (Docker Container) Dropdown belegen (NUR gekoppelte & aktive Container)
      const cSelect = document.getElementById("new-agent-id");
      if (cSelect) {
        cSelect.innerHTML = '';
        const activeCoupled = servicesList.filter(s => {
          if (SYSTEM_INTERNAL_IDS.includes((s.id || '').toLowerCase())) return false;
          return (s.active === true || s.coupled === true);
        });
        if (activeCoupled.length === 0) {
          const opt = document.createElement("option");
          opt.value = "";
          opt.innerText = "Keine gekoppelten aktiven Container";
          opt.disabled = true;
          opt.selected = true;
          cSelect.appendChild(opt);
        } else {
          activeCoupled.forEach(s => {
            const opt = document.createElement("option");
            opt.value = s.id;
            opt.innerText = `${s.id} (${s.name})`;
            cSelect.appendChild(opt);
          });
        }
      }
      // 2. Rolle (Master Prompt) Dropdown belegen mit ALLEN 24 KI-Rollen aus rolesList
      const rSelect = document.getElementById("new-agent-role");
      if (rSelect) {
        rSelect.innerHTML = '';
        const sourceRoles = (typeof rolesList !== 'undefined' && rolesList && rolesList.length > 0) ? rolesList : [
          { name: "Orchestrator & System-Architekt" }, { name: "Product Manager / Requirements Engineer" },
          { name: "Agile Scrum Master / Task Triage Manager" }, { name: "Enterprise Architect" },
          { name: "Technical Writer & Documentation Specialist" }, { name: "Prompt & AI Systems Engineer" },
          { name: "Senior Coder / Software Engineer" }, { name: "Frontend & UI/UX Architect" },
          { name: "Backend & Database Designer" }, { name: "Refactoring & Clean Code Expert" },
          { name: "DevOps & Container Specialist" }, { name: "QA & Automated Testing Engineer" },
          { name: "Security Auditor / DevSecOps" }, { name: "Data Protection & Compliance Officer (DSGVO)" },
          { name: "Performance & Benchmarking Auditor" }, { name: "Fact-Checker & Logic Validator" },
          { name: "Dependency & Supply Chain Auditor" }, { name: "Skeptic / Devil's Advocate" },
          { name: "Researcher & Data Analyst" }, { name: "Market & Competitor Intelligence Analyst" },
          { name: "SEO & Content Pipeline Specialist" }, { name: "Outreach & Lead Gen Automator" },
          { name: "Financial & Cost Optimizer" }, { name: "Growth & UX Conversion Strategist" }
        ];
        
        sourceRoles.forEach(r => {
          const opt = document.createElement("option");
          opt.value = r.name || r.id;
          opt.innerText = r.name || r.id;
          rSelect.appendChild(opt);
        });
      }
    }
    function handleDockerContainerSelectChange(containerId) {
      const service = servicesList.find(s => s.id === containerId);
      if (service) {
        const nameEl = document.getElementById("new-agent-name");
        if (nameEl) nameEl.value = service.name || containerId;
        const modelEl = document.getElementById("new-agent-model");
        if (modelEl && service.model) modelEl.value = service.model;
        const roleEl = document.getElementById("new-agent-role");
        if (roleEl && service.role) roleEl.value = service.role;
      }
    }
    function applyTemplateToFields(serviceId) {
      const service = servicesList.find(s => s.id === serviceId);
      if (service) {
        const cSelect = document.getElementById("new-agent-id");
        if (cSelect) cSelect.value = service.id;
        const nameEl = document.getElementById("new-agent-name");
        if (nameEl) nameEl.value = service.name;
        const modelEl = document.getElementById("new-agent-model");
        if (modelEl && service.model) modelEl.value = service.model;
        const roleEl = document.getElementById("new-agent-role");
        if (roleEl && service.role) roleEl.value = service.role;
      }
    }
    function openCreateAgentModal() {
      if (typeof switchView === "function") switchView("agent-profiles");
      if (typeof createNewAgentProfile === "function") createNewAgentProfile();
    }
    function closeCreateAgentModal() {}
    async function submitCreateAgent() {
      const idEl = document.getElementById("new-agent-id");
      const nameEl = document.getElementById("new-agent-name");
      const modelEl = document.getElementById("new-agent-model");
      const roleEl = document.getElementById("new-agent-role");
      if (!idEl || !nameEl) return;
      const id = idEl.value.trim();
      const name = nameEl.value.trim();
      const model = modelEl ? modelEl.value : "";
      const role = roleEl ? roleEl.value : "";
      if (!id || !name) {
        alert("Bitte wählen Sie einen Docker-Container und geben Sie einen Namen an.");
        return;
      }
      const roleObj = roles.find(r => r.name === role) || roles[0];
      const prompt = roleObj ? roleObj.prompt : "Du bist ein hilfreicher KI-Agent im System.";
      let existing = agents.find(a => a.id === id);
      if (existing) {
        existing.name = name;
        existing.model = model;
        existing.role = role;
        existing.prompt = prompt;
        existing.active = true;
      } else {
        agents.push({
          id,
          name,
          model,
          role,
          prompt,
          active: true
        });
      }
      // Service in servicesList ebenfalls auf active = true setzen und speichern
      const targetService = servicesList.find(s => s.id === id);
      if (targetService) {
        targetService.active = true;
        await fetch("/api/v1/services", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(servicesList)
        });
      }
      // Docker-Container physisch über den Docker Socket auf dem Host starten!
      fetch("/api/docker/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ container_name: id, id: id })
      }).catch(e => console.error("Error starting docker container:", e));
      await saveAgentsToServer();
      renderAgentsSidebar();
      renderAgentRegistryTable();
      renderSidebarPresetsSelect();
      openTerminalForAgent(id);
      
      closeCreateAgentModal();
    }
    function renderAgentsSidebar() {
      const listDiv = document.getElementById("sidebar-agents-nodes");
      if (!listDiv) return;
      listDiv.innerHTML = "";
      
      agents.forEach((agent, index) => {
        const card = document.createElement("div");
        card.className = "daw-card flex gap-3 items-start relative text-xs cursor-pointer hover:border-accent-color transition-colors";
        // Make the entire card open the terminal/chat
        card.onclick = (e) => openTerminalForAgent(agent.id, e);
        
        const isHermesEngine = (agent.engine === "hermes" || (agent.id && agent.id.toLowerCase().includes("hermes")));
        const ledClass = agent.active ? "daw-led-active" : "daw-led-idle";
        
        let roleOptionsHtml = "";
        roles.forEach(r => {
          const selected = (agent.role === r.name || agent.role === r.id) ? "selected" : "";
          roleOptionsHtml += `<option value="${r.id}" ${selected}>${r.name}</option>`;
        });
        
        let modelOptionsHtml = "";
        modelsList.forEach(m => {
          const selected = agent.model === m ? "selected" : "";
          modelOptionsHtml += `<option value="${m}" ${selected}>${m}</option>`;
        });
        
        card.innerHTML = `
          <div class="flex-1 min-w-0 flex flex-col p-1 space-y-2">
            <!-- Header Row -->
            <div class="flex items-center justify-between mb-1">
              <input type="text" value="${agent.name}" onchange="updateAgentField('${agent.id}', 'name', this.value); event.stopPropagation();" onclick="event.stopPropagation();" class="daw-input-name focus:outline-none focus:bg-neutral-900/40 text-[13px] font-bold" placeholder="Agent Name">
              <div class="flex items-center gap-1.5">
                ${isHermesEngine ? '<span class="px-1.5 py-0.5 rounded text-[9px] font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">● Aktiv via Hermes</span>' : ''}
                <div class="daw-led ${ledClass} relative w-2.5 h-2.5 rounded-full flex-shrink-0 ml-1" style="position:static;" title="Status: ${agent.active ? 'Active/Running' : 'Idle'}"></div>
              </div>
            </div>
            
            <!-- Grid for Dropdowns -->
            <div class="grid grid-cols-[70px_1fr] items-center gap-2 mb-1" onclick="event.stopPropagation();">
              <span class="text-[10px] text-muted-custom">Sprachmodell</span>
              <select onchange="updateAgentField('${agent.id}', 'model', this.value)" class="daw-select cursor-pointer py-0.5 px-1 bg-neutral-900/5 border-none">
                ${modelOptionsHtml}
              </select>
              
              <span class="text-[10px] text-muted-custom">Rolle</span>
              <select onchange="handleAgentRoleChange('${agent.id}', this.value)" class="daw-select cursor-pointer py-0.5 px-1 bg-neutral-900/5 border-none">
                ${roleOptionsHtml}
                <option disabled>──────────</option>
                <option value="manage_roles">⚙️ Rollen verwalten...</option>
              </select>
            </div>
            
            <!-- Icon Action Row -->
            <div class="flex items-center justify-end gap-3 pt-2 mt-2 border-t border-black/5 dark:border-white/5" onclick="event.stopPropagation();">
              <button onclick="openEditPresetModalForAgent('${agent.id}')" class="hover:text-accent-color text-muted-custom transition-colors" title="Preset laden/bearbeiten">
                <i data-lucide="folder-open" class="w-3.5 h-3.5"></i>
              </button>
              <button onclick="saveAgentsToServer()" class="hover:text-accent-color text-muted-custom transition-colors" title="Preset speichern">
                <i data-lucide="save" class="w-3.5 h-3.5"></i>
              </button>
              <button onclick="toggleAgentActive('${agent.id}')" class="hover:text-amber-500 text-muted-custom transition-colors" title="${agent.active ? 'Pausieren' : 'Starten'}">
                <i data-lucide="${agent.active ? 'pause' : 'play'}" class="w-3.5 h-3.5"></i>
              </button>
              <button onclick="restartAgent('${agent.name}')" class="hover:text-accent-color text-muted-custom transition-colors" title="Zurücksetzen / Neustart">
                <i data-lucide="rotate-ccw" class="w-3.5 h-3.5"></i>
              </button>
              <button onclick="unloadAgent('${agent.id}')" class="hover:text-red-500 text-muted-custom transition-colors" title="Unload / Stoppen">
                <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
              </button>
            </div>
          </div>
        `;
        listDiv.appendChild(card);
      });
      lucide.createIcons();
    }
      // NATIVE MASTER CHAT EXTRACTED TO js/chat_engine.js