/**
 * static/js/operations_projects.js
 * =================================
 * Projekt-Zentrale für Operations in Archon OS:
 * - Projekt-Cards klickbar -> Detail-Modal (CRM-artig, Tabs: Übersicht / Aufgaben / Dateien)
 * - Aufgaben (Subtasks) NICHT mehr auf der Card (User-Entscheidung 19.11.2026):
 *   Card zeigt nur den Zähler "5/8 Aufgaben"; die Liste lebt im Detail-Modal,
 *   jeder Task dort direkt anklickbar -> öffnet den Kanban-Task-Detail-Dialog.
 * - Editierbare Felder (Beschreibung/Ziel/Status/Lead-Agent) via Sidecar config/projects_meta.json
 *   (Backend: PUT /api/operations/projects/{id}/meta, PROJEKT.md bleibt unangetastet).
 */

(function() {
  let allProjectsData = null;
  let activeFilter = "all"; // "all" | "in_progress" | "completed" | "planned"
  let projectModalEl = null;
  let projectModalTab = "overview";
  let projectModalProject = null;

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
        ? `<button onclick="event.stopPropagation(); openProjectHtmlReport('${escapeHtml(p.primary_document)}', '${escapeHtml(p.title)}')" class="h-8 px-3 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-semibold text-xs flex items-center gap-1.5 shadow-xs transition cursor-pointer">
             <i data-lucide="file-check-2" class="w-3.5 h-3.5"></i>
             <span>Abschlussbericht (HTML)</span>
           </button>`
        : (p.primary_document
          ? `<button onclick="event.stopPropagation(); openProjectDocument('${escapeHtml(p.primary_document)}', '${escapeHtml(p.title)}')" class="h-8 px-3 rounded-lg border border-[var(--border)] hover:bg-[var(--secondary)] text-[var(--foreground)] font-semibold text-xs flex items-center gap-1.5 shadow-2xs transition cursor-pointer">
               <i data-lucide="file-text" class="w-3.5 h-3.5 text-sky-500"></i>
               <span>Bericht (MD)</span>
             </button>`
          : ``);

      const filesBtn = `<button onclick="event.stopPropagation(); openProjectDetailModal('${escapeHtml(p.id)}', 'files')" class="h-8 px-2.5 rounded-lg border border-[var(--border)] bg-[var(--card)] hover:bg-[var(--secondary)] text-[var(--foreground)] text-xs font-mono transition cursor-pointer flex items-center gap-1.5 shadow-2xs" title="Dateien im Projekt-Detail öffnen">
        <i data-lucide="folder-open" class="w-3.5 h-3.5 text-amber-500"></i>
        <span>${totalFiles} Dateien</span>
      </button>`;

      const chatBtn = `<button onclick="event.stopPropagation(); openProjectInMasterChat('${escapeHtml(p.id)}', '${escapeHtml(p.title)}')" class="h-8 px-2.5 rounded-lg border border-[var(--border)] bg-[var(--card)] hover:bg-[var(--secondary)] text-[var(--foreground)] text-xs font-mono transition cursor-pointer flex items-center gap-1.5 shadow-2xs" title="Projekt im Master Chat mit Robert öffnen">
        <i data-lucide="message-square" class="w-3.5 h-3.5 text-indigo-500"></i>
        <span>Chat</span>
      </button>`;

      // 19.11.2026: Aufgaben NUR als Zähler auf der Card — die Liste lebt im Detail-Modal.
      const tasksLine = (p.tasks_total || 0) > 0
        ? `<div class="flex items-center justify-between text-[11px] font-mono text-muted-custom mb-2">
             <span class="inline-flex items-center gap-1.5">
               <i data-lucide="list-checks" class="w-3 h-3"></i> Aufgaben
             </span>
             <span class="font-bold text-[var(--foreground)]">${p.tasks_completed || 0}/${p.tasks_total || 0}</span>
           </div>`
        : ``;

      return `
        <div onclick="openProjectDetailModal('${escapeHtml(p.id)}')"
             class="rounded-xl border border-[var(--border)] bg-[var(--card)] p-4 sm:p-5 flex flex-col justify-between shadow-xs hover:border-sky-500/40 hover:shadow-sm transition group cursor-pointer"
             title="Projekt-Detail öffnen">
          <div>
            <div class="flex items-start justify-between gap-2.5 mb-2.5">
              <div class="min-w-0 flex-1">
                <h3 class="text-sm sm:text-base font-bold text-[var(--foreground)] tracking-tight truncate group-hover:text-sky-500 transition" title="${escapeHtml(p.title)}">
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

            <!-- Aufgaben-Zähler (Liste nur im Detail-Modal) -->
            ${tasksLine}

            <!-- Team Chips -->
            <div class="flex flex-wrap gap-1.5 my-2.5">
              ${teamChips}
            </div>
          </div>

          <div>
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

  // ==============================
  // Projekt-Detail-Modal (19.11.2026)
  // CRM-artig: Header + Tabs Übersicht / Aufgaben / Dateien.
  // Übersicht editierbar -> PUT /api/operations/projects/{id}/meta (Sidecar projects_meta.json).
  // ==============================

  function ensureProjectModal() {
    if (projectModalEl) return projectModalEl;
    projectModalEl = document.createElement("div");
    projectModalEl.id = "project-detail-modal";
    projectModalEl.className = "fixed inset-0 z-[70] hidden items-center justify-center p-4 bg-black/40 backdrop-blur-sm";
    projectModalEl.innerHTML = `
      <div class="relative w-full max-w-3xl max-h-[85vh] rounded-xl border border-[var(--border)] bg-[var(--card)] shadow-2xl flex flex-col overflow-hidden">
        <div class="flex items-start justify-between gap-3 p-5 border-b border-[var(--border)] shrink-0">
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-2 mb-1">
              <h2 id="pdm-title" class="text-lg font-bold text-[var(--foreground)] tracking-tight truncate">Projekt</h2>
              <span id="pdm-status-badge" class="shrink-0"></span>
            </div>
            <div id="pdm-folder" class="text-[10px] font-mono text-muted-custom truncate"></div>
          </div>
          <button onclick="closeProjectDetailModal()" class="shrink-0 w-8 h-8 rounded-lg flex items-center justify-center text-muted-custom hover:bg-[var(--secondary)] hover:text-[var(--foreground)] transition cursor-pointer" title="Schließen">
            <i data-lucide="x" class="w-4 h-4"></i>
          </button>
        </div>
        <div class="flex items-center gap-1 px-5 pt-3 border-b border-[var(--border)] shrink-0" id="pdm-tabs">
          <button onclick="switchProjectModalTab('overview')" data-tab="overview" class="pdm-tab px-3 py-2 text-xs font-semibold rounded-t-lg border-b-2 border-transparent text-muted-custom hover:text-[var(--foreground)] transition cursor-pointer">Übersicht</button>
          <button onclick="switchProjectModalTab('tasks')" data-tab="tasks" class="pdm-tab px-3 py-2 text-xs font-semibold rounded-t-lg border-b-2 border-transparent text-muted-custom hover:text-[var(--foreground)] transition cursor-pointer">Aufgaben</button>
          <button onclick="switchProjectModalTab('files')" data-tab="files" class="pdm-tab px-3 py-2 text-xs font-semibold rounded-t-lg border-b-2 border-transparent text-muted-custom hover:text-[var(--foreground)] transition cursor-pointer">Dateien</button>
        </div>
        <div id="pdm-body" class="flex-1 overflow-y-auto custom-scrollbar p-5"></div>
      </div>
    `;
    document.body.appendChild(projectModalEl);
    projectModalEl.addEventListener("click", (e) => {
      if (e.target === projectModalEl) closeProjectDetailModal();
    });
    return projectModalEl;
  }

  window.closeProjectDetailModal = function() {
    if (projectModalEl) projectModalEl.classList.add("hidden");
  };

  window.switchProjectModalTab = function(tab) {
    projectModalTab = tab;
    if (projectModalEl) {
      projectModalEl.querySelectorAll(".pdm-tab").forEach(btn => {
        const active = btn.dataset.tab === tab;
        btn.className = "pdm-tab px-3 py-2 text-xs font-semibold rounded-t-lg border-b-2 transition cursor-pointer " +
          (active
            ? "border-sky-500 text-sky-500"
            : "border-transparent text-muted-custom hover:text-[var(--foreground)]");
      });
    }
    renderProjectModalBody();
  };

  window.openProjectDetailModal = async function(projectId, tab) {
    if (!allProjectsData) return;
    const p = (allProjectsData.all || []).find(x => x.id === projectId);
    if (!p) return;
    projectModalProject = p;
    const modal = ensureProjectModal();
    modal.classList.remove("hidden");
    modal.classList.add("flex");

    document.getElementById("pdm-title").textContent = p.title || p.id;
    document.getElementById("pdm-folder").textContent = "📁 " + (p.folder || p.id) + "  ·  Lead: " + (p.lead_agent_display || p.lead_agent || "—");
    updateProjectModalStatusBadge(p.status);

    await fetchProjectMeta(projectId);
    switchProjectModalTab(tab || projectModalTab || "overview");
  };

  function updateProjectModalStatusBadge(status) {
    const el = document.getElementById("pdm-status-badge");
    if (!el) return;
    const map = {
      completed: ["bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border-emerald-500/30", "Abgeschlossen", "bg-emerald-500"],
      in_progress: ["bg-amber-500/15 text-amber-600 dark:text-amber-400 border-amber-500/30", "In Bearbeitung", "bg-amber-500 animate-pulse"],
      planned: ["bg-sky-500/15 text-sky-600 dark:text-sky-400 border-sky-500/30", "Geplant", "bg-sky-500"]
    };
    const [cls, label, dot] = map[status] || map.planned;
    el.className = "px-2 py-0.5 rounded-full text-[10px] font-bold font-mono border flex items-center gap-1 shrink-0 " + cls;
    el.innerHTML = `<span class="w-1.5 h-1.5 rounded-full ${dot}"></span> ${label}`;
  }

  async function fetchProjectMeta(projectId) {
    try {
      const res = await fetch(`/api/operations/projects/${encodeURIComponent(projectId)}/meta`);
      if (res.ok) {
        const data = await res.json();
        projectModalProject.meta = data.meta || {};
      }
    } catch (e) { /* Meta optional */ }
  }

  function renderProjectModalBody() {
    const body = document.getElementById("pdm-body");
    const p = projectModalProject;
    if (!body || !p) return;

    if (projectModalTab === "overview") {
      renderProjectOverviewTab(body, p);
    } else if (projectModalTab === "tasks") {
      renderProjectTasksTab(body, p);
    } else {
      renderProjectFilesTab(body, p);
    }
    if (window.lucide) window.lucide.createIcons();
  }

  // --- Tab: Übersicht (editierbar) ---
  function renderProjectOverviewTab(body, p) {
    const meta = p.meta || {};
    const desc = meta.description != null ? meta.description : (p.description || "");
    const goal = meta.goal != null ? meta.goal : (p.goal || "");
    const status = meta.status || p.status || "planned";
    const lead = meta.lead_agent || p.lead_agent || "";
    const cadre = (allProjectsData && allProjectsData.cadre_options) || [];

    const progressColor = status === "completed" ? "bg-emerald-500" : (p.progress > 50 ? "bg-sky-500" : "bg-amber-500");

    const teamChips = (p.assignee_objects && p.assignee_objects.length > 0)
      ? p.assignee_objects.map(a => `
          <button type="button"
                  onclick="openAgentChat('${escapeHtml(a.id)}', '${escapeHtml(a.person_name || a.id)}')"
                  class="inline-flex items-center gap-1.5 px-2 py-1 rounded-md text-[11px] font-medium bg-[var(--secondary)] hover:bg-indigo-500/15 text-[var(--foreground)] border border-[var(--border)] hover:border-indigo-500/50 transition cursor-pointer group/chip"
                  title="Direktchat mit ${escapeHtml(a.person_name || a.id)} öffnen">
            <i data-lucide="message-square" class="w-3 h-3 text-indigo-500 group-hover/chip:scale-110 transition-transform"></i>
            <span class="font-bold">${escapeHtml(a.person_name || a.id)}</span>
            ${a.role ? `<span class="text-[9.5px] text-muted-custom truncate max-w-[160px] font-normal">${escapeHtml(', ' + a.role.split('(')[0].trim())}</span>` : ''}
          </button>
        `).join("")
      : `<span class="text-[11px] text-muted-custom italic">Kernteam</span>`;

    const leadOptions = cadre.map(c =>
      `<option value="${escapeHtml(c.id)}" ${c.id === lead ? "selected" : ""}>${escapeHtml(c.display || c.id)}</option>`
    ).join("");

    body.innerHTML = `
      <div class="space-y-4">
        <div>
          <label class="text-[11px] font-mono text-muted-custom mb-1 block">Beschreibung / Mission</label>
          <textarea id="pdm-desc" rows="3" placeholder="Worum geht es in diesem Projekt?"
            class="w-full rounded-lg border border-[var(--border)] bg-[var(--secondary)]/50 px-3 py-2 text-xs text-[var(--foreground)] placeholder:text-muted-custom/60 focus:outline-none focus:border-sky-500/60 focus:ring-1 focus:ring-sky-500/30 resize-y font-mono">${escapeHtml(desc)}</textarea>
        </div>
        <div>
          <label class="text-[11px] font-mono text-muted-custom mb-1 block">Ziel</label>
          <textarea id="pdm-goal" rows="2" placeholder="Konkretes Ziel / Definition of Done"
            class="w-full rounded-lg border border-[var(--border)] bg-[var(--secondary)]/50 px-3 py-2 text-xs text-[var(--foreground)] placeholder:text-muted-custom/60 focus:outline-none focus:border-sky-500/60 focus:ring-1 focus:ring-sky-500/30 resize-y font-mono">${escapeHtml(goal)}</textarea>
        </div>
        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="text-[11px] font-mono text-muted-custom mb-1 block">Status</label>
            <select id="pdm-status" class="w-full rounded-lg border border-[var(--border)] bg-[var(--secondary)]/50 px-3 py-2 text-xs text-[var(--foreground)] focus:outline-none focus:border-sky-500/60 cursor-pointer">
              <option value="planned" ${status === "planned" ? "selected" : ""}>Geplant</option>
              <option value="in_progress" ${status === "in_progress" ? "selected" : ""}>In Bearbeitung</option>
              <option value="completed" ${status === "completed" ? "selected" : ""}>Abgeschlossen</option>
            </select>
          </div>
          <div>
            <label class="text-[11px] font-mono text-muted-custom mb-1 block">Lead-Agent</label>
            <select id="pdm-lead" class="w-full rounded-lg border border-[var(--border)] bg-[var(--secondary)]/50 px-3 py-2 text-xs text-[var(--foreground)] focus:outline-none focus:border-sky-500/60 cursor-pointer">
              ${leadOptions || `<option value="${escapeHtml(lead)}">${escapeHtml(p.lead_agent_display || lead)}</option>`}
            </select>
          </div>
        </div>

        <div>
          <div class="flex items-center justify-between text-[10px] font-mono text-muted-custom mb-1">
            <span>Fortschritt (${p.tasks_completed || 0}/${p.tasks_total || 0} Aufgaben)</span>
            <span class="font-bold text-[var(--foreground)]">${p.progress}%</span>
          </div>
          <div class="w-full h-1.5 rounded-full bg-[var(--secondary)] overflow-hidden">
            <div class="${progressColor} h-full rounded-full transition-all duration-300" style="width: ${p.progress}%"></div>
          </div>
        </div>

        <div>
          <label class="text-[11px] font-mono text-muted-custom mb-1.5 block">Zugewiesene Agenten</label>
          <div class="flex flex-wrap gap-1.5">${teamChips}</div>
        </div>

        <div class="flex items-center justify-between gap-2 pt-3 border-t border-[var(--border)]">
          <span id="pdm-save-msg" class="text-[11px] font-mono text-muted-custom"></span>
          <button onclick="saveProjectMeta()" id="pdm-save-btn"
            class="h-9 px-4 rounded-lg bg-sky-600 hover:bg-sky-500 text-white font-semibold text-xs flex items-center gap-1.5 shadow-xs transition cursor-pointer">
            <i data-lucide="save" class="w-3.5 h-3.5"></i>
            <span>Speichern</span>
          </button>
        </div>
      </div>
    `;
  }

  window.saveProjectMeta = async function() {
    const p = projectModalProject;
    if (!p) return;
    const btn = document.getElementById("pdm-save-btn");
    const msg = document.getElementById("pdm-save-msg");
    const payload = {
      description: ((document.getElementById("pdm-desc") || {}).value ?? "").trim(),
      goal: ((document.getElementById("pdm-goal") || {}).value ?? "").trim(),
      status: (document.getElementById("pdm-status") || {}).value || null,
      lead_agent: (document.getElementById("pdm-lead") || {}).value || null
    };
    if (btn) { btn.disabled = true; btn.innerHTML = `<i data-lucide="loader-2" class="w-3.5 h-3.5 animate-spin"></i><span>Speichere...</span>`; if (window.lucide) window.lucide.createIcons(); }
    try {
      const res = await fetch(`/api/operations/projects/${encodeURIComponent(p.id)}/meta`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (!res.ok) {
        const txt = await res.text();
        throw new Error("HTTP " + res.status + (txt ? ": " + txt.slice(0, 120) : ""));
      }
      const data = await res.json();
      p.meta = data.meta || {};
      if (msg) { msg.textContent = "Gespeichert ✓"; msg.className = "text-[11px] font-mono text-emerald-500"; }
      await loadOperationsProjects();
      // Status-Badge im Modal aktualisieren (ohne Re-Render des Bodies, damit Felder nicht verloren gehen)
      const merged = (allProjectsData.all || []).find(x => x.id === p.id);
      if (merged) updateProjectModalStatusBadge(merged.status);
    } catch (err) {
      if (msg) { msg.textContent = "Fehler: " + err.message; msg.className = "text-[11px] font-mono text-red-400"; }
    } finally {
      if (btn) { btn.disabled = false; btn.innerHTML = `<i data-lucide="save" class="w-3.5 h-3.5"></i><span>Speichern</span>`; if (window.lucide) window.lucide.createIcons(); }
    }
  };

  // --- Tab: Aufgaben (Liste, direkt anklickbar -> Kanban-Task-Detail) ---
  function renderProjectTasksTab(body, p) {
    const subtasks = p.subtasks || [];
    if (subtasks.length === 0) {
      body.innerHTML = `
        <div class="py-12 text-center text-muted-custom">
          <i data-lucide="list-checks" class="w-8 h-8 mx-auto mb-2 opacity-50"></i>
          <p class="text-xs font-mono">Keine Aufgaben für dieses Projekt verknüpft.</p>
          <p class="text-[10px] font-mono opacity-70 mt-1">Aufgaben werden im Operations-Kanban gepflegt.</p>
        </div>`;
      return;
    }
    body.innerHTML = `
      <div class="flex items-center justify-between text-[11px] font-mono text-muted-custom mb-3">
        <span>${p.tasks_completed || 0} von ${p.tasks_total || 0} erledigt</span>
        <span class="opacity-70">Klick auf eine Aufgabe öffnet den Kanban-Detail-Dialog</span>
      </div>
      <div class="space-y-1.5">
        ${subtasks.map(st => `
          <div onclick="openTaskDetailModal('${escapeHtml(st.id)}')"
               class="flex items-start justify-between gap-2 p-2.5 rounded-lg bg-[var(--secondary)]/40 border border-[var(--border)]/50 hover:border-sky-500/40 hover:bg-[var(--secondary)]/70 transition cursor-pointer">
            <div class="min-w-0 flex-1">
              <div class="font-medium text-[12px] text-[var(--foreground)]">${escapeHtml(st.title || st.id)}</div>
              <button type="button"
                      onclick="event.stopPropagation(); openAgentChat('${escapeHtml(st.assignee || '')}', '${escapeHtml(st.assignee_person_name || st.assignee || '')}')"
                      class="text-[10px] text-indigo-400 hover:text-indigo-300 hover:underline cursor-pointer inline-flex items-center gap-1 mt-0.5 text-left font-mono"
                      title="Direktchat mit Agent öffnen">
                <i data-lucide="user" class="w-2.5 h-2.5"></i>
                <span class="font-semibold">${escapeHtml(st.assignee_person_name || st.assignee || 'unassigned')}</span>
                ${st.assignee_title ? `<span class="text-[9px] text-muted-custom opacity-80 font-normal">${escapeHtml('(' + st.assignee_title.split('(')[0].trim() + ')')}</span>` : ''}
              </button>
            </div>
            <span class="px-1.5 py-0.5 rounded text-[9px] uppercase font-bold shrink-0 ${st.status === 'done' || st.status === 'review' || st.status === 'completed' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-amber-500/20 text-amber-400'}">
              ${escapeHtml(st.status || 'todo')}
            </span>
          </div>
        `).join("")}
      </div>
    `;
  }

  // --- Tab: Dateien (ersetzt den alten alert()-Placeholder) ---
  function renderProjectFilesTab(body, p) {
    body.innerHTML = `
      <div class="py-12 flex flex-col items-center justify-center text-muted-custom">
        <i data-lucide="loader-2" class="w-6 h-6 animate-spin mb-2 text-sky-500"></i>
        <div class="text-xs font-mono">Lade Dateien...</div>
      </div>`;
    fetch(`/api/operations/projects/${encodeURIComponent(p.id)}/files`)
      .then(res => { if (!res.ok) throw new Error("HTTP " + res.status); return res.json(); })
      .then(data => {
        const files = data.files || [];
        if (files.length === 0) {
          body.innerHTML = `
            <div class="py-12 text-center text-muted-custom">
              <i data-lucide="folder-open" class="w-8 h-8 mx-auto mb-2 opacity-50"></i>
              <p class="text-xs font-mono">Keine Dateien im Projektordner <span class="text-[var(--foreground)]">${escapeHtml(data.folder || "")}</span>.</p>
            </div>`;
        } else {
          const byDir = {};
          files.forEach(f => { (byDir[f.dir] = byDir[f.dir] || []).push(f); });
          const dirOrder = ["Root", "01_Zwischenberichte", "02_Medien", "03_Endprodukte"];
          const dirs = Object.keys(byDir).sort((a, b) => {
            const ia = dirOrder.indexOf(a), ib = dirOrder.indexOf(b);
            return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
          });
          body.innerHTML = `
            <div class="text-[11px] font-mono text-muted-custom mb-3">${files.length} Dateien in ${escapeHtml(data.folder || "")}</div>
            <div class="space-y-4">
              ${dirs.map(d => `
                <div>
                  <div class="text-[10px] font-mono uppercase tracking-wide text-muted-custom mb-1.5 flex items-center gap-1.5">
                    <i data-lucide="folder" class="w-3 h-3 text-amber-500"></i> ${escapeHtml(d)}
                  </div>
                  <div class="space-y-1">
                    ${byDir[d].map(f => `
                      <div onclick="openProjectDocument('${escapeHtml(f.path)}', '${escapeHtml(f.name)}')"
                           class="flex items-center justify-between gap-2 px-2.5 py-1.5 rounded-lg bg-[var(--secondary)]/40 border border-[var(--border)]/50 hover:border-sky-500/40 hover:bg-[var(--secondary)]/70 transition cursor-pointer">
                        <span class="text-[11.5px] font-mono text-[var(--foreground)] truncate">${escapeHtml(f.name)}</span>
                        <span class="text-[10px] font-mono text-muted-custom shrink-0">${Math.round(f.size / 1024)} KB</span>
                      </div>
                    `).join("")}
                  </div>
                </div>
              `).join("")}
            </div>`;
        }
        if (window.lucide) window.lucide.createIcons();
      })
      .catch(err => {
        body.innerHTML = `
          <div class="py-10 px-6 rounded-xl border border-red-500/20 bg-red-500/10 text-center text-red-400 text-xs font-mono">
            Fehler beim Laden der Dateien: ${escapeHtml(err.message)}
          </div>`;
      });
  }

  // ESC schließt das Modal
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && projectModalEl && !projectModalEl.classList.contains("hidden")) {
      closeProjectDetailModal();
    }
  });

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
