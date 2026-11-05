/**
 * static/js/operations_projects.js
 * =================================
 * Projekt-Zentrale für Operations in Archon OS:
 * Zeigt alle laufenden, abgeschlossenen und geplanten Projekte mit
 * Fortschritt, Teilergebnissen und 1-Klick-Vorschau des HTML-Abschlussberichts.
 */

(function() {
  let allProjectsData = null;
  let activeFilter = "all"; // "all" | "in_progress" | "completed" | "planned"

  async function loadOperationsProjects() {
    const listContainer = document.getElementById("operations-projects-container");
    if (!listContainer) return;

    listContainer.innerHTML = `
      <div class="col-span-full py-16 flex flex-col items-center justify-center text-muted-custom">
        <i data-lucide="loader-2" class="w-7 h-7 animate-spin mb-3 text-sky-500"></i>
        <div class="text-xs font-mono">Lade Projekte und Artefakte aus dem Vault...</div>
      </div>
    `;
    if (window.lucide) window.lucide.createIcons();

    try {
      const res = await fetch("/api/operations/projects/overview");
      if (!res.ok) throw new Error("HTTP " + res.status);
      const data = await res.json();
      allProjectsData = data;
      renderOperationsProjects();
    } catch (err) {
      console.error("[OperationsProjects] Fehler:", err);
      listContainer.innerHTML = `
        <div class="col-span-full py-12 px-6 rounded-xl border border-red-500/20 bg-red-500/10 text-center text-red-400 text-xs font-mono">
          Fehler beim Laden der Projekte: ${escapeHtml(err.message)}
        </div>
      `;
    }
  }

  function setProjectsFilter(filter) {
    activeFilter = filter;
    document.querySelectorAll(".proj-filter-btn").forEach(btn => {
      const f = btn.dataset.filter;
      if (f === filter) {
        btn.className = "proj-filter-btn px-3 py-1.5 rounded-lg text-xs font-semibold bg-[var(--primary)] text-[var(--primary-foreground)] shadow-xs transition cursor-pointer";
      } else {
        btn.className = "proj-filter-btn px-3 py-1.5 rounded-lg text-xs font-medium border border-[var(--border)] bg-[var(--card)] hover:bg-[var(--secondary)] text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition cursor-pointer";
      }
    });
    renderOperationsProjects();
  }

  function renderOperationsProjects() {
    const listContainer = document.getElementById("operations-projects-container");
    if (!listContainer || !allProjectsData) return;

    const searchInput = document.getElementById("operations-projects-search");
    const query = (searchInput ? searchInput.value : "").trim().toLowerCase();

    let list = allProjectsData.all || [];
    if (activeFilter === "in_progress") list = allProjectsData.in_progress || [];
    else if (activeFilter === "completed") list = allProjectsData.completed || [];
    else if (activeFilter === "planned") list = allProjectsData.planned || [];

    if (query) {
      list = list.filter(p => 
        (p.title || "").toLowerCase().includes(query) ||
        (p.id || "").toLowerCase().includes(query) ||
        (p.folder || "").toLowerCase().includes(query) ||
        (p.assignees || []).some(a => a.toLowerCase().includes(query))
      );
    }

    // Update Counter Badges
    const bAll = document.getElementById("badge-count-all");
    const bProg = document.getElementById("badge-count-prog");
    const bComp = document.getElementById("badge-count-comp");
    const bPlan = document.getElementById("badge-count-plan");
    if (bAll) bAll.innerText = allProjectsData.total || 0;
    if (bProg) bProg.innerText = (allProjectsData.in_progress || []).length;
    if (bComp) bComp.innerText = (allProjectsData.completed || []).length;
    if (bPlan) bPlan.innerText = (allProjectsData.planned || []).length;

    if (list.length === 0) {
      listContainer.innerHTML = `
        <div class="col-span-full py-16 text-center text-muted-custom">
          <i data-lucide="folder-search" class="w-8 h-8 mx-auto mb-2 opacity-50"></i>
          <p class="text-xs font-mono">Keine Projekte in dieser Kategorie gefunden.</p>
        </div>
      `;
      if (window.lucide) window.lucide.createIcons();
      return;
    }

    listContainer.innerHTML = list.map(p => {
      const isDone = p.status === "completed";
      const isProg = p.status === "in_progress";
      const statusBadge = isDone
        ? `<span class="px-2 py-0.5 rounded-full text-[10px] font-bold font-mono bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border border-emerald-500/30 flex items-center gap-1"><span class="w-1.5 h-1.5 rounded-full bg-emerald-500"></span> Abgeschlossen</span>`
        : (isProg 
          ? `<span class="px-2 py-0.5 rounded-full text-[10px] font-bold font-mono bg-amber-500/15 text-amber-600 dark:text-amber-400 border border-amber-500/30 flex items-center gap-1"><span class="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse"></span> In Bearbeitung</span>`
          : `<span class="px-2 py-0.5 rounded-full text-[10px] font-bold font-mono bg-sky-500/15 text-sky-600 dark:text-sky-400 border border-sky-500/30 flex items-center gap-1"><span class="w-1.5 h-1.5 rounded-full bg-sky-500"></span> Geplant</span>`);

      const progressColor = isDone ? "bg-emerald-500" : (p.progress > 50 ? "bg-sky-500" : "bg-amber-500");
      
      const teamChips = (p.assignee_objects && p.assignee_objects.length > 0)
        ? p.assignee_objects.map(a => `
            <button type="button" 
                    onclick="event.stopPropagation(); openAgentChat('${escapeHtml(a.id)}', '${escapeHtml(a.person_name || a.id)}')" 
                    class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md text-[10.5px] font-medium bg-[var(--secondary)] hover:bg-indigo-500/15 text-[var(--foreground)] border border-[var(--border)] hover:border-indigo-500/50 transition cursor-pointer group/chip" 
                    title="Direktchat mit ${escapeHtml(a.person_name || a.id)} im Master Chat öffnen">
              <i data-lucide="message-square" class="w-3 h-3 text-indigo-500 group-hover/chip:scale-110 transition-transform"></i>
              <span class="font-bold text-[var(--foreground)]">${escapeHtml(a.person_name || a.id)}</span>
              ${a.role ? `<span class="text-[9.5px] text-muted-custom truncate max-w-[130px] font-normal">${escapeHtml(', ' + a.role.split('(')[0].trim())}</span>` : ''}
            </button>
          `).join("")
        : (p.assignees || []).map(a => `
            <button type="button" 
                    onclick="event.stopPropagation(); openAgentChat('${escapeHtml(a)}', '${escapeHtml(a)}')" 
                    class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md text-[10.5px] font-medium bg-[var(--secondary)] text-[var(--foreground)] border border-[var(--border)]">
              <i data-lucide="user" class="w-2.5 h-2.5 opacity-60"></i> ${escapeHtml(a)}
            </button>
          `).join("") || `<span class="text-[10px] text-muted-custom italic">Kernteam</span>`;

      const files = p.files_summary || { zwischenberichte: 0, medien: 0, endprodukte: 0 };
      const totalFiles = (files.zwischenberichte || 0) + (files.medien || 0) + (files.endprodukte || 0);

      // Buttons
      const htmlBtn = p.has_html_report && p.primary_document
        ? `<button onclick="openProjectHtmlReport('${escapeHtml(p.primary_document)}', '${escapeHtml(p.title)}')" class="h-8 px-3 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-semibold text-xs flex items-center gap-1.5 shadow-xs transition cursor-pointer">
             <i data-lucide="file-check-2" class="w-3.5 h-3.5"></i>
             <span>Abschlussbericht (HTML)</span>
           </button>`
        : (p.primary_document
          ? `<button onclick="openProjectDocument('${escapeHtml(p.primary_document)}', '${escapeHtml(p.title)}')" class="h-8 px-3 rounded-lg border border-[var(--border)] hover:bg-[var(--secondary)] text-[var(--foreground)] font-semibold text-xs flex items-center gap-1.5 shadow-2xs transition cursor-pointer">
               <i data-lucide="file-text" class="w-3.5 h-3.5 text-sky-500"></i>
               <span>Bericht (MD)</span>
             </button>`
          : ``);

      const filesBtn = `<button onclick="openProjectFolderModal('${escapeHtml(p.id)}', '${escapeHtml(p.title)}')" class="h-8 px-2.5 rounded-lg border border-[var(--border)] bg-[var(--card)] hover:bg-[var(--secondary)] text-[var(--foreground)] text-xs font-mono transition cursor-pointer flex items-center gap-1.5 shadow-2xs" title="Dateien durchsuchen">
        <i data-lucide="folder-open" class="w-3.5 h-3.5 text-amber-500"></i>
        <span>${totalFiles} Dateien</span>
      </button>`;

      const chatBtn = `<button onclick="openProjectInMasterChat('${escapeHtml(p.id)}', '${escapeHtml(p.title)}')" class="h-8 px-2.5 rounded-lg border border-[var(--border)] bg-[var(--card)] hover:bg-[var(--secondary)] text-[var(--foreground)] text-xs font-mono transition cursor-pointer flex items-center gap-1.5 shadow-2xs" title="Projekt im Master Chat mit Robert öffnen">
        <i data-lucide="message-square" class="w-3.5 h-3.5 text-indigo-500"></i>
        <span>Chat</span>
      </button>`;

      // Subtasks Collapsible
      const subtasksHtml = (p.subtasks && p.subtasks.length > 0) ? `
        <div class="mt-3 pt-3 border-t border-[var(--border)]/70">
          <div class="flex items-center justify-between text-[11px] font-mono text-muted-custom mb-2">
            <span>Aufgaben (${p.tasks_completed || 0} von ${p.tasks_total || 0} erledigt)</span>
            <button onclick="toggleProjectSubtasks('${escapeHtml(p.id)}')" class="text-sky-500 hover:underline cursor-pointer flex items-center gap-0.5">
              <span id="sub-toggle-lbl-${escapeHtml(p.id)}">Details anzeigen</span>
              <i data-lucide="chevron-down" id="sub-toggle-ico-${escapeHtml(p.id)}" class="w-3 h-3"></i>
            </button>
          </div>
          <div id="subtasks-list-${escapeHtml(p.id)}" class="hidden space-y-1.5 max-h-48 overflow-y-auto custom-scrollbar">
            ${p.subtasks.map(st => `
              <div class="flex items-start justify-between gap-2 p-1.5 rounded bg-[var(--secondary)]/40 border border-[var(--border)]/50 text-[11px] font-mono">
                <div class="min-w-0 flex-1">
                  <div class="font-medium text-[var(--foreground)] truncate">${escapeHtml(st.title || st.id)}</div>
                  <button type="button" 
                          onclick="event.stopPropagation(); openAgentChat('${escapeHtml(st.assignee || '')}', '${escapeHtml(st.assignee_person_name || st.assignee || '')}')" 
                          class="text-[10px] text-indigo-400 hover:text-indigo-300 hover:underline cursor-pointer inline-flex items-center gap-1 mt-0.5 text-left font-mono" 
                          title="Direktchat mit Agent öffnen">
                    <i data-lucide="user" class="w-2.5 h-2.5"></i>
                    <span class="font-semibold">${escapeHtml(st.assignee_person_name || st.assignee || 'unassigned')}</span>
                    ${st.assignee_title ? `<span class="text-[9px] text-muted-custom opacity-80 font-normal">${escapeHtml('(' + st.assignee_title.split('(')[0].trim() + ')')}</span>` : ''}
                  </button>
                </div>
                <span class="px-1.5 py-0.5 rounded text-[9px] uppercase font-bold shrink-0 ${st.status === 'done' || st.status === 'review' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-amber-500/20 text-amber-400'}">
                  ${escapeHtml(st.status || 'todo')}
                </span>
              </div>
            `).join("")}
          </div>
        </div>
      ` : ``;

      return `
        <div class="rounded-xl border border-[var(--border)] bg-[var(--card)] p-4 sm:p-5 flex flex-col justify-between shadow-xs hover:border-[var(--border)]/90 transition group">
          <div>
            <div class="flex items-start justify-between gap-2.5 mb-2.5">
              <div class="min-w-0 flex-1">
                <h3 class="text-sm sm:text-base font-bold text-[var(--foreground)] tracking-tight truncate" title="${escapeHtml(p.title)}">
                  ${escapeHtml(p.title)}
                </h3>
                <div class="text-[10px] font-mono text-muted-custom truncate mt-0.5">
                  📁 ${escapeHtml(p.folder || p.id)}
                </div>
              </div>
              <div class="shrink-0">
                ${statusBadge}
              </div>
            </div>

            <!-- Fortschrittsbalken -->
            <div class="my-3">
              <div class="flex items-center justify-between text-[10px] font-mono text-muted-custom mb-1">
                <span>Fortschritt</span>
                <span class="font-bold text-[var(--foreground)]">${p.progress}%</span>
              </div>
              <div class="w-full h-1.5 rounded-full bg-[var(--secondary)] overflow-hidden">
                <div class="${progressColor} h-full rounded-full transition-all duration-300" style="width: ${p.progress}%"></div>
              </div>
            </div>

            <!-- Team Chips -->
            <div class="flex flex-wrap gap-1.5 my-2.5">
              ${teamChips}
            </div>
          </div>

          <div>
            ${subtasksHtml}

            <!-- Card Actions Footer -->
            <div class="mt-4 pt-3 border-t border-[var(--border)] flex items-center justify-between gap-2 flex-wrap">
              <div class="flex items-center gap-1.5">
                ${filesBtn}
                ${chatBtn}
              </div>
              <div class="ml-auto">
                ${htmlBtn}
              </div>
            </div>
          </div>
        </div>
      `;
    }).join("");

    if (window.lucide) window.lucide.createIcons();
  }

  window.toggleProjectSubtasks = function(projId) {
    const list = document.getElementById(`subtasks-list-${projId}`);
    const lbl = document.getElementById(`sub-toggle-lbl-${projId}`);
    const ico = document.getElementById(`sub-toggle-ico-${projId}`);
    if (!list) return;
    const isHidden = list.classList.contains("hidden");
    if (isHidden) {
      list.classList.remove("hidden");
      if (lbl) lbl.innerText = "Ausblenden";
      if (ico) ico.style.transform = "rotate(180deg)";
    } else {
      list.classList.add("hidden");
      if (lbl) lbl.innerText = "Details anzeigen";
      if (ico) ico.style.transform = "rotate(0deg)";
    }
  };

  window.openProjectHtmlReport = function(relPath, title) {
    const rawUrl = "/api/operations/raw?path=" + encodeURIComponent("/opt/data/obsidian/" + relPath);
    // Open in interactive modal or new window
    window.open(rawUrl, "_blank", "noopener");
  };

  window.openProjectDocument = async function(relPath, title) {
    const rawUrl = "/api/operations/raw?path=" + encodeURIComponent("/opt/data/obsidian/" + relPath);
    try {
      const res = await fetch(rawUrl);
      if (res.ok) {
        const text = await res.text();
        if (typeof showArtifactPreviewModal === "function") {
          showArtifactPreviewModal(title, text, relPath);
        } else {
          window.open(rawUrl, "_blank", "noopener");
        }
      } else {
        window.open(rawUrl, "_blank", "noopener");
      }
    } catch(e) {
      window.open(rawUrl, "_blank", "noopener");
    }
  };

  window.openProjectFolderModal = async function(projId, title) {
    try {
      const res = await fetch(`/api/operations/kanban/projects/${encodeURIComponent(projId)}`);
      if (!res.ok) {
        // Fallback: Show alert or toast
        alert(`Projektordner: 01_PROJEKTE/${projId}\nAlle Dateien liegen im Obsidian Vault unter 01_Zwischenberichte, 02_Medien und 03_Endprodukte.`);
        return;
      }
      const data = await res.json();
      const files = data.files || [];
      const lines = files.map(f => `• [${f.dir || 'Root'}] ${f.name} (${Math.round(f.size/1024)} KB)`).join("\n");
      alert(`Dateien in ${title}:\n\n` + (lines || "Keine Dateien gefunden"));
    } catch(e) {
      alert(`Dateien in ${title} im Obsidian Vault unter 01_PROJEKTE abgelegt.`);
    }
  };

  window.openProjectInMasterChat = function(projId, title) {
    if (typeof setTab === "function") {
      setTab("master-chat");
      const input = document.getElementById("master-chat-input");
      if (input) {
        input.value = `Status-Update zu Projekt '${title}' (${projId}): Wie ist der aktuelle Umsetzungsstand?`;
        input.focus();
      }
    }
  };

  window.openAgentChat = function(agentId, agentName) {
    if (!agentId) return;
    if (typeof setTab === "function") {
      setTab("master-chat");
      setTimeout(() => {
        if (typeof switchMasterChatAgent === "function") {
          switchMasterChatAgent(agentId);
        }
      }, 50);
    }
  };

  window.loadOperationsProjects = loadOperationsProjects;
  window.renderOperationsProjects = renderOperationsProjects;
  window.setProjectsFilter = setProjectsFilter;
})();
