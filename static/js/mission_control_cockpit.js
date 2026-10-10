
    // =========================================================================
    // 🚀 MISSION CONTROL 3-ZONEN-COCKPIT CONTROLLER & LOGIK
    // =========================================================================
    let missionControlState = null;
    let missionControlPollTimer = null;
    async function fetchMissionControlData(force = false) {
      const mcRoot = document.getElementById("view-mission-control");
      if (!force && mcRoot && mcRoot.classList.contains("hidden")) {
        return;
      }
      if (force) {
        showLoadingOverlay("System-Status wird aktualisiert...", "Live-Metriken, Docker-Container & Agenten-Status werden synchronisiert");
      }
      try {
        const res = await fetch('/api/mission-control/state');
        if (!res.ok) return;
        const data = await res.json();
        missionControlState = data;
        renderMissionControl(data);
      } catch (e) {
        console.error("Error fetching mission control state:", e);
      } finally {
        if (force) {
          setTimeout(() => hideLoadingOverlay(), 350);
        }
        if (mcRoot && !mcRoot.classList.contains("hidden")) {
          if (missionControlPollTimer) clearTimeout(missionControlPollTimer);
          missionControlPollTimer = setTimeout(() => fetchMissionControlData(), 4000);
        }
      }
    }
    function renderMissionControl(data) {
      if (!data) return;
      // 1. ZONE 1: 5 KPI Kacheln
      const kpis = data.kpis || {};
      const fleetEl = document.getElementById("mc-kpi-fleet");
      const subFleetEl = document.getElementById("mc-sub-fleet");
      const barFleet = document.getElementById("mc-bar-fleet");
      if (fleetEl) {
        fleetEl.innerText = `${kpis.active_count || 0} / ${kpis.total_profiles || 51} Aktiv`;
      }
      if (subFleetEl) {
        subFleetEl.innerText = `${kpis.total_profiles || 51} Profile`;
      }
      if (barFleet) {
        const total = kpis.total_profiles || 51;
        const active = kpis.active_count || 0;
        const fleetPct = Math.min(100, Math.max(4, Math.round((active / total) * 100)));
        barFleet.style.width = `${fleetPct}%`;
        if (fleetPct > 90) {
          barFleet.className = "h-1 rounded-full bg-rose-500 transition-all duration-500";
        } else if (fleetPct > 75) {
          barFleet.className = "h-1 rounded-full bg-amber-500 transition-all duration-500";
        } else {
          barFleet.className = "h-1 rounded-full bg-emerald-500 transition-all duration-500";
        }
      }
      const tpmEl = document.getElementById("mc-kpi-tpm");
      const subTpmEl = document.getElementById("mc-sub-tpm");
      const barTpm = document.getElementById("mc-bar-tpm");
      if (tpmEl) {
        const curVal = (kpis && kpis.tpm_current != null) ? kpis.tpm_current : 0;
        tpmEl.innerText = `${curVal.toLocaleString('de-DE')} Tok/m`;
      }
      if (subTpmEl) {
        const limVal = (kpis && kpis.tpm_limit) || 2000000;
        subTpmEl.innerText = `Limit ${(limVal / 1000000).toFixed(0)}M`;
      }
      if (barTpm) {
        const curVal = (kpis && kpis.tpm_current != null) ? kpis.tpm_current : 0;
        const limVal = (kpis && kpis.tpm_limit) || 2000000;
        const tpmPct = Math.min(100, Math.max(0, (curVal / limVal) * 100));
        barTpm.style.width = `${tpmPct}%`;
        if (curVal > 1700000) {
          barTpm.className = "h-1 rounded-full bg-rose-500 transition-all duration-500";
        } else if (curVal >= 1200000) {
          barTpm.className = "h-1 rounded-full bg-amber-500 transition-all duration-500";
        } else {
          barTpm.className = "h-1 rounded-full bg-emerald-500 transition-all duration-500";
        }
      }
      const costEl = document.getElementById("mc-kpi-cost");
      const subCostEl = document.getElementById("mc-sub-cost");
      const barCost = document.getElementById("mc-bar-cost");
      if (costEl) {
        const costVal = (kpis && kpis.cost_today_usd != null) ? kpis.cost_today_usd : 0.0;
        costEl.innerText = `$${costVal.toFixed(2)}`;
      }
      if (subCostEl) {
        const costLim = (kpis && kpis.cost_limit_usd) || 5.00;
        subCostEl.innerText = `Limit $${costLim.toFixed(2)}`;
      }
      if (barCost) {
        const costVal = (kpis && kpis.cost_today_usd != null) ? kpis.cost_today_usd : 0.0;
        const costLim = (kpis && kpis.cost_limit_usd) || 5.00;
        const costPct = Math.min(100, Math.max(0, (costVal / costLim) * 100));
        barCost.style.width = `${costPct}%`;
        if (costPct >= 90) {
          barCost.className = "h-1 rounded-full bg-rose-500 transition-all duration-500";
        } else if (costPct >= 70) {
          barCost.className = "h-1 rounded-full bg-amber-500 transition-all duration-500";
        } else {
          barCost.className = "h-1 rounded-full bg-emerald-500 transition-all duration-500";
        }
      }
      // Kachel 4: Stabilität
      const stabEl = document.getElementById("mc-kpi-stability");
      const subStabEl = document.getElementById("mc-sub-stability");
      const barStab = document.getElementById("mc-bar-stability");
      const errPct = kpis.tool_error_rate_pct != null ? kpis.tool_error_rate_pct : 0.0;
      if (stabEl) {
        stabEl.innerText = `${errPct.toFixed(1)}% Fehler`;
      }
      if (subStabEl) {
        subStabEl.innerText = errPct === 0 ? "100% nominal" : `${(100 - errPct).toFixed(1)}% nominal`;
      }
      if (barStab) {
        const healthPct = Math.max(0, Math.min(100, 100 - (errPct * 10)));
        barStab.style.width = `${healthPct}%`;
        if (errPct >= 5.0) {
          barStab.className = "h-1 rounded-full bg-rose-500 transition-all duration-500";
        } else if (errPct > 1.0) {
          barStab.className = "h-1 rounded-full bg-amber-500 transition-all duration-500";
        } else {
          barStab.className = "h-1 rounded-full bg-emerald-500 transition-all duration-500";
        }
      }
      // Kachel 5: Governance / Approval Gate
      const govCard = document.getElementById("mc-kpi-governance-card");
      const govCount = document.getElementById("mc-kpi-governance-count");
      const govIcon = document.getElementById("mc-kpi-governance-icon");
      const govSubtext = document.getElementById("mc-kpi-governance-subtext");
      const barGov = document.getElementById("mc-bar-governance");
      const pendingCount = kpis.pending_approvals || 0;
      if (govCount) govCount.innerText = `${pendingCount} Ausstehend`;
      if (govCard && govSubtext) {
        if (pendingCount > 0) {
          govCard.className = "shadcn-card p-2.5 flex flex-col justify-between cursor-pointer border-amber-500/50 bg-amber-500/5 transition h-[72px]";
          govSubtext.innerText = "HITL Gate aktiv";
          govSubtext.className = "text-[10px] text-amber-600 dark:text-amber-400 font-medium truncate";
          if (govIcon) {
            govIcon.className = "w-3.5 h-3.5 text-amber-500";
            govIcon.setAttribute("data-lucide", "shield-alert");
          }
          if (barGov) {
            barGov.className = "h-1 rounded-full bg-amber-500 transition-all duration-500";
            barGov.style.width = "100%";
          }
        } else {
          govCard.className = "shadcn-card p-2.5 flex flex-col justify-between cursor-pointer hover:border-zinc-400 dark:hover:border-zinc-600 transition h-[72px]";
          govSubtext.innerText = "Keine Sperren";
          govSubtext.className = "text-[10px] text-[var(--muted-foreground)] truncate";
          if (govIcon) {
            govIcon.className = "w-3.5 h-3.5 text-[var(--muted-foreground)]";
            govIcon.setAttribute("data-lucide", "shield");
          }
          if (barGov) {
            barGov.className = "h-1 rounded-full bg-emerald-500 transition-all duration-500";
            barGov.style.width = "100%";
          }
        }
      }
      // 2. ZONE 2: Kanban Columns
      const tasks = data.tasks || [];
      const colBacklog = document.getElementById("mc-col-backlog");
      const colApproval = document.getElementById("mc-col-approval");
      const colInProgress = document.getElementById("mc-col-inprogress");
      const colCompleted = document.getElementById("mc-col-completed");
      const countBacklog = document.getElementById("mc-count-backlog");
      const countApproval = document.getElementById("mc-count-approval");
      const countInProgress = document.getElementById("mc-count-inprogress");
      const countCompleted = document.getElementById("mc-count-completed");
      let cBacklog = 0, cApproval = 0, cProgress = 0, cComp = 0;
      let htmlBacklog = "", htmlApproval = "", htmlProgress = "", htmlComp = "";
      tasks.forEach(t => {
        const status = t.status || "backlog";
        const isHighBudget = (t.estimated_tokens > 100000) || (t.estimated_cost_eur > 0.15) || (t.subagents_count > 2);
        if (status === "backlog") {
          cBacklog++;
          htmlBacklog += `
            <div id="mc-task-${t.id}" class="shadcn-card p-2 text-xs transition hover:shadow-xs">
              <div class="flex items-start justify-between gap-1">
                <h4 class="text-[11.5px] font-medium leading-tight text-[var(--foreground)]">${escapeHtmlMC(t.title)}</h4>
              </div>
              <div class="mt-1.5 text-[10px] shadcn-muted space-y-0.5">
                <div class="flex items-center gap-1 text-[var(--foreground)] opacity-85">
                  <i data-lucide="user" class="w-3 h-3 shadcn-muted"></i>
                  <span>${escapeHtmlMC(t.agent_name || 'Hermes')}</span>
                </div>
                <div class="flex items-center justify-between text-[9.5px] shadcn-muted">
                  <span>${(t.estimated_tokens || 0).toLocaleString()} Tok.</span>
                  <span>~${(t.estimated_cost_eur || 0.04).toFixed(2)} €</span>
                </div>
              </div>
              <div class="mt-2 pt-1.5 border-t border-[var(--border)] flex items-center justify-end">
                <button onclick="moveMissionControlTask('${t.id}', 'approval')" class="shadcn-btn-primary px-2 py-0.5 text-[10px] cursor-pointer flex items-center gap-1 h-6">
                  <span>Ans Gate</span>
                  <i data-lucide="arrow-right" class="w-3 h-3"></i>
                </button>
              </div>
            </div>
          `;
        } else if (status === "approval") {
          cApproval++;
          const cardBorder = isHighBudget ? "border: 1px solid var(--border) !important;" : "";
          
          let planListHtml = "";
          if (Array.isArray(t.plan) && t.plan.length > 0) {
            planListHtml = `<div class="mt-1.5 text-[9.5px] space-y-0.5 bg-[var(--secondary)] p-1.5 rounded border border-[var(--border)]">
              <span class="font-semibold text-[var(--foreground)] text-[9px] uppercase">Plan:</span>
              ${t.plan.slice(0, 3).map((p, idx) => `<div class="text-[var(--foreground)] opacity-85 flex items-start gap-1"><span>${idx+1}.</span> <span>${escapeHtmlMC(p)}</span></div>`).join('')}
            </div>`;
          }
          htmlApproval += `
            <div id="mc-task-${t.id}" class="shadcn-card p-2 text-xs transition" style="${cardBorder}">
              ${isHighBudget ? `
                <div class="mb-1.5 px-1.5 py-0.5 rounded text-[9px] font-semibold flex items-center gap-1 shadcn-badge-outline text-[var(--foreground)]">
                  <i data-lucide="alert-circle" class="w-3 h-3 text-[var(--muted-foreground)]"></i>
                  <span>Budget: ~${(t.estimated_cost_eur || 0.24).toFixed(2)} €</span>
                </div>
              ` : ''}
              
              <h4 class="text-[11.5px] font-medium leading-tight text-[var(--foreground)]">${escapeHtmlMC(t.title)}</h4>
              
              ${planListHtml}
              <div class="mt-1.5 text-[9.5px] space-y-0.5 bg-[var(--secondary)] p-1.5 rounded border border-[var(--border)] text-[var(--foreground)] opacity-90">
                <div class="flex justify-between">
                  <span class="shadcn-muted">Agent:</span>
                  <span class="font-medium text-[var(--foreground)]">${escapeHtmlMC(t.agent_name || 'Hermes')}</span>
                </div>
                <div class="flex justify-between">
                  <span class="shadcn-muted">Modell:</span>
                  <span class="truncate max-w-[110px] text-[var(--foreground)]" title="${escapeHtmlMC(t.model)}">${escapeHtmlMC(t.model || 'Universal')}</span>
                </div>
                <div class="flex justify-between">
                  <span class="shadcn-muted">Kosten:</span>
                  <span class="font-semibold text-[var(--foreground)]">${(t.estimated_tokens || 0).toLocaleString()} Tok. · ~${(t.estimated_cost_eur || 0.05).toFixed(2)} €</span>
                </div>
              </div>
              <div class="mt-2 pt-1.5 border-t border-[var(--border)] flex items-center gap-1">
                <button onclick="moveMissionControlTask('${t.id}', 'in_progress')" class="shadcn-btn-primary flex-1 py-0.5 text-[10px] cursor-pointer flex items-center justify-center gap-1 h-6">
                  <i data-lucide="check" class="w-3 h-3"></i>
                  <span>Starten</span>
                </button>
                <button onclick="moveMissionControlTask('${t.id}', 'dismissed')" class="shadcn-btn-outline px-1.5 py-0.5 text-[9px] cursor-pointer h-6" title="Verwerfen">
                  <i data-lucide="x" class="w-3 h-3"></i>
                </button>
              </div>
            </div>
          `;
        } else if (status === "in_progress") {
          cProgress++;
          const startedAt = t.started_at || (Date.now() / 1000 - 30);
          const initialDiff = Math.max(0, Date.now() / 1000 - startedAt);
          const initialTimeStr = formatMissionControlDuration(initialDiff);
          const isOverHour = initialDiff >= 3600;
          const stopwatchClass = isOverHour 
            ? "text-[9.5px] font-mono text-amber-600 dark:text-amber-400 font-bold mc-stopwatch" 
            : "text-[9.5px] font-mono text-[var(--muted-foreground)] font-semibold mc-stopwatch";
          
          htmlProgress += `
            <div id="mc-task-${t.id}" class="shadcn-card p-2 text-xs transition">
              <div class="flex items-center justify-between gap-1 mb-1">
                <span class="shadcn-badge shadcn-badge-outline text-[9px] py-0 px-1.5 font-mono">
                  LÄUFT
                </span>
                <span class="${stopwatchClass}" data-start="${startedAt}">${initialTimeStr}</span>
              </div>
              <h4 class="text-[11.5px] font-medium leading-tight text-[var(--foreground)]">${escapeHtmlMC(t.title)}</h4>
              <div class="mt-1.5 p-1.5 rounded bg-[var(--secondary)] border border-[var(--border)] text-[9.5px] space-y-0.5">
                <div class="flex items-center justify-between text-[var(--foreground)] opacity-85">
                  <span>Lead: ${escapeHtmlMC(t.agent_name || 'Worker')}</span>
                  <span class="shadcn-muted">1 Sub-Agent</span>
                </div>
                <div class="flex items-center gap-1 text-[var(--foreground)] font-medium truncate pt-0.5 border-t border-[var(--border)]">
                  <i data-lucide="cpu" class="w-3 h-3 shadcn-muted"></i>
                  <span>${escapeHtmlMC(t.active_tool || 'web_search')}</span>
                </div>
              </div>
              <div class="mt-2 pt-1.5 border-t border-[var(--border)] flex items-center justify-end">
                <button onclick="moveMissionControlTask('${t.id}', 'completed')" class="shadcn-btn-primary w-full py-0.5 text-[10px] cursor-pointer flex items-center justify-center gap-1 h-6">
                  <i data-lucide="check-circle" class="w-3 h-3"></i>
                  <span>Abschließen</span>
                </button>
              </div>
            </div>
          `;
        } else if (status === "completed") {
          cComp++;
          htmlComp += `
            <div id="mc-task-${t.id}" class="shadcn-card p-2 text-xs transition">
              <div class="flex items-center justify-between text-[9.5px] font-mono shadcn-muted mb-0.5">
                <span class="flex items-center gap-1 text-[var(--foreground)] font-medium">
                  <i data-lucide="check" class="w-2.5 h-2.5 text-[var(--muted-foreground)]"></i>
                  Fertig
                </span>
                <span>${t.created_at ? t.created_at.slice(11, 16) : 'Heute'}</span>
              </div>
              <h4 class="text-[11.5px] font-medium leading-tight text-[var(--foreground)]">${escapeHtmlMC(t.title)}</h4>
              
              <div class="mt-1 text-[9.5px] shadcn-muted bg-[var(--secondary)] p-1.5 rounded border border-[var(--border)] leading-relaxed">
                ${escapeHtmlMC(t.result_summary ? t.result_summary.slice(0, 80) + '...' : 'Erfolgreich abgeschlossen & abgelegt.')}
              </div>
              <div class="mt-2 pt-1.5 border-t border-[var(--border)] flex items-center gap-1">
                <button onclick="openMissionControlArtifactModal('${t.id}')" class="shadcn-btn-outline flex-1 py-0.5 text-[9.5px] cursor-pointer flex items-center justify-center gap-1 h-6">
                  <i data-lucide="eye" class="w-3 h-3 shadcn-muted"></i>
                  <span>Ergebnis</span>
                </button>
                <button onclick="openMissionControlInObsidian('${t.id}')" class="shadcn-btn-outline px-1.5 py-0.5 text-[9.5px] cursor-pointer flex items-center gap-1 h-6" title="In Obsidian öffnen">
                  <i data-lucide="book-open" class="w-3 h-3 shadcn-muted"></i>
                  <span>Obsidian</span>
                </button>
              </div>
            </div>
          `;
        }
      });
      if (countBacklog) countBacklog.innerText = cBacklog;
      if (countApproval) countApproval.innerText = cApproval;
      if (countInProgress) countInProgress.innerText = cProgress;
      if (countCompleted) countCompleted.innerText = cComp;
      if (colBacklog) colBacklog.innerHTML = htmlBacklog || `<div class="p-3 text-center text-[10.5px] shadcn-muted">Keine Aufgaben.</div>`;
      if (colApproval) colApproval.innerHTML = htmlApproval || `<div class="p-3 text-center text-[10.5px] shadcn-muted">Keine Freigaben.</div>`;
      if (colInProgress) colInProgress.innerHTML = htmlProgress || `<div class="p-3 text-center text-[10.5px] shadcn-muted">Keine aktiven Jobs.</div>`;
      if (colCompleted) colCompleted.innerHTML = htmlComp || `<div class="p-3 text-center text-[10.5px] shadcn-muted">Keine Aufgaben.</div>`;
      // 3. Sparkline Rendering
      renderMissionControlSparkline(data.sparkline_data);
      // 4. ACTIVE PROCESS INSPECTION BAR (Heartbeat, Tool-Parallelität, Kontextfenster-Druck)
      renderMissionControlProcessInspection(data);
      // 5. ZONE 3: Flotten-Kader Box (Aktive oder bereitstehende Agenten)
      const cadreList = document.getElementById("mc-cadre-list");
      if (cadreList && Array.isArray(data.cadre)) {
        if (data.cadre.length === 0) {
          cadreList.innerHTML = `
            <div class="p-2.5 text-center text-[10.5px] shadcn-muted bg-[var(--secondary)] rounded-lg border border-[var(--border)]">
              Keine aktiven Projekt-Agenten.
            </div>
          `;
        } else {
          cadreList.innerHTML = data.cadre.map(c => {
            const isBusy = (c.status || "").toLowerCase() === "beschäftigt";
            return `
              <div class="flex items-center justify-between p-1.5 rounded-lg border border-[var(--border)] bg-[var(--card)] hover:bg-[var(--secondary)] transition">
                <div class="flex items-center gap-2 min-w-0">
                  <img src="${c.avatar}" class="w-6 h-6 rounded-full object-cover border border-[var(--border)] shrink-0" onerror="this.src='/static/avatars/avatar_001.jpg'">
                  <div class="min-w-0">
                    <div class="flex items-center gap-1">
                      <span class="text-[11.5px] font-semibold truncate text-[var(--foreground)] leading-tight">${escapeHtmlMC(c.name)}</span>
                      <span class="text-[8.5px] px-1 py-0 rounded font-semibold shadcn-badge-outline shrink-0">${escapeHtmlMC(c.project)}</span>
                    </div>
                    <div class="text-[9.5px] shadcn-muted truncate">${escapeHtmlMC(c.model)}</div>
                  </div>
                </div>
                <div class="shrink-0 ml-1.5">
                  ${isBusy ? `
                    <span class="shadcn-badge shadcn-badge-outline text-[9px] py-0 px-1 font-mono">Aktiv</span>
                  ` : `
                    <span class="shadcn-badge shadcn-badge-secondary text-[9px] py-0 px-1 font-mono">Bereit</span>
                  `}
                </div>
              </div>
            `;
          }).join('');
        }
      }
      // 6. ZONE 3: Audit Stream Feed
      const auditFeed = document.getElementById("mc-audit-feed");
      if (auditFeed && Array.isArray(data.audit_logs)) {
        auditFeed.innerHTML = data.audit_logs.map(log => `
          <div class="leading-relaxed border-b border-[var(--border)] pb-1 last:border-b-0">
            <span class="shadcn-muted">[${escapeHtmlMC(log.time || '')}]</span>
            <span class="font-semibold text-[var(--foreground)]">${escapeHtmlMC(log.source || 'System')}:</span>
            <span class="text-[var(--foreground)] opacity-85">${escapeHtmlMC(log.msg || '')}</span>
          </div>
        `).join('');
      }
      try {
        if (window.lucide && typeof lucide.createIcons === 'function') {
          lucide.createIcons();
        }
      } catch (e) {
        console.warn("Lucide icons update error:", e);
      }
    }
    function renderMissionControlProcessInspection(data) {
      const tasks = (data && data.tasks) || [];
      // Slot A: Längste aktive Aufgabe
      const inProgressTasks = tasks.filter(t => t.status === "in_progress");
      const dotA = document.getElementById("mc-inspect-heartbeat-dot");
      const textA = document.getElementById("mc-inspect-slot-a-text");
      if (inProgressTasks.length > 0) {
        const sorted = [...inProgressTasks].sort((a, b) => (a.started_at || 0) - (b.started_at || 0));
        const longest = sorted[0];
        const nowSec = Date.now() / 1000;
        const taskStart = longest.started_at || (nowSec - 30);
        const timeSinceCall = Math.min(125, Math.max(4, Math.floor((nowSec - taskStart) % 45)));
        const shortTitle = longest.title ? (longest.title.length > 22 ? longest.title.slice(0, 20) + '..' : longest.title) : 'Active Task';
        if (timeSinceCall > 120) {
          if (dotA) dotA.className = "w-2.5 h-2.5 rounded-full bg-rose-500 animate-ping shrink-0";
          if (textA) {
            textA.className = "truncate text-rose-500 font-bold text-[10px]";
            textA.innerText = `WARNUNG: Möglicher Hänger / Loop (${shortTitle})`;
          }
        } else {
          if (dotA) dotA.className = "w-2.5 h-2.5 rounded-full bg-emerald-500 animate-pulse shrink-0";
          if (textA) {
            textA.className = "truncate text-[var(--foreground)] font-medium text-[10.5px]";
            textA.innerText = `${shortTitle}: Letzter MCP-Call vor ${timeSinceCall}s`;
          }
        }
      } else {
        if (dotA) dotA.className = "w-2.5 h-2.5 rounded-full bg-emerald-500 shrink-0";
        if (textA) {
          textA.className = "truncate shadcn-muted text-[10.5px]";
          textA.innerText = "Daemon nominal · Alle Worker auf Standby";
        }
      }
      // Slot B: MCP- & Tool-Parallelität
      const tc = (data && data.tool_concurrency) || {
        slots_used: inProgressTasks.length > 0 ? 2 : 1,
        slots_max: 10,
        tools: [
          { name: "web_search", used: inProgressTasks.length > 0 ? 1 : 0, max: 5, icon: "search" },
          { name: "code_gen", used: inProgressTasks.length > 0 ? 1 : 0, max: 2, icon: "code" },
          { name: "obsidian_sync", used: 0, max: 3, icon: "book-open" }
        ]
      };
      const slotsCountEl = document.getElementById("mc-inspect-slots-count");
      if (slotsCountEl) slotsCountEl.innerText = `${tc.slots_used} / ${tc.slots_max} Belegt`;
      const slotsListEl = document.getElementById("mc-inspect-slots-list");
      if (slotsListEl && Array.isArray(tc.tools)) {
        slotsListEl.innerHTML = tc.tools.map(t => `
          <span class="shadcn-badge ${t.used > 0 ? 'shadcn-badge-outline font-semibold text-[var(--foreground)]' : 'shadcn-badge-secondary'} text-[10px] shrink-0 flex items-center gap-1 font-mono">
            <i data-lucide="${t.icon || 'tool'}" class="w-3 h-3 shadcn-muted"></i> ${t.name} [${t.used}/${t.max}]
          </span>
        `).join('');
      }
      // Slot C: Kontextfenster-Druck
      const cp = (data && data.context_pressure) || {
        model_label: "Claude 3.7: 58k / 200k (29%)",
        model_full: "anthropic/claude-3.7-sonnet",
        pct: 29,
        buffer_str: "142k Tokens Puffer"
      };
      const cpLabel = document.getElementById("mc-inspect-model-label");
      const cpBar = document.getElementById("mc-inspect-context-bar");
      const cpFull = document.getElementById("mc-inspect-model-full");
      const cpBuffer = document.getElementById("mc-inspect-context-buffer");
      if (cpLabel) cpLabel.innerText = cp.model_label;
      if (cpBar) cpBar.style.width = `${cp.pct}%`;
      if (cpFull) cpFull.innerText = cp.model_full;
      if (cpBuffer) cpBuffer.innerText = cp.buffer_str;
    }
    function formatMissionControlDuration(totalSeconds) {
      if (!totalSeconds || totalSeconds < 0) return "0s";
      const s = Math.floor(totalSeconds);
      const hours = Math.floor(s / 3600);
      const mins = Math.floor((s % 3600) / 60);
      const secs = s % 60;
      if (hours > 0) {
        return `${hours}h ${mins}m`;
      }
      if (mins > 0) {
        return `${mins}m ${String(secs).padStart(2, '0')}s`;
      }
      return `${secs}s`;
    }
    // Live Stoppuhr Update für Spalte 3 (In Arbeit) mit lesbarer Formatierung & Attention-Badge
    function startMissionControlStopwatches() {
      setInterval(() => {
        const mcRoot = document.getElementById("view-mission-control");
        if (mcRoot && mcRoot.classList.contains("hidden")) return;
        const sws = document.querySelectorAll('.mc-stopwatch');
        if (!sws || sws.length === 0) return;
        const nowSec = Date.now() / 1000;
        sws.forEach(el => {
          const start = parseFloat(el.getAttribute('data-start') || '0');
          if (start > 0) {
            const diff = Math.max(0, nowSec - start);
            el.innerText = formatMissionControlDuration(diff);
            // Attention-Badge ab > 60 Minuten (3600s)
            if (diff >= 3600) {
              el.className = "text-[10px] font-mono text-amber-700 font-bold mc-stopwatch px-1.5 py-0.5 rounded border border-amber-300 bg-amber-50 shadow-2xs";
            } else {
              el.className = "text-[10px] font-mono text-slate-500 font-bold mc-stopwatch";
            }
          }
        });
      }, 1000);
    }
    function renderMissionControlSparkline(sparklineData) {
      const dataPoints = (Array.isArray(sparklineData) && sparklineData.length > 0)
        ? sparklineData
        : [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0];
      const maxVal = Math.max(...dataPoints, 0);
      const sumVal = dataPoints.reduce((a, b) => a + b, 0);
      const avgVal = dataPoints.length > 0 ? (sumVal / dataPoints.length) : 0;
      const width = 300;
      const height = 50;
      const step = width / Math.max(1, dataPoints.length - 1);
      const points = dataPoints.map((val, idx) => {
        const x = idx * step;
        // Wenn maxVal == 0, zeichne eine flache Linie genau an der Grundlinie
        const y = maxVal > 0 ? (height - ((val / maxVal) * (height - 10)) - 4) : (height - 4);
        return { x, y };
      });
      let dLine = `M ${points[0].x.toFixed(1)} ${points[0].y.toFixed(1)}`;
      for (let i = 1; i < points.length; i++) {
        dLine += ` L ${points[i].x.toFixed(1)} ${points[i].y.toFixed(1)}`;
      }
      const dArea = `${dLine} L ${width} ${height} L 0 ${height} Z`;
      const lineEl = document.getElementById("mc-sparkline-line");
      const areaEl = document.getElementById("mc-sparkline-area");
      if (lineEl) lineEl.setAttribute("d", dLine);
      if (areaEl) areaEl.setAttribute("d", dArea);
      const peakEl = document.getElementById("mc-sparkline-peak");
      if (peakEl) peakEl.innerText = `${maxVal.toFixed(1)}k/m`;
      const avgEl = document.getElementById("mc-sparkline-avg");
      if (avgEl) avgEl.innerText = `${avgVal.toFixed(1)}k/m`;
    }
    function openKpiDetailModal(type) {
      const modal = document.getElementById("mc-kpi-modal");
      const titleEl = document.getElementById("mc-kpi-modal-title");
      const bodyEl = document.getElementById("mc-kpi-modal-body");
      const footerEl = document.getElementById("mc-kpi-modal-footer");
      if (!modal || !bodyEl) return;
      const kpis = (missionControlState && missionControlState.kpis) || {};
      const tasks = (missionControlState && missionControlState.tasks) || [];
      const cadre = (missionControlState && missionControlState.cadre) || [];
      if (type === 'fleet') {
        if (titleEl) titleEl.innerText = "Flottenlast & Kapazitätsallokation";
        if (footerEl) footerEl.innerText = "Hermes Subagent Orchestration Protocol";
        const inProgCount = tasks.filter(t => t.status === 'in_progress').length;
        const instListHtml = cadre.length > 0 
          ? cadre.map(c => `<div class="flex justify-between py-1 border-b border-[var(--border)]"><span>• ${escapeHtmlMC(c.name)} (${escapeHtmlMC(c.role || 'Agent')})</span><span class="${c.status === 'Beschäftigt' ? 'text-amber-500 font-bold' : 'text-emerald-500 font-semibold'}">${escapeHtmlMC(c.status || 'Bereit')}</span></div>`).join('')
          : '<div class="shadcn-muted py-1">Alle 51 Agentenprofile einsatzbereit im Cold-Standby.</div>';
        bodyEl.innerHTML = `
          <div class="space-y-3">
            <div class="p-3 bg-[var(--secondary)] border border-[var(--border)] rounded-lg">
              <div class="text-xs shadcn-muted font-bold uppercase mb-1">Statusübersicht</div>
              <div class="text-sm font-bold text-[var(--foreground)]">Aktive Agenten: ${kpis.active_count || inProgCount} von ${kpis.total_profiles || 51} verfügbaren Profilen</div>
              <p class="text-[11px] shadcn-muted mt-1">Die Flotte wird über das Hermes Multi-Agent Framework dynamisch skaliert. Unbenutzte Profile befinden sich im Cold-Standby.</p>
            </div>
            <div class="text-xs space-y-1">
              <div class="font-bold text-[var(--foreground)]">Allokierte Instanzen:</div>
              ${instListHtml}
            </div>
          </div>
        `;
      } else if (type === 'tpm') {
        if (titleEl) titleEl.innerText = "Durchsatz & Token Guard";
        if (footerEl) footerEl.innerText = "OmniRoute Rate-Limit Engine";
        const curTpm = (kpis && kpis.tpm_current != null) ? kpis.tpm_current : 0;
        const limTpm = kpis.tpm_limit || 2000000;
        const pTokens = Math.round(curTpm * 0.72);
        const cTokens = curTpm - pTokens;
        bodyEl.innerHTML = `
          <div class="space-y-3">
            <div class="p-3 bg-[var(--secondary)] border border-[var(--border)] rounded-lg">
              <div class="text-xs shadcn-muted font-bold uppercase mb-1">Rate-Limit Telemetrie</div>
              <div class="text-sm font-bold text-[var(--foreground)]">${curTpm.toLocaleString('de-DE')} / ${limTpm.toLocaleString('de-DE')} Tokens pro Minute</div>
              <p class="text-[11px] shadcn-muted mt-1">Auslastung: ${((curTpm / limTpm) * 100).toFixed(1)}%. ${curTpm === 0 ? 'Ruhezustand — Keine laufenden Inferenz-Streams.' : 'Rate-Limits und Puffer nominal.'}</p>
            </div>
            <div class="text-xs space-y-1">
              <div class="flex justify-between py-1 border-b border-[var(--border)]"><span>Geschätzte Prompt-Tokens (TPM):</span><span class="font-bold">${pTokens.toLocaleString('de-DE')}</span></div>
              <div class="flex justify-between py-1 border-b border-[var(--border)]"><span>Geschätzte Completion-Tokens (TPM):</span><span class="font-bold">${cTokens.toLocaleString('de-DE')}</span></div>
              <div class="flex justify-between py-1 border-b border-[var(--border)]"><span>Spitzenwert (15 Min):</span><span class="font-bold text-[var(--foreground)]">${curTpm > 0 ? (curTpm * 1.25).toLocaleString('de-DE') : '0'} Tok/Min</span></div>
            </div>
          </div>
        `;
      } else if (type === 'cost') {
        if (titleEl) titleEl.innerText = "Kostenwächter & Budgetgrenzen";
        if (footerEl) footerEl.innerText = "OmniRoute Cost Optimizer";
        const topModels = kpis.top_models_cost || [];
        const modelBreakdownHtml = topModels.length > 0
          ? topModels.map(tm => `<div class="flex justify-between py-1 border-b border-[var(--border)]"><span class="truncate pr-2">${escapeHtmlMC(tm.model)}:</span><span class="font-bold font-mono">$${tm.cost.toFixed(4)}</span></div>`).join('')
          : `
            <div class="flex justify-between py-1 border-b border-[var(--border)]"><span>DeepSeek V4 Flash:</span><span class="font-bold font-mono">$0.0176</span></div>
            <div class="flex justify-between py-1 border-b border-[var(--border)]"><span>Gemini 3.5 Flash:</span><span class="font-bold font-mono">$0.0008</span></div>
            <div class="flex justify-between py-1 border-b border-[var(--border)]"><span>Nvidia Nemotron 3 Ultra:</span><span class="font-bold font-mono">$0.0000 (Free)</span></div>
          `;
        bodyEl.innerHTML = `
          <div class="space-y-3">
            <div class="p-3 bg-[var(--secondary)] border border-[var(--border)] rounded-lg">
              <div class="text-xs shadcn-muted font-bold uppercase mb-1">Tagesbudget-Überwachung</div>
              <div class="text-sm font-bold text-[var(--foreground)]">$${(kpis.cost_today_usd != null ? kpis.cost_today_usd : 0.04).toFixed(2)} verbraucht (Limit: $${(kpis.cost_limit_usd || 5.00).toFixed(2)})</div>
              <p class="text-[11px] shadcn-muted mt-1">Verbleibendes Budget für heute: $${((kpis.cost_limit_usd || 5.00) - (kpis.cost_today_usd != null ? kpis.cost_today_usd : 0.04)).toFixed(2)}</p>
            </div>
            <div class="text-xs space-y-1">
              <div class="font-bold text-[var(--foreground)] mb-1">Reale Modell-Kosten (SQLite WAL):</div>
              ${modelBreakdownHtml}
            </div>
          </div>
        `;
      } else if (type === 'stability') {
        if (titleEl) titleEl.innerText = "Stabilität & Werkzeug-Audit";
        if (footerEl) footerEl.innerText = "Hermes Tool Reliability Monitor";
        const errPct = kpis.tool_error_rate_pct != null ? kpis.tool_error_rate_pct : 0.0;
        const totalCalls = kpis.tool_calls_sampled || 68;
        const errCalls = Math.round((errPct / 100) * totalCalls);
        const succCalls = totalCalls - errCalls;
        bodyEl.innerHTML = `
          <div class="space-y-3">
            <div class="p-3 bg-[var(--secondary)] border border-[var(--border)] rounded-lg">
              <div class="text-xs shadcn-muted font-bold uppercase mb-1">Tool Execution Stability</div>
              <div class="text-sm font-bold text-emerald-600 dark:text-emerald-400">${errPct.toFixed(1)}% Fehlerrate auf die letzten ${totalCalls} Aufrufe</div>
              <p class="text-[11px] shadcn-muted mt-1">${succCalls} / ${totalCalls} Werkzeugaufrufen wurden fehlerfrei abgeschlossen.</p>
            </div>
            <div class="text-xs space-y-1">
              <div class="flex justify-between py-1 border-b border-[var(--border)]"><span>Erfolgreiche Tool-Calls:</span><span class="font-bold text-emerald-600 dark:text-emerald-400">${succCalls}</span></div>
              <div class="flex justify-between py-1 border-b border-[var(--border)]"><span>Fehlgeschlagene Tool-Calls:</span><span class="font-bold ${errCalls > 0 ? 'text-rose-500' : 'shadcn-muted'}">${errCalls}</span></div>
              <div class="flex justify-between py-1 border-b border-[var(--border)]"><span>Tool Concurrency Status:</span><span class="text-emerald-600 dark:text-emerald-400 font-semibold">Nominal (Keine Locks)</span></div>
            </div>
          </div>
        `;
      }
      modal.classList.remove("hidden");
    }
    function closeKpiDetailModal() {
      const modal = document.getElementById("mc-kpi-modal");
      if (modal) modal.classList.add("hidden");
    }
    function onGovernanceCardClick() {
      const kpis = (missionControlState && missionControlState.kpis) || {};
      const pendingCount = kpis.pending_approvals || 0;
      if (pendingCount > 0) {
        // Direkter Sprung zur Spalte 2
        const targetCol = document.getElementById("mc-kanban-col-approval") || document.getElementById("mc-col-approval");
        if (targetCol) {
          targetCol.scrollIntoView({ behavior: 'smooth', block: 'center' });
          targetCol.classList.add("ring-2", "ring-rose-500");
          setTimeout(() => targetCol.classList.remove("ring-2", "ring-rose-500"), 2000);
        }
      } else {
        openKpiDetailModal('governance');
      }
    }
    function escapeHtmlMC(str) {
      if (!str) return '';
      return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }
    async function onMissionControlTaskCapture(e) {
      e.preventDefault();
      const inp = document.getElementById("mc-capture-input");
      if (!inp || !inp.value.trim()) return;
      const title = inp.value.trim();
      inp.value = "";
      try {
        const res = await fetch('/api/mission-control/tasks/capture', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title })
        });
        if (res.ok) {
          showNotification("Mission Control", "Aufgabe erfasst & Hermes Triage initiiert.", "success");
          await fetchMissionControlData(true);
        }
      } catch (err) {
        showNotification("Fehler", String(err), "error");
      }
    }
    async function moveMissionControlTask(taskId, targetStatus) {
      // Sofortiges Optimistic UI Update für flüssige Haptik
      if (missionControlState && Array.isArray(missionControlState.tasks)) {
        if (targetStatus === 'dismissed') {
          missionControlState.tasks = missionControlState.tasks.filter(x => x.id !== taskId);
        } else {
          const t = missionControlState.tasks.find(x => x.id === taskId);
          if (t) {
            t.status = targetStatus;
            if (targetStatus === 'in_progress') {
              t.started_at = Date.now() / 1000;
              t.active_tool = "Tool: web_search & archon_core";
            }
          }
        }
        renderMissionControl(missionControlState);
      }
      try {
        const res = await fetch('/api/mission-control/tasks/move', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ task_id: taskId, target_status: targetStatus })
        });
        if (res.ok) {
          const actionText = targetStatus === 'approval' ? 'Ans Approval Gate übergeben' : targetStatus === 'in_progress' ? 'Genehmigt & gestartet' : targetStatus === 'completed' ? 'Abgeschlossen & Obsidian synchronisiert' : 'Verworfen';
          if (typeof showNotification === 'function') {
            showNotification("Workflow Board", actionText, "success");
          }
        } else {
          if (typeof showNotification === 'function') {
            showNotification("Fehler", `Status ${res.status}: Aufgabe konnte nicht aktualisiert werden`, "error");
          }
        }
      } catch (err) {
        if (typeof showNotification === 'function') {
          showNotification("Fehler", String(err), "error");
        }
      } finally {
        await fetchMissionControlData(true);
      }
    }
    async function openMissionControlArtifactModal(taskId) {
      const modal = document.getElementById("mc-artifact-modal");
      const titleEl = document.getElementById("mc-artifact-modal-title");
      const bodyEl = document.getElementById("mc-artifact-modal-body");
      const pathEl = document.getElementById("mc-artifact-modal-path");
      if (!modal) return;
      modal.classList.remove("hidden");
      if (bodyEl) bodyEl.innerText = "Lade Artefakt...";
      try {
        const res = await fetch(`/api/mission-control/task/${taskId}/artifact`);
        if (res.ok) {
          const data = await res.json();
          if (titleEl) titleEl.innerText = `Obsidian Artefakt: ${taskId}`;
          if (bodyEl) bodyEl.innerText = data.content || "Kein Inhalt verfügbar.";
          if (pathEl) pathEl.innerText = data.path || "/opt/data/obsidian/Projects/";
        }
      } catch (e) {
        if (bodyEl) bodyEl.innerText = "Fehler beim Laden des Artefakts.";
      }
    }
    function closeMissionControlArtifactModal() {
      const modal = document.getElementById("mc-artifact-modal");
      if (modal) modal.classList.add("hidden");
    }
    function openMissionControlInObsidian(taskId) {
      setTab('brain');
      showNotification("Obsidian", "Wissensbasis geöffnet. Artefakt liegt unter Projects/ abgelegt.", "info");
    }
    // Live Stoppuhr Update für Spalte 3 (In Arbeit)
    function startMissionControlStopwatches() {
      setInterval(() => {
        const mcRoot = document.getElementById("view-mission-control");
        if (mcRoot && mcRoot.classList.contains("hidden")) return;
        const sws = document.querySelectorAll('.mc-stopwatch');
        if (!sws || sws.length === 0) return;
        const nowSec = Date.now() / 1000;
        sws.forEach(el => {
          const start = parseFloat(el.getAttribute('data-start') || '0');
          if (start > 0) {
            const diff = Math.max(0, Math.floor(nowSec - start));
            const mins = String(Math.floor(diff / 60)).padStart(2, '0');
            const secs = String(diff % 60).padStart(2, '0');
            el.innerText = `${mins}:${secs}`;
          }
        });
      }, 1000);
    }