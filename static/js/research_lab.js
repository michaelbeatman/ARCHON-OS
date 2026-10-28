

    // ==========================================
    // RESEARCH LAB (SÄULE 2: KOGNITION & WISSEN)
    // ==========================================
    
    let currentResearchTab = "labor";
    const RESEARCH_HEADER_META = {
      labor: {
        title: "Research Lab · Labor",
        subtitle: "Evidenzbasierte Multi-Engine Recherche, Quellen-Triangulation & Dossier-Generierung",
        img: "/static/img/cadre_icons/research_labor.png"
      },
      dossiers: {
        title: "Research Lab · Dossier-Archiv",
        subtitle: "Gespeicherte Forschungsberichte, Evidenz-Inspektion & Obsidian-Sync",
        img: "/static/img/cadre_icons/research_dossiers.png"
      },
      quellen: {
        title: "Research Lab · Quellen & Engines",
        subtitle: "Multi-Engine Quellen (DuckDuckGo, Wikipedia, ArXiv, Perplexity, SearXNG, Tavily)",
        img: "/static/img/cadre_icons/research_quellen.png"
      }
    };

    function switchResearchSubTab(tab) {
      if (!tab) tab = "labor";
      currentResearchTab = tab;
      const tabs = ["labor", "dossiers", "quellen"];

      const meta = RESEARCH_HEADER_META[tab] || RESEARCH_HEADER_META.labor;
      const titleEl = document.getElementById("research-main-title");
      const subtitleEl = document.getElementById("research-main-subtitle");
      const headerImgEl = document.getElementById("research-main-header-img");
      if (titleEl) titleEl.textContent = meta.title;
      if (subtitleEl) subtitleEl.textContent = meta.subtitle;
      if (headerImgEl) headerImgEl.src = meta.img;

      tabs.forEach(t => {
        const btn = document.getElementById(`research-subtab-btn-${t}`);
        const view = document.getElementById(`research-subtab-${t}`);
        const iconWrap = btn ? btn.querySelector(".tile-icon-wrap") : null;
        const label = btn ? btn.querySelector(".research-tab-label") : null;

        if (t === tab) {
          if (btn) {
            btn.className = "research-header-tile active-cadre-tab flex flex-col items-center justify-between min-w-[56px] sm:min-w-[62px] h-[72px] py-1 px-0.5 bg-transparent border-0 shadow-none opacity-100 cursor-pointer select-none transition-transform hover:scale-105 duration-150";
          }
          if (iconWrap) iconWrap.classList.add("active-tile");
          if (label) {
            label.className = "research-tab-label text-[10px] font-mono tracking-tight text-center whitespace-nowrap text-red-600 font-bold leading-none";
          }
          if (view) view.classList.remove("hidden");
        } else {
          if (btn) {
            btn.className = "research-header-tile flex flex-col items-center justify-between min-w-[56px] sm:min-w-[62px] h-[72px] py-1 px-0.5 bg-transparent border-0 shadow-none opacity-80 hover:opacity-100 cursor-pointer select-none transition-transform hover:scale-105 duration-150";
          }
          if (iconWrap) iconWrap.classList.remove("active-tile");
          if (label) {
            label.className = "research-tab-label text-[10px] font-mono tracking-tight text-center whitespace-nowrap text-[var(--muted-foreground)] font-medium leading-none";
          }
          if (view) view.classList.add("hidden");
        }
      });

      if (tab === "dossiers") {
        refreshResearchHistory();
      } else if (tab === "quellen") {
        refreshResearchProviders();
      }

      if (window.lucide) window.lucide.createIcons();
    }
    window.switchResearchSubTab = switchResearchSubTab;
    function sendDossierToBoardroom(customContent) {
      const content = customContent || currentResearchDossierMarkdown;
      if (!content || !content.trim()) {
        alert("Kein Dossier geladen. Bitte führe erst eine Recherche durch oder wähle ein archiviertes Dossier aus.");
        return;
      }
      
      // 1. Wechsle zur Decision Engine
      if (typeof window.setTab === 'function') {
        window.setTab('ai-mastermind');
      }
      if (typeof window.switchMastermindSubTab === 'function') {
        window.switchMastermindSubTab('debatte');
      }
      
      // 2. Extrahiere Thema & füge Vorlage in das Task-Textfeld ein
      setTimeout(() => {
        const taskInput = document.getElementById('boardroom-task');
        if (taskInput) {
          const lines = content.split('\n').map(l => l.trim()).filter(Boolean);
          let title = "Recherche-Ergebnis";
          for (const l of lines) {
            if (l.startsWith('#')) {
              title = l.replace(/^#+\s*/, '').trim();
              break;
            }
          }
          const snippet = content.length > 1800 ? content.substring(0, 1800) + "\n\n[... vollständiges Dossier in Zentralbibliothek/Obsidian hinterlegt]" : content;
          taskInput.value = `Entscheidungsfrage auf Basis des Research-Dossiers "${title}":\n\n` + snippet;
          taskInput.focus();
        }
      }, 250);
    }
    window.sendDossierToBoardroom = sendDossierToBoardroom;


    let currentResearchProfile = "deep";
    let currentResearchDossierMarkdown = "";
    let researchHistoryList = [];
    function selectResearchProfile(prof) {
      currentResearchProfile = prof;
      const profiles = ["deep", "quick", "academic", "market"];
      profiles.forEach(p => {
        const btn = document.getElementById(`prof-btn-${p}`);
        if (!btn) return;
        btn.removeAttribute("style");
        const titleDiv = btn.querySelector(".prof-title");
        if (titleDiv) titleDiv.removeAttribute("style");
        if (p === prof) {
          btn.className = "research-prof-btn p-2 rounded text-left transition-all cursor-pointer bg-[var(--secondary)] border-2 border-[var(--foreground)]";
          if (titleDiv) titleDiv.className = "prof-title flex items-center gap-1.5 font-bold text-xs font-mono text-[var(--foreground)]";
        } else {
          btn.className = "research-prof-btn p-2 rounded text-left transition-all cursor-pointer bg-[var(--card)] border border-[var(--border)] hover:bg-[var(--secondary)]";
          if (titleDiv) titleDiv.className = "prof-title flex items-center gap-1.5 font-bold text-xs font-mono text-[var(--foreground)]";
        }
      });
      const depthInput = document.getElementById("research-input-depth");
      if (depthInput) {
        if (prof === "quick") depthInput.value = 2;
        else if (prof === "deep") depthInput.value = 4;
        else if (prof === "academic") depthInput.value = 3;
        else if (prof === "market") depthInput.value = 3;
      }
    }
    async function loadResearchLab() {
      await refreshResearchProviders();
      await refreshResearchHistory();
      await loadResearchAgentsAndModels();
    }
    
    function onResearchAgentChanged(agentVal) {
      if (!agentVal) return;
      const profiles = window.hermesProfilesData || [];
      const found = profiles.find(p => p.id === agentVal || p.name === agentVal || p.person_name === agentVal);
      if (found && found.model) {
        const modelSelect = document.getElementById("research-model-select");
        if (modelSelect) {
          let exists = Array.from(modelSelect.options).some(o => o.value === found.model);
          if (!exists) {
            const opt = document.createElement("option");
            opt.value = found.model;
            opt.textContent = typeof window.formatModelOptionWithPrice === "function"
              ? window.formatModelOptionWithPrice(found.model, found.model)
              : found.model;
            modelSelect.appendChild(opt);
          }
          modelSelect.value = found.model;
          onResearchModelChanged(found.model);
        }
      }
    }
    window.onResearchAgentChanged = onResearchAgentChanged;
    window.onResearchModelChanged = onResearchModelChanged;

    function onResearchModelChanged(val) {
      const statModel = document.getElementById("research-stat-model");
      if (statModel) statModel.innerText = val;
      const modelBadge = document.getElementById("dossier-model-badge");
      if (modelBadge && !currentResearchDossierMarkdown) {
        modelBadge.innerText = `MODELL: ${val.toUpperCase()}`;
      }
    }
    async function loadResearchAgentsAndModels() {
      // 1. Rollen / Agenten laden
      try {
        const resRoles = await fetch("/api/roles");
        if (resRoles.ok) {
          const roles = await resRoles.json();
          const select = document.getElementById("research-agent-select");
          if (select && Array.isArray(roles) && roles.length > 0) {
            const currentVal = select.value || "Lead Research Analyst";
            let html = `
              <option value="Lead Research Analyst">Lead Research Analyst</option>
              <option value="Hermes Orchestrator (Root)">Hermes Orchestrator (Root)</option>
              <option value="Red Team / Critical Challenger">Red Team Challenger</option>
              <option value="Academic & Science Scout">Academic & Science Scout</option>
              <option value="Market Intelligence Officer">Market Intelligence Officer</option>
              <optgroup label="Archon Agenten-Kader (${roles.length})">
            `;
            roles.forEach(r => {
              const name = r.name || r.id;
              const person = r.person_name ? ` (${r.person_name})` : '';
              if (!["Hermes Orchestrator (Root)", "Red Team / Critical Challenger"].includes(name)) {
                html += `<option value="${escapeHtml(name)}">${escapeHtml(name)}${escapeHtml(person)}</option>`;
              }
            });
            html += `</optgroup>`;
            select.innerHTML = html;
            select.value = currentVal;
          }
        }
      } catch (err) {
        console.warn("Konnte Agenten-Rollen nicht abrufen:", err);
      }
      // 2. Modelle laden
      try {
        const resModels = await fetch("/api/models");
        if (resModels.ok) {
          const models = await resModels.json();
          const modelSelect = document.getElementById("research-model-select");
          if (modelSelect && Array.isArray(models)) {
            const currentVal = modelSelect.value || "auto/best-reasoning";
            const known = new Set(["auto/best-reasoning", "auto/best-fast", "auto/best-free", "auto/best-coding", "omniroute/free-forever"]);
            models.forEach(m => {
              if (!known.has(m)) {
                known.add(m);
                const opt = document.createElement("option");
                opt.value = m;
                opt.innerText = `${m}`;
                modelSelect.appendChild(opt);
              }
            });
            modelSelect.value = currentVal;
          }
        }
      } catch (err) {
        console.warn("Konnte Modelle nicht abrufen:", err);
      }
      // Stat pill aktualisieren
      const modelSelect = document.getElementById("research-model-select");
      const statModel = document.getElementById("research-stat-model");
      if (modelSelect && statModel) {
        statModel.innerText = modelSelect.value;
      }
    }
    async function refreshResearchProviders() {
      try {
        const res = await fetch("/api/v1/research/providers");
        if (!res.ok) return;
        const data = await res.json();
        const activeCnt = (data.providers || []).filter(p => p.is_configured).length;
        const engEl = document.getElementById("research-stat-engines");
        if (engEl) engEl.innerText = `${activeCnt} aktiv`;
      } catch (err) {
        console.warn("Konnte Research Provider nicht abrufen:", err);
      }
    }
    async function refreshResearchHistory() {
      const listEl = document.getElementById("research-history-list");
      const statDossiers = document.getElementById("research-stat-dossiers");
      if (!listEl) return;
      try {
        const res = await fetch("/api/v1/research/history");
        if (!res.ok) return;
        const data = await res.json();
        researchHistoryList = data.dossiers || [];
        if (statDossiers) statDossiers.innerText = researchHistoryList.length;
        if (researchHistoryList.length === 0) {
          listEl.innerHTML = '<div class="text-[11px] text-muted-custom p-2 text-center italic">Noch keine Dossiers archiviert.</div>';
          return;
        }
        listEl.innerHTML = researchHistoryList.map(item => `
          <div onclick="loadResearchDossier('${item.filename}')" class="p-2 rounded-lg border theme-border bg-[var(--page-bg)] hover:border-zinc-400 dark:hover:border-zinc-600 cursor-pointer transition flex items-center justify-between group">
            <div class="min-w-0 flex-1 pr-2">
              <div class="text-xs font-semibold text-[var(--foreground)] truncate">${item.title}</div>
              <div class="text-[10px] text-[var(--muted-foreground)] font-mono">${item.modified} · ${(item.size_bytes / 1024).toFixed(1)} KB</div>
            </div>
            <i data-lucide="chevron-right" class="w-3.5 h-3.5 text-black dark:text-white shrink-0"></i>
          </div>
        `).join("");
        lucide.createIcons();
      } catch (err) {
        console.warn("Konnte Research History nicht abrufen:", err);
      }
    }
    async function startResearchMission() {
      const qInput = document.getElementById("research-input-query");
      const query = qInput ? qInput.value.trim() : "";
      if (!query) {
        alert("Bitte gib eine Forschungsfrage oder ein Thema ein.");
        return;
      }
      const engines = [];
      if (document.getElementById("engine-duckduckgo")?.checked) engines.push("duckduckgo");
      if (document.getElementById("engine-wikipedia")?.checked) engines.push("wikipedia");
      if (document.getElementById("engine-arxiv")?.checked) engines.push("arxiv");
      if (document.getElementById("engine-perplexity")?.checked) engines.push("perplexity");
      if (document.getElementById("engine-searxng")?.checked) engines.push("searxng");
      if (document.getElementById("engine-tavily")?.checked) engines.push("tavily");
      if (engines.length === 0) {
        alert("Bitte wähle mindestens eine Suchmaschine aus.");
        return;
      }
      const agentRole = document.getElementById("research-agent-select")?.value || "Lead Research Analyst";
      const model = document.getElementById("research-model-select")?.value || "auto/best-reasoning";
      const depth = parseInt(document.getElementById("research-input-depth")?.value || "3", 10);
      const reflect = !!document.getElementById("research-check-reflect")?.checked;
      const adversarial = !!document.getElementById("research-check-adversarial")?.checked;
      const exportObsidian = !!document.getElementById("research-check-obsidian")?.checked;
      const btn = document.getElementById("btn-start-research");
      const statusBox = document.getElementById("research-live-status");
      const statusText = document.getElementById("research-live-status-text");
      const emptyState = document.getElementById("dossier-empty-state");
      const textView = document.getElementById("dossier-text-view");
      if (btn) {
        btn.disabled = true;
        btn.classList.add("opacity-50", "cursor-not-allowed");
      }
      if (statusBox) statusBox.classList.remove("hidden");
      if (statusText) {
        statusText.innerText = reflect
          ? `Autonome Tiefen-Recherche mit Reflexionsschleife & Volltext-Scraper über ${engines.join(", ")} mit ${agentRole} (${model})...`
          : `Recherchiere über ${engines.join(", ")} mit ${agentRole} (${model})... Triangulation läuft.`;
      }
      if (emptyState) emptyState.classList.add("hidden");
      try {
        const res = await fetch("/api/v1/research/run", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            query,
            profile: currentResearchProfile,
            engines,
            depth,
            reflect,
            adversarial,
            export_obsidian: exportObsidian,
            model,
            agent_role: agentRole
          })
        });
        const data = await res.json();
        if (data.status === "success" || data.status === "no_evidence") {
          renderResearchDossier(data);
          if (data.status === "success") await refreshResearchHistory();
        } else {
          alert("Fehler bei der Recherche: " + (data.detail || data.message || "Unbekannter Fehler"));
        }
      } catch (err) {
        alert("Netzwerkfehler bei der Recherche: " + err.message);
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.classList.remove("opacity-50", "cursor-not-allowed");
        }
        if (statusBox) statusBox.classList.add("hidden");
      }
    }
    function renderResearchDossier(data) {
      const emptyState = document.getElementById("dossier-empty-state");
      const textView = document.getElementById("dossier-text-view");
      const agentBadge = document.getElementById("dossier-agent-badge");
      const modelBadge = document.getElementById("dossier-model-badge");
      const triBadge = document.getElementById("dossier-triangulation-badge");
      const qualBadge = document.getElementById("dossier-quality-badge");
      const srcCount = document.getElementById("dossier-sources-count");
      if (emptyState) emptyState.classList.add("hidden");
      if (textView) {
        textView.classList.remove("hidden");
        textView.innerText = data.dossier_markdown || "";
      }
      currentResearchDossierMarkdown = data.dossier_markdown || "";
      if (agentBadge) {
        agentBadge.innerText = `AGENT: ${(data.agent_role || "LEAD RESEARCHER").toUpperCase()}`;
      }
      if (modelBadge) {
        modelBadge.innerText = `MODELL: ${(data.model || "AUTO").toUpperCase()}`;
      }
      if (triBadge) {
        triBadge.innerText = `TRIANGULATION: ${data.triangulation_verdict || "ABGESCHLOSSEN"}`;
        triBadge.className = "px-2.5 py-0.5 rounded text-[10px] font-mono font-bold bg-[var(--secondary)] text-[var(--foreground)] border border-[var(--border)]";
      }
      if (qualBadge) {
        const qg = data.quality_gate || {};
        const score = qg.score ?? 8;
        const rec = qg.recommendation || "TRUST";
        qualBadge.innerText = `QUALITY GATE: ${rec} (${score}/10)`;
        qualBadge.className = "px-2.5 py-0.5 rounded text-[10px] font-mono font-bold bg-[var(--secondary)] text-[var(--foreground)] border border-[var(--border)]";
      }
      if (srcCount) {
        srcCount.innerText = `${data.total_sources || 0} Quellen · ${data.unique_domains || 0} Domains · ${data.duration_seconds || 0}s`;
      }
    }
    async function loadResearchDossier(filename) {
      try {
        const res = await fetch(`/api/v1/research/dossier/${encodeURIComponent(filename)}`);
        if (!res.ok) return;
        const data = await res.json();
        const emptyState = document.getElementById("dossier-empty-state");
        const textView = document.getElementById("dossier-text-view");
        const triBadge = document.getElementById("dossier-triangulation-badge");
        const agentBadge = document.getElementById("dossier-agent-badge");
        const modelBadge = document.getElementById("dossier-model-badge");
        if (emptyState) emptyState.classList.add("hidden");
        if (textView) {
          textView.classList.remove("hidden");
          textView.innerText = data.content;
        }
                currentResearchDossierMarkdown = data.content;
        const archiveTitle = document.getElementById("research-archive-active-title");
        const archiveContent = document.getElementById("research-archive-content-view");
        if (archiveTitle) archiveTitle.innerText = data.filename || filename;
        if (archiveContent) archiveContent.innerText = data.content;
        if (triBadge) {
          triBadge.innerText = `DOSSIER: ${data.filename}`;
          triBadge.className = "px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-slate-100 dark:bg-slate-800 text-muted-custom border theme-border";
        }
        const agentMatch = data.content ? data.content.match(/\*\*Lead-Agent:\*\*\s*(.+)/) : null;
        const modelMatch = data.content ? data.content.match(/\*\*Sprachmodell:\*\*\s*(.+)/) : null;
        if (agentBadge) {
          agentBadge.innerText = `AGENT: ${(agentMatch ? agentMatch[1].trim() : "ARCHIV").toUpperCase()}`;
        }
        if (modelBadge) {
          modelBadge.innerText = `MODELL: ${(modelMatch ? modelMatch[1].trim() : "STANDARD").toUpperCase()}`;
        }
      } catch (err) {
        console.warn("Fehler beim Laden des Dossiers:", err);
      }
    }
    function copyDossierMarkdown() {
      if (!currentResearchDossierMarkdown) {
        alert("Kein Dossier zum Kopieren vorhanden.");
        return;
      }
      navigator.clipboard.writeText(currentResearchDossierMarkdown).then(() => {
        const btn = document.getElementById("btn-copy-dossier");
        if (btn) {
          const original = btn.innerHTML;
          btn.innerHTML = '<i data-lucide="check" class="w-3.5 h-3.5 text-emerald-500"></i> Kopiert!';
          lucide.createIcons();
          setTimeout(() => { btn.innerHTML = original; lucide.createIcons(); }, 2000);
        }
      }).catch(err => {
        alert("Fehler beim Kopieren: " + err.message);
      });
    }
    function filterResearchHistoryList(term) {
      const listEl = document.getElementById("research-history-list");
      if (!listEl) return;
      const lower = (term || "").toLowerCase().trim();
      const filtered = lower
        ? researchHistoryList.filter(item => (item.title || "").toLowerCase().includes(lower) || (item.filename || "").toLowerCase().includes(lower))
        : researchHistoryList;
      if (filtered.length === 0) {
        listEl.innerHTML = '<div class="text-[11px] text-[var(--muted-foreground)] p-2 text-center italic">Keine passenden Dossiers gefunden.</div>';
        return;
      }
      listEl.innerHTML = filtered.map(item => `
        <div onclick="loadResearchDossier('${item.filename}')" class="p-2.5 rounded-xl border border-[var(--border)] bg-[var(--background)] hover:bg-[var(--secondary)] cursor-pointer transition flex items-center justify-between group shadow-2xs">
          <div class="min-w-0 flex-1 pr-2">
            <div class="text-xs font-semibold text-[var(--foreground)] truncate">${item.title}</div>
            <div class="text-[10px] text-[var(--muted-foreground)] font-mono mt-0.5">${item.modified} · ${(item.size_bytes / 1024).toFixed(1)} KB</div>
          </div>
          <i data-lucide="chevron-right" class="w-3.5 h-3.5 text-[var(--muted-foreground)] group-hover:text-red-500 shrink-0"></i>
        </div>
      `).join("");
      if (window.lucide) window.lucide.createIcons();
    }
    window.filterResearchHistoryList = filterResearchHistoryList;
