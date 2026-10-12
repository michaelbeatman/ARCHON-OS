


    // =========================================================================
    // OPERATIONS CONTROL CENTER (KANBAN, ORG-CHART & INTER-AGENT COMM)
    // =========================================================================
    let currentOpsTab = 'kanban';
    let opsOrgViewMode = 'flow'; // 'flow' (Ablaufdiagramm) oder 'grid' (Kompakte Karten)
    let opsKanbanData = null;
    let opsOrgData = null;
    let opsCommData = null;
    let currentOpsDetailTaskId = null;
    let activeCommFilter = null;

    // Interaktive Ablaufdiagramm / Organigramm Zustandsverwaltung
    let currentHierarchyData = { nodes: [], links: [], canvas_width: 2200, canvas_height: 1400 };
    let flowDraggingNode = null;
    let flowDragOffset = { x: 0, y: 0 };
    let flowConnectingSource = null;

    function opsEscapeHtml(str) {
      if (!str) return '';
      return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
    }

    function setOperationsTab(subtab) {
      currentOpsTab = subtab;
      const tabs = ['kanban', 'org', 'comm'];
      tabs.forEach(t => {
        const btn = document.getElementById(`ops-subtab-${t}`);
        const view = document.getElementById(`ops-view-${t}`);
        const label = btn ? btn.querySelector(".ops-tab-label") : null;
        if (t === subtab) {
          if (btn) {
            btn.className = "ops-header-tile flex flex-col items-center justify-center min-w-[56px] sm:min-w-[62px] py-0.5 px-0.5 bg-transparent border-0 shadow-none opacity-100 cursor-pointer select-none transition-transform hover:scale-105 duration-150";
          }
          if (label) {
            label.className = "ops-tab-label text-[10px] font-mono tracking-tight text-center whitespace-nowrap text-red-600 font-bold";
          }
          if (view) view.classList.remove('hidden');
        } else {
          if (btn) {
            btn.className = "ops-header-tile flex flex-col items-center justify-center min-w-[56px] sm:min-w-[62px] py-0.5 px-0.5 bg-transparent border-0 shadow-none opacity-75 hover:opacity-100 cursor-pointer select-none transition-transform hover:scale-105 duration-150";
          }
          if (label) {
            label.className = "ops-tab-label text-[10px] font-mono tracking-tight text-center whitespace-nowrap text-black dark:text-zinc-100 font-medium";
          }
          if (view) view.classList.add('hidden');
        }
      });
      if (subtab === 'org') {
        if (opsOrgViewMode === 'flow') {
          if (!currentHierarchyData || !currentHierarchyData.nodes || currentHierarchyData.nodes.length === 0) {
            loadOrgHierarchyData();
          } else {
            renderOpsOrgFlowchart();
          }
        } else if (opsOrgData) {
          renderOperationsOrgChart(opsOrgData);
        }
      }
      if (window.lucide) lucide.createIcons();
    }

    async function loadOperationsData(showOverlay = true) {
      if (showOverlay) {
        showLoadingOverlay("Operations Center wird geladen...", "Kanban-Board, Organigramm & Kommunikationskanäle werden synchronisiert");
      }
      try {
        const [tasksRes, orgRes, commRes, hierRes] = await Promise.all([
          fetch('/api/operations/kanban/tasks'),
          fetch('/api/operations/org-chart'),
          fetch('/api/operations/comm-feed'),
          fetch('/api/operations/org-hierarchy')
        ]);
        if (tasksRes.ok) {
          opsKanbanData = await tasksRes.json();
          renderOperationsKanban(opsKanbanData);
          loadOpsKanbanStats();
        }
        if (orgRes.ok) {
          opsOrgData = await orgRes.json();
          renderOperationsOrgChart(opsOrgData);
          populateAssigneeDropdowns(opsOrgData);
        }
        if (commRes.ok) {
          opsCommData = await commRes.json();
          renderOperationsCommFeed(opsCommData, activeCommFilter);
        }
        if (hierRes.ok) {
          const resp = await hierRes.json();
          currentHierarchyData = resp.data || { nodes: [], links: [] };
          if (opsOrgViewMode === 'flow') {
            renderOpsOrgFlowchart();
          }
        }
      } catch (err) {
        console.error("Fehler beim Laden der Operations-Daten:", err);
      } finally {
        if (showOverlay) {
          hideLoadingOverlay();
        }
      }
    }

    // =========================================================================
    // BOARD-TOOLBAR: Suche, Filter, Sortierung, WIP, Stats, Archiv (10.10.2026)
    // =========================================================================
    const opsKanbanFilters = { q: '', assignee: '', prio: '', sort: 'default' };
    let opsKanbanWip = {};

    function onOpsKanbanFilterChange() {
      const q = document.getElementById('ops-kanban-search');
      const fa = document.getElementById('ops-kanban-filter-assignee');
      const fp = document.getElementById('ops-kanban-filter-prio');
      const so = document.getElementById('ops-kanban-sort');
      if (q) opsKanbanFilters.q = q.value.trim();
      if (fa) opsKanbanFilters.assignee = fa.value;
      if (fp) opsKanbanFilters.prio = fp.value;
      if (so) opsKanbanFilters.sort = so.value;
      if (typeof opsKanbanData !== 'undefined' && opsKanbanData) renderOperationsKanban(opsKanbanData);
    }

    function opsKanbanMatches(t) {
      const f = opsKanbanFilters;
      if (f.assignee && (t.assignee || '') !== f.assignee) return false;
      if (f.prio !== '' && String(t.priority || 0) !== f.prio) return false;
      if (f.q) {
        const hay = ((t.title || '') + ' ' + (t.body || '') + ' ' + t.id).toLowerCase();
        if (hay.indexOf(f.q.toLowerCase()) === -1) return false;
      }
      return true;
    }

    function populateOpsKanbanAssigneeFilter(data) {
      const sel = document.getElementById('ops-kanban-filter-assignee');
      if (!sel) return;
      const current = sel.value;
      const names = new Set();
      Object.values(data.columns || {}).forEach(arr => arr.forEach(t => { if (t.assignee) names.add(t.assignee); }));
      sel.innerHTML = ['<option value="">Alle Agenten</option>']
        .concat([...names].sort().map(n => `<option value="${n}">${n}</option>`)).join('');
      sel.value = (current && names.has(current)) ? current : '';
      opsKanbanFilters.assignee = sel.value;
    }

    function saveOpsKanbanWip() {
      const colEl = document.getElementById('ops-kanban-wip-col');
      const nEl = document.getElementById('ops-kanban-wip-n');
      if (!colEl || !nEl) return;
      const limits = Object.assign({}, opsKanbanWip);
      const n = parseInt(nEl.value, 10);
      const col = colEl.value;
      if (!n || n <= 0) delete limits[col]; else limits[col] = n;
      fetch('/api/operations/kanban/meta', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ kind: 'wip', limits })
      }).then(r => r.json()).then(() => {
        nEl.value = '';
        loadOperationsData(false);
      }).catch(e => console.error('[Kanban] WIP speichern fehlgeschlagen:', e));
    }

    async function loadOpsKanbanStats() {
      try {
        const res = await fetch('/api/operations/kanban/stats');
        if (!res.ok) return;
        const s = await res.json();
        const el = document.getElementById('ops-kanban-stats');
        if (el) {
          const cyc = (s.avg_cycle_hours == null) ? '–'
            : (s.avg_cycle_hours < 1 ? Math.round(s.avg_cycle_hours * 60) + 'm' : s.avg_cycle_hours + 'h');
          el.innerHTML = `<span title="Ø Durchlaufzeit (Start → Ende)">⏱ ${cyc}</span>`
            + `<span title="Erledigt in den letzten 7 Tagen">✓ 7T: ${s.done_7d}</span>`
            + `<span title="Aktuell blockiert">⛔ ${s.blocked}</span>`;
        }
        const btnSpan = document.querySelector('#ops-kanban-archive-btn span');
        if (btnSpan) btnSpan.textContent = `Archiv (${s.archived_total})`;
      } catch (e) {
        console.warn('[Kanban] Stats nicht ladbar:', e);
      }
    }

    async function toggleOpsKanbanArchive(force) {
      const panel = document.getElementById('ops-kanban-archive');
      const cont = document.getElementById('ops-kanban-columns-container');
      if (!panel || !cont) return;
      const open = (typeof force === 'boolean') ? force : panel.classList.contains('hidden');
      if (open) {
        panel.classList.remove('hidden');
        cont.classList.add('hidden');
        const list = document.getElementById('ops-kanban-archive-list');
        if (list) list.innerHTML = '<div class="text-xs text-muted-custom font-mono">Lade Archiv…</div>';
        try {
          const res = await fetch('/api/operations/kanban/tasks?archived=true');
          const data = await res.json();
          const tasks = data.tasks || [];
          if (list) {
            list.innerHTML = tasks.length ? tasks.map(t => {
              const done = (typeof t.completed_at === 'number') ? new Date(t.completed_at * 1000)
                : (t.completed_at ? new Date(String(t.completed_at).replace(' ', 'T')) : null);
              return `
              <div class="p-2.5 rounded-lg border border-[var(--border)] bg-[var(--background)] flex items-center justify-between gap-2 text-xs">
                <div class="min-w-0">
                  <span class="font-mono font-bold text-muted-custom">${t.id}</span>
                  <span class="font-semibold text-primary-custom ml-2">${opsEscapeHtml((t.title || '').slice(0, 90))}</span>
                </div>
                <div class="flex items-center gap-2.5 shrink-0 text-[10px] font-mono text-muted-custom">
                  ${t.due_date ? `<span title="Fällig">📅 ${t.due_date}</span>` : ''}
                  ${(t.tags || []).slice(0, 2).map(tg => `<span>#${opsEscapeHtml(tg)}</span>`).join('')}
                  <span>${done && !isNaN(done) ? done.toLocaleDateString('de-DE') : ''}</span>
                  <span title="Zugewiesen an">👤 ${opsEscapeHtml(t.assignee_name || '-')}</span>
                </div>
              </div>`;
            }).join('') : '<div class="text-xs text-muted-custom font-mono">Archiv leer</div>';
          }
        } catch (e) {
          if (list) list.innerHTML = '<div class="text-xs text-red-500 font-mono">Archiv nicht ladbar</div>';
        }
        if (window.lucide) lucide.createIcons();
      } else {
        panel.classList.add('hidden');
        cont.classList.remove('hidden');
      }
    }

    function populateOpsDetailMeta(taskId) {
      const dueEl = document.getElementById('ops-detail-due');
      const tagsEl = document.getElementById('ops-detail-tags');
      if (!dueEl || !tagsEl) return;
      let found = null;
      if (typeof opsKanbanData !== 'undefined' && opsKanbanData && opsKanbanData.columns) {
        for (const arr of Object.values(opsKanbanData.columns)) {
          found = arr.find(t => t.id === taskId);
          if (found) break;
        }
      }
      dueEl.value = (found && found.due_date) ? found.due_date : '';
      tagsEl.value = (found && found.tags && found.tags.length) ? found.tags.join(', ') : '';
    }

    function saveOpsDetailMeta() {
      const dueEl = document.getElementById('ops-detail-due');
      const tagsEl = document.getElementById('ops-detail-tags');
      if (typeof currentOpsDetailTaskId === 'undefined' || !currentOpsDetailTaskId) return;
      const tagList = ((tagsEl && tagsEl.value) || '').split(',').map(s => s.trim()).filter(Boolean);
      const hasDue = !!(dueEl && dueEl.value);
      fetch('/api/operations/kanban/meta', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          kind: 'task',
          task_id: currentOpsDetailTaskId,
          due: hasDue ? dueEl.value : null,
          clear_due: !hasDue,
          tags: tagList
        })
      }).then(r => r.json()).then(() => {
        loadOperationsData(false);
      }).catch(e => console.error('[Kanban] Fälligkeit/Tags speichern fehlgeschlagen:', e));
    }

    // =========================================================================
    // ORGANIGRAMM & ABLAUFDIAGRAMM (FLOWCHART BUILDER)
    // =========================================================================

    function setOpsOrgViewMode(mode) {
      opsOrgViewMode = mode;
      const btnFlow = document.getElementById('ops-org-mode-flow');
      const btnGrid = document.getElementById('ops-org-mode-grid');
      const containerFlow = document.getElementById('ops-org-flow-container');
      const containerGrid = document.getElementById('ops-org-grid-container');
      
      if (mode === 'flow') {
        if (btnFlow) btnFlow.className = "px-3 py-1 rounded-lg font-bold transition flex items-center gap-1.5 cursor-pointer bg-[var(--card)] text-primary-custom shadow-xs border border-[var(--border)]";
        if (btnGrid) btnGrid.className = "px-3 py-1 rounded-lg font-medium transition flex items-center gap-1.5 cursor-pointer text-muted-custom hover:text-primary-custom";
        if (containerFlow) containerFlow.classList.remove('hidden');
        if (containerGrid) containerGrid.classList.add('hidden');
        renderOpsOrgFlowchart();
      } else {
        if (btnGrid) btnGrid.className = "px-3 py-1 rounded-lg font-bold transition flex items-center gap-1.5 cursor-pointer bg-[var(--card)] text-primary-custom shadow-xs border border-[var(--border)]";
        if (btnFlow) btnFlow.className = "px-3 py-1 rounded-lg font-medium transition flex items-center gap-1.5 cursor-pointer text-muted-custom hover:text-primary-custom";
        if (containerFlow) containerFlow.classList.add('hidden');
        if (containerGrid) containerGrid.classList.remove('hidden');
        if (opsOrgData) renderOperationsOrgChart(opsOrgData);
      }
      if (window.lucide) lucide.createIcons();
    }

    async function loadOrgHierarchyData() {
      try {
        const res = await fetch('/api/operations/org-hierarchy');
        if (res.ok) {
          const resp = await res.json();
          currentHierarchyData = resp.data || { nodes: [], links: [] };
          if (opsOrgViewMode === 'flow') {
            renderOpsOrgFlowchart();
          }
        }
      } catch (err) {
        console.error("Fehler beim Laden der Organigramm-Hierarchie:", err);
      }
    }

    async function saveCurrentOrgHierarchy() {
      try {
        const res = await fetch('/api/operations/org-hierarchy', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(currentHierarchyData)
        });
        if (res.ok) {
          if (typeof showArchonToast === 'function') {
            showArchonToast('Organigramm & Hierarchie erfolgreich gespeichert.', 'success');
          }
        } else {
          alert('Fehler beim Speichern der Hierarchie.');
        }
      } catch (err) {
        console.error("Save error:", err);
      }
    }

    async function resetOrgHierarchyToDefault() {
      const confirmed = confirm("Möchtest du das Organigramm wirklich auf die 6 Standard-Teams zurücksetzen?");
      if (!confirmed) return;
      try {
        const res = await fetch('/api/operations/org-hierarchy', { method: 'DELETE' });
        if (res.ok) {
          const resp = await res.json();
          currentHierarchyData = resp.data || { nodes: [], links: [] };
          renderOpsOrgFlowchart();
          if (typeof showArchonToast === 'function') {
            showArchonToast('Organigramm auf 6 Standard-Teams zurückgesetzt.', 'info');
          }
        }
      } catch (err) {
        console.error("Reset error:", err);
      }
    }

    function autoAlignOrgHierarchy() {
      const nodes = currentHierarchyData.nodes || [];
      const links = currentHierarchyData.links || [];
      if (nodes.length === 0) return;

      const teamConfigs = [
        { id: 'team_strategy', leadId: 'executive_decision_architect', colX: 60 },
        { id: 'team_tech', leadId: 'system_architect_orchestrator', colX: 520 },
        { id: 'team_legal', leadId: 'commercial_jurist_contracts', colX: 980 },
        { id: 'team_realestate', leadId: 'construction_project_manager', colX: 1440 },
        { id: 'team_growth', leadId: 'gtm_launch_strategist', colX: 1900 },
        { id: 'team_operations', leadId: 'logistics_supply_chain_manager', colX: 2360 }
      ];

      const nodesMap = {};
      nodes.forEach(n => nodesMap[n.id] = n);

      // Apex placement (Top Center)
      const apex1 = nodesMap['executive_decision_architect'];
      if (apex1) {
        apex1.x = 1320;
        apex1.y = 40;
        apex1.tier = 1;
      }
      const apex2 = nodesMap['system_architect_orchestrator'];
      if (apex2) {
        apex2.x = 1320;
        apex2.y = 200;
        apex2.tier = 1;
      }

      // Teams placement
      teamConfigs.forEach(tcfg => {
        const teamNodes = nodes.filter(n => n.team_id === tcfg.id && n.id !== 'executive_decision_architect' && n.id !== 'system_architect_orchestrator');
        
        // Lead
        const lead = nodesMap[tcfg.leadId];
        if (lead && lead.id !== 'executive_decision_architect' && lead.id !== 'system_architect_orchestrator') {
          lead.x = tcfg.colX + 100;
          lead.y = 380;
          lead.tier = 2;
        }

        // Specialists in 2 clean columns without any overlap
        const specialists = teamNodes.filter(n => n.id !== tcfg.leadId);
        specialists.forEach((sp, idx) => {
          const col = idx % 2;
          const row = Math.floor(idx / 2);
          sp.x = tcfg.colX + (col * 200); // 176px width + 24px gap = 200px step
          sp.y = 560 + (row * 180);       // 145px height + 35px gap = 180px step
          sp.tier = 3;
        });
      });

      // Any remaining nodes
      const processed = new Set([
        'executive_decision_architect', 'system_architect_orchestrator',
        ...nodes.filter(n => teamConfigs.some(tc => tc.id === n.team_id)).map(n => n.id)
      ]);
      const otherNodes = nodes.filter(n => !processed.has(n.id));
      otherNodes.forEach((node, idx) => {
        const col = idx % 2;
        const row = Math.floor(idx / 2);
        node.x = 2820 + (col * 200);
        node.y = 560 + (row * 180);
      });

      renderOpsOrgFlowchart();
      saveCurrentOrgHierarchy();
      if (typeof showArchonToast === 'function') {
        showArchonToast('Kacheln sauber am 20px-Raster ausgerichtet (überlappungsfrei).', 'success');
      }
    }

    function renderOpsOrgFlowchart() {
      const nodesContainer = document.getElementById('ops-org-flow-nodes');
      const linksGroup = document.getElementById('ops-flow-links-group');
      if (!nodesContainer || !linksGroup) return;

      const nodes = currentHierarchyData.nodes || [];

      // Dynamische Canvas-Größe basierend auf Knoten-Positionen (mindestens 3200x4000)
      let maxNodeX = 2800;
      let maxNodeY = 3600;
      nodes.forEach(n => {
        if (n.x && n.x > maxNodeX - 400) maxNodeX = n.x + 400;
        if (n.y && n.y > maxNodeY - 400) maxNodeY = n.y + 400;
      });
      const reqWidth = Math.max(3200, currentHierarchyData.canvas_width || 3200, maxNodeX);
      const reqHeight = Math.max(4000, currentHierarchyData.canvas_height || 4000, maxNodeY);

      const flowSvg = document.getElementById('ops-org-flow-svg');
      if (flowSvg) {
        flowSvg.style.minWidth = reqWidth + 'px';
        flowSvg.style.width = reqWidth + 'px';
        flowSvg.style.minHeight = reqHeight + 'px';
        flowSvg.style.height = reqHeight + 'px';
      }
      nodesContainer.style.minWidth = reqWidth + 'px';
      nodesContainer.style.width = reqWidth + 'px';
      nodesContainer.style.minHeight = reqHeight + 'px';
      nodesContainer.style.height = reqHeight + 'px';

      nodesContainer.innerHTML = nodes.map(n => {
        const teamColors = {
          team_strategy: 'border-red-500/30 text-red-600 dark:text-red-400 bg-red-500/10',
          team_tech: 'border-sky-500/30 text-sky-600 dark:text-sky-400 bg-sky-500/10',
          team_legal: 'border-amber-500/30 text-amber-600 dark:text-amber-400 bg-amber-500/10',
          team_realestate: 'border-emerald-500/30 text-emerald-600 dark:text-emerald-400 bg-emerald-500/10',
          team_growth: 'border-orange-500/30 text-orange-600 dark:text-orange-400 bg-orange-500/10',
          team_operations: 'border-zinc-500/30 text-zinc-700 dark:text-zinc-300 bg-zinc-500/10'
        }[n.team_id || 'team_strategy'] || 'border-red-500/30 text-red-600 dark:text-red-400 bg-red-500/10';

        const tierBadge = n.tier === 1 ? '👑 Apex' : (n.tier === 2 ? '★ Lead' : 'Specialist');

        return `
          <div id="flow-node-${n.id}"
               data-node-id="${n.id}"
               class="ops-flow-node absolute w-44 rounded-2xl border-2 border-[var(--border)] bg-[var(--card)] shadow-md hover:shadow-xl hover:border-[#d42a2b] transition-all select-none group cursor-pointer"
               style="left: ${n.x}px; top: ${n.y}px;"
               onmousedown="startDragFlowNode(event, '${n.id}')"
               onclick="handleFlowNodeCardClick(event, '${n.id}')">
            
            <!-- TOP CONNECTION PORT (Vorgesetzter / Reporting To) -->
            <div class="ops-flow-port ops-flow-port-top absolute -top-3.5 left-1/2 -translate-x-1/2 w-6 h-6 rounded-full bg-[var(--card)] border-2 border-slate-400 dark:border-slate-500 hover:scale-125 hover:border-[#d42a2b] hover:bg-[#d42a2b] transition-all flex items-center justify-center cursor-pointer shadow-sm z-30"
                 data-node-id="${n.id}"
                 data-port="top"
                 title="▲ Vorgesetzter (Hierarchie-Eingang von oben)"
                 onmouseup="onEndConnectPort(event, '${n.id}', 'top')">
              <span class="w-2 h-2 rounded-full bg-slate-500 dark:bg-slate-400 pointer-events-none group-hover:bg-[#d42a2b]"></span>
            </div>

            <!-- Card Header -->
            <div class="px-2.5 py-1.5 border-b border-[var(--border)] flex items-center justify-between text-[9px] font-mono">
              <span class="px-1.5 py-0.2 rounded font-bold ${teamColors}">${tierBadge}</span>
              <span class="text-muted-custom font-semibold">${n.active_tasks || 0} Tasks</span>
            </div>

            <!-- Card Content -->
            <div class="p-2.5 flex flex-col items-center text-center space-y-1.5">
              <div class="relative cursor-pointer" onclick="event.stopPropagation(); openOrgNodeDetailModal('${n.id}')" title="Klicke für Eigenschaften &amp; Ergebnisse">
                <img src="${n.avatar || '/static/avatars/avatar_001.jpg'}" class="w-11 h-11 rounded-full object-cover border-2 border-[var(--border)] group-hover:border-[#d42a2b] transition-colors shadow-xs pointer-events-none" />
                <span class="absolute bottom-0 right-0 w-3 h-3 rounded-full bg-emerald-500 border-2 border-[var(--card)] pointer-events-none"></span>
              </div>
              <div class="w-full leading-tight px-1">
                <div class="text-[11px] font-bold text-primary-custom truncate hover:text-[#d42a2b] transition-colors cursor-pointer" onclick="event.stopPropagation(); openOrgNodeDetailModal('${n.id}')" title="${opsEscapeHtml(n.person_name || n.name || n.id)}">${opsEscapeHtml(n.person_name || n.name || n.id)}</div>
                <div class="text-[9px] text-muted-custom truncate font-mono mt-0.5" title="${opsEscapeHtml((n.person_name && n.name && n.person_name !== n.name) ? n.name : (n.role || 'Spezialist'))}">${opsEscapeHtml((n.person_name && n.name && n.person_name !== n.name) ? n.name : (n.role || 'Spezialist'))}</div>
              </div>
              <div class="w-full pt-1 flex items-center justify-center gap-1.5">
                <button type="button" onclick="event.stopPropagation(); openOrgNodeDetailModal('${n.id}')" class="px-2 py-0.8 rounded text-[9.5px] bg-[var(--secondary)] hover:bg-[var(--card)] border border-[var(--border)] text-[var(--foreground)] font-medium transition cursor-pointer shadow-2xs flex items-center gap-1" title="Eigenschaften, Profil &amp; Ergebnisse ansehen">
                  <i data-lucide="eye" class="w-3 h-3 text-[#d42a2b]"></i>
                  <span>Öffnen</span>
                </button>
                <button type="button" onclick="event.stopPropagation(); openNewTaskModal('todo', '${n.id}', '${n.team_id || ''}')" class="px-2 py-0.8 rounded text-[9.5px] bg-[#d42a2b] hover:bg-[#b82223] text-white font-medium transition cursor-pointer shadow-2xs flex items-center gap-1" title="Neue Aufgabe zuweisen">
                  <i data-lucide="plus" class="w-3 h-3"></i>
                  <span>Aufgabe</span>
                </button>
              </div>
            </div>

            <!-- BOTTOM CONNECTION PORT (Zuständigkeit nach unten / Subordinates) -->
            <div class="ops-flow-port ops-flow-port-bottom absolute -bottom-3.5 left-1/2 -translate-x-1/2 w-6 h-6 rounded-full bg-[var(--card)] border-2 border-slate-400 dark:border-slate-500 hover:scale-125 hover:border-[#d42a2b] hover:bg-[#d42a2b] transition-all flex items-center justify-center cursor-pointer shadow-sm z-30"
                 data-node-id="${n.id}"
                 data-port="bottom"
                 title="▼ Zuständigkeit nach unten (Hier klicken oder Linie ziehen)"
                 onmousedown="event.stopPropagation(); onStartConnectPort(event, '${n.id}', 'bottom')">
              <span class="w-2 h-2 rounded-full bg-slate-500 dark:bg-slate-400 pointer-events-none group-hover:bg-[#d42a2b]"></span>
            </div>
          </div>
        `;
      }).join('');

      renderOpsFlowLinks();
      if (window.lucide) lucide.createIcons();
    }

    function renderOpsFlowLinks() {
      const linksGroup = document.getElementById('ops-flow-links-group');
      if (!linksGroup) return;

      const nodesMap = {};
      (currentHierarchyData.nodes || []).forEach(n => nodesMap[n.id] = n);

      const links = currentHierarchyData.links || [];
      linksGroup.innerHTML = links.map((link, idx) => {
        const fromNode = nodesMap[link.from];
        const toNode = nodesMap[link.to];
        if (!fromNode || !toNode) return '';

        const x1 = fromNode.x + 88;
        const y1 = fromNode.y + 130;
        const x2 = toNode.x + 88;
        const y2 = toNode.y - 2;

        const dy = Math.max(30, Math.abs(y2 - y1) * 0.5);
        const pathData = `M ${x1} ${y1} C ${x1} ${y1 + dy}, ${x2} ${y2 - dy}, ${x2} ${y2}`;

        return `
          <g class="flow-link-group cursor-pointer group" onclick="deleteOrgLink(${idx})">
            <path d="${pathData}" fill="none" stroke="transparent" stroke-width="16" />
            <path d="${pathData}" fill="none" stroke="#71717a" stroke-width="2" marker-end="url(#flow-arrow-down)" class="group-hover:stroke-[#d42a2b] transition-colors" />
          </g>
        `;
      }).join('');
    }

    function deleteOrgLink(linkIndex) {
      const links = currentHierarchyData.links || [];
      if (linkIndex >= 0 && linkIndex < links.length) {
        const link = links[linkIndex];
        const confirmed = confirm(`Hierarchie-Verbindung von '${link.from}' zu '${link.to}' wirklich trennen?`);
        if (confirmed) {
          links.splice(linkIndex, 1);
          renderOpsFlowLinks();
          saveCurrentOrgHierarchy();
          if (typeof showArchonToast === 'function') {
            showArchonToast('Verbindung getrennt.', 'info');
          }
        }
      }
    }

    // Node Dragging mit 20px-Raster (Snap to Grid) & Click Detection
    let hasDraggedFlowNode = false;
    let dragStartPos = { x: 0, y: 0 };

    function startDragFlowNode(e, nodeId) {
      if (e.target.closest('.ops-flow-port') || e.target.closest('button')) return;
      const node = (currentHierarchyData.nodes || []).find(n => n.id === nodeId);
      if (!node) return;

      hasDraggedFlowNode = false;
      dragStartPos = { x: e.clientX, y: e.clientY };
      flowDraggingNode = node;
      flowDragOffset.x = e.clientX - node.x;
      flowDragOffset.y = e.clientY - node.y;

      window.addEventListener('mousemove', onMoveDragFlowNode);
      window.addEventListener('mouseup', onEndDragFlowNode);
    }

    function onMoveDragFlowNode(e) {
      if (!flowDraggingNode) return;
      const dx = Math.abs(e.clientX - dragStartPos.x);
      const dy = Math.abs(e.clientY - dragStartPos.y);
      if (dx > 4 || dy > 4) {
        hasDraggedFlowNode = true;
      }

      // Rastern: Snap auf 20px-Raster
      const GRID_SNAP = 20;
      const rawX = e.clientX - flowDragOffset.x;
      const rawY = e.clientY - flowDragOffset.y;
      flowDraggingNode.x = Math.max(20, Math.min(3100, Math.round(rawX / GRID_SNAP) * GRID_SNAP));
      flowDraggingNode.y = Math.max(20, Math.min(3900, Math.round(rawY / GRID_SNAP) * GRID_SNAP));

      const el = document.getElementById(`flow-node-${flowDraggingNode.id}`);
      if (el) {
        el.style.left = `${flowDraggingNode.x}px`;
        el.style.top = `${flowDraggingNode.y}px`;
      }
      renderOpsFlowLinks();
    }

    function onEndDragFlowNode() {
      if (flowDraggingNode && hasDraggedFlowNode) {
        saveCurrentOrgHierarchy();
      }
      flowDraggingNode = null;
      window.removeEventListener('mousemove', onMoveDragFlowNode);
      window.removeEventListener('mouseup', onEndDragFlowNode);
    }

    function handleFlowNodeCardClick(e, nodeId) {
      if (hasDraggedFlowNode) return;
      if (e.target.closest('.ops-flow-port') || e.target.closest('button')) return;
      openOrgNodeDetailModal(nodeId);
    }

    // Port Connection Dragging
    function onStartConnectPort(e, nodeId, portType) {
      e.preventDefault();
      e.stopPropagation();
      flowConnectingSource = nodeId;

      const tempLine = document.getElementById('ops-flow-temp-line');
      const container = document.getElementById('ops-org-flow-container');
      const node = (currentHierarchyData.nodes || []).find(n => n.id === nodeId);
      if (!node || !tempLine || !container) return;

      const startX = node.x + 88;
      const startY = node.y + 130;

      tempLine.classList.remove('hidden');

      function onMoveConnectLine(moveEvent) {
        const rect = container.getBoundingClientRect();
        const scrollLeft = container.scrollLeft;
        const scrollTop = container.scrollTop;
        const mouseX = moveEvent.clientX - rect.left + scrollLeft;
        const mouseY = moveEvent.clientY - rect.top + scrollTop;

        const dy = Math.max(30, Math.abs(mouseY - startY) * 0.5);
        tempLine.setAttribute('d', `M ${startX} ${startY} C ${startX} ${startY + dy}, ${mouseX} ${mouseY - dy}, ${mouseX} ${mouseY}`);
      }

      function onUpConnectLine(upEvent) {
        tempLine.classList.add('hidden');
        window.removeEventListener('mousemove', onMoveConnectLine);
        window.removeEventListener('mouseup', onUpConnectLine);

        const targetPort = upEvent.target.closest('.ops-flow-port-top') || upEvent.target.closest('.ops-flow-node');
        if (targetPort) {
          const targetNodeId = targetPort.getAttribute('data-node-id');
          if (targetNodeId && targetNodeId !== flowConnectingSource) {
            createHierarchyLink(flowConnectingSource, targetNodeId);
          }
        }
        flowConnectingSource = null;
      }

      window.addEventListener('mousemove', onMoveConnectLine);
      window.addEventListener('mouseup', onUpConnectLine);
    }

    function onEndConnectPort(e, targetNodeId, portType) {
      if (flowConnectingSource && flowConnectingSource !== targetNodeId) {
        createHierarchyLink(flowConnectingSource, targetNodeId);
        flowConnectingSource = null;
      }
    }

    function createHierarchyLink(fromId, toId) {
      if (!fromId || !toId) return;
      if (fromId === toId) {
        if (typeof showArchonToast === 'function') {
          showArchonToast('Ein Agent kann nicht sein eigener Vorgesetzter sein.', 'warning');
        }
        return;
      }
      currentHierarchyData.links = currentHierarchyData.links || [];
      // Vorherigen Vorgesetzten und eventuelle Schleifen entfernen
      currentHierarchyData.links = currentHierarchyData.links.filter(l => l.to !== toId && l.from !== l.to);
      currentHierarchyData.links.push({ from: fromId, to: toId });
      renderOpsFlowLinks();
      saveCurrentOrgHierarchy();
      if (typeof showArchonToast === 'function') {
        const fromNode = (currentHierarchyData.nodes || []).find(n => n.id === fromId);
        const toNode = (currentHierarchyData.nodes || []).find(n => n.id === toId);
        const fromName = fromNode ? (fromNode.person_name || fromNode.name) : fromId;
        const toName = toNode ? (toNode.person_name || toNode.name) : toId;
        showArchonToast(`Hierarchie aktualisiert: ${toName} berichtet an ${fromName}`, 'success');
      }
    }

    let currentOrgDetailNodeId = null;

    function openOrgNodeDetailModal(nodeId) {
      currentOrgDetailNodeId = nodeId;
      const node = (currentHierarchyData.nodes || []).find(n => n.id === nodeId);
      if (!node) return;

      const modal = document.getElementById('ops-node-detail-modal');
      if (!modal) return;

      const profile = (hermesProfilesData || []).find(p => p.id === nodeId) || {};

      const teamNames = {
        team_strategy: '1. Geschäftsführung, Strategie & M&A',
        team_tech: '2. Software, Cloud & System-Architektur',
        team_legal: '3. Recht, Verträge & Governance',
        team_realestate: '4. Immobilien, Finanzierung & Projektentwicklung',
        team_growth: '5. Sales, Marketing & Growth',
        team_operations: '6. Operations, Personal & Backoffice'
      };
      const teamName = teamNames[node.team_id] || profile.category || 'Fachbereich';

      const personName = (node.person_name || profile.person_name || '').trim();
      const roleName = (node.name || profile.name || node.role || nodeId).trim();
      const currentProvider = profile.provider || node.provider || 'omniroute';
      const currentModel = profile.model || node.model || 'auto/best-free';

      // Header Elements
      const avatarEl = document.getElementById('ond-avatar');
      if (avatarEl) avatarEl.src = node.avatar || profile.avatar || '/static/avatars/avatar_001.jpg';
      
      const nameEl = document.getElementById('ond-name');
      if (nameEl) nameEl.innerText = personName || roleName;

      const roleEl = document.getElementById('ond-role');
      if (roleEl) roleEl.innerText = (personName && personName !== roleName) ? roleName : (node.role || profile.name || 'Spezialist');

      const teamBadgeEl = document.getElementById('ond-team-badge');
      if (teamBadgeEl) teamBadgeEl.innerText = teamName;
      
      const tierBadgeEl = document.getElementById('ond-tier-badge');
      if (tierBadgeEl) {
        tierBadgeEl.innerText = node.tier === 1 ? '👑 Tier 1 - Apex' : (node.tier === 2 ? '★ Tier 2 - Team Lead' : 'Tier 3 - Specialist');
      }

      // Formular-Felder mit aktuellen Werten befüllen
      const editPersonNameEl = document.getElementById('ond-edit-person-name');
      if (editPersonNameEl) editPersonNameEl.value = personName;

      const editNameEl = document.getElementById('ond-edit-name');
      if (editNameEl) editNameEl.value = roleName;

      const editProviderEl = document.getElementById('ond-edit-provider');
      if (editProviderEl) editProviderEl.value = currentProvider;

      const editModelEl = document.getElementById('ond-edit-model');
      if (editModelEl) editModelEl.value = currentModel;

      const editTeamEl = document.getElementById('ond-edit-team');
      if (editTeamEl) editTeamEl.value = node.team_id || 'team_strategy';

      const editTierEl = document.getElementById('ond-edit-tier');
      if (editTierEl) editTierEl.value = String(node.tier || 3);

      // Vorgesetzten-Dropdown befüllen (Selbstreferenzen strikt ausgeschlossen)
      const links = currentHierarchyData.links || [];
      const parentLink = links.find(l => l.to === nodeId && l.from !== nodeId);
      const currentParentId = parentLink ? parentLink.from : '';

      const editParentEl = document.getElementById('ond-edit-parent');
      if (editParentEl) {
        let parentOpts = `<option value="">-- Kein Vorgesetzter (Apex / Oberste Führungsebene) --</option>`;
        const sortedNodes = [...(currentHierarchyData.nodes || [])].sort((a, b) => {
          const nameA = (a.person_name || a.name || a.id).toLowerCase();
          const nameB = (b.person_name || b.name || b.id).toLowerCase();
          return nameA.localeCompare(nameB);
        });

        sortedNodes.forEach(other => {
          if (other.id === nodeId) return; // Keine Selbstreferenz zulassen!
          const otherProf = (hermesProfilesData || []).find(p => p.id === other.id);
          const pName = other.person_name || otherProf?.person_name || '';
          const rName = other.name || otherProf?.name || other.id;
          const label = pName ? `${pName} (${rName})` : rName;
          const isSelected = other.id === currentParentId ? 'selected' : '';
          parentOpts += `<option value="${other.id}" ${isSelected}>${opsEscapeHtml(label)}</option>`;
        });
        editParentEl.innerHTML = parentOpts;
      }

      // Quick Stats
      const modelEl = document.getElementById('ond-model');
      if (modelEl) modelEl.innerText = currentModel;

      const providerEl = document.getElementById('ond-provider');
      if (providerEl) providerEl.innerText = currentProvider;

      const tasksCountEl = document.getElementById('ond-tasks-count');
      if (tasksCountEl) tasksCountEl.innerText = `${node.active_tasks || 0} aktiv`;

      // System Prompt & Kompetenzen
      const descEl = document.getElementById('ond-description');
      if (descEl) {
        descEl.innerText = profile.description || profile.system_prompt || 'Kein detailliertes System-Profil hinterlegt.';
      }

      // Hierarchy: Vorgesetzter & Unterstellte Displays (ohne Selbstreferenzen)
      const parentLinks = links.filter(l => l.to === nodeId && l.from !== nodeId);
      const childLinks = links.filter(l => l.from === nodeId && l.to !== nodeId);

      const parentListEl = document.getElementById('ond-parent-list');
      if (parentListEl) {
        if (parentLinks.length === 0) {
          parentListEl.innerHTML = `<span class="text-xs text-muted-custom italic">Oberste Führungsebene (Kein Vorgesetzter)</span>`;
        } else {
          parentListEl.innerHTML = parentLinks.map(l => {
            const pNode = (currentHierarchyData.nodes || []).find(n => n.id === l.from);
            const pProf = (hermesProfilesData || []).find(p => p.id === l.from);
            const pHuman = pNode?.person_name || pProf?.person_name || '';
            const pTitle = pHuman ? `${pHuman} (${pNode?.name || l.from})` : (pNode?.name || l.from);
            const pAvatar = pNode?.avatar || pProf?.avatar || '/static/avatars/avatar_001.jpg';
            return `
              <div class="inline-flex items-center gap-2 px-2.5 py-1 rounded-lg border border-[var(--border)] bg-[var(--card)] hover:border-[#d42a2b] transition cursor-pointer shadow-2xs" onclick="openOrgNodeDetailModal('${l.from}')" title="Zu Vorgesetztem springen">
                <img src="${pAvatar}" class="w-5 h-5 rounded-full object-cover" />
                <span class="text-xs font-semibold text-primary-custom">${opsEscapeHtml(pTitle)}</span>
              </div>
            `;
          }).join(' ');
        }
      }

      const childListEl = document.getElementById('ond-child-list');
      if (childListEl) {
        if (childLinks.length === 0) {
          childListEl.innerHTML = `<span class="text-xs text-muted-custom italic">Keine direkt unterstellten Agenten</span>`;
        } else {
          childListEl.innerHTML = childLinks.map(l => {
            const cNode = (currentHierarchyData.nodes || []).find(n => n.id === l.to);
            const cProf = (hermesProfilesData || []).find(p => p.id === l.to);
            const cHuman = cNode?.person_name || cProf?.person_name || '';
            const cTitle = cHuman ? `${cHuman} (${cNode?.name || l.to})` : (cNode?.name || l.to);
            const cAvatar = cNode?.avatar || cProf?.avatar || '/static/avatars/avatar_001.jpg';
            return `
              <div class="inline-flex items-center gap-2 px-2.5 py-1 rounded-lg border border-[var(--border)] bg-[var(--card)] hover:border-[#d42a2b] transition cursor-pointer shadow-2xs" onclick="openOrgNodeDetailModal('${l.to}')" title="Zu Agent springen">
                <img src="${cAvatar}" class="w-5 h-5 rounded-full object-cover" />
                <span class="text-xs font-semibold text-primary-custom">${opsEscapeHtml(cTitle)}</span>
              </div>
            `;
          }).join(' ');
        }
      }

      // Aufgaben & Arbeitsergebnisse aus kanban.db
      const allTasks = [];
      if (opsKanbanData && opsKanbanData.columns) {
        Object.values(opsKanbanData.columns).forEach(col => {
          col.forEach(t => {
            if (t.assignee === nodeId) {
              allTasks.push(t);
            }
          });
        });
      }

      const tasksContainer = document.getElementById('ond-tasks-container');
      if (tasksContainer) {
        if (allTasks.length === 0) {
          tasksContainer.innerHTML = `
            <div class="p-4 text-center border border-dashed border-[var(--border)] rounded-xl bg-[var(--background)]">
              <p class="text-xs text-muted-custom font-mono">Diesem Agenten sind momentan keine Aufgaben zugewiesen.</p>
              <button type="button" onclick="closeOrgNodeDetailModal(); openNewTaskModal('todo', '${nodeId}', '${node.team_id || ''}')" class="mt-2.5 px-3 py-1.5 rounded-lg bg-[#d42a2b] hover:bg-[#b82223] text-white text-xs font-mono font-medium transition cursor-pointer inline-flex items-center gap-1.5 shadow-2xs">
                <i data-lucide="plus" class="w-3.5 h-3.5"></i>
                <span>Aufgabe zuweisen</span>
              </button>
            </div>
          `;
        } else {
          tasksContainer.innerHTML = allTasks.map(t => {
            const statusColors = {
              triage: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300',
              todo: 'bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300',
              ready: 'bg-cyan-50 text-cyan-700 dark:bg-cyan-950/40 dark:text-cyan-300',
              in_progress: 'bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300',
              review: 'bg-purple-50 text-purple-700 dark:bg-purple-950/40 dark:text-purple-300',
              done: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300'
            }[t.status] || 'bg-slate-100 text-slate-700';

            const hasResult = t.result && t.result.trim().length > 0;

            return `
              <div class="p-3.5 rounded-xl border border-[var(--border)] bg-[var(--background)] space-y-2 shadow-2xs">
                <div class="flex items-center justify-between gap-2">
                  <div class="flex items-center gap-2 min-w-0">
                    <span class="px-2 py-0.5 rounded text-[10px] font-mono font-bold ${statusColors}">${(t.status || 'todo').toUpperCase()}</span>
                    <span class="text-xs font-bold text-primary-custom truncate">${opsEscapeHtml(t.title)}</span>
                  </div>
                  <button type="button" onclick="closeOrgNodeDetailModal(); openTaskDetailModal('${t.id}')" class="text-xs text-muted-custom hover:text-[#d42a2b] font-mono font-medium transition cursor-pointer shrink-0">
                    Details &rarr;
                  </button>
                </div>
                ${t.body ? `<p class="text-xs text-muted-custom line-clamp-2 leading-relaxed font-sans">${opsEscapeHtml(t.body)}</p>` : ''}
                
                ${hasResult ? `
                  <div class="p-3 rounded-lg border border-emerald-500/30 bg-emerald-500/10 text-xs">
                    <div class="flex items-center gap-1.5 font-bold text-emerald-600 dark:text-emerald-400 mb-1 font-mono">
                      <i data-lucide="check-circle" class="w-3.5 h-3.5"></i>
                      <span>Arbeitsergebnis / Deliverable:</span>
                    </div>
                    <div data-archon-linkify class="text-[11.5px] leading-relaxed text-primary-custom font-sans whitespace-pre-wrap">${opsEscapeHtml(t.result)}</div>
                  </div>
                ` : ''}
              </div>
            `;
          }).join('');
        }
      }

      // Actions
      const assignBtn = document.getElementById('ond-action-assign');
      if (assignBtn) {
        assignBtn.onclick = () => {
          closeOrgNodeDetailModal();
          openNewTaskModal('todo', nodeId, node.team_id || '');
        };
      }

      const chatBtn = document.getElementById('ond-action-chat');
      if (chatBtn) {
        chatBtn.onclick = () => {
          const targetAgentId = nodeId || (profile && profile.id) || (node && node.id);
          closeOrgNodeDetailModal();
          setTab('master-chat');
          if (typeof switchMasterChatAgent === 'function') {
            switchMasterChatAgent(targetAgentId);
          }
        };
      }

      const kaderBtn = document.getElementById('ond-action-kader');
      if (kaderBtn) {
        kaderBtn.onclick = () => {
          closeOrgNodeDetailModal();
          setTab('agent-profiles');
          if (typeof selectProfileForEditor === 'function') {
            selectProfileForEditor(nodeId);
          }
        };
      }

      modal.classList.remove('hidden');
      if (window.lucide) lucide.createIcons();
    }

    async function saveOrgNodeDetailChanges() {
      if (!currentOrgDetailNodeId) return;
      const saveBtn = document.getElementById('ond-action-save');
      const origHtml = saveBtn ? saveBtn.innerHTML : 'Speichern';
      if (saveBtn) {
        saveBtn.disabled = true;
        saveBtn.innerHTML = `<svg class="animate-spin -ml-1 mr-1.5 h-3.5 w-3.5 text-white inline" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg> Speichere...`;
      }

      try {
        const personName = (document.getElementById('ond-edit-person-name')?.value || '').trim();
        const roleName = (document.getElementById('ond-edit-name')?.value || '').trim();
        const provider = document.getElementById('ond-edit-provider')?.value || 'omniroute';
        const model = (document.getElementById('ond-edit-model')?.value || 'auto/best-free').trim();
        const teamId = document.getElementById('ond-edit-team')?.value || 'team_strategy';
        const tier = parseInt(document.getElementById('ond-edit-tier')?.value, 10) || 3;
        let parentId = (document.getElementById('ond-edit-parent')?.value || '').trim();

        // Selbstreferenz strikt verhindern!
        if (parentId === currentOrgDetailNodeId) {
          parentId = '';
        }

        // 1. Lokalen Node in currentHierarchyData aktualisieren
        const node = (currentHierarchyData.nodes || []).find(n => n.id === currentOrgDetailNodeId);
        if (node) {
          node.person_name = personName;
          node.name = roleName || personName || node.id;
          node.role = roleName || node.role;
          node.provider = provider;
          node.model = model;
          node.team_id = teamId;
          node.tier = tier;
        }

        // 2. Links aktualisieren: Alte Vorgesetzten-Verbindung für diesen Knoten entfernen
        currentHierarchyData.links = (currentHierarchyData.links || []).filter(l => 
          l.to !== currentOrgDetailNodeId && l.from !== l.to
        );

        // Neue Verbindung hinzufügen, falls Vorgesetzter gewählt
        if (parentId && parentId !== currentOrgDetailNodeId) {
          currentHierarchyData.links.push({
            from: parentId,
            to: currentOrgDetailNodeId
          });
        }

        // 3. Hierarchie im Backend speichern
        const hierRes = await fetch('/api/operations/org-hierarchy', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(currentHierarchyData)
        });

        if (!hierRes.ok) {
          console.warn('[Operations] Hierarchy save response not ok:', hierRes.status);
        }

        // 4. Profil im Profil-SSOT (/api/hermes/profiles) spiegeln
        const prof = (hermesProfilesData || []).find(p => p.id === currentOrgDetailNodeId);
        if (prof) {
          prof.person_name = personName;
          prof.name = roleName || prof.name;
          prof.provider = provider;
          prof.model = model;

          const payload = {
            id: currentOrgDetailNodeId,
            old_id: currentOrgDetailNodeId,
            person_name: personName || prof.person_name || roleName,
            name: roleName || prof.name || personName,
            category: prof.category || "1. Strategie, Führung & Lebensplanung",
            description: prof.description || "",
            avatar: prof.avatar || node?.avatar || "/static/avatars/avatar_001.jpg",
            prompt: prof.prompt || prof.system_prompt || "",
            system_prompt: prof.prompt || prof.system_prompt || "",
            provider: provider,
            model: model,
            skills: prof.skills || [],
            tools: prof.tools || (typeof DEFAULT_HERMES_TOOLS !== 'undefined' ? DEFAULT_HERMES_TOOLS : [])
          };

          try {
            await fetch('/api/hermes/profiles', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(payload)
            });
          } catch(e) {
            console.warn('[Operations] Error mirroring profile to hermes API:', e);
          }
        }

        // 5. Flowchart neu rendern
        renderOpsOrgFlowchart();
        if (typeof showArchonToast === 'function') {
          showArchonToast('Agenten-Eigenschaften & Hierarchie erfolgreich gespeichert!', 'success');
        }
        closeOrgNodeDetailModal();
      } catch (err) {
        console.error('Fehler beim Speichern der Agenten-Eigenschaften:', err);
        if (typeof showArchonToast === 'function') {
          showArchonToast('Fehler beim Speichern: ' + (err.message || err), 'error');
        }
      } finally {
        if (saveBtn) {
          saveBtn.disabled = false;
          saveBtn.innerHTML = origHtml;
          if (window.lucide) lucide.createIcons();
        }
      }
    }

    function closeOrgNodeDetailModal() {
      const modal = document.getElementById('ops-node-detail-modal');
      if (modal) modal.classList.add('hidden');
    }

    // =========================================================================
    // TASK MODAL TEAM & PROMPT STUDIO INTEGRATION
    // =========================================================================

    function onOpsTaskTeamChange(teamId) {
      const select = document.getElementById('ops-task-assignee');
      if (!select || !opsOrgData) return;
      select.innerHTML = '<option value="">(Nicht zugewiesen / Auto-Dispatch an Lead)</option>';

      if (!teamId) {
        populateAssigneeDropdowns(opsOrgData);
        return;
      }

      const team = (opsOrgData.teams || []).find(t => t.id === teamId);
      if (!team) return;

      const grp = document.createElement('optgroup');
      grp.label = team.name;
      if (team.lead) {
        const opt = document.createElement('option');
        opt.value = team.lead.id;
        opt.textContent = `★ ${team.lead.name} (Department Lead)`;
        opt.selected = true;
        grp.appendChild(opt);
      }
      (team.members || []).forEach(m => {
        const opt = document.createElement('option');
        opt.value = m.id;
        opt.textContent = `${m.name} (${m.role || m.category})`;
        grp.appendChild(opt);
      });
      select.appendChild(grp);
    }

    function populateAssigneeDropdowns(orgData) {
      const select = document.getElementById('ops-task-assignee');
      if (!select) return;
      const currentVal = select.value;
      select.innerHTML = '<option value="">(Nicht zugewiesen / Auto-Dispatch an Lead)</option>';
      
      const grpBoard = document.createElement('optgroup');
      grpBoard.label = 'Unternehmensführung & Apex';
      if (orgData.tier1_executive?.chairman) {
        const opt = document.createElement('option');
        opt.value = orgData.tier1_executive.chairman.id;
        opt.textContent = `${orgData.tier1_executive.chairman.name} (Chairman)`;
        grpBoard.appendChild(opt);
      }
      if (orgData.tier1_executive?.orchestrator) {
        const opt = document.createElement('option');
        opt.value = orgData.tier1_executive.orchestrator.id;
        opt.textContent = `${orgData.tier1_executive.orchestrator.name} (CTO / Orchestrator)`;
        grpBoard.appendChild(opt);
      }
      select.appendChild(grpBoard);

      (orgData.teams || []).forEach(team => {
        const grp = document.createElement('optgroup');
        grp.label = team.name;
        if (team.lead) {
          const opt = document.createElement('option');
          opt.value = team.lead.id;
          opt.textContent = `★ ${team.lead.name} (Lead)`;
          grp.appendChild(opt);
        }
        (team.members || []).forEach(m => {
          const opt = document.createElement('option');
          opt.value = m.id;
          opt.textContent = `${m.name} (${m.role || m.category})`;
          grp.appendChild(opt);
        });
        select.appendChild(grp);
      });
      if (currentVal) select.value = currentVal;
    }

    // Spalten-Design (User-Vorgabe 10.10.2026): „Posteo-Regenbogen"-Naturpalette.
    // headerColor/headerTextColor = exakte Hex-Werte, inline gestylt.
    const OPS_COLUMNS_CONFIG = [
      { id: 'todo', label: 'To-Do', icon: 'circle', color: 'slate', border: 'border-slate-400/30', bg: 'bg-slate-500/10', text: 'text-slate-400',
        headerColor: '#F3E8DE', headerTextColor: '#6b5d4f' },
      { id: 'in_progress', label: 'In Bearbeitung', icon: 'play-circle', color: 'amber', border: 'border-amber-500/30', bg: 'bg-amber-500/10', text: 'text-amber-500',
        headerColor: '#EED65B', headerTextColor: '#6b5c10' },
      { id: 'review', label: 'Review & QA', icon: 'eye', color: 'purple', border: 'border-purple-500/30', bg: 'bg-purple-500/10', text: 'text-purple-500',
        headerColor: '#7CA982', headerTextColor: '#2f4a33' },
      { id: 'blocked', label: 'Blockiert / Eskalation', icon: 'alert-octagon', color: 'rose', border: 'border-rose-500/30', bg: 'bg-rose-500/10', text: 'text-rose-500',
        headerColor: '#C15C53', headerTextColor: '#ffffff' },
      { id: 'done', label: 'Abgeschlossen', icon: 'check-check', color: 'emerald', border: 'border-emerald-500/30', bg: 'bg-emerald-500/10', text: 'text-emerald-500',
        headerColor: '#4A6D88', headerTextColor: '#ffffff' }
    ];
    // 10.10.2026 (User-Entscheidung): 5-Spalten-Modell. Maschinen-Status der
    // Engine werden in der To-Do-Spalte gruppiert — reine UI-Sache, kein Engine-Eingriff.
    const OPS_COLUMN_GROUPS = {
      todo: ['todo', 'ready', 'triage', 'scheduled'],
      in_progress: ['in_progress'],
      review: ['review'],
      blocked: ['blocked'],
      done: ['done']
    };
    const OPS_STATUS_BADGES = {
      ready:     { text: '⚡ bereit',  cls: 'bg-cyan-500/10 text-cyan-600 border-cyan-500/30' },
      triage:    { text: '🔍 Triage',  cls: 'bg-slate-500/10 text-slate-500 border-slate-500/30' },
      scheduled: { text: '⏱ geplant', cls: 'bg-amber-500/10 text-amber-600 border-amber-500/30' }
    };

    // Einstellbare Farbpalette (User-Wunsch 10.10.2026, Design-Tab der Einstellungen)
    let opsKanbanPalette = null;
    async function fetchOpsKanbanPalette() {
      try {
        const res = await fetch('/api/operations/kanban/palette');
        const data = await res.json();
        if (data && data.columns) opsKanbanPalette = data.columns;
      } catch (e) {
        console.warn('[Kanban] Farbpalette konnte nicht geladen werden:', e);
      }
    }
    window.fetchOpsKanbanPalette = fetchOpsKanbanPalette;
    fetchOpsKanbanPalette();

    function opsHexToRgba(hex, alpha) {
      // Header-Farbe (Palette oder Posteo-Default) -> 10 %-Tönung für den Spaltenkörper.
      const h = String(hex || '').replace('#', '');
      const full = h.length === 3 ? h.split('').map(c => c + c).join('') : h;
      const n = parseInt(full.slice(0, 6), 16);
      if (!isFinite(n)) return `rgba(128,128,128,${alpha})`;
      return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${alpha})`;
    }
    function renderOperationsKanban(data) {
      const container = document.getElementById('ops-kanban-columns-container');
      const badge = document.getElementById('ops-kanban-badge');
      if (!container) return;
      if (badge) badge.textContent = data.total_tasks || 0;
      opsKanbanWip = data.wip || {};
      populateOpsKanbanAssigneeFilter(data);

      const cols = data.columns || {};
      container.innerHTML = OPS_COLUMNS_CONFIG.map(col => {
        const group = OPS_COLUMN_GROUPS[col.id] || [col.id];
        const entries = [];
        group.forEach((s, si) => (cols[s] || []).forEach(t => {
          if (opsKanbanMatches(t)) entries.push({ t, si });
        }));
        const sortMode = opsKanbanFilters.sort;
        if (sortMode === 'prio') entries.sort((a, b) => ((b.t.priority || 0) - (a.t.priority || 0)) || (a.si - b.si));
        else if (sortMode === 'newest') entries.sort((a, b) => String(b.t.created_at || '').localeCompare(String(a.t.created_at || '')));
        else if (sortMode === 'title') entries.sort((a, b) => String(a.t.title || '').localeCompare(String(b.t.title || ''), 'de'));
        else entries.sort((a, b) => a.si - b.si);
        const tasks = entries.map(o => o.t);
        const wipLimit = (opsKanbanWip || {})[col.id] || 0;
        const wipOver = wipLimit > 0 && tasks.length > wipLimit;
        const countText = wipLimit > 0 ? `${tasks.length}/${wipLimit}` : String(tasks.length);
        const taskCards = tasks.map(t => {
          const priorityLabels = ['P3', 'P2', 'P1', 'P0'];
          const priorityColors = [
            'bg-slate-500/10 text-slate-400 border-slate-500/20',
            'bg-blue-500/10 text-blue-500 border-blue-500/20',
            'bg-amber-500/10 text-amber-500 border-amber-500/20',
            'bg-rose-500/10 text-rose-500 border-rose-500/20 font-bold'
          ];
          const prioIdx = Math.min(Math.max(t.priority || 0, 0), 3);
          const prioClass = priorityColors[prioIdx];
          const prioText = priorityLabels[prioIdx];

                    let avatar = t.assignee_avatar || '/static/avatars/avatar_001.jpg';
          let assigneeName = t.assignee_name || t.assignee || t.agent_name || 'Auto-Dispatch';
          if (typeof opsOrgData !== 'undefined' && opsOrgData && opsOrgData.nodes) {
            const node = opsOrgData.nodes.find(n => n.id === t.agent_id || n.id === t.agent_name || n.person_name === t.agent_name);
            if (node && node.avatar) avatar = node.avatar;
            if (node && node.person_name) assigneeName = node.person_name;
          }
          const modelBadge = t.model_override ? `<span class="px-1.5 py-0.5 rounded text-[9px] font-mono bg-slate-500/10 text-slate-400 border border-slate-500/20 truncate max-w-[110px]">${t.model_override.split('/').pop()}</span>` : '';
          const badgeInfo = OPS_STATUS_BADGES[t.status];
          const statusBadge = badgeInfo ? `<span class="px-1.5 py-0.5 rounded text-[9px] font-bold border ${badgeInfo.cls}">${badgeInfo.text}</span>` : '';
          const todayStr = new Date().toISOString().slice(0, 10);
          const isOverdue = !!(t.due_date && t.due_date < todayStr && t.status !== 'done');
          const dueBadge = t.due_date
            ? `<span class="px-1.5 py-0.5 rounded text-[9px] font-bold border ${isOverdue ? 'bg-red-500/15 text-red-500 border-red-500/40' : 'bg-amber-500/10 text-amber-600 border-amber-500/30'}" title="Fällig bis ${t.due_date}${isOverdue ? ' — ÜBERFÄLLIG' : ''}">📅 ${t.due_date.slice(5)}</span>`
            : '';
          const countParts = [];
          if (t.comment_count > 0) countParts.push(`💬${t.comment_count}`);
          if (t.subtask_count > 0) countParts.push(`↳${t.subtask_count}`);
          if (t.parent_count > 0) countParts.push(`⛓${t.parent_count}`);
          // User-Wunsch 11.10.: Ergebnis-Fortschritt direkt auf der Card sichtbar
          if (t.result && String(t.result).trim().length > 0) countParts.push(`📄`);
          const countBadge = countParts.length
            ? `<span class="px-1 py-0.5 rounded text-[9px] font-bold border bg-slate-500/10 text-slate-500 border-slate-500/30" title="Kommentare / Subtasks / Abhängigkeiten">${countParts.join(' ')}</span>`
            : '';
          const tagPills = ((t.tags || []).slice(0, 3).map(tg =>
              `<span class="px-1 py-0.5 rounded text-[9px] font-bold border bg-indigo-500/10 text-indigo-500 border-indigo-500/30 shrink-0">#${opsEscapeHtml(tg)}</span>`).join(''))
            + ((t.tags || []).length > 3 ? `<span class="text-[9px] text-muted-custom shrink-0">+${t.tags.length - 3}</span>` : '');

          const decOpen = !!(t.decision && ((t.decision.status || 'offen') === 'offen'));
          const decTypName = { delegation_review: 'Delegation prüfen', synthesis_freigabe: 'Synthese freigeben',
                               mission_freigabe: 'Mission freigeben', permission_gate: 'Rechte freigeben' };
          const decTyp = decOpen ? (decTypName[t.decision.typ] || 'Entscheidung') : '';
          const projektName = t.obsidian ? String(t.obsidian).split('/').filter(Boolean).pop() : '';
          return `
            <div draggable="true" 
                 ondragstart="onKanbanDragStart(event, '${t.id}')"
                 onclick="openTaskDetailModal('${t.id}')"
                 class="group rounded-xl border ${decOpen ? 'border-[#e8c37a]' : 'border-[var(--border)]'} bg-[var(--card)] hover:border-indigo-500/40 hover:shadow-md transition-all duration-150 cursor-pointer overflow-hidden">
              ${decOpen ? `<div class="flex items-center justify-between gap-1 px-3 py-1.5 bg-[#fdf3e2] border-b border-[#e8c37a]">
                <span class="text-[9.5px] font-bold uppercase tracking-wider text-[#8a5d10] truncate">⏳ Offene Entscheidung · ${opsEscapeHtml(decTyp)}</span>
                <span class="px-1.5 py-0.2 rounded border ${prioClass} text-[9px] shrink-0">${prioText}</span>
              </div>` : ''}
              <div class="p-3 space-y-2.5">
                <div class="flex items-center justify-between gap-1 text-[10px] font-mono">
                  <div class="flex items-center gap-1 min-w-0 truncate">${statusBadge}${dueBadge}${modelBadge}</div>
                  <div class="flex items-center gap-1 shrink-0">
                    ${countBadge}
                    ${decOpen ? '' : `<span class="px-1.5 py-0.2 rounded border ${prioClass}">${prioText}</span>`}
                  </div>
                </div>
                <h4 class="text-xs font-semibold text-primary-custom leading-snug line-clamp-2">${opsEscapeHtml(t.title)}</h4>
                ${t.body ? `<p class="text-[11px] text-muted-custom line-clamp-2 leading-relaxed">${opsEscapeHtml(t.body)}</p>` : ''}
                ${projektName ? `<div class="inline-block max-w-full truncate px-1.5 py-0.5 rounded text-[9.5px] font-mono text-muted-custom bg-[var(--secondary)] border border-[var(--border)]" title="${opsEscapeHtml(t.obsidian)}">📁 ${opsEscapeHtml(projektName)}</div>` : ''}
                <div class="pt-1 flex items-center justify-between border-t border-[var(--border)]/50 text-[10px]">
                  <div class="flex items-center gap-1.5 min-w-0">
                    <img src="${avatar}" class="w-7 h-7 rounded-full object-cover shrink-0 border border-[var(--border)]" />
                    <span class="truncate text-muted-custom font-medium">${opsEscapeHtml(assigneeName)}</span>
                  </div>
                  ${tagPills}
                  <i data-lucide="chevron-right" class="w-3 h-3 text-muted-custom/40 group-hover:text-indigo-500 transition-colors"></i>
                </div>
              </div>
            </div>
          `;
        }).join('');

        return `
          <div class="w-80 shrink-0 flex flex-col h-full rounded-2xl border border-[var(--border)] bg-[var(--card)]/60 overflow-hidden shadow-2xs" style="background-color: ${opsHexToRgba(((opsKanbanPalette && opsKanbanPalette[col.id] && opsKanbanPalette[col.id].header) || col.headerColor), 0.10)};">
            <!-- Header (User-Design 10.10.2026): Palette aus Einstellungen, sonst Posteo-Default) -->
            <div class="px-3 py-2.5 min-h-[52px] flex items-center justify-between border-b border-[var(--border)] shrink-0" style="background-color: ${((opsKanbanPalette && opsKanbanPalette[col.id] && opsKanbanPalette[col.id].header) || col.headerColor)}; color: ${((opsKanbanPalette && opsKanbanPalette[col.id] && opsKanbanPalette[col.id].text) || col.headerTextColor)};">
              <div class="flex items-center gap-2 min-w-0">
                <span class="w-2.5 h-2.5 rounded-full ${col.bg} border ${col.border} shrink-0"></span>
                <span class="text-xs font-bold font-mono uppercase tracking-wider truncate" style="color: ${((opsKanbanPalette && opsKanbanPalette[col.id] && opsKanbanPalette[col.id].text) || col.headerTextColor)};">${col.label}</span>
                <span class="px-1.5 py-0.2 rounded-full text-[10px] font-mono font-bold bg-[var(--card)] text-muted-custom border border-[var(--border)] shrink-0" ${wipOver ? 'style="color:#C15C53;border-color:#C15C53;" title="WIP-Limit überschritten!"' : (wipLimit > 0 ? `title="WIP-Limit: ${wipLimit}"` : '')}>${countText}</span>
              </div>
              <button onclick="openNewTaskModal('${col.id}')" class="p-1 rounded-lg hover:bg-[var(--card)] text-muted-custom hover:text-indigo-500 transition cursor-pointer shrink-0" title="Aufgabe hier hinzufügen">
                <i data-lucide="plus" class="w-3.5 h-3.5"></i>
              </button>
            </div>
            <!-- Drop-Zone / Tasks List -->
            <div ondragover="onKanbanDragOver(event)" 
                 ondrop="onKanbanDrop(event, '${col.id}')" 
                 class="flex-1 p-2.5 overflow-y-auto space-y-2.5 min-h-[150px] transition-colors">
              ${tasks.length > 0 ? taskCards : `
                <div class="h-32 border-2 border-dashed border-[var(--border)]/60 rounded-xl flex flex-col items-center justify-center text-center p-3 text-muted-custom/60 pointer-events-none">
                  <i data-lucide="${col.icon}" class="w-5 h-5 mb-1 opacity-40"></i>
                  <span class="text-[11px] font-mono">Keine Aufgaben</span>
                </div>
              `}
            </div>
          </div>
        `;
      }).join('');
      if (window.lucide) lucide.createIcons();
    }

    function onKanbanDragStart(e, taskId) {
      e.dataTransfer.setData('text/plain', taskId);
      e.dataTransfer.effectAllowed = 'move';
    }

    function onKanbanDragOver(e) {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
    }

    async function onKanbanDrop(e, targetColumn) {
      e.preventDefault();
      const taskId = e.dataTransfer.getData('text/plain');
      if (!taskId) return;
      try {
        const res = await fetch(`/api/operations/kanban/tasks/${taskId}/status`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ status: targetColumn })
        });
        if (res.ok) {
          if (typeof showArchonToast === 'function') {
            showArchonToast(`Task ${taskId} nach '${targetColumn}' verschoben.`, 'success');
          }
          await loadOperationsData();
        } else {
          const err = await res.json();
          alert(`Fehler beim Verschieben: ${err.detail || 'Unbekannt'}`);
        }
      } catch (err) {
        console.error("Kanban Drop Error:", err);
      }
    }

    function renderOperationsOrgChart(orgData) {
      const container = document.getElementById('ops-org-chart-container');
      if (!container) return;

      const chairman = orgData.tier1_executive?.chairman;
      const orchestrator = orgData.tier1_executive?.orchestrator;

      const chairmanCard = chairman ? `
        <div class="w-84 p-4 rounded-2xl border-2 border-indigo-500/30 bg-[var(--card)] shadow-md flex items-center gap-3.5 relative overflow-hidden group">
          <div class="absolute -right-2 -top-2 w-16 h-16 bg-indigo-500/10 rounded-full blur-xl pointer-events-none"></div>
          <div class="relative shrink-0">
            <img src="${chairman.avatar}" class="w-13 h-13 rounded-2xl object-cover border border-indigo-500/30 shadow-xs" />
            <span class="absolute -bottom-1 -right-1 w-3.5 h-3.5 rounded-full bg-emerald-500 border-2 border-[var(--card)]"></span>
          </div>
          <div class="min-w-0 flex-1">
            <div class="flex items-center justify-between gap-1">
              <span class="px-2 py-0.5 rounded text-[9px] font-mono font-bold bg-indigo-500/10 text-indigo-500 border border-indigo-500/20">TIER 1 · CHAIRMAN</span>
              <span class="text-[10px] font-mono text-muted-custom">${chairman.active_tasks || 0} Tasks</span>
            </div>
            <h3 class="text-sm font-bold text-primary-custom truncate mt-1">${opsEscapeHtml(chairman.name)}</h3>
            <p class="text-[11px] text-muted-custom truncate">${opsEscapeHtml(chairman.role)}</p>
            <div class="mt-2 flex items-center justify-between">
              <span class="text-[9px] font-mono text-muted-custom truncate">${chairman.model ? chairman.model.split('/').pop() : 'OmniRoute'}</span>
              <button onclick="openNewTaskModal('todo', '${chairman.id}')" class="px-2 py-0.8 rounded text-[10px] bg-indigo-600 hover:bg-indigo-700 text-white font-medium transition cursor-pointer">
                Delegieren
              </button>
            </div>
          </div>
        </div>
      ` : '';

      const orchestratorCard = orchestrator ? `
        <div class="w-84 p-4 rounded-2xl border-2 border-blue-500/30 bg-[var(--card)] shadow-md flex items-center gap-3.5 relative overflow-hidden group">
          <div class="absolute -right-2 -top-2 w-16 h-16 bg-blue-500/10 rounded-full blur-xl pointer-events-none"></div>
          <div class="relative shrink-0">
            <img src="${orchestrator.avatar}" class="w-13 h-13 rounded-2xl object-cover border border-blue-500/30 shadow-xs" />
            <span class="absolute -bottom-1 -right-1 w-3.5 h-3.5 rounded-full bg-emerald-500 border-2 border-[var(--card)]"></span>
          </div>
          <div class="min-w-0 flex-1">
            <div class="flex items-center justify-between gap-1">
              <span class="px-2 py-0.5 rounded text-[9px] font-mono font-bold bg-blue-500/10 text-blue-500 border border-blue-500/20">TIER 1 · CTO & DISPATCHER</span>
              <span class="text-[10px] font-mono text-muted-custom">${orchestrator.active_tasks || 0} Tasks</span>
            </div>
            <h3 class="text-sm font-bold text-primary-custom truncate mt-1">${opsEscapeHtml(orchestrator.name)}</h3>
            <p class="text-[11px] text-muted-custom truncate">${opsEscapeHtml(orchestrator.role)}</p>
            <div class="mt-2 flex items-center justify-between">
              <span class="text-[9px] font-mono text-muted-custom truncate">${orchestrator.model ? orchestrator.model.split('/').pop() : 'OmniRoute'}</span>
              <button onclick="openNewTaskModal('todo', '${orchestrator.id}')" class="px-2 py-0.8 rounded text-[10px] bg-blue-600 hover:bg-blue-700 text-white font-medium transition cursor-pointer">
                Delegieren
              </button>
            </div>
          </div>
        </div>
      ` : '';

      const teamsHtml = (orgData.teams || []).map(team => {
        const lead = team.lead;
        const colorClasses = {
          indigo: 'border-indigo-500/30 bg-indigo-500/5 text-indigo-500',
          blue: 'border-blue-500/30 bg-blue-500/5 text-blue-500',
          amber: 'border-amber-500/30 bg-amber-500/5 text-amber-500',
          emerald: 'border-emerald-500/30 bg-emerald-500/5 text-emerald-500',
          purple: 'border-purple-500/30 bg-purple-500/5 text-purple-500',
          rose: 'border-rose-500/30 bg-rose-500/5 text-rose-500'
        }[team.color || 'indigo'] || 'border-indigo-500/30 bg-indigo-500/5 text-indigo-500';

        const membersList = (team.members || []).map(m => `
          <div class="p-2 rounded-xl border border-[var(--border)] bg-[var(--background)] hover:border-indigo-500/30 transition flex items-center justify-between gap-2 text-xs">
            <div class="flex items-center gap-2 min-w-0">
              <img src="${m.avatar}" class="w-6 h-6 rounded-full object-cover shrink-0 border border-[var(--border)]" />
              <div class="min-w-0 leading-tight">
                <div class="font-semibold text-primary-custom truncate text-[11px]">${opsEscapeHtml(m.name)}</div>
                <div class="text-[9.5px] text-muted-custom truncate">${opsEscapeHtml(m.role || m.category)}</div>
              </div>
            </div>
            <div class="flex items-center gap-1.5 shrink-0">
              <span class="px-1.5 py-0.2 rounded text-[9px] font-mono bg-slate-500/10 text-muted-custom">${m.active_tasks || 0}</span>
              <button onclick="openNewTaskModal('todo', '${m.id}', '${team.id}')" class="p-1 rounded hover:bg-[var(--secondary)] text-muted-custom hover:text-indigo-500 transition cursor-pointer" title="Aufgabe an ${opsEscapeHtml(m.name)} zuweisen">
                <i data-lucide="plus" class="w-3 h-3"></i>
              </button>
            </div>
          </div>
        `).join('');

        return `
          <div class="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4 shadow-xs flex flex-col space-y-3.5">
            <!-- Team Header -->
            <div class="flex items-center justify-between border-b border-[var(--border)] pb-2.5">
              <div>
                <span class="px-2 py-0.5 rounded text-[9.5px] font-mono font-bold border uppercase tracking-wider ${colorClasses}">
                  ${team.name}
                </span>
                <span class="text-[10px] font-mono text-muted-custom ml-2">${team.member_count} Agenten</span>
              </div>
            </div>

            <!-- Team Lead Card -->
            ${lead ? `
              <div class="p-3 rounded-xl border-2 border-dashed ${colorClasses} flex items-center justify-between gap-2.5">
                <div class="flex items-center gap-2.5 min-w-0">
                  <div class="relative shrink-0">
                    <img src="${lead.avatar}" class="w-9 h-9 rounded-xl object-cover border border-[var(--border)]" />
                    <span class="absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 rounded-full bg-emerald-500 border border-white dark:border-black"></span>
                  </div>
                  <div class="min-w-0 leading-tight">
                    <div class="text-[9px] font-mono uppercase font-bold text-muted-custom">Department Lead</div>
                    <div class="text-xs font-bold text-primary-custom truncate">${opsEscapeHtml(lead.name)}</div>
                    <div class="text-[10px] text-muted-custom truncate">${opsEscapeHtml(lead.role)}</div>
                  </div>
                </div>
                <button onclick="openNewTaskModal('todo', '${lead.id}', '${team.id}')" class="px-2 py-1 rounded-lg bg-[var(--secondary)] hover:bg-indigo-600 hover:text-white text-muted-custom text-[10px] font-mono transition cursor-pointer shrink-0">
                  Zuweisen
                </button>
              </div>
            ` : ''}

            <!-- Specialists Grid -->
            <div class="space-y-1.5 flex-1 overflow-y-auto max-h-48 pr-1">
              ${membersList}
            </div>
          </div>
        `;
      }).join('');

      container.innerHTML = `
        <!-- TIER 1: BOARDROOM APEX -->
        <div class="flex flex-col items-center justify-center space-y-4">
          <div class="text-center">
            <span class="text-[10px] font-mono uppercase tracking-widest text-muted-custom font-bold">Organisationsstruktur & Hierarchie</span>
            <h2 class="text-base font-bold text-primary-custom font-mono">Tier 1: Executive Board & Architektur-Apex</h2>
          </div>
          <div class="flex flex-wrap items-center justify-center gap-6">
            ${chairmanCard}
            ${orchestratorCard}
          </div>
          <div class="w-0.5 h-8 bg-indigo-500/30"></div>
        </div>

        <!-- TIER 2 & 3: 6 DEPARTMENTS & SPECIALISTS -->
        <div class="space-y-3">
          <div class="flex items-center justify-between border-b border-[var(--border)] pb-2">
            <h3 class="text-xs font-bold uppercase tracking-wider text-muted-custom font-mono">Tier 2 & 3: Fachabteilungen & Spezialisten</h3>
            <span class="text-[10px] font-mono text-muted-custom">${orgData.total_agents || 0} Agenten im Kader registriert</span>
          </div>
          <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
            ${teamsHtml}
          </div>
        </div>
      `;
      if (window.lucide) lucide.createIcons();
    }

    function renderOperationsCommFeed(commData, filterAgentId) {
      const messagesContainer = document.getElementById('ops-comm-messages');
      const channelsContainer = document.getElementById('ops-comm-channels');
      const feedBadge = document.getElementById('ops-comm-badge');
      if (!messagesContainer || !channelsContainer) return;

      const rawItems = commData.feed || [];
      if (feedBadge) feedBadge.title = `${rawItems.length} Events`;

      const items = filterAgentId ? rawItems.filter(i => i.author_id === filterAgentId || i.target_id === filterAgentId) : rawItems;

      const agentsSet = new Map();
      rawItems.forEach(i => {
        if (i.author_id && !agentsSet.has(i.author_id)) {
          agentsSet.set(i.author_id, { id: i.author_id, name: i.author_name, avatar: i.author_avatar });
        }
      });

      channelsContainer.innerHTML = `
        <button onclick="filterOperationsComm(null)" class="w-full px-3 py-2 rounded-xl text-left text-xs font-mono transition cursor-pointer flex items-center justify-between ${!filterAgentId ? 'bg-indigo-600 text-white font-bold' : 'hover:bg-[var(--secondary)] text-muted-custom hover:text-primary-custom'}">
          <div class="flex items-center gap-2">
            <i data-lucide="radio" class="w-3.5 h-3.5"></i>
            <span>Alle Funkkanäle</span>
          </div>
          <span class="text-[10px] opacity-80">${rawItems.length}</span>
        </button>
        <div class="pt-2 pb-1 px-1">
          <span class="text-[9.5px] font-mono uppercase font-bold text-muted-custom/70">Aktive Funk-Teilnehmer</span>
        </div>
        ${Array.from(agentsSet.values()).map(a => `
          <button onclick="filterOperationsComm('${a.id}')" class="w-full px-2.5 py-1.5 rounded-lg text-left text-xs transition cursor-pointer flex items-center justify-between ${filterAgentId === a.id ? 'bg-indigo-600 text-white font-bold' : 'hover:bg-[var(--secondary)] text-muted-custom hover:text-primary-custom'}">
            <div class="flex items-center gap-2 min-w-0">
              <img src="${a.avatar || '/static/avatars/avatar_001.jpg'}" class="w-5 h-5 rounded-full object-cover shrink-0 border border-white/20" />
              <span class="truncate text-[11px]">${opsEscapeHtml(a.name)}</span>
            </div>
            <i data-lucide="chevron-right" class="w-3 h-3 opacity-60"></i>
          </button>
        `).join('')}
      `;

      if (items.length === 0) {
        messagesContainer.innerHTML = `
          <div class="h-64 flex flex-col items-center justify-center text-center p-6 text-muted-custom">
            <i data-lucide="message-square-off" class="w-8 h-8 mb-2 opacity-40"></i>
            <span class="text-xs font-mono">Keine internen Nachrichten für diesen Filter gefunden.</span>
          </div>
        `;
      } else {
        messagesContainer.innerHTML = items.map(item => {
          const isEvent = item.type === 'event_handoff';
          const avatar = item.author_avatar || '/static/avatars/avatar_001.jpg';
          const timeStr = item.timestamp ? new Date(item.timestamp).toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '';
          const taskBadge = item.task_id ? `
            <button onclick="openTaskDetailModal('${item.task_id}')" class="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-indigo-500/10 text-indigo-500 border border-indigo-500/20 hover:bg-indigo-500/20 transition cursor-pointer">
              Task: ${item.task_id}
            </button>
          ` : '';

          if (isEvent) {
            return `
              <div class="p-3 rounded-xl border border-indigo-500/20 bg-indigo-500/5 space-y-1.5">
                <div class="flex items-center justify-between gap-2 text-[10px] font-mono">
                  <div class="flex items-center gap-1.5">
                    <span class="px-1.5 py-0.2 rounded font-bold bg-indigo-500/20 text-indigo-400">DISPATCHER EVENT</span>
                    <span class="text-muted-custom">${timeStr}</span>
                  </div>
                  ${taskBadge}
                </div>
                <p class="text-xs text-primary-custom font-sans leading-relaxed">${opsEscapeHtml(item.message)}</p>
              </div>
            `;
          }

          return `
            <div class="p-3.5 rounded-2xl border border-[var(--border)] bg-[var(--card)] space-y-2 shadow-2xs">
              <div class="flex items-center justify-between gap-2">
                <div class="flex items-center gap-2 min-w-0">
                  <img src="${avatar}" class="w-6 h-6 rounded-full object-cover shrink-0 border border-[var(--border)]" />
                  <span class="text-xs font-bold text-primary-custom truncate">${opsEscapeHtml(item.author_name)}</span>
                  <span class="text-[10px] font-mono text-muted-custom">${timeStr}</span>
                </div>
                ${taskBadge}
              </div>
              <p class="text-xs text-primary-custom font-sans leading-relaxed pl-8">${opsEscapeHtml(item.message)}</p>
            </div>
          `;
        }).join('');
      }
      if (window.lucide) lucide.createIcons();
    }

    function filterOperationsComm(filterId) {
      activeCommFilter = filterId;
      const titleEl = document.getElementById('ops-comm-active-title');
      if (titleEl) {
        titleEl.textContent = filterId ? `📡 Funkverkehr gefiltert: ${filterId}` : '📡 Gesamt-Funkverkehr aller Agenten';
      }
      if (opsCommData) {
        renderOperationsCommFeed(opsCommData, activeCommFilter);
      }
    }

    function openNewTaskModal(defaultColumn, defaultAssignee, defaultTeam) {
      const modal = document.getElementById('ops-new-task-modal');
      if (!modal) return;
      if (defaultColumn) {
        const colSelect = document.getElementById('ops-task-column');
        if (colSelect) colSelect.value = defaultColumn;
      }
      if (defaultTeam) {
        const teamSelect = document.getElementById('ops-task-team');
        if (teamSelect) {
          teamSelect.value = defaultTeam;
          onOpsTaskTeamChange(defaultTeam);
        }
      }
      if (defaultAssignee) {
        const assignSelect = document.getElementById('ops-task-assignee');
        if (assignSelect) assignSelect.value = defaultAssignee;
      }
      modal.classList.remove('hidden');
      if (window.lucide) lucide.createIcons();
      setTimeout(() => document.getElementById('ops-task-title')?.focus(), 50);
    }

    let currentOpsTaskAttachment = null;
    let isOpsTaskDictating = false;
    let opsTaskDictationRecognition = null;

    function setOpsTaskAttachmentFile(file) {
      if (!file) return;
      currentOpsTaskAttachment = {
        file: file,
        name: file.name || "datei",
        size: (file.size / 1024).toFixed(1) + " KB",
        type: file.type || "application/octet-stream"
      };
      const bar = document.getElementById("ops-task-attachment-bar");
      const nameEl = document.getElementById("ops-task-attachment-name");
      const sizeEl = document.getElementById("ops-task-attachment-size");
      if (bar && nameEl) {
        nameEl.innerText = currentOpsTaskAttachment.name;
        if (sizeEl) sizeEl.innerText = `(${currentOpsTaskAttachment.size})`;
        bar.classList.remove("hidden");
        if (window.lucide && typeof lucide.createIcons === "function") lucide.createIcons();
      }
    }

    function handleOpsTaskFileSelected(event) {
      const file = event.target.files && event.target.files[0];
      if (!file) return;
      setOpsTaskAttachmentFile(file);
    }

    function handleOpsTaskInputPaste(event) {
      const items = (event.clipboardData || window.clipboardData)?.items;
      if (!items) return;
      for (let i = 0; i < items.length; i++) {
        const item = items[i];
        if (item.kind === 'file' && item.type.startsWith('image/')) {
          const blob = item.getAsFile();
          if (blob) {
            event.preventDefault();
            const ts = new Date().toISOString().replace(/[-:T.]/g, "").slice(0, 14);
            const file = new File([blob], `screenshot_${ts}.png`, { type: blob.type || "image/png" });
            setOpsTaskAttachmentFile(file);
            return;
          }
        }
      }
    }

    function removeOpsTaskAttachment() {
      currentOpsTaskAttachment = null;
      const bar = document.getElementById("ops-task-attachment-bar");
      if (bar) bar.classList.add("hidden");
      const input = document.getElementById("ops-task-file-input");
      if (input) input.value = "";
    }

    function toggleOpsTaskDictation() {
      const btn = document.getElementById("ops-task-mic-btn");
      const label = document.getElementById("ops-task-mic-label");
      const textarea = document.getElementById("ops-task-body");
      if (!("webkitSpeechRecognition" in window) && !("SpeechRecognition" in window)) {
        alert("Spracherkennung wird in diesem Browser leider nicht unterstützt. Bitte Chrome oder Edge nutzen.");
        return;
      }
      if (isOpsTaskDictating) {
        if (opsTaskDictationRecognition) {
          opsTaskDictationRecognition.stop();
        }
        isOpsTaskDictating = false;
        if (btn) {
          btn.className = "px-2.5 py-1 rounded-lg border border-[var(--border)] bg-[var(--card)] hover:bg-[var(--secondary)] text-[var(--foreground)] text-xs font-mono transition cursor-pointer flex items-center gap-1.5 shadow-2xs";
          btn.title = "Spracheingabe / Diktat starten (Mikrofon)";
        }
        if (label) label.textContent = "Diktat";
        return;
      }
      const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
      opsTaskDictationRecognition = new SpeechRec();
      opsTaskDictationRecognition.continuous = true;
      opsTaskDictationRecognition.interimResults = true;
      opsTaskDictationRecognition.lang = "de-DE";
      let baseText = textarea && textarea.value ? textarea.value.trim() + " " : "";
      opsTaskDictationRecognition.onresult = (event) => {
        let interimTranscript = "";
        let finalTranscript = "";
        for (let i = event.resultIndex; i < event.results.length; ++i) {
          if (event.results[i].isFinal) {
            finalTranscript += event.results[i][0].transcript;
          } else {
            interimTranscript += event.results[i][0].transcript;
          }
        }
        if (textarea) {
          textarea.value = baseText + finalTranscript + interimTranscript;
        }
      };
      opsTaskDictationRecognition.onerror = (event) => {
        console.error("[OpsTask Speech] Fehler:", event.error);
        isOpsTaskDictating = false;
        if (btn) {
          btn.className = "px-2.5 py-1 rounded-lg border border-[var(--border)] bg-[var(--card)] hover:bg-[var(--secondary)] text-[var(--foreground)] text-xs font-mono transition cursor-pointer flex items-center gap-1.5 shadow-2xs";
        }
        if (label) label.textContent = "Diktat";
      };
      opsTaskDictationRecognition.onend = () => {
        isOpsTaskDictating = false;
        if (btn) {
          btn.className = "px-2.5 py-1 rounded-lg border border-[var(--border)] bg-[var(--card)] hover:bg-[var(--secondary)] text-[var(--foreground)] text-xs font-mono transition cursor-pointer flex items-center gap-1.5 shadow-2xs";
        }
        if (label) label.textContent = "Diktat";
      };
      opsTaskDictationRecognition.start();
      isOpsTaskDictating = true;
      if (btn) {
        btn.className = "px-2.5 py-1 rounded-lg border border-red-500 text-red-500 bg-red-500/10 animate-pulse transition shrink-0 cursor-pointer shadow-2xs flex items-center gap-1.5 font-bold";
        btn.title = "Diktat läuft... Klicken zum Stoppen";
      }
      if (label) label.textContent = "Hört zu...";
    }

    function closeNewTaskModal() {
      if (isOpsTaskDictating && opsTaskDictationRecognition) {
        try { opsTaskDictationRecognition.stop(); } catch(e){}
        isOpsTaskDictating = false;
      }
      removeOpsTaskAttachment();
      const modal = document.getElementById('ops-new-task-modal');
      if (modal) modal.classList.add('hidden');
    }

    async function submitNewTask(e) {
      if (e) e.preventDefault();
      const title = document.getElementById('ops-task-title')?.value.trim();
      if (!title) return;

      let body = document.getElementById('ops-task-body')?.value.trim() || '';
      const column = document.getElementById('ops-task-column')?.value || 'todo';
      const priority = parseInt(document.getElementById('ops-task-priority')?.value || '0', 10);
      const teamId = document.getElementById('ops-task-team')?.value || null;
      const assignee = document.getElementById('ops-task-assignee')?.value || null;
      const model = document.getElementById('ops-task-model')?.value || null;
      const decompose = document.getElementById('ops-task-decompose')?.checked || false;

      const btn = document.getElementById('ops-task-submit-btn');
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<span class="animate-spin inline-block mr-1.5">⏳</span> Erstelle...`;
      }

      // Falls Anhang vorhanden, via /api/chat/upload hochladen und Pfad einbetten
      if (currentOpsTaskAttachment && currentOpsTaskAttachment.file) {
        try {
          const formData = new FormData();
          formData.append("file", currentOpsTaskAttachment.file);
          const uploadRes = await fetch("/api/chat/upload", {
            method: "POST",
            body: formData
          });
          if (uploadRes.ok) {
            const uploadData = await uploadRes.json();
            body = (body ? body + "\n\n" : "") + `[Datei angehängt: ${uploadData.path || uploadData.filename}]`;
          }
        } catch (uploadErr) {
          console.warn("[OpsTask Upload] Upload-Fehler:", uploadErr);
        }
      }

      try {
        const res = await fetch('/api/operations/kanban/tasks', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            title,
            body,
            column,
            priority,
            team_id: teamId,
            assignee,
            model_override: model,
            decompose
          })
        });
        const data = await res.json();
        if (res.ok && data.status === 'success') {
          closeNewTaskModal();
          removeOpsTaskAttachment();
          document.getElementById('ops-new-task-form')?.reset();
          if (typeof showArchonToast === 'function') {
            showArchonToast(`Aufgabe '${title}' angelegt (${data.task_id}).`, 'success');
          }
          await loadOperationsData();
        } else {
          alert(`Fehler beim Erstellen der Aufgabe: ${data.detail || data.message || 'Unbekannt'}`);
        }
      } catch (err) {
        console.error("Task creation error:", err);
        alert(`Verbindungsfehler: ${err.message}`);
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = `<i data-lucide="check" class="w-3.5 h-3.5"></i><span>Aufgabe erstellen</span>`;
          if (window.lucide) lucide.createIcons();
        }
      }
    }

    async function openTaskDetailModal(taskId) {
      currentOpsDetailTaskId = taskId;
      const modal = document.getElementById('ops-detail-modal');
      if (!modal) return;
      modal.classList.remove('hidden');

      const badgeId = document.getElementById('ops-detail-badge-id');
      const titleEl = document.getElementById('ops-detail-title');
      const statusSelect = document.getElementById('ops-detail-status-select');
      const bodyEl = document.getElementById('ops-detail-body');
      const nameEl = document.getElementById('ops-detail-assignee-name');
      const avatarEl = document.getElementById('ops-detail-assignee-avatar');
      const modelTag = document.getElementById('ops-detail-model-tag');
      const commentsList = document.getElementById('ops-detail-comments-list');
      const eventsList = document.getElementById('ops-detail-events-list');
      const subtasksSection = document.getElementById('ops-detail-subtasks-section');
      const subtasksList = document.getElementById('ops-detail-subtasks-list');
      const subtasksCount = document.getElementById('ops-detail-subtasks-count');

      if (badgeId) badgeId.textContent = taskId;
      if (titleEl) titleEl.textContent = 'Lade Details...';

      try {
        const res = await fetch(`/api/operations/kanban/tasks/${taskId}`);
        if (!res.ok) throw new Error('Task konnte nicht geladen werden');
        const data = await res.json();
        const task = data.task;

        if (titleEl) titleEl.textContent = task.title;
        if (statusSelect) statusSelect.value = (task.status || 'todo').toLowerCase();
        if (bodyEl) bodyEl.textContent = task.body || 'Keine Beschreibung hinterlegt.';
        // ERGEBNIS direkt im Dialog anzeigen (User-Wunsch 11.10.2026):
        // vorher nur body + wer/wann - das Ergebnis war nur per Suche zu finden.
        const resultSection = document.getElementById('ops-detail-result-section');
        const resultText = document.getElementById('ops-detail-result-text');
        const resultVal = (task.result || '').trim();
        const resultLabel = document.getElementById('ops-detail-result-label');
        const resultPath = document.getElementById('ops-detail-result-path');
        if (resultPath) { resultPath.classList.add('hidden'); resultPath.textContent = ''; }
        // PROJEKT-BRUECKE (Option A, 11.10.2026): toten workspace_path (scratch,
        // nie angelegt) nicht mehr zeigen - stattdessen Sidecar 'obsidian' mit
        // Dateiliste + Direkt-Leser der Projektdateien ueber die API.
        const projSection = document.getElementById('ops-detail-project-section');
        const projLabel = document.getElementById('ops-detail-project-label');
        const projFilesEl = document.getElementById('ops-detail-project-files');
        const projViewer = document.getElementById('ops-detail-project-viewer');
        const projBtn = document.getElementById('ops-detail-project-open');
        if (projSection && projLabel && projBtn) {
          if (task.obsidian) {
            projSection.classList.remove('hidden');
            projLabel.textContent = '📁 Projekt: ' + task.obsidian;
            projFilesEl.classList.add('hidden'); projViewer.classList.add('hidden');
            projFilesEl.innerHTML = ''; projViewer.classList.add('hidden');
            const afpJ = async (u) => {
              const r = await fetch(u, { signal: AbortSignal.timeout(9000) });
              if (!r.ok) { let d = ''; try { d = (await r.json()).detail || ''; } catch (e) {}
                throw new Error('HTTP ' + r.status + (d ? ' – ' + d : '')); }
              return r.json();
            };
            const projListBtn = document.getElementById('ops-detail-project-list');
            const zeigeHauptdok = async () => {
              projBtn.disabled = true; projBtn.textContent = 'Lädt…';
              try {
                const d = await afpJ(`/api/operations/kanban/projects/${encodeURIComponent(task.id)}`);
                const ziel = (d.files || []).find(f => f.path.startsWith('03_Endprodukte/'))
                          || (d.files || []).find(f => f.path === 'PROJEKT.md')
                          || (d.files || [])[0];
                if (!ziel) throw new Error('Keine Datei im Projekt.');
                const fd = await afpJ(`/api/operations/kanban/projects/${encodeURIComponent(task.id)}/file?path=${encodeURIComponent(ziel.path)}`);
                projViewer.classList.remove('hidden');
                projViewer.textContent = `── ${d.relative}/${ziel.path} ──\n\n${fd.content}`;
              } catch (e) {
                projViewer.classList.remove('hidden');
                projViewer.textContent = 'Fehler beim Laden: ' + e;
              } finally { projBtn.disabled = false; projBtn.textContent = '📁 Hauptdokument öffnen'; }
            };
            projBtn.onclick = zeigeHauptdok;
            if (projListBtn) projListBtn.onclick = async () => {
              projListBtn.disabled = true; projListBtn.textContent = 'Lädt…';
              try {
                const d = await afpJ(`/api/operations/kanban/projects/${encodeURIComponent(task.id)}`);
                projFilesEl.classList.remove('hidden');
                projFilesEl.innerHTML = (d.files || []).map(f => `
                  <button type="button" class="block w-full text-left px-1.5 py-0.5 rounded hover:bg-[var(--card)] transition cursor-pointer"
                    data-fpath="${opsEscapeHtml(f.path)}">
                    <span class="text-muted-custom">${opsEscapeHtml(f.dir ? f.dir + '/' : '')}</span><span class="text-primary-custom font-semibold">${opsEscapeHtml(f.name)}</span>
                    <span class="text-muted-custom"> · ${f.size}B</span>
                  </button>`).join('') || '<span class="text-muted-custom">Leerer Ordner.</span>';
                projFilesEl.querySelectorAll('button[data-fpath]').forEach(b => {
                  b.onclick = async () => {
                    try {
                      const fd = await afpJ(`/api/operations/kanban/projects/${encodeURIComponent(task.id)}/file?path=${encodeURIComponent(b.dataset.fpath)}`);
                      projViewer.classList.remove('hidden');
                      projViewer.textContent = `── ${fd.path} ──\n\n${fd.content}`;
                    } catch (e) { projViewer.classList.remove('hidden'); projViewer.textContent = 'Fehler: ' + e; }
                  };
                });
              } catch (e) {
                projFilesEl.classList.remove('hidden');
                projFilesEl.innerHTML = '<span class="text-rose-500">Fehler: ' + opsEscapeHtml(String(e)) + '</span>';
              } finally { projListBtn.disabled = false; projListBtn.textContent = 'Alle Dateien'; }
            };

          } else { projSection.classList.add('hidden'); }
        }
        // 2b (12.10.2026): Entscheidungs-Panel — Typ, Status, Kurzfassung, Bericht-Reader
        // und Freigeben/Ablehnen ueber den ZENTRALEN Entscheidungs-Endpoint (derselbe
        // Schreibpfad wie Telegram, damit auch die Folgeaktion wirklich laeuft).
        const decSection = document.getElementById('ops-detail-decision-section');
        if (decSection) {
          const dec = task.decision || null;
          if (!dec) {
            decSection.classList.add('hidden');
          } else {
            decSection.classList.remove('hidden');
            const _dj = async (u) => {
              const r = await fetch(u, { signal: AbortSignal.timeout(12000) });
              if (!r.ok) { let d = ''; try { d = (await r.json()).detail || ''; } catch (e) {} throw new Error('HTTP ' + r.status + (d ? ' – ' + d : '')); }
              return r.json();
            };
            const decStatusEl = document.getElementById('ops-detail-decision-status');
            const decMetaEl = document.getElementById('ops-detail-decision-meta');
            const decKurzEl = document.getElementById('ops-detail-decision-kurz');
            const decReader = document.getElementById('ops-detail-decision-reader');
            const decReadBtn = document.getElementById('ops-detail-decision-read');
            const decOkBtn = document.getElementById('ops-detail-decision-approve');
            const decNoBtn = document.getElementById('ops-detail-decision-reject');
            const decTypName = { delegation_review: 'Delegation prüfen', synthesis_freigabe: 'Synthese freigeben',
                                 mission_freigabe: 'Mission freigeben', permission_gate: 'Rechte freigeben' };
            const decOffen = (dec.status || 'offen') === 'offen';
            if (decStatusEl) {
              const st = dec.status || 'offen';
              decStatusEl.textContent = st === 'offen' ? '⏳ offen' : (st === 'freigegeben' ? '✅ freigegeben' : '⛔ ' + st);
            }
            if (decMetaEl) {
              const teile = ['Typ: ' + (decTypName[dec.typ] || dec.typ || '?')];
              if (dec.ref_id) teile.push('Ref: ' + dec.ref_id);
              if (dec.entschieden_von) teile.push('Entschieden von: ' + dec.entschieden_von);
              if (dec.entschieden_am) teile.push(String(dec.entschieden_am).replace('T', ' ').slice(0, 16));
              decMetaEl.textContent = teile.join('  ·  ');
            }
            if (decKurzEl) decKurzEl.textContent = dec.kurzfassung || '(keine Kurzfassung hinterlegt)';
            if (decReader) { decReader.classList.add('hidden'); decReader.innerHTML = ''; }
            [decOkBtn, decNoBtn].forEach(b => { if (b) { b.disabled = !decOffen; b.style.opacity = decOffen ? '1' : '.45'; } });
            const entscheiden = async (decision) => {
              if (!decOffen) return;
              if (!confirm(decision === 'approve' ? 'Diese Entscheidung wirklich FREIGEBEN?' : 'Diese Entscheidung wirklich ABLEHNEN?')) return;
              try {
                const r = await fetch('/api/decisions/decide', {
                  method: 'POST', headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ task_id: task.id, decision, von: 'kanban' }),
                  signal: AbortSignal.timeout(40000)
                });
                const d = await r.json().catch(() => ({}));
                if (r.ok) {
                  if (typeof showArchonToast === 'function') showArchonToast(`Entscheidung ${decision === 'approve' ? 'freigegeben' : 'abgelehnt'}.`, 'success');
                  if (typeof loadOperationsData === 'function') await loadOperationsData();
                  await openTaskDetailModal(task.id);
                } else if (typeof showArchonToast === 'function') {
                  showArchonToast('Fehler: ' + (d.detail || r.status), 'error');
                }
              } catch (e) {
                if (typeof showArchonToast === 'function') showArchonToast('Fehler: ' + e, 'error');
              }
            };
            if (decOkBtn) decOkBtn.onclick = () => entscheiden('approve');
            if (decNoBtn) decNoBtn.onclick = () => entscheiden('reject');
            if (decReadBtn && decReader) decReadBtn.onclick = async () => {
              if (!decReader.classList.contains('hidden')) { decReader.classList.add('hidden'); return; }
              decReader.classList.remove('hidden');
              decReader.className = 'mt-2.5 p-3 rounded-lg border border-[var(--border)] bg-[var(--background)] text-xs font-mono text-muted-custom';
              decReader.textContent = 'Lädt…';
              const datei = (dec.dossier || '').split('/').pop();
              if (!datei) { decReader.textContent = 'Kein Bericht hinterlegt.'; return; }
              try {
                const rel = '01_Zwischenberichte/' + datei;
                const fd = await _dj(`/api/operations/kanban/projects/${encodeURIComponent(task.id)}/file?path=${encodeURIComponent(rel)}`);
                if (/\.html?$/i.test(datei)) {
                  // .html-Dossier RENDERN statt Rohtext auswerfen
                  decReader.className = 'mt-2.5 h-80 w-full overflow-hidden rounded-lg border border-[var(--border)] bg-white';
                  decReader.innerHTML = '';
                  const fr = document.createElement('iframe');
                  fr.setAttribute('sandbox', '');
                  fr.setAttribute('title', 'Zwischenbericht');
                  fr.className = 'w-full h-full border-0 bg-white';
                  fr.srcdoc = fd.content || '';
                  decReader.appendChild(fr);
                } else {
                  decReader.className = 'mt-2.5 max-h-80 overflow-auto p-3 rounded-lg border border-[var(--border)] bg-[var(--background)] text-[11.5px] leading-relaxed whitespace-pre-wrap font-mono text-primary-custom';
                  decReader.textContent = fd.content || '(leer)';
                }
              } catch (e) {
                decReader.className = 'mt-2.5 p-3 rounded-lg border border-rose-500/40 bg-rose-500/5 text-xs font-mono text-rose-600';
                decReader.textContent = 'Bericht nicht lesbar: ' + e;
              }
            };
          }
        }
        if (resultSection && resultText) {
          const zeige = (txt, quelle) => {
            resultText.textContent = txt;
            if (resultLabel) resultLabel.textContent = quelle;
            resultSection.classList.remove('hidden');
          };
          const verstecke = () => { resultSection.classList.add('hidden'); resultText.textContent = ''; };
          if (resultVal) {
            zeige(resultVal, '📄 Ergebnis / Deliverable');
          } else {
            // Befund 11.10.: die Engine befuellt tasks.result UND session_id NIE -
            // das Ergebnis steht in der zugehoerigen mc-Chat-Session. Bruecke:
            // 1) direkte session_id, sonst 2) Session suchen ueber
            // Titel-Prefix + Agenten-Suffix in der Session-ID.
            verstecke();
            const lade = (sid) =>
              fetch(`/api/chat/sessions/${encodeURIComponent(sid)}/messages`, { signal: AbortSignal.timeout(8000) })
                .then(r => (r.ok ? r.json() : null));
            const zeigeAntw = (d) => {
              if (!d) return;
              const msgs = (d.messages) || [];
              const antw = [...msgs].reverse().find(m => m.role === 'assistant' && m.content && String(m.content).trim());
              if (antw) zeige(String(antw.content).trim(), '📄 Ergebnis (aus zugehöriger Chat-Session)');
            };
            const sucheSession = () =>
              fetch('/api/chat/sessions?limit=65', { signal: AbortSignal.timeout(8000) })
                .then(r => (r.ok ? r.json() : null))
                .then(d => {
                  const ss = Array.isArray(d) ? d : ((d && (d.sessions || d.items)) || []);
                  const hit = ss.find(s => {
                    const id = s.id || '', t = s.title || '';
                    if (task.assignee && !id.endsWith('_' + task.assignee)) return false;
                    return !!(t && task.title && (task.title.startsWith(t) || t.startsWith(task.title.slice(0, 30))));
                  });
                  return hit ? lade(hit.id) : null;
                });
            (task.session_id ? lade(task.session_id) : sucheSession())
              .then(zeigeAntw)
              .catch(() => {});
          }
        }
        if (nameEl) nameEl.textContent = task.assignee_name || task.assignee || 'Nicht zugewiesen';
        if (avatarEl) avatarEl.src = task.assignee_avatar || '/static/avatars/avatar_001.jpg';
        if (modelTag) modelTag.textContent = task.model_override ? task.model_override.split('/').pop() : 'OmniRoute Auto';
        populateOpsDetailMeta(taskId);

        const subtasks = data.subtasks || [];
        if (subtasks.length > 0) {
          if (subtasksSection) subtasksSection.classList.remove('hidden');
          if (subtasksCount) subtasksCount.textContent = subtasks.length;
          if (subtasksList) {
            subtasksList.innerHTML = subtasks.map(st => `
              <div class="flex items-center justify-between p-2 rounded-lg bg-[var(--card)] border border-[var(--border)] text-xs">
                <span class="font-medium text-primary-custom">${opsEscapeHtml(st.title)}</span>
                <span class="font-mono text-[10px] text-muted-custom">${st.child_id}</span>
              </div>
            `).join('');
          }
        } else {
          if (subtasksSection) subtasksSection.classList.add('hidden');
        }

        const events = data.events || [];
        if (eventsList) {
          if (events.length > 0) {
            eventsList.innerHTML = events.map(ev => `
              <div class="flex items-center justify-between p-1.5 border-b border-[var(--border)]/50 last:border-0">
                <span class="text-indigo-400 font-bold uppercase">${opsEscapeHtml(ev.kind)}</span>
                <span class="text-muted-custom text-[10px]">${ev.created_at ? new Date(ev.created_at).toLocaleTimeString('de-DE') : ''}</span>
              </div>
            `).join('');
          } else {
            eventsList.innerHTML = '<span class="text-muted-custom">Keine Events aufgezeichnet.</span>';
          }
        }

        const comments = data.comments || [];
        if (commentsList) {
          if (comments.length > 0) {
            commentsList.innerHTML = comments.map(c => `
              <div class="p-2.5 rounded-xl border border-[var(--border)] bg-[var(--card)] text-xs space-y-1">
                <div class="flex items-center justify-between text-[10px] text-muted-custom font-mono">
                  <span class="font-bold text-primary-custom">${opsEscapeHtml(c.author)}</span>
                  <span>${c.created_at ? new Date(c.created_at).toLocaleTimeString('de-DE') : ''}</span>
                </div>
                <p class="text-primary-custom leading-relaxed">${opsEscapeHtml(c.body)}</p>
              </div>
            `).join('');
          } else {
            commentsList.innerHTML = '<p class="text-xs text-muted-custom italic p-2">Noch keine Kommentare hinterlegt.</p>';
          }
        }
      } catch (err) {
        console.error("Detail load error:", err);
      }
      if (window.lucide) lucide.createIcons();
    }

    function closeTaskDetailModal() {
      const modal = document.getElementById('ops-detail-modal');
      if (modal) modal.classList.add('hidden');
      currentOpsDetailTaskId = null;
    }

    async function updateCurrentTaskStatus(newStatus) {
      if (!currentOpsDetailTaskId) return;
      try {
        // 2b/2c (12.10.2026): Entscheidungs-Tasks NICHT direkt verschieben — sonst
        // aendert sich nur der Status, die Folgeaktion (Synthese-Finalisierung,
        // Gate-Ausfuehrung, Missions-Start) laeuft aber NICHT. Darum ueber den
        // zentralen Entscheidungs-Endpoint: derselbe Schreibpfad wie Telegram.
        let dec = null;
        try {
          const rd = await fetch(`/api/operations/kanban/tasks/${currentOpsDetailTaskId}`, { signal: AbortSignal.timeout(10000) });
          if (rd.ok) { const dd = await rd.json(); dec = (dd.task || dd).decision || null; }
        } catch (e) {}
        if (dec && (dec.status || 'offen') === 'offen') {
          const aufloesend = { todo: 'approve', in_progress: 'approve', done: 'approve', archived: 'reject' };
          const dec2 = aufloesend[String(newStatus).toLowerCase()];
          if (dec2) {
            const r2 = await fetch('/api/decisions/decide', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ task_id: currentOpsDetailTaskId, decision: dec2, von: 'kanban' }),
              signal: AbortSignal.timeout(40000)
            });
            const d2 = await r2.json().catch(() => ({}));
            if (r2.ok) {
              if (typeof showArchonToast === 'function') {
                showArchonToast(`Entscheidung ${dec2 === 'approve' ? 'freigegeben' : 'abgelehnt'} — Kanban: ${d2.kanban_status || newStatus}`, 'success');
              }
              await loadOperationsData();
              await openTaskDetailModal(currentOpsDetailTaskId);
            } else if (typeof showArchonToast === 'function') {
              showArchonToast('Fehler: ' + (d2.detail || r2.status), 'error');
            }
            return;
          }
        }
        const res = await fetch(`/api/operations/kanban/tasks/${currentOpsDetailTaskId}/status`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ status: newStatus })
        });
        if (res.ok) {
          if (typeof showArchonToast === 'function') {
            showArchonToast(`Status auf '${newStatus}' aktualisiert.`, 'success');
          }
          await loadOperationsData();
        }
      } catch (err) {
        console.error("Status update error:", err);
      }
    }

    async function submitTaskDetailComment() {
      if (!currentOpsDetailTaskId) return;
      const input = document.getElementById('ops-detail-new-comment-input');
      const body = input ? input.value.trim() : '';
      if (!body) return;

      try {
        const res = await fetch(`/api/operations/kanban/tasks/${currentOpsDetailTaskId}/comments`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            author: 'Master Architect',
            body: body
          })
        });
        if (res.ok) {
          if (input) input.value = '';
          await openTaskDetailModal(currentOpsDetailTaskId);
          await loadOperationsData();
        }
      } catch (err) {
        console.error("Comment submit error:", err);
      }
    }
    window.archiveKanbanTask = async function(e, taskId) {
      e.stopPropagation();
      if (!confirm("Task " + taskId + " wirklich ins Archiv verschieben?")) return;
      try {
        const res = await fetch('/api/operations/kanban/tasks/' + taskId + '/status', {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ status: 'archived' })
        });
        if (res.ok) {
          if (typeof showArchonToast === 'function') showArchonToast('Task ' + taskId + ' archiviert.', 'success');
          loadOperationsData(false);
        }
      } catch (err) {
        console.error("Archive error:", err);
      }
    };


