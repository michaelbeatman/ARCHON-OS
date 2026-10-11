
    // ==========================================
    // NATIVE MASTER CHAT & MISSIONS-MODUS ENGINE
    // ==========================================
    let masterChatProfiles = [];
    let masterChatSessions = [];
    let currentMasterChatProfileId = "default";
    let currentMasterChatSessionId = "";
    let currentMasterChatMode = "direct"; // 'direct' | 'mission'
    let currentMasterChatProvider = "openrouter";
    let currentMasterChatModel = "meta-llama/llama-3.3-70b-instruct";
    let currentMasterChatAttachment = null;
    let isMasterChatDictating = false;
    let masterChatDictationRecognition = null;
    let isMasterChatGenerating = false;
    let masterChatInitialized = false;
    let masterChatModelPrices = {};
    let currentMasterChatAgentId = "default"; // Backward compatibility
    let currentMasterChatTab = "agents"; // 'agents' | 'group'
    // Tab-Klassifizierung & Filterlogik
    function isSessionGroupType(sess) {
      if (!sess) return false;
      if (sess.chat_type) return sess.chat_type === "group";
      const s = (sess.source || "").toLowerCase();
      const id = (sess.id || "").toLowerCase();
      const p = (sess.profile_name || "").toLowerCase();
      return s === "paperclip" || s === "boardroom" || s === "multi-agent" || s === "group" || s === "team" || id.startsWith("paperclip:") || id.startsWith("group:") || p === "boardroom" || p === "multi-agent" || p === "team";
    }
    function setMasterChatTab(tab) {
      currentMasterChatTab = tab;
      const tabAgents = document.getElementById("master-chat-tab-agents");
      const tabGroup = document.getElementById("master-chat-tab-group");
      if (tab === "agents") {
        if (tabAgents) {
          tabAgents.className = "flex-1 py-1.5 px-2 rounded-md text-xs font-semibold transition flex items-center justify-center gap-1.5 cursor-pointer bg-[var(--secondary)] border border-[var(--border)] text-[var(--foreground)]";
        }
        if (tabGroup) {
          tabGroup.className = "flex-1 py-1.5 px-2 rounded-md text-xs font-medium transition flex items-center justify-center gap-1.5 cursor-pointer text-[var(--muted-foreground)] hover:text-[var(--foreground)] hover:bg-[var(--secondary)] border border-transparent";
        }
      } else {
        if (tabAgents) {
          tabAgents.className = "flex-1 py-1.5 px-2 rounded-md text-xs font-medium transition flex items-center justify-center gap-1.5 cursor-pointer text-[var(--muted-foreground)] hover:text-[var(--foreground)] hover:bg-[var(--secondary)] border border-transparent";
        }
        if (tabGroup) {
          tabGroup.className = "flex-1 py-1.5 px-2 rounded-md text-xs font-semibold transition flex items-center justify-center gap-1.5 cursor-pointer bg-[var(--secondary)] border border-[var(--border)] text-[var(--foreground)]";
        }
      }
      const searchInput = document.getElementById("master-chat-session-search");
      filterMasterChatSessions(searchInput ? searchInput.value : "");
      // Wenn die aktive Session nicht zum gewählten Tab gehört, automatisch wechseln
      const visibleSessions = getMasterChatSessionsForCurrentTab();
      const currentBelongsToTab = visibleSessions.some(s => s && s.id === currentMasterChatSessionId);
      if (!currentBelongsToTab) {
        if (visibleSessions.length > 0) {
          selectMasterChatSession(visibleSessions[0].id);
        } else {
          currentMasterChatSessionId = null;
          renderMasterChatEmptyWelcome();
        }
      }
    }
    function updateMasterChatTabBadges() {
      let agentsCount = 0;
      let groupCount = 0;
      masterChatSessions.forEach(s => {
        if (isSessionGroupType(s)) {
          groupCount++;
        } else {
          agentsCount++;
        }
      });
      const badgeAgents = document.getElementById("master-chat-agents-count");
      const badgeGroup = document.getElementById("master-chat-group-count");
      if (badgeAgents) badgeAgents.textContent = agentsCount;
      if (badgeGroup) badgeGroup.textContent = groupCount;
    }
    function getMasterChatSessionsForCurrentTab(baseList = null) {
      const sourceList = baseList !== null ? baseList : masterChatSessions;
      return sourceList.filter(s => {
        const isGroup = isSessionGroupType(s);
        return currentMasterChatTab === "group" ? isGroup : !isGroup;
      });
    }
    // 1. Initialisierung
    let masterChatInitPromise = null;
    async function initMasterChat() {
      if (masterChatInitPromise) return masterChatInitPromise;
      masterChatInitPromise = (async () => {
        await loadMasterChatProfiles();
        await loadMasterChatSessions();
          await loadMasterChatPrices();
        masterChatInitialized = true;
      })();
      return masterChatInitPromise;
    }
    // 2. Profile aus /api/agents/profiles laden und Dropdown befüllen (51 Profile)
        async function loadMasterChatPrices() {
      try {
        const res = await fetch("/api/llm-providers/prices");
        if (res.ok) {
          const data = await res.json();
          masterChatModelPrices = data.prices || {};
          window.masterChatModelPrices = masterChatModelPrices;
        }
      } catch(e) {
        console.warn("Could not load prices", e);
      }
    }
    async function loadMasterChatProfiles() {
      try {
        const res = await fetch("/api/agents/profiles");
        if (!res.ok) throw new Error("HTTP " + res.status);
        const data = await res.json();
        masterChatProfiles = Array.isArray(data) ? data : [];
      } catch (err) {
        console.warn("[MasterChat] Fehler beim Laden der Profile:", err);
        masterChatProfiles = [];
      }
      const selectEl = document.getElementById("master-chat-profile-select");
      if (!selectEl) return;
      selectEl.innerHTML = "";
      if (masterChatProfiles.length === 0) {
        selectEl.innerHTML = `<option value="default">Hermes Orchestrator (Root)</option>`;
        return;
      }
      // Profile nach Kategorien gruppieren
      const categories = {};
      masterChatProfiles.forEach(p => {
        const cat = p.category || "Allgemein";
        if (!categories[cat]) categories[cat] = [];
        categories[cat].push(p);
      });
      Object.keys(categories).forEach(catName => {
        const optgroup = document.createElement("optgroup");
        optgroup.label = catName;
        categories[catName].forEach(p => {
          const opt = document.createElement("option");
          opt.value = p.id;
          const dispName = p.person_name ? `${p.person_name} (${p.name})` : p.name;
          opt.textContent = dispName;
          if (p.id === currentMasterChatProfileId) opt.selected = true;
          optgroup.appendChild(opt);
        });
        selectEl.appendChild(optgroup);
      });
      // Standardprofil aktivieren
      if (!currentMasterChatProfileId || !masterChatProfiles.some(p => p.id === currentMasterChatProfileId)) {
        currentMasterChatProfileId = masterChatProfiles[0].id;
        selectEl.value = currentMasterChatProfileId;
      }
      currentMasterChatAgentId = currentMasterChatProfileId;
      await onMasterChatProfileChanged(currentMasterChatProfileId);
    }
    // 3. UI für gewähltes Profil & Modell aktualisieren
    async function onMasterChatProfileChanged(profileId, targetSessionId = null) {
      if (profileId === "__group__") return;
      currentMasterChatProfileId = profileId;
      currentMasterChatAgentId = profileId;
      const selectEl = document.getElementById("master-chat-profile-select");
      if (selectEl) {
        const groupOpt = selectEl.querySelector('option[value="__group__"]');
        if (groupOpt) groupOpt.remove();
        selectEl.value = profileId;
      }
      
      const prof = (masterChatProfiles || []).find(p => p.id === profileId);
      const prov = (prof && prof.provider) || (prof && prof.model && prof.model.includes("gemini") ? "google" : "openrouter");
      const mod = (prof && prof.model && prof.model !== "free-forever") ? prof.model : null;
      currentMasterChatProvider = prov;
      const provSelect = document.getElementById("master-chat-provider-select");
      if (provSelect) provSelect.value = prov;
      await onMasterChatProviderChanged(prov, mod);
      updateMasterChatProfileUI();
      if (currentMasterChatTab !== "agents") {
        setMasterChatTab("agents");
      }

      // Falls explizit eine Session angegeben wurde
      if (targetSessionId) {
        selectMasterChatSession(targetSessionId, true);
        return;
      }

      // Profilbezogene Sessions filtern & nach Aktualität (neueste zuerst) sortieren
      const profLower = (profileId || '').toLowerCase();
      const profObj = (masterChatProfiles || []).find(p => p.id === profileId);
      const nameLower = (profObj && profObj.name || '').toLowerCase();
      const personLower = (profObj && profObj.person_name || '').toLowerCase();

      const profileSessions = (masterChatSessions || []).filter(s => {
        if (!s) return false;
        const sProf = (s.profile_name || '').toLowerCase();
        if (sProf && (sProf === profLower || (nameLower && sProf === nameLower) || (personLower && sProf === personLower))) return true;
        if (profileId === "telegram_bot" && (s.source || "").toLowerCase() === "telegram") return true;
        const sId = (s.id || '').toLowerCase();
        if (sId.startsWith('mc_') && (sId.endsWith(`_${profLower}`) || sId.includes(`_${profLower}_`))) return true;
        return false;
      });

      profileSessions.sort((a, b) => {
        const tA = Number(a.last_activity_at || a.started_at || 0);
        const tB = Number(b.last_activity_at || b.started_at || 0);
        return tB - tA;
      });

      if (profileSessions.length > 0) {
        selectMasterChatSession(profileSessions[0].id, true);
      } else {
        createNewMasterChatSession();
      }
    }
    async function onMasterChatProviderChanged(prov, preferredModel) {
      currentMasterChatProvider = prov || "openrouter";
      const modelSelect = document.getElementById("master-chat-model-select");
      if (!modelSelect) return;
      modelSelect.disabled = true;
      modelSelect.innerHTML = `<option value="">Lade...</option>`;
      const models = await loadLlmModelsForProvider(currentMasterChatProvider);
      modelSelect.disabled = false;
      populateModelDropdown(modelSelect, models, preferredModel);
      currentMasterChatModel = modelSelect.value;
      updateMasterChatProfileUI();
    }
    function onMasterChatModelChanged(model) {
      currentMasterChatModel = model;
      updateMasterChatProfileUI();
    }
    function updateMasterChatProfileUI() {
      if (currentMasterChatProfileId === "__group__") return;
      const prof = masterChatProfiles.find(p => p.id === currentMasterChatProfileId) || masterChatProfiles[0];
      if (!prof) return;
      const avatarEl = document.getElementById("master-chat-selected-avatar");
      if (avatarEl) {
        avatarEl.src = (typeof getProfileAvatarUrl === "function") ? getProfileAvatarUrl(prof) : (prof.avatar || "/static/avatars/hermes_default_avatar.png");
      }
      const costEl = document.getElementById("master-chat-model-cost");
      if (costEl && currentMasterChatModel) {
        if (currentMasterChatProvider === "openrouter" && masterChatModelPrices[currentMasterChatModel]) {
          const p = masterChatModelPrices[currentMasterChatModel];
          costEl.innerHTML = `Input: <span class="text-emerald-400">$${(p.prompt_1m||0).toFixed(2)}/1M</span> | Output: <span class="text-amber-400">$${(p.completion_1m||0).toFixed(2)}/1M</span>`;
          costEl.classList.remove("hidden");
        } else {
          costEl.classList.add("hidden");
        }
      }

      const catEl = document.getElementById("master-chat-profile-category");
      if (catEl) {
        catEl.textContent = prof.category || "Agenten-Kader";
      }
      const descEl = document.getElementById("master-chat-profile-desc");
      if (descEl) {
        descEl.textContent = prof.description || (prof.role ? `Rolle: ${prof.role}` : "Hermes Spezial-Agent");
      }
      const provSelect = document.getElementById("master-chat-provider-select");
      if (provSelect && currentMasterChatProvider) {
        provSelect.value = currentMasterChatProvider;
      }
      const modelSelect = document.getElementById("master-chat-model-select");
      if (modelSelect && currentMasterChatModel) {
        modelSelect.value = currentMasterChatModel;
      }
      // Switch visual synchronisieren
      syncMasterChatSwitchUI(currentMasterChatMode);
    }
    // 3b. Sprung zum Profil im Agenten-Kader bei Avatar-Klick
    async function jumpToAgentProfile(profileId) {
      const targetId = profileId || currentMasterChatProfileId;
      if (!targetId || targetId === "__group__") return;
      // In Tab "Agenten-Kader" wechseln
      setTab('agent-profiles');
      // Sicherstellen, dass Profile geladen sind
      if (typeof hermesProfilesData === "undefined" || !Array.isArray(hermesProfilesData) || hermesProfilesData.length === 0) {
        if (typeof loadHermesProfilesView === "function") {
          await loadHermesProfilesView(true);
        }
      }
      // Zielprofil auflösen (unterstützt id, person_name, name)
      let foundProfile = null;
      if (Array.isArray(hermesProfilesData)) {
        foundProfile = hermesProfilesData.find(p => p.id === targetId);
        if (!foundProfile) {
          const tLower = targetId.toLowerCase();
          foundProfile = hermesProfilesData.find(p => 
            (p.id && p.id.toLowerCase() === tLower) ||
            (p.person_name && p.person_name.toLowerCase() === tLower) ||
            (p.name && p.name.toLowerCase() === tLower) ||
            (p.id && p.id.toLowerCase().includes(tLower))
          );
        }
      }
      const finalId = foundProfile ? foundProfile.id : targetId;
      // Filter zurücksetzen, damit das Profil sicher in der Liste sichtbar ist
      if (typeof setProfileTabFilter === "function") {
        setProfileTabFilter('all');
      }
      activeProfileCategoryFilter = "all";
      const catDropdown = document.getElementById("profile-category-dropdown");
      if (catDropdown) catDropdown.value = "all";
      const searchInput = document.getElementById("profile-search-input");
      if (searchInput) searchInput.value = "";
      const clearBtn = document.getElementById("profile-search-input-clear");
      if (clearBtn) clearBtn.classList.add("hidden");
      // Liste neu rendern und Zielprofil im Editor auswählen
      if (typeof renderHermesProfilesList === "function") {
        renderHermesProfilesList();
      }
      if (typeof selectProfileForEditor === "function") {
        selectProfileForEditor(finalId);
      }
      // Zur Profil-Karte scrollen und mit Akzentfarbe hervorheben
      setTimeout(() => {
        const card = document.querySelector(`[data-profile-id="${finalId}"]`);
        if (card) {
          card.scrollIntoView({ behavior: "smooth", block: "center" });
          card.classList.add("ring-4", "ring-[#EF233C]/40");
          setTimeout(() => card.classList.remove("ring-4", "ring-[#EF233C]/40"), 2000);
        }
      }, 180);
    }
    // 4. Dual-Mode Umschaltung: Direkt vs. Mission Toggle Switch
    function toggleMasterChatModeSwitch() {
      const nextMode = currentMasterChatMode === "mission" ? "direct" : "mission";
      setMasterChatMode(nextMode);
    }
    function syncMasterChatSwitchUI(mode) {
      const switchTrack = document.getElementById("master-chat-mode-switch");
      const switchKnob = document.getElementById("master-chat-switch-pill");
      const labelDirect = document.getElementById("master-chat-label-direct");
      const labelMission = document.getElementById("master-chat-label-mission");
      const inputEl = document.getElementById("master-chat-input");
      if (mode === "mission") {
        if (switchTrack) switchTrack.className = "w-10 h-5 bg-zinc-900 dark:bg-zinc-100 rounded-full p-0.5 transition-colors duration-200 ease-in-out relative flex items-center";
        if (switchKnob) {
          switchKnob.style.transform = "translateX(20px)";
          switchKnob.className = "w-4 h-4 bg-white dark:bg-zinc-900 rounded-full shadow-sm transform transition-transform duration-200 ease-in-out";
        }
        if (labelDirect) labelDirect.className = "text-xs font-mono font-medium transition-colors text-[var(--muted-foreground)]";
        if (labelMission) labelMission.className = "text-xs font-mono font-bold transition-colors text-[var(--foreground)]";
        if (inputEl) inputEl.placeholder = "Missions-Auftrag formulieren (wird als Task in Operations angelegt und im Approval Gate gestoppt)...";
      } else {
        if (switchTrack) switchTrack.className = "w-10 h-5 bg-zinc-900 dark:bg-zinc-100 rounded-full p-0.5 transition-colors duration-200 ease-in-out relative flex items-center";
        if (switchKnob) {
          switchKnob.style.transform = "translateX(0px)";
          switchKnob.className = "w-4 h-4 bg-white dark:bg-zinc-900 rounded-full shadow-sm transform transition-transform duration-200 ease-in-out";
        }
        if (labelDirect) labelDirect.className = "text-xs font-mono font-bold transition-colors text-[var(--foreground)]";
        if (labelMission) labelMission.className = "text-xs font-mono font-medium transition-colors text-[var(--muted-foreground)]";
        if (inputEl) inputEl.placeholder = "Nachricht an den Agenten eingeben (Enter zum Senden, Shift+Enter für Zeilenumbruch)...";
      }
    }
    function setMasterChatMode(mode) {
      currentMasterChatMode = mode;
      syncMasterChatSwitchUI(mode);
    }
    // 5. Saubere Datumsformatierung für Sessions (verhindert 'Januar 1970')
    function formatMasterChatSessionDate(sess) {
      if (!sess) return "";
      if (sess.last_activity_at_formatted) return sess.last_activity_at_formatted;
      if (sess.started_at_formatted) return sess.started_at_formatted;
      const raw = sess.last_activity_at || sess.started_at;
      if (!raw) return "";
      let ms = raw;
      if (typeof raw === "number" || (!isNaN(raw) && !String(raw).includes("-") && !String(raw).includes("T"))) {
        const num = parseFloat(raw);
        // Unix-Timestamp in Sekunden -> Millisekunden
        ms = num < 1e11 ? num * 1000 : num;
      }
      const d = new Date(ms);
      if (isNaN(d.getTime())) return String(raw).slice(0, 16);
      return d.toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
    }
    async function promptRenameSession(sessionId, defaultTitle = "") {
      if (!sessionId) return;
      const current = defaultTitle || "";
      const newTitle = prompt("Neuen Namen für diese Chat-Sitzung eingeben:", current);
      if (!newTitle || !newTitle.trim() || newTitle.trim() === current.trim()) return;
      try {
        const res = await fetch(`/api/chat/sessions/${encodeURIComponent(sessionId)}/rename`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ title: newTitle.trim() })
        });
        if (res.ok) {
          if (typeof loadMasterChatSessions === "function") {
            await loadMasterChatSessions();
          await loadMasterChatPrices();
          }
          if (typeof updateAgentChatSessionsDropdown === "function") {
            await updateAgentChatSessionsDropdown();
          }
        } else {
          const err = await res.json().catch(() => ({}));
          alert(`Fehler beim Umbenennen: ${err.detail || "Serverfehler"}`);
        }
      } catch (e) {
        console.error("Fehler beim Umbenennen der Session:", e);
        alert("Konnte Sitzung nicht umbenennen.");
      }
    }
    // 6. Sessions laden und Sidebar rendern
    async function loadMasterChatSessions() {
      const listContainer = document.getElementById("master-chat-sessions-list");
      if (!listContainer) return;
      try {
        const res = await fetch("/api/chat/sessions");
        if (res.ok) {
          const data = await res.json();
          masterChatSessions = Array.isArray(data.sessions) ? data.sessions : [];
        }
      } catch (e) {
        console.warn("[MasterChat] Konnte Sessions nicht laden:", e);
      }
      updateMasterChatTabBadges();
      renderMasterChatSessionsSidebar();
      // Falls keine Session aktiv ist, entweder die neueste der aktuellen Tab-Kategorie wählen oder Begrüßung zeigen
      const visible = getMasterChatSessionsForCurrentTab();
      if (!currentMasterChatSessionId && visible.length > 0) {
        selectMasterChatSession(visible[0].id);
      } else if (currentMasterChatSessionId) {
        const messagesContainer = document.getElementById("master-chat-messages");
        if (messagesContainer && (!messagesContainer.children.length || messagesContainer.innerHTML.includes("Lade Nachrichtenverlauf"))) {
          selectMasterChatSession(currentMasterChatSessionId);
        }
      } else {
        createNewMasterChatSession();
      }
    }
    function renderMasterChatSessionsSidebar(filteredList = null) {
      const listContainer = document.getElementById("master-chat-sessions-list");
      if (!listContainer) return;
      updateMasterChatTabBadges();
      const tabSessions = getMasterChatSessionsForCurrentTab(filteredList);
      listContainer.innerHTML = "";
      if (tabSessions.length === 0) {
        const emptyMsg = currentMasterChatTab === "group" 
          ? "Keine Gruppen- oder Multi-Agenten-Sessions vorhanden." 
          : "Keine Agenten-Dialoge gefunden.";
        listContainer.innerHTML = `<div class="text-xs text-slate-400 p-4 text-center italic">${emptyMsg}</div>`;
        return;
      }
      tabSessions.forEach(sess => {
        const isSelected = sess.id === currentMasterChatSessionId;
        const isGroup = isSessionGroupType(sess);
        const item = document.createElement("div");
        item.onclick = () => selectMasterChatSession(sess.id);
        item.className = `group p-2.5 rounded-lg cursor-pointer transition border text-left flex flex-col gap-1.5 ${
          isSelected 
            ? "bg-[var(--secondary)] border-zinc-400 dark:border-zinc-500 text-[var(--foreground)] font-semibold shadow-xs" 
            : "bg-[var(--card)] border-[var(--border)] text-[var(--foreground)] hover:bg-[var(--secondary)] hover:border-zinc-300 dark:hover:border-zinc-700"
        }`;
        const title = sess.title || (isGroup ? "Gruppen-Task" : "Neuer Chat");
        const dateStr = formatMasterChatSessionDate(sess);
        const msgCount = sess.message_count ? `${sess.message_count} Msgs` : "0 Msgs";
        const modelStr = sess.model || sess.profile_name || (isGroup ? "Operations / Team" : "auto/best-coding");
        const costStr = sess.estimated_cost_usd ? `$${parseFloat(sess.estimated_cost_usd).toFixed(3)}` : (sess.total_tokens ? `${sess.total_tokens} Tok` : "");
        const badgeTypeHtml = isGroup
          ? `<span class="px-1.5 py-0.2 rounded text-[9px] font-mono font-medium border border-[var(--border)] bg-[var(--background)] text-[var(--foreground)] shrink-0">Gruppe</span>`
          : `<span class="px-1.5 py-0.2 rounded text-[9px] font-mono font-medium border border-[var(--border)] bg-[var(--background)] text-[var(--foreground)] shrink-0">1:1</span>`;
        const isTg = (sess.source || '').toLowerCase() === 'telegram' || sess.profile_name === 'telegram_bot' || sess.id === '20260828_131801_1284dd5a';
        const idBadge = isTg ? '#telegram' : `#${escapeHtml((sess.id || '').slice(0, 8))}`;
        item.innerHTML = `
          <!-- Zeile 1: Überschrift & Typ-Badge -->
          <div class="flex items-center justify-between gap-1.5">
            <span class="text-xs truncate ${isSelected ? 'text-[var(--foreground)] font-bold' : 'text-[var(--foreground)] font-medium'}" title="${escapeHtml(title)}">${escapeHtml(title)}</span>
            <div class="flex items-center gap-1 shrink-0">
              <button type="button" onclick="event.stopPropagation(); promptRenameSession('${sess.id}', '${escapeHtml(title).replace(/'/g, "\\'")}')" class="opacity-0 group-hover:opacity-100 hover:text-[var(--foreground)] text-[var(--muted-foreground)] p-0.5 rounded cursor-pointer transition" title="Session umbenennen">
                <i data-lucide="pencil" class="w-3 h-3"></i>
              </button>
              ${badgeTypeHtml}
            </div>
          </div>
          <!-- Zeile 2: Sprachmodell, Nachrichtenanzahl & Kontext/Kosten -->
          <div class="flex items-center gap-1.5 text-[10px] font-mono text-[var(--muted-foreground)]">
            <span class="px-1.5 py-0.2 rounded bg-[var(--background)] text-[var(--foreground)] font-medium border border-[var(--border)] truncate max-w-[120px]" title="${escapeHtml(modelStr)}">${escapeHtml(modelStr)}</span>
            <span>·</span>
            <span class="shrink-0">${msgCount}</span>
            ${costStr ? `<span>·</span><span class="font-medium shrink-0 text-[var(--foreground)]">${costStr}</span>` : ""}
          </div>
          <!-- Zeile 3: Datum & Uhrzeit -->
          <div class="flex items-center justify-between text-[10px] font-mono text-[var(--muted-foreground)] pt-1 border-t border-[var(--border)]">
            <span class="flex items-center gap-1 text-[var(--foreground)] font-medium">
              <i data-lucide="calendar" class="w-3 h-3 text-black dark:text-white"></i>
              ${dateStr}
            </span>
            <span class="text-[9px] text-[var(--muted-foreground)] font-mono">${idBadge}</span>
          </div>
        `;
        listContainer.appendChild(item);
      });
      if (window.lucide && typeof lucide.createIcons === "function") lucide.createIcons();
    }
    function filterMasterChatSessions(query) {
      const q = (query || "").toLowerCase().trim();
      if (!q) {
        renderMasterChatSessionsSidebar();
        return;
      }
      const filtered = masterChatSessions.filter(s => 
        (s.title && s.title.toLowerCase().includes(q)) || 
        (s.profile_name && s.profile_name.toLowerCase().includes(q)) ||
        (s.model && s.model.toLowerCase().includes(q)) ||
        (s.id && s.id.toLowerCase().includes(q))
      );
      renderMasterChatSessionsSidebar(filtered);
    }
    function createNewMasterChatSession() {
      const nowStr = new Date().toISOString().replace(/[-:T.]/g, "").slice(0, 14);
      currentMasterChatSessionId = `mc_${nowStr}_${currentMasterChatProfileId || 'default'}`;
      
      const messagesContainer = document.getElementById("master-chat-messages");
      if (messagesContainer) {
        messagesContainer.innerHTML = "";
        renderMasterChatEmptyWelcome();
      }
      removeMasterChatAttachment();
      renderMasterChatSessionsSidebar();
      const inputEl = document.getElementById("master-chat-input");
      if (inputEl) {
        inputEl.value = "";
        inputEl.focus();
      }
    }
    function updateMasterChatGroupUI(targetSess) {
      currentMasterChatProfileId = "__group__";
      currentMasterChatAgentId = "__group__";
      const selectEl = document.getElementById("master-chat-profile-select");
      if (selectEl) {
        let groupOpt = selectEl.querySelector('option[value="__group__"]');
        if (!groupOpt) {
          groupOpt = document.createElement("option");
          groupOpt.value = "__group__";
          selectEl.insertBefore(groupOpt, selectEl.firstChild);
        }
        const sessionTitle = (targetSess && targetSess.title) ? targetSess.title : "Gruppen-Session";
        groupOpt.textContent = `👥 ${sessionTitle}`;
        selectEl.value = "__group__";
      }
      const avatarEl = document.getElementById("master-chat-selected-avatar");
      if (avatarEl) {
        avatarEl.src = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%234f46e5' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2'/%3E%3Ccircle cx='9' cy='7' r='4'/%3E%3Cpath d='M22 21v-2a4 4 0 0 0-3-3.87'/%3E%3Cpath d='M16 3.13a4 4 0 0 1 0 7.75'/%3E%3C/svg%3E";
      }
      const catEl = document.getElementById("master-chat-profile-category");
      if (catEl) {
        catEl.textContent = "👥 Gruppe / Multi-Agent";
      }
      const descEl = document.getElementById("master-chat-profile-desc");
      if (descEl) {
        descEl.textContent = (targetSess && targetSess.title)
          ? `Mission: ${targetSess.title}`
          : "Kollaborative Multi-Agenten-Session (Operations / Boardroom)";
      }
    }
    async function selectMasterChatSession(sessionId, skipProfileSync = false) {
      currentMasterChatSessionId = sessionId;
      // Ermittle Profil der Session und synchronisiere Profil-Dropdown & Header falls abweichend
      if (!skipProfileSync) {
        const targetSess = masterChatSessions.find(s => s && s.id === sessionId);
        if (targetSess) {
          const isGroup = isSessionGroupType(targetSess);
          if (isGroup) {
            updateMasterChatGroupUI(targetSess);
          } else {
            let detectedProfId = targetSess.profile_name || "";
            if (!detectedProfId && sessionId.startsWith("mc_")) {
              const parts = sessionId.split("_");
              detectedProfId = parts.slice(3).join("_") || parts[2] || "";
            }
            if ((targetSess.source || "").toLowerCase() === "telegram" || detectedProfId === "telegram_bot") {
              detectedProfId = "telegram_bot";
            }
            if (!detectedProfId || !masterChatProfiles.some(p => p.id === detectedProfId)) {
              detectedProfId = "default";
            }
            currentMasterChatProfileId = detectedProfId;
            currentMasterChatAgentId = detectedProfId;
            const selectEl = document.getElementById("master-chat-profile-select");
            if (selectEl) {
              const groupOpt = selectEl.querySelector('option[value="__group__"]');
              if (groupOpt) groupOpt.remove();
              selectEl.value = detectedProfId;
            }
            updateMasterChatProfileUI();
          }
        }
      }
      renderMasterChatSessionsSidebar();
      const messagesContainer = document.getElementById("master-chat-messages");
      if (!messagesContainer) return;
      messagesContainer.innerHTML = `<div class="text-center text-xs text-slate-400 py-12 italic">Lade Nachrichtenverlauf...</div>`;
      try {
        console.log("[DEBUG MasterChat] Fetching messages for:", sessionId);
        const res = await fetch(`/api/chat/sessions/${encodeURIComponent(sessionId)}/messages`);
        console.log("[DEBUG MasterChat] Fetch response status:", res.status);
        if (res.ok) {
          const data = await res.json();
          const msgs = data.messages || [];
          console.log("[DEBUG MasterChat] Parsed msgs count:", msgs.length);
          messagesContainer.innerHTML = "";
          if (msgs.length === 0) {
            renderMasterChatEmptyWelcome();
          } else {
            msgs.forEach((m, idx) => {
              try {
                appendMasterChatMessageBubble(m.role, m.content, m.timestamp, m.id, true);
              } catch (bErr) {
                console.error("[DEBUG MasterChat] Error rendering bubble at idx " + idx + ":", bErr, m);
              }
            });
            if (window.lucide && typeof lucide.createIcons === "function") {
              lucide.createIcons();
            }
            messagesContainer.scrollTop = messagesContainer.scrollHeight;
          }
          return;
        }
      } catch (e) {
        console.warn("[MasterChat] Fehler beim Laden des Verlaufs:", e);
      }
      renderMasterChatEmptyWelcome();
    }
    function renderMasterChatEmptyWelcome() {
      const messagesContainer = document.getElementById("master-chat-messages");
      if (!messagesContainer) return;
      const targetSess = masterChatSessions.find(s => s && s.id === currentMasterChatSessionId);
      const isGroup = isSessionGroupType(targetSess) || currentMasterChatProfileId === "__group__";
      if (isGroup) {
        const title = (targetSess && targetSess.title) ? targetSess.title : "Gruppen-Session";
        messagesContainer.innerHTML = `
          <div class="max-w-md mx-auto text-center py-12 space-y-4 bg-[var(--card)] border border-[var(--border)] rounded-xl p-8 mt-6 shadow-xs">
            <div class="w-16 h-16 rounded-xl bg-[var(--secondary)] border border-[var(--border)] text-indigo-500 flex items-center justify-center mx-auto text-2xl font-bold p-3">
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="w-10 h-10"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
            </div>
            <div class="space-y-1">
              <h3 class="text-base font-bold text-[var(--foreground)]">${escapeHtml(title)}</h3>
              <p class="text-xs text-[var(--muted-foreground)] font-mono">Multi-Agenten / Operations Koordination</p>
            </div>
            <p class="text-xs text-[var(--muted-foreground)] leading-relaxed max-w-sm mx-auto">
              Dieser Chat ist einer kollaborativen Multi-Agenten Mission zugeordnet.
            </p>
          </div>
        `;
        return;
      }
      const prof = masterChatProfiles.find(p => p.id === currentMasterChatProfileId) || {
        name: "Hermes Agent",
        person_name: "Default",
        role: "Zentraler Orchestrator",
        description: "Direkter Dialog und Operations-Missionssteuerung."
      };
      const name = prof.person_name || prof.name;
      const initials = (name || "HA").substring(0, 2).toUpperCase();
      const avatarUrl = (typeof getProfileAvatarUrl === "function") ? getProfileAvatarUrl(prof) : (prof.avatar || "/static/avatars/hermes_default_avatar.png");
      messagesContainer.innerHTML = `
        <div class="max-w-md mx-auto text-center py-12 space-y-4 bg-[var(--card)] border border-[var(--border)] rounded-xl p-8 mt-6 shadow-xs">
          <div class="w-16 h-16 rounded-xl bg-[var(--secondary)] border border-[var(--border)] text-[var(--foreground)] flex items-center justify-center mx-auto text-xl font-bold font-mono overflow-hidden">
            <img src="${avatarUrl}" class="w-full h-full object-cover" onerror="this.outerHTML='${initials}'">
          </div>
          <div class="space-y-1">
            <h3 class="text-base font-bold text-[var(--foreground)]">${escapeHtml(name)}</h3>
            <p class="text-xs text-[var(--muted-foreground)] font-mono">${escapeHtml(prof.role || "Spezialist")}</p>
          </div>
          <p class="text-xs text-[var(--muted-foreground)] leading-relaxed max-w-sm mx-auto">
            ${escapeHtml(prof.description || "Bereit für Instruktionen im Direkt-Dialog oder strukturierte Aufträge im Missions-Modus.")}
          </p>
          <div class="pt-2 flex items-center justify-center gap-2 text-[10.5px] font-mono text-[var(--muted-foreground)]">
            <!-- Removed redundant badges -->
          </div>
        </div>
      `;
    }
    // 7. Nachrichten rendern (Monochrome Theme-Aware Chat Bubble)
    function appendMasterChatMessageBubble(role, content, timestamp, msgId, skipBatchIcons = false) {
      const messagesContainer = document.getElementById("master-chat-messages");
      if (!messagesContainer) return null;
      const safeContent = content == null ? "" : String(content);
      const isUser = role === "user";
      // Formatiere Datum & Uhrzeit (z. B. 13.09.2026, 19:55)
      let dateFormatted = "";
      if (timestamp) {
        if (typeof timestamp === "number" || (!isNaN(timestamp) && !String(timestamp).includes(":") && !String(timestamp).includes("-"))) {
          const num = parseFloat(timestamp);
          const ms = num < 1e11 ? num * 1000 : num;
          const d = new Date(ms);
          if (!isNaN(d.getTime())) {
            dateFormatted = d.toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
          }
        } else if (typeof timestamp === "string") {
          dateFormatted = timestamp.length <= 8 ? `${new Date().toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit", year: "numeric" })}, ${timestamp}` : timestamp;
        }
      }
      if (!dateFormatted) {
        dateFormatted = new Date().toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
      }
      const displayMsgId = msgId ? `#msg-${msgId}` : `#msg-${Math.floor(1000 + Math.random() * 9000)}`;
      const bubbleWrap = document.createElement("div");
      if (isUser) {
        bubbleWrap.className = "flex justify-end";
        bubbleWrap.innerHTML = `
          <div class="max-w-2xl bg-[var(--secondary)] border border-[var(--border)] text-[var(--foreground)] rounded-xl rounded-tr-xs px-4 py-3 text-xs shadow-xs leading-relaxed space-y-2 min-w-[200px]">
            <div class="font-bold text-[var(--foreground)] text-[10px] uppercase tracking-wider font-mono">Du</div>
            <div class="whitespace-pre-wrap font-sans text-[var(--foreground)] leading-relaxed">${escapeHtml(safeContent)}</div>
            <div class="pt-1.5 border-t border-[var(--border)] flex items-center justify-between gap-3 text-[9.5px] font-mono text-[var(--muted-foreground)]">
              <span class="flex items-center gap-1 shrink-0"><i data-lucide="clock" class="w-3 h-3 text-black dark:text-white"></i>${dateFormatted}</span>
              <span class="font-mono font-medium text-[var(--muted-foreground)] shrink-0">${displayMsgId}</span>
            </div>
          </div>
        `;
      } else if (role === "system") {
        bubbleWrap.className = "flex justify-center";
        bubbleWrap.innerHTML = `
          <div class="max-w-xl bg-[var(--secondary)] border border-[var(--border)] rounded-lg px-4 py-2 text-xs text-[var(--foreground)] space-y-0.5 shadow-xs text-center leading-relaxed font-sans">
            <div class="font-bold text-[9px] uppercase tracking-wider font-mono text-[var(--muted-foreground)]">System-Ereignis</div>
            <div class="whitespace-pre-wrap font-mono">${escapeHtml(safeContent)}</div>
            <div class="pt-1 border-t border-[var(--border)] flex items-center justify-between text-[9px] font-mono text-[var(--muted-foreground)]">
              <span>${dateFormatted}</span>
              <span>${displayMsgId}</span>
            </div>
          </div>
        `;
      } else {
        bubbleWrap.className = "flex justify-start";
        const isGroup = currentMasterChatProfileId === "__group__";
        const prof = masterChatProfiles.find(p => p.id === currentMasterChatProfileId);
        let name = prof ? (prof.person_name || prof.name) : "Hermes";
        if (isGroup) {
          name = "Gruppe";
        } else if (currentMasterChatProfileId === "telegram_bot" || (prof && prof.id === "telegram_bot")) {
          name = "Telegram Bot";
        }
        const initials = name.substring(0, 2).toUpperCase();
        let avatarUrl = (typeof getProfileAvatarUrl === "function" && prof) ? getProfileAvatarUrl(prof) : (prof && prof.avatar ? prof.avatar : "/static/avatars/hermes_default_avatar.png");
        if (isGroup) {
          avatarUrl = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%234f46e5' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2'/%3E%3Ccircle cx='9' cy='7' r='4'/%3E%3Cpath d='M22 21v-2a4 4 0 0 0-3-3.87'/%3E%3Cpath d='M16 3.13a4 4 0 0 1 0 7.75'/%3E%3C/svg%3E";
        }
        
        let routingTagHtml = "";
        // Much more robust regex ignoring surrounding newlines and markdown asterisks
        const updatedRoutingRegex = /[\r\n\s]*\*?-\s*Routed to:\s*`?([^|`]+?)`?\s*\|\s*Tier:\s*`?([^|`]+?)`?\s*\|\s*Est\. Cost:\s*`?([^|`\n*]+?)`?\*?[\r\n\s]*$/i;
        const match = safeContent.match(updatedRoutingRegex);
        if (match) {
            safeContent = safeContent.replace(updatedRoutingRegex, '');
            // Move into the footer below the clock
            routingTagHtml = `<div class="flex items-center gap-1.5 border border-[var(--border)] bg-[var(--background)] px-2 py-0.5 rounded-md w-fit">
              <i data-lucide="cpu" class="w-3 h-3 text-indigo-400"></i>
              <span class="truncate max-w-[200px]" title="${match[1].trim()}">${match[1].trim()}</span>
              <span class="text-emerald-500 font-bold ml-1">${match[2].trim()}</span>
              <span class="text-amber-500 font-bold ml-1">${match[3].trim()}</span>
            </div>`;
        }
        const formattedContent = (window.archonLinkifyHtml
          ? window.archonLinkifyHtml(typeof formatMarkdownText === "function" ? formatMarkdownText(safeContent) : escapeHtml(safeContent))
          : (typeof formatMarkdownText === "function" ? formatMarkdownText(safeContent) : escapeHtml(safeContent)));

        // Prüfen, ob HITL Freigabe erforderlich ist
        const hasApprovalGate = safeContent.includes("Freigabe erforderlich") || safeContent.includes("Missions-Modus");
        const actionCardHtml = hasApprovalGate ? `
          <div class="mt-3 p-3 bg-[var(--secondary)] border border-[var(--border)] rounded-lg flex items-center justify-between gap-3 text-[var(--foreground)] shadow-xs">
            <div class="text-xs font-sans font-medium flex items-center gap-1.5">
              <i data-lucide="shield-alert" class="w-4 h-4 text-black dark:text-white"></i>
              <span>Diese Mission wartet im Approval Gate auf Freigabe.</span>
            </div>
            <button onclick="setTab('mission-control')" class="shadcn-btn-primary px-3 py-1 text-xs font-semibold rounded-md flex items-center gap-1.5 cursor-pointer shadow-xs transition shrink-0">
              <i data-lucide="shield" class="w-3.5 h-3.5"></i>
              <span>Zur Freigabe</span>
            </button>
          </div>
        ` : '';
        const clickHandler = isGroup ? '' : `onclick="jumpToAgentProfile('${prof ? prof.id : currentMasterChatProfileId}')"`;
        bubbleWrap.innerHTML = `
          <div class="flex gap-3 max-w-3xl">
            <div ${clickHandler} class="w-12 h-12 rounded-xl border border-[var(--border)] bg-[var(--secondary)] text-[var(--foreground)] flex items-center justify-center font-mono text-sm font-bold shrink-0 shadow-xs mt-0.5 overflow-hidden cursor-pointer hover:border-zinc-950 dark:hover:border-zinc-50 transition duration-150 group" title="${isGroup ? 'Gruppen-Session' : 'Profil &amp; Einstellungen im Agenten-Kader öffnen'}">
              <img src="${avatarUrl}" class="w-full h-full object-cover group-hover:opacity-90 transition" onerror="this.outerHTML='${initials}'">
            </div>
            <div class="bg-[var(--card)] border border-[var(--border)] rounded-xl rounded-tl-xs px-4 py-3 text-xs text-[var(--foreground)] space-y-2 shadow-xs leading-relaxed min-w-[260px]">
              <div class="flex items-center justify-between gap-2 mb-1 pb-1 border-b border-[var(--border)]">
                <span class="font-bold text-[var(--foreground)] text-xs font-mono">${escapeHtml(name)}</span>
                <div class="flex items-center gap-1.5">
                                    <button type="button" class="text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition p-1 rounded cursor-pointer" title="Zitieren / Antworten" onclick="replyToAgentMessage(this)" data-text="${escapeHtml(safeContent).replace(/\"/g, '&quot;')}">
                    <i data-lucide="reply" class="w-3.5 h-3.5 text-black dark:text-white"></i>
                  </button>
                  <button type="button" class="copy-bubble-btn text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition p-1 rounded cursor-pointer" title="In Zwischenablage kopieren" onclick="copyAgentMessageText(this)" data-text="${escapeHtml(safeContent).replace(/"/g, '&quot;')}">
                    <i data-lucide="copy" class="w-3.5 h-3.5 text-black dark:text-white"></i>
                  </button>
                  <button class="text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition p-1 rounded cursor-pointer" title="Vorlesen (Text-to-Speech)" onclick="speakText(this.getAttribute('data-text'))" data-text="${escapeHtml(safeContent).replace(/"/g, '&quot;')}">
                    <i data-lucide="volume-2" class="w-3.5 h-3.5 text-black dark:text-white"></i>
                  </button>
                </div>
              </div>
              <div class="chat-assistant-body chat-markdown font-sans leading-relaxed text-[var(--foreground)]">${formattedContent}</div>
              ${actionCardHtml}
              <div class="pt-2 mt-2 border-t border-[var(--border)] flex flex-col gap-1.5 text-[9.5px] font-mono text-[var(--muted-foreground)]">
                <div class="flex items-center justify-between">
                  <span class="flex items-center gap-1"><i data-lucide="clock" class="w-3 h-3 text-black dark:text-white"></i>${dateFormatted}</span>
                  <span class="font-mono font-medium text-[var(--muted-foreground)]">${displayMsgId}</span>
                </div>
                ${routingTagHtml}
              </div>
            </div>
          </div>
        `;
      }
      messagesContainer.appendChild(bubbleWrap);
      if (!skipBatchIcons) {
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
        if (window.lucide && typeof lucide.createIcons === "function") {
          lucide.createIcons();
        }
      }
      return bubbleWrap;
    }
    // 8. Text-to-Speech (TTS) Wiedergabe
    function speakText(text) {
      if (!text || !('speechSynthesis' in window)) {
        alert("Text-to-Speech wird von deinem Browser nicht unterstützt.");
        return;
      }
      if (window.speechSynthesis.speaking) {
        window.speechSynthesis.cancel();
        return;
      }
      const cleanText = text
        .replace(/<[^>]*>/g, '')
        .replace(/`{1,3}[^`]*`{1,3}/g, '')
        .replace(/[*_#\-~]/g, ' ')
        .trim();
      const utterance = new SpeechSynthesisUtterance(cleanText);
      utterance.lang = "de-DE";
      utterance.rate = 1.05;
      window.speechSynthesis.speak(utterance);
    }
    // 9. Quick Chat Mikrofon / Spracheingabe (Continuous Speech Recognition)
    function toggleMasterChatDictation() {
      const btn = document.getElementById("master-chat-mic-btn");
      const textarea = document.getElementById("master-chat-input");
      if (!("webkitSpeechRecognition" in window) && !("SpeechRecognition" in window)) {
        alert("Spracherkennung wird in diesem Browser leider nicht unterstützt. Bitte Chrome oder Edge nutzen.");
        return;
      }
      if (isMasterChatDictating) {
        if (masterChatDictationRecognition) {
          masterChatDictationRecognition.stop();
        }
        isMasterChatDictating = false;
        if (btn) {
          btn.className = "p-2.5 rounded-xl border border-slate-200 text-slate-600 hover:text-slate-900 hover:bg-slate-100 transition shrink-0 cursor-pointer shadow-2xs";
          btn.style.backgroundColor = "#FFFFFF";
          btn.title = "Spracheingabe / Diktat starten (Mikrofon)";
        }
        return;
      }
      const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
      masterChatDictationRecognition = new SpeechRec();
      masterChatDictationRecognition.continuous = true;
      masterChatDictationRecognition.interimResults = true;
      masterChatDictationRecognition.lang = "de-DE";
      let baseText = textarea.value ? textarea.value.trim() + " " : "";
      masterChatDictationRecognition.onresult = (event) => {
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
        autoResizeMasterChatInput(textarea);
      };
      masterChatDictationRecognition.onerror = (event) => {
        console.error("[MasterChat Speech] Fehler:", event.error);
        isMasterChatDictating = false;
        if (btn) {
          btn.className = "p-2.5 rounded-xl border border-slate-200 text-slate-600 hover:text-slate-900 hover:bg-slate-100 transition shrink-0 cursor-pointer shadow-2xs";
          btn.style.backgroundColor = "#FFFFFF";
        }
      };
      masterChatDictationRecognition.onend = () => {
        isMasterChatDictating = false;
        if (btn) {
          btn.className = "p-2.5 rounded-xl border border-slate-200 text-slate-600 hover:text-slate-900 hover:bg-slate-100 transition shrink-0 cursor-pointer shadow-2xs";
          btn.style.backgroundColor = "#FFFFFF";
        }
      };
      masterChatDictationRecognition.start();
      isMasterChatDictating = true;
      if (btn) {
        btn.className = "p-2.5 rounded-xl border border-red-400 text-red-500 bg-red-50 animate-pulse transition shrink-0 cursor-pointer shadow-2xs";
        btn.title = "Diktat läuft... Klicken zum Stoppen";
      }
    }
    // 10. Quick Chat Datei-Anhang Handling & Screen Capture
    function setMasterChatAttachmentFile(file) {
      if (!file) return;
      currentMasterChatAttachment = {
        file: file,
        name: file.name || "screenshot.png",
        size: (file.size / 1024).toFixed(1) + " KB",
        type: file.type || "image/png"
      };
      const bar = document.getElementById("master-chat-attachment-bar");
      const nameEl = document.getElementById("master-chat-attachment-name");
      const sizeEl = document.getElementById("master-chat-attachment-size");
      if (bar && nameEl) {
        nameEl.innerText = currentMasterChatAttachment.name;
        if (sizeEl) sizeEl.innerText = `(${currentMasterChatAttachment.size})`;
        bar.classList.remove("hidden");
        if (window.lucide && typeof lucide.createIcons === "function") lucide.createIcons();
      }
    }
    function handleMasterChatFileSelected(event) {
      const file = event.target.files && event.target.files[0];
      if (!file) return;
      setMasterChatAttachmentFile(file);
    }
    function handleMasterChatInputPaste(event) {
      const items = (event.clipboardData || window.clipboardData)?.items;
      if (!items) return;
      for (let i = 0; i < items.length; i++) {
        const item = items[i];
        if (item.kind === 'file' && item.type.startsWith('image/')) {
          const blob = item.getAsFile();
          if (blob) {
            event.preventDefault();
            const ts = new Date().toISOString().replace(/[-:T.]/g, "").slice(0, 14);
            const file = new File([blob], `pasted_image_${ts}.png`, { type: blob.type || "image/png" });
            setMasterChatAttachmentFile(file);
            return;
          }
        }
      }
    }
    async function captureScreenForMasterChat() {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getDisplayMedia) {
        alert("Bildschirm-Aufnahme wird von diesem Browser nicht unterstützt oder erfordert HTTPS / localhost.");
        return;
      }
      try {
        const stream = await navigator.mediaDevices.getDisplayMedia({
          video: { cursor: "always" },
          audio: false
        });
        const track = stream.getVideoTracks()[0];
        const video = document.createElement("video");
        video.srcObject = stream;
        await video.play();
        const canvas = document.createElement("canvas");
        canvas.width = video.videoWidth || 1920;
        canvas.height = video.videoHeight || 1080;
        const ctx = canvas.getContext("2d");
        ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
        track.stop();
        stream.getTracks().forEach(t => t.stop());
        canvas.toBlob((blob) => {
          if (!blob) return;
          const ts = new Date().toISOString().replace(/[-:T.]/g, "").slice(0, 14);
          const file = new File([blob], `screen_capture_${ts}.png`, { type: "image/png" });
          setMasterChatAttachmentFile(file);
        }, "image/png");
      } catch (err) {
        if (err.name !== "NotAllowedError") {
          console.warn("[ScreenCapture] Fehler:", err);
        }
      }
    }
    function removeMasterChatAttachment() {
      currentMasterChatAttachment = null;
      const fileInput = document.getElementById("master-chat-file-input");
      if (fileInput) fileInput.value = "";
      const bar = document.getElementById("master-chat-attachment-bar");
      if (bar) bar.classList.add("hidden");
    }





    window.replyToAgentMessage = function(btn) {
      const text = btn.getAttribute('data-text');
      if (!text) return;
      let unescapedText = text.replace(/&quot;/g, '"').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
      if (unescapedText.length > 800) unescapedText = unescapedText.substring(0, 800) + '...';
      const inputEl = document.getElementById("master-chat-input");
      if (inputEl) {
        const lines = unescapedText.split('\n').map(line => '> ' + line).join('\n');
        inputEl.value = lines + '\n\n' + inputEl.value;
        inputEl.focus();
      }
    };
