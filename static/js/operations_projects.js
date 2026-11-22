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

    let list = (allProjectsData.all || []).filter(p => !p.archived);
    if (activeFilter === "in_progress") list = allProjectsData.in_progress || [];
    else if (activeFilter === "completed") list = allProjectsData.completed || [];
    else if (activeFilter === "planned") list = allProjectsData.planned || [];
    else if (activeFilter === "archived") list = allProjectsData.archived || [];

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
    const bArch = document.getElementById("badge-count-arch");
    if (bAll) bAll.innerText = allProjectsData.total || 0;
    if (bProg) bProg.innerText = (allProjectsData.in_progress || []).length;
    if (bComp) bComp.innerText = (allProjectsData.completed || []).length;
    if (bPlan) bPlan.innerText = (allProjectsData.planned || []).length;
    if (bArch) bArch.innerText = (allProjectsData.archived || []).length;

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
        ? p.assignee_objects.map(a =>
            renderAgentIdentityBadge(
              a.id,
              a.person_name || a.id,
              a.avatar_url,
              `event.stopPropagation(); openAgentChat('${escapeHtml(a.id)}', '${escapeHtml(a.person_name || a.id)}')`
            )
          ).join("")
        : (p.assignees || []).map(a =>
            renderAgentIdentityBadge(
              a,
              a,
              null,
              `event.stopPropagation(); openAgentChat('${escapeHtml(a)}', '${escapeHtml(a)}')`
            )
          ).join("") || `<span class="text-[10px] text-muted-custom italic">Kernteam</span>`;

      const files = p.files_summary || { zwischenberichte: 0, medien: 0, endprodukte: 0 };
      const totalFiles = (files.zwischenberichte || 0) + (files.medien || 0) + (files.endprodukte || 0);

      // Buttons: Bericht öffnet direkt den Ergebnisse-Tab im Detail-Modal
      const htmlBtn = p.has_html_report && p.primary_document
        ? `<button onclick="event.stopPropagation(); openProjectDetailModal('${escapeHtml(p.id)}', 'results')" class="h-8 px-3 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-semibold text-xs flex items-center gap-1.5 shadow-xs transition cursor-pointer">
             <i data-lucide="file-check-2" class="w-3.5 h-3.5"></i>
             <span>Bericht</span>
           </button>`
        : (p.primary_document
          ? `<button onclick="event.stopPropagation(); openProjectDetailModal('${escapeHtml(p.id)}', 'results')" class="h-8 px-3 rounded-lg border border-[var(--border)] hover:bg-[var(--secondary)] text-[var(--foreground)] font-semibold text-xs flex items-center gap-1.5 shadow-2xs transition cursor-pointer">
               <i data-lucide="file-text" class="w-3.5 h-3.5 text-sky-500"></i>
               <span>Bericht</span>
             </button>`
          : ``);

      const archiveBtn = `<button onclick="event.stopPropagation(); toggleProjectArchive('${escapeHtml(p.id)}', ${p.archived ? 'false' : 'true'})" class="h-8 px-2.5 rounded-lg border border-[var(--border)] bg-[var(--card)] hover:bg-[var(--secondary)] text-[var(--muted-foreground)] hover:text-[var(--foreground)] text-xs font-mono transition cursor-pointer flex items-center gap-1.5 shadow-2xs" title="${p.archived ? 'Aus Archiv wiederherstellen' : 'Projekt archivieren'}">
        <i data-lucide="${p.archived ? 'archive-restore' : 'archive'}" class="w-3.5 h-3.5"></i>
        <span>${p.archived ? 'Wiederherstellen' : 'Archiv'}</span>
      </button>`;

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

      const taskNum = p.task_number || formatTaskNumber(p.created_at) || String(p.seq_number || '');
      const dateStr = formatOpDate(p.created_at, false);
      const leadDisplay = p.lead_agent_display || p.lead_agent || '—';

      return `
        <div onclick="openProjectDetailModal('${escapeHtml(p.id)}')"
             class="rounded-xl border border-[var(--border)] bg-[var(--card)] p-4 sm:p-5 flex flex-col justify-between shadow-xs hover:border-sky-500/40 hover:shadow-sm transition group cursor-pointer"
             title="Projekt-Detail öffnen">
          <div>
            <div class="space-y-1.5 mb-2.5">
              <!-- Reihe 1: Dick & schwarz die Taskbezeichnung -->
              <h3 class="text-sm sm:text-base font-black text-zinc-950 dark:text-zinc-50 tracking-tight truncate group-hover:text-sky-500 transition" title="${escapeHtml(p.title)}">
                ${escapeHtml(p.title)}
              </h3>
              <!-- Reihe 2: 2 Spalten: links Lead/Auftraggeber, rechts Status -->
              <div class="flex items-center justify-between gap-2 pt-0.5">
                <span class="text-[11px] font-mono text-muted-custom truncate min-w-0" title="${escapeHtml(leadDisplay)}">
                  Lead: <strong class="text-[var(--foreground)] font-semibold">${escapeHtml(leadDisplay)}</strong>
                </span>
                <div class="shrink-0">
                  ${statusBadge}
                </div>
              </div>
              <!-- Reihe 3: Schlichte Tasknummer (YYYYMMDDHHMMSS) & US-Datum -->
              <div class="flex items-center justify-between gap-2 text-[10.5px] font-mono text-muted-custom pt-0.5">
                <span>${escapeHtml(taskNum)}</span>
                <span>${escapeHtml(dateStr)}</span>
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
              <div class="ml-auto flex items-center gap-1.5">
                ${htmlBtn}
                ${archiveBtn}
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

  function parseOpDate(val) {
    if (val === null || val === undefined || val === "") return null;
    const s = String(val).trim();
    if (/^\d+(\.\d+)?$/.test(s)) {
      let num = Number(s);
      if (num > 0 && num < 1e12) num *= 1000;
      const d = new Date(num);
      return Number.isNaN(d.getTime()) ? null : d;
    }
    const d = new Date(s);
    return Number.isNaN(d.getTime()) ? null : d;
  }

  function formatOpDate(iso, withTime) {
    const d = parseOpDate(iso);
    if (!d) return "";
    const mm = String(d.getMonth() + 1).padStart(2, "0");
    const dd = String(d.getDate()).padStart(2, "0");
    const yyyy = d.getFullYear();
    if (!withTime) return `${mm}/${dd}/${yyyy}`;
    const hh = String(d.getHours()).padStart(2, "0");
    const min = String(d.getMinutes()).padStart(2, "0");
    return `${mm}/${dd}/${yyyy} ${hh}:${min}`;
  }

  function formatTaskNumber(iso) {
    const d = parseOpDate(iso);
    if (!d) return "";
    return (
      String(d.getFullYear()) +
      String(d.getMonth() + 1).padStart(2, "0") +
      String(d.getDate()).padStart(2, "0") +
      String(d.getHours()).padStart(2, "0") +
      String(d.getMinutes()).padStart(2, "0") +
      String(d.getSeconds()).padStart(2, "0")
    );
  }

  function renderAgentIdentityBadge(id, name, avatarUrl, onClickExpr) {
    const safeId = escapeHtml(id || "unassigned");
    const safeName = escapeHtml(name || id || "Unassigned");
    const fallbackSrc = "/static/avatars/hermes_default_avatar.png";
    const svgFallback = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Ccircle cx='16' cy='16' r='16' fill='%23334155'/%3E%3Ccircle cx='16' cy='12' r='5' fill='%23cbd5e1'/%3E%3Cpath d='M6 27c1.8-5 6-7 10-7s8.2 2 10 7' fill='%23cbd5e1'/%3E%3C/svg%3E";
    const src = escapeHtml(avatarUrl || fallbackSrc);
    return `
      <button type="button"
              onclick="${onClickExpr}"
              class="inline-flex items-center gap-2 px-2.5 py-1.5 rounded-xl bg-[var(--secondary)] hover:bg-indigo-500/10 text-[var(--foreground)] border border-[var(--border)] hover:border-indigo-500/40 transition cursor-pointer text-left shrink-0"
              title="Direktchat mit ${safeName} öffnen">
        <img src="${src}" onerror="if(this.dataset.fb){this.onerror=null;this.src='${svgFallback}';}else{this.dataset.fb='1';this.src='${fallbackSrc}';}" alt="${safeName}"
             class="w-7 h-7 rounded-full object-cover border border-[var(--border)] bg-[var(--card)] shrink-0">
        <div class="min-w-0 leading-tight">
          <div class="text-[11px] font-bold text-[var(--foreground)] truncate max-w-[160px]">${safeName}</div>
          <div class="text-[9.5px] font-mono text-muted-custom truncate max-w-[160px]">${safeId}</div>
        </div>
      </button>
    `;
  }

  function renderFormattedResult(rawText) {
    const txt = (rawText || "").trim();
    if (!txt) return "";
    if (window.marked && typeof window.marked.parse === "function") {
      try {
        return `<div class="prose prose-xs dark:prose-invert max-w-none text-xs leading-relaxed">${DOMPurify.sanitize(window.marked.parse(txt))}</div>`;
      } catch (e) { /* fallback */ }
    }
    return `<div class="text-xs text-[var(--foreground)] leading-relaxed whitespace-pre-wrap font-sans">${escapeHtml(txt)}</div>`;
  }

  function getSubtasksTabLabel() {
    if (typeof window.t === "function") {
      return window.t("view.operations.subtasks_tab", "Teilaufgaben");
    }
    const lang = (localStorage.getItem("archon_lang") || document.documentElement.lang || "de").toLowerCase();
    return lang.startsWith("en") ? "Sub-Tasks" : "Teilaufgaben";
  }

  function ensureProjectModal() {
    if (projectModalEl) return projectModalEl;
    projectModalEl = document.createElement("div");
    projectModalEl.id = "project-detail-modal";
    projectModalEl.className = "fixed inset-0 z-[99999] hidden items-center justify-center p-4 bg-black/50 backdrop-blur-md";
    projectModalEl.innerHTML = `
      <div class="relative w-[96vw] max-w-6xl h-[88vh] max-h-[88vh] rounded-2xl border border-[var(--border)] bg-[var(--card)] shadow-2xl flex flex-col overflow-hidden">
        <div class="flex items-start justify-between gap-3 p-5 border-b border-[var(--border)] shrink-0">
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-2 mb-1">
              <span id="pdm-seq-badge" class="hidden px-1.5 py-0.5 rounded bg-[var(--secondary)] border border-[var(--border)] text-[10px] font-mono font-bold text-[var(--muted-foreground)] shrink-0"></span>
              <h2 id="pdm-title" class="text-lg font-bold text-[var(--foreground)] tracking-tight truncate">Projekt</h2>
              <span id="pdm-status-badge" class="shrink-0"></span>
            </div>
            <div id="pdm-folder" class="text-[10px] font-mono text-muted-custom truncate"></div>
          </div>
          <button onclick="closeProjectDetailModal()" class="shrink-0 w-8 h-8 rounded-lg flex items-center justify-center text-muted-custom hover:bg-[var(--secondary)] hover:text-[var(--foreground)] transition cursor-pointer" title="Schließen">
            <i data-lucide="x" class="w-4 h-4"></i>
          </button>
        </div>
        <div class="flex items-center gap-1 px-5 pt-3 border-b border-[var(--border)] shrink-0 overflow-x-auto" id="pdm-tabs">
          <button onclick="switchProjectModalTab('overview')" data-tab="overview" class="pdm-tab px-3 py-2 text-xs font-semibold rounded-t-lg border-b-2 border-transparent text-muted-custom hover:text-[var(--foreground)] transition cursor-pointer whitespace-nowrap">Übersicht</button>
          <button onclick="switchProjectModalTab('tasks')" data-tab="tasks" id="pdm-tab-btn-tasks" class="pdm-tab px-3 py-2 text-xs font-semibold rounded-t-lg border-b-2 border-transparent text-muted-custom hover:text-[var(--foreground)] transition cursor-pointer whitespace-nowrap">${escapeHtml(getSubtasksTabLabel())}</button>
          <button onclick="switchProjectModalTab('tools')" data-tab="tools" class="pdm-tab px-3 py-2 text-xs font-semibold rounded-t-lg border-b-2 border-transparent text-muted-custom hover:text-[var(--foreground)] transition cursor-pointer whitespace-nowrap">Tools</button>
          <button onclick="switchProjectModalTab('files')" data-tab="files" class="pdm-tab px-3 py-2 text-xs font-semibold rounded-t-lg border-b-2 border-transparent text-muted-custom hover:text-[var(--foreground)] transition cursor-pointer whitespace-nowrap">Dateien</button>
          <button onclick="switchProjectModalTab('results')" data-tab="results" class="pdm-tab px-3 py-2 text-xs font-semibold rounded-t-lg border-b-2 border-transparent text-muted-custom hover:text-[var(--foreground)] transition cursor-pointer whitespace-nowrap">Ergebnisse</button>
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

    const seqEl = document.getElementById("pdm-seq-badge");
    const taskNum = p.task_number || formatTaskNumber(p.created_at) || "";
    if (seqEl) {
      seqEl.classList.add("hidden");
    }
    const tasksBtn = document.getElementById("pdm-tab-btn-tasks");
    if (tasksBtn) tasksBtn.textContent = getSubtasksTabLabel();
    const dtStr = formatOpDate(p.created_at, false);
    document.getElementById("pdm-title").textContent = p.title || p.id;
    const headerMetaParts = [
      taskNum,
      dtStr,
      "Lead: " + (p.lead_agent_display || p.lead_agent || "—"),
    ].filter(Boolean);
    document.getElementById("pdm-folder").textContent = headerMetaParts.join(" | ");
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
    } else if (projectModalTab === "tools") {
      renderProjectToolsTab(body, p);
    } else if (projectModalTab === "results") {
      renderProjectResultsTab(body, p);
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
      ? p.assignee_objects.map(a =>
          renderAgentIdentityBadge(
            a.id,
            a.person_name || a.id,
            a.avatar_url,
            `openAgentChat('${escapeHtml(a.id)}', '${escapeHtml(a.person_name || a.id)}')`
          )
        ).join("")
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
        <div>
          <label class="text-[11px] font-mono text-muted-custom mb-1 block">Speicherort (Obsidian-Ordner)</label>
          <button type="button" onclick="openProjectObsidianFolder('${escapeHtml(p.folder || ("01_PROJEKTE/" + p.id))}')"
            class="w-full flex items-center justify-between gap-3 rounded-lg border border-[var(--border)] bg-[var(--secondary)]/50 hover:bg-[var(--secondary)] hover:border-amber-500/50 px-3 py-2 text-xs font-mono text-[var(--foreground)] transition cursor-pointer text-left"
            title="Obsidian-Ordner öffnen">
            <span class="flex items-center gap-2 min-w-0">
              <i data-lucide="folder-open" class="w-4 h-4 text-amber-500 shrink-0"></i>
              <span class="break-all">${escapeHtml(p.folder || ("01_PROJEKTE/" + p.id))}</span>
            </span>
            <span class="text-[10px] text-amber-600 dark:text-amber-400 font-bold shrink-0 flex items-center gap-1">
              <span>Obsidian öffnen</span>
              <i data-lucide="external-link" class="w-3 h-3"></i>
            </span>
          </button>
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

  // --- Tab: Teilaufgaben (Liste mit Avatar/Name/ID, Datum, Token, Modell & Kosten) ---
  function renderProjectTasksTab(body, p) {
    const subtasks = p.subtasks || [];
    if (subtasks.length === 0) {
      body.innerHTML = `
        <div class="py-12 text-center text-muted-custom">
          <i data-lucide="list-checks" class="w-8 h-8 mx-auto mb-2 opacity-50"></i>
          <p class="text-xs font-mono">Keine Teilaufgaben für dieses Projekt verknüpft.</p>
          <p class="text-[10px] font-mono opacity-70 mt-1">Teilaufgaben werden im Operations-Kanban gepflegt.</p>
        </div>`;
      return;
    }
    const totalTokens = Number(p.total_tokens || 0);
    const totalCost = Number(p.total_cost_usd || 0);
    body.innerHTML = `
      <div class="flex flex-wrap items-center justify-between gap-2 text-[11px] font-mono text-muted-custom mb-3 pb-2 border-b border-[var(--border)]">
        <span>${p.tasks_completed || 0} von ${p.tasks_total || 0} erledigt</span>
        <div class="flex items-center gap-3">
          <span>Gesamt: <strong class="text-[var(--foreground)]">${totalTokens.toLocaleString('de-DE')} Tokens</strong></span>
          <span>Kosten: <strong class="text-emerald-600 dark:text-emerald-400">$${totalCost.toFixed(4)}</strong></span>
        </div>
      </div>
      <div class="space-y-2">
        ${subtasks.map(st => {
          const stTokens = Number(st.tokens_total || 0);
          const stCost = Number(st.cost_usd || 0);
          const stModel = st.model || "—";
          const stDate = formatOpDate(st.created_at, true);
          const agentBadge = renderAgentIdentityBadge(
            st.assignee || "unassigned",
            st.assignee_person_name || st.assignee || "Unassigned",
            st.assignee_avatar,
            `event.stopPropagation(); openAgentChat('${escapeHtml(st.assignee || '')}', '${escapeHtml(st.assignee_person_name || st.assignee || '')}')`
          );
          return `
          <div onclick="openTaskDetailModal('${escapeHtml(st.id)}')"
               class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-3 rounded-xl bg-[var(--secondary)]/35 border border-[var(--border)]/70 hover:border-sky-500/40 hover:bg-[var(--secondary)]/65 transition cursor-pointer">
            <div class="min-w-0 flex-1 space-y-1.5">
              <div class="flex items-center gap-2 flex-wrap">
                <span class="font-semibold text-[12.5px] text-[var(--foreground)]">${escapeHtml(st.title || st.id)}</span>
                ${stDate ? `<span class="text-[10px] font-mono text-muted-custom">· ${escapeHtml(stDate)}</span>` : ''}
              </div>
              <div class="flex items-center gap-2 flex-wrap">
                ${agentBadge}
              </div>
            </div>
            <div class="flex sm:flex-col items-end justify-between sm:justify-center gap-1.5 shrink-0 text-right font-mono">
              <span class="px-1.5 py-0.5 rounded text-[9px] uppercase font-bold ${st.status === 'done' || st.status === 'review' || st.status === 'completed' ? 'bg-emerald-500/20 text-emerald-500' : 'bg-amber-500/20 text-amber-500'}">
                ${escapeHtml(st.status || 'todo')}
              </span>
              <div class="text-[10px] text-muted-custom space-y-0.5">
                <div class="truncate max-w-[190px]" title="${escapeHtml(stModel)}">🤖 ${escapeHtml(stModel)}</div>
                <div>${stTokens.toLocaleString('de-DE')} Tok · <span class="text-emerald-600 dark:text-emerald-400 font-bold">$${stCost.toFixed(4)}</span></div>
              </div>
            </div>
          </div>`;
        }).join("")}
      </div>
    `;
  }

  // --- Tab: Tools (Freigegebene & eingesetzte Tools + Token-Umfang) ---
  function renderProjectToolsTab(body, p) {
    const approved = p.approved_tools || [];
    const used = p.used_tools || [];
    const subtasks = p.subtasks || [];
    const perToolStats = {};
    subtasks.forEach(st => {
      const tList = st.tools_used || [];
      const perToolTok = tList.length > 0 ? Math.round((st.tokens_total || 0) / tList.length) : 0;
      tList.forEach(tName => {
        if (!perToolStats[tName]) perToolStats[tName] = { calls: 0, tokens: 0 };
        perToolStats[tName].calls += Math.max(1, Number(st.tool_call_count || 1));
        perToolStats[tName].tokens += perToolTok;
      });
    });

    body.innerHTML = `
      <div class="space-y-4">
        <div class="p-3.5 rounded-xl border border-[var(--border)] bg-[var(--background)] space-y-2">
          <div class="text-[11px] font-mono font-bold uppercase tracking-wider text-[var(--foreground)]">Eingesetzte Tools &amp; Token-Umfang</div>
          ${used.length === 0
            ? `<p class="text-xs font-mono text-muted-custom italic">Bisher keine Tool-Aufrufe für die Teilaufgaben protokolliert.</p>`
            : `<div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
                ${used.map(t => {
                  const st = perToolStats[t] || { calls: 0, tokens: 0 };
                  return `
                    <div class="flex items-center justify-between px-3 py-2 rounded-lg border border-[var(--border)] bg-[var(--card)] text-xs font-mono">
                      <span class="font-bold text-[var(--foreground)] truncate">${escapeHtml(t)}</span>
                      <span class="text-[10.5px] text-muted-custom shrink-0">${st.tokens.toLocaleString('de-DE')} Tok</span>
                    </div>`;
                }).join("")}
               </div>`}
        </div>
        <div class="p-3.5 rounded-xl border border-[var(--border)] bg-[var(--background)] space-y-2">
          <div class="text-[11px] font-mono font-bold uppercase tracking-wider text-[var(--foreground)]">Freigegebene Profil-Tools (${approved.length})</div>
          ${approved.length === 0
            ? `<p class="text-xs font-mono text-muted-custom italic">Keine expliziten Tool-Freigaben im Profil hinterlegt.</p>`
            : `<div class="flex flex-wrap gap-1.5">
                ${approved.map(t => `<span class="px-2 py-1 rounded-md border border-[var(--border)] bg-[var(--card)] text-[11px] font-mono text-[var(--foreground)]">${escapeHtml(t)}</span>`).join("")}
               </div>`}
        </div>
      </div>
    `;
  }

  // --- Tab: Ergebnisse (Formatierte Ergebnisse pro Teilaufgabe + Endprodukte direkt gerendert) ---
  function renderProjectResultsTab(body, p) {
    const subtasks = (p.subtasks || []).filter(st => (st.result || "").trim().length > 0);
    const hasPrimary = Boolean(p.primary_document);
    if (subtasks.length === 0 && !hasPrimary) {
      body.innerHTML = `
        <div class="py-12 text-center text-muted-custom">
          <i data-lucide="file-check-2" class="w-8 h-8 mx-auto mb-2 opacity-50"></i>
          <p class="text-xs font-mono">Für diese Aufgabe liegen noch keine Ergebnisse vor.</p>
        </div>`;
      return;
    }
    body.innerHTML = `
      <div class="space-y-4">
        ${hasPrimary ? `
          <div class="rounded-xl border border-emerald-500/30 bg-emerald-500/5 overflow-hidden">
            <div class="p-3.5 flex items-center justify-between gap-3 border-b border-emerald-500/20">
              <div class="min-w-0">
                <div class="text-[10px] font-mono font-bold uppercase text-emerald-600 dark:text-emerald-400">Haupt-Endprodukt (Showroom)</div>
                <div class="text-xs font-mono text-[var(--foreground)] truncate">${escapeHtml(p.primary_document)}</div>
              </div>
              <button type="button" onclick="openProjectHtmlReport('${escapeHtml(p.primary_document)}', '${escapeHtml(p.title)}')" class="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold shrink-0 cursor-pointer">
                HTML / Vollansicht öffnen
              </button>
            </div>
            <div id="pdm-primary-result-preview" class="p-4 bg-[var(--card)] max-h-[420px] overflow-y-auto custom-scrollbar">
              <div class="text-xs font-mono text-muted-custom">Lade formatiertes Ergebnis...</div>
            </div>
          </div>` : ''}
        ${subtasks.map(st => `
          <div class="p-4 rounded-xl border border-[var(--border)] bg-[var(--background)] space-y-2.5">
            <div class="flex items-center justify-between gap-2 pb-2 border-b border-[var(--border)]">
              <div class="font-bold text-xs text-[var(--foreground)] truncate">${escapeHtml(st.title || st.id)}</div>
              <span class="text-[10px] font-mono text-muted-custom shrink-0">${escapeHtml(formatOpDate(st.completed_at || st.created_at, true))}</span>
            </div>
            ${renderFormattedResult(st.result)}
          </div>
        `).join("")}
      </div>
    `;
    if (hasPrimary) {
      const prevEl = document.getElementById("pdm-primary-result-preview");
      const rawUrl = "/api/operations/raw?path=" + encodeURIComponent("/opt/data/obsidian/" + p.primary_document);
      fetch(rawUrl)
        .then(r => r.ok ? r.text() : Promise.reject(new Error("HTTP " + r.status)))
        .then(txt => {
          if (!prevEl) return;
          if (p.primary_document.toLowerCase().endsWith(".html") || p.primary_document.toLowerCase().endsWith(".htm")) {
            prevEl.innerHTML = `<iframe class="w-full h-[360px] rounded-lg border border-[var(--border)] bg-white" sandbox="allow-same-origin" srcdoc="${escapeHtml(txt)}"></iframe>`;
          } else {
            prevEl.innerHTML = renderFormattedResult(txt);
          }
        })
        .catch(() => {
          if (prevEl) prevEl.innerHTML = `<div class="text-xs font-mono text-muted-custom italic">Vorschau nicht verfügbar — bitte über den Button öffnen.</div>`;
        });
    }
  }

  // --- Tab: Dateien (leerer Zustand ohne 404-Fehler) ---
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
              <p class="text-xs font-mono">Keine Dateien für diese Aufgabe verwendet.</p>
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

  window.toggleProjectArchive = async function(projectId, archiveState) {
    try {
      const res = await fetch(`/api/operations/projects/${encodeURIComponent(projectId)}/meta`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ archived: !!archiveState })
      });
      if (!res.ok) throw new Error("HTTP " + res.status);
      await loadOperationsProjects();
    } catch (err) {
      console.error("[OperationsProjects] Archive toggle error:", err);
    }
  };

  window.openProjectObsidianFolder = function(relFolder) {
    const clean = String(relFolder || "").replace(/^\/+/, "");
    const vaultBase = localStorage.getItem("archon_obsidian_vault_path") || "";
    const uri = vaultBase
      ? `obsidian://open?path=${encodeURIComponent(vaultBase.replace(/\/+$/, "") + "/" + clean)}`
      : `obsidian://open?file=${encodeURIComponent(clean)}`;
    window.location.href = uri;
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
