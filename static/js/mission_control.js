
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
    // --- OPERATIONS ORCHESTRATOR ---
    function reloadPaperclipIframe() {}
    async function runPaperclip() {}
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