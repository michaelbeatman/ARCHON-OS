import os
import json
import re

base_dir = "/app/project_root" if os.path.exists("/app/project_root") else r"C:\.Antigravity-projekte\AgenticOS-2026"
index_html_path = os.path.join(base_dir, "static", "index.html")

with open(index_html_path, "r", encoding="utf-8") as f:
    html = f.read()

boardroom_js_module = '''
    // ==========================================
    // AI MASTERMIND / BOARDROOM ARENA ENGINE
    // ==========================================

    function getRoleOptionsHtml(selectedRole) {
      const sourceRoles = (typeof roles !== 'undefined' && roles && roles.length > 0) ? roles : (typeof hermesProfilesData !== 'undefined' && hermesProfilesData ? hermesProfilesData : [
        { handle: "senior_fullstack_engineer", id: "senior_fullstack_engineer", display_name: "Senior Fullstack Engineer", name: "Senior Fullstack Engineer", category: "2. Software Development & Architecture" },
        { handle: "red_team_challenger", id: "red_team_challenger", display_name: "Red Team / Critical Challenger", name: "Red Team / Critical Challenger", category: "1. Strategie, Führung & Lebensplanung" },
        { handle: "system_architect_orchestrator", id: "system_architect_orchestrator", display_name: "System Architekt & Orchestrator", name: "System Architekt & Orchestrator", category: "2. Software Development & Architecture" },
        { handle: "gtm_launch_strategist", id: "gtm_launch_strategist", display_name: "Go-to-Market Stratege", name: "Go-to-Market Stratege", category: "4. Marketing, Sales & Growth" },
        { handle: "executive_decision_architect", id: "executive_decision_architect", display_name: "Executive Decision Architect", name: "Executive Decision Architect", category: "1. Strategie, Führung & Lebensplanung" }
      ]);

      const categories = {};
      sourceRoles.forEach(r => {
        const cat = r.category || "Allgemein";
        if (!categories[cat]) categories[cat] = [];
        categories[cat].push(r);
      });

      let html = "";
      for (const [catName, rList] of Object.entries(categories)) {
        html += `<optgroup label="${catName}">`;
        rList.forEach(r => {
          const rHandle = r.handle || r.id;
          const rName = r.display_name || r.name || rHandle;
          const isSelected = (rHandle === selectedRole || r.id === selectedRole || (r.name && r.name.toLowerCase() === (selectedRole || '').toLowerCase())) ? "selected" : "";
          html += `<option value="${rHandle}" ${isSelected}>${rName}</option>`;
        });
        html += `</optgroup>`;
      }
      return html;
    }

    function renderBoardroomSlots(frameworkName) {
      const container = document.getElementById("boardroom-slots-list");
      if (!container) return;
      
      const fwKey = frameworkName || "Steffi Kieffer Boardroom";
      const fwConfig = (typeof FRAMEWORK_SLOT_DEFAULTS !== 'undefined' && FRAMEWORK_SLOT_DEFAULTS[fwKey]) 
        ? FRAMEWORK_SLOT_DEFAULTS[fwKey] 
        : {
            chair: "executive_decision_architect",
            slots: [
              { role_name: "Skeptiker (Kritische Risikoprüfung)", default_profile: "red_team_challenger" },
              { role_name: "Innovator (Vision & Chancen)", default_profile: "gtm_launch_strategist" },
              { role_name: "Pragmatiker (Realisierung & Code)", default_profile: "senior_fullstack_engineer" }
            ]
          };

      if (fwConfig.chair) {
        populateBoardroomChairmanSelect(fwConfig.chair);
      }

      container.innerHTML = "";
      
      fwConfig.slots.forEach((s, idx) => {
        const slotEl = document.createElement("div");
        slotEl.className = "boardroom-slot-card p-2.5 bg-slate-50 border border-[#cbd5e1] rounded-xl flex items-center justify-between gap-2 text-xs shadow-xs transition hover:border-indigo-300";
        
        const avatarSeed = s.default_profile || `slot_${idx+1}`;
        const avatarUrl = `https://api.dicebear.com/7.x/notionists/svg?seed=${avatarSeed}&backgroundColor=3b82f6`;
        
        slotEl.innerHTML = `
          <div class="flex items-center gap-2 min-w-0 flex-1">
            <div class="relative shrink-0">
              <img src="${avatarUrl}" alt="Avatar" class="boardroom-slot-avatar w-7 h-7 rounded-full object-cover border border-slate-300 shadow-xs" onerror="this.src='/static/avatars/avatar_001.jpg'">
              <span class="absolute -bottom-1 -right-1 w-3.5 h-3.5 rounded-full bg-white border border-slate-300 flex items-center justify-center text-[8px] font-bold text-slate-600 font-mono shadow-2xs">${idx+1}</span>
            </div>
            <div class="min-w-0 flex-1">
              <input type="text" value="${s.role_name}" class="boardroom-slot-name w-full bg-transparent font-bold text-slate-800 text-[11px] focus:outline-none border-b border-transparent focus:border-indigo-400 font-sans truncate" placeholder="Rollenbezeichnung..." title="${s.role_name}">
              <div class="flex items-center gap-1 mt-0.5">
                <select class="boardroom-slot-role w-full bg-white border border-slate-200 rounded px-1.5 py-0.5 text-[10px] text-slate-700 focus:outline-none cursor-pointer truncate font-mono shadow-2xs" onchange="onBoardroomSlotRoleChange(this)">
                  ${getRoleOptionsHtml(s.default_profile)}
                </select>
              </div>
            </div>
          </div>
          <button type="button" onclick="removeBoardroomSlot(this)" class="shrink-0 p-1 text-slate-400 hover:text-rose-500 rounded-lg hover:bg-rose-50 transition cursor-pointer" title="Slot entfernen">
            <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
          </button>
        `;
        container.appendChild(slotEl);
      });
      lucide.createIcons();
    }

    function addBoardroomCustomSlot() {
      const container = document.getElementById("boardroom-slots-list");
      if (!container) return;
      const count = container.children.length + 1;
      const slotEl = document.createElement("div");
      slotEl.className = "boardroom-slot-card p-2.5 bg-slate-50 border border-[#cbd5e1] rounded-xl flex items-center justify-between gap-2 text-xs shadow-xs transition hover:border-indigo-300";
      
      const avatarUrl = `https://api.dicebear.com/7.x/notionists/svg?seed=custom_${count}&backgroundColor=3b82f6`;
      
      slotEl.innerHTML = `
        <div class="flex items-center gap-2 min-w-0 flex-1">
          <div class="relative shrink-0">
            <img src="${avatarUrl}" alt="Avatar" class="boardroom-slot-avatar w-7 h-7 rounded-full object-cover border border-slate-300 shadow-xs" onerror="this.src='/static/avatars/avatar_001.jpg'">
            <span class="absolute -bottom-1 -right-1 w-3.5 h-3.5 rounded-full bg-white border border-slate-300 flex items-center justify-center text-[8px] font-bold text-slate-600 font-mono shadow-2xs">${count}</span>
          </div>
          <div class="min-w-0 flex-1">
            <input type="text" value="Experte ${count} (Fachexpertise)" class="boardroom-slot-name w-full bg-transparent font-bold text-slate-800 text-[11px] focus:outline-none border-b border-transparent focus:border-indigo-400 font-sans truncate" placeholder="Rollenbezeichnung...">
            <div class="flex items-center gap-1 mt-0.5">
              <select class="boardroom-slot-role w-full bg-white border border-slate-200 rounded px-1.5 py-0.5 text-[10px] text-slate-700 focus:outline-none cursor-pointer truncate font-mono shadow-2xs" onchange="onBoardroomSlotRoleChange(this)">
                ${getRoleOptionsHtml("senior_fullstack_engineer")}
              </select>
            </div>
          </div>
        </div>
        <button type="button" onclick="removeBoardroomSlot(this)" class="shrink-0 p-1 text-slate-400 hover:text-rose-500 rounded-lg hover:bg-rose-50 transition cursor-pointer" title="Slot entfernen">
          <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
        </button>
      `;
      container.appendChild(slotEl);
      lucide.createIcons();
    }

    function removeBoardroomSlot(btn) {
      const card = btn.closest(".boardroom-slot-card");
      if (card) {
        card.remove();
      }
    }

    function onBoardroomSlotRoleChange(selectEl) {
      const card = selectEl.closest(".boardroom-slot-card");
      if (!card) return;
      const avatarImg = card.querySelector(".boardroom-slot-avatar");
      if (avatarImg) {
        const val = selectEl.value;
        const sourceRoles = (typeof roles !== 'undefined' && roles && roles.length > 0) ? roles : (typeof hermesProfilesData !== 'undefined' ? hermesProfilesData : []);
        const matched = sourceRoles.find(r => (r.handle === val || r.id === val));
        if (matched && matched.avatar) {
          avatarImg.src = matched.avatar;
        } else {
          avatarImg.src = `https://api.dicebear.com/7.x/notionists/svg?seed=${val}&backgroundColor=3b82f6`;
        }
      }
    }

    function onBoardroomChairmanChange() {
      const select = document.getElementById("boardroom-chairman-select");
      const avatarImg = document.getElementById("boardroom-chair-avatar");
      if (!select || !avatarImg) return;
      const val = select.value;
      const sourceRoles = (typeof roles !== 'undefined' && roles && roles.length > 0) ? roles : (typeof hermesProfilesData !== 'undefined' ? hermesProfilesData : []);
      const matched = sourceRoles.find(r => (r.handle === val || r.id === val));
      if (matched && matched.avatar) {
        avatarImg.src = matched.avatar;
      } else {
        avatarImg.src = `https://api.dicebear.com/7.x/notionists/svg?seed=${val}&backgroundColor=6366f1`;
      }
    }

    function onBoardroomFrameworkChange() {
      const select = document.getElementById("boardroom-framework-select");
      if (!select) return;
      updateFrameworkSummaryTooltip();
      renderBoardroomSlots(select.value);
    }

    async function loadBoardroomFrameworks() {
      const select = document.getElementById("boardroom-framework-select");
      if (!select) return;
      try {
        const res = await fetch("/api/boardroom/frameworks");
        if (!res.ok) return;
        categorizedFrameworksData = await res.json();
        select.innerHTML = "";
        
        let isFirst = true;
        for (const [catName, frameworks] of Object.entries(categorizedFrameworksData)) {
          const group = document.createElement("optgroup");
          group.label = catName;
          for (const [fwName, fwData] of Object.entries(frameworks)) {
            const opt = document.createElement("option");
            opt.value = fwName;
            opt.innerText = fwName;
            const summaryText = typeof fwData === "string" ? fwData : (fwData.summary || fwData.system_instruction || "");
            opt.setAttribute("data-summary", summaryText);
            if (fwName === "CLEAR-Model" || isFirst) {
              opt.selected = true;
              isFirst = false;
            }
            group.appendChild(opt);
          }
          select.appendChild(group);
        }
        updateFrameworkSummaryTooltip();
        renderBoardroomSlots(select.value || "CLEAR-Model");
      } catch (e) {
        console.error("Error loading boardroom frameworks:", e);
      }
    }

    function updateFrameworkSummaryTooltip() {
      const select = document.getElementById("boardroom-framework-select");
      const summaryEl = document.getElementById("boardroom-framework-summary");
      if (!select || !summaryEl) return;
      const selectedOpt = select.options[select.selectedIndex];
      if (selectedOpt) {
        const text = selectedOpt.getAttribute("data-summary") || selectedOpt.value || "";
        summaryEl.value = text;
        summaryEl.innerText = text;
      }
    }

    function populateBoardroomChairmanSelect(selectedChairId) {
      const select = document.getElementById("boardroom-chairman-select");
      if (!select) return;
      
      const targetId = selectedChairId || select.value || "executive_decision_architect";
      const sourceRoles = (typeof roles !== 'undefined' && roles && roles.length > 0) ? roles : (typeof hermesProfilesData !== 'undefined' && hermesProfilesData ? hermesProfilesData : [
        { handle: "executive_decision_architect", id: "executive_decision_architect", display_name: "Executive Decision Architect", name: "Executive Decision Architect", category: "1. Strategie, Führung & Lebensplanung" }
      ]);

      select.innerHTML = "";
      const categories = {};
      sourceRoles.forEach(r => {
        const cat = r.category || "Management";
        if (!categories[cat]) categories[cat] = [];
        categories[cat].push(r);
      });

      for (const [catName, rList] of Object.entries(categories)) {
        const group = document.createElement("optgroup");
        group.label = catName;
        rList.forEach(r => {
          const opt = document.createElement("option");
          const rHandle = r.handle || r.id;
          opt.value = rHandle;
          opt.innerText = `${r.display_name || r.name || rHandle}`;
          if (rHandle === targetId || r.id === targetId) {
            opt.selected = true;
          }
          group.appendChild(opt);
        });
        select.appendChild(group);
      }
      if (select.selectedIndex === -1 && select.options.length > 0) {
        let found = false;
        for (let i = 0; i < select.options.length; i++) {
          if (select.options[i].value === targetId) {
            select.selectedIndex = i;
            found = true;
            break;
          }
        }
        if (!found) select.options[0].selected = true;
      }
      onBoardroomChairmanChange();
    }

    async function runBoardroomDebate() {
      const taskInput = document.getElementById("boardroom-task");
      const roundsInput = document.getElementById("boardroom-rounds");
      const chairmanSelect = document.getElementById("boardroom-chairman-select");
      const frameworkSelect = document.getElementById("boardroom-framework-select");
      const threadEl = document.getElementById("boardroom-thread");
      const loadingEl = document.getElementById("boardroom-loading");
      const startBtn = document.getElementById("boardroom-start-btn");

      const task = taskInput ? taskInput.value.trim() : "";
      if (!task) {
        alert("Bitte gib eine Aufgabenstellung für den Boardroom ein.");
        return;
      }

      const rounds = roundsInput ? parseInt(roundsInput.value) || 2 : 2;
      const chairmanId = chairmanSelect ? chairmanSelect.value : "executive_decision_architect";
      const framework = frameworkSelect ? frameworkSelect.value : "Steffi Kieffer Boardroom";

      // Sammle aktive Slots
      const slotCards = document.querySelectorAll("#boardroom-slots-list .boardroom-slot-card");
      const slotsPayload = [];
      slotCards.forEach(card => {
        const nameInput = card.querySelector(".boardroom-slot-name");
        const roleSelect = card.querySelector(".boardroom-slot-role");
        if (nameInput && roleSelect) {
          slotsPayload.push({
            role_name: nameInput.value.trim(),
            profile_id: roleSelect.value
          });
        }
      });

      if (loadingEl) loadingEl.classList.remove("hidden");
      if (startBtn) startBtn.disabled = true;

      // Initialisiere UI mit Starter-Event
      if (threadEl) {
        threadEl.innerHTML = `
          <div class="p-3 rounded-xl bg-indigo-50 border border-indigo-200 text-xs text-indigo-900 font-mono space-y-1 shadow-xs">
            <div class="flex items-center justify-between font-bold">
              <span>🚀 INITIALISIERE MASTERMIND DEBATTE</span>
              <span class="text-[10px] text-indigo-600">${framework}</span>
            </div>
            <p class="text-[11px] text-indigo-700">${task}</p>
          </div>
        `;
      }

      try {
        const res = await fetch("/api/boardroom/run", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            task: task,
            rounds: rounds,
            chairman_id: chairmanId,
            framework: framework,
            slots: slotsPayload
          })
        });

        const data = await res.json();
        if (!res.ok || data.status === "error") {
          throw new Error(data.content || data.detail || "Debatte fehlgeschlagen.");
        }

        if (threadEl && data.events) {
          threadEl.innerHTML = "";
          data.events.forEach(ev => {
            const isChairman = ev.type === "chairman_init" || ev.type === "chairman_synthesis";
            const bubbleEl = document.createElement("div");
            bubbleEl.className = isChairman 
              ? "p-3.5 rounded-2xl bg-indigo-50/90 border border-indigo-200 text-xs shadow-xs space-y-1.5"
              : "p-3.5 rounded-2xl bg-white border border-slate-200 text-xs shadow-xs space-y-1.5";

            const headerBadge = isChairman 
              ? `<span class="px-2 py-0.5 rounded-md bg-indigo-600 text-white font-mono text-[9.5px] font-bold uppercase">${ev.type === 'chairman_init' ? 'Moderator Briefing' : 'Finale Synthese'}</span>`
              : `<span class="px-2 py-0.5 rounded-md bg-slate-100 text-slate-700 border border-slate-300 font-mono text-[9.5px] font-bold">Runde ${ev.round} • ${ev.role || 'Experte'}</span>`;

            const avatarUrl = `https://api.dicebear.com/7.x/notionists/svg?seed=${ev.agent_id}&backgroundColor=${isChairman ? '6366f1' : '3b82f6'}`;

            bubbleEl.innerHTML = `
              <div class="flex items-center justify-between pb-1 border-b border-black/5">
                <div class="flex items-center gap-2">
                  <img src="${avatarUrl}" class="w-6 h-6 rounded-full border border-slate-300" onerror="this.src='/static/avatars/avatar_001.jpg'">
                  <span class="font-bold text-slate-800 text-[11px]">${ev.agent_name || ev.agent_id}</span>
                </div>
                ${headerBadge}
              </div>
              <div class="text-slate-700 font-sans text-xs leading-relaxed whitespace-pre-wrap select-text">${ev.content}</div>
            `;
            threadEl.appendChild(bubbleEl);
          });
          threadEl.scrollTop = threadEl.scrollHeight;
        }

      } catch (e) {
        if (threadEl) {
          const errEl = document.createElement("div");
          errEl.className = "p-3 rounded-xl bg-rose-50 border border-rose-200 text-xs text-rose-700 font-mono";
          errEl.innerText = `Fehler bei der Ausführung: ${e.message || e}`;
          threadEl.appendChild(errEl);
        }
      } finally {
        if (loadingEl) loadingEl.classList.add("hidden");
        if (startBtn) startBtn.disabled = false;
        lucide.createIcons();
      }
    }

    function clearBoardroomThread() {
      const threadEl = document.getElementById("boardroom-thread");
      if (threadEl) {
        threadEl.innerHTML = `
          <div class="h-full flex flex-col items-center justify-center text-center p-6 text-slate-400">
            <div class="w-12 h-12 rounded-full bg-white border border-slate-200 shadow-xs flex items-center justify-center mb-3">
              <i data-lucide="message-square" class="w-6 h-6 text-slate-400"></i>
            </div>
            <p class="text-xs font-bold prof-title-text">Noch keine Boardroom-Debatte aktiv</p>
            <p class="text-[11px] prof-desc-text mt-1 max-w-sm">Gib oben deine Fragestellung ein, wähle rechts die Methodik und klicke auf "Debatte starten".</p>
          </div>
        `;
        lucide.createIcons();
      }
    }

    let isBoardroomDictating = false;
    let boardroomRecognition = null;

    function toggleBoardroomDictation() {
      const btn = document.getElementById("boardroom-mic-btn");
      const textarea = document.getElementById("boardroom-task");
      if (!textarea) return;

      if (!("webkitSpeechRecognition" in window || "SpeechRecognition" in window)) {
        alert("Spracherkennung wird in diesem Browser nicht unterstützt. Bitte nutze Google Chrome oder Edge.");
        return;
      }

      if (isBoardroomDictating && boardroomRecognition) {
        boardroomRecognition.stop();
        isBoardroomDictating = false;
        if (btn) btn.classList.remove("text-red-500", "animate-pulse", "border-red-500");
        return;
      }

      const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
      boardroomRecognition = new SpeechRecognition();
      boardroomRecognition.continuous = true;
      boardroomRecognition.interimResults = true;
      boardroomRecognition.lang = "de-DE";

      let baseText = textarea.value ? textarea.value.trim() + " " : "";

      boardroomRecognition.onresult = (event) => {
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
      };

      boardroomRecognition.onerror = (event) => {
        console.error("Speech recognition error:", event.error);
        isBoardroomDictating = false;
        if (btn) btn.classList.remove("text-red-500", "animate-pulse", "border-red-500");
      };

      boardroomRecognition.onend = () => {
        isBoardroomDictating = false;
        if (btn) btn.classList.remove("text-red-500", "animate-pulse", "border-red-500");
      };

      boardroomRecognition.start();
      isBoardroomDictating = true;
      if (btn) {
        btn.classList.add("text-red-500", "animate-pulse", "border-red-500");
        btn.title = "Diktieren läuft... Klicken zum Stoppen";
      }
    }
'''

# Find end of FRAMEWORK_SLOT_DEFAULTS
anchor = "const FRAMEWORK_SLOT_DEFAULTS = "
fw_idx = html.find(anchor)
if fw_idx != -1:
    # find closing semicolon of this object
    end_fw_idx = html.find("};\n", fw_idx)
    if end_fw_idx != -1:
        insert_pos = end_fw_idx + 3
        # Check if already present
        if "function renderBoardroomSlots" not in html:
            html = html[:insert_pos] + "\n" + boardroom_js_module + "\n" + html[insert_pos:]

with open(index_html_path, "w", encoding="utf-8") as f:
    f.write(html)

print(f"Successfully integrated Mastermind JS module into {index_html_path}")
