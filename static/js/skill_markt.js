
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
          const logRow = `<div class="flex gap-3">
            <span class="text-label-custom flex-shrink-0 font-mono">${time}</span>
            <span class="${nameColorClass} font-mono flex-shrink-0 w-24 truncate">System</span>
            <span class="${msgColorClass} flex-1 leading-relaxed">${msg}</span>
          </div>`;
          
          if (logDiv.innerHTML.includes("Connecting to") || logDiv.innerHTML.includes("Heartbeat OK")) {
            logDiv.innerHTML = logRow;
          } else {
            logDiv.innerHTML += logRow;
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
        document.getElementById("agent-preset-select").value = selectedPresetId;
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
        agents = loadedAgents.filter(a => a.active !== false && !SYSTEM_INTERNAL_IDS.includes((a.id || '').toLowerCase()));
        
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
      "Steffi Kieffer Boardroom": [
        { role_name: "Skeptiker & Risikoprüfer", default_profile: "devils_advocate" },
        { role_name: "Innovator & Chancen-Scout", default_profile: "enterprise_architect" },
        { role_name: "Pragmatiker & Implementierer", default_profile: "senior_coder" }
      ],
      "Six Thinking Hats (Edward de Bono)": [
        { role_name: "⚪ Weißer Hut (Fakten & Daten)", default_profile: "researcher" },
        { role_name: "🔴 Roter Hut (Gefühle & Intuition)", default_profile: "product_manager" },
        { role_name: "🖤 Schwarzer Hut (Risiken & Kritik)", default_profile: "devils_advocate" },
        { role_name: "🟡 Gelber Hut (Chancen & Optimismus)", default_profile: "financial_optimizer" },
        { role_name: "🟢 Grüner Hut (Kreativität & Ideen)", default_profile: "frontend_architect" }
      ],
      "SWOT / TOWS": [
        { role_name: "Stärken (Interne Ressourcen & Code)", default_profile: "senior_coder" },
        { role_name: "Schwächen (Tech-Debt & Lücken)", default_profile: "clean_code_expert" },
        { role_name: "Chancen (Markttrends & Scale)", default_profile: "market_intelligence" },
        { role_name: "Risiken (Security, Compliance & DSGVO)", default_profile: "security_auditor" }
      ],
      "Red Teaming / Adversarial Attack": [
        { role_name: "Red Team (Angriffsvektoren)", default_profile: "security_auditor" },
        { role_name: "Blue Team (Härtung & Defensive)", default_profile: "senior_coder" }
      ],
      "Design Sprint (GV / Jake Knapp)": [
        { role_name: "Map & Decide (Product Requirements)", default_profile: "product_manager" },
        { role_name: "Sketch & Prototype (UX/UI)", default_profile: "frontend_architect" },
        { role_name: "Tech Builder & Code", default_profile: "senior_coder" },
        { role_name: "Test & Validation (QA)", default_profile: "qa_test_engineer" }
      ],
      "Double Diamond (Design Council)": [
        { role_name: "Discover (Marktforscher & Discovery)", default_profile: "researcher" },
        { role_name: "Define (Problem-Spezifikation)", default_profile: "product_manager" },
        { role_name: "Develop & Deliver (Software Engineer)", default_profile: "senior_coder" }
      ],
      "DMAIC (Six Sigma)": [
        { role_name: "Define & Measure (Performance)", default_profile: "performance_auditor" },
        { role_name: "Analyze & Improve (Refactoring)", default_profile: "clean_code_expert" },
        { role_name: "Control & Standards (DevOps)", default_profile: "devops_container" }
      ],
      "Theory of Constraints (TOC)": [
        { role_name: "Engpass-Analyst (Bottlenecks)", default_profile: "performance_auditor" },
        { role_name: "Durchsatz-Optimierer (Dev)", default_profile: "senior_coder" }
      ],
      "Eisenhower-Matrix": [
        { role_name: "Do First (Sofortige Umsetzung)", default_profile: "senior_coder" },
        { role_name: "Schedule (Architektur-Planung)", default_profile: "enterprise_architect" },
        { role_name: "Delegate (Automatisierung)", default_profile: "devops_container" }
      ],
      "Pre-Mortem Analyse": [
        { role_name: "Todesursachen-Analyst (Failure Modes)", default_profile: "devils_advocate" },
        { role_name: "Präventiv-Schützer (Defense)", default_profile: "security_auditor" }
      ]
    };
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
    function renderBoardroomSlots(frameworkName) {
      const container = document.getElementById("boardroom-slots-list");
      if (!container) return;
      container.innerHTML = "";
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
      lucide.createIcons();
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
    }
    function onBoardroomChairmanChange() {
      const select = document.getElementById("boardroom-chairman-select");
      const img = document.getElementById("boardroom-chair-avatar");
      const descEl = document.getElementById("boardroom-chair-desc");
      const catEl = document.getElementById("boardroom-chair-cat");
      const personEl = document.getElementById("boardroom-chair-person");
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
      if (descEl) descEl.innerText = foundProf ? (foundProf.description || '') : 'Zentrales Master-System für die Leitung und Synthese der Debatte.';
      if (catEl) catEl.innerText = foundProf ? (foundProf.category || '1. Strategie') : '1. Strategie';
      if (personEl) personEl.innerText = foundProf ? (foundProf.person_name ? foundProf.person_name.split(' ')[0] : 'Michael') : 'Michael';
    }
    function addBoardroomSlotElement(roleName, profileId, slotNumber) {
      const container = document.getElementById("boardroom-slots-list");
      if (!container) return;
      const foundProf = (typeof hermesProfilesData !== 'undefined' && hermesProfilesData && hermesProfilesData.length > 0)
        ? (hermesProfilesData.find(p => p.id === profileId) || hermesProfilesData.find(p => p.name === profileId) || hermesProfilesData[Math.min(slotNumber || 1, hermesProfilesData.length - 1)])
        : null;
      
      const actualId = foundProf ? foundProf.id : profileId;
      let avatarUrl = '/static/avatars/avatar_001.jpg';
      if (typeof getProfileAvatarUrl === 'function') {
        avatarUrl = getProfileAvatarUrl(foundProf || { id: actualId });
      }
      const firstName = foundProf && foundProf.person_name ? foundProf.person_name.split(' ')[0] : '';
      const row = document.createElement("div");
      row.className = "boardroom-slot-row p-2 rounded-xl border border-[var(--border)] bg-[var(--card)] space-y-1 text-xs relative group hover:border-[var(--muted-foreground)] transition";
      row.innerHTML = `
        <div class="flex items-center justify-between gap-1.5 border-b border-[var(--border)] pb-1">
          <div class="flex items-center gap-1.5 flex-1 min-w-0">
            <span class="w-2 h-2 rounded-full bg-zinc-400 shrink-0"></span>
            <input type="text" value="${roleName}" class="boardroom-slot-role-name bg-transparent font-bold text-xs prof-title-text border-b border-dashed border-[var(--border)] focus:outline-none focus:border-[var(--foreground)] px-1 py-0.5 flex-1 truncate" placeholder="Slot-Rolle (z.B. Skeptiker)..." title="Rollen-Bezeichnung im Framework anpassen">
          </div>
          <button onclick="this.closest('.boardroom-slot-row').remove()" class="text-[var(--muted-foreground)] hover:text-[var(--foreground)] p-1 rounded-md cursor-pointer transition text-xs" title="Diesen Slot entfernen">
            <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
          </button>
        </div>
        <div class="flex items-start gap-2.5 pt-0.5">
          <div class="flex flex-col items-center shrink-0">
            <img src="${avatarUrl}" alt="Avatar" class="boardroom-slot-avatar w-10 h-10 rounded-xl object-cover border border-[var(--border)] shrink-0 shadow-xs" onerror="this.src='/static/avatars/avatar_001.jpg'">
            <span class="boardroom-slot-person text-[9px] font-bold text-[var(--foreground)] mt-1 max-w-[55px] text-center truncate">${firstName}</span>
          </div>
          <div class="flex-1 min-w-0">
            <select onchange="updateBoardroomSlotCard(this)" class="boardroom-slot-profile-select w-full bg-[var(--background)] border border-[var(--border)] rounded-lg px-2 py-1 text-xs prof-title-text focus:outline-none cursor-pointer truncate font-bold shadow-xs">
              ${getRoleOptionsHtml(actualId)}
            </select>
            <p class="boardroom-slot-desc text-[10.5px] text-[var(--muted-foreground)] mt-0.5 leading-snug line-clamp-2">${foundProf?.description || 'Fach-Agent für diese Debatten-Position.'}</p>
            <span class="boardroom-slot-cat inline-block text-[9px] font-mono text-[var(--foreground)] bg-[var(--secondary)] px-1.5 py-0.5 rounded mt-0.5 border border-[var(--border)] truncate max-w-[180px]">${foundProf?.category || ''}</span>
          </div>
        </div>
      `;
      container.appendChild(row);
      lucide.createIcons();
    }
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
    async function runBoardroomDebate() {
      const taskInput = document.getElementById("boardroom-task");
      const roundsInput = document.getElementById("boardroom-rounds");
      const chairmanSelect = document.getElementById("boardroom-chairman-select");
      const frameworkSelect = document.getElementById("boardroom-framework-select");
      const startBtn = document.getElementById("boardroom-start-btn");
      const loadingDiv = document.getElementById("boardroom-loading");
      const task = taskInput ? taskInput.value.trim() : "";
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
        return {
          role_name: roleInput ? (roleInput.value.trim() || `Experte ${idx + 1}`) : `Experte ${idx + 1}`,
          profile_id: profileSelect ? profileSelect.value : "senior_coder"
        };
      });
      if (startBtn) startBtn.disabled = true;
      if (loadingDiv) {
        loadingDiv.classList.remove("hidden");
        document.getElementById("boardroom-loading-status").innerText = `AI Boardroom Debatte wird mit ${slots.length + 1} Profilen ausgeführt (${frameworkVal}, ${rounds} Runden)...`;
      }
      try {
        const response = await fetch("/api/boardroom/stream", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ task, rounds, chairman_id: chairmanId, framework: frameworkVal, slots, reasoning_level: (document.getElementById("boardroom-reasoning-select") && document.getElementById("boardroom-reasoning-select").value) || "profile" })
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
              if (ev.type === "start") {
                boardMeta = ev;
                if (threadDiv) {
                  const headerBanner = document.createElement("div");
                  headerBanner.className = "rounded-lg p-4 bg-[var(--card)] border border-[var(--border)] text-xs space-y-1 mb-4 font-mono text-[var(--foreground)]";
                  headerBanner.innerHTML = `
                    <div class="flex items-center justify-between text-[var(--foreground)] font-bold uppercase tracking-wider">
                      <span>📋 BOARDROOM DEBATTE: ${ev.task}</span>
                      <span>CHAIRMAN: ${ev.chairman ? ev.chairman.name : 'Moderator'}</span>
                    </div>
                    <div class="text-[10px] text-muted-custom">
                      Max Runden: ${ev.max_rounds} | Framework: ${ev.framework || 'Steffi Kieffer Boardroom'} | Live Streaming aktiv
                    </div>
                  `;
                  threadDiv.appendChild(headerBanner);
                }
              } else if (ev.type === "round_start") {
                if (threadDiv && ev.round && ev.round !== currentRound) {
                  currentRound = ev.round;
                  const divider = document.createElement("div");
                  divider.className = "flex items-center gap-3 my-4 animate-fade-in";
                  divider.innerHTML = `
                    <div class="flex-1 h-[1px] bg-neutral-800"></div>
                    <span class="text-[10px] font-mono font-bold tracking-widest uppercase px-3 py-1 rounded bg-neutral-900 border theme-border accent-color">
                      ⚡ DEBATE ROUND ${currentRound} OF ${boardMeta.max_rounds}
                    </span>
                    <div class="flex-1 h-[1px] bg-neutral-800"></div>
                  `;
                  threadDiv.appendChild(divider);
                  threadDiv.scrollTop = threadDiv.scrollHeight;
                }
              } else if (ev.type === "consensus_reached") {
                if (threadDiv) {
                  const alertBox = document.createElement("div");
                  alertBox.className = "rounded-md p-3 bg-[var(--secondary)] border border-[var(--border)] text-[var(--foreground)] font-mono text-xs font-semibold flex items-center gap-2 my-2 animate-fade-in";
                  alertBox.innerHTML = `<i data-lucide="check-circle" class="w-4 h-4"></i> <span>${ev.content}</span>`;
                  threadDiv.appendChild(alertBox);
                  if (window.lucide) window.lucide.createIcons();
                  threadDiv.scrollTop = threadDiv.scrollHeight;
                }
              } else if (ev.type === "final_synthesis") {
                if (threadDiv) {
                  const synthCard = document.createElement("div");
                  synthCard.className = "rounded-xl p-6 bg-[var(--card)] border border-[var(--border)] space-y-4 my-6 shadow-md animate-fade-in";
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
                  if (window.lucide) window.lucide.createIcons();
                  threadDiv.scrollTop = threadDiv.scrollHeight;
                }
              } else if (ev.type === "chairman_init" || ev.type === "agent_response") {
                if (threadDiv) {
                  const card = document.createElement("div");
                  const isChairman = ev.type === "chairman_init" || ev.agent_id === (boardMeta.chairman ? boardMeta.chairman.id : "");
                  card.className = `rounded-xl p-3.5 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 transition-all space-y-2 my-2 animate-fade-in ${isChairman ? 'ring-1 ring-indigo-500/30' : ''}`;
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
                      <span class="text-[10px] font-mono text-slate-400 dark:text-neutral-500">${new Date().toLocaleTimeString()}</span>
                    </div>
                    <div class="text-xs leading-relaxed text-slate-700 dark:text-slate-300 whitespace-pre-wrap font-sans font-normal pt-1">
                      ${ev.content}
                    </div>
                  `;
                  threadDiv.appendChild(card);
                  if (window.lucide) window.lucide.createIcons();
                  threadDiv.scrollTop = threadDiv.scrollHeight;
                }
              } else if (ev.type === "done") {
                if (document.getElementById("boardroom-loading-status")) {
                  document.getElementById("boardroom-loading-status").innerText = "Debatte erfolgreich abgeschlossen!";
                }
              }
            } catch (err) {
              console.error("Parse SSE chunk error:", err);
            }
          }
        }
      } catch (e) {
        console.error("Boardroom debate error:", e);
        alert(`Verbindungsfehler: ${e.message}`);
      } finally {
        if (startBtn) startBtn.disabled = false;
        if (loadingDiv) loadingDiv.classList.add("hidden");
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
        document.getElementById("new-agent-name").value = service.name || containerId;
        if (service.model) document.getElementById("new-agent-model").value = service.model;
        if (service.role) document.getElementById("new-agent-role").value = service.role;
      }
    }
    function applyTemplateToFields(serviceId) {
      const service = servicesList.find(s => s.id === serviceId);
      if (service) {
        const cSelect = document.getElementById("new-agent-id");
        if (cSelect) cSelect.value = service.id;
        document.getElementById("new-agent-name").value = service.name;
        if (service.model) document.getElementById("new-agent-model").value = service.model;
        if (service.role) document.getElementById("new-agent-role").value = service.role;
      }
    }
    function openCreateAgentModal() {
      if (typeof switchView === "function") switchView("agent-profiles");
      if (typeof createNewAgentProfile === "function") createNewAgentProfile();
    }
    function closeCreateAgentModal() {}
    async function submitCreateAgent() {
      const id = document.getElementById("new-agent-id").value.trim();
      const name = document.getElementById("new-agent-name").value.trim();
      const model = document.getElementById("new-agent-model").value;
      const role = document.getElementById("new-agent-role").value;
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