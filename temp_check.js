
    let currentTab = "mission-control";
    let theme = "light";
    let agents = [];
    let roles = [];
    let modelsList = [];
    let kanbanCards = [];
    let vaultFiles = [];
    let loadedFilePath = "";
    let servicesList = [];
    let activeSettingsTab = "services";

    // Status mapping für Farben und Labels
    const statusColor = {
      active: "#22c55e",
      running: "#6b7cff",
      idle: "#9ca3af",
      paused: "#f59e0b",
      inactive: "#9ca3af"
    };

    window.onload = async () => {
      // Wende Initialtheme an
      document.documentElement.setAttribute('data-theme', theme);
      updateThemeUI();

      await loadRolesFromServer();
      await loadModelsFromServer();
      await loadAgentsFromServer();
      await loadKanbanFromServer();
      await loadVaultFiles();
      setTab(currentTab);
      
      // Starte System Time
      setInterval(updateSystemTime, 1000);
      updateSystemTime();

      // Log ticker polling
      startLogPolling();
      
      // Metriken abfragen
      updateStats();
      setInterval(updateStats, 2000);
    };

    function updateSystemTime() {
      const now = new Date();
      document.getElementById("system-time").innerText = now.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    }

    // Theme Switcher
    function toggleTheme() {
      theme = theme === "dark" ? "light" : "dark";
      document.documentElement.setAttribute('data-theme', theme);
      updateThemeUI();
    }

    function updateThemeUI() {
      const icon = document.getElementById("theme-icon");
      const label = document.getElementById("theme-label");
      if (theme === "dark") {
        icon.setAttribute("data-lucide", "sun");
        label.innerText = "LIGHT";
      } else {
        icon.setAttribute("data-lucide", "moon");
        label.innerText = "DARK";
      }
      lucide.createIcons();
    }

    // Custom SPA Tab Navigation Router
    function setTab(tabId) {
      currentTab = tabId;
      
      // Verstecke alle Views inklusive des isolierten Agenten-Terminals
      document.getElementById("view-mission-control").classList.add("hidden");
      document.getElementById("view-paperclip").classList.add("hidden");
      document.getElementById("view-ai-mastermind").classList.add("hidden");
      document.getElementById("view-kanban").classList.add("hidden");
      document.getElementById("view-workspace-gallery").classList.add("hidden");
      const agentTermView = document.getElementById("view-agent-terminal");
      if (agentTermView) agentTermView.classList.add("hidden");

      // Stats Dashboard wird nur in der Mission Control Übersicht angezeigt
      const statsDash = document.getElementById("stats-dashboard");
      if (statsDash) {
        if (tabId === "mission-control") {
          statsDash.classList.remove("hidden");
        } else {
          statsDash.classList.add("hidden");
        }
      }

      // Zeige die ausgewählte View
      const selectedView = document.getElementById(`view-${tabId}`);
      if (selectedView) selectedView.classList.remove("hidden");

      // Sidebar Styling anpassen
      const navIds = {
        "mission-control": "nav-mission-control",
        "paperclip": "nav-paperclip",
        "ai-mastermind": "nav-ai-mastermind",
        "kanban": "nav-kanban",
        "workspace-gallery": "nav-workspace-gallery"
      };

      Object.keys(navIds).forEach(key => {
        const btn = document.getElementById(navIds[key]);
        const arrow = btn.querySelector('.active-arrow');
        if (key === tabId) {
          btn.style.backgroundColor = "var(--item-selected-bg)";
          btn.style.borderColor = "var(--item-selected-border)";
          btn.style.color = "var(--item-selected-text)";
          arrow.classList.remove("hidden");
        } else {
          btn.style.backgroundColor = "transparent";
          btn.style.borderColor = "transparent";
          btn.style.color = "var(--item-text)";
          arrow.classList.add("hidden");
        }
      });

      // Topbar Details
      const titleMap = {
        "mission-control": "Mission Control",
        "paperclip": "Paperclip Orchestrator",
        "ai-mastermind": "AI Mastermind",
        "kanban": "Kanban Pipeline",
        "workspace-gallery": "Workspace Gallery"
      };
      const iconMap = {
        "mission-control": "rocket",
        "paperclip": "paperclip",
        "ai-mastermind": "brain",
        "kanban": "columns",
        "workspace-gallery": "gallery-horizontal"
      };

      document.getElementById("topbar-title").innerText = titleMap[tabId];
      document.getElementById("topbar-icon").innerHTML = `<i data-lucide="${iconMap[tabId]}" class="w-4 h-4"></i>`;
      
      // Topbar Status
      const statusSpan = document.getElementById("topbar-status");
      if (tabId === "mission-control") {
        statusSpan.classList.remove("hidden");
      } else {
        statusSpan.classList.add("hidden");
      }

      if (tabId === "kanban") renderKanbanBoard();
      
      lucide.createIcons();
    }

    // --- LOG POLING ---
    // --- LOG POLING ---
    let logEventSource = null;
    function startLogPolling() {
      if (logEventSource) {
        logEventSource.close();
      }
      
      const logDiv = document.getElementById("system-log-body");
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
      
      document.getElementById("preset-modal-title").innerText = "Preset bearbeiten";
      document.getElementById("preset-modal-id").value = agent.id;
      document.getElementById("preset-modal-name").value = agent.name;
      document.getElementById("preset-modal-model").value = agent.model;
      document.getElementById("preset-modal-prompt").value = agent.prompt;
      document.getElementById("preset-modal-active").checked = agent.active || false;
      
      document.getElementById("preset-modal").classList.remove("hidden");
    }

    function openCreatePresetModal() {
      document.getElementById("preset-modal-title").innerText = "Neue Vorlage erstellen";
      document.getElementById("preset-modal-id").value = "new";
      document.getElementById("preset-modal-name").value = "Neue Vorlage";
      document.getElementById("preset-modal-model").value = "free-forever";
      document.getElementById("preset-modal-prompt").value = "";
      document.getElementById("preset-modal-active").checked = true;
      
      document.getElementById("preset-modal").classList.remove("hidden");
    }

    function closePresetModal() {
      document.getElementById("preset-modal").classList.add("hidden");
    }

    async function submitPresetModal() {
      const id = document.getElementById("preset-modal-id").value;
      const name = document.getElementById("preset-modal-name").value.trim();
      const model = document.getElementById("preset-modal-model").value.trim();
      const prompt = document.getElementById("preset-modal-prompt").value.trim();
      const active = document.getElementById("preset-modal-active").checked;
      
      if (!name) {
        alert("Der Name darf nicht leer sein.");
        return;
      }
      
      if (id === "new") {
        const newId = `A-0${agents.length + 1}`;
        agents.push({
          id: newId,
          name,
          model,
          prompt,
          active
        });
        selectedPresetId = newId;
      } else {
        const agent = agents.find(a => a.id === id);
        if (agent) {
          agent.name = name;
          agent.model = model;
          agent.prompt = prompt;
          agent.active = active;
        }
      }
      
      await saveAgentsToServer();
      await loadAgentsFromServer();
      closePresetModal();
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
    }

    async function deleteAgent(id) {
      agents = agents.filter(a => a.id !== id);
      await saveAgentsToServer();
      renderAgentsSidebar();
      renderAgentRegistryTable();
      renderSidebarPresetsSelect();
    }

    async function toggleAgentActive(id) {
      const agent = agents.find(a => a.id === id);
      if (agent) {
        agent.active = !agent.active;
        await saveAgentsToServer();
        renderAgentsSidebar();
        renderAgentRegistryTable();
      }
    }

    async function restartAgent(name) {
      await fetch("/api/outreach", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ platform: "System", target: name, message: "Agent manually restarted." })
      });
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
      }
    }

    async function updateStats() {
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
        if (avgUptimeEl) avgUptimeEl.innerText = `${data.average_uptime}s`;
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

    async function loadBoardroomFrameworks() {
      const select = document.getElementById("boardroom-framework-select");
      if (!select) return;
      try {
        const res = await fetch("/api/boardroom/frameworks");
        if (!res.ok) return;
        const categorized = await res.json();
        select.innerHTML = "";
        
        let isFirst = true;
        for (const [catName, frameworks] of Object.entries(categorized)) {
          const group = document.createElement("optgroup");
          group.label = catName;
          for (const [fwName, fwData] of Object.entries(frameworks)) {
            const opt = document.createElement("option");
            opt.value = fwName;
            opt.innerText = fwName;
            const summaryText = typeof fwData === "string" ? fwData : (fwData.summary || fwData.system_instruction || "");
            opt.title = summaryText;
            opt.setAttribute("data-summary", summaryText);
            if (isFirst) {
              opt.selected = true;
              isFirst = false;
            }
            group.appendChild(opt);
          }
          select.appendChild(group);
        }
        updateFrameworkSummaryTooltip();
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
        summaryEl.innerText = selectedOpt.getAttribute("data-summary") || selectedOpt.title || "";
      }
    }

    function populateBoardroomChairmanSelect() {
      const select = document.getElementById("boardroom-chairman-select");
      if (!select) return;
      select.innerHTML = "";
      if (agents.length === 0) {
        select.innerHTML = '<option value="" disabled selected>Keine aktiven Agenten</option>';
        return;
      }
      agents.forEach(agent => {
        const opt = document.createElement("option");
        opt.value = agent.id;
        opt.innerText = `${agent.name} (${agent.role || 'Orchestrator'})`;
        if (agent.id === "hermes" || agent.role === "Orchestrator") {
          opt.selected = true;
        }
        select.appendChild(opt);
      });
    }

    async function runBoardroomDebate() {
      const taskInput = document.getElementById("boardroom-task");
      const roundsInput = document.getElementById("boardroom-rounds");
      const chairmanSelect = document.getElementById("boardroom-chairman-select");
      const frameworkSelect = document.getElementById("boardroom-framework-select");
      const startBtn = document.getElementById("boardroom-start-btn");
      const loadingDiv = document.getElementById("boardroom-loading");

      const task = taskInput ? taskInput.value.trim() : "";
      const rounds = roundsInput ? parseInt(roundsInput.value) || 3 : 3;
      const chairmanId = chairmanSelect ? chairmanSelect.value : "";
      const frameworkVal = frameworkSelect ? frameworkSelect.value : "Steffi Kieffer Boardroom";

      if (!task) {
        alert("Bitte geben Sie eine strategische Aufgabenstellung für den Boardroom ein.");
        return;
      }

      if (startBtn) startBtn.disabled = true;
      if (loadingDiv) {
        loadingDiv.classList.remove("hidden");
        document.getElementById("boardroom-loading-status").innerText = `AI Boardroom Debatte wird ausgeführt (${frameworkVal}, ${rounds} Runden)...`;
      }

      try {
        const res = await fetch("/api/boardroom/run", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ task, rounds, chairman_id: chairmanId, framework: frameworkVal })
        });

        if (!res.ok) {
          const errData = await res.json();
          alert(`Fehler: ${errData.detail || 'Debatte konnte nicht gestartet werden.'}`);
          return;
        }

        const data = await res.json();
        renderBoardroomThread(data);
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
      headerBanner.className = "rounded-lg p-4 theme-card border border-indigo-500/30 text-xs space-y-1 mb-4 font-mono";
      headerBanner.innerHTML = `
        <div class="flex items-center justify-between text-indigo-400 font-bold uppercase tracking-wider">
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
          alertBox.className = "rounded-md p-3 bg-green-500/10 border border-green-500/30 text-green-400 font-mono text-xs font-semibold flex items-center gap-2 my-2";
          alertBox.innerHTML = `<i data-lucide="check-circle" class="w-4 h-4"></i> <span>${ev.content}</span>`;
          threadDiv.appendChild(alertBox);
          return;
        }

        if (ev.type === "final_synthesis") {
          const synthCard = document.createElement("div");
          synthCard.className = "rounded-xl p-6 theme-card border-2 border-indigo-500/50 shadow-2xl space-y-4 my-6";
          
          synthCard.innerHTML = `
            <div class="flex items-center justify-between border-b theme-border pb-3">
              <h3 class="text-sm font-bold uppercase tracking-wider accent-color flex items-center gap-2">
                <i data-lucide="award" class="w-4 h-4 text-yellow-500"></i> FINALE SYNTHESE & AKTIONSPLAN
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
        
        card.className = `rounded-lg p-4 theme-card border transition-all space-y-2 ${isChairman ? 'border-indigo-500/40' : 'theme-border'}`;

        const avatarColor = isChairman ? 'bg-indigo-500/10 text-indigo-500 border-indigo-500/30' : 'bg-emerald-500/10 text-emerald-500 border-emerald-500/30';

        card.innerHTML = `
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2.5">
              <div class="w-7 h-7 rounded-md flex items-center justify-center font-bold text-xs border ${avatarColor}">
                ${ev.agent_name ? ev.agent_name.substring(0, 2).toUpperCase() : 'AG'}
              </div>
              <div>
                <div class="flex items-center gap-2">
                  <span class="text-xs font-bold text-primary-custom">${ev.agent_name}</span>
                  <span class="text-[9px] font-mono px-1.5 py-0.2 rounded theme-card text-muted-custom border theme-border">${ev.role}</span>
                  ${isChairman ? '<span class="text-[9px] font-mono font-bold px-1.5 py-0.2 rounded bg-indigo-500/10 text-indigo-500 border border-indigo-500/20">MODERATOR</span>' : ''}
                </div>
                <div class="text-[9px] text-muted-custom font-mono">Modell: ${ev.model || 'free-forever'}</div>
              </div>
            </div>
          </div>
          <div class="text-xs leading-relaxed text-primary-custom whitespace-pre-wrap pt-1 font-sans">
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
          <div class="text-muted-custom text-center py-16 text-xs flex flex-col items-center gap-2">
            <i data-lucide="message-square" class="w-8 h-8 opacity-40"></i>
            <span>Noch keine Boardroom-Debatte gestartet. Gib oben eine Aufgabenstellung ein und klicke auf "Debatte".</span>
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

    function populateCreateAgentTemplatesAndContainers() {
      const SYSTEM_INTERNAL_IDS = ["agent-os-container", "agent-os-ui", "agent-os", "agent_os", "agent_os_ui", "agent_os_container"];

      // 1. Vorlage Laden (Template) Dropdown belegen
      const tSelect = document.getElementById("new-agent-template-select");
      if (tSelect) {
        tSelect.innerHTML = '<option value="" disabled selected>Wähle ein Template...</option>';
        servicesList.forEach(s => {
          if (!SYSTEM_INTERNAL_IDS.includes((s.id || '').toLowerCase())) {
            const opt = document.createElement("option");
            opt.value = s.id;
            opt.innerText = `${s.name} (${s.model || 'free-forever'} - ${s.role || 'Custom'})`;
            tSelect.appendChild(opt);
          }
        });
      }

      // 2. Agent ID (Docker Container) Dropdown belegen
      const cSelect = document.getElementById("new-agent-id");
      if (cSelect) {
        cSelect.innerHTML = '';
        servicesList.forEach(s => {
          if (!SYSTEM_INTERNAL_IDS.includes((s.id || '').toLowerCase())) {
            const opt = document.createElement("option");
            opt.value = s.id;
            const statusTag = s.active ? "🟢 LÄUFT" : "⚪ GESTOPPT";
            opt.innerText = `${s.id} (${s.name}) — ${statusTag}`;
            cSelect.appendChild(opt);
          }
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
      populateCreateAgentTemplatesAndContainers();
      
      const cSelect = document.getElementById("new-agent-id");
      if (cSelect && cSelect.options.length > 0) {
        cSelect.selectedIndex = 0;
        handleDockerContainerSelectChange(cSelect.value);
      }
      
      document.getElementById("create-agent-modal").classList.remove("hidden");
    }

    function closeCreateAgentModal() {
      document.getElementById("create-agent-modal").classList.add("hidden");
    }

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
        // Make the entire card open the terminal
        card.onclick = (e) => openTerminalForAgent(agent.id, e);
        
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
              <div class="daw-led ${ledClass} relative w-2.5 h-2.5 rounded-full flex-shrink-0 ml-2" style="position:static;" title="Status: ${agent.active ? 'Active/Running' : 'Idle'}"></div>
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

    let currentSelectedAgentId = "";

    function openTerminalForAgent(agentId, event) {
      if (event) event.stopPropagation();
      const agent = agents.find(a => a.id === agentId);
      if (!agent) return;
      
      currentSelectedAgentId = agent.id;

      // Docker-Container auf Host-System via API automatisch starten!
      fetch("/api/docker/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ container_name: agent.container_name || agent.id, id: agent.id })
      }).catch(e => console.error("Error starting docker container:", e));

      // 1. Haupt-Navigations-Items ent-markieren
      const navIds = ["nav-mission-control", "nav-paperclip", "nav-ai-mastermind", "nav-kanban", "nav-workspace-gallery"];
      navIds.forEach(id => {
        const btn = document.getElementById(id);
        if (btn) {
          btn.style.backgroundColor = "transparent";
          btn.style.borderColor = "transparent";
          btn.style.color = "var(--item-text)";
          const arrow = btn.querySelector('.active-arrow');
          if (arrow) arrow.classList.add("hidden");
        }
      });

      // 2. Mission Control Übersicht & Stats Dashboard komplett ausblenden
      document.getElementById("stats-dashboard").classList.add("hidden");
      document.getElementById("view-mission-control").classList.add("hidden");
      document.getElementById("view-paperclip").classList.add("hidden");
      document.getElementById("view-ai-mastermind").classList.add("hidden");
      document.getElementById("view-kanban").classList.add("hidden");
      document.getElementById("view-workspace-gallery").classList.add("hidden");

      // 3. Dedizierte Agenten-Terminal View einblenden
      const termView = document.getElementById("view-agent-terminal");
      if (termView) {
        termView.classList.remove("hidden");
      }

      // Topbar Titel & Status anpassen
      document.getElementById("topbar-title").innerText = `Agent: ${agent.name}`;
      document.getElementById("topbar-icon").innerHTML = `<i data-lucide="bot" class="w-4 h-4 text-accent-color"></i>`;
      const statusSpan = document.getElementById("topbar-status");
      if (statusSpan) statusSpan.classList.add("hidden");

      // Header Details im Terminal
      const titleEl = document.getElementById("agent-terminal-title");
      if (titleEl) titleEl.innerText = `Terminal: ${agent.name}`;

      const subEl = document.getElementById("agent-terminal-subtitle");
      if (subEl) {
        const displayModel = (agent.model && !agent.model.includes('/')) ? agent.model : "free-forever";
        const displayRole = (agent.role && !agent.role.includes('tcp')) ? agent.role : "Orchestrator";
        subEl.innerText = `ID: ${agent.id} | Modell: ${displayModel} | Rolle: ${displayRole}`;
      }

      const infoEl = document.getElementById("agent-terminal-docker-info");
      if (infoEl) {
        const activeHtml = agent.active 
          ? `<span class="bg-green-500/10 border border-green-500/20 px-2 py-0.5 rounded text-green-500 font-bold tracking-wider">AKTIV</span>`
          : `<span class="bg-yellow-500/10 border border-yellow-500/20 px-2 py-0.5 rounded text-yellow-500 font-bold tracking-wider">IDLE</span>`;
        
        const portMap = {
          "omniroute": "20128",
          "hermes-dashboard": "9119",
          "agent-os-container": "8501",
          "agent-os-ui": "8502",
          "sillytavern": "8000"
        };
        const port = agent.port || portMap[agent.id] || "8080";
        const containerUrl = agent.url || `http://localhost:${port}`;

        infoEl.innerHTML = `
          <div class="flex flex-col items-end gap-1.5 font-mono text-[10px]">
            <!-- Zeile 1: Container-Name + Web UI Button -->
            <div class="flex items-center gap-2">
              <span class="bg-neutral-900/10 border theme-border px-2 py-0.5 rounded text-secondary-custom font-bold">${agent.id}-container</span>
              <a href="${containerUrl}" target="_blank" rel="noopener noreferrer" class="bg-indigo-500/10 hover:bg-indigo-500/20 border border-indigo-500/30 px-2 py-0.5 rounded text-indigo-400 font-bold flex items-center gap-1 transition-colors" title="Eigenes Web UI im neuen Tab öffnen">
                <i data-lucide="external-link" class="w-3 h-3"></i> Web UI ↗
              </a>
            </div>
            <!-- Zeile 2: Port + Status Badge -->
            <div class="flex items-center gap-2">
              <span class="bg-neutral-900/10 border theme-border px-2 py-0.5 rounded text-secondary-custom flex items-center gap-1">
                <i data-lucide="split" class="w-3 h-3 text-muted-custom"></i> :${port}
              </span>
              ${activeHtml}
            </div>
          </div>
        `;
        lucide.createIcons();
      }

      // Prompt platzhalter & Fokus
      const promptEl = document.getElementById("agent-terminal-prompt");
      if (promptEl) {
        promptEl.placeholder = `Befehl an ${agent.name} senden...`;
        promptEl.focus();
      }
    }

    function handleAgentTerminalKey(e) {
      if (e.key === "Enter") {
        runAgentTerminalCommand();
      }
    }

    async function runAgentTerminalCommand() {
      const input = document.getElementById("agent-terminal-prompt");
      if (!input) return;
      let val = input.value.trim();
      if (!val) return;
      input.value = "";

      const agent = agents.find(a => a.id === currentSelectedAgentId) || agents[0];
      if (!agent) return;

      const consoleOut = document.getElementById("agent-terminal-console-output");
      const ts = new Date().toLocaleTimeString();

      function escapeHtml(str) {
        if (!str) return '';
        return String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
      }

      if (consoleOut) {
        consoleOut.innerHTML += `
          <div class="mt-3 text-white font-bold">&gt; USER @${agent.name}: ${escapeHtml(val)}</div>
          <div class="text-xs text-slate-400 font-mono flex items-center gap-2 mt-1" id="agent-terminal-pending-${agent.id}">
            <div class="animate-spin rounded-full h-3 w-3 border-b-2 border-green-400"></div>
            <span>[${ts}] Leite Anfrage an '${agent.id}' weiter...</span>
          </div>
        `;
        consoleOut.scrollTop = consoleOut.scrollHeight;
      }

      try {
        const res = await fetch("/api/run", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ prompt: `@${agent.id} ${val}` })
        });
        const results = await res.json();

        const pendingEl = document.getElementById(`agent-terminal-pending-${agent.id}`);
        if (pendingEl) pendingEl.remove();

        let reply = "";
        if (Array.isArray(results)) {
          const match = results.find(r => r.agent_id === agent.id) || results[0];
          reply = match ? match.content : JSON.stringify(results);
        } else {
          reply = results.content || JSON.stringify(results);
        }

        if (consoleOut) {
          consoleOut.innerHTML += `
            <div class="mt-2 text-green-300 whitespace-pre-wrap">[${ts}] ${agent.name}: ${escapeHtml(reply)}</div>
          `;
          consoleOut.scrollTop = consoleOut.scrollHeight;
        }
      } catch (err) {
        if (consoleOut) {
          consoleOut.innerHTML += `
            <div class="mt-2 text-red-400">[${ts}] Dispatcher Fehler: ${escapeHtml(err.message)}</div>
          `;
          consoleOut.scrollTop = consoleOut.scrollHeight;
        }
      }
    }

    async function unloadAgent(id) {
      if (!confirm("Soll der Agent-Docker-Container gestoppt (Unload) werden?")) return;
      
      // Logisch aus dem Stack entfernen oder inaktiveren
      agents = agents.filter(a => a.id !== id);
      await saveAgentsToServer();
      renderAgentsSidebar();
      renderAgentRegistryTable();
      renderSidebarPresetsSelect();
    }

    function handleAgentRoleChange(agentId, value) {
      if (value === "manage_roles") {
        openRoleManagerModal();
        renderAgentsSidebar(); // Render zurücksetzen
        return;
      }
      
      const agent = agents.find(a => a.id === agentId);
      const role = roles.find(r => r.id === value);
      if (agent && role) {
        agent.role = role.name;
        agent.prompt = role.prompt;
        saveAgentsToServer();
      }
    }

    function openEditPresetModalForAgent(agentId) {
      selectedPresetId = agentId;
      openEditPresetModal();
    }

    // --- ROLE MANAGER MODAL LOGIC ---
    let currentEditingRoleId = "";

    function openRoleManagerModal() {
      populateRoleManagerDropdown();
      if (roles.length > 0) {
        loadRoleIntoEditor(roles[0].id);
      } else {
        clearRoleEditorFields();
      }
      document.getElementById("role-manager-modal").classList.remove("hidden");
    }

    function closeRoleManagerModal() {
      document.getElementById("role-manager-modal").classList.add("hidden");
    }

    function populateRoleManagerDropdown() {
      const select = document.getElementById("role-manager-select");
      if (!select) return;
      select.innerHTML = "";
      
      roles.forEach(role => {
        const opt = document.createElement("option");
        opt.value = role.id;
        opt.innerText = role.name;
        if (role.id === currentEditingRoleId) {
          opt.selected = true;
        }
        select.appendChild(opt);
      });
    }

    function loadRoleIntoEditor(roleId) {
      currentEditingRoleId = roleId;
      const role = roles.find(r => r.id === roleId);
      if (role) {
        document.getElementById("role-manager-name").value = role.name;
        document.getElementById("role-manager-prompt").value = role.prompt;
      }
      const select = document.getElementById("role-manager-select");
      if (select) select.value = roleId;
    }

    function clearRoleEditorFields() {
      document.getElementById("role-manager-name").value = "";
      document.getElementById("role-manager-prompt").value = "";
    }

    async function saveRoleManagerChanges() {
      const name = document.getElementById("role-manager-name").value.trim();
      const prompt = document.getElementById("role-manager-prompt").value.trim();
      
      if (!name) {
        alert("Bitte einen Rollennamen eingeben.");
        return;
      }
      
      let role = roles.find(r => r.id === currentEditingRoleId);
      if (!role || currentEditingRoleId === "new") {
        const newId = `R-0${roles.length + 1}`;
        role = { id: newId, name, prompt };
        roles.push(role);
        currentEditingRoleId = newId;
      } else {
        role.name = name;
        role.prompt = prompt;
      }
      
      // Update prompts in agents that use this role!
      agents.forEach(agent => {
        if (agent.role === role.name || agent.role === role.id) {
          agent.prompt = prompt;
        }
      });
      
      await saveRolesToServer();
      await saveAgentsToServer();
      await loadAgentsFromServer();
      populateRoleManagerDropdown();
      loadRoleIntoEditor(currentEditingRoleId);
      alert("Rolle erfolgreich gespeichert und synchronisiert.");
    }

    function createNewRoleInManager() {
      currentEditingRoleId = "new";
      clearRoleEditorFields();
      document.getElementById("role-manager-name").placeholder = "z.B. Planner";
      document.getElementById("role-manager-name").focus();
      
      const select = document.getElementById("role-manager-select");
      if (select) {
        const opt = document.createElement("option");
        opt.value = "new";
        opt.innerText = "➕ Neue Rolle...";
        opt.selected = true;
        select.appendChild(opt);
      }
    }

    async function deleteSelectedRole() {
      if (!currentEditingRoleId || currentEditingRoleId === "new") return;
      const role = roles.find(r => r.id === currentEditingRoleId);
      if (!role) return;
      
      if (!confirm(`Möchten Sie die Rolle "${role.name}" wirklich löschen?`)) {
        return;
      }
      
      roles = roles.filter(r => r.id !== currentEditingRoleId);
      await saveRolesToServer();
      
      const defaultRole = roles.length > 0 ? roles[0].name : "Researcher";
      const defaultPrompt = roles.length > 0 ? roles[0].prompt : "";
      
      agents.forEach(agent => {
        if (agent.role === role.name) {
          agent.role = defaultRole;
          agent.prompt = defaultPrompt;
        }
      });
      await saveAgentsToServer();
      await loadAgentsFromServer();
      
      openRoleManagerModal();
    }

    async function resetRolesToDefault() {
      if (!confirm("Möchten Sie alle Rollen auf die Standardwerte zurücksetzen? Eigene Rollen gehen verloren.")) {
        return;
      }
      
      roles = [];
      await saveRolesToServer();
      await loadRolesFromServer();
      await loadAgentsFromServer();
      openRoleManagerModal();
    }

    async function loadRolesFromServer() {
      try {
        const res = await fetch("/api/roles");
        roles = await res.json();
      } catch (e) { console.error("Error loading roles:", e); }
    }

    async function saveRolesToServer() {
      try {
        await fetch("/api/roles", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(roles)
        });
      } catch (e) { console.error("Error saving roles:", e); }
    }

    async function loadModelsFromServer() {
      try {
        const res = await fetch("/api/models");
        modelsList = await res.json();
      } catch (e) {
        modelsList = ["free-forever", "gpt-4o", "gpt-4o-mini", "claude-3-5-sonnet", "hermes-3", "gemini-1.5-pro"];
      }
    }

    function renderAgentRegistryTable() {
      const tbody = document.getElementById("agent-registry-body");
      tbody.innerHTML = "";
      if (agents.length === 0) {
        tbody.innerHTML = `<tr><td colspan="7" class="px-4 py-8 text-center text-xs text-muted-custom">No deployed agents. Click Deploy to add slots.</td></tr>`;
        return;
      }

      agents.forEach(agent => {
        const tr = document.createElement("tr");
        tr.className = "border-b theme-border hover:bg-neutral-800/10 transition-colors";
        
        const status = agent.active ? "running" : "idle";
        const dotColor = statusColor[status];
        
        tr.innerHTML = `
          <td class="px-4 py-3 text-xs font-mono text-label-custom">${agent.id}</td>
          <td class="px-4 py-3 text-xs font-semibold text-secondary-custom">
            <input type="text" value="${agent.name}" onchange="updateAgentField('${agent.id}', 'name', this.value)" class="bg-transparent border-none text-xs font-semibold focus:outline-none w-24 text-secondary-custom">
          </td>
          <td class="px-4 py-3 text-xs font-mono text-muted-custom">
            <input type="text" value="${agent.model}" onchange="updateAgentField('${agent.id}', 'model', this.value)" class="bg-transparent border-none text-xs font-mono focus:outline-none w-28 text-muted-custom">
          </td>
          <td class="px-4 py-3">
            <div class="flex items-center gap-1.5">
              <span class="w-1.5 h-1.5 rounded-full flex-shrink-0" style="background: ${dotColor}; box-shadow: 0 0 5px ${dotColor}"></span>
              <span class="text-[10px] uppercase font-mono tracking-wider" style="color: ${dotColor}">${status}</span>
            </div>
          </td>
          <td class="px-4 py-3 text-xs text-muted-custom">${agent.active ? '12' : '0'}</td>
          <td class="px-4 py-3 text-xs font-mono text-label-custom">${agent.active ? '2h 10m' : '—'}</td>
          <td class="px-4 py-3">
            <div class="flex items-center gap-1.5">
              <button onclick="toggleAgentActive('${agent.id}')" class="p-1 rounded hover:bg-black/10 transition-colors" title="${agent.active ? 'Pause' : 'Start'}">
                <i data-lucide="${agent.active ? 'pause' : 'play'}" class="w-3.5 h-3.5 text-muted-custom"></i>
              </button>
              <button onclick="restartAgent('${agent.name}')" class="p-1 rounded hover:bg-black/10 transition-colors" title="Restart">
                <i data-lucide="rotate-ccw" class="w-3.5 h-3.5 text-muted-custom"></i>
              </button>
              <button onclick="alert('System Prompt: ' + '${agent.prompt}')" class="p-1 rounded hover:bg-black/10 transition-colors" title="System Prompt">
                <i data-lucide="more-horizontal" class="w-3.5 h-3.5 text-muted-custom"></i>
              </button>
            </div>
          </td>
        `;
        tbody.appendChild(tr);
      });
      lucide.createIcons();
    }

    // --- MISSION CONTROL PARALLEL execution ---
    // --- MISSION CONTROL PARALLEL execution ---
    function renderMixerOutputs(targetAgentId) {
      const grid = document.getElementById("mission-control-output-grid");
      grid.innerHTML = "";
      
      let targets = [];
      if (targetAgentId) {
        const found = agents.find(a => a.id === targetAgentId);
        if (found) targets.push(found);
      } else {
        targets = agents.filter(a => a.active);
      }
      
      if (targets.length === 0) return;

      targets.forEach(agent => {
        const col = document.createElement("div");
        col.className = "w-80 flex-shrink-0 rounded-lg border theme-border p-4 theme-card flex flex-col h-72";
        col.innerHTML = `
          <h4 class="text-xs font-bold text-accent-color border-b theme-border pb-1.5 mb-3 flex justify-between items-center">
            <span>👤 ${agent.name}</span>
            <span class="text-[9px] font-mono text-label-custom">${agent.model}</span>
          </h4>
          <div class="flex-1 overflow-y-auto text-xs text-secondary-custom whitespace-pre-wrap leading-relaxed" id="mc-output-${agent.id}">
            <span class="text-muted-custom italic">Warte auf Eingabe...</span>
          </div>
        `;
        grid.appendChild(col);
      });
    }

    async function handlePromptKey(e) {
      if (e.key === "Enter") {
        runGlobalCommand();
      }
    }

    async function runGlobalCommand() {
      const input = document.getElementById("global-prompt");
      let val = input.value.trim();
      if (!val) return;
      input.value = "";

      let targetAgentId = "";

      // 1. Prüfe auf @-Prefix zur Adressierung
      if (val.startsWith("@")) {
        const parts = val.split(" ");
        targetAgentId = parts[0].substring(1);
        val = parts.slice(1).join(" ");
      } else {
        // Fallback: Dropdown-Preset
        const select = document.getElementById("agent-preset-select");
        if (select) {
          targetAgentId = select.value;
        }
      }

      if (!targetAgentId) {
        alert("Bitte wählen Sie einen Agenten im Dropdown aus oder geben Sie ein @id Präfix ein.");
        return;
      }

      const agent = agents.find(a => a.id === targetAgentId);
      if (!agent) {
        alert(`Der Agent mit der ID '${targetAgentId}' wurde im System nicht gefunden.`);
        return;
      }

      // Spalte im UI vorbereiten
      renderMixerOutputs(agent.id);
      
      const outDiv = document.getElementById(`mc-output-${agent.id}`);
      if (outDiv) {
        outDiv.innerHTML = `
          <div class="flex items-center gap-2 text-muted-custom text-xs">
            <div class="animate-spin rounded-full h-3 w-3 border-b-2 border-accent-color"></div>
            <span>Agenten-Prozess wird gestartet...</span>
          </div>
        `;
      }

      try {
        // Manifest-Formatierung für den Deploy-Aufruf (Schicht 11)
        const manifestContent = `---
agent_id: ${agent.id}
name: ${agent.name}
base_model: ${agent.model}
mcp_tools: [${agent.mcp_tools ? agent.mcp_tools.join(", ") : "read_file, write_file"}]
privilege_group: ${agent.privilege_group || "developer"}
---
${agent.prompt}`;

        // Deployen
        await fetch("/api/v1/deploy", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ manifest_content: manifestContent })
        });

        // Ausführen
        const execRes = await fetch("/api/v1/execute", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ agent_id: agent.id, prompt: val })
        });
        const execData = await execRes.json();

        if (outDiv) {
          outDiv.innerHTML = `
            <div class="text-[10px] text-green-500 font-mono mb-1">PROZESS GESTARTET</div>
            <div class="text-[10px] text-slate-400 font-mono">Task: ${execData.task_id}</div>
            <div class="mt-2 leading-relaxed">Der Task wurde im Kernel eingereiht und läuft im Hintergrund. Du kannst den Status oben in der Tabelle verfolgen!</div>
          `;
        }
      } catch (err) {
        if (outDiv) {
          outDiv.innerHTML = `<span class="text-red-500">Fehler: ${err.message}</span>`;
        }
      }
    }

    // --- PAPERCLIP ORCHESTRATOR ---
    async function runPaperclip() {
      const task = document.getElementById("paperclip-task").value.trim();
      if (!task) return;

      document.getElementById("paperclip-loading").classList.remove("hidden");
      document.getElementById("paperclip-results").classList.add("hidden");

      try {
        const res = await fetch("/api/paperclip", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ prompt: task })
        });
        
        if (res.ok) {
          const data = await res.json();
          document.getElementById("paperclip-plan-output").innerText = data.plan;
          document.getElementById("paperclip-exec-output").innerText = data.exec;
          document.getElementById("paperclip-results").classList.remove("hidden");
        } else {
          const err = await res.json();
          alert(`Fehler: ${err.detail}`);
        }
      } catch (e) {
        alert("Verbindungsfehler.");
      } finally {
        document.getElementById("paperclip-loading").classList.add("hidden");
      }
    }

    // --- AI MASTERMIND ---
    async function runMastermind() {
      const prompt = document.getElementById("mastermind-prompt").value.trim();
      const rounds = parseInt(document.getElementById("mastermind-rounds").value) || 1;
      if (!prompt) return;

      const thread = document.getElementById("mastermind-thread");
      thread.innerHTML = `
        <div class="flex items-center gap-2 text-muted-custom text-xs justify-center py-12">
          <div class="animate-spin rounded-full h-4 w-4 border-b-2 border-accent-color"></div>
          <span>Diskussion läuft im Loop...</span>
        </div>
      `;

      try {
        const res = await fetch("/api/mastermind", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ prompt, rounds })
        });
        const history = await res.json();
        
        thread.innerHTML = "";
        history.forEach(msg => {
          const card = document.createElement("div");
          card.className = "rounded-lg p-3 border theme-border theme-card space-y-1";
          card.innerHTML = `
            <div class="flex justify-between items-center">
              <strong class="text-xs text-primary-custom">👤 ${msg.agent_name}</strong>
              <span class="text-[10px] text-label-custom font-mono">${msg.timestamp}</span>
            </div>
            <div class="text-xs text-secondary-custom whitespace-pre-wrap leading-relaxed">${msg.content}</div>
          `;
          thread.appendChild(card);
        });
      } catch (e) {
        thread.innerHTML = `<span class="text-red-500 text-xs">Fehler bei Verbindung.</span>`;
      }
    }

    function clearMastermind() {
      document.getElementById("mastermind-thread").innerHTML = "<div class='text-muted-custom text-center py-8 text-xs'>Diskussionsverlauf geleert.</div>";
    }

    // --- KANBAN BOARD ---
    async function loadKanbanFromServer() {
      try {
        const res = await fetch("/api/kanban");
        kanbanCards = await res.json();
      } catch (e) {}
    }

    async function saveKanbanToServer() {
      await fetch("/api/kanban", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(kanbanCards)
      });
    }

    function renderKanbanBoard() {
      const cols = {
        "📥 Backlog": "kanban-col-backlog",
        "⚙️ Building": "kanban-col-building",
        "👀 Human Review": "kanban-col-review",
        "🚀 Deployed": "kanban-col-deployed"
      };

      Object.values(cols).forEach(id => document.getElementById(id).innerHTML = "");

      kanbanCards.forEach(card => {
        const div = document.createElement("div");
        div.className = "p-3 rounded border theme-border theme-card text-xs space-y-2";
        div.innerHTML = `
          <div class="font-bold text-accent-color">${card.title}</div>
          <div class="text-muted-custom leading-normal whitespace-pre-wrap">${card.content}</div>
          <div class="flex justify-between items-center pt-1 border-t theme-border">
            <button onclick="moveCard('${card.id}', 'left')" class="hover:text-accent-color">◀</button>
            <button onclick="deleteCard('${card.id}')" class="hover:text-red-500">🗑️</button>
            <button onclick="moveCard('${card.id}', 'right')" class="hover:text-accent-color">▶</button>
          </div>
        `;
        const colDiv = document.getElementById(cols[card.column]);
        if (colDiv) colDiv.appendChild(div);
      });
    }

    function moveCard(cardId, dir) {
      const card = kanbanCards.find(c => c.id === cardId);
      if (!card) return;
      const statuses = ["📥 Backlog", "⚙️ Building", "👀 Human Review", "🚀 Deployed"];
      const idx = statuses.indexOf(card.column);

      if (dir === 'left' && idx > 0) {
        card.column = statuses[idx - 1];
      } else if (dir === 'right' && idx < statuses.length - 1) {
        card.column = statuses[idx + 1];
      }

      saveKanbanToServer();
      renderKanbanBoard();
    }

    function deleteCard(cardId) {
      kanbanCards = kanbanCards.filter(c => c.id !== cardId);
      saveKanbanToServer();
      renderKanbanBoard();
    }

    function openNewTaskModal() {
      document.getElementById("new-task-modal").classList.remove("hidden");
    }
    function closeNewTaskModal() {
      document.getElementById("new-task-modal").classList.add("hidden");
    }

    async function submitNewTask() {
      const title = document.getElementById("new-task-title").value.trim();
      const content = document.getElementById("new-task-content").value.trim();
      const platform = document.getElementById("new-task-platform").value;
      const target = document.getElementById("new-task-target").value.trim();

      if (!title || !content) return;

      await fetch("/api/outreach", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ platform, target, message: content })
      });

      kanbanCards.push({
        id: "m_" + Date.now(),
        title,
        content,
        column: "📥 Backlog"
      });

      await saveKanbanToServer();
      renderKanbanBoard();
      closeNewTaskModal();
    }

    // --- WORKSPACE GALLERY & SANDBOX ---
    let activeGallerySubTab = "vault";

    function setGallerySubTab(tab) {
      activeGallerySubTab = tab;
      const tabVaultBtn = document.getElementById("gallery-sub-vault");
      const tabSandboxBtn = document.getElementById("gallery-sub-sandbox");
      
      if (tab === "vault") {
        document.getElementById("gallery-subview-vault").classList.remove("hidden");
        document.getElementById("gallery-subview-sandbox").classList.add("hidden");
        tabVaultBtn.className = "py-2 px-4 text-xs font-bold border-b-2 border-accent-color text-primary-custom";
        tabSandboxBtn.className = "py-2 px-4 text-xs font-bold border-b-2 border-transparent text-muted-custom";
        loadVaultFiles();
      } else {
        document.getElementById("gallery-subview-vault").classList.add("hidden");
        document.getElementById("gallery-subview-sandbox").classList.remove("hidden");
        tabVaultBtn.className = "py-2 px-4 text-xs font-bold border-b-2 border-transparent text-muted-custom";
        tabSandboxBtn.className = "py-2 px-4 text-xs font-bold border-b-2 border-accent-color text-primary-custom";
      }
    }

    async function loadVaultFiles() {
      try {
        const res = await fetch("/api/vault");
        vaultFiles = await res.json();
        const select = document.getElementById("vault-select");
        select.innerHTML = "";

        if (vaultFiles.length === 0) {
          select.innerHTML = "<option>Keine Dateien</option>";
          document.getElementById("vault-editor").value = "";
          document.getElementById("markdown-preview-container").classList.add("hidden");
          return;
        }

        vaultFiles.forEach(file => {
          const opt = document.createElement("option");
          opt.value = file.path;
          opt.innerText = `${file.type}: ${file.name}`;
          select.appendChild(opt);
        });

        loadFile(vaultFiles[0].path);
      } catch (e) {}
    }

    async function loadFile(path) {
      if (!path || path === "Keine Dateien" || path.startsWith("Keine")) return;
      loadedFilePath = path;
      const file = vaultFiles.find(f => f.path === path);

      try {
        const res = await fetch(`/api/vault/file?path=${encodeURIComponent(path)}`);
        const data = await res.json();

        const editor = document.getElementById("vault-editor");
        editor.value = data.content;

        const previewContainer = document.getElementById("markdown-preview-container");
        if (file && file.type === "Obsidian MD") {
          previewContainer.classList.remove("hidden");
          document.getElementById("markdown-preview").innerText = data.content;
        } else {
          previewContainer.classList.add("hidden");
        }
      } catch (e) {
        console.error("Error loading file:", e);
      }
    }

    async function saveFile() {
      if (!loadedFilePath) return;
      const content = document.getElementById("vault-editor").value;
      try {
        const res = await fetch("/api/vault/edit", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path: loadedFilePath, content })
        });
        if (res.ok) {
          alert("Datei erfolgreich gespeichert!");
          const file = vaultFiles.find(f => f.path === loadedFilePath);
          if (file && file.type === "Obsidian MD") {
            document.getElementById("markdown-preview").innerText = content;
          }
        } else {
          alert("Fehler beim Speichern der Datei.");
        }
      } catch (e) {
        alert("Fehler: " + e.message);
      }
    }

    async function deleteFile() {
      if (!loadedFilePath) return;
      if (!confirm("Möchten Sie diese Datei wirklich löschen?")) return;
      try {
        const res = await fetch(`/api/vault?path=${encodeURIComponent(loadedFilePath)}`, {
          method: "DELETE"
        });
        if (res.ok) {
          alert("Datei gelöscht!");
          await loadVaultFiles();
        } else {
          alert("Fehler beim Löschen der Datei.");
        }
      } catch (e) {
        alert("Fehler: " + e.message);
      }
    }

    // Sandbox code runner
    async function runSandbox() {
      const filename = document.getElementById("sandbox-filename").value.trim();
      const code = document.getElementById("sandbox-code").value;
      if (!filename) return;

      const btn = document.getElementById("sandbox-btn");
      btn.innerText = "Ausführen...";
      btn.disabled = true;

      try {
        const res = await fetch("/api/sandbox", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ file_path: filename, code_content: code })
        });
        const data = await res.json();
        
        document.getElementById("sandbox-output-block").classList.remove("hidden");
        const consolePre = document.getElementById("sandbox-console");

        if (data.status === "success") {
          let output = `Exit Code: ${data.code}\n\n`;
          if (data.stdout) {
            output += `--- STDOUT ---\n${data.stdout}\n`;
          }
          if (data.stderr) {
            output += `--- STDERR ---\n${data.stderr}\n`;
          }
          consolePre.innerText = output;
          consolePre.style.color = "#22c55e";
        } else {
          consolePre.innerText = `Fehler: ${data.message}`;
          consolePre.style.color = "#ef4444";
        }
      } catch (e) {
        alert("Fehler bei Sandbox-Verbindung.");
      } finally {
        btn.innerText = "🚀 Code ausführen";
        btn.disabled = false;
      }
    }

    // --- CUSTOMIZER STEUERUNG & LIVE-UPDATE ---
    let customizerOpen = false;

    const defaultTheme = {
      sidebarWidth: 256,
      borderRadius: 6,
      cardPadding: 16,
      fontSize: 12,
      fontFamily: "'Outfit', sans-serif",
      colorBg: "",
      colorSidebar: "",
      colorCard: "",
      colorAccent: "",
      colorTextPrimary: "",
      colorTextSecondary: "",
      colorTextMuted: "",
      colorTextLabel: "",
      gradientEnable: false,
      gradientStart: "#4f46e5",
      gradientEnd: "#6b7cff",
      logoUrl: "",
      bgImageUrl: "",
      bgOpacity: 100,
      lblSecWorkspace: "1. WORKSPACE",
      lblSecArrangement: "2. ARRANGEMENT",
      lblSecAgents: "3. AGENTS",
      lblTabMc: "Mission Control",
      lblTabPc: "Paperclip Orchestrator",
      lblTabMm: "AI Mastermind",
      lblTabKb: "Kanban Pipeline",
      lblTabGl: "Workspace Gallery"
    };

    let themeSettings = { ...defaultTheme };

    function toggleCustomizer() {
      customizerOpen = !customizerOpen;
      const drawer = document.getElementById("customizer-drawer");
      if (customizerOpen) {
        drawer.classList.remove("translate-x-full");
        syncColorPickers();
      } else {
        drawer.classList.add("translate-x-full");
      }
    }

    function syncColorPickers() {
      const getStyleVal = (varName) => {
        return getComputedStyle(document.documentElement).getPropertyValue(varName).trim();
      };
      
      document.getElementById("opt-color-bg").value = rgbToHex(getStyleVal('--page-bg')) || "#f4f5f9";
      document.getElementById("opt-color-sidebar").value = rgbToHex(getStyleVal('--sidebar-bg')) || "#ffffff";
      document.getElementById("opt-color-card").value = rgbToHex(getStyleVal('--card-bg')) || "#ffffff";
      document.getElementById("opt-color-accent").value = rgbToHex(getStyleVal('--accent')) || "#4f46e5";
      
      document.getElementById("opt-color-text-primary").value = rgbToHex(getStyleVal('--text-primary')) || "#111827";
      document.getElementById("opt-color-text-secondary").value = rgbToHex(getStyleVal('--text-secondary')) || "#374151";
      document.getElementById("opt-color-text-muted").value = rgbToHex(getStyleVal('--text-muted')) || "#6b7280";
      document.getElementById("opt-color-text-label").value = rgbToHex(getStyleVal('--text-label')) || "#9ca3af";
      
      document.getElementById("opt-gradient-start").value = themeSettings.gradientStart || "#4f46e5";
      document.getElementById("opt-gradient-end").value = themeSettings.gradientEnd || "#6b7cff";
      document.getElementById("opt-gradient-enable").checked = themeSettings.gradientEnable || false;
      document.getElementById("opt-logo-url").value = themeSettings.logoUrl || "";
      document.getElementById("opt-bg-image-url").value = themeSettings.bgImageUrl || "";
      document.getElementById("opt-bg-opacity").value = themeSettings.bgOpacity !== undefined ? themeSettings.bgOpacity : 100;
    }

    function rgbToHex(rgbStr) {
      if (!rgbStr) return null;
      if (rgbStr.startsWith("#")) return rgbStr;
      const match = rgbStr.match(/\d+/g);
      if (!match || match.length < 3) return null;
      const r = parseInt(match[0]);
      const g = parseInt(match[1]);
      const b = parseInt(match[2]);
      return "#" + ((1 << 24) + (r << 16) + (g << 8) + b).toString(16).slice(1);
    }

    function applyCustomizerSetting(key, value) {
      themeSettings[key] = value;
      
      if (key === 'sidebarWidth') {
        document.documentElement.style.setProperty('--sidebar-width', `${value}px`);
        document.getElementById("val-sidebar-width").innerText = `${value}px`;
      }
      else if (key === 'borderRadius') {
        document.documentElement.style.setProperty('--border-radius', `${value}px`);
        document.getElementById("val-border-radius").innerText = `${value}px`;
      }
      else if (key === 'cardPadding') {
        document.documentElement.style.setProperty('--card-padding', `${value}px`);
        document.getElementById("val-card-padding").innerText = `${value}px`;
      }
      else if (key === 'fontSize') {
        document.documentElement.style.setProperty('--font-size', `${value}px`);
        document.getElementById("val-font-size").innerText = `${value}px`;
      }
      else if (key === 'fontFamily') {
        document.documentElement.style.setProperty('--font-family', value);
      }
      else if (key === 'colorBg') {
        document.documentElement.style.setProperty('--page-bg', value);
      }
      else if (key === 'colorSidebar') {
        document.documentElement.style.setProperty('--sidebar-bg', value);
      }
      else if (key === 'colorCard') {
        document.documentElement.style.setProperty('--card-bg', value);
      }
      else if (key === 'colorAccent') {
        document.documentElement.style.setProperty('--accent', value);
        document.documentElement.style.setProperty('--accent-bg', hexToRgba(value, 0.1));
        document.documentElement.style.setProperty('--accent-border', hexToRgba(value, 0.25));
      }
      else if (key === 'colorTextPrimary') {
        document.documentElement.style.setProperty('--text-primary', value);
      }
      else if (key === 'colorTextSecondary') {
        document.documentElement.style.setProperty('--text-secondary', value);
      }
      else if (key === 'colorTextMuted') {
        document.documentElement.style.setProperty('--text-muted', value);
      }
      else if (key === 'colorTextLabel') {
        document.documentElement.style.setProperty('--text-label', value);
      }
      else if (key === 'lblSecWorkspace') {
        const el = document.getElementById("sidebar-sec-1-title");
        if (el) el.innerText = value;
      }
      else if (key === 'lblSecArrangement') {
        const el = document.getElementById("sidebar-sec-2-title");
        if (el) el.innerText = value;
      }
      else if (key === 'lblSecAgents') {
        const el = document.getElementById("sidebar-sec-3-title");
        if (el) el.innerText = value;
      }
      else if (key === 'lblTabMc') {
        const el = document.getElementById("sidebar-tab-mc-title");
        if (el) el.innerText = value;
      }
      else if (key === 'lblTabPc') {
        const el = document.getElementById("sidebar-tab-pc-title");
        if (el) el.innerText = value;
      }
      else if (key === 'lblTabMm') {
        const el = document.getElementById("sidebar-tab-mm-title");
        if (el) el.innerText = value;
      }
      else if (key === 'lblTabKb') {
        const el = document.getElementById("sidebar-tab-kb-title");
        if (el) el.innerText = value;
      }
      else if (key === 'lblTabGl') {
        const el = document.getElementById("sidebar-tab-gl-title");
        if (el) el.innerText = value;
      }
      else if (key === 'gradientEnable' || key === 'gradientStart' || key === 'gradientEnd') {
        updateCardBackground();
      }
      else if (key === 'logoUrl') {
        updateLogo(value);
      }
      else if (key === 'bgImageUrl' || key === 'bgOpacity') {
        updateBackgroundImage();
      }
    }

    function hexToRgba(hex, alpha) {
      const r = parseInt(hex.slice(1, 3), 16);
      const g = parseInt(hex.slice(3, 5), 16);
      const b = parseInt(hex.slice(5, 7), 16);
      return `rgba(${r}, ${g}, ${b}, ${alpha})`;
    }

    function updateCardBackground() {
      const enable = themeSettings.gradientEnable;
      const start = themeSettings.gradientStart || "#4f46e5";
      const end = themeSettings.gradientEnd || "#6b7cff";
      if (enable) {
        document.documentElement.style.setProperty('--card-bg-gradient', `linear-gradient(135deg, ${start}, ${end})`);
      } else {
        document.documentElement.style.removeProperty('--card-bg-gradient');
      }
    }

    function updateLogo(url) {
      const headerDiv = document.querySelector(".theme-sidebar div.flex.items-center");
      if (headerDiv) {
        let logoImg = document.getElementById("custom-sidebar-logo");
        if (url) {
          if (!logoImg) {
            logoImg = document.createElement("img");
            logoImg.id = "custom-sidebar-logo";
            logoImg.className = "w-7 h-7 rounded object-cover mr-1";
            headerDiv.insertBefore(logoImg, headerDiv.firstChild);
            const settingsIcon = headerDiv.querySelector("div");
            if (settingsIcon) settingsIcon.classList.add("hidden");
          }
          logoImg.src = url;
        } else {
          if (logoImg) {
            logoImg.remove();
            const settingsIcon = headerDiv.querySelector("div");
            if (settingsIcon) settingsIcon.classList.remove("hidden");
          }
        }
      }
    }

    function updateBackgroundImage() {
      const url = themeSettings.bgImageUrl;
      const opacity = themeSettings.bgOpacity !== undefined ? themeSettings.bgOpacity : 100;
      let bgDiv = document.getElementById("custom-page-bg-image");
      
      if (url) {
        if (!bgDiv) {
          bgDiv = document.createElement("div");
          bgDiv.id = "custom-page-bg-image";
          bgDiv.className = "fixed inset-0 pointer-events-none z-[-1] bg-cover bg-center transition-all duration-300";
          document.body.appendChild(bgDiv);
        }
        bgDiv.style.backgroundImage = `url('${url}')`;
        bgDiv.style.opacity = opacity / 100;
      } else {
        if (bgDiv) bgDiv.remove();
      }
      document.getElementById("val-bg-opacity").innerText = `${opacity}%`;
    }

    async function loadThemeFromServer() {
      try {
        const res = await fetch("/api/theme");
        const data = await res.json();
        if (data && Object.keys(data).length > 0) {
          themeSettings = { ...defaultTheme, ...data };
          Object.keys(themeSettings).forEach(key => {
            applyCustomizerSetting(key, themeSettings[key]);
          });
          syncInputsWithSettings();
        }
      } catch (e) {
        console.error("Fehler beim Laden des Themes:", e);
      }
    }

    function syncInputsWithSettings() {
      document.getElementById("opt-sidebar-width").value = themeSettings.sidebarWidth || 256;
      document.getElementById("opt-border-radius").value = themeSettings.borderRadius || 6;
      document.getElementById("opt-card-padding").value = themeSettings.cardPadding || 16;
      document.getElementById("opt-font-size").value = themeSettings.fontSize || 12;
      document.getElementById("opt-font-family").value = themeSettings.fontFamily || "'Outfit', sans-serif";
      document.getElementById("opt-gradient-enable").checked = themeSettings.gradientEnable || false;
      document.getElementById("opt-logo-url").value = themeSettings.logoUrl || "";
      document.getElementById("opt-bg-image-url").value = themeSettings.bgImageUrl || "";
      document.getElementById("opt-bg-opacity").value = themeSettings.bgOpacity !== undefined ? themeSettings.bgOpacity : 100;

      document.getElementById("opt-color-text-primary").value = themeSettings.colorTextPrimary || "";
      document.getElementById("opt-color-text-secondary").value = themeSettings.colorTextSecondary || "";
      document.getElementById("opt-color-text-muted").value = themeSettings.colorTextMuted || "";
      document.getElementById("opt-color-text-label").value = themeSettings.colorTextLabel || "";

      document.getElementById("lbl-sec-workspace").value = themeSettings.lblSecWorkspace || "1. WORKSPACE";
      document.getElementById("lbl-sec-arrangement").value = themeSettings.lblSecArrangement || "2. ARRANGEMENT";
      document.getElementById("lbl-sec-agents").value = themeSettings.lblSecAgents || "3. AGENTS";
      
      document.getElementById("lbl-tab-mc").value = themeSettings.lblTabMc || "Mission Control";
      document.getElementById("lbl-tab-pc").value = themeSettings.lblTabPc || "Paperclip Orchestrator";
      document.getElementById("lbl-tab-mm").value = themeSettings.lblTabMm || "AI Mastermind";
      document.getElementById("lbl-tab-kb").value = themeSettings.lblTabKb || "Kanban Pipeline";
      document.getElementById("lbl-tab-gl").value = themeSettings.lblTabGl || "Workspace Gallery";

      document.getElementById("val-sidebar-width").innerText = `${themeSettings.sidebarWidth || 256}px`;
      document.getElementById("val-border-radius").innerText = `${themeSettings.borderRadius || 6}px`;
      document.getElementById("val-card-padding").innerText = `${themeSettings.cardPadding || 16}px`;
      document.getElementById("val-font-size").innerText = `${themeSettings.fontSize || 12}px`;
      document.getElementById("val-bg-opacity").innerText = `${themeSettings.bgOpacity !== undefined ? themeSettings.bgOpacity : 100}%`;
    }

    async function saveThemeToServer() {
      try {
        const res = await fetch("/api/theme", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(themeSettings)
        });
        if (res.ok) {
          alert("Theme-Einstellungen erfolgreich gespeichert!");
        } else {
          alert("Fehler beim Speichern auf dem Server.");
        }
      } catch (e) {
        alert("Verbindungsfehler: " + e.message);
      }
    }

    function resetTheme() {
      if (confirm("Möchten Sie alle Designanpassungen zurücksetzen?")) {
        themeSettings = { ...defaultTheme };
        document.documentElement.style.removeProperty('--sidebar-width');
        document.documentElement.style.removeProperty('--border-radius');
        document.documentElement.style.removeProperty('--card-padding');
        document.documentElement.style.removeProperty('--font-size');
        document.documentElement.style.removeProperty('--font-family');
        document.documentElement.style.removeProperty('--card-bg-gradient');
        
        if (theme === "dark") {
          document.documentElement.style.setProperty('--page-bg', '#08090e');
          document.documentElement.style.setProperty('--sidebar-bg', '#08090e');
          document.documentElement.style.setProperty('--card-bg', '#0d0f1a');
          document.documentElement.style.setProperty('--accent', '#6b7cff');
        } else {
          document.documentElement.style.setProperty('--page-bg', '#f4f5f9');
          document.documentElement.style.setProperty('--sidebar-bg', '#ffffff');
          document.documentElement.style.setProperty('--card-bg', '#ffffff');
          document.documentElement.style.setProperty('--accent', '#4f46e5');
        }

        updateLogo("");
        updateBackgroundImage();
        syncInputsWithSettings();
        syncColorPickers();
        saveThemeToServer();
      }
    }

    // --- SYSTEM CONTROL CENTER LOGIC ---
    let currentEditingRoleSettingsId = "";

    async function openSystemSettingsModal(defaultTab = "services") {
      try {
        const res = await fetch("/api/settings");
        const settings = await res.json();
        document.getElementById("setting-gateway-url").value = settings.gateway_url || "http://localhost:20128/v1";
        document.getElementById("setting-workspace-dir").value = settings.workspace_dir || "";
      } catch (e) {
        console.error("Failed to load settings:", e);
      }
      
      document.getElementById("setting-gateway-key").value = "sk-949ea8f3766d6490-f9ab38-33bea980";

      try {
        const res = await fetch("/api/v1/services");
        servicesList = await res.json();
      } catch (e) {
        console.error("Failed to load services:", e);
      }

      populateSettingsRoleDropdown();
      if (roles.length > 0) {
        loadRoleIntoSettingsEditor(roles[0].id);
      }

      await loadFrameworksFromServer();
      populateSettingsFrameworkDropdown();
      const fwSelect = document.getElementById("setting-framework-select");
      if (fwSelect && fwSelect.options.length > 0) {
        loadFrameworkIntoSettingsEditor(fwSelect.options[0].value);
      }

      renderSettingsServices();
      setSettingsTab(defaultTab);
      document.getElementById("system-settings-modal").classList.remove("hidden");
    }

    function closeSystemSettingsModal() {
      document.getElementById("system-settings-modal").classList.add("hidden");
    }

    function setSettingsTab(tabName) {
      activeSettingsTab = tabName;
      const tabs = ["services", "routing", "kernel", "roles", "frameworks"];
      tabs.forEach(t => {
        const pane = document.getElementById(`settings-tab-${t}`);
        const btn = document.getElementById(`btn-tab-${t}`);
        if (t === tabName) {
          pane.classList.remove("hidden");
          btn.className = "py-2 px-4 text-xs font-bold border-b-2 border-[var(--accent)] text-[var(--text-primary)]";
        } else {
          pane.classList.add("hidden");
          btn.className = "py-2 px-4 text-xs font-bold border-b-2 border-transparent text-muted-custom hover:text-[var(--text-primary)]";
        }
      });
      lucide.createIcons();
    }

    let currentConnectionMode = 'remote';

    function selectConnectionMode(mode) {
      currentConnectionMode = mode;
      const modes = ['local', 'cloud', 'remote', 'ssh'];
      modes.forEach(m => {
        const card = document.getElementById(`conn-card-${m}`);
        const check = document.getElementById(`conn-check-${m}`);
        if (m === mode) {
          if (card) card.className = "p-3.5 rounded-lg border-2 border-amber-500/80 bg-amber-500/5 cursor-pointer transition-all space-y-1.5 relative";
          if (check) check.classList.remove("hidden");
        } else {
          if (card) card.className = "p-3.5 rounded-lg border theme-border hover:border-amber-500/50 cursor-pointer transition-all space-y-1.5 relative opacity-80 hover:opacity-100";
          if (check) check.classList.add("hidden");
        }
      });
      lucide.createIcons();
    }

    async function testRemoteConnection() {
      const url = document.getElementById("setting-gateway-url").value.trim() || "http://127.0.0.1:9119";
      alert(`Prüfe Remote-Verbindung zu ${url}...\nStatus: HTTP 200 OK — Remote Gateway antwortet.`);
    }

    function toggleKeyVisibility() {
      const input = document.getElementById("setting-gateway-key");
      if (input.type === "password") {
        input.type = "text";
      } else {
        input.type = "password";
      }
    }

    function renderSettingsServices() {
      const container = document.getElementById("coupled-services-list");
      if (!container) return;
      container.innerHTML = "";

      servicesList.forEach(service => {
        const card = document.createElement("div");
        card.className = "p-3 rounded-lg border theme-border flex items-start justify-between gap-4 bg-[var(--page-bg)]";
        const ledColor = service.active ? "bg-green-500 shadow-[0_0_5px_#22c55e]" : "bg-neutral-500";

        let roleOptions = "";
        roles.forEach(r => {
          const sel = (service.role === r.name || service.role === r.id) ? "selected" : "";
          roleOptions += `<option value="${r.id}" ${sel}>${r.name}</option>`;
        });

        let modelOptions = "";
        modelsList.forEach(m => {
          const sel = service.model === m ? "selected" : "";
          modelOptions += `<option value="${m}" ${sel}>${m}</option>`;
        });

        card.innerHTML = `
          <div class="flex-1 space-y-1 text-xs">
            <div class="flex items-center gap-2">
              <span class="inline-block w-2.5 h-2.5 rounded-full ${ledColor}"></span>
              <span class="font-bold text-xs uppercase text-primary-custom">${service.name}</span>
              <span class="text-[9px] font-mono bg-neutral-900/10 px-1 py-0.5 rounded text-muted-custom border theme-border">@${service.id}</span>
            </div>
            <p class="text-[10px] text-muted-custom leading-tight">${service.description}</p>
            
            <div class="flex gap-2 mt-2 pt-2 border-t theme-border">
              <div class="flex-1">
                <label class="block text-[8px] uppercase font-bold text-muted-custom mb-0.5">Modell</label>
                <select onchange="updateServiceField('${service.id}', 'model', this.value)" class="w-full bg-[var(--card-bg)] border theme-border rounded text-[10px] px-1.5 py-0.5 focus:outline-none cursor-pointer">
                  ${modelOptions}
                </select>
              </div>
              <div class="flex-1">
                <label class="block text-[8px] uppercase font-bold text-muted-custom mb-0.5">Rolle</label>
                <select onchange="updateServiceField('${service.id}', 'role', this.value)" class="w-full bg-[var(--card-bg)] border theme-border rounded text-[10px] px-1.5 py-0.5 focus:outline-none cursor-pointer">
                  ${roleOptions}
                </select>
              </div>
            </div>
          </div>

          <div class="flex flex-col items-end justify-between h-full gap-2 text-xs">
            <span class="text-[9px] font-bold uppercase tracking-wider ${service.active ? 'text-green-500' : 'text-muted-custom'}">
              ${service.active ? 'GEKOPPELT' : 'INAKTIV'}
            </span>
            <label class="relative inline-flex items-center cursor-pointer mt-1">
              <input type="checkbox" ${service.active ? 'checked' : ''} onchange="toggleServiceActive('${service.id}')" class="rounded bg-neutral-900/10 border theme-border w-4 h-4 accent-green-500">
            </label>
          </div>
        `;
        container.appendChild(card);
      });
    }

    function updateServiceField(serviceId, field, value) {
      const service = servicesList.find(s => s.id === serviceId);
      if (service) {
        if (field === "role") {
          const selectedRole = roles.find(r => r.id === value);
          service.role = selectedRole ? selectedRole.name : value;
        } else {
          service[field] = value;
        }
      }
    }

    function toggleServiceActive(serviceId) {
      const service = servicesList.find(s => s.id === serviceId);
      if (service) {
        service.active = !service.active;
        if (!service.active) {
          // If deactivated, we can remove any running instances
          agents = agents.filter(a => a.id !== service.id);
        }
        renderSettingsServices();
      }
    }

    async function saveSystemSettings() {
      const gwUrl = document.getElementById("setting-gateway-url").value.trim() || "http://localhost:20128/v1";
      const wsDir = document.getElementById("setting-workspace-dir").value.trim();
      try {
        await fetch("/api/settings", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ gateway_url: gwUrl, workspace_dir: wsDir })
        });

        await fetch("/api/v1/services", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(servicesList)
        });
      } catch (e) {
        console.error("Error saving settings:", e);
      }

      await saveAgentsToServer();
      renderAgentsSidebar();
      renderAgentRegistryTable();
      renderSidebarPresetsSelect();
      closeSystemSettingsModal();
      
      alert("Systemkonfiguration und Agenten-Kopplung erfolgreich gespeichert!");
    }

    async function resetSystemData() {
      if (confirm("Möchtest du wirklich alle Caches und konfigurierten Agenten zurücksetzen? Dies setzt das System in den Werkszustand zurück.")) {
        try {
          await fetch("/api/ticker/clear", { method: "POST" });
          agents = [];
          await saveAgentsToServer();
          location.reload();
        } catch (e) {
          alert("Fehler beim Zurücksetzen: " + e);
        }
      }
    }

    let selectedRoleCategoryFilter = "all";

    function filterRoleDropdownByCategory(category) {
      selectedRoleCategoryFilter = category;
      populateSettingsRoleDropdown();
      const select = document.getElementById("setting-role-select");
      if (select && select.options.length > 0) {
        loadRoleIntoSettingsEditor(select.options[0].value);
      }
    }

    function populateSettingsRoleDropdown() {
      const select = document.getElementById("setting-role-select");
      if (!select) return;
      select.innerHTML = "";

      let filteredRoles = roles;
      if (selectedRoleCategoryFilter && selectedRoleCategoryFilter !== "all") {
        filteredRoles = roles.filter(r => (r.category || "1. Management & Architektur") === selectedRoleCategoryFilter);
      }

      if (selectedRoleCategoryFilter === "all") {
        const categories = {};
        filteredRoles.forEach(role => {
          const cat = role.category || "1. Management & Architektur";
          if (!categories[cat]) categories[cat] = [];
          categories[cat].push(role);
        });

        for (const [catName, catRoles] of Object.entries(categories)) {
          const group = document.createElement("optgroup");
          group.label = catName;
          catRoles.forEach(role => {
            const opt = document.createElement("option");
            opt.value = role.id;
            opt.innerText = role.name;
            if (role.id === currentEditingRoleSettingsId) {
              opt.selected = true;
            }
            group.appendChild(opt);
          });
          select.appendChild(group);
        }
      } else {
        filteredRoles.forEach(role => {
          const opt = document.createElement("option");
          opt.value = role.id;
          opt.innerText = role.name;
          if (role.id === currentEditingRoleSettingsId) {
            opt.selected = true;
          }
          select.appendChild(opt);
        });
      }

      if (filteredRoles.length > 0 && !filteredRoles.some(r => r.id === currentEditingRoleSettingsId)) {
        currentEditingRoleSettingsId = filteredRoles[0].id;
        select.value = currentEditingRoleSettingsId;
      }
    }

    function loadRoleIntoSettingsEditor(roleId) {
      currentEditingRoleSettingsId = roleId;
      const role = roles.find(r => r.id === roleId);
      if (role) {
        document.getElementById("setting-role-name").value = role.name;
        document.getElementById("setting-role-prompt").value = role.prompt;
        const catSelect = document.getElementById("setting-role-category");
        if (catSelect) catSelect.value = role.category || "1. Management & Architektur";
      }
      const select = document.getElementById("setting-role-select");
      if (select) select.value = roleId;
    }

    function createNewRoleInSettings() {
      const newId = "role_" + Math.floor(Math.random()*100000);
      const cat = selectedRoleCategoryFilter !== "all" ? selectedRoleCategoryFilter : "1. Management & Architektur";
      const newRole = {
        id: newId,
        category: cat,
        name: "Neue Spezial-Rolle",
        prompt: "Beschreibe hier das Mandat und die System-Instruktion der neuen Rolle."
      };
      roles.push(newRole);
      populateSettingsRoleDropdown();
      loadRoleIntoSettingsEditor(newId);
    }

    function deleteSelectedRoleFromSettings() {
      if (!currentEditingRoleSettingsId) return;
      if (roles.length <= 1) {
        alert("Mindestens eine Systemrolle muss bestehen bleiben!");
        return;
      }
      roles = roles.filter(r => r.id !== currentEditingRoleSettingsId);
      currentEditingRoleSettingsId = roles[0].id;
      populateSettingsRoleDropdown();
      loadRoleIntoSettingsEditor(currentEditingRoleSettingsId);
    }

    async function saveRoleSettingsChanges() {
      const name = document.getElementById("setting-role-name").value.trim();
      const prompt = document.getElementById("setting-role-prompt").value.trim();
      const category = document.getElementById("setting-role-category").value;
      if (!name || !prompt) {
        alert("Bitte fülle Rollenname und System Prompt aus!");
        return;
      }
      const role = roles.find(r => r.id === currentEditingRoleSettingsId);
      if (role) {
        role.name = name;
        role.prompt = prompt;
        role.category = category;
      }
      
      try {
        await fetch("/api/roles", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(roles)
        });
        alert("Rolle erfolgreich gespeichert!");
        populateSettingsRoleDropdown();
        renderAgentsSidebar();
      } catch (e) {
        alert("Fehler beim Speichern der Rollen: " + e);
      }
    }

    async function loadRolesFromServer() {
      try {
        const res = await fetch("/api/roles");
        if (res.ok) {
          roles = await res.json();
        }
      } catch (e) {
        console.error("Failed to load roles from server:", e);
      }
    }

    let categorizedFrameworksData = {};
    let selectedFrameworkCategoryFilter = "all";
    let currentEditingFrameworkName = "";

    async function loadFrameworksFromServer() {
      try {
        const res = await fetch("/api/boardroom/frameworks");
        if (res.ok) {
          categorizedFrameworksData = await res.json();
        }
      } catch (e) {
        console.error("Failed to load frameworks from server:", e);
      }
    }

    function filterFrameworkDropdownByCategory(category) {
      selectedFrameworkCategoryFilter = category;
      populateSettingsFrameworkDropdown();
      const select = document.getElementById("setting-framework-select");
      if (select && select.options.length > 0) {
        loadFrameworkIntoSettingsEditor(select.options[0].value);
      }
    }

    function populateSettingsFrameworkDropdown() {
      const select = document.getElementById("setting-framework-select");
      if (!select) return;
      select.innerHTML = "";

      let firstFw = "";

      for (const [catName, frameworks] of Object.entries(categorizedFrameworksData)) {
        if (selectedFrameworkCategoryFilter !== "all" && selectedFrameworkCategoryFilter !== catName) {
          continue;
        }

        const group = document.createElement("optgroup");
        group.label = catName;

        for (const [fwName, fwVal] of Object.entries(frameworks)) {
          if (!firstFw) firstFw = fwName;
          const opt = document.createElement("option");
          opt.value = fwName;
          opt.innerText = fwName;
          opt.setAttribute("data-category", catName);
          if (fwName === currentEditingFrameworkName) {
            opt.selected = true;
          }
          group.appendChild(opt);
        }
        select.appendChild(group);
      }

      if (!currentEditingFrameworkName && firstFw) {
        currentEditingFrameworkName = firstFw;
        select.value = firstFw;
      }
    }

    function loadFrameworkIntoSettingsEditor(fwName) {
      currentEditingFrameworkName = fwName;

      let foundCat = "1. Bisherige, Agile & Innovation";
      let foundInstruction = "";

      for (const [catName, frameworks] of Object.entries(categorizedFrameworksData)) {
        if (fwName in frameworks) {
          foundCat = catName;
          const fwVal = frameworks[fwName];
          foundInstruction = typeof fwVal === "string" ? fwVal : (fwVal.system_instruction || fwVal.summary || "");
          break;
        }
      }

      const nameInput = document.getElementById("setting-framework-name");
      const catSelect = document.getElementById("setting-framework-category");
      const instInput = document.getElementById("setting-framework-instruction");

      if (nameInput) nameInput.value = fwName;
      if (catSelect) catSelect.value = foundCat;
      if (instInput) instInput.value = foundInstruction;

      const select = document.getElementById("setting-framework-select");
      if (select) select.value = fwName;
    }

    function createNewFrameworkInSettings() {
      const newName = "Neues Methodik-Framework " + Math.floor(Math.random() * 1000);
      const targetCat = selectedFrameworkCategoryFilter !== "all" ? selectedFrameworkCategoryFilter : "1. Bisherige, Agile & Innovation";

      if (!categorizedFrameworksData[targetCat]) {
        categorizedFrameworksData[targetCat] = {};
      }

      categorizedFrameworksData[targetCat][newName] = "Beschreibe hier die methodischen Phasen und Anweisungen für die Agenten.";
      currentEditingFrameworkName = newName;
      populateSettingsFrameworkDropdown();
      loadFrameworkIntoSettingsEditor(newName);
    }

    function deleteSelectedFrameworkFromSettings() {
      if (!currentEditingFrameworkName) return;

      for (const [catName, frameworks] of Object.entries(categorizedFrameworksData)) {
        if (currentEditingFrameworkName in frameworks) {
          delete frameworks[currentEditingFrameworkName];
          break;
        }
      }

      currentEditingFrameworkName = "";
      populateSettingsFrameworkDropdown();
      const select = document.getElementById("setting-framework-select");
      if (select && select.options.length > 0) {
        loadFrameworkIntoSettingsEditor(select.options[0].value);
      }
    }

    async function saveFrameworkSettingsChanges() {
      const nameInput = document.getElementById("setting-framework-name").value.trim();
      const catSelect = document.getElementById("setting-framework-category").value;
      const instInput = document.getElementById("setting-framework-instruction").value.trim();

      if (!nameInput || !instInput) {
        alert("Bitte fülle den Framework-Namen und die System-Instruktion aus!");
        return;
      }

      if (currentEditingFrameworkName && currentEditingFrameworkName !== nameInput) {
        for (const [catName, frameworks] of Object.entries(categorizedFrameworksData)) {
          if (currentEditingFrameworkName in frameworks) {
            delete frameworks[currentEditingFrameworkName];
          }
        }
      }

      if (!categorizedFrameworksData[catSelect]) {
        categorizedFrameworksData[catSelect] = {};
      }

      categorizedFrameworksData[catSelect][nameInput] = instInput;
      currentEditingFrameworkName = nameInput;

      try {
        await fetch("/api/boardroom/frameworks", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(categorizedFrameworksData)
        });
        alert("Methodik-Framework erfolgreich gespeichert!");
        populateSettingsFrameworkDropdown();
        loadBoardroomFrameworks();
      } catch (e) {
        alert("Fehler beim Speichern der Frameworks: " + e);
      }
    }

    async function resetFrameworksToDefault() {
      if (confirm("Möchtest du alle Methodik-Frameworks auf die 23 Basis-Standards zurücksetzen?")) {
        try {
          await fetch("/api/boardroom/frameworks/reset", { method: "POST" });
          await loadFrameworksFromServer();
          currentEditingFrameworkName = "";
          populateSettingsFrameworkDropdown();
          const select = document.getElementById("setting-framework-select");
          if (select && select.options.length > 0) {
            loadFrameworkIntoSettingsEditor(select.options[0].value);
          }
          loadBoardroomFrameworks();
          alert("Erfolgreich auf alle 23 Basis-Frameworks zurückgesetzt.");
        } catch (e) {
          alert("Fehler beim Zurücksetzen: " + e);
        }
      }
    }

    async function loadModelsFromServer() {
      try {
        const res = await fetch("/api/v1/models");
        if (res.ok) {
          modelsList = await res.json();
        }
      } catch (e) {
        console.error("Failed to load models from server:", e);
      }
      if (!modelsList || modelsList.length === 0) {
        modelsList = ["free-forever", "gpt-4o", "gpt-4o-mini", "claude-3-5-sonnet", "deepseek-r1", "hermes-3", "llama-3.3-70b"];
      }
    }

    async function loadKanbanFromServer() {
      try {
        const res = await fetch("/api/kanban");
        if (res.ok) {
          kanbanCards = await res.json();
        }
      } catch (e) {
        console.error("Failed to load kanban cards:", e);
      }
    }

    async function loadVaultFiles() {
      try {
        const res = await fetch("/api/vault/files");
        if (res.ok) {
          vaultFiles = await res.json();
        }
      } catch (e) {
        console.error("Failed to load vault files:", e);
      }
    }

    async function resetRolesToDefault() {
      if (confirm("Möchtest du die KI-Rollen wirklich auf alle 24 Basis-Standardrollen zurücksetzen?")) {
        try {
          const res = await fetch("/api/roles");
          // Re-fetch default roles by resetting roles.json on server or re-sending defaults
          roles = [
            { id: "orchestrator", category: "1. Management & Architektur", name: "Orchestrator & System-Architekt", prompt: "Du bist ein erfahrener Orchestrator & System-Architekt. Deine Aufgabe ist es, meisterhaft komplexe Problemstellungen zu analysieren, Aufgaben strukturiert auf Spezial-Agenten zu verteilen, Abhängigkeiten zu managen und Teilergebnisse zu einer schlüssigen Gesamtlösung zu synthetisieren." },
            { id: "product_manager", category: "1. Management & Architektur", name: "Product Manager / Requirements Engineer", prompt: "Du bist ein strikter Product Manager & Requirements Engineer. Du übersetzt vage Nutzerideen in glasklare, präzise technische User Stories, Akzeptanzkriterien und funktionale Spezifikationen (PRDs). Du verhinderst Scope Creep und forderst Messbarkeit in allen Anforderungen." },
            { id: "scrum_master", category: "1. Management & Architektur", name: "Agile Scrum Master / Task Triage Manager", prompt: "Du bist ein proaktiver Agile Scrum Master & Task Triage Manager. Du strukturierst Workflows in überschaubare Sprint-Tasks, identifizierst Blockaden, priorisierst das Backlog in der Kanban-Pipeline und verteilst Arbeitspakete effizient an ausführende Worker-Agenten." },
            { id: "enterprise_architect", category: "1. Management & Architektur", name: "Enterprise Architect", prompt: "Du bist ein pragmatischer Enterprise Architect. Du bewertest Systemarchitekturen auf langfristige Skalierbarkeit, Modulkopplung, Microservice-Muster und Technologie-Stacks. Du verhinderst technologische Sackgassen und achtest auf Zukunftsfähigkeit." },
            { id: "technical_writer", category: "1. Management & Architektur", name: "Technical Writer & Documentation Specialist", prompt: "Du bist ein präziser Technical Writer & Dokumentations-Spezialist. Du wandelst komplexen Code und Architekturentscheidungen in saubere, übersichtliche Markdown-Dokumentationen, API-Guides, READMEs und strukturierte Obsidian-Vault-Notizen um." },
            { id: "prompt_engineer", category: "1. Management & Architektur", name: "Prompt & AI Systems Engineer", prompt: "Du bist ein Prompt & AI Systems Engineer. Du analysierst und optimierst System-Prompts, Instruction Tuning, Context-Window-Nutzung und Output-Parsing (z.B. JSON/XML-Garantien) für maximale Genauigkeit der ausführenden LLM-Agenten." },
            { id: "senior_coder", category: "2. Software Development & Engineering", name: "Senior Coder / Software Engineer", prompt: "Du bist ein extrem kompetenter Senior Software Engineer. Du schreibst sauberen, modularen, objektorientierten und produktionsreifen Code (Python, TypeScript, Go). Du folgst strikt Best Practices (DRY, SOLID) und lieferst fehlerfreie Implementierungen." },
            { id: "frontend_architect", category: "2. Software Development & Engineering", name: "Frontend & UI/UX Architect", prompt: "Du bist ein visuell denkender Frontend & UI/UX Architect. Du entwirfst moderne, performante und ergonomische Benutzeroberflächen (Streamlit, React, CSS3, Tailwind). Du achtest penibel auf visuelle Hierarchien, responsive Grids und reibungslose User-Flows." },
            { id: "backend_db_designer", category: "2. Software Development & Engineering", name: "Backend & Database Designer", prompt: "Du bist ein hochspezialisierter Backend & Database Designer. Du entwickelst robuste API-Schnittstellen (REST, GraphQL, gRPC), optimierst SQL/NoSQL-Datenbankschemas, indizierst Tabellen und verhinderst Bottlenecks bei Abfragen." },
            { id: "clean_code_expert", category: "2. Software Development & Engineering", name: "Refactoring & Clean Code Expert", prompt: "Du bist ein kompromissloser Refactoring & Clean Code Expert. Du durchleuchtest bestehenden Code auf Code Smells, Redundanzen, hohe zyklomatische Komplexität und schlechte Benennungen, um die Wartbarkeit drastisch zu erhöhen." },
            { id: "devops_container", category: "2. Software Development & Engineering", name: "DevOps & Container Specialist", prompt: "Du bist ein erfahrener DevOps & Container Specialist. Du erstellst gehärtete Dockerfiles, Docker-Compose-Setups, Netzwerkkonfigurationen und CI/CD-Pipelines für eine nahtlose, isolierte und ausfallsichere Container-Laufzeitumgebung." },
            { id: "qa_test_engineer", category: "2. Software Development & Engineering", name: "QA & Automated Testing Engineer", prompt: "Du bist ein penibler QA & Automated Testing Engineer. Du entwirfst umfassende Unit-Tests, Integrationstests und E2E-Testsuites (PyTest, Jest). Du suchst gezielt nach Edge Cases, um Fehler vor dem Deployment abzufangen." },
            { id: "security_auditor", category: "3. Security, Data & Audit", name: "Security Auditor / DevSecOps", prompt: "Du bist ein akribischer Security Auditor & DevSecOps. Du analysierst Code und Systeme auf Sicherheitslücken (OWASP Top 10, Injection Risks, Secret Leaks, Insecure Deserialization) und verlangst harte Schutzmaßnahmen und Sanitization." },
            { id: "gdpr_compliance", category: "3. Security, Data & Audit", name: "Data Protection & Compliance Officer (DSGVO)", prompt: "Du bist ein Data Protection & Compliance Officer. Du stellst sicher, dass Systeme, Logs und Speichermethoden vollumfänglich DSGVO-konform sind, keine personenbezogenen Daten (PII) unverschlüsselt verarbeiten und Datenschutzprinzipien wahren." },
            { id: "performance_auditor", category: "3. Security, Data & Audit", name: "Performance & Benchmarking Auditor", prompt: "Du bist ein analytischer Performance & Benchmarking Auditor. Du misst Ausführungszeiten, Token-Effizienz, Memory Leaks und CPU-Last. Du identifizierst Ineffizienzen und machst konkrete Vorschläge zur Ressourcenminimierung." },
            { id: "fact_checker", category: "3. Security, Data & Audit", name: "Fact-Checker & Logic Validator", prompt: "Du bist ein unbestechlicher Fact-Checker & Logic Validator. Du prüfst Generierungen und Behauptungen anderer Agenten auf Halluzinationen, mathematische Fehler, logische Fehlschlüsse und verifizierst Quellen auf absolute Richtigkeit." },
            { id: "dependency_auditor", category: "3. Security, Data & Audit", name: "Dependency & Supply Chain Auditor", prompt: "Du bist ein wachsamer Dependency & Supply Chain Auditor. Du prüfst externe Bibliotheken (pip, npm), Lizenzen (MIT, GPL, Apache) und Paketabhängigkeiten auf Sicherheitsrisiken, veraltete Versionen und Deprecations." },
            { id: "devils_advocate", category: "3. Security, Data & Audit", name: "Skeptic / Devil's Advocate", prompt: "Du bist der kritische Skeptic & Devil's Advocate im Boardroom. Deine Aufgabe ist es, getroffene Entscheidungen, Pläne und Code-Entwürfe konstruktiv, aber schonungslos zu hinterfragen, um verdeckte Risiken und Denkfehler aufzudecken." },
            { id: "researcher", category: "4. Business, Research & Marketing", name: "Researcher & Data Analyst", prompt: "Du bist ein tiefgründiger Researcher & Data Analyst. Du durchsuchst das Web, Datenbanken und Fachliteratur, filterst Rauschen von Signalen und erstellst fundierte, evidenzbasierte Analysen und Zusammenfassungen." },
            { id: "market_intelligence", category: "4. Business, Research & Marketing", name: "Market & Competitor Intelligence Analyst", prompt: "Du bist ein strategischer Market & Competitor Intelligence Analyst. Du analysierst Marktsegmente, Mitbewerber-Tools, Preismodelle und Feature-Gaps, um Wettbewerbsvorteile und Differenzierungsmerkmale herauszuarbeiten." },
            { id: "seo_content", category: "4. Business, Research & Marketing", name: "SEO & Content Pipeline Specialist", prompt: "Du bist ein datengetriebener SEO & Content Pipeline Specialist. Du recherchierst High-Intent-Keywords, erstellst strukturierte Content-Pipelines und entwirfst suchmaschinenoptimierte Artikel und Veröffentlichungsstrategien." },
            { id: "outreach_automator", category: "4. Business, Research & Marketing", name: "Outreach & Lead Gen Automator", prompt: "Du bist ein fokussierter Outreach & Lead Gen Automator. Du konzipierst automatisierte B2B-Ansprachen, LinkedIn-Sequenzen und E-Mail-Kampagnen, inklusive Lead-Validierung und Triage für den Vertrieb." },
            { id: "financial_optimizer", category: "4. Business, Research & Marketing", name: "Financial & Cost Optimizer", prompt: "Du bist ein kostenbewusster Financial & Cost Optimizer. Du überwachst Token-Verbräuche, verglichst API-Kosten vs. Open-Source-Modelle und optimierst die Betriebskosten der gesamten Agenten-Infrastruktur." },
            { id: "growth_strategist", category: "4. Business, Research & Marketing", name: "Growth & UX Conversion Strategist", prompt: "Du bist ein ergebnisorientierter Growth & UX Conversion Strategist. Du analysierst Funnels, Onboarding-Abläufe und A/B-Test-Szenarien, um Reibungspunkte abzubauen und die Nutzeraktivierung zu maximieren." }
          ];

          await fetch("/api/roles", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(roles)
          });
          alert("Erfolgreich auf alle 24 Basis-Standardrollen zurückgesetzt.");
          populateSettingsRoleDropdown();
          if (roles.length > 0) loadRoleIntoSettingsEditor(roles[0].id);
        } catch (e) {
          alert("Fehler beim Zurücksetzen der Rollen: " + e);
        }
      }
    }

    async function loadBoardroomFrameworks() {
      await loadFrameworksFromServer();

      const select = document.getElementById("boardroom-framework-select");
      if (!select) return;
      
      const currentSelected = select.value || "Steffi Kieffer Boardroom";
      select.innerHTML = "";

      for (const [catName, frameworks] of Object.entries(categorizedFrameworksData)) {
        const group = document.createElement("optgroup");
        group.label = catName;

        for (const [fwName, fwVal] of Object.entries(frameworks)) {
          const opt = document.createElement("option");
          opt.value = fwName;
          opt.innerText = fwName;
          if (fwName === currentSelected) {
            opt.selected = true;
          }
          group.appendChild(opt);
        }
        select.appendChild(group);
      }

      updateFrameworkSummaryTooltip();
    }

    function updateFrameworkSummaryTooltip() {
      const select = document.getElementById("boardroom-framework-select");
      const tooltip = document.getElementById("boardroom-framework-summary");
      if (!select || !tooltip) return;

      const fwName = select.value;
      let foundInstruction = "Empathische, nutzerzentrierte Debatte mit Fokus auf Barrierefreiheit, KI-Ethik & Menschzentriertheit.";

      for (const [catName, frameworks] of Object.entries(categorizedFrameworksData)) {
        if (fwName in frameworks) {
          const fwVal = frameworks[fwName];
          foundInstruction = typeof fwVal === "string" ? fwVal : (fwVal.system_instruction || fwVal.summary || "");
          break;
        }
      }

      if (tooltip.tagName === "TEXTAREA" || tooltip.tagName === "INPUT") {
        tooltip.value = foundInstruction;
      } else {
        tooltip.innerText = foundInstruction;
      }
    }

    let boardroomRecognition = null;
    let isBoardroomDictating = false;

    function toggleBoardroomDictation() {
      const btn = document.getElementById("boardroom-mic-btn");
      const textarea = document.getElementById("boardroom-task");

      if (!("webkitSpeechRecognition" in window) && !("SpeechRecognition" in window)) {
        alert("Spracherkennung wird von diesem Browser leider nicht unterstützt. Bitte nutze Google Chrome oder Edge.");
        return;
      }

      if (isBoardroomDictating) {
        if (boardroomRecognition) boardroomRecognition.stop();
        isBoardroomDictating = false;
        if (btn) {
          btn.classList.remove("text-red-500", "animate-pulse", "border-red-500");
          btn.title = "Aufgabe diktieren (Mikrofon)";
        }
        return;
      }

      const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
      boardroomRecognition = new SpeechRecognition();
      boardroomRecognition.continuous = true;
      boardroomRecognition.interimResults = true;
      boardroomRecognition.lang = "de-DE";

      let baseText = textarea.value ? textarea.value.trim() + " " : "";

      boardroomRecognition.onresult = (event) => {
        let interimTranscript = "";
        let finalTranscript = "";
        for (let i = event.resultIndex; i < event.results.length; ++i) {
          if (event.results[i].isFinal) {
            finalTranscript += event.results[i][0].transcript;
          } else {
            interimTranscript += event.results[i][0].transcript;
          }
        }
        textarea.value = baseText + finalTranscript + interimTranscript;
      };

      boardroomRecognition.onerror = (event) => {
        console.error("Speech recognition error:", event.error);
        isBoardroomDictating = false;
        if (btn) btn.classList.remove("text-red-500", "animate-pulse", "border-red-500");
      };

      boardroomRecognition.onend = () => {
        isBoardroomDictating = false;
        if (btn) btn.classList.remove("text-red-500", "animate-pulse", "border-red-500");
      };

      boardroomRecognition.start();
      isBoardroomDictating = true;
      if (btn) {
        btn.classList.add("text-red-500", "animate-pulse", "border-red-500");
        btn.title = "Diktieren läuft... Klicken zum Stoppen";
      }
    }

    const originalOnload = window.onload;
    window.onload = async () => {
      if (originalOnload) await originalOnload();
      await loadThemeFromServer();
      await loadBoardroomFrameworks();
    };
  