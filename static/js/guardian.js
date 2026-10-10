// ============================================================================
// GUARDIAN & TOKEN ANALYTICS — eigenständiges Modul
// Konsolidiert am 09.10.2026 aus css_live_studio.js und index.html.
// Alle Guardian-/Token-Guard-Funktionen und Caches leben hier.
// ============================================================================

    // ═════════════════════════════════════════════════════════════════════════
    // GUARDIAN & ANALYTICS CLIENT LOGIC
    // ═════════════════════════════════════════════════════════════════════════
    let guardianProfilesCache = [];
    let guardianPluginsCache = [];
    let guardianCurrentTimeframe = "all";
    let guardianCurrentCategory = "ALL";
    let guardianChartInstance = null;
    function setGuardianTimeframe(tf) {
      guardianCurrentTimeframe = tf;
      ['24h', '7d', '30d', 'all'].forEach(t => {
        const btn = document.getElementById(`guard-tf-btn-${t}`);
        if (!btn) return;
        if (t === tf) {
          btn.className = "py-1 px-2.5 rounded-lg bg-[var(--card)] text-[var(--foreground)] border border-[var(--border)] shadow-xs font-bold cursor-pointer";
        } else {
          btn.className = "py-1 px-2.5 rounded-lg text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition font-bold cursor-pointer";
        }
      });
      const labelMap = { '24h': '24 Std.', '7d': '7 Tage', '30d': '30 Tage', 'all': 'Gesamt' };
      const elLabel = document.getElementById("guard-kpi-tf-label");
      if (elLabel) elLabel.innerText = labelMap[tf] || tf;
      loadGuardianData();
    }
    async function loadGuardianData(isManual = false) {
      const refreshIcon = document.getElementById("guard-refresh-icon");
      if (refreshIcon && isManual) {
        refreshIcon.classList.add("animate-spin");
      }
      try {
        const [statsRes, cfgRes] = await Promise.all([
          fetch(`/api/guardian/stats?timeframe=${guardianCurrentTimeframe}`),
          fetch('/api/guardian/config')
        ]);
        
        const stats = await statsRes.json();
        const cfg = await cfgRes.json();
        
        if (stats.status === "success") {
          document.getElementById("guard-kpi-tokens").innerText = (stats.grand_total_tokens || 0).toLocaleString();
          document.getElementById("guard-kpi-calls").innerText = `${(stats.grand_total_calls || 0).toLocaleString()} Calls`;
          document.getElementById("guard-kpi-cost").innerText = `$${(stats.grand_total_cost || 0).toFixed(2)}`;
          
          if (stats.profiles && stats.profiles.length > 0) {
            const topP = stats.profiles[0];
            document.getElementById("guard-kpi-top-profile").innerText = topP.profile;
            document.getElementById("guard-kpi-top-tokens").innerText = `${(topP.total_tokens || 0).toLocaleString()} Tokens`;
          } else {
            document.getElementById("guard-kpi-top-profile").innerText = "Keine Daten";
            document.getElementById("guard-kpi-top-tokens").innerText = "0 Tokens";
          }
          
          // Ungenutzte Zeit / Inaktivitätsanzeige
          const localTime = new Date().toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
          const elIdleBadge = document.getElementById("guard-idle-badge");
          if (elIdleBadge) elIdleBadge.innerText = stats.idle_str || "--";
          const elCheckedBadge = document.getElementById("guard-checked-badge");
          if (elCheckedBadge) elCheckedBadge.innerText = `Stand: ${localTime}`;
          const elKpiIdle = document.getElementById("guard-kpi-idle");
          if (elKpiIdle) elKpiIdle.innerText = `Inaktiv: ${stats.idle_str || "--"}`;
          
          if (isManual && typeof showNotification === "function") {
            showNotification(
              "Token Guard",
              `Aktualisiert um ${localTime}: Keine Token verbraucht seit ${stats.idle_str || "--"}.`,
              "info"
            );
          }
          
          guardianProfilesCache = stats.profiles || [];
          guardianSessionsCache = stats.sessions || [];
          
          const sessionsBadge = document.getElementById("guard-sessions-badge");
          if (sessionsBadge) sessionsBadge.innerText = guardianSessionsCache.length;
          renderGuardianProfiles(guardianProfilesCache);
          renderGuardianModels(stats.models || []);
          renderGuardianTrendChart(stats.trend || []);
          if (guardianCurrentSubTab === "sessions") {
            renderGuardianSessions(guardianSessionsCache);
          }
        }
        if (cfg.status === "success") {
          const budget = cfg.budget || {};
          const limits = cfg.limits || {};
          const plugins = cfg.plugins || [];
          guardianPluginsCache = plugins;
          
          document.getElementById("guard-kpi-daily-budget").innerText = `$${(budget.daily_budget || 2.0).toFixed(2)}`;
          const activePluginsCount = plugins.filter(p => p.enabled).length;
          document.getElementById("guard-kpi-plugins-count").innerText = `${activePluginsCount} / ${plugins.length}`;
          const badgeEl = document.getElementById("guard-plugin-total-badge");
          if (badgeEl) badgeEl.innerText = plugins.length;
          
          // Fill form
          const elMaxContext = document.getElementById("guard-set-max-context");
          if (elMaxContext) elMaxContext.value = limits.max_context_tokens || 32000;
          const elMaxHistory = document.getElementById("guard-set-max-history");
          if (elMaxHistory) elMaxHistory.value = limits.max_history_messages || 20;
          const elDaily = document.getElementById("guard-set-daily-budget");
          if (elDaily) elDaily.value = budget.daily_budget || 2.0;
          const elTask = document.getElementById("guard-set-task-budget");
          if (elTask) elTask.value = budget.task_budget || 0.5;
          const elSteps = document.getElementById("guard-set-max-steps");
          if (elSteps) elSteps.value = limits.max_steps_per_task || 15;
          const elTimeout = document.getElementById("guard-set-timeout");
          if (elTimeout) elTimeout.value = limits.session_timeout_seconds || 60;
          const elCacheTTL = document.getElementById("guard-set-cache-ttl");
          if (elCacheTTL) elCacheTTL.value = limits.cache_ttl_hours || 24;
          const elWatchdog = document.getElementById("guard-set-watchdog-interval");
          if (elWatchdog) elWatchdog.value = limits.watchdog_interval_seconds || 30;
          renderGuardianCategories(plugins);
          filterGuardianPlugins();
        }
        
        if (window.lucide) lucide.createIcons();
      } catch (err) {
        console.error("Fehler beim Laden der Guardian-Daten:", err);
      } finally {
        if (refreshIcon) {
          setTimeout(() => refreshIcon.classList.remove("animate-spin"), 400);
        }
      }
    }
    function renderGuardianTrendChart(trendData) {
      const canvas = document.getElementById('guardian-trend-canvas');
      if (!canvas || typeof Chart === "undefined") return;
      const labels = trendData.map(t => t.date);
      const tokenValues = trendData.map(t => Math.round(t.tokens / 1000)); // in kTokens
      const costValues = trendData.map(t => t.cost);
      if (guardianChartInstance) {
        guardianChartInstance.destroy();
      }
      const ctx = canvas.getContext('2d');
      guardianChartInstance = new Chart(ctx, {
        type: 'bar',
        data: {
          labels: labels.length ? labels : ['Keine Daten'],
          datasets: [
            {
              label: 'Tokens (kTokens)',
              data: tokenValues.length ? tokenValues : [0],
              backgroundColor: 'rgba(239, 35, 60, 0.75)',
              borderColor: '#ef233c',
              borderWidth: 1,
              borderRadius: 6,
              yAxisID: 'y'
            },
            {
              type: 'line',
              label: 'Kosten ($ USD)',
              data: costValues.length ? costValues : [0],
              borderColor: '#10b981',
              backgroundColor: 'rgba(16, 185, 129, 0.1)',
              borderWidth: 2,
              tension: 0.3,
              pointRadius: 4,
              pointBackgroundColor: '#10b981',
              yAxisID: 'y1'
            }
          ]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          interaction: {
            mode: 'index',
            intersect: false,
          },
          plugins: {
            legend: {
              position: 'top',
              labels: { font: { family: 'JetBrains Mono', size: 11 }, boxWidth: 12 }
            },
            tooltip: {
              callbacks: {
                label: function(context) {
                  if (context.dataset.yAxisID === 'y') {
                    return `Tokens: ${(context.raw * 1000).toLocaleString()}`;
                  } else {
                    return `Kosten: $${context.raw.toFixed(4)}`;
                  }
                }
              }
            }
          },
          scales: {
            x: {
              grid: { display: false },
              ticks: { font: { family: 'JetBrains Mono', size: 10 } }
            },
            y: {
              type: 'linear',
              display: true,
              position: 'left',
              title: { display: true, text: 'kTokens', font: { family: 'JetBrains Mono', size: 10 } },
              ticks: { font: { family: 'JetBrains Mono', size: 10 } },
              grid: { color: 'rgba(226, 232, 240, 0.6)' }
            },
            y1: {
              type: 'linear',
              display: true,
              position: 'right',
              title: { display: true, text: 'USD ($)', font: { family: 'JetBrains Mono', size: 10 } },
              ticks: { font: { family: 'JetBrains Mono', size: 10 } },
              grid: { drawOnChartArea: false }
            }
          }
        }
      });
    }
    function renderGuardianProfiles(profiles) {
      const tbody = document.getElementById("guard-profiles-table-body");
      if (!tbody) return;
      if (!profiles || profiles.length === 0) {
        tbody.innerHTML = `<tr><td colspan="4" class="py-6 text-center text-slate-400 italic">Keine Profile im gewählten Zeitraum</td></tr>`;
        return;
      }
      tbody.innerHTML = profiles.map(p => `
        <tr class="hover:bg-slate-50 transition">
          <td class="py-2.5 px-4 font-bold text-slate-800">
            <div class="flex items-center gap-2">
              <span class="w-2 h-2 rounded-full ${p.total_tokens > 10000000 ? 'bg-amber-500' : 'bg-emerald-500'}"></span>
              <span class="truncate max-w-[180px]" title="${p.profile}">${p.profile}</span>
            </div>
          </td>
          <td class="py-2.5 px-4 text-right text-slate-600">${(p.total_calls || 0).toLocaleString()}</td>
          <td class="py-2.5 px-4 text-right font-bold text-slate-900">${(p.total_tokens || 0).toLocaleString()}</td>
          <td class="py-2.5 px-4 text-right font-bold text-emerald-600">$${(p.total_cost || 0).toFixed(4)}</td>
        </tr>
      `).join('');
    }
    function filterGuardianProfiles(query) {
      const q = (query || "").toLowerCase();
      const filtered = guardianProfilesCache.filter(p => p.profile.toLowerCase().includes(q));
      renderGuardianProfiles(filtered);
    }
    let guardianSessionsCache = [];
    let guardianCurrentSubTab = "overview";
    function setGuardianSubTab(tab) {
      guardianCurrentSubTab = tab;
      const btnOverview = document.getElementById("guard-subtab-btn-overview");
      const btnSessions = document.getElementById("guard-subtab-btn-sessions");
      const btnConcurrency = document.getElementById("guard-subtab-btn-concurrency");
      const viewOverview = document.getElementById("guard-subview-overview");
      const viewSessions = document.getElementById("guard-subview-sessions");
      const viewConcurrency = document.getElementById("guard-subview-concurrency");

      const activeClass = "py-2.5 px-3.5 border-b-2 border-zinc-900 text-zinc-900 dark:border-zinc-100 dark:text-zinc-100 font-mono text-xs font-bold transition flex items-center gap-1.5 cursor-pointer";
      const inactiveClass = "py-2.5 px-3.5 border-b-2 border-transparent text-[var(--muted-foreground)] hover:text-[var(--foreground)] font-mono text-xs font-medium transition flex items-center gap-1.5 cursor-pointer";

      if (btnOverview) btnOverview.className = inactiveClass;
      if (btnSessions) btnSessions.className = inactiveClass;
      if (btnConcurrency) btnConcurrency.className = inactiveClass;

      if (viewOverview) viewOverview.classList.add("hidden");
      if (viewSessions) viewSessions.classList.add("hidden");
      if (viewConcurrency) viewConcurrency.classList.add("hidden");

      if (tab === "overview") {
        if (btnOverview) btnOverview.className = activeClass;
        if (viewOverview) viewOverview.classList.remove("hidden");
      } else if (tab === "sessions") {
        if (btnSessions) btnSessions.className = activeClass;
        if (viewSessions) viewSessions.classList.remove("hidden");
        renderGuardianSessions(guardianSessionsCache);
      } else if (tab === "concurrency") {
        if (btnConcurrency) btnConcurrency.className = activeClass;
        if (viewConcurrency) viewConcurrency.classList.remove("hidden");
        loadConcurrencySettings();
      }
      lucide.createIcons();
    }


    function renderGuardianModels(models) {
      const tbody = document.getElementById("guard-models-table-body");
      if (!tbody) return;
      if (!models || models.length === 0) {
        tbody.innerHTML = `<tr><td colspan="4" class="py-6 text-center text-slate-400 italic">Keine Modelldaten im gewählten Zeitraum</td></tr>`;
        return;
      }
      tbody.innerHTML = models.map(m => `
        <tr class="hover:bg-slate-50 transition">
          <td class="py-2.5 px-4 font-bold text-slate-800">
            <span class="truncate max-w-[200px] block" title="${m.model}">${m.model}</span>
          </td>
          <td class="py-2.5 px-4 text-right text-slate-600">${(m.calls || 0).toLocaleString()}</td>
          <td class="py-2.5 px-4 text-right font-bold text-slate-900">${(m.total_tokens || 0).toLocaleString()}</td>
          <td class="py-2.5 px-4 text-right font-bold text-emerald-600">$${(m.cost || 0).toFixed(4)}</td>
        </tr>
      `).join('');
    }

    function renderGuardianSessions(sessions) {
      const tbody = document.getElementById("guard-sessions-table-body");
      if (!tbody) return;
      if (!sessions || sessions.length === 0) {
        tbody.innerHTML = `<tr><td colspan="11" class="py-8 text-center text-slate-400 italic">Keine Sitzungen im gewählten Zeitraum gefunden</td></tr>`;
        return;
      }
      tbody.innerHTML = sessions.map(s => `
        <tr class="hover:bg-slate-50 transition group">
          <td class="py-2.5 px-3 text-center">
            <button 
              onclick="openSessionInMasterChat('${s.session_id}', '${s.profile}')" 
              class="w-7 h-7 rounded-lg bg-rose-50 hover:bg-rose-600 text-rose-600 hover:text-white border border-rose-200 hover:border-rose-600 transition flex items-center justify-center cursor-pointer shadow-2xs mx-auto"
              title="Session im Master Chat öffnen"
            >
              <i data-lucide="message-square" class="w-3.5 h-3.5"></i>
            </button>
          </td>
          <td class="py-2.5 px-4 font-bold text-slate-900">
            <span class="font-mono text-[11px] truncate block max-w-[160px]" title="${s.session_id}">${s.session_id}</span>
          </td>
          <td class="py-2.5 px-4 font-semibold text-slate-700">
            <span class="truncate block max-w-[130px]" title="${s.profile}">${s.profile}</span>
          </td>
          <td class="py-2.5 px-4 text-slate-600">
            <span class="truncate block max-w-[150px]" title="${s.model}">${s.model}</span>
          </td>
          <td class="py-2.5 px-4 text-right font-bold text-slate-700">${(s.calls || 0).toLocaleString()}</td>
          <td class="py-2.5 px-4 text-right text-slate-700">${(s.input_tokens || 0).toLocaleString()}</td>
          <td class="py-2.5 px-4 text-right text-slate-700">${(s.output_tokens || 0).toLocaleString()}</td>
          <td class="py-2.5 px-4 text-right text-indigo-600 font-bold">${(s.cache_tokens || 0).toLocaleString()}</td>
          <td class="py-2.5 px-4 text-right font-extrabold ${s.total_tokens > 5000000 ? 'text-rose-600' : 'text-slate-900'}">${(s.total_tokens || 0).toLocaleString()}</td>
          <td class="py-2.5 px-4 text-right font-bold text-emerald-600">$${(s.cost || 0).toFixed(4)}</td>
          <td class="py-2.5 px-4 text-right text-[11px] text-slate-500 font-mono">${s.last_seen || '-'}</td>
        </tr>
      `).join('');
      if (window.lucide) lucide.createIcons();
    }

    let guardianSessionsSortKey = "total_tokens";
    let guardianSessionsSortAsc = false;
    function sortGuardianSessions(key) {
      if (guardianSessionsSortKey === key) {
        guardianSessionsSortAsc = !guardianSessionsSortAsc;
      } else {
        guardianSessionsSortKey = key;
        // Strings standardmäßig aufsteigend (A-Z), Zahlen und Daten standardmäßig absteigend (Höchste zuerst)
        guardianSessionsSortAsc = (key === 'session_id' || key === 'profile' || key === 'model');
      }
      guardianSessionsCache.sort((a, b) => {
        let valA = a[key];
        let valB = b[key];
        // Für Zeitstempel fallback
        if (key === 'last_seen_ts') {
          valA = a.last_seen_ts || a.last_seen || 0;
          valB = b.last_seen_ts || b.last_seen || 0;
        }
        if (typeof valA === 'string') {
          return guardianSessionsSortAsc ? valA.localeCompare(valB) : valB.localeCompare(valA);
        } else {
          valA = valA || 0;
          valB = valB || 0;
          return guardianSessionsSortAsc ? (valA - valB) : (valB - valA);
        }
      });
      const currentFilter = (document.getElementById("guard-sessions-filter")?.value || "").trim();
      if (currentFilter) {
        filterGuardianSessions(currentFilter);
      } else {
        renderGuardianSessions(guardianSessionsCache);
      }
    }

    function filterGuardianSessions(query) {
      const q = (query || "").toLowerCase();
      const filtered = guardianSessionsCache.filter(s => 
        s.session_id.toLowerCase().includes(q) || 
        s.profile.toLowerCase().includes(q) || 
        s.model.toLowerCase().includes(q)
      );
      renderGuardianSessions(filtered);
    }

    async function saveGuardianSettings(e) {
      if (e) e.preventDefault();
      try {
        const payload = {
          max_context_tokens: parseInt(document.getElementById("guard-set-max-context").value) || 32000,
          max_history_messages: parseInt(document.getElementById("guard-set-max-history").value) || 20,
          daily_budget: parseFloat(document.getElementById("guard-set-daily-budget").value) || 2.0,
          task_budget: parseFloat(document.getElementById("guard-set-task-budget").value) || 0.5,
          max_steps_per_task: parseInt(document.getElementById("guard-set-max-steps").value) || 15,
          session_timeout_seconds: parseInt(document.getElementById("guard-set-timeout").value) || 60,
          cache_ttl_hours: parseInt(document.getElementById("guard-set-cache-ttl").value) || 24,
          watchdog_interval_seconds: parseInt(document.getElementById("guard-set-watchdog-interval").value) || 30
        };
        const res = await fetch('/api/guardian/config', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.status === "success") {
          const feedback = document.getElementById("guard-save-feedback");
          if (feedback) {
            feedback.classList.remove("hidden");
            setTimeout(() => feedback.classList.add("hidden"), 3000);
          }
          showNotification("Guardian", "Einstellungen erfolgreich gespeichert.", "success");
          await loadGuardianData();
        }
      } catch (err) {
        showNotification("Fehler", String(err), "error");
      }
    }

    async function clearGuardianCache() {
      if (!confirm("Möchtest du den Delegations- und Prompt-Cache wirklich leeren?")) return;
      try {
        const res = await fetch('/api/guardian/cache/clear', { method: 'POST' });
        const data = await res.json();
        showNotification("Guardian", data.message || "Cache geleert", "success");
      } catch (err) {
        showNotification("Fehler", String(err), "error");
      }
    }

