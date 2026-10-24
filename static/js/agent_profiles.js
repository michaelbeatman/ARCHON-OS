
    // --- HERMES AGENTENPROFILE & SKILL-MANAGER LOGIK ---
    let hermesProfilesData = [];
    let hermesGlobalSkillsData = [];
    let currentSelectedProfileId = "";
    let activeProfileCategoryFilter = "all";
    let isLoadingProfiles = false;
    let _profilesLoadingPromise = null;
    async function loadHermesProfilesView(force = false) {
      if (_profilesLoadingPromise && !force) {
        return _profilesLoadingPromise;
      }
      _profilesLoadingPromise = (async () => {
        isLoadingProfiles = true;
        const shouldShowOverlay = (currentTab === 'agent-profiles' || force) && hermesProfilesData.length === 0;
        if (shouldShowOverlay) {
          showLoadingOverlay("Agenten-Kader wird geladen...", "54 Personalakten, Rollen & SOUL-Direktiven werden synchronisiert");
        }
        try {
          // Starte Skills-Download asynchron im Hintergrund (blockiert nicht die Anzeige der Profile)
          if (hermesGlobalSkillsData.length === 0 || force) {
            loadHermesSkillsFromServer().then(() => {
              populateGlobalSkillsDropdown();
              initTalentMarketplace();
              if (currentSelectedProfileId) {
                const prof = hermesProfilesData.find(p => p.id === currentSelectedProfileId);
                if (prof) renderActiveProfileSkillsTags(prof.skills || []);
              }
            }).catch(e => console.warn("Skills background load:", e));
          }
          if (hermesProfilesData.length === 0 || force) {
            await loadHermesProfilesFromServer();
          } else {
            renderHermesProfilesList();
          }
          if (hermesProfilesData.length > 0) {
            let targetProfileId = currentSelectedProfileId;
            if (!targetProfileId || !hermesProfilesData.find(p => p.id === targetProfileId)) {
              try {
                const savedId = localStorage.getItem("archon_active_profile_id");
                if (savedId && hermesProfilesData.find(p => p.id === savedId)) {
                  targetProfileId = savedId;
                }
              } catch(e) {}
            }
            if (!targetProfileId || !hermesProfilesData.find(p => p.id === targetProfileId)) {
              targetProfileId = hermesProfilesData[0].id;
            }
            if (activeProfileTabFilter === 'active') {
              const activeProfs = hermesProfilesData.filter(p => isProfileDeployedActive(p));
              const currentIsActive = activeProfs.some(p => p.id === targetProfileId);
              if (!currentIsActive && activeProfs.length > 0) {
                targetProfileId = activeProfs[0].id;
              }
            }
            currentSelectedProfileId = targetProfileId;
            selectProfileForEditor(currentSelectedProfileId);
          } else {
            createNewProfileDraft();
          }
          if (window.lucide) lucide.createIcons();
        } catch (err) {
          console.error("Error in loadHermesProfilesView:", err);
        } finally {
          if (shouldShowOverlay) {
            hideLoadingOverlay();
          }
          isLoadingProfiles = false;
          _profilesLoadingPromise = null;
        }
      })();
      return _profilesLoadingPromise;
    }
    async function loadHermesSkillsFromServer() {
      try {
        const res = await fetch("/api/hermes/skills");
        if (res.ok) {
          hermesGlobalSkillsData = await res.json();
        }
      } catch (e) {
        console.error("Error loading hermes skills:", e);
      }
    }
    async function loadHermesProfilesFromServer() {
      try {
        const res = await fetch("/api/hermes/profiles");
        if (res.ok) {
          hermesProfilesData = await res.json();
          window.hermesProfilesData = hermesProfilesData;
        }
      } catch (e) {
        console.error("[DEBUG PROFILES] Error loading hermes profiles:", e);
      }
      if (currentSelectedProfileId) {
        selectProfileForEditor(currentSelectedProfileId);
      } else {
        renderHermesProfilesList();
      }
    }
    function populateGlobalSkillsDropdown() {
      const select = document.getElementById("prof-add-skill-select");
      if (!select) return;
      select.innerHTML = '<option value="" disabled selected>+ Skill aus dem Katalog hinzufügen...</option>';
      const categories = {};
      hermesGlobalSkillsData.forEach(sk => {
        const cat = sk.category || "Allgemein";
        if (!categories[cat]) categories[cat] = [];
        categories[cat].push(sk);
      });
      for (const [catName, list] of Object.entries(categories)) {
        const group = document.createElement("optgroup");
        group.label = catName;
        list.forEach(sk => {
          const opt = document.createElement("option");
          opt.value = sk.id;
          opt.innerText = `${sk.name} (${(sk.tags || []).join(', ')})`;
          group.appendChild(opt);
        });
        select.appendChild(group);
      }
    }
    const AVATAR_REV = "20260913_rev4";
    let avatarDynamicRev = Date.now();
    function withAvatarRevision(url) {
      if (!url) return `/static/avatars/avatar_001.jpg?v=${AVATAR_REV}`;
      if (url.startsWith("data:") || url.startsWith("blob:")) return url;
      const clean = url.split("?")[0];
      if (clean.includes("custom_") || clean.includes("upload")) {
        return `${clean}?v=${avatarDynamicRev}`;
      }
      return `${clean}?v=${AVATAR_REV}`;
    }
    const ALL_AVATARS_LIST = [
      "/static/avatars/hermes_default_avatar.png",
      ...Array.from({ length: 174 }, (_, i) => `/static/avatars/avatar_${String(i + 1).padStart(3, '0')}.jpg`)
    ];
    function getProfileAvatarUrl(prof) {
      if (prof && (prof.id === "default" || prof.id === "hermes_default")) {
        if (prof.avatar && !prof.avatar.includes("avatar_001.jpg") && !prof.avatar.includes("dicebear.com")) {
          return withAvatarRevision(prof.avatar);
        }
        return withAvatarRevision("/static/avatars/hermes_default_avatar.png");
      }
      if (prof && prof.avatar && !prof.avatar.includes("dicebear.com")) return withAvatarRevision(prof.avatar);
      if (prof && prof.avatar_url && !prof.avatar_url.includes("dicebear.com")) return withAvatarRevision(prof.avatar_url);
      // Deterministischer Avatar-Index basierend auf Profil-ID oder Name
      let hash = 0;
      const str = (prof && (prof.id || prof.name)) || "agent";
      for (let i = 0; i < str.length; i++) {
        hash = (hash << 5) - hash + str.charCodeAt(i);
        hash |= 0;
      }
      const avatarIndex = (Math.abs(hash) % 174) + 1;
      return withAvatarRevision(`/static/avatars/avatar_${String(avatarIndex).padStart(3, '0')}.jpg`);
    }
    const AVAILABLE_SYSTEM_TOOLS = [
      { id: "web_search", name: "Web Search & Scraping", icon: "globe", desc: "web_search, web_extract", subtools: ["web_search", "web_extract"], mode: "sandbox", timeout: 30 },
      { id: "browser", name: "Browser Automation", icon: "chrome", desc: "navigate, click, type, scroll, snapshot", subtools: ["browser_back", "browser_cdp", "browser_click", "browser_console", "browser_dialog", "browser_exec", "browser_get_images", "browser_navigate", "browser_press", "browser_scroll", "browser_snapshot", "browser_type", "browser_vision"], mode: "sandbox", timeout: 90 },
      { id: "terminal", name: "Terminal & Processes", icon: "terminal", desc: "terminal, process", subtools: ["process", "terminal"], mode: "direct", timeout: 120 },
      { id: "filesystem", name: "File Operations", icon: "folder-tree", desc: "read, write, patch, search", subtools: ["patch", "read_file", "search_files", "write_file"], mode: "direct", timeout: 60 },
      { id: "execute_code", name: "Code Execution", icon: "code-2", desc: "execute_code (Polyglot Runtime)", subtools: ["execute_code"], mode: "sandbox", timeout: 60 },
      { id: "vision_analyze", name: "Vision / Image Analysis", icon: "eye", desc: "vision_analyze", subtools: ["vision_analyze"], mode: "sandbox", timeout: 60 },
      { id: "video_analyze", name: "Video Analysis", icon: "video", desc: "video_analyze (requires video-capable model)", subtools: ["video_analyze"], mode: "sandbox", timeout: 120 },
      { id: "image_generate", name: "Image Generation", icon: "image", desc: "image_generate", subtools: ["image_generate"], mode: "sandbox", timeout: 60 },
      { id: "video_generate", name: "Video Generation", icon: "film", desc: "video_generate (text/image/reference)", subtools: ["video_generate", "xai_video_edit", "xai_video_extend"], mode: "sandbox", timeout: 180 },
      { id: "bfl_flux3", name: "BFL FLUX 3 Video", icon: "clapperboard", desc: "bfl_flux3_* (Text/Image/Keyframes to Video)", subtools: ["bfl_flux3_get_result", "bfl_flux3_image_to_video", "bfl_flux3_keyframes_to_video", "bfl_flux3_prompting_guide", "bfl_flux3_text_to_video", "bfl_flux3_video_continuation"], mode: "sandbox", timeout: 180 },
      { id: "x_search", name: "X (Twitter) Search", icon: "twitter", desc: "x_search (xAI OAuth / XAI_API_KEY)", subtools: ["x_search"], mode: "sandbox", timeout: 30 },
      { id: "text_to_speech", name: "Text-to-Speech", icon: "volume-2", desc: "text_to_speech (Voice Output)", subtools: ["text_to_speech"], mode: "sandbox", timeout: 30 },
      { id: "speech_to_text", name: "Speech-to-Text", icon: "mic", desc: "voice transcription (gateway messages + voice mode)", subtools: ["stt_toolset"], mode: "sandbox", timeout: 30 },
      { id: "skills", name: "Skills", icon: "sparkles", desc: "list, view, manage", subtools: ["skill_manage", "skill_view", "skills_list"], mode: "direct", timeout: 30 },
      { id: "task_planning", name: "Task Planning", icon: "check-square", desc: "todo planning & task breakdown", subtools: ["todo"], mode: "direct", timeout: 30 },
      { id: "memory", name: "Memory", icon: "database", desc: "persistent memory across sessions", subtools: ["memory"], mode: "direct", timeout: 30 },
      { id: "context_engine", name: "Context Engine", icon: "cpu", desc: "runtime tools from active context engine", subtools: ["context_engine"], mode: "direct", timeout: 30 },
      { id: "session_search", name: "Session Search", icon: "search", desc: "search past conversations", subtools: ["session_search"], mode: "direct", timeout: 30 },
      { id: "clarify", name: "Clarifying Questions", icon: "help-circle", desc: "clarify user requirements & ambiguous intent", subtools: ["clarify"], mode: "direct", timeout: 30 },
      { id: "delegate_task", name: "Task Delegation", icon: "share-2", desc: "delegate_task to specialized subagents", subtools: ["delegate_task"], mode: "direct", timeout: 60 },
      { id: "cronjob", name: "Cron Jobs", icon: "clock", desc: "create/list/update/pause/resume/run cronjobs", subtools: ["cronjob"], mode: "direct", timeout: 60 },
      { id: "home_assistant", name: "Home Assistant", icon: "home", desc: "smart home device control", subtools: ["ha_call_service", "ha_get_state", "ha_list_entities", "ha_list_services"], mode: "sandbox", timeout: 45 },
      { id: "spotify", name: "Spotify", icon: "music", desc: "playback, search, playlists, library", subtools: ["spotify_albums", "spotify_devices", "spotify_library", "spotify_playback", "spotify_playlists", "spotify_queue", "spotify_search"], mode: "sandbox", timeout: 45 },
      { id: "discord", name: "Discord (read/participate)", icon: "message-circle", desc: "fetch messages, search members, create thread", subtools: ["discord"], mode: "sandbox", timeout: 45 },
      { id: "discord_admin", name: "Discord Server Admin", icon: "shield", desc: "list channels/roles, pin, assign roles", subtools: ["discord_admin"], mode: "sandbox", timeout: 45 },
      { id: "yuanbao", name: "Yuanbao", icon: "messages-square", desc: "group info, member queries, DM", subtools: ["yb_query_group_info", "yb_query_group_members", "yb_search_sticker", "yb_send_dm", "yb_send_sticker"], mode: "sandbox", timeout: 45 },
      { id: "computer_use", name: "Computer Use (macOS/Win/Linux)", icon: "monitor", desc: "background desktop control via cua-driver", subtools: ["computer_use"], mode: "direct", timeout: 120 },
      { id: "a2a", name: "A2A Protocol (Agent-to-Agent)", icon: "network", desc: "A2A standard v1.0 (discover, call, orchestrate)", subtools: ["a2a_call", "a2a_discover", "a2a_history", "a2a_list", "a2a_orchestrate"], mode: "direct", timeout: 60 }
    ];
    const DEFAULT_HERMES_TOOLS = [
      "web_search", "browser", "terminal", "filesystem", "execute_code", "vision_analyze",
      "image_generate", "bfl_flux3", "text_to_speech", "speech_to_text", "skills", "task_planning",
      "memory", "session_search", "clarify", "delegate_task", "cronjob", "computer_use"
    ];
    let dynamicPaperclipAgentIds = [];
    let dynamicPaperclipAgents = [];
    async function loadPaperclipActiveAgents() {
      // Paperclip-Polling entfernt; Profile-Status kommt direkt aus agent_profiles.json
      return Promise.resolve();
    }
    async function refreshProfiles(isManual = false) {
      if (isManual) {
        showLoadingOverlay("Agenten-Disposition wird abgeglichen...", "Agenten-Profile werden synchronisiert");
      }
      try {
        await loadHermesProfilesFromServer();
        if (currentSelectedProfileId) {
          selectProfileForEditor(currentSelectedProfileId);
        }
        if (isManual && typeof showNotification === 'function') {
          showNotification("Agenten Sync", "Agenten-Status erfolgreich synchronisiert.", "info");
        }
      } catch (e) {
        console.error("Error syncing profiles:", e);
      } finally {
        if (isManual) {
          setTimeout(() => hideLoadingOverlay(), 300);
        }
      }
    }
    const refreshPaperclipAndProfiles = refreshProfiles;
    window.refreshPaperclipAndProfiles = refreshProfiles;
    let activeProfileTabFilter = 'active';
    function setProfileTabFilter(tabName) {
      activeProfileTabFilter = tabName || 'active';
      
      const btnActive = document.getElementById("tab-filter-active");
      const btnFav = document.getElementById("tab-filter-favorites");
      const btnAll = document.getElementById("tab-filter-all");
      const activeClass = "py-1 px-1.5 rounded-lg text-[10.5px] font-bold font-mono transition text-center cursor-pointer shadow-xs bg-[var(--card)] text-[var(--foreground)] border border-[var(--border)] truncate";
      const inactiveClass = "py-1 px-1.5 rounded-lg text-[10.5px] font-medium font-mono transition text-center cursor-pointer bg-transparent text-[var(--muted-foreground)] hover:text-[var(--foreground)] border border-transparent truncate";
      if (btnActive) {
        btnActive.className = (activeProfileTabFilter === 'active') ? activeClass : inactiveClass;
        btnActive.style.cssText = "";
      }
      if (btnFav) {
        btnFav.className = (activeProfileTabFilter === 'favorites') ? activeClass : inactiveClass;
        btnFav.style.cssText = "";
      }
      if (btnAll) {
        btnAll.className = (activeProfileTabFilter === 'all') ? activeClass : inactiveClass;
        btnAll.style.cssText = "";
      }
      renderHermesProfilesList();
    }
    async function toggleProfileFavorite(profId, event) {
      if (event) event.stopPropagation();
      const prof = hermesProfilesData.find(p => p.id === profId);
      if (!prof) return;
      
      prof.is_favorite = !prof.is_favorite;
      renderHermesProfilesList();
      try {
        await fetch(`/api/hermes/profiles/${profId}/favorite`, {
          method: "POST",
          headers: { "Content-Type": "application/json" }
        });
      } catch (e) {
        console.error("Error toggling favorite:", e);
      }
    }
    function getProfilePaperclipAgent(p) {
      if (!p || !p.id || !Array.isArray(dynamicPaperclipAgents)) return null;
      const pid = (p.id || '').toLowerCase().trim();
      const pperson = (p.person_name || '').toLowerCase().trim();
      const pname = (p.name || '').toLowerCase().trim();
      
      return dynamicPaperclipAgents.find(a => {
        const apid = (a.profile_id || '').toLowerCase().trim();
        const arole = (a.role || '').toLowerCase().trim();
        const aname = (a.name || '').toLowerCase().trim();
        const atitle = (a.title || '').toLowerCase().trim();
        
        return (apid && apid === pid) ||
               (arole && (arole === pid || arole === pid.replace(/_/g, ' '))) ||
               (aname && (aname === pperson || aname === pname)) ||
               (atitle && (atitle === pname || atitle === pperson));
      }) || null;
    }
    function isProfileDeployedActive(p) {
      // 1. Check OmniRoute Gateway
      if (typeof gwProfilesData !== 'undefined' && Array.isArray(gwProfilesData)) {
        const agent = gwProfilesData.find(gw => gw && gw.id === p.id);
        if (agent) {
          const st = (agent.status || '').toLowerCase().trim();
          if (st === 'active' || st === 'idle' || st === 'running') return true;
        }
      }
      
      // 2. Check if user is currently chatting with them
      if (typeof currentSelectedProfileId !== 'undefined' && p.id === currentSelectedProfileId) return true;
      if (typeof currentMasterChatProfileId !== 'undefined' && p.id === currentMasterChatProfileId) return true;
      
      // 3. The 'default' (Master) is practically always active when you interact with it
      if (p.id === 'default' && (currentSelectedProfileId === 'default' || currentMasterChatProfileId === 'default')) return true;
      
      return false;
    }
    function startPaperclipBackgroundSync() {
      // Paperclip-Polling entfernt; Profile werden bei Bedarf synchronisiert.
    }
    let catalogCollapsed = false;
    let activeAgentCadreTab = 'overview';
    let inlinePersonalakteViewMode = 'dossier';
    function toggleCatalogCollapse(forceState) {
      if (typeof forceState === 'boolean') {
        catalogCollapsed = forceState;
      } else {
        catalogCollapsed = !catalogCollapsed;
      }
      
      const col = document.getElementById("agent-catalog-col");
      const expHeader = document.getElementById("catalog-expanded-header");
      const colHeader = document.getElementById("catalog-collapsed-header");
      const expFooter = document.getElementById("catalog-expanded-footer");
      
      if (col) {
        if (catalogCollapsed) {
          col.classList.remove("w-[250px]", "min-w-[250px]", "max-w-[250px]", "p-3");
          col.classList.add("w-[68px]", "min-w-[68px]", "max-w-[68px]", "p-1.5");
          if (expHeader) expHeader.classList.add("hidden");
          if (colHeader) colHeader.classList.remove("hidden");
          if (expFooter) expFooter.classList.add("hidden");
        } else {
          col.classList.remove("w-[68px]", "min-w-[68px]", "max-w-[68px]", "p-1.5");
          col.classList.add("w-[250px]", "min-w-[250px]", "max-w-[250px]", "p-3");
          if (expHeader) expHeader.classList.remove("hidden");
          if (colHeader) colHeader.classList.add("hidden");
          if (expFooter) expFooter.classList.remove("hidden");
        }
      }
      renderHermesProfilesList();
    }
    function switchAgentCadreTab(tabName) {
      activeAgentCadreTab = tabName || 'overview';
      
      const tabNames = ['overview', 'chat', 'skills', 'operations', 'soul', 'personalakte', 'marketplace'];
      tabNames.forEach(t => {
        const btn = document.getElementById(`agent-tab-btn-${t}`);
        const pane = document.getElementById(`agent-pane-${t}`);
        const label = btn ? btn.querySelector(".agent-tab-label") : null;
        
        const iconWrap = btn ? btn.querySelector(".tile-icon-wrap") : null;
        
        if (t === activeAgentCadreTab) {
          if (btn) {
            btn.className = "agent-header-tile active-cadre-tab flex flex-col items-center justify-center min-w-[58px] sm:min-w-[66px] py-0.5 px-0.5 bg-transparent border-0 shadow-none opacity-100 cursor-pointer select-none transition-transform hover:scale-105 duration-150";
          }
          if (iconWrap) {
            iconWrap.classList.add("active-tile");
          }
          if (label) {
            label.className = "agent-tab-label text-[10px] font-mono tracking-tight text-center whitespace-nowrap text-red-600 font-bold";
          }
          if (pane) pane.classList.remove("hidden");
        } else {
          if (btn) {
            btn.className = "agent-header-tile flex flex-col items-center justify-center min-w-[58px] sm:min-w-[66px] py-0.5 px-0.5 bg-transparent border-0 shadow-none opacity-100 cursor-pointer select-none transition-transform hover:scale-105 duration-150";
          }
          if (iconWrap) {
            iconWrap.classList.remove("active-tile");
          }
          if (label) {
            label.className = "agent-tab-label text-[10px] font-mono tracking-tight text-center whitespace-nowrap text-black dark:text-zinc-100 font-medium";
          }
          if (pane) pane.classList.add("hidden");
        }
      });
      if (currentSelectedProfileId) {
        if (activeAgentCadreTab === 'overview') {
          loadAgentLiveActivity(currentSelectedProfileId);
          loadAgentProjectsHistory(currentSelectedProfileId);
        } else if (activeAgentCadreTab === 'soul') {
          loadInlineSoulMarkdown(currentSelectedProfileId);
        } else if (activeAgentCadreTab === 'personalakte') {
          loadInlinePersonalakte(currentSelectedProfileId);
        } else if (activeAgentCadreTab === 'chat') {
          loadAgentTabChatSessions(currentSelectedProfileId);
        }
      }
      
      if (window.lucide) lucide.createIcons();
    }
    function renderHermesProfilesList() {
      const container = document.getElementById("hermes-profiles-list");
      if (!container) return;
      container.innerHTML = "";
      // Fallback: Wenn noch keine Daten geladen wurden, lade sie vom Server
      if (!Array.isArray(hermesProfilesData) || hermesProfilesData.length === 0) {
        if (!isLoadingProfiles) {
          loadHermesProfilesFromServer();
        }
        container.innerHTML = `<div class="text-center py-8 text-xs text-[var(--muted-foreground)] font-mono animate-pulse">Lade Agenten-Kader...</div>`;
        return;
      }
      const query = (document.getElementById("profile-search-input")?.value || "").toLowerCase().trim();
      // Counts berechnen
      const totalAll = hermesProfilesData.length;
      const totalFav = hermesProfilesData.filter(p => p.is_favorite === true).length;
      const totalActive = hermesProfilesData.filter(p => isProfileDeployedActive(p)).length;
      const countActiveEl = document.getElementById("count-active");
      const countFavEl = document.getElementById("count-favorites");
      const countAllEl = document.getElementById("count-all");
      const countBadge = document.getElementById("profile-count-badge");
      if (countActiveEl) countActiveEl.innerText = totalActive;
      if (countFavEl) countFavEl.innerText = totalFav;
      if (countAllEl) countAllEl.innerText = totalAll;
      const filtered = hermesProfilesData.filter(p => {
        // Tab Filter
        let matchesTab = true;
        if (activeProfileTabFilter === 'active') {
          matchesTab = isProfileDeployedActive(p);
        } else if (activeProfileTabFilter === 'favorites') {
          matchesTab = (p.is_favorite === true);
        }
        // Domänen Filter
        const matchesCat = (activeProfileCategoryFilter === "all" || p.category === activeProfileCategoryFilter);
        
        // Such-Query Filter
        const matchesQuery = !query || 
          (p.person_name || "").toLowerCase().includes(query) ||
          (p.name || "").toLowerCase().includes(query) ||
          (p.id || "").toLowerCase().includes(query) ||
          (p.category || "").toLowerCase().includes(query) ||
          (p.description || "").toLowerCase().includes(query) ||
          (p.skills || []).some(s => s.toLowerCase().includes(query));
        return matchesTab && matchesCat && matchesQuery;
      });
      if (countBadge) {
        countBadge.innerText = `${filtered.length} ${filtered.length === 1 ? 'Profil' : 'Profile'}`;
      }
      if (filtered.length === 0) {
        container.innerHTML = `<div class="text-center py-6 text-xs text-[var(--muted-foreground)] font-mono">${catalogCollapsed ? '—' : 'Keine Profile gefunden.'}</div>`;
        return;
      }
      filtered.forEach(prof => {
        const isSelected = prof.id === currentSelectedProfileId;
        const skillsCount = (prof.skills || []).length;
        const avatarUrl = getProfileAvatarUrl(prof);
        const personName = prof.person_name || prof.name || prof.id;
        const roleName = prof.name || prof.id;
        const isFav = prof.is_favorite === true;
        const isDeployed = isProfileDeployedActive(prof);
        const runtimeStatus = prof.runtime_status || (isDeployed ? 'active' : '');
        const coreAgents = ['default', 'micha', 'executive_decision_architect', 'labor_law_hr_governance'];
        const isOnMission = runtimeStatus === 'active' && !coreAgents.includes(prof.id) && prof.current_task_id;
        if (catalogCollapsed) {
          // 68px Icon-Rail Ansicht mit 44px (w-11 h-11) Avatar
          const item = document.createElement("div");
          item.setAttribute("data-profile-id", prof.id);
          item.onclick = () => selectProfileForEditor(prof.id);
          item.title = `${personName} (${roleName})\nStatus: ${isDeployed ? 'Aktiv' : 'Inaktiv'}\nID: ${prof.id}`;
          item.className = `cursor-pointer relative p-1 rounded-2xl flex items-center justify-center transition-all duration-150 ${
            isSelected 
              ? 'bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900 ring-2 ring-zinc-500 shadow-xs' 
              : 'hover:bg-[var(--secondary)] text-[var(--foreground)]'
          }`;
          item.innerHTML = `
            <div class="relative w-11 h-11 shrink-0">
              <img src="${avatarUrl}" alt="${escapeHtml(personName)}" class="w-full h-full rounded-full object-cover border-2 border-[var(--border)] bg-[var(--card)] shadow-xs" onerror="this.onerror=null; this.src=withAvatarRevision('/static/avatars/hermes_default_avatar.png');">
              <span class="absolute -bottom-0.5 -right-0.5 w-3 h-3 rounded-full border-2 border-[var(--background)] ${isDeployed ? 'bg-emerald-500' : 'bg-zinc-400'}"></span>
            </div>
          `;
          container.appendChild(item);
        } else {
          // 320px Schlanke Kartenansicht mit 56px (w-14 h-14) Avatar
          const card = document.createElement("div");
          card.setAttribute("data-profile-id", prof.id);
          card.onclick = () => selectProfileForEditor(prof.id);
          card.className = `prof-list-item p-2.5 cursor-pointer relative overflow-hidden bg-[var(--card)] border rounded-2xl transition-all duration-150 shadow-2xs ${
            isSelected 
              ? 'selected-item border-zinc-900 dark:border-zinc-100 ring-1 ring-zinc-900/20 dark:ring-zinc-100/20 bg-[var(--secondary)]/40' 
              : 'border-[var(--border)] hover:border-zinc-400 dark:hover:border-zinc-600'
          }`;
          let statusLabel = 'Inaktiv';
          let statusColor = 'text-[var(--muted-foreground)]';
          let ledColor = 'bg-zinc-400 dark:bg-zinc-600';
          let switchTooltip = 'Inaktiv im Agenten-Netzwerk (Klicken zum Aktivieren)';
          if (isDeployed) {
            statusLabel = 'Aktiv';
            statusColor = 'text-[var(--foreground)] font-bold';
            ledColor = 'bg-emerald-500';
            switchTooltip = 'Aktiv im Agenten-Netzwerk (Klicken zum Deaktivieren)';
          }
          card.innerHTML = `
            <div class="flex items-center gap-3">
              <div class="relative shrink-0">
                <img src="${avatarUrl}" alt="${escapeHtml(personName)}" class="w-14 h-14 rounded-full object-cover border-2 border-[var(--border)] bg-[var(--secondary)] shadow-xs" onerror="this.onerror=null; this.src=withAvatarRevision('/static/avatars/hermes_default_avatar.png');">
                <button type="button" onclick="toggleProfileFavorite('${prof.id}', event)" class="absolute -bottom-1 -left-1 w-5 h-5 rounded-full bg-[var(--card)] border border-[var(--border)] text-[10px] flex items-center justify-center cursor-pointer text-amber-500 shadow-2xs hover:scale-110 transition" title="${isFav ? 'Aus Favoriten entfernen' : 'Zu Favoriten hinzufügen'}">
                  ${isFav ? '⭐' : '☆'}
                </button>
              </div>
              <div class="min-w-0 flex-1 space-y-0.5">
                <div class="flex items-center justify-between gap-1">
                  <span class="font-bold text-xs sm:text-sm text-[var(--foreground)] truncate leading-snug">${escapeHtml(personName)}</span>
                  <span class="text-[9.5px] font-mono px-1.5 py-0.2 rounded bg-[var(--secondary)] text-[var(--muted-foreground)] border border-[var(--border)] shrink-0">
                    ${skillsCount} Sk.
                  </span>
                </div>
                <div class="text-[11px] font-medium text-[var(--muted-foreground)] truncate">${escapeHtml(roleName)}</div>
                <div class="flex items-center justify-between gap-1 pt-1 mt-1 border-t border-[var(--border)] text-[9.5px] font-mono">
                  <button type="button" onclick="toggleProfileDeployment('${prof.id}', ${!isDeployed}, event)" class="flex items-center gap-1.5 cursor-pointer hover:opacity-80 transition select-none" title="${switchTooltip}">
                    <span class="w-2 h-2 rounded-full ${ledColor}"></span>
                    <span class="${statusColor} uppercase">${statusLabel}</span>
                  </button>
                  <span class="text-[9px] text-[var(--muted-foreground)] truncate max-w-[110px]" title="${escapeHtml(prof.id)}">${escapeHtml(prof.id)}</span>
                </div>
              </div>
            </div>
          `;
          container.appendChild(card);
        }
      });
      if (window.lucide) lucide.createIcons();
    }
    function onProfileSearchOrFilter() {
      renderHermesProfilesList();
    }
    function filterProfilesByCategory(cat) {
      activeProfileCategoryFilter = cat;
      renderHermesProfilesList();
    }
    function createNewProfileDraft() {
      const draftId = `custom_agent_${Date.now()}`;
      const draftProfile = {
        id: draftId,
        person_name: "Neuer Spezialist",
        name: "Spezial-Agent Rolle",
        category: activeProfileCategoryFilter !== "all" ? activeProfileCategoryFilter : "1. Strategie, Führung & Lebensplanung",
        description: "Beschreibung der Kernkompetenzen und Aufgaben...",
        prompt: "Du bist ein erfahrener Spezialist in Archon OS. Deine Aufgabe ist es, Aufgaben präzise und lösungsorientiert auszuführen.",
        provider: "openrouter",
        model: "deepseek/deepseek-v4-flash-0731",
        skills: [],
        tools: typeof DEFAULT_HERMES_TOOLS !== 'undefined' ? [...DEFAULT_HERMES_TOOLS] : [],
        avatar: "/static/avatars/avatar_001.jpg",
        status: "active",
        is_favorite: false
      };
      
      hermesProfilesData.unshift(draftProfile);
      switchAgentCadreTab('overview');
      selectProfileForEditor(draftId);
      setTimeout(() => focusProfileNameInput(), 50);
    }
    function focusProfileNameInput() {
      switchAgentCadreTab('overview');
      const input = document.getElementById("prof-edit-person-name");
      if (input) {
        input.focus();
        input.select();
      }
    }
    function onProfilePersonNameInputChange(val) {
      const titleEl = document.getElementById("profile-editor-title");
      if (titleEl) {
        titleEl.innerText = val.trim() || "Neuer Agent";
      }
    }
    function onProfileNameInputChange(val) {
      const roleEl = document.getElementById("profile-editor-role");
      if (roleEl) {
        roleEl.innerText = val.trim() || "Rolle";
      }
    }
    function onProfileCategoryChange(val) {
      const catEl = document.getElementById("profile-editor-cat-tag");
      if (catEl) {
        catEl.innerText = val;
      }
    }
    function setAvatarValue(url, skipListRender = false) {
      const input = document.getElementById("prof-edit-avatar");
      const img = document.getElementById("prof-edit-avatar-preview");
      if (input) input.value = url;
      if (img) {
        img.src = withAvatarRevision(url || "/static/avatars/avatar_001.jpg");
      }
      if (currentSelectedProfileId && !skipListRender) {
        const prof = hermesProfilesData.find(p => p.id === currentSelectedProfileId);
        if (prof) {
          prof.avatar = url;
          prof.avatar_url = url;
          renderHermesProfilesList();
        }
      }
    }
    function triggerAvatarFileInput() {
      const input = document.getElementById("prof-avatar-file-input");
      if (input) input.click();
    }
    function processUploadedAvatarFile(file) {
      if (!file || !file.type.startsWith("image/")) {
        showArchonToast("Bitte eine gültige Bilddatei auswählen.", "error");
        return;
      }
      if (file.size > 10 * 1024 * 1024) {
        showArchonToast("Bild ist zu groß (max. 10 MB).", "error");
        return;
      }
      const reader = new FileReader();
      reader.onload = async function(evt) {
        const dataUrl = evt.target.result;
        setAvatarValue(dataUrl);
        if (currentSelectedProfileId && !currentSelectedProfileId.startsWith("custom_agent_")) {
          try {
            const res = await fetch(`/api/hermes/profiles/${currentSelectedProfileId}/avatar`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ image: dataUrl })
            });
            if (res.ok) {
              const data = await res.json();
              avatarDynamicRev = Date.now();
              const freshUrl = data.avatar_url;
              setAvatarValue(freshUrl);
              showArchonToast("Avatar erfolgreich gespeichert.", "success");
            }
          } catch(err) {
            console.warn("Avatar upload deferred to profile save:", err);
          }
        }
      };
      reader.readAsDataURL(file);
    }
    function handleAvatarFileSelected(e) {
      const file = e.target.files && e.target.files[0];
      if (!file) return;
      processUploadedAvatarFile(file);
      e.target.value = "";
    }
    function handleAvatarDragOver(e) {
      e.preventDefault();
      e.stopPropagation();
      const dropzone = document.getElementById("prof-avatar-dropzone");
      if (dropzone) dropzone.classList.add("ring-4", "ring-indigo-500", "scale-105");
    }
    function handleAvatarDragLeave(e) {
      e.preventDefault();
      e.stopPropagation();
      const dropzone = document.getElementById("prof-avatar-dropzone");
      if (dropzone) dropzone.classList.remove("ring-4", "ring-indigo-500", "scale-105");
    }
    function handleAvatarDrop(e) {
      e.preventDefault();
      e.stopPropagation();
      const dropzone = document.getElementById("prof-avatar-dropzone");
      if (dropzone) dropzone.classList.remove("ring-4", "ring-indigo-500", "scale-105");
      const file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      if (file) {
        processUploadedAvatarFile(file);
      }
    }
    window.addEventListener("paste", function(e) {
      const profilesTab = document.getElementById("tab-agent-profiles");
      if (!profilesTab || profilesTab.classList.contains("hidden")) return;
      if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA')) {
        if (!e.clipboardData || !e.clipboardData.types.includes('Files')) return;
      }
      const items = (e.clipboardData || window.clipboardData)?.items;
      if (!items) return;
      for (let i = 0; i < items.length; i++) {
        if (items[i].type && items[i].type.indexOf("image") !== -1) {
          const blob = items[i].getAsFile();
          if (blob) {
            e.preventDefault();
            processUploadedAvatarFile(blob);
            break;
          }
        }
      }
    });
    function handleDiceClick(e) {
      if (e) e.stopPropagation();
      const randIndex = Math.floor(Math.random() * ALL_AVATARS_LIST.length);
      const url = ALL_AVATARS_LIST[randIndex];
      setAvatarValue(url);
    }
    function resetAvatarToDefault(e) {
      if (e) e.stopPropagation();
      const prof = hermesProfilesData.find(p => p.id === currentSelectedProfileId);
      const defaultUrl = prof ? getProfileAvatarUrl(prof) : "/static/avatars/avatar_001.jpg";
      setAvatarValue(defaultUrl);
    }
    let currentAvatarColorFilter = "all";
    let avatarMetadataCache = null;
    const AVATAR_COLOR_CATEGORIES = [
      { id: "all", label: "Alle", badge: "174", dot: "bg-slate-400" },
      { id: "rot", label: "Rot", badge: "36", dot: "bg-rose-500" },
      { id: "orange", label: "Orange", badge: "31", dot: "bg-amber-500" },
      { id: "gelb", label: "Gelb", badge: "2", dot: "bg-yellow-400" },
      { id: "gruen", label: "Grün", badge: "24", dot: "bg-emerald-500" },
      { id: "tuerkis", label: "Türkis", badge: "14", dot: "bg-teal-400" },
      { id: "blau", label: "Blau", badge: "21", dot: "bg-sky-500" },
      { id: "lila", label: "Lila", badge: "2", dot: "bg-purple-500" },
      { id: "pink", label: "Pink", badge: "8", dot: "bg-pink-500" },
      { id: "braun", label: "Braun", badge: "6", dot: "bg-amber-800" },
      { id: "neutral", label: "Studio / Neutral", badge: "30", dot: "bg-slate-400" }
    ];
    async function loadAvatarMetadata() {
      if (!avatarMetadataCache) {
        try {
          const res = await fetch(`/static/avatars/avatars_metadata.json?t=${Date.now()}`, { cache: "no-store" });
          if (res.ok) {
            avatarMetadataCache = await res.json();
          }
        } catch (e) {
          console.warn("Konnte avatars_metadata.json nicht laden:", e);
        }
      }
      return avatarMetadataCache;
    }
    async function openAvatarLibraryModal(e) {
      if (e) e.stopPropagation();
      await loadAvatarMetadata();
      renderAvatarColorFilters();
      renderAvatarLibraryGrid();
      document.getElementById("avatar-picker-modal").classList.remove("hidden");
      lucide.createIcons();
    }
    function closeAvatarLibraryModal() {
      document.getElementById("avatar-picker-modal").classList.add("hidden");
    }
    function setAvatarColorFilter(groupId) {
      currentAvatarColorFilter = groupId;
      renderAvatarColorFilters();
      renderAvatarLibraryGrid();
    }
    function renderAvatarColorFilters() {
      const bar = document.getElementById("avatar-color-filters");
      if (!bar) return;
      bar.innerHTML = "";
      AVATAR_COLOR_CATEGORIES.forEach(cat => {
        const btn = document.createElement("button");
        btn.type = "button";
        const isActive = (currentAvatarColorFilter === cat.id);
        btn.className = `px-2.5 py-1 rounded-lg text-xs font-semibold font-mono flex items-center gap-1.5 transition cursor-pointer shrink-0 border ${
          isActive
            ? "!bg-[#EF233C] !text-white !border-[#EF233C] shadow-xs"
            : "!bg-white hover:!bg-slate-50 !text-slate-800 !border-slate-300 shadow-xs"
        }`;
        btn.onclick = () => setAvatarColorFilter(cat.id);
        btn.innerHTML = `
          <span class="w-2 h-2 rounded-full ${cat.dot}"></span>
          <span>${cat.label}</span>
          <span class="text-[10px] opacity-75">(${cat.badge})</span>
        `;
        bar.appendChild(btn);
      });
    }
    function renderAvatarLibraryGrid() {
      const grid = document.getElementById("avatar-library-grid");
      if (!grid) return;
      grid.innerHTML = "";
      const currentAvatar = (document.getElementById("prof-edit-avatar")?.value || "").trim();
      let itemsToShow = [];
      if (avatarMetadataCache && avatarMetadataCache.length > 0) {
        itemsToShow = avatarMetadataCache.filter(m => {
          if (currentAvatarColorFilter === "all") return true;
          return m.color_group === currentAvatarColorFilter;
        });
      } else {
        itemsToShow = ALL_AVATARS_LIST.slice(1).map((url, i) => ({
          url,
          filename: `avatar_${String(i+1).padStart(3, '0')}.jpg`,
          index: i + 1,
          color_name: "Avatar"
        }));
      }
      const countSpan = document.getElementById("avatar-library-count-text");
      if (countSpan) {
        countSpan.textContent = `${itemsToShow.length} von 174 Porträts angezeigt – farblich sortiert`;
      }
      itemsToShow.forEach((item) => {
        const url = item.url;
        const displayUrl = withAvatarRevision(url);
        const el = document.createElement("div");
        const isSel = (url === currentAvatar);
        el.className = `cursor-pointer p-2.5 rounded-2xl border transition flex flex-col items-center gap-2 hover:shadow-md ${
          isSel
            ? 'border-2 border-[#EF233C] bg-rose-50 dark:bg-rose-950/30 ring-2 ring-rose-300'
            : 'border-slate-200 dark:border-neutral-800 hover:border-slate-400 bg-white dark:bg-neutral-900'
        }`;
        el.onclick = () => {
          setAvatarValue(url);
          closeAvatarLibraryModal();
        };
        el.innerHTML = `
          <img src="${displayUrl}" alt="${item.filename || 'Avatar'}" class="w-28 h-28 sm:w-32 sm:h-32 rounded-full object-cover border-2 border-slate-200 dark:border-neutral-700 bg-slate-100 dark:bg-neutral-800 shadow-xs">
          <span class="text-xs font-mono font-medium text-slate-600 dark:text-slate-400 truncate w-full text-center">#${String(item.index || '').padStart(3, '0')}</span>
        `;
        grid.appendChild(el);
      });
    }
    // Globaler Cache und Modell-Lader für Hermes LLM-Provider
    window._llmProviderModelsCache = {};
    async function loadLlmModelsForProvider(provider) {
      const p = (provider || "openrouter").toLowerCase().trim();
      if (window._llmProviderModelsCache[p] && window._llmProviderModelsCache[p].length > 0) {
        return window._llmProviderModelsCache[p];
      }
      try {
        const res = await fetch(`/api/llm-providers/models?provider=${encodeURIComponent(p)}`);
        if (res.ok) {
          const data = await res.json();
          if (data && Array.isArray(data.models) && data.models.length > 0) {
            window._llmProviderModelsCache[p] = data.models;
            return data.models;
          }
        }
      } catch (e) {
        console.warn("[LLM] Error fetching models for", p, e);
      }
      // Standard-Fallbacklisten
      if (p === "google") {
        return ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.5-flash-image", "gemini-2.0-flash", "gemini-1.5-pro"];
      } else if (p === "openrouter") {
        return [
          "google/gemini-2.5-flash-image",
          "google/gemini-3.1-flash-image",
          "google/gemini-3-pro-image",
          "google/gemini-3.1-flash-lite-image",
          "openai/gpt-image-2",
          "openai/gpt-image-2.5-sunburst",
          "bytedance/seedream-4.5",
          "anthropic/claude-3.7-sonnet",
          "anthropic/claude-3.5-sonnet",
          "openai/gpt-4o",
          "openai/gpt-4o-mini",
          "deepseek/deepseek-chat",
          "meta-llama/llama-3.3-70b-instruct"
        ];
      } else if (p === "groq") {
        return ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"];
      } else if (p === "openai") {
        return ["gpt-4o", "gpt-4o-mini", "o1", "o3-mini", "dall-e-3"];
      } else if (p === "nvidia") {
        return ["nvidia/llama-3.1-nemotron-70b-instruct", "meta/llama-3.3-70b-instruct"];
      } else {
        return [
          "auto/best-coding", "auto/best-reasoning", "auto/best-vision", "auto/best-fast", "auto/best-chat",
          "deepseek-ai/DeepSeek-V4-Pro", "qwen/Qwen3.6-27B", "google/gemma-4-31B-it",
          "meta-llama/Llama-4-Scout-17B-16E-Instruct", "CohereLabs/command-a-vision-07-2025", "omniroute/free-forever"
        ];
      }
    }
    window.loadLlmModelsForProvider = loadLlmModelsForProvider;
    window.fetchProviderModelsList = loadLlmModelsForProvider;
    function populateModelDropdown(selectEl, models, selectedModel) {
      if (!selectEl) return;
      const validModels = (Array.isArray(models) && models.length > 0) 
        ? models 
        : ["google/gemini-2.5-flash-image", "anthropic/claude-3.7-sonnet", "deepseek/deepseek-v3", "meta-llama/llama-3.3-70b-instruct"];
      
      // Modus 1: HTML5 Input mit Datalist (wie Hermes Desktop App)
      if (selectEl.tagName === "INPUT") {
        const listId = selectEl.getAttribute("list") || "prof-edit-model-datalist";
        let dl = document.getElementById(listId);
        if (!dl) {
          dl = document.createElement("datalist");
          dl.id = listId;
          selectEl.setAttribute("list", listId);
          selectEl.parentNode.appendChild(dl);
        }
        dl.innerHTML = "";
        validModels.forEach(m => {
          const opt = document.createElement("option");
          opt.value = m;
          dl.appendChild(opt);
        });
        if (selectedModel) {
          selectEl.value = selectedModel;
        } else if (!selectEl.value && validModels.length > 0) {
          selectEl.value = validModels[0];
        }
        return;
      }
      // Modus 2: Klassisches SELECT Element mit Freitext-Option
      selectEl.innerHTML = "";
      let found = false;
      validModels.forEach(m => {
        const opt = document.createElement("option");
        opt.value = m;
        opt.textContent = m;
        if (m === selectedModel) {
          opt.selected = true;
          found = true;
        }
        selectEl.appendChild(opt);
      });
      // Eigenes Modell manuell eingeben Option hinzufügen
      const customOpt = document.createElement("option");
      customOpt.value = "__CUSTOM__";
      customOpt.textContent = "+ Eigenes Modell manuell eingeben...";
      selectEl.appendChild(customOpt);
      if (!found && selectedModel && selectedModel !== "free-forever" && selectedModel !== "Keine Modelle geladen") {
        const opt = document.createElement("option");
        opt.value = selectedModel;
        opt.textContent = `${selectedModel} (Aktuell)`;
        opt.selected = true;
        selectEl.insertBefore(opt, selectEl.firstChild);
      } else if (!found && validModels.length > 0) {
        selectEl.selectedIndex = 0;
      }
    }
    function handleCustomModelOption(selectEl) {
      if (!selectEl || selectEl.value !== "__CUSTOM__") return false;
      const custom = prompt("Gib die genaue Modell-ID ein (z. B. google/gemini-2.5-flash-image oder bytedance/seedream-4.5):");
      if (custom && custom.trim()) {
        const val = custom.trim();
        const opt = document.createElement("option");
        opt.value = val;
        opt.textContent = `${val} (Benutzerdefiniert)`;
        opt.selected = true;
        selectEl.insertBefore(opt, selectEl.firstChild);
        selectEl.value = val;
        return true;
      }
      selectEl.selectedIndex = 0;
      return false;
    }
    window.handleCustomModelOption = handleCustomModelOption;
    function setProfileModelPreset(modelId, provider) {
      const provSelect = document.getElementById("prof-edit-provider");
      const modInput = document.getElementById("prof-edit-model");
      if (provSelect && provider) {
        provSelect.value = provider;
        onProfileProviderChange(provider, modelId);
      } else if (modInput) {
        modInput.value = modelId;
      }
      const label = document.getElementById("prof-active-model-label");
      if (label) label.innerText = `aktiv: ${modelId}`;
    }
    window.setProfileModelPreset = setProfileModelPreset;
    function selectProfileForEditor(profileId) {
      currentSelectedProfileId = profileId;
      if (profileId && !profileId.startsWith("custom_agent_")) {
        try { localStorage.setItem("archon_active_profile_id", profileId); } catch(e){}
      }
      const listContainer = document.getElementById("hermes-profiles-list");
      const existingNodes = listContainer ? listContainer.querySelectorAll("[data-profile-id]") : [];
      if (existingNodes.length > 0 && listContainer.querySelector(`[data-profile-id="${CSS.escape(profileId)}"]`)) {
        existingNodes.forEach(node => {
          const isSel = node.getAttribute("data-profile-id") === profileId;
          if (catalogCollapsed) {
            node.className = `cursor-pointer relative p-1 rounded-2xl flex items-center justify-center transition-all duration-150 ${
              isSel
                ? 'bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900 ring-2 ring-zinc-500 shadow-xs'
                : 'hover:bg-[var(--secondary)] text-[var(--foreground)]'
            }`;
          } else {
            node.className = `prof-list-item p-2.5 cursor-pointer relative overflow-hidden bg-[var(--card)] border rounded-2xl transition-all duration-150 shadow-2xs ${
              isSel
                ? 'selected-item border-zinc-900 dark:border-zinc-100 ring-1 ring-zinc-900/20 dark:ring-zinc-100/20 bg-[var(--secondary)]/40'
                : 'border-[var(--border)] hover:border-zinc-400 dark:hover:border-zinc-600'
            }`;
          }
        });
      } else {
        renderHermesProfilesList();
      }
      const prof = hermesProfilesData.find(p => p.id === profileId);
      if (!prof) return;
      const personName = prof.person_name || prof.name || "Profil";
      const roleName = prof.name || prof.id || "";
      const avatarUrl = getProfileAvatarUrl(prof);
      // Header befüllen
      const titleEl = document.getElementById("profile-editor-title");
      if (titleEl) titleEl.innerText = personName;
      
      const roleEl = document.getElementById("profile-editor-role");
      if (roleEl) roleEl.innerText = roleName;
      const catTag = document.getElementById("profile-editor-cat-tag");
      if (catTag) catTag.innerText = prof.category || '1. Strategie, Führung & Lebensplanung';
      const idTag = document.getElementById("profile-editor-id-tag");
      if (idTag) idTag.innerText = `id: ${prof.id}`;
      const statusTag = document.getElementById("profile-editor-status-tag");
      const isDeployed = isProfileDeployedActive(prof);
      const pcAgent = getProfilePaperclipAgent(prof);
      const pcStatus = pcAgent ? (pcAgent.status || '').toLowerCase().trim() : '';
      if (statusTag) {
        if (isDeployed) {
          statusTag.className = "inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-mono font-bold bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20";
          statusTag.innerHTML = `<span class="w-1.5 h-1.5 rounded-full bg-emerald-500"></span> Bereit (Aktiv)`;
        } else if (pcStatus === 'terminated') {
          statusTag.className = "inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-mono font-bold bg-zinc-500/10 text-zinc-500 border border-zinc-500/20";
          statusTag.innerHTML = `<span class="w-1.5 h-1.5 rounded-full bg-zinc-400"></span> Terminiert`;
        } else {
          statusTag.className = "inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-mono font-bold bg-zinc-500/10 text-zinc-600 dark:text-zinc-400 border border-zinc-500/20";
          statusTag.innerHTML = `<span class="w-1.5 h-1.5 rounded-full bg-zinc-400"></span> Bereit (Standby)`;
        }
      }
      setAvatarValue(avatarUrl, true);
      // Reiter 1 (Übersicht) befüllen
      const personNameEl = document.getElementById("prof-edit-person-name");
      if (personNameEl) personNameEl.value = prof.person_name || "";
      
      const nameEl = document.getElementById("prof-edit-name");
      if (nameEl) nameEl.value = prof.name || "";
      
      const idEl = document.getElementById("prof-edit-id");
      if (idEl) {
        idEl.value = prof.id || "";
        idEl.readOnly = false;
      }
      
      const catEl = document.getElementById("prof-edit-category");
      if (catEl) catEl.value = prof.category || "1. Strategie, Führung & Lebensplanung";
      
      const descEl = document.getElementById("prof-edit-desc");
      if (descEl) descEl.value = prof.description || "";
      const promptEl = document.getElementById("prof-edit-prompt");
      if (promptEl) promptEl.value = prof.prompt || prof.system_prompt || "";
      const providerSelect = document.getElementById("prof-edit-provider");
      const initialProv = prof.provider || (prof.model && prof.model.includes("gemini") ? "google" : "openrouter");
      if (providerSelect) {
        providerSelect.value = initialProv;
      }
      onProfileProviderChange(initialProv, prof.model);
      const reasoningSelect = document.getElementById("prof-edit-reasoning");
      if (reasoningSelect) {
        reasoningSelect.value = prof.reasoning_level || "medium";
      }
      const chatReasoningSelect = document.getElementById("agent-tab-reasoning-select");
      if (chatReasoningSelect) {
        chatReasoningSelect.value = prof.reasoning_level || "medium";
      }
      if (typeof populateAgentTabModelSelect === "function") {
        populateAgentTabModelSelect();
      }
      // KPI Bar befüllen
      const callsignInput = document.getElementById("prof-edit-callsign");
      if (callsignInput) {
        let defCallsign = prof.callsign || "";
        if (!defCallsign) {
          if (prof.id === "executive_decision_architect") defCallsign = "robert";
          else if (prof.id === "micha") defCallsign = "micha";
        }
        callsignInput.value = defCallsign;
      }
      const kpiDomain = document.getElementById("kpi-val-domain");
      if (kpiDomain) kpiDomain.innerText = prof.category || "1. Strategie, Führung";
      const kpiSupervisor = document.getElementById("kpi-val-supervisor");
      if (kpiSupervisor) {
        const isRoot = prof.id === "hermes_default" || prof.id === "micha";
        const isBoard = prof.id === "executive_decision_architect";
        kpiSupervisor.innerText = isRoot ? "Michael Keller (Owner / CEO)" : (isBoard ? "Hermes Master System" : "Alexander Richter (Decision Lead)");
      }
      const kpiTasks = document.getElementById("kpi-val-tasks");
      const kpiSuccess = document.getElementById("kpi-val-success");
      if (kpiTasks) {
        kpiTasks.innerText = "Lade Akte...";
        fetch(`/api/v1/agent/${encodeURIComponent(profileId)}/stats`)
          .then(r => r.json())
          .then(stats => {
            if (stats && stats.status === "ok") {
              const count = stats.tasks_completed || 0;
              const lCount = stats.learnings_count || 0;
              kpiTasks.innerText = `${count} ${count === 1 ? 'Einsatz' : 'Einsätze'} (${lCount} ${lCount === 1 ? 'Learning' : 'Learnings'})`;
              if (kpiSuccess) {
                kpiSuccess.innerText = count > 0 ? "100% (Verifiziert)" : (isProfileDeployedActive(prof) ? "100% (Bereit)" : "Standby");
              }
            } else {
              kpiTasks.innerText = "0 Einsätze";
            }
          })
          .catch(() => {
            kpiTasks.innerText = "0 Einsätze (Standby)";
          });
      }
      // Reiter 2: Skills & Tools befüllen
      renderActiveProfileSkillsTags(prof.skills || []);
      renderActiveProfileTools(prof.tools || []);
      // Dispatch Tab-spezifischer Lader
      if (activeAgentCadreTab === 'overview') {
        loadAgentLiveActivity(profileId);
        loadAgentProjectsHistory(profileId);
      } else if (activeAgentCadreTab === 'soul') {
        loadInlineSoulMarkdown(profileId);
      } else if (activeAgentCadreTab === 'personalakte') {
        loadInlinePersonalakte(profileId);
      } else if (activeAgentCadreTab === 'chat') {
        loadAgentTabChatSessions(profileId);
      }
      // Operations Tab Daten
      const pcStatusEl = document.getElementById("operations-pane-status");
      if (pcStatusEl) {
        pcStatusEl.innerHTML = isDeployed 
          ? `<span class="w-2 h-2 rounded-full bg-emerald-500"></span> Bereit im Agenten-Netzwerk` 
          : `<span class="w-2 h-2 rounded-full bg-zinc-400"></span> Inaktiv / Standby`;
      }
      const tasksCountEl = document.getElementById("operations-tasks-count");
      const tasksListEl = document.getElementById("operations-assigned-tasks-list");
      if (tasksListEl) {
        const agentTasks = (opsKanbanData?.tasks || []).filter(t => t.assignee === profileId);
        if (tasksCountEl) tasksCountEl.innerText = `${agentTasks.length} aktive Tasks`;
        if (agentTasks.length === 0) {
          tasksListEl.innerHTML = `<div class="p-3 text-center text-xs text-[var(--muted-foreground)] font-mono">Keine aktiven Aufgaben zugewiesen. Klicke auf '+ Aufgabe zuweisen', um einen Task im Operations Center zu starten.</div>`;
        } else {
          tasksListEl.innerHTML = agentTasks.map(t => `
            <div class="p-2.5 rounded-lg bg-[var(--card)] border border-[var(--border)] flex items-center justify-between">
              <div>
                <div class="font-bold text-xs text-[var(--foreground)]">${opsEscapeHtml(t.title)}</div>
                <div class="text-[10px] text-[var(--muted-foreground)] font-mono">Spalte: ${opsEscapeHtml(t.column_id)} | Priorität: ${opsEscapeHtml(t.priority)}</div>
              </div>
              <span class="px-2 py-0.5 rounded text-[9.5px] font-mono bg-indigo-500/10 text-indigo-500 font-bold border border-indigo-500/20">${opsEscapeHtml(t.column_id)}</span>
            </div>
          `).join('');
        }
      }
      // Gateway Manager Widget
      if (typeof updateGatewayWidgetForCurrentProfile === "function") {
        updateGatewayWidgetForCurrentProfile();
      }
      if (window.lucide) lucide.createIcons();
    }
    async function deleteCurrentProfile() {
      if (!currentSelectedProfileId) {
        alert("Kein Profil ausgewählt.");
        return;
      }
      const prof = hermesProfilesData.find(p => p.id === currentSelectedProfileId);
      const name = prof ? (prof.person_name || prof.name) : currentSelectedProfileId;
      
      if (!confirm(`Möchtest du das Agenten-Profil '${name}' (${currentSelectedProfileId}) wirklich unwiderruflich löschen?`)) {
        return;
      }
      try {
        const res = await fetch(`/api/hermes/profiles/${encodeURIComponent(currentSelectedProfileId)}`, {
          method: "DELETE"
        });
        if (res.ok) {
          let delData = null; try { delData = await res.clone().json(); } catch(e) {} if (delData && delData.status === "pending_owner_approval" && delData.gate_id) { if (confirm(`🔐 Sicherheits-Gate (${delData.gate_id}):\n${delData.message || "Profil-Löschung erfordert Owner-Bestätigung."}\n\nMöchtest du die Löschung direkt hier im Browser freigeben?`)) { await fetch(`/api/permission-gates/${encodeURIComponent(delData.gate_id)}/decide`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ decision: "approve" }) }); } else { showArchonToast("🔐 " + (delData.message || "Warte auf Telegram-Bestätigung."), "info"); return; } }
          showArchonToast(`Profil '${name}' erfolgreich gelöscht!`, "success");
          await loadHermesProfilesFromServer();
          if (hermesProfilesData.length > 0) {
            selectProfileForEditor(hermesProfilesData[0].id);
          } else {
            createNewProfileDraft();
          }
        } else {
          const err = await res.json().catch(() => ({}));
          showArchonToast(`Fehler beim Löschen: ${err.detail || res.statusText}`, "error");
        }
      } catch (err) {
        showArchonToast(`Verbindungsfehler beim Löschen: ${err.message}`, "error");
      }
    }
    // =========================================================================
    // INLINE SOUL.MD LOGIK (REITER 4)
    // =========================================================================
    async function loadInlineSoulMarkdown(agentId) {
      const id = agentId || currentSelectedProfileId || "hermes_default";
      const pathLabel = document.getElementById("prof-soul-path-label");
      const statusEl = document.getElementById("prof-soul-save-status");
      const textarea = document.getElementById("prof-soul-inline-editor");
      if (pathLabel) pathLabel.innerText = `~/.hermes/profiles/${id}/SOUL.md`;
      if (statusEl) statusEl.innerText = "Lade SOUL.md...";
      if (textarea) textarea.value = "";
      try {
        const res = await fetch(`/api/v1/hermes/soul/${id}`);
        if (res.ok) {
          const data = await res.json();
          if (data && typeof data.markdown === "string") {
            if (textarea) textarea.value = data.markdown;
            if (statusEl) statusEl.innerText = "Synchronisiert";
          }
        } else {
          if (statusEl) statusEl.innerText = "Standard / Neu";
        }
      } catch (e) {
        if (statusEl) statusEl.innerText = "Fehler beim Laden";
      }
    }
    async function saveInlineSoulMarkdown(agentId) {
      const id = agentId || currentSelectedProfileId || "hermes_default";
      const textarea = document.getElementById("prof-soul-inline-editor");
      const statusEl = document.getElementById("prof-soul-save-status");
      if (!textarea) return;
      const markdown = textarea.value;
      if (statusEl) statusEl.innerText = "Speichere...";
      try {
        const res = await fetch(`/api/v1/hermes/soul/${id}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ markdown })
        });
        if (res.ok) {
          if (statusEl) {
            statusEl.innerText = "✅ Gespeichert";
            setTimeout(() => { if (statusEl) statusEl.innerText = "Synchronisiert"; }, 3000);
          }
          showArchonToast(`SOUL.md für ${id} gespeichert!`, "success");
        } else {
          if (statusEl) statusEl.innerText = "❌ Fehler";
          showArchonToast(`Fehler beim Speichern der SOUL.md`, "error");
        }
      } catch (e) {
        if (statusEl) statusEl.innerText = "❌ Verbindungsfehler";
        showArchonToast(`Verbindungsfehler: ${e.message}`, "error");
      }
    }
    // =========================================================================
    // INLINE PERSONALAKTE LOGIK (REITER 5)
    // =========================================================================
    function toggleInlinePersonalakteView(mode) {
      inlinePersonalakteViewMode = mode || (inlinePersonalakteViewMode === 'dossier' ? 'raw' : 'dossier');
      const btnDossier = document.getElementById("btn-pa-inline-dossier");
      const btnRaw = document.getElementById("btn-pa-inline-raw");
      const dossierView = document.getElementById("pa-inline-dossier-view");
      const rawView = document.getElementById("pa-inline-raw-view");
      if (inlinePersonalakteViewMode === 'dossier') {
        if (btnDossier) {
          btnDossier.className = "px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-[var(--card)] text-[var(--foreground)] shadow-2xs cursor-pointer";
        }
        if (btnRaw) {
          btnRaw.className = "px-2 py-0.5 rounded text-[10px] font-mono text-[var(--muted-foreground)] hover:text-[var(--foreground)] bg-transparent cursor-pointer";
        }
        if (dossierView) dossierView.classList.remove("hidden");
        if (rawView) rawView.classList.add("hidden");
      } else {
        if (btnDossier) {
          btnDossier.className = "px-2 py-0.5 rounded text-[10px] font-mono text-[var(--muted-foreground)] hover:text-[var(--foreground)] bg-transparent cursor-pointer";
        }
        if (btnRaw) {
          btnRaw.className = "px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-[var(--card)] text-[var(--foreground)] shadow-2xs cursor-pointer";
        }
        if (dossierView) dossierView.classList.add("hidden");
        if (rawView) rawView.classList.remove("hidden");
      }
      if (window.lucide) lucide.createIcons();
    }
    async function loadInlinePersonalakte(agentId) {
      const id = agentId || currentSelectedProfileId || "hermes_default";
      const prof = hermesProfilesData.find(p => p.id === id) || { id, person_name: id, name: id, category: "Strategie" };
      
      const pathLabel = document.getElementById("pa-inline-path");
      if (pathLabel) pathLabel.innerText = `00_HR_Agenten/Personalakten/${id}.md`;
      
      const nameEl = document.getElementById("pa-inline-person-name");
      if (nameEl) nameEl.innerText = prof.person_name || prof.name || id;
      
      const roleEl = document.getElementById("pa-inline-role-name");
      if (roleEl) roleEl.innerText = prof.name || id;
      
      const supEl = document.getElementById("pa-inline-supervisor");
      if (supEl) {
        const isRoot = prof.id === "hermes_default" || prof.id === "micha";
        const isBoard = prof.id === "executive_decision_architect";
        supEl.innerText = isRoot ? "[[Michael Keller (Owner / CEO)]]" : (isBoard ? "[[Hermes Master System]]" : "[[Alexander Richter (Decision Lead)]]");
      }
      const descEl = document.getElementById("pa-inline-desc");
      if (descEl) descEl.innerText = prof.description || "Autonome Fach-Exekution im Archon OS Netzwerk.";
      const skillsContainer = document.getElementById("pa-inline-skills-list");
      if (skillsContainer) {
        const skills = prof.skills || [];
        if (skills.length === 0) {
          skillsContainer.innerHTML = `<span class="text-[10px] text-[var(--muted-foreground)] italic">Keine expliziten Fach-Skills zugeordnet.</span>`;
        } else {
          skillsContainer.innerHTML = skills.map(sk => `
            <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono bg-[var(--secondary)] text-[var(--foreground)] border border-[var(--border)] font-bold">
              <span class="w-1.5 h-1.5 rounded-full bg-emerald-500"></span> ${escapeHtml(sk)}
            </span>
          `).join('');
        }
      }
      const statusEl = document.getElementById("pa-inline-save-status");
      const rawTextarea = document.getElementById("pa-inline-raw-markdown");
      if (statusEl) statusEl.innerText = "Lade Akte...";
      
      try {
        const res = await fetch(`/api/v1/hr/personalakte/${id}`);
        if (res.ok) {
          const data = await res.json();
          if (data && data.markdown) {
            if (rawTextarea) rawTextarea.value = data.markdown;
            
            const renderedDiv = document.getElementById("pa-inline-rendered-markdown");
            if (renderedDiv) {
              renderedDiv.innerHTML = formatMarkdownText(data.markdown);
            }
            if (statusEl) statusEl.innerText = "Synchronisiert";
            // Frontmatter parsen um Stammdaten exakt abzugleichen
            const md = data.markdown;
            const pNameM = md.match(/person_name:\s*([^\n]+)/);
            if (pNameM && nameEl) nameEl.innerText = pNameM[1].trim();
            const roleM = md.match(/name:\s*([^\n]+)/);
            if (roleM && roleEl) roleEl.innerText = roleM[1].trim();
            const supM = md.match(/supervisor:\s*([^\n]+)/);
            if (supM && supEl) supEl.innerText = supM[1].trim();
            const descM = md.match(/description:\s*([^\n]+)/);
            if (descM && descEl) descEl.innerText = descM[1].trim();
          }
        } else {
          if (statusEl) statusEl.innerText = "Bereit (Standard)";
        }
      } catch (e) {
        if (statusEl) statusEl.innerText = "Fehler beim Laden";
      }
    }
    async function saveInlinePersonalakteMarkdown(agentId) {
      const id = agentId || currentSelectedProfileId || "hermes_default";
      const rawTextarea = document.getElementById("pa-inline-raw-markdown");
      const statusEl = document.getElementById("pa-inline-save-status");
      const renderedDiv = document.getElementById("pa-inline-rendered-markdown");
      if (!rawTextarea) return;
      const markdown = rawTextarea.value;
      if (statusEl) statusEl.innerText = "Speichere in Obsidian...";
      try {
        const res = await fetch(`/api/v1/hr/personalakte/${id}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ markdown })
        });
        if (res.ok) {
          if (renderedDiv) renderedDiv.innerHTML = formatMarkdownText(markdown);
          if (statusEl) {
            statusEl.innerText = "✅ Gespeichert";
            setTimeout(() => { if (statusEl) statusEl.innerText = "Synchronisiert"; }, 3000);
          }
          showArchonToast(`Personalakte für ${id} in Obsidian gespeichert!`, "success");
        } else {
          if (statusEl) statusEl.innerText = "❌ Fehler";
          showArchonToast(`Fehler beim Speichern der Personalakte`, "error");
        }
      } catch (e) {
        if (statusEl) statusEl.innerText = "❌ Verbindungsfehler";
        showArchonToast(`Verbindungsfehler: ${e.message}`, "error");
      }
    }
    // =========================================================================
    // INLINE PERSISTENTER TAB-CHAT LOGIK (REITER 3 - SYNCHRONISIERT MIT MASTER-KONSOLE)
    // =========================================================================
    let currentAgentTabSessionId = null;
    let currentAgentTabAttachments = [];
    let isAgentTabGenerating = false;
    let isAgentTabDictating = false;
    let agentTabDictationRecognition = null;
    let currentAgentTabModel = null;
    let currentAgentTabMode = "direct"; // 'direct' | 'mission'
    function toggleAgentTabModeSwitch() {
      const nextMode = currentAgentTabMode === "mission" ? "direct" : "mission";
      setAgentTabMode(nextMode);
    }
    function syncAgentTabSwitchUI(mode) {
      const flatDirect = document.getElementById("agent-tab-flat-direct");
      const flatMission = document.getElementById("agent-tab-flat-mission");
      const inputEl = document.getElementById("agent-tab-chat-input");
      if (mode === "mission") {
        if (flatDirect) {
          flatDirect.className = "px-2 py-0.5 rounded text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition-all cursor-pointer";
        }
        if (flatMission) {
          flatMission.className = "px-2 py-0.5 rounded font-bold transition-all bg-[var(--card)] text-[var(--foreground)] shadow-2xs cursor-pointer";
        }
        if (inputEl) inputEl.placeholder = "Missions-Auftrag formulieren (wird als Task in Operations angelegt und im Approval Gate gestoppt)...";
      } else {
        if (flatDirect) {
          flatDirect.className = "px-2 py-0.5 rounded font-bold transition-all bg-[var(--card)] text-[var(--foreground)] shadow-2xs cursor-pointer";
        }
        if (flatMission) {
          flatMission.className = "px-2 py-0.5 rounded text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition-all cursor-pointer";
        }
        if (inputEl) inputEl.placeholder = "Nachricht an diesen Agenten eingeben (Enter zum Senden, Shift+Enter für Zeilenumbruch)...";
      }
    }
    function setAgentTabMode(mode) {
      currentAgentTabMode = mode;
      syncAgentTabSwitchUI(mode);
    }
    async function loadAgentTabChatSessions(agentId) {
      const id = agentId || currentSelectedProfileId || "default";
      const select = document.getElementById("agent-chat-session-select");
      if (!select) return;
      select.innerHTML = '<option value="">Lade Sitzungen...</option>';
      populateAgentTabModelSelect();
      syncAgentTabSwitchUI(currentAgentTabMode);
      // JEV State auch für Agent Tab synchronisieren
      const masterJevState = document.getElementById("master-chat-jev-state")?.innerText === "ON";
      updateJevStatusPill(masterJevState);
      let agentSessions = [];
      try {
        const res = await fetch(`/api/chat/sessions?profile_id=${encodeURIComponent(id)}`);
        if (res.ok) {
          const data = await res.json();
          const list = Array.isArray(data.sessions) ? data.sessions : [];
          // Strikte Filterung: Nur Sitzungen DIESES spezifischen Agenten!
          agentSessions = list.filter(s => {
            if (!s) return false;
            if (id === "default") {
              if (s.profile_name === "default" || !s.profile_name || s.profile_name === "") return true;
              if (s.id && (s.id.endsWith(`_default`) || s.id.includes(`_default_`))) return true;
              return false;
            }
            if (s.profile_name === id) return true;
            if (s.id && (s.id.endsWith(`_${id}`) || s.id.includes(`_${id}_`))) return true;
            return false;
          });
        }
      } catch (e) {
        console.warn("[AgentTabChat] Fehler beim Laden der Sessions für", id, e);
      }
      select.innerHTML = "";
      if (agentSessions.length === 0) {
        // Keine vorhandene Session für diesen Agenten -> neue isolierte Session anlegen
        const nowStr = new Date().toISOString().replace(/[-:T.]/g, "").slice(0, 14);
        const newSessionId = `mc_${nowStr}_${id}`;
        currentAgentTabSessionId = newSessionId;
        const opt = document.createElement("option");
        opt.value = newSessionId;
        opt.innerText = `Neuer Chat (${new Date().toLocaleTimeString("de-DE", { hour: '2-digit', minute: '2-digit' })})`;
        select.appendChild(opt);
        select.value = newSessionId;
        renderAgentTabEmptyWelcome();
        return;
      }
      // Prüfe, ob die bisherige Session wirklich zu DIESEM Agenten gehört
      const currentBelongsToAgent = agentSessions.some(s => s.id === currentAgentTabSessionId);
      if (!currentBelongsToAgent) {
        // Sofort auf die neueste eigene Session dieses Agenten wechseln!
        currentAgentTabSessionId = agentSessions[0].id;
      }
      agentSessions.forEach(s => {
        const opt = document.createElement("option");
        opt.value = s.id;
        let rawTitle = (s.title && s.title.trim()) ? s.title.trim() : (s.id || "Chat");
        if ((id === "telegram_bot" || (s.source || "").toLowerCase() === "telegram") && (!rawTitle || rawTitle === "Analyze uploaded image" || rawTitle === "New Session")) {
          rawTitle = "Telegram Bot (Live-Stream)";
        }
        const title = rawTitle.length > 55 ? rawTitle.slice(0, 52) + "..." : rawTitle;
        const msgs = s.message_count ? `${s.message_count} Msgs` : "0 Msgs";
        const dateStr = s.last_activity_at_formatted || s.started_at_formatted;
        const date = dateStr ? ` · Zuletzt: ${dateStr}` : "";
        opt.innerText = `${title} (${msgs}${date})`;
        if (s.id === currentAgentTabSessionId) {
          opt.selected = true;
        }
        select.appendChild(opt);
      });
      select.value = currentAgentTabSessionId;
      await loadAgentTabChatMessages(currentAgentTabSessionId);
    }
    function createNewAgentChatSession() {
      const id = currentSelectedProfileId || "default";
      const nowStr = new Date().toISOString().replace(/[-:T.]/g, "").slice(0, 14);
      const newSessionId = `mc_${nowStr}_${id}`;
      currentAgentTabSessionId = newSessionId;
      const select = document.getElementById("agent-chat-session-select");
      if (select) {
        const opt = document.createElement("option");
        opt.value = newSessionId;
        opt.innerText = `Neuer Chat (${new Date().toLocaleTimeString("de-DE", { hour: '2-digit', minute: '2-digit' })})`;
        opt.selected = true;
        select.insertBefore(opt, select.firstChild);
        select.value = newSessionId;
      }
      removeAgentTabAttachment();
      const inputEl = document.getElementById("agent-tab-chat-input");
      if (inputEl) {
        inputEl.value = "";
        inputEl.focus();
      }
      renderAgentTabEmptyWelcome();
    }
    async function renameCurrentAgentTabSession() {
      const select = document.getElementById("agent-chat-session-select");
      if (!select || !select.value) return;
      const sId = select.value;
      const opt = select.options[select.selectedIndex];
      const currentTitle = opt ? opt.text.split(" (")[0] : "";
      if (typeof promptRenameSession === "function") {
        await promptRenameSession(sId, currentTitle);
        if (typeof loadAgentTabChatSessions === "function") {
          await loadAgentTabChatSessions(currentSelectedProfileId);
        }
      }
    }
    async function loadAgentTabChatMessages(sessionId) {
      const sId = sessionId || currentAgentTabSessionId;
      if (!sId) return;
      currentAgentTabSessionId = sId;
      const container = document.getElementById("agent-tab-chat-messages");
      if (!container) return;
      container.innerHTML = `<div class="text-center text-xs text-slate-400 py-10 font-mono italic animate-pulse">Lade Nachrichtenverlauf...</div>`;
      try {
        const res = await fetch(`/api/chat/sessions/${encodeURIComponent(sId)}/messages`);
        if (res.ok) {
          const data = await res.json();
          const msgs = data.messages || [];
          container.innerHTML = "";
          if (msgs.length === 0) {
            renderAgentTabEmptyWelcome();
          } else {
            msgs.forEach(m => appendAgentTabMessageBubble(m.role, m.content, m.timestamp, m.id));
          }
          container.scrollTop = container.scrollHeight;
          requestAnimationFrame(() => {
            container.scrollTop = container.scrollHeight;
            setTimeout(() => { container.scrollTop = container.scrollHeight; }, 100);
          });
          if (window.lucide && typeof lucide.createIcons === "function") lucide.createIcons();
          return;
        }
      } catch (e) {
        console.warn("[AgentTabChat] Fehler beim Laden der Nachrichten:", e);
      }
      renderAgentTabEmptyWelcome();
    }
    function renderAgentTabEmptyWelcome() {
      const container = document.getElementById("agent-tab-chat-messages");
      if (!container) return;
      const agentId = currentSelectedProfileId || "default";
      const prof = hermesProfilesData.find(p => p.id === agentId);
      const name = prof ? (prof.person_name || prof.name) : "Hermes Agent";
      const role = prof ? (prof.description || prof.category || "Spezialist") : "Agenten-System";
      const avatarUrl = (typeof getProfileAvatarUrl === "function" && prof) ? getProfileAvatarUrl(prof) : (prof && prof.avatar ? prof.avatar : "/static/avatars/hermes_default_avatar.png");
      container.innerHTML = `
        <div class="h-full flex flex-col items-center justify-center p-6 text-center select-none space-y-4 my-auto">
          <div class="w-14 h-14 rounded-2xl border border-[var(--border)] overflow-hidden shadow-xs bg-[var(--secondary)] flex items-center justify-center">
            <img src="${avatarUrl}" class="w-full h-full object-cover" onerror="this.src='/static/avatars/avatar_001.jpg'">
          </div>
          <div class="space-y-1">
            <h4 class="font-bold text-sm text-[var(--foreground)]">${escapeHtml(name)}</h4>
            <p class="text-xs text-[var(--muted-foreground)] max-w-md">${escapeHtml(role)}</p>
          </div>
          <div class="flex flex-wrap items-center justify-center gap-1.5 pt-2 max-w-lg">
            <button type="button" onclick="insertAgentTabPromptTemplate('Was sind deine Kernkompetenzen und verfügbaren Werkzeuge?')" class="text-[11px] font-mono px-2.5 py-1 rounded-lg border border-[var(--border)] bg-[var(--card)] hover:bg-[var(--secondary)] text-[var(--foreground)] transition cursor-pointer shadow-2xs">
              🛠️ Werkzeuge & Skills
            </button>
            <button type="button" onclick="insertAgentTabPromptTemplate('Analysiere den aktuellen Projektstand und schlage nächste Schritte vor.')" class="text-[11px] font-mono px-2.5 py-1 rounded-lg border border-[var(--border)] bg-[var(--card)] hover:bg-[var(--secondary)] text-[var(--foreground)] transition cursor-pointer shadow-2xs">
              📊 Status & Empfehlungen
            </button>
            <button type="button" onclick="openSurePromptsModal('agent-tab')" class="text-[11px] font-mono px-2.5 py-1 rounded-lg border border-[var(--border)] bg-[var(--card)] hover:bg-[var(--secondary)] text-[var(--foreground)] transition cursor-pointer shadow-2xs">
              ✨ Archon Prompt Studio
            </button>
          </div>
        </div>
      `;
      if (window.lucide && typeof lucide.createIcons === "function") lucide.createIcons();
    }
    function insertAgentTabPromptTemplate(text) {
      const input = document.getElementById("agent-tab-chat-input");
      if (!input) return;
      input.value = text;
      autoResizeAgentTabInput(input);
      input.focus();
    }
    function appendAgentTabMessageBubble(role, content, timestamp, msgId) {
      const container = document.getElementById("agent-tab-chat-messages");
      if (!container) return;
      const safeContent = content == null ? "" : String(content);
      const isUser = role === "user";
      const div = document.createElement("div");
      div.className = `flex ${isUser ? 'justify-end' : 'justify-start'}`;
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
      const idStr = msgId ? `#msg-${msgId}` : `#msg-${Math.floor(1000 + Math.random() * 9000)}`;
      if (isUser) {
        div.innerHTML = `
          <div class="max-w-[85%] bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900 rounded-2xl rounded-br-xs px-4 py-2.5 shadow-xs min-w-[200px]">
            <div class="text-xs font-sans whitespace-pre-wrap leading-relaxed">${escapeHtml(safeContent)}</div>
            <div class="text-[9.5px] opacity-75 font-mono text-right mt-1.5 flex items-center justify-end gap-1.5 border-t border-white/10 dark:border-black/10 pt-1">
              <i data-lucide="clock" class="w-2.5 h-2.5"></i>
              <span>${dateFormatted}</span>
              <span class="opacity-60 ml-1">${idStr}</span>
            </div>
          </div>
        `;
      } else {
        const prof = hermesProfilesData.find(p => p.id === currentSelectedProfileId);
        const name = prof ? (prof.person_name || prof.name) : "Hermes Agent";
        const avatarUrl = (typeof getProfileAvatarUrl === "function" && prof) ? getProfileAvatarUrl(prof) : (prof && prof.avatar ? prof.avatar : "/static/avatars/hermes_default_avatar.png");
        div.innerHTML = `
          <div class="flex gap-2.5 max-w-[90%]">
            <div class="w-8 h-8 rounded-lg border border-[var(--border)] overflow-hidden shrink-0 mt-0.5 bg-[var(--secondary)] shadow-2xs">
              <img src="${avatarUrl}" class="w-full h-full object-cover" onerror="this.src='/static/avatars/avatar_001.jpg'">
            </div>
            <div class="bg-[var(--card)] border border-[var(--border)] text-[var(--foreground)] rounded-2xl rounded-tl-xs px-3.5 py-2.5 text-xs shadow-xs leading-relaxed space-y-1.5 flex-1 min-w-0">
              <div class="flex items-center justify-between gap-2 border-b border-[var(--border)] pb-1">
                <span class="font-bold text-xs font-mono text-[var(--foreground)] truncate">${escapeHtml(name)}</span>
                <div class="flex items-center gap-1">
                  <button type="button" class="copy-bubble-btn text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition p-0.5 rounded cursor-pointer" title="In Zwischenablage kopieren" onclick="copyAgentMessageText(this)" data-text="${escapeHtml(safeContent).replace(/"/g, '&quot;')}">
                    <i data-lucide="copy" class="w-3.5 h-3.5 text-black dark:text-white"></i>
                  </button>
                  <button type="button" class="speaker-btn text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition p-0.5 rounded cursor-pointer" title="Vorlesen" onclick="speakText(this.getAttribute('data-text'))" data-text="${escapeHtml(safeContent).replace(/"/g, '&quot;')}">
                    <i data-lucide="volume-2" class="w-3.5 h-3.5 text-black dark:text-white"></i>
                  </button>
                </div>
              </div>
              <div class="chat-markdown font-sans leading-relaxed text-[var(--foreground)] break-words">
                ${typeof formatMarkdownText === "function" ? formatMarkdownText(safeContent) : escapeHtml(safeContent)}
              </div>
              <div class="pt-1.5 border-t border-[var(--border)] flex items-center justify-between gap-2 text-[9px] font-mono text-[var(--muted-foreground)]">
                <span class="flex items-center gap-1 shrink-0"><i data-lucide="clock" class="w-2.5 h-2.5 text-black dark:text-white"></i>${dateFormatted}</span>
                <span class="shrink-0 font-medium">${idStr}</span>
              </div>
            </div>
          </div>
        `;
      }
      container.appendChild(div);
      container.scrollTop = container.scrollHeight;
      if (window.lucide && typeof lucide.createIcons === "function") lucide.createIcons();
    }
    async function sendAgentTabChatMessage() {
      if (isAgentTabGenerating) return;
      const inputEl = document.getElementById("agent-tab-chat-input");
      if (!inputEl) return;
      const text = inputEl.value.trim();
      const hasAttachments = currentAgentTabAttachments.length > 0;
      if (!text && !hasAttachments) return;
      if (isAgentTabDictating) {
        toggleAgentTabDictation();
      }
      inputEl.value = "";
      autoResizeAgentTabInput(inputEl);
      const agentId = currentSelectedProfileId || "default";
      if (!currentAgentTabSessionId) {
        const nowStr = new Date().toISOString().replace(/[-:T.]/g, "").slice(0, 14);
        currentAgentTabSessionId = `mc_${nowStr}_${agentId}`;
      }
      let attachmentNotice = "";
      if (hasAttachments) {
        const statusSpan = document.getElementById("agent-tab-chat-status");
        if (statusSpan) statusSpan.textContent = `Lade ${currentAgentTabAttachments.length} Datei(en) hoch...`;
        try {
          for (const att of currentAgentTabAttachments) {
            const formData = new FormData();
            formData.append("file", att.file);
            const uploadRes = await fetch("/api/chat/upload", {
              method: "POST",
              body: formData
            });
            if (uploadRes.ok) {
              const uploadData = await uploadRes.json();
              attachmentNotice += `\n[Datei angehängt: ${uploadData.path || uploadData.filename}]`;
            }
          }
        } catch (err) {
          console.warn("[AgentTabChat Upload] Fehler:", err);
        }
        removeAgentTabAttachment();
      }
      const fullUserMessage = (text + attachmentNotice).trim();
      appendAgentTabMessageBubble("user", fullUserMessage);
      const statusSpan = document.getElementById("agent-tab-chat-status");
      const sendBtn = document.getElementById("agent-tab-send-btn");
      if (statusSpan) {
        statusSpan.innerHTML = currentAgentTabMode === "mission" 
          ? '<span class="font-semibold animate-pulse text-[var(--foreground)]">⚙️ Erstelle Operations Mission...</span>'
          : '<span class="font-semibold animate-pulse text-[var(--foreground)]">● Agent antwortet...</span>';
      }
      if (sendBtn) sendBtn.disabled = true;
      isAgentTabGenerating = true;
      const container = document.getElementById("agent-tab-chat-messages");
      const assistantBubble = document.createElement("div");
      assistantBubble.className = "flex justify-start";
      const prof = hermesProfilesData.find(p => p.id === agentId);
      const name = prof ? (prof.person_name || prof.name) : "Hermes Agent";
      const avatarUrl = (typeof getProfileAvatarUrl === "function" && prof) ? getProfileAvatarUrl(prof) : (prof && prof.avatar ? prof.avatar : "/static/avatars/hermes_default_avatar.png");
      const timeStr = new Date().toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
      const liveMsgId = `#msg-${Math.floor(1000 + Math.random() * 9000)}`;
      assistantBubble.innerHTML = `
        <div class="flex gap-2.5 max-w-[90%]">
          <div class="w-8 h-8 rounded-lg border border-[var(--border)] overflow-hidden shrink-0 mt-0.5 bg-[var(--secondary)] shadow-2xs">
            <img src="${avatarUrl}" class="w-full h-full object-cover" onerror="this.src='/static/avatars/avatar_001.jpg'">
          </div>
          <div class="bg-[var(--card)] border border-[var(--border)] text-[var(--foreground)] rounded-2xl rounded-tl-xs px-3.5 py-2.5 text-xs shadow-xs leading-relaxed space-y-1.5 flex-1 min-w-0">
            <div class="flex items-center justify-between gap-2 border-b border-[var(--border)] pb-1">
              <span class="font-bold text-xs font-mono text-[var(--foreground)] truncate">${escapeHtml(name)}</span>
              <div class="flex items-center gap-1">
                <button type="button" class="copy-bubble-btn text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition p-0.5 rounded cursor-pointer" title="In Zwischenablage kopieren" onclick="copyAgentMessageText(this)" data-text="">
                  <i data-lucide="copy" class="w-3.5 h-3.5 text-black dark:text-white"></i>
                </button>
                <button type="button" class="speaker-btn text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition p-0.5 rounded cursor-pointer" title="Vorlesen" onclick="speakText(this.getAttribute('data-text'))" data-text="">
                  <i data-lucide="volume-2" class="w-3.5 h-3.5 text-black dark:text-white"></i>
                </button>
              </div>
            </div>
            <div class="chat-assistant-body chat-markdown font-sans leading-relaxed text-[var(--foreground)] break-words">
              <span class="text-[var(--muted-foreground)] italic animate-pulse">Antwort wird generiert...</span>
            </div>
            <div class="chat-assistant-action-card"></div>
            <div class="pt-1.5 border-t border-[var(--border)] flex items-center justify-between text-[9px] font-mono text-[var(--muted-foreground)]">
              <span class="flex items-center gap-1"><i data-lucide="clock" class="w-2.5 h-2.5 text-black dark:text-white"></i>${timeStr}</span>
              <span>${liveMsgId}</span>
            </div>
          </div>
        </div>
      `;
      container.appendChild(assistantBubble);
      container.scrollTop = container.scrollHeight;
      if (window.lucide && typeof lucide.createIcons === "function") lucide.createIcons();
      const bodyEl = assistantBubble.querySelector(".chat-assistant-body");
      const actionCardContainer = assistantBubble.querySelector(".chat-assistant-action-card");
      const speakerBtn = assistantBubble.querySelector(".speaker-btn");
      let fullText = "";
      try {
        const reasoningLvl = document.getElementById("agent-tab-reasoning-select")?.value || 
                             document.getElementById("prof-edit-reasoning")?.value || 
                             (prof && prof.reasoning_level) || 
                             "medium";
        const payload = {
          agent_id: agentId,
          message: fullUserMessage,
          session_id: currentAgentTabSessionId,
          mode: currentAgentTabMode,
          provider: currentAgentTabProvider || (prof && prof.provider) || "openrouter",
          model: currentAgentTabModel || (prof && prof.model) || "auto/best-coding",
          reasoning_level: reasoningLvl
        };
        const res = await fetch("/api/chat/stream", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        if (!res.ok) {
          throw new Error("HTTP Fehler " + res.status);
        }
        const reader = res.body.getReader();
        const decoder = new TextDecoder("utf-8");
        let buffer = "";
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop();
          for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed || !trimmed.startsWith("data: ")) continue;
            const jsonStr = trimmed.slice(6).trim();
            if (jsonStr === "[DONE]") break;
            try {
              const eventData = JSON.parse(jsonStr);
              if (eventData.type === "delta" && eventData.delta) {
                fullText += eventData.delta;
                if (bodyEl) {
                  bodyEl.innerHTML = typeof formatMarkdownText === "function" ? formatMarkdownText(fullText) : escapeHtml(fullText);
                }
                container.scrollTop = container.scrollHeight;
              } else if (eventData.type === "mission_created") {
                fullText = eventData.content || "Mission angelegt.";
                if (bodyEl) {
                  bodyEl.innerHTML = typeof formatMarkdownText === "function" ? formatMarkdownText(fullText) : escapeHtml(fullText);
                }
                if (actionCardContainer) {
                  actionCardContainer.innerHTML = `
                    <div class="mt-2.5 p-2.5 bg-[var(--secondary)] border border-[var(--border)] rounded-lg flex items-center justify-between gap-3 text-[var(--foreground)] shadow-xs">
                      <div class="text-xs font-sans font-medium flex items-center gap-1.5">
                        <i data-lucide="shield-alert" class="w-4 h-4 text-black dark:text-white"></i>
                        <span>Diese Mission wartet im Approval Gate auf Freigabe.</span>
                      </div>
                      <button type="button" onclick="setTab('mission-control')" class="shadcn-btn-primary px-2.5 py-1 text-xs font-semibold rounded-md flex items-center gap-1.5 cursor-pointer shadow-xs transition shrink-0">
                        <i data-lucide="shield" class="w-3.5 h-3.5"></i>
                        <span>Zur Freigabe</span>
                      </button>
                    </div>
                  `;
                  if (window.lucide && typeof lucide.createIcons === "function") lucide.createIcons();
                }
                container.scrollTop = container.scrollHeight;
              } else if (eventData.type === "error") {
                fullText += `\n❌ Fehler: ${eventData.error}`;
                if (bodyEl) {
                  bodyEl.innerHTML = `<span class="text-rose-600 font-semibold">${escapeHtml(fullText)}</span>`;
                }
              }
            } catch (jsonErr) {
              console.warn("[AgentTabChat SSE] Ungültiges Event:", trimmed, jsonErr);
            }
          }
        }
        const copyBtn = assistantBubble.querySelector(".copy-bubble-btn");
        if (copyBtn) {
          copyBtn.setAttribute("data-text", escapeHtml(fullText).replace(/"/g, '&quot;'));
        }
        if (speakerBtn) {
          speakerBtn.setAttribute("data-text", escapeHtml(fullText).replace(/"/g, '&quot;'));
        }
        // Sessions neu laden
        loadMasterChatSessions();
      } catch (err) {
        if (bodyEl) {
          bodyEl.innerHTML = `<span class="text-rose-600 font-semibold">Verbindungsfehler: ${escapeHtml(err.message)}</span>`;
        }
      } finally {
        isAgentTabGenerating = false;
        if (statusSpan) statusSpan.textContent = "Bereit";
        if (sendBtn) sendBtn.disabled = false;
        if (window.lucide && typeof lucide.createIcons === "function") lucide.createIcons();
        if (inputEl) inputEl.focus();
      }
    }
    function addAgentTabAttachmentFiles(files) {
      if (!files || !files.length) return;
      const fileList = Array.from(files);
      const remaining = 5 - currentAgentTabAttachments.length;
      if (remaining <= 0) {
        if (typeof showActionFeedbackToast === "function") {
          showActionFeedbackToast("⚠️ Maximal 5 Anhänge erlaubt.");
        } else {
          alert("Maximal 5 Anhänge gleichzeitig erlaubt.");
        }
        return;
      }
      const toAdd = fileList.slice(0, remaining);
      if (fileList.length > remaining && typeof showActionFeedbackToast === "function") {
        showActionFeedbackToast(`⚠️ Nur ${remaining} Datei(en) hinzugefügt (Limit: 5).`);
      }
      toAdd.forEach(file => {
        currentAgentTabAttachments.push({
          file: file,
          name: file.name || "datei",
          size: (file.size / 1024).toFixed(1) + " KB",
          type: file.type || "application/octet-stream"
        });
      });
      renderAgentTabAttachments();
    }
    function renderAgentTabAttachments() {
      const bar = document.getElementById("agent-tab-attachment-bar");
      if (!bar) return;
      if (!currentAgentTabAttachments.length) {
        bar.classList.add("hidden");
        bar.innerHTML = "";
        return;
      }
      bar.classList.remove("hidden");
      bar.innerHTML = `
        <div class="flex items-center gap-1.5 flex-wrap flex-1 min-w-0">
          <span class="text-[10px] font-mono text-[var(--muted-foreground)] uppercase font-bold shrink-0">Anhänge (${currentAgentTabAttachments.length}/5):</span>
          ${currentAgentTabAttachments.map((att, idx) => `
            <div class="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-[var(--card)] border border-[var(--border)] text-[10.5px] font-mono text-[var(--foreground)] shadow-2xs">
              <i data-lucide="file" class="w-3 h-3 text-emerald-500 shrink-0"></i>
              <span class="truncate max-w-[130px] font-medium" title="${escapeHtml(att.name)}">${escapeHtml(att.name)}</span>
              <span class="text-[9px] text-[var(--muted-foreground)] font-normal">${att.size}</span>
              <button type="button" onclick="removeAgentTabAttachment(${idx})" class="text-[var(--muted-foreground)] hover:text-red-500 transition p-0.5 cursor-pointer" title="Entfernen">
                <i data-lucide="x" class="w-3 h-3"></i>
              </button>
            </div>
          `).join('')}
        </div>
        <button type="button" onclick="removeAgentTabAttachment()" class="text-[10px] font-mono text-[var(--muted-foreground)] hover:text-red-500 transition px-1.5 py-0.5 rounded cursor-pointer shrink-0" title="Alle Anhänge entfernen">
          Alle löschen
        </button>
      `;
      if (window.lucide && typeof lucide.createIcons === "function") lucide.createIcons();
    }
    function handleAgentTabFileSelected(event) {
      const files = event.target.files;
      if (!files || !files.length) return;
      addAgentTabAttachmentFiles(files);
    }
    function handleAgentTabInputPaste(event) {
      const items = (event.clipboardData || window.clipboardData)?.items;
      if (!items) return;
      const foundFiles = [];
      for (let i = 0; i < items.length; i++) {
        const item = items[i];
        if (item.kind === 'file') {
          const blob = item.getAsFile();
          if (blob) {
            const ts = new Date().toISOString().replace(/[-:T.]/g, "").slice(0, 14);
            const isImg = item.type.startsWith('image/');
            const ext = isImg ? "png" : "bin";
            const file = new File([blob], `pasted_${ts}_${i}.${ext}`, { type: blob.type || (isImg ? "image/png" : "application/octet-stream") });
            foundFiles.push(file);
          }
        }
      }
      if (foundFiles.length > 0) {
        event.preventDefault();
        addAgentTabAttachmentFiles(foundFiles);
      }
    }
    async function captureScreenForAgentChat() {
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
          addAgentTabAttachmentFiles([file]);
        }, "image/png");
      } catch (err) {
        if (err.name !== "NotAllowedError") {
          console.warn("[ScreenCapture] Fehler:", err);
        }
      }
    }
    function removeAgentTabAttachment(idx) {
      if (typeof idx === "number") {
        currentAgentTabAttachments.splice(idx, 1);
      } else {
        currentAgentTabAttachments = [];
      }
      const fileInput = document.getElementById("agent-tab-file-input");
      if (fileInput) fileInput.value = "";
      renderAgentTabAttachments();
    }
    function toggleAgentTabDictation() {
      const btn = document.getElementById("agent-tab-mic-btn");
      const textarea = document.getElementById("agent-tab-chat-input");
      if (!("webkitSpeechRecognition" in window) && !("SpeechRecognition" in window)) {
        alert("Spracherkennung wird in diesem Browser leider nicht unterstützt. Bitte Chrome oder Edge nutzen.");
        return;
      }
      if (isAgentTabDictating) {
        if (agentTabDictationRecognition) {
          agentTabDictationRecognition.stop();
        }
        isAgentTabDictating = false;
        if (btn) {
          btn.className = "p-2 rounded-lg border border-[var(--border)] text-[var(--foreground)] hover:bg-[var(--secondary)] bg-[var(--card)] transition shrink-0 cursor-pointer shadow-2xs";
          btn.title = "Spracheingabe / Diktat starten (Mikrofon)";
        }
        return;
      }
      const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
      agentTabDictationRecognition = new SpeechRec();
      agentTabDictationRecognition.continuous = true;
      agentTabDictationRecognition.interimResults = true;
      agentTabDictationRecognition.lang = "de-DE";
      let baseText = textarea.value ? textarea.value.trim() + " " : "";
      agentTabDictationRecognition.onresult = (event) => {
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
        autoResizeAgentTabInput(textarea);
      };
      agentTabDictationRecognition.onerror = (event) => {
        console.error("[AgentTab Speech] Fehler:", event.error);
        isAgentTabDictating = false;
        if (btn) {
          btn.className = "p-2 rounded-lg border border-[var(--border)] text-[var(--foreground)] hover:bg-[var(--secondary)] bg-[var(--card)] transition shrink-0 cursor-pointer shadow-2xs";
        }
      };
      agentTabDictationRecognition.onend = () => {
        isAgentTabDictating = false;
        if (btn) {
          btn.className = "p-2 rounded-lg border border-[var(--border)] text-[var(--foreground)] hover:bg-[var(--secondary)] bg-[var(--card)] transition shrink-0 cursor-pointer shadow-2xs";
        }
      };
      agentTabDictationRecognition.start();
      isAgentTabDictating = true;
      if (btn) {
        btn.className = "p-2 rounded-lg border border-red-500 text-red-500 bg-red-50 dark:bg-red-950/30 animate-pulse transition shrink-0 cursor-pointer shadow-2xs";
        btn.title = "Diktat läuft... Klicken zum Stoppen";
      }
    }
    function autoResizeAgentTabInput(el) {
      if (!el) return;
      el.style.height = "auto";
      const maxH = Math.floor(window.innerHeight * 0.25);
      el.style.height = Math.max(48, Math.min(el.scrollHeight, maxH)) + "px";
    }
    let currentAgentTabProvider = "openrouter";
    // --- Tokenpreis pro 1M (Input/Output) neben der Modell-Auswahl ---
    let agentTabModelPrices = {};
    let agentTabModelPricesLoaded = false;
    async function loadAgentTabModelPrices() {
      if (agentTabModelPricesLoaded) return;
      try {
        const res = await fetch("/api/llm-providers/prices");
        if (!res.ok) return;
        const data = await res.json();
        if (data && data.prices) {
          agentTabModelPrices = data.prices;
          agentTabModelPricesLoaded = true;
        }
      } catch (e) {
        console.warn("Tokenpreise konnten nicht geladen werden:", e);
      }
    }
    function formatPricePer1M(usd) {
      if (usd === undefined || usd === null || isNaN(usd)) return "0.00";
      const num = Number(usd);
      if (num === 0) return "0.00";
      if (num >= 10) return num.toFixed(2);
      if (num >= 1) return num.toFixed(2);
      if (num >= 0.1) return num.toFixed(3);
      return num.toFixed(4);
    }
    window.formatPricePer1M = formatPricePer1M;

    function updateAgentTabModelCost() {
      const el = document.getElementById("agent-tab-model-cost");
      if (!el) return;
      const modelSelect = document.getElementById("agent-tab-model-select");
      const model = (modelSelect && modelSelect.value) || currentAgentTabModel;
      const info = findModelPriceInfo(model);
      if (info && info.p) {
        const pre = info.approx ? "≈ " : "";
        const inP = formatPricePer1M(info.p.prompt_1m);
        const outP = formatPricePer1M(info.p.completion_1m);
        el.innerHTML = `${pre}In: <span class="text-emerald-500">$${inP}</span> | Out: <span class="text-amber-500">$${outP}</span> /1M Tok`;
        el.classList.remove("hidden");
        el.title = info.approx
          ? `Preis des passenden Modells (${info.matched}) — Input: $${inP} / Output: $${outP} pro 1M Tokens`
          : `Input: $${inP} / Output: $${outP} pro 1 Million Tokens (live von OpenRouter)`;
      } else {
        el.classList.add("hidden");
      }
    }
    function findModelPriceInfo(model) {
      if (!model || !Object.keys(agentTabModelPrices).length) return null;
      // 1. Exakter Match
      const exact = agentTabModelPrices[model];
      if (exact) return { p: exact, approx: false, matched: model };

      const lowModel = model.toLowerCase();
      // 2. Case-Insensitive Match
      for (const k of Object.keys(agentTabModelPrices)) {
        if (k.toLowerCase() === lowModel) {
          return { p: agentTabModelPrices[k], approx: false, matched: k };
        }
      }

      // 3. Match ohne Vendor-Präfix
      const modelBase = lowModel.includes("/") ? lowModel.split("/").pop() : lowModel;
      for (const k of Object.keys(agentTabModelPrices)) {
        const kBase = k.toLowerCase().split("/").pop();
        if (kBase === modelBase) {
          return { p: agentTabModelPrices[k], approx: false, matched: k };
        }
      }

      // 4. Intelligenter Substring- / Slug-Match unter Beibehaltung der Modell-Klasse (Flash, Pro, Mini, etc.)
      const tiers = ["flash", "pro", "mini", "sonnet", "opus", "haiku", "max", "nano", "small", "medium", "large"];
      const activeTiers = tiers.filter(t => lowModel.includes(t));

      let bestKey = null;
      let bestScore = -1;

      const cleanModel = modelBase.replace(/[^a-z0-9]/g, "");

      for (const k of Object.keys(agentTabModelPrices)) {
        const lowK = k.toLowerCase();
        // Falls das Suchmodell eine Tier-Kennung hat (z.B. Flash), MUSS der Kandidat dieselbe Kennung haben!
        if (activeTiers.length > 0) {
          const hasAllTiers = activeTiers.every(t => lowK.includes(t));
          if (!hasAllTiers) continue;
        }

        const kBase = lowK.split("/").pop();
        const cleanK = kBase.replace(/[^a-z0-9]/g, "");

        let score = 0;
        if (cleanK === cleanModel) score += 100;
        else if (cleanK.includes(cleanModel) || cleanModel.includes(cleanK)) score += 50;

        // Vendor-Bonus wenn übereinstimmend
        if (lowModel.includes("/") && lowK.includes("/")) {
          const v1 = lowModel.split("/")[0].replace(/[^a-z0-9]/g, "");
          const v2 = lowK.split("/")[0].replace(/[^a-z0-9]/g, "");
          if (v1 === v2) score += 30;
        }

        if (score > bestScore) {
          bestScore = score;
          bestKey = k;
        }
      }

      if (bestKey && bestScore > 0) {
        return { p: agentTabModelPrices[bestKey], approx: true, matched: bestKey };
      }
      return null;
    }
    window.findModelPriceInfo = findModelPriceInfo;
    window.updateAgentTabModelCost = updateAgentTabModelCost;
    async function onAgentHeaderProviderChange(prov) {
      const tabProvSelect = document.getElementById("agent-tab-provider-select");
      if (tabProvSelect) tabProvSelect.value = prov;
      await onAgentTabProviderChange(prov);
      syncAgentHeaderModelDropdown();
    }
    async function onAgentHeaderModelChange(val) {
      const tabModelSelect = document.getElementById("agent-tab-model-select");
      if (tabModelSelect) tabModelSelect.value = val;
      await onAgentTabModelChange(val);
    }
    function syncAgentHeaderModelDropdown() {
      const tabModelSelect = document.getElementById("agent-tab-model-select");
      const headerModelSelect = document.getElementById("agent-header-model-select");
      const headerProvSelect = document.getElementById("agent-header-provider-select");
      const tabProvSelect = document.getElementById("agent-tab-provider-select");
      if (headerProvSelect && tabProvSelect) {
        if (headerProvSelect.options.length !== tabProvSelect.options.length) {
          headerProvSelect.innerHTML = tabProvSelect.innerHTML;
        }
        headerProvSelect.value = tabProvSelect.value;
      }
      if (tabModelSelect && headerModelSelect) {
        headerModelSelect.innerHTML = tabModelSelect.innerHTML;
        headerModelSelect.value = tabModelSelect.value;
      }
    }
    async function populateAgentTabModelSelect() {
      const providerSelect = document.getElementById("agent-tab-provider-select");
      const prof = hermesProfilesData.find(p => p.id === currentSelectedProfileId);
      const prov = (prof && prof.provider) || (prof && prof.model && prof.model.includes("gemini") ? "google" : "openrouter");
      const mod = (prof && prof.model && prof.model !== "free-forever") ? prof.model : null;
      currentAgentTabProvider = prov;
      if (providerSelect) providerSelect.value = prov;
      await onAgentTabProviderChange(prov, mod, true);
      syncAgentHeaderModelDropdown();
    }
    async function onAgentTabProviderChange(prov, preferredModel, skipSave = false) {
      currentAgentTabProvider = prov || "openrouter";
      const modelSelect = document.getElementById("agent-tab-model-select");
      if (!modelSelect) return;
      modelSelect.disabled = true;
      modelSelect.innerHTML = `<option value="">Lade Modelle für ${currentAgentTabProvider}...</option>`;
      const models = await loadLlmModelsForProvider(currentAgentTabProvider);
      modelSelect.disabled = false;
      populateModelDropdown(modelSelect, models, preferredModel);
      currentAgentTabModel = modelSelect.value;
      await loadAgentTabModelPrices();
      updateAgentTabModelCost();
      syncAgentHeaderModelDropdown();
      if (!skipSave && currentSelectedProfileId && currentAgentTabModel) {
        saveActiveAgentModelAndProvider(currentAgentTabProvider, currentAgentTabModel);
      }
    }
    async function onAgentTabModelChange(val) {
      if (val === "__CUSTOM__") {
        const selectEl = document.getElementById("agent-tab-model-select");
        if (handleCustomModelOption(selectEl)) {
          val = selectEl.value;
        } else {
          return;
        }
      }
      currentAgentTabModel = val;
      syncAgentHeaderModelDropdown();
      updateAgentTabModelCost();
      if (currentSelectedProfileId && val) {
        await saveActiveAgentModelAndProvider(currentAgentTabProvider, val);
      }
    }
    async function saveActiveAgentModelAndProvider(provider, model) {
      if (!currentSelectedProfileId || !provider || !model) return;
      const prof = hermesProfilesData.find(p => p.id === currentSelectedProfileId);
      if (prof) {
        prof.provider = provider;
        prof.model = model;
      }
      const profProv = document.getElementById("prof-edit-provider");
      const profMod = document.getElementById("prof-edit-model");
      const profLabel = document.getElementById("prof-active-model-label");
      if (profProv) profProv.value = provider;
      if (profMod) {
        profMod.value = model;
      }
      if (profLabel) profLabel.innerText = `aktiv: ${model} (${provider})`;
      try {
        await fetch(`/api/hermes/profiles/${encodeURIComponent(currentSelectedProfileId)}/model`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ provider, model })
        });
      } catch (err) {
        console.warn("[Profile Model] Auto-save error:", err);
      }
    }
    function jumpToMasterChatWithCurrentAgent() {
      const agentId = currentSelectedProfileId || "default";
      setTab('master-chat');
      if (typeof selectMasterChatProfile === "function") {
        selectMasterChatProfile(agentId);
      }
    }
    function togglePinAgentToCurrentTask() {
      if (!currentSelectedProfileId) return;
      const prof = hermesProfilesData.find(p => p.id === currentSelectedProfileId);
      const name = prof ? (prof.person_name || prof.name) : currentSelectedProfileId;
      prof.is_pinned_to_task = !prof.is_pinned_to_task;
      showArchonToast(
        prof.is_pinned_to_task 
          ? `Agent '${name}' an aktiven Task geheftet!` 
          : `Task-Bindung für '${name}' gelöst.`, 
        "success"
      );
    }
    // Modal-Umleitungen zur Vermeidung von Popup-Modals
    function openSoulModal(agentId) {
      if (agentId) selectProfileForEditor(agentId);
      switchAgentCadreTab('soul');
    }
    function closeSoulModal() {}
    function saveSoulMarkdown() { saveInlineSoulMarkdown(); }
    function openPersonalakteModal(agentId) {
      if (agentId) selectProfileForEditor(agentId);
      switchAgentCadreTab('personalakte');
    }
    function closePersonalakteModal() {}
    function switchPersonalakteTab(tabName) {}
    function savePersonalakteMarkdown() { saveInlinePersonalakteMarkdown(); }
    function openDirectChatForCurrentProfile(agentId) {
      if (agentId) selectProfileForEditor(agentId);
      switchAgentCadreTab('chat');
    }
    function closeAgentDirectChatModal() {}
    async function loadAgentLiveActivity(agentId) {
      const term = document.getElementById("prof-activity-log-terminal");
      const statusEl = document.getElementById("prof-log-status");
      if (!term) return;
      term.innerHTML = `<div class="text-[var(--muted-foreground)] italic">Verbinde mit Agenten-Log...</div>`;
      if (statusEl) statusEl.innerText = "Lade...";
      try {
        const res = await fetch(`/api/v1/agent/${agentId}/activity`);
        if (!res.ok) throw new Error("Status " + res.status);
        const data = await res.json();
        const logs = data.logs || [];
        const turns = data.recent_turns || [];
        if (statusEl) statusEl.innerText = "Aktiv";
        let html = "";
        if (turns.length > 0) {
          html += `<div class="text-[10px] text-zinc-900 dark:text-zinc-100 font-bold mb-1 border-b border-[var(--border)] pb-0.5">💬 Letzte Konversationsturns:</div>`;
          turns.forEach(t => {
            html += `<div class="text-[var(--foreground)]/90 whitespace-pre-wrap leading-tight py-0.5">${escapeHtml(t)}</div>`;
          });
          html += `<div class="text-[10px] text-zinc-900 dark:text-zinc-100 font-bold mt-2 mb-1 border-b border-[var(--border)] pb-0.5">⚡ System & Daemon Telemetrie:</div>`;
        }
        if (logs.length > 0) {
          logs.forEach(l => {
            let color = "text-[var(--muted-foreground)]";
            if (l.includes("INFO") || l.includes("aktiv") || l.includes("online")) color = "text-emerald-600 dark:text-emerald-400";
            if (l.includes("WARN") || l.includes("caution")) color = "text-amber-600 dark:text-amber-400";
            if (l.includes("ERROR") || l.includes("Fehler")) color = "text-rose-600 dark:text-rose-400";
            html += `<div class="${color} whitespace-pre-wrap leading-tight py-0.5 font-mono">${escapeHtml(l)}</div>`;
          });
        } else {
          html += `<div class="text-[var(--muted-foreground)] italic">Keine aktuellen Hintergrund-Logs für diesen Agenten.</div>`;
        }
        term.innerHTML = html;
        term.scrollTop = term.scrollHeight;
      } catch (err) {
        term.innerHTML = `<div class="text-[var(--foreground)] font-mono"><span class="font-bold">[DAEMON]</span> Agent bereit im Standby-Modus.<br><span class="text-[var(--muted-foreground)]">[ROUTER]</span> Port 20128 aktiv. Keine Warnungen.</div>`;
        if (statusEl) statusEl.innerText = "Bereit";
      }
    }
    async function loadAgentProjectsHistory(agentId) {
      const list = document.getElementById("prof-projects-list");
      const countEl = document.getElementById("prof-projects-count");
      if (!list) return;
      list.innerHTML = `<div class="text-[11px] text-[var(--muted-foreground)] italic p-1">Lade Projektbeteiligungen...</div>`;
      try {
        const res = await fetch(`/api/v1/agent/${agentId}/projects`);
        if (!res.ok) throw new Error("Status " + res.status);
        const data = await res.json();
        const projects = data.projects || [];
        if (countEl) {
          countEl.innerText = `${projects.length} ${projects.length === 1 ? 'Projekt' : 'Projekte'}`;
        }
        if (projects.length === 0) {
          list.innerHTML = `<div class="text-[11px] text-[var(--muted-foreground)] italic p-1">Bisher keine dokumentierten Projektbeteiligungen.</div>`;
          return;
        }
        list.innerHTML = projects.map(p => `
          <div class="p-1.5 rounded-lg border border-[var(--border)] bg-[var(--card)] hover:border-zinc-500 transition shadow-2xs">
            <div class="flex items-center justify-between gap-1">
              <span class="font-bold text-xs text-[var(--foreground)] truncate">${escapeHtml(p.name)}</span>
              <span class="px-1.5 py-0.2 rounded text-[9px] font-mono bg-[var(--secondary)] text-[var(--foreground)] font-bold border border-[var(--border)] shrink-0">${escapeHtml(p.status || 'Aktiv')}</span>
            </div>
            <div class="flex items-center justify-between text-[9.5px] font-mono text-[var(--muted-foreground)] mt-0.5">
              <span>📅 ${escapeHtml(p.date || '2026')}</span>
              <span class="truncate max-w-[110px]">${escapeHtml(p.source || 'Vault')}</span>
            </div>
          </div>
        `).join('');
      } catch (err) {
        list.innerHTML = `
          <div class="p-1.5 rounded-lg border border-[var(--border)] bg-[var(--card)] shadow-2xs">
            <div class="flex items-center justify-between">
              <span class="font-bold text-xs text-[var(--foreground)]">AgenticOS 2026 Kernsystem</span>
              <span class="px-1.5 py-0.2 rounded text-[9px] font-mono bg-[var(--secondary)] text-[var(--foreground)] font-bold border border-[var(--border)]">Aktiv</span>
            </div>
            <div class="text-[9.5px] font-mono text-[var(--muted-foreground)] mt-0.5">📅 2026-09 • Archon OS</div>
          </div>
        `;
        if (countEl) countEl.innerText = "1 Projekt";
      }
    }
    async function onProfileProviderChange(provider, preferredModel) {
      const modelSelect = document.getElementById("prof-edit-model");
      if (modelSelect.tagName === "SELECT") {
        modelSelect.disabled = true;
        modelSelect.innerHTML = `<option value="">Lade Modelle für ${provider}...</option>`;
      } else {
        modelSelect.placeholder = `Lade Modelle für ${provider}...`;
      }
      const models = await loadLlmModelsForProvider(provider);
      if (modelSelect.tagName === "SELECT") {
        modelSelect.disabled = false;
      } else {
        modelSelect.placeholder = "Modell suchen oder manuell eingeben...";
      }
      populateModelDropdown(modelSelect, models, preferredModel);
      const label = document.getElementById("prof-active-model-label");
      if (label && modelSelect.value) {
        label.innerText = `aktiv: ${modelSelect.value}`;
      }
    }
    async function applyProfileModelSelection() {
      const providerSelect = document.getElementById("prof-edit-provider");
      const modelSelect = document.getElementById("prof-edit-model");
      const reasoningSelect = document.getElementById("prof-edit-reasoning");
      const label = document.getElementById("prof-active-model-label");
      if (!modelSelect || !providerSelect) return;
      const provider = providerSelect.value;
      const model = modelSelect.value;
      const reasoning_level = reasoningSelect ? reasoningSelect.value : "medium";
      if (!provider || !model) return;
      if (label) label.innerText = `aktiv: ${model} (${provider}) · 🧠 ${reasoning_level}`;
      const prof = hermesProfilesData.find(p => p.id === currentSelectedProfileId);
      if (prof) {
        prof.provider = provider;
        prof.model = model;
        prof.reasoning_level = reasoning_level;
      }
      // Falls der Chat-Tab für diesen Agenten geöffnet ist, synchronisiere auch die Chat-Auswahl
      const tabProv = document.getElementById("agent-tab-provider-select");
      const tabMod = document.getElementById("agent-tab-model-select");
      const tabReas = document.getElementById("agent-tab-reasoning-select");
      if (tabProv && tabProv.value !== provider) tabProv.value = provider;
      if (tabMod) tabMod.value = model;
      if (tabReas) tabReas.value = reasoning_level;
      currentAgentTabProvider = provider;
      currentAgentTabModel = model;
      if (typeof updateAgentTabModelCost === "function") {
        updateAgentTabModelCost();
      }
      try {
        const res = await fetch(`/api/hermes/profiles/${encodeURIComponent(currentSelectedProfileId)}/model`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ provider, model, reasoning_level })
        });
        const data = await res.json();
        if (data.status === "ok") {
          if (typeof showActionFeedbackToast === "function") {
            showActionFeedbackToast(`Modell gespeichert: ${model} (${provider})`);
          } else if (label) {
            label.innerText = `✓ aktiv: ${model} (${provider})`;
          }
        }
      } catch (err) {
        console.error("[Profile Model] Save failed:", err);
      }
    }
    function assignSelectedMarketplaceSkillToProfile() {
      if (typeof assignSelectedMarketplaceSkill === "function") {
        return assignSelectedMarketplaceSkill();
      }
    }
    function renderActiveProfileSkillsTags(skillsList) {
      const tagsContainer = document.getElementById("prof-active-skills-tags");
      const countEl = document.getElementById("prof-skills-count");
      if (!tagsContainer) return;
      tagsContainer.innerHTML = "";
      if (countEl) countEl.innerText = `${skillsList.length} ${skillsList.length === 1 ? 'Skill aktiv' : 'Skills aktiv'}`;
      if (skillsList.length === 0) {
        tagsContainer.innerHTML = `<span class="text-[10px] text-[var(--muted-foreground)] font-mono italic py-1">Noch keine Skills zugeordnet. Wähle unten einen Skill aus dem Katalog.</span>`;
        return;
      }
      skillsList.forEach(skId => {
        const skObj = hermesGlobalSkillsData.find(s => s.id === skId) || { name: skId, category: "Skill" };
        const badge = document.createElement("span");
        badge.className = "prof-skill-tag inline-flex items-center gap-1.5 text-xs font-semibold px-2 py-0.5 shadow-xs bg-[var(--card)] border border-[var(--border)] rounded-md";
        badge.innerHTML = `
          <span class="truncate max-w-[150px]">${skObj.name}</span>
          <span class="inline-flex items-center gap-1 ml-1 shrink-0">
            <button type="button" onclick="openSkillDetailModal('${skId}')" class="text-[var(--foreground)] opacity-75 hover:opacity-100 transition cursor-pointer flex items-center justify-center p-0.5" title="Skill-Details & Code bearbeiten">
              <i data-lucide="info" class="w-3 h-3"></i>
            </button>
            <button type="button" onclick="removeSkillFromProfile('${skId}')" class="opacity-60 hover:opacity-100 text-[var(--foreground)] font-bold cursor-pointer transition p-0.5" title="Skill entfernen">✕</button>
          </span>
        `;
        tagsContainer.appendChild(badge);
      });
      if (window.lucide) lucide.createIcons();
    }
    function renderActiveProfileTools(toolsList = []) {
      const tagsContainer = document.getElementById("prof-active-tools-tags");
      const countEl = document.getElementById("prof-tools-count");
      if (!tagsContainer) return;
      tagsContainer.innerHTML = "";
      const activeTools = Array.isArray(toolsList) && toolsList.length > 0 ? toolsList : (typeof DEFAULT_HERMES_TOOLS !== 'undefined' ? DEFAULT_HERMES_TOOLS : []);
      if (countEl) {
        countEl.innerText = `${activeTools.length} ${activeTools.length === 1 ? 'Tool aktiv' : 'Tools aktiv'}`;
      }
      if (activeTools.length === 0) {
        tagsContainer.innerHTML = `<span class="text-[10px] text-[var(--muted-foreground)] font-mono italic py-1">Noch keine Tools zugeordnet. Wähle unten ein Tool aus dem Katalog.</span>`;
      } else {
        activeTools.forEach(toolId => {
          const tool = AVAILABLE_SYSTEM_TOOLS.find(t => t.id === toolId) || { id: toolId, name: toolId, icon: "wrench", desc: "System Tool" };
          const badge = document.createElement("span");
          badge.className = "prof-tool-card-active inline-flex items-center gap-1.5 text-xs font-semibold px-2 py-0.5 rounded-md border border-[var(--border)] bg-[var(--card)] shadow-xs select-none";
          badge.innerHTML = `
            <i data-lucide="${tool.icon || 'wrench'}" class="w-3 h-3 shrink-0 text-[var(--foreground)]"></i>
            <span class="truncate max-w-[150px] text-[11px] font-bold">${tool.name}</span>
            <span class="inline-flex items-center gap-1 ml-1 shrink-0">
              <button type="button" onclick="openToolConfigModal('${tool.id}', event)" class="tool-settings-trigger opacity-75 hover:opacity-100 text-[var(--foreground)] transition cursor-pointer flex items-center justify-center p-0.5" title="Tool-Einstellungen & Parameter öffnen">
                <i data-lucide="settings" class="w-3 h-3"></i>
              </button>
              <button type="button" onclick="removeToolFromProfile('${tool.id}')" class="opacity-60 hover:opacity-100 text-[var(--foreground)] font-bold cursor-pointer transition p-0.5" title="Tool entfernen">✕</button>
            </span>
          `;
          tagsContainer.appendChild(badge);
        });
      }
      populateGlobalToolsDropdown(activeTools);
      if (window.lucide) lucide.createIcons();
    }
    function populateGlobalToolsDropdown(activeTools = []) {
      const select = document.getElementById("prof-add-tool-select");
      if (!select) return;
      select.innerHTML = '<option value="" disabled selected>+ Tool aus Katalog hinzufügen...</option>';
      AVAILABLE_SYSTEM_TOOLS.forEach(tool => {
        if (!activeTools.includes(tool.id)) {
          const opt = document.createElement("option");
          opt.value = tool.id;
          opt.innerText = `${tool.name} - ${tool.desc}`;
          select.appendChild(opt);
        }
      });
    }
    function addSelectedToolToProfile() {
      const select = document.getElementById("prof-add-tool-select");
      const toolId = select.value;
      if (!toolId) return;
      const prof = hermesProfilesData.find(p => p.id === currentSelectedProfileId);
      if (!prof) {
        alert("Bitte wähle zuerst ein Profil aus.");
        return;
      }
      if (!prof.tools) prof.tools = [];
      if (!prof.tools.includes(toolId)) {
        prof.tools.push(toolId);
        renderActiveProfileTools(prof.tools);
        select.selectedIndex = 0;
      }
    }
    function removeToolFromProfile(toolId) {
      const prof = hermesProfilesData.find(p => p.id === currentSelectedProfileId);
      if (!prof || !prof.tools) return;
      prof.tools = prof.tools.filter(t => t !== toolId);
      renderActiveProfileTools(prof.tools);
    }
    let currentConfiguringToolId = "";
    function openToolConfigModal(toolId, event) {
      if (event) event.stopPropagation();
      currentConfiguringToolId = toolId;
      const tool = AVAILABLE_SYSTEM_TOOLS.find(t => t.id === toolId) || { id: toolId, name: toolId, desc: "System Tool", mode: "direct", timeout: 60 };
      
      const titleEl = document.getElementById("tool-modal-title");
      if (titleEl) titleEl.innerText = `Tool-Einstellungen: ${tool.name}`;
      const idInput = document.getElementById("tool-modal-tool-id");
      if (idInput) idInput.value = tool.id;
      const nameInput = document.getElementById("tool-modal-name");
      if (nameInput) nameInput.value = tool.name;
      const descInput = document.getElementById("tool-modal-desc");
      if (descInput) descInput.value = tool.desc || "";
      const modeInput = document.getElementById("tool-modal-mode");
      if (modeInput) modeInput.value = tool.mode || "direct";
      const timeoutInput = document.getElementById("tool-modal-timeout");
      if (timeoutInput) timeoutInput.value = tool.timeout || 60;
      const prof = hermesProfilesData.find(p => p.id === currentSelectedProfileId);
      const isCurrentlyActive = prof && prof.tools ? prof.tools.includes(toolId) : true;
      const toggleEl = document.getElementById("tool-modal-active-toggle");
      if (toggleEl) toggleEl.checked = isCurrentlyActive;
      const configEl = document.getElementById("tool-modal-config");
      if (configEl) {
        const defaultConfig = {
          enabled: isCurrentlyActive,
          mode: tool.mode || "direct",
          timeout: tool.timeout || 60,
          env_vars: {},
          max_retries: 3
        };
        configEl.value = JSON.stringify(defaultConfig, null, 2);
      }
      const modal = document.getElementById("tool-config-modal");
      if (modal) modal.classList.remove("hidden");
      if (window.lucide) lucide.createIcons();
    }
    function closeToolConfigModal() {
      const modal = document.getElementById("tool-config-modal");
      if (modal) modal.classList.add("hidden");
    }
    function saveToolConfigFromModal() {
      const toolId = document.getElementById("tool-modal-tool-id")?.value;
      const tool = AVAILABLE_SYSTEM_TOOLS.find(t => t.id === toolId);
      if (tool) {
        tool.desc = document.getElementById("tool-modal-desc")?.value.trim() || "";
        tool.mode = document.getElementById("tool-modal-mode")?.value || "direct";
        tool.timeout = parseInt(document.getElementById("tool-modal-timeout")?.value) || 60;
      }
      const isActive = document.getElementById("tool-modal-active-toggle")?.checked;
      const prof = hermesProfilesData.find(p => p.id === currentSelectedProfileId);
      if (prof) {
        if (!prof.tools) prof.tools = AVAILABLE_SYSTEM_TOOLS.map(t => t.id);
        if (isActive && !prof.tools.includes(toolId)) {
          prof.tools.push(toolId);
        } else if (!isActive && prof.tools.includes(toolId)) {
          prof.tools = prof.tools.filter(t => t !== toolId);
        }
        renderActiveProfileTools(prof.tools);
      }
      closeToolConfigModal();
    }
    async function openSkillDetailModal(skillId) {
      const idEl = document.getElementById("skill-edit-id");
      if (idEl) idEl.value = skillId;
      const nameEl = document.getElementById("skill-edit-name");
      const catEl = document.getElementById("skill-edit-category");
      const tagsEl = document.getElementById("skill-edit-tags");
      const descEl = document.getElementById("skill-edit-desc");
      const contentEl = document.getElementById("skill-edit-content");
      const titleEl = document.getElementById("skill-modal-title");
      const resetBtn = document.getElementById("skill-modal-reset-btn");
      if (titleEl) titleEl.innerText = `Skill: ${skillId}`;
      if (contentEl) contentEl.value = "Lade Spezifikation...";
      const modal = document.getElementById("skill-editor-modal");
      if (modal) modal.classList.remove("hidden");
      try {
        const res = await fetch(`/api/hermes/skills/${encodeURIComponent(skillId)}`);
        if (res.ok) {
          const fullSkill = await res.json();
          if (titleEl) titleEl.innerText = `Skill: ${fullSkill.name || skillId}`;
          if (nameEl) nameEl.value = fullSkill.name || skillId;
          if (catEl) catEl.value = fullSkill.category || "Allgemein";
          if (tagsEl) tagsEl.value = (fullSkill.tags || []).join(", ");
          if (descEl) descEl.value = fullSkill.description || "";
          if (contentEl) contentEl.value = fullSkill.content || "";
          if (resetBtn) {
            resetBtn.disabled = !fullSkill.has_original_backup;
            resetBtn.style.opacity = fullSkill.has_original_backup ? "1" : "0.5";
            resetBtn.title = fullSkill.has_original_backup ? "Auf Originalzustand (.SKILL.md.orig) zurücksetzen" : "Noch keine Anpassung vorgenommen (Original ist aktiv)";
          }
        }
      } catch (e) {
        console.error("Error loading skill details:", e);
      }
      if (window.lucide) lucide.createIcons();
    }
    function closeSkillDetailModal() {
      const modal = document.getElementById("skill-editor-modal");
      if (modal) modal.classList.add("hidden");
    }
    async function resetSkillDetailsToOriginal() {
      const skillId = document.getElementById("skill-edit-id")?.value;
      if (!skillId) return;
      if (!confirm(`Möchtest du den Skill '${skillId}' wirklich auf die Original-Version zurücksetzen?`)) {
        return;
      }
      try {
        const res = await fetch(`/api/hermes/skills/${encodeURIComponent(skillId)}/reset`, {
          method: "POST"
        });
        const data = await res.json();
        if (!res.ok) {
          showArchonToast(data.error || "Fehler beim Zurücksetzen.", "error");
          return;
        }
        const nameEl = document.getElementById("skill-edit-name");
        const catEl = document.getElementById("skill-edit-category");
        const tagsEl = document.getElementById("skill-edit-tags");
        const descEl = document.getElementById("skill-edit-desc");
        const contentEl = document.getElementById("skill-edit-content");
        const resetBtn = document.getElementById("skill-modal-reset-btn");
        if (nameEl && data.name) nameEl.value = data.name;
        if (catEl && data.category) catEl.value = data.category;
        if (tagsEl && data.tags) tagsEl.value = (data.tags || []).join(", ");
        if (descEl && data.description) descEl.value = data.description;
        if (contentEl && data.content) contentEl.value = data.content;
        if (resetBtn) {
          resetBtn.disabled = true;
          resetBtn.style.opacity = "0.5";
          resetBtn.title = "Bereits im Originalzustand";
        }
        await loadHermesSkillsFromServer();
        showArchonToast("Skill erfolgreich auf Original zurückgesetzt!", "success");
      } catch (e) {
        console.error("Reset skill error:", e);
        showArchonToast(`Fehler: ${e.message}`, "error");
      }
    }
    async function saveSkillDetailsFromModal() {
      const skillId = document.getElementById("skill-edit-id")?.value;
      const name = document.getElementById("skill-edit-name")?.value.trim();
      const category = document.getElementById("skill-edit-category")?.value.trim();
      const tags = (document.getElementById("skill-edit-tags")?.value || "").split(",").map(t => t.trim()).filter(Boolean);
      const description = document.getElementById("skill-edit-desc")?.value.trim();
      const content = document.getElementById("skill-edit-content")?.value;
      if (!name) {
        alert("Bitte gib einen Skill-Namen ein.");
        return;
      }
      const payload = { id: skillId, name, category, tags, description, content };
      try {
        const res = await fetch(`/api/hermes/skills/${encodeURIComponent(skillId)}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        if (!res.ok) {
          alert("Fehler beim Speichern der Skill-Spezifikation.");
          return;
        }
        await loadHermesSkillsFromServer();
        populateGlobalSkillsDropdown();
        
        const prof = hermesProfilesData.find(p => p.id === currentSelectedProfileId);
        if (prof && prof.skills) {
          renderActiveProfileSkillsTags(prof.skills);
        }
        closeSkillDetailModal();
        showArchonToast(`Skill '${name}' erfolgreich gespeichert!`, "success");
      } catch (e) {
        console.error("Save skill error:", e);
        showArchonToast(`Fehler: ${e.message}`, "error");
      }
    }
    function addSelectedSkillToProfile() {
      const select = document.getElementById("prof-add-skill-select");
      const skillId = select?.value;
      if (!skillId) return;
      const prof = hermesProfilesData.find(p => p.id === currentSelectedProfileId);
      if (!prof) {
        alert("Bitte wähle zuerst ein Profil aus.");
        return;
      }
      if (!prof.skills) prof.skills = [];
      if (!prof.skills.includes(skillId)) {
        prof.skills.push(skillId);
        renderActiveProfileSkillsTags(prof.skills);
        select.selectedIndex = 0;
      }
    }
    function removeSkillFromProfile(skillId) {
      const prof = hermesProfilesData.find(p => p.id === currentSelectedProfileId);
      if (!prof || !prof.skills) return;
      prof.skills = prof.skills.filter(s => s !== skillId);
      renderActiveProfileSkillsTags(prof.skills);
    }
    function showArchonToast(msg, type = "success") {
      let container = document.getElementById("archon-global-toast-container");
      if (!container) {
        container = document.createElement("div");
        container.id = "archon-global-toast-container";
        container.className = "fixed bottom-5 right-5 z-[999999] flex flex-col gap-2 pointer-events-none";
        document.body.appendChild(container);
      }
      const toast = document.createElement("div");
      const isErr = type === "error";
      toast.className = `pointer-events-auto px-4 py-2.5 rounded-xl shadow-2xl border text-xs font-mono font-bold flex items-center gap-2 transition-all duration-300 transform translate-y-2 opacity-0 ${
        isErr 
          ? 'bg-rose-50 text-rose-800 border-rose-300' 
          : 'bg-emerald-50 text-emerald-800 border-emerald-300'
      }`;
      toast.innerHTML = `<span>${isErr ? '❌' : '✅'}</span> <span>${escapeHtml(msg)}</span>`;
      container.appendChild(toast);
      requestAnimationFrame(() => {
        toast.classList.remove('translate-y-2', 'opacity-0');
      });
      setTimeout(() => {
        toast.classList.add('opacity-0', 'translate-y-2');
        setTimeout(() => toast.remove(), 350);
      }, 4000);
    }
    async function saveCurrentProfile(event) {
      if (event) {
        try { event.preventDefault(); event.stopPropagation(); } catch(e){}
      }
      const btn = document.getElementById("btn-save-profile");
      const originalBtnHtml = btn ? btn.innerHTML : '<i data-lucide="save" class="w-3.5 h-3.5"></i> Speichern';
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<svg class="animate-spin -ml-1 mr-1.5 h-3.5 w-3.5 text-white dark:text-zinc-900 inline" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg> Speichere...`;
      }
      try {
        const personName = (document.getElementById("prof-edit-person-name")?.value || "").trim();
        const name = (document.getElementById("prof-edit-name")?.value || "").trim();
        let id = (document.getElementById("prof-edit-id")?.value || "").trim();
        const category = document.getElementById("prof-edit-category")?.value || "1. Strategie, Führung & Lebensplanung";
        const description = (document.getElementById("prof-edit-desc")?.value || "").trim();
        const avatar = (document.getElementById("prof-edit-avatar")?.value || "").trim() || "/static/avatars/avatar_001.jpg";
        const prof = Array.isArray(hermesProfilesData) ? hermesProfilesData.find(p => p.id === currentSelectedProfileId) : null;
        const promptEl = document.getElementById("prof-edit-prompt");
        const prompt = (promptEl?.value || prof?.prompt || prof?.system_prompt || "").trim();
        if (!name && !personName) {
          showArchonToast("Bitte persönlichen Namen oder Stellenbeschreibung eingeben.", "error");
          if (btn) { btn.disabled = false; btn.innerHTML = originalBtnHtml; if (window.lucide) lucide.createIcons(); }
          return;
        }
        const finalRoleName = name || personName;
        const finalPersonName = personName || name;
        if (!id) {
          id = finalRoleName.toLowerCase().replace(/[^a-z0-9_]/g, '_');
        }
        const old_id = currentSelectedProfileId;
        let activeSkills = [];
        let activeTools = typeof DEFAULT_HERMES_TOOLS !== 'undefined' ? [...DEFAULT_HERMES_TOOLS] : [];
        if (prof) {
          if (Array.isArray(prof.skills)) activeSkills = [...prof.skills];
          if (Array.isArray(prof.tools)) activeTools = [...prof.tools];
        }
        const providerSelect = document.getElementById("prof-edit-provider");
        const provider = providerSelect?.value || (prof?.provider || "openrouter");
        const modelSelect = document.getElementById("prof-edit-model");
        const model = modelSelect?.value || (prof?.model || "deepseek/deepseek-v4-flash-0731");
        const reasoningSelect = document.getElementById("prof-edit-reasoning");
        const reasoning_level = reasoningSelect?.value || (prof?.reasoning_level || "high");
        const callsign = (document.getElementById("prof-edit-callsign")?.value || "").trim().toLowerCase().replace(/[^a-z0-9_]/g, '');
        const payload = {
          id,
          old_id,
          name: finalRoleName,
          person_name: finalPersonName,
          callsign,
          category,
          description,
          avatar,
          prompt: prompt || prof?.prompt || prof?.system_prompt || "",
          system_prompt: prompt || prof?.prompt || prof?.system_prompt || "",
          provider,
          model,
          reasoning_level,
          skills: activeSkills,
          tools: activeTools
        };
        const res = await fetch("/api/hermes/profiles", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        if (!res.ok) {
          let errDetail = "Fehler beim Speichern des Profils.";
          try {
            const errJson = await res.json();
            if (errJson.detail) {
              errDetail = typeof errJson.detail === "string" ? errJson.detail : JSON.stringify(errJson.detail);
            }
          } catch(e) {}
          showArchonToast(`Fehler (${res.status}): ${errDetail}`, "error");
          if (btn) {
            btn.innerHTML = `<span class="text-rose-500 font-bold">⚠️ Fehler</span>`;
            setTimeout(() => { if (btn) { btn.disabled = false; btn.innerHTML = originalBtnHtml; if (window.lucide) lucide.createIcons(); } }, 3000);
          }
          return;
        }
        // PERMISSION-GATE (12.10.2026): Rechte-Erweiterung braucht die
        // Owner-Bestaetigung per Telegram - NICHTS wird gespeichert.
        let _gateData = null;
        try { _gateData = await res.clone().json(); } catch(e) {}
        if (_gateData && _gateData.status === "pending_owner_approval" && _gateData.gate_id && confirm(`🔐 Sicherheits-Gate (${_gateData.gate_id}):\n${_gateData.message || "Neue Tool-Rechte erfordern Owner-Bestätigung."}\n\nMöchtest du diese Rechte-Erweiterung direkt hier im Browser freigeben?`)) { await fetch(`/api/permission-gates/${encodeURIComponent(_gateData.gate_id)}/decide`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ decision: "approve" }) }); showArchonToast("✅ Rechte-Gate direkt freigegeben & Profil gespeichert!", "success"); } else if (_gateData && _gateData.status === "pending_owner_approval") {
          showArchonToast("🔐 " + (_gateData.message || "Warte auf deine Telegram-Bestätigung."), "info");
          if (btn) { btn.disabled = false; btn.innerHTML = originalBtnHtml; if (window.lucide) lucide.createIcons(); }
          return;
        }
        // Parallel SOUL.md und Personalakte mitspeichern wenn Inhalte editiert wurden
        const soulEditor = document.getElementById("prof-soul-inline-editor");
        if (soulEditor && soulEditor.value.trim()) {
          fetch(`/api/v1/hermes/soul/${id}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ markdown: soulEditor.value })
          }).catch(console.error);
        }
        const paEditor = document.getElementById("pa-inline-raw-markdown");
        if (paEditor && paEditor.value.trim()) {
          fetch(`/api/v1/hr/personalakte/${id}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ markdown: paEditor.value })
          }).catch(console.error);
        }
        currentSelectedProfileId = id;
        try { localStorage.setItem("archon_active_profile_id", id); } catch(e){}
        await loadHermesProfilesFromServer();
        renderHermesProfilesList();
        selectProfileForEditor(id);
        if (typeof loadMasterChatProfiles === "function") {
          await loadMasterChatProfiles();
        }
        // Synchronisiere auch das geladene Organigramm im Speicher
        if (typeof currentHierarchyData !== "undefined" && currentHierarchyData && Array.isArray(currentHierarchyData.nodes)) {
          const orgNode = currentHierarchyData.nodes.find(n => n.id === id || n.id === old_id);
          if (orgNode) {
            orgNode.id = id;
            orgNode.name = finalRoleName;
            orgNode.role = finalRoleName;
            orgNode.person_name = finalPersonName;
            orgNode.avatar = avatar;
            orgNode.provider = provider;
            orgNode.model = model;
            orgNode.reasoning_level = reasoning_level;
            if (typeof renderOpsOrgFlowchart === "function") {
              try { renderOpsOrgFlowchart(); } catch(e) {}
            }
          }
        }
        if (btn) {
          btn.innerHTML = `<span class="text-emerald-400 font-bold">✓ Gespeichert!</span>`;
          setTimeout(() => {
            if (btn) {
              btn.disabled = false;
              btn.innerHTML = originalBtnHtml;
              if (window.lucide) lucide.createIcons();
            }
          }, 2500);
        }
      } catch (e) {
        console.error("Save profile error:", e);
        showArchonToast(`Verbindungsfehler: ${e.message}`, "error");
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = `<span class="text-rose-500 font-bold">⚠️ Fehler</span>`;
          setTimeout(() => { if (btn) { btn.innerHTML = originalBtnHtml; if (window.lucide) lucide.createIcons(); } }, 3000);
        }
      }
    }

    async function onProfileCallsignChanged(val) {
      const cleanVal = (val || "").trim().toLowerCase().replace(/[^a-z0-9_]/g, '');
      const input = document.getElementById("prof-edit-callsign");
      if (input) input.value = cleanVal;
      const statusEl = document.getElementById("prof-callsign-status");
      if (statusEl) {
        statusEl.classList.remove("hidden");
        statusEl.innerText = "⏳ Speichere...";
      }
      try {
        const prof = Array.isArray(hermesProfilesData) ? hermesProfilesData.find(p => p.id === currentSelectedProfileId) : null;
        if (!prof) return;
        prof.callsign = cleanVal;
        await saveCurrentProfile(null);
        if (statusEl) {
          statusEl.innerText = "✓ Gespeichert";
          setTimeout(() => { if (statusEl) statusEl.classList.add("hidden"); }, 2000);
        }
      } catch (err) {
        if (statusEl) {
          statusEl.innerText = "⚠️ Fehler";
          setTimeout(() => { if (statusEl) statusEl.classList.add("hidden"); }, 3000);
        }
      }
    }
    window.onProfileCallsignChanged = onProfileCallsignChanged;
// --- GLOBAL EXPORTS FR DOM-EVENTS ---
window.onAgentTabProviderChange = typeof onAgentTabProviderChange !== 'undefined' ? onAgentTabProviderChange : null;
window.onAgentTabModelChange = typeof onAgentTabModelChange !== 'undefined' ? onAgentTabModelChange : null;
window.handleAgentTabFileSelected = typeof handleAgentTabFileSelected !== 'undefined' ? handleAgentTabFileSelected : null;
window.removeAgentTabAttachment = typeof removeAgentTabAttachment !== 'undefined' ? removeAgentTabAttachment : null;
window.sendAgentTabChatMessage = typeof sendAgentTabChatMessage !== 'undefined' ? sendAgentTabChatMessage : null;
window.autoResizeAgentTabInput = typeof autoResizeAgentTabInput !== 'undefined' ? autoResizeAgentTabInput : null;
window.toggleAgentTabDictation = typeof toggleAgentTabDictation !== 'undefined' ? toggleAgentTabDictation : null;
window.onAgentHeaderProviderChange = typeof onAgentHeaderProviderChange !== 'undefined' ? onAgentHeaderProviderChange : null;
window.onAgentHeaderModelChange = typeof onAgentHeaderModelChange !== 'undefined' ? onAgentHeaderModelChange : null;
window.onProfileCategoryChange = typeof onProfileCategoryChange !== 'undefined' ? onProfileCategoryChange : null;
window.onProfileProviderChange = typeof onProfileProviderChange !== 'undefined' ? onProfileProviderChange : null;
window.filterProfilesByCategory = typeof filterProfilesByCategory !== 'undefined' ? filterProfilesByCategory : null;
window.handleAvatarFileSelected = typeof handleAvatarFileSelected !== 'undefined' ? handleAvatarFileSelected : null;
window.loadAgentTabChatMessages = typeof loadAgentTabChatMessages !== 'undefined' ? loadAgentTabChatMessages : null;
window.switchAgentCadreTab = typeof switchAgentCadreTab !== 'undefined' ? switchAgentCadreTab : null;
window.selectProfileForEditor = typeof selectProfileForEditor !== 'undefined' ? selectProfileForEditor : null;
window.applyProfileModelSelection = typeof applyProfileModelSelection !== 'undefined' ? applyProfileModelSelection : null;
window.renameCurrentAgentTabSession = typeof renameCurrentAgentTabSession !== 'undefined' ? renameCurrentAgentTabSession : null;
window.loadAgentTabChatSessions = typeof loadAgentTabChatSessions !== 'undefined' ? loadAgentTabChatSessions : null;
window.updateAgentChatSessionsDropdown = typeof loadAgentTabChatSessions !== 'undefined' ? loadAgentTabChatSessions : null;

    function onAgentTabReasoningChange(val) {
      const prof = hermesProfilesData.find(p => p.id === currentSelectedProfileId);
      if (prof) prof.reasoning_level = val;
      const reasoningSelect = document.getElementById("prof-edit-reasoning");
      if (reasoningSelect) reasoningSelect.value = val;
      if (currentSelectedProfileId) {
        const provider = currentAgentTabProvider || (prof && prof.provider) || "openrouter";
        const model = currentAgentTabModel || (prof && prof.model) || "auto/best-coding";
        fetch(`/api/hermes/profiles/${encodeURIComponent(currentSelectedProfileId)}/model`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ provider, model, reasoning_level: val })
        }).catch(e => console.warn("[Reasoning] Auto-save error:", e));
      }
    }
    window.onAgentTabReasoningChange = onAgentTabReasoningChange;
