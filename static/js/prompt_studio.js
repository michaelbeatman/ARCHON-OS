

    // --- i18n-Helfer (Tranche 3) ---------------------------------------------
    // psT() liefert den Katalogtext mit PFLICHT-Fallback: fehlt der Key in der
    // aktiven Sprache und in de, bleibt der deutsche Text stehen - nie "".
    // {platzhalter} werden aus params gefuellt (Zahlen stehen nie im Key).
    function psT(key, fallback, params) {
      const i18n = window.archonI18n;
      let text = i18n ? i18n.t(key, fallback) : fallback;
      if (params) {
        Object.keys(params).forEach(name => {
          text = text.split(`{${name}}`).join(String(params[name]));
        });
      }
      return text;
    }
    // psLocale() ist das Sprach-Tag fuer Intl/toLocaleString: die Ausgabesprache
    // folgt dem Katalog statt eines festen "de-DE".
    function psLocale() {
      return (window.archonI18n && window.archonI18n.currentLang) || "de";
    }

    // =========================================================================
    // PROMPT-TEMPLATES (5-FELDER-STRUKTUR) & FABRIC-PATTERNS (255+ MUSTER)
    // =========================================================================
    let currentPromptTemplatesData = { categories: [], templates: [] };
    let currentFabricPatternsData = [];
    let selectedPromptTemplateId = null;
    let currentSelectedPatternDetail = null;
    let currentPromptTemplateTarget = "master"; // "master" or "agent"
    let currentCategoryFilter = "all";
    // Favoriten-Management via localStorage
    function getFavoritePatternIds() {
      try {
        const raw = localStorage.getItem("archon_fav_patterns");
        return raw ? JSON.parse(raw) : [];
      } catch (e) {
        return [];
      }
    }
    function isPatternFavorite(id) {
      return getFavoritePatternIds().includes(id);
    }
    function toggleFavoritePattern(id, event) {
      if (event) event.stopPropagation();
      let favs = getFavoritePatternIds();
      if (favs.includes(id)) {
        favs = favs.filter(x => x !== id);
      } else {
        favs.push(id);
      }
      try {
        localStorage.setItem("archon_fav_patterns", JSON.stringify(favs));
      } catch (e) {}
      updateFavoriteBadges();
      renderPromptTemplateCards();
      updateDetailFavIcon();
    }
    function toggleCurrentFavorite() {
      if (!selectedPromptTemplateId) return;
      toggleFavoritePattern(selectedPromptTemplateId);
    }
    function updateFavoriteBadges() {
      const favs = getFavoritePatternIds();
      const countEl = document.getElementById("tpl-fav-count");
      if (countEl) countEl.innerText = favs.length;
    }
    function updateDetailFavIcon() {
      const btn = document.getElementById("tpl-detail-fav-btn");
      if (!btn) return;
      const isFav = isPatternFavorite(selectedPromptTemplateId);
      btn.innerHTML = isFav 
        ? `<i data-lucide="star" class="w-4 h-4 text-amber-500 fill-amber-400"></i>`
        : `<i data-lucide="star" class="w-4 h-4 text-slate-400"></i>`;
      if (window.lucide) window.lucide.createIcons();
    }
    async function openPromptTemplateModal(target = "master") {
      currentPromptTemplateTarget = target;
      const modal = document.getElementById("prompt-template-modal");
      if (!modal) return;
      modal.classList.remove("hidden");
      updateFavoriteBadges();
      if (window.lucide) window.lucide.createIcons();
      await loadPromptTemplates();
    }
    function closePromptTemplateModal() {
      const modal = document.getElementById("prompt-template-modal");
      if (modal) modal.classList.add("hidden");
    }
    async function loadPromptTemplates() {
      const loading = document.getElementById("tpl-list-loading");
      const wrapper = document.getElementById("tpl-cards-wrapper");
      if (loading) loading.classList.remove("hidden");
      if (wrapper) wrapper.innerHTML = "";
      try {
        // Parallel laden: Standard-Templates und 255 Fabric-Patterns
        const [resTpl, resFab] = await Promise.all([
          fetch("/api/templates").catch(() => null),
          fetch("/api/fabric/patterns").catch(() => null)
        ]);
        if (resTpl && resTpl.ok) {
          currentPromptTemplatesData = await resTpl.json();
        }
        if (resFab && resFab.ok) {
          const fabData = await resFab.json();
          currentFabricPatternsData = fabData.patterns || [];
          const badge = document.getElementById("tpl-count-badge");
          if (badge) badge.innerText = `${psT('ui.prompt_studio.count_muster', '{count}+ Muster', { count: currentFabricPatternsData.length })}`;
        }
        updateFavoriteBadges();
        renderPromptTemplateCards();
        // Erstes Item selektieren
        const allItems = getAllCombinedTemplates();
        if (allItems.length > 0 && !selectedPromptTemplateId) {
          selectPromptTemplate(allItems[0].id);
        }
      } catch (e) {
        console.error("[Fabric & Templates] Fehler beim Laden:", e);
      } finally {
        if (loading) loading.classList.add("hidden");
      }
    }
    function getAllCombinedTemplates() {
      const standard = (currentPromptTemplatesData.templates || []).map(t => ({
        id: t.id,
        title: t.title,
        name_de: t.title,
        category: t.category,
        description: t.description || "",
        purpose: t.description || "",
        isFabric: false,
        raw_text: t.raw_text,
        fields: t.fields
      }));
      const fabric = (currentFabricPatternsData || []).map(f => ({
        id: f.id,
        title: f.name_de,
        name_de: f.name_de,
        category: f.category,
        description: f.purpose || "",
        purpose: f.purpose || "",
        variables: f.variables || "",
        isFabric: true
      }));
      return [...fabric, ...standard];
    }
    function filterPromptTemplates(cat) {
      currentCategoryFilter = cat;
      const btns = document.querySelectorAll(".tpl-cat-btn");
      btns.forEach(b => {
        if (b.dataset.cat === cat) {
          b.className = "tpl-cat-btn px-3 py-1.5 rounded-xl text-xs font-bold border border-indigo-600 bg-indigo-50 text-indigo-700 shadow-xs transition cursor-pointer shrink-0";
        } else if (b.dataset.cat === "Favoriten") {
          b.className = "tpl-cat-btn px-3 py-1.5 rounded-xl text-xs font-bold border border-amber-300 bg-amber-50 text-amber-700 hover:bg-amber-100 shadow-xs flex items-center gap-1 transition cursor-pointer shrink-0";
        } else {
          b.className = "tpl-cat-btn px-3 py-1.5 rounded-xl text-xs font-medium border border-slate-200 bg-white text-slate-700 hover:text-indigo-600 hover:border-indigo-300 shadow-xs hover:shadow-md transition cursor-pointer shrink-0";
        }
      });
      renderPromptTemplateCards();
    }
    function searchPromptTemplates(query) {
      renderPromptTemplateCards(query.trim().toLowerCase());
    }
    function renderPromptTemplateCards(search = "") {
      const wrapper = document.getElementById("tpl-cards-wrapper");
      if (!wrapper) return;
      wrapper.innerHTML = "";
      const favIds = getFavoritePatternIds();
      const all = getAllCombinedTemplates();
      const filtered = all.filter(t => {
        let matchesCat = true;
        if (currentCategoryFilter === "Favoriten") {
          matchesCat = favIds.includes(t.id);
        } else if (currentCategoryFilter !== "all") {
          matchesCat = t.category.toLowerCase() === currentCategoryFilter.toLowerCase();
        }
        const matchesSearch = !search || 
          t.title.toLowerCase().includes(search) || 
          t.id.toLowerCase().includes(search) ||
          (t.description && t.description.toLowerCase().includes(search)) ||
          t.category.toLowerCase().includes(search);
        return matchesCat && matchesSearch;
      });
      if (filtered.length === 0) {
        wrapper.innerHTML = `
          <div class="p-8 text-center text-xs text-slate-400 italic">
            ${currentCategoryFilter === "Favoriten" ? psT('ui.prompt_studio.no_fav_templates', 'Noch keine Favoriten gespeichert.<br>Klicke auf das Sternchen ★ bei einem Muster!') : psT('ui.prompt_studio.no_match_templates', 'Keine passenden Muster gefunden')}
          </div>
        `;
        return;
      }
      filtered.forEach(t => {
        const isSel = t.id === selectedPromptTemplateId;
        const isFav = favIds.includes(t.id);
        const card = document.createElement("div");
        card.className = `p-3 rounded-2xl border transition cursor-pointer group ${
          isSel 
            ? 'border-indigo-600 bg-indigo-50/80 shadow-sm' 
            : 'border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50/90 shadow-2xs hover:shadow-xs'
        }`;
        card.onclick = () => selectPromptTemplate(t.id);
        
        card.innerHTML = `
          <div class="flex items-center justify-between gap-1 mb-1">
            <span class="text-[9px] font-mono font-bold uppercase px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 truncate max-w-[130px]">${t.category}</span>
            <div class="flex items-center gap-1">
              <span class="text-[9px] font-mono text-indigo-600 font-semibold">${t.isFabric ? 'Fabric' : psT('ui.prompt_studio.five_fields', '5-Felder')}</span>
              <button 
                type="button" 
                onclick="toggleFavoritePattern('${t.id}', event)" 
                class="p-0.5 rounded hover:bg-slate-200 transition text-slate-300 hover:text-amber-500"
                title="${isFav ? psT('ui.prompt_studio.favorite_remove', 'Aus Favoriten entfernen') : psT('ui.prompt_studio.favorite_add', 'Zu Favoriten hinzufügen')}"
              >
                <i data-lucide="star" class="w-3.5 h-3.5 ${isFav ? 'text-amber-500 fill-amber-400' : ''}"></i>
              </button>
            </div>
          </div>
          <h4 class="text-xs font-bold text-slate-900 truncate">${t.title}</h4>
          <p class="text-[11px] text-slate-500 line-clamp-2 mt-0.5 leading-snug">${t.description || t.variables || ''}</p>
        `;
        wrapper.appendChild(card);
      });
      if (window.lucide) window.lucide.createIcons();
    }
    async function selectPromptTemplate(tplId) {
      selectedPromptTemplateId = tplId;
      const hint = document.getElementById("tpl-empty-hint");
      const detail = document.getElementById("tpl-detail-content");
      const createForm = document.getElementById("tpl-create-form");
      if (createForm) createForm.classList.add("hidden");
      if (hint) hint.classList.add("hidden");
      if (detail) detail.classList.remove("hidden");
      // Highlight in list
      const cards = document.querySelectorAll("#tpl-cards-wrapper > div");
      // Find item
      const all = getAllCombinedTemplates();
      const item = all.find(x => x.id === tplId);
      if (!item) return;
      document.getElementById("tpl-detail-category").innerText = item.category;
      document.getElementById("tpl-detail-title").innerText = item.title;
      document.getElementById("tpl-detail-desc").innerText = item.description || item.purpose || "";
      updateDetailFavIcon();
      // Fabric Details laden (falls Fabric Pattern)
      if (item.isFabric) {
        try {
          const res = await fetch(`/api/fabric/pattern/${tplId}`);
          if (res.ok) {
            currentSelectedPatternDetail = await res.json();
          } else {
            currentSelectedPatternDetail = { template_de: item.description, pattern: item };
          }
        } catch (e) {
          currentSelectedPatternDetail = { template_de: item.description, pattern: item };
        }
      } else {
        currentSelectedPatternDetail = {
          template_de: item.raw_text || `# ROLLE:\n${item.fields?.rolle || ''}\n\n# ZIEL:\n${item.fields?.ziel || ''}`,
          pattern: item
        };
      }
      updateLivePromptPreview();
      if (window.lucide) window.lucide.createIcons();
    }
    function buildAssembledPrompt() {
      if (!currentSelectedPatternDetail) return "";
      const base = currentSelectedPatternDetail.template_de || "";
      const contextVal = document.getElementById("tpl-var-context")?.value?.trim() || "";
      const focusVal = document.getElementById("tpl-var-focus")?.value?.trim() || "";
      const styleVal = document.getElementById("tpl-var-style")?.value || "Ausführlicher strukturierter Analysebericht";
      let assembled = `${base}\n\n`;
      if (contextVal) {
        assembled += `### EINGABE / ZU ANALYSIERENDER KONTEXT:\n${contextVal}\n\n`;
      }
      if (focusVal) {
        assembled += `### SPEZIFISCHER SCHWERPUNKT / FRAGESTELLUNG:\n${focusVal}\n\n`;
      }
      assembled += `### GEWÜNSCHTES AUSGABEFORMAT:\nBitte erstelle das Ergebnis auf Deutsch als: ${styleVal}.\n`;
      return assembled.trim();
    }
    function updateLivePromptPreview() {
      const previewEl = document.getElementById("tpl-live-preview");
      if (!previewEl) return;
      previewEl.innerText = buildAssembledPrompt();
    }
    function applySelectedPromptTemplate() {
      const assembledText = buildAssembledPrompt();
      if (!assembledText) return;
      const targetId = currentPromptTemplateTarget === "agent" ? "agent-chat-input" : "master-chat-input";
      const textarea = document.getElementById(targetId);
      if (textarea) {
        // Anhangen, falls schon Text vorhanden
        const currentVal = textarea.value.trim();
        textarea.value = currentVal ? `${currentVal}\n\n${assembledText}` : assembledText;
        // Auto-Resize aufrufen (wächst bis max 30% Viewport-Höhe)
        if (typeof autoResizeMasterChatInput === "function") {
          autoResizeMasterChatInput(textarea);
        }
        // Sofort ins Chateingabefeld fokussieren
        textarea.focus();
        textarea.scrollIntoView({ behavior: "smooth", block: "nearest" });
        textarea.classList.add("ring-2", "ring-indigo-500");
        setTimeout(() => textarea.classList.remove("ring-2", "ring-indigo-500"), 1500);
      }
      // Visuelles Feedback auf dem Button (Modal bleibt offen wie vom Nutzer gewünscht!)
      const applyBtn = document.getElementById("tpl-apply-btn");
      if (applyBtn) {
        const originalHtml = applyBtn.innerHTML;
        applyBtn.innerHTML = `<span>${psT('ui.prompt_studio.applied_chat', '✓ Im Chat eingefügt')}</span><i data-lucide="check" class="w-3.5 h-3.5 text-emerald-400"></i>`;
        applyBtn.classList.replace("bg-slate-900", "bg-emerald-700");
        if (window.lucide) window.lucide.createIcons();
        setTimeout(() => {
          applyBtn.innerHTML = originalHtml;
          applyBtn.classList.replace("bg-emerald-700", "bg-slate-900");
          if (window.lucide) window.lucide.createIcons();
        }, 2200);
      }
    }
    function copyCurrentTemplateToClipboard() {
      const assembledText = buildAssembledPrompt();
      if (!assembledText) return;
      navigator.clipboard.writeText(assembledText).then(() => {
        const lbl = document.getElementById("tpl-copy-label");
        if (lbl) {
          lbl.innerText = psT('ui.prompt_studio.copied', 'Kopiert!');
          setTimeout(() => { lbl.innerText = psT('ui.prompt_studio.copied_label', 'Kopieren'); }, 1800);
        }
      });
    }
    function togglePromptTemplateCreateForm() {
      const form = document.getElementById("tpl-create-form");
      const detail = document.getElementById("tpl-detail-content");
      const hint = document.getElementById("tpl-empty-hint");
      const btnLabel = document.getElementById("tpl-create-btn-label");
      if (!form) return;
      if (form.classList.contains("hidden")) {
        form.classList.remove("hidden");
        if (detail) detail.classList.add("hidden");
        if (hint) hint.classList.add("hidden");
        if (btnLabel) btnLabel.innerText = psT('ui.prompt_studio.back_to_view', 'Zurück zur Ansicht');
      } else {
        form.classList.add("hidden");
        if (btnLabel) btnLabel.innerText = psT('ui.prompt_studio.create', 'Neue Vorlage');
        if (selectedPromptTemplateId) {
          if (detail) detail.classList.remove("hidden");
        } else {
          if (hint) hint.classList.remove("hidden");
        }
      }
    }
    async function submitNewPromptTemplate() {
      const cat = document.getElementById("new-tpl-cat")?.value || "Strategie & Business";
      const title = document.getElementById("new-tpl-title")?.value?.trim();
      const rolle = document.getElementById("new-tpl-rolle")?.value?.trim();
      const ziel = document.getElementById("new-tpl-ziel")?.value?.trim();
      const sop = document.getElementById("new-tpl-sop")?.value?.trim();
      const restriktionen = document.getElementById("new-tpl-restriktionen")?.value?.trim();
      const artefakt = document.getElementById("new-tpl-artefakt")?.value?.trim();
      if (!title || !ziel) {
        alert(psT('ui.prompt_studio.err_title_goal_required', 'Bitte mindestens Titel und Ziel der Vorlage angeben.'));
        return;
      }
      const payload = {
        category: cat,
        title: title,
        description: `Individuelle Vorlage: ${title}`,
        fields: {
          rolle: rolle || "Spezialist",
          ziel: ziel,
          sop: sop || "",
          restriktionen: restriktionen || "- Phrasenverbot: Keine Höflichkeitsfloskeln.",
          ausgabe_artefakt: artefakt || "Obsidian Markdown Dokument"
        }
      };
      try {
        const res = await fetch("/api/templates", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        if (res.ok) {
          const respData = await res.json();
          togglePromptTemplateCreateForm();
          await loadPromptTemplates();
          if (respData.template?.id) {
            selectPromptTemplate(respData.template.id);
          }
        } else {
          alert(psT('ui.prompt_studio.err_template_save', 'Fehler beim Speichern der Vorlage.'));
        }
      } catch (e) {
        console.error("[Templates] Submit-Fehler:", e);
        alert(psT('ui.prompt_studio.err_server_save', 'Serverfehler beim Speichern.'));
      }
    }
    // =========================================================================
    // ARCHON PROMPT STUDIO (824 ENTERPRISE TEMPLATES + 255 FABRIC SOPS = 1.079)
    // =========================================================================
    let currentSurePromptsCatalog = [];
    let selectedSurePromptId = null;
    let selectedSurePromptData = null;
    let currentSurePromptsTarget = "master";
    let currentSurePromptsFilter = "all";
    let surePromptsFormValues = {};
    function getFavoriteSurePromptIds() {
      try {
        const stored = localStorage.getItem("archon_fav_prompts") || localStorage.getItem("archon_fav_sureprompts");
        return stored ? JSON.parse(stored) : [];
      } catch (e) {
        return [];
      }
    }
    function isSurePromptFavorite(id) {
      return getFavoriteSurePromptIds().includes(id);
    }
    function toggleFavoriteSurePrompt(id, ev) {
      if (ev) ev.stopPropagation();
      let favs = getFavoriteSurePromptIds();
      if (favs.includes(id)) {
        favs = favs.filter(f => f !== id);
      } else {
        favs.push(id);
      }
      localStorage.setItem("archon_fav_prompts", JSON.stringify(favs)); localStorage.setItem("archon_fav_sureprompts", JSON.stringify(favs));
      updateSurePromptsFavoriteBadges();
      updateSurePromptDetailFavIcon();
      renderSurePromptsCards(document.getElementById("sp-search-input")?.value || "");
    }
    function toggleCurrentSurePromptsFavorite() {
      if (!selectedSurePromptId) return;
      toggleFavoriteSurePrompt(selectedSurePromptId);
    }
    function updateSurePromptsFavoriteBadges() {
      const favs = getFavoriteSurePromptIds();
      const countEl = document.getElementById("sp-fav-count");
      if (countEl) countEl.innerText = favs.length;
    }
    function updateSurePromptDetailFavIcon() {
      const btn = document.getElementById("sp-detail-fav-btn");
      if (!btn) return;
      const isFav = isSurePromptFavorite(selectedSurePromptId);
      btn.innerHTML = isFav 
        ? `<i data-lucide="star" class="w-4 h-4 text-amber-500 fill-amber-400"></i>`
        : `<i data-lucide="star" class="w-4 h-4 text-slate-400"></i>`;
      if (window.lucide) window.lucide.createIcons();
    }
    async function openSurePromptsModal(target = "master") {
      currentSurePromptsTarget = target;
      const modal = document.getElementById("sureprompts-modal");
      if (!modal) return;
      const applyBtnSpan = document.querySelector("#sp-apply-btn span");
      if (applyBtnSpan) {
        applyBtnSpan.textContent = target === "ops-task" ? psT('ui.prompt_studio.apply_to_task', 'In Aufgabe übernehmen') : psT('ui.prompt_studio.use_in_chat', 'In Chat übernehmen');
      }
      modal.classList.remove("hidden");
      updateSurePromptsFavoriteBadges();
      if (window.lucide) window.lucide.createIcons();
      await loadSurePromptsCatalog();
    }
    function closeSurePromptsModal() {
      const modal = document.getElementById("sureprompts-modal");
      if (modal) modal.classList.add("hidden");
    }
    // Aliases fuer Archon Prompt Studio
    window.openPromptStudioModal = openSurePromptsModal;
    window.closePromptStudioModal = closeSurePromptsModal;
    window.openSurePromptsModal = openSurePromptsModal;
    window.closeSurePromptsModal = closeSurePromptsModal;
    async function loadSurePromptsCatalog() {
      const loading = document.getElementById("sp-list-loading");
      const wrapper = document.getElementById("sp-cards-wrapper");
      if (loading) loading.classList.remove("hidden");
      if (wrapper) wrapper.innerHTML = "";
      try {
        // Parallel laden: SurePrompts und Fabric-Patterns
        const [tplRes, fabRes] = await Promise.all([
          fetch("/api/templates/catalog").catch(() => null),
          fetch("/api/fabric/patterns").catch(() => null)
        ]);
        let sureTemplates = [];
        if (tplRes && tplRes.ok) {
          const tplData = await tplRes.json();
          sureTemplates = tplData.templates || [];
        }
        let fabricTemplates = [];
        if (fabRes && fabRes.ok) {
          const fabData = await fabRes.json();
          fabricTemplates = (fabData.patterns || []).map(p => {
            const rawCat = p.category || "Allgemein & Produktivität";
            const prefixedCat = "Fabric " + rawCat;
            return {
              id: "fabric__" + p.id,
              original_id: p.id,
              name: p.name_de || p.id,
              name_de: p.name_de || p.id,
              category: prefixedCat,
              category_slug: "fabric",
              raw_category: rawCat,
              isFabric: true,
              description: p.purpose || psT('ui.prompt_studio.fabric_default_desc', 'Spezialisiertes Fabric SOP-Analysemuster'),
              description_de: p.purpose || psT('ui.prompt_studio.fabric_default_desc', 'Spezialisiertes Fabric SOP-Analysemuster'),
              field_count: 3,
              form_fields: [
                {
                  id: "context_input",
                  label: psT('ui.prompt_studio.field_context', 'Eingabekontext / Rohtext'),
                  label_de: psT('ui.prompt_studio.field_context', 'Eingabekontext / Rohtext'),
                  type: "multiline",
                  required: true,
                  placeholder_de: psT('ui.prompt_studio.field_context_ph', 'Füge hier den zu analysierenden Text, Code, Notizen oder Rohdaten ein...')
                },
                {
                  id: "specific_focus",
                  label: psT('ui.prompt_studio.field_focus', 'Besonderer Fokus / Leitfrage'),
                  label_de: psT('ui.prompt_studio.field_focus', 'Besonderer Fokus / Leitfrage'),
                  type: "text",
                  required: false,
                  placeholder_de: psT('ui.prompt_studio.field_focus_ph', 'z. B. Fokus auf Risiken, Einsparpotenziale oder Handlungsempfehlungen...')
                },
                {
                  id: "output_style",
                  label: psT('ui.prompt_studio.field_format', 'Ausgabeformat'),
                  label_de: psT('ui.prompt_studio.field_format', 'Ausgabeformat'),
                  type: "select",
                  required: false,
                  placeholder_de: psT('ui.prompt_studio.field_format_ph', 'z. B. Strukturierter Markdown-Bericht')
                }
              ],
              archon_prompt_template: `# EXPERTEN-ROLLE & PROFIL:
Du agierst als spezialisierter Senior-Experte für: ${p.name_de || p.id}.
${p.purpose || ''}
# ANALYSE-AUFGABE & SCHWERPUNKT:
Analysiere die übergebene Eingabe systematisch, methodisch fundiert und ohne Floskeln oder Füllwörter.
{{ specific_focus }}
# EINGABEDATEN / KONTEXT:
{{ context_input }}
# AUSGABESTRUKTUR & FORM:
{{ output_style }}
Erstelle die Auswertung vollständig auf Deutsch, präzise gegliedert in Markdown mit konkreten Handlungsempfehlungen.
4. ARCHON OS GOVERNANCE & PHRASEN-VERBOT
- Vermeide Floskeln wie "Gerne!", "Ich hoffe das hilft!", "In der heutigen dynamischen Welt".
- Antworte direkt, substanziell, mit echten Fakten, Zahlen und klaren Handlungsschritten.`
            };
          });
        }
        currentSurePromptsCatalog = [...sureTemplates, ...fabricTemplates];
        const countBadge = document.getElementById("sp-count-badge");
        if (countBadge) countBadge.innerText = `${psT('ui.prompt_studio.count_templates_sops', '{count} Vorlagen & SOPs', { count: currentSurePromptsCatalog.length })}`;
        updateSurePromptsFavoriteBadges();
        renderSurePromptsCards(document.getElementById("sp-search-input")?.value || "");
        if (currentSurePromptsCatalog.length > 0 && !selectedSurePromptId) {
          selectSurePrompt(currentSurePromptsCatalog[0].id);
        }
      } catch (e) {
        console.error("[Archon Prompt Studio] Fehler beim Laden des Katalogs:", e);
      } finally {
        if (loading) loading.classList.add("hidden");
      }
    }
    function filterSurePrompts(cat) {
      currentSurePromptsFilter = cat;
      const btns = document.querySelectorAll(".sp-cat-btn");
      btns.forEach(b => {
        if (b.dataset.cat === cat) {
          if (cat === "Favoriten") {
            b.className = "sp-cat-btn w-full text-left px-2.5 py-1.5 rounded-lg text-xs font-bold border border-amber-400 bg-amber-100 text-amber-900 shadow-xs flex items-center justify-between transition cursor-pointer";
          } else {
            b.className = "sp-cat-btn w-full text-left px-2.5 py-1.5 rounded-lg text-xs font-bold border border-red-600 bg-red-600 text-white shadow-xs flex items-center justify-between transition cursor-pointer";
          }
        } else if (b.dataset.cat === "Favoriten") {
          b.className = "sp-cat-btn w-full text-left px-2.5 py-1.5 rounded-lg text-xs font-bold border border-amber-300 bg-amber-50 text-amber-800 hover:bg-amber-100 shadow-2xs flex items-center justify-between transition cursor-pointer";
        } else {
          b.className = "sp-cat-btn w-full text-left px-2.5 py-1.5 rounded-lg text-xs font-medium border border-transparent bg-transparent text-slate-700 hover:bg-white hover:border-slate-200 hover:text-red-600 hover:shadow-2xs transition cursor-pointer flex items-center justify-between";
        }
      });
      renderSurePromptsCards(document.getElementById("sp-search-input")?.value || "");
    }
    function searchSurePrompts(query) {
      renderSurePromptsCards(query.trim().toLowerCase());
    }
    function renderSurePromptsCards(search = "") {
      const wrapper = document.getElementById("sp-cards-wrapper");
      if (!wrapper) return;
      wrapper.innerHTML = "";
      const favIds = getFavoriteSurePromptIds();
      const filtered = currentSurePromptsCatalog.filter(t => {
        let matchesCat = true;
        if (currentSurePromptsFilter === "Favoriten") {
          matchesCat = favIds.includes(t.id);
        } else if (currentSurePromptsFilter === "Fabric (Alle)" || currentSurePromptsFilter === "Fabric" || currentSurePromptsFilter === "Fabric SOP-Muster") {
          matchesCat = !!t.isFabric || (t.category && t.category.toLowerCase().startsWith("fabric"));
        } else if (currentSurePromptsFilter !== "all") {
          const filterLower = currentSurePromptsFilter.toLowerCase();
          matchesCat = (t.category && t.category.toLowerCase() === filterLower) ||
                       (t.raw_category && ("fabric " + t.raw_category.toLowerCase()) === filterLower) ||
                       (t.category_slug && t.category_slug.toLowerCase() === filterLower);
        }
        const matchesSearch = !search ||
          (t.name && t.name.toLowerCase().includes(search)) ||
          (t.name_de && t.name_de.toLowerCase().includes(search)) ||
          (t.id && t.id.toLowerCase().includes(search)) ||
          (t.description && t.description.toLowerCase().includes(search)) ||
          (t.description_de && t.description_de.toLowerCase().includes(search)) ||
          (t.category && t.category.toLowerCase().includes(search));
        return matchesCat && matchesSearch;
      });
      const countLabel = document.getElementById("sp-cards-count-label");
      if (countLabel) countLabel.textContent = `${filtered.length}`;
      if (filtered.length === 0) {
        wrapper.innerHTML = `
          <div class="p-8 text-center text-xs text-slate-400 italic">
            ${currentSurePromptsFilter === "Favoriten" ? psT('ui.prompt_studio.no_fav_prompts', 'Noch keine Favoriten gespeichert.<br>Klicke auf das Sternchen ★ bei einer Vorlage!') : psT('ui.prompt_studio.no_match_prompts', 'Keine passenden Vorlagen gefunden')}
          </div>
        `;
        return;
      }
      filtered.forEach(t => {
        const isSel = t.id === selectedSurePromptId;
        const isFav = favIds.includes(t.id);
        const fCount = t.form_fields ? t.form_fields.length : (t.field_count || 0);
        const card = document.createElement("div");
        card.className = `p-2.5 rounded-xl border transition cursor-pointer group ${
          isSel
            ? 'border-2 border-[#d42a2b] bg-white shadow-md'
            : 'border-slate-200 bg-white hover:border-slate-300 hover:shadow-md hover:bg-white shadow-md'
        }`;
        card.onclick = () => selectSurePrompt(t.id);
        card.innerHTML = `
          <div class="flex items-center justify-between gap-1 mb-1">
            <div class="flex items-center gap-1 min-w-0">
              <span class="text-[9px] font-mono font-bold uppercase px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 truncate max-w-[125px]" title="${t.category || ''}">${t.category || ''}</span>
              <span class="text-[9px] font-mono font-medium px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 shrink-0">${fCount} ${fCount === 1 ? psT('ui.prompt_studio.unit_field', 'Feld') : psT('ui.prompt_studio.unit_fields', 'Felder')}</span>
            </div>
            <button 
              type="button" 
              onclick="toggleFavoriteSurePrompt('${t.id}', event)" 
              class="p-0.5 rounded hover:bg-slate-200 text-slate-400 hover:text-amber-500 transition cursor-pointer shrink-0" 
              title="${psT('ui.prompt_studio.favorite_tooltip', 'Favorit')}"
            >
              <i data-lucide="star" class="w-3.5 h-3.5 ${isFav ? 'text-amber-500 fill-amber-400' : 'text-slate-300 group-hover:text-slate-400'}"></i>
            </button>
          </div>
          <div class="text-xs font-bold text-slate-800 group-hover:text-red-600 transition leading-snug truncate">${t.name_de || t.name}</div>
          <p class="text-[10.5px] text-slate-500 mt-0.5 line-clamp-2 leading-relaxed">${t.description_de || t.description || ''}</p>
        `;
        wrapper.appendChild(card);
      });
      if (window.lucide) window.lucide.createIcons();
    }
    async function selectSurePrompt(id) {
      selectedSurePromptId = id;
      renderSurePromptsCards(document.getElementById("sp-search-input")?.value || "");
      const hint = document.getElementById("sp-form-empty");
      const content = document.getElementById("sp-form-content");
      if (hint) hint.classList.add("hidden");
      if (content) content.classList.remove("hidden");
      try {
        if (id.startsWith("fabric__")) {
          const item = currentSurePromptsCatalog.find(t => t.id === id);
          if (item && item.archon_prompt_template) {
            selectedSurePromptData = item;
          } else {
            const origId = id.replace("fabric__", "");
            const res = await fetch(`/api/fabric/pattern/${origId}`);
            if (!res.ok) throw new Error(psT('ui.prompt_studio.err_fabric_load', 'Fabric-Pattern konnte nicht geladen werden'));
            const data = await res.json();
            const pat = data.pattern || {};
            const rawCat = pat.category || "Allgemein & Produktivität";
            selectedSurePromptData = {
              id: id,
              name_de: pat.name_de || origId,
              category: "Fabric " + rawCat,
              raw_category: rawCat,
              description_de: pat.purpose || psT('ui.prompt_studio.fabric_desc_short', 'Fabric SOP-Analysemuster'),
              form_fields: [
                {
                  id: "context_input",
                  label: psT('ui.prompt_studio.field_context', 'Eingabekontext / Rohtext'),
                  label_de: psT('ui.prompt_studio.field_context', 'Eingabekontext / Rohtext'),
                  type: "multiline",
                  required: true,
                  placeholder_de: psT('ui.prompt_studio.field_context_ph', 'Füge hier den zu analysierenden Text, Code, Notizen oder Rohdaten ein...')
                },
                {
                  id: "specific_focus",
                  label: psT('ui.prompt_studio.field_focus', 'Besonderer Fokus / Leitfrage'),
                  label_de: psT('ui.prompt_studio.field_focus', 'Besonderer Fokus / Leitfrage'),
                  type: "text",
                  required: false,
                  placeholder_de: psT('ui.prompt_studio.field_focus_ph', 'z. B. Fokus auf Risiken, Einsparpotenziale oder Handlungsempfehlungen...')
                },
                {
                  id: "output_style",
                  label: psT('ui.prompt_studio.field_format', 'Ausgabeformat'),
                  label_de: psT('ui.prompt_studio.field_format', 'Ausgabeformat'),
                  type: "select",
                  required: false,
                  placeholder_de: psT('ui.prompt_studio.field_format_ph', 'z. B. Strukturierter Markdown-Bericht')
                }
              ],
              archon_prompt_template: `# EXPERTEN-ROLLE & PROFIL:
Du agierst als spezialisierter Senior-Experte für: ${pat.name_de || origId}.
${pat.purpose || ''}
# ANALYSE-AUFGABE & SCHWERPUNKT:
Analysiere die übergebene Eingabe systematisch, methodisch fundiert und ohne Floskeln.
{{ specific_focus }}
# EINGABEDATEN / KONTEXT:
{{ context_input }}
# AUSGABESTRUKTUR & FORM:
{{ output_style }}
Erstelle die Auswertung vollständig auf Deutsch, präzise gegliedert in Markdown mit konkreten Handlungsschritten.
4. ARCHON OS GOVERNANCE & PHRASEN-VERBOT
- Vermeide Floskeln wie "Gerne!", "Ich hoffe das hilft!".
- Antworte direkt, substanziell mit echten Fakten.`
            };
          }
        } else {
          const res = await fetch(`/api/templates/${id}/schema`);
          if (!res.ok) throw new Error(psT('ui.prompt_studio.err_schema_load', 'Schema konnte nicht geladen werden'));
          const data = await res.json();
          selectedSurePromptData = data.template;
        }
        const titleEl = document.getElementById("sp-detail-title");
        const catEl = document.getElementById("sp-detail-category");
        const descEl = document.getElementById("sp-detail-desc");
        if (titleEl) titleEl.innerText = selectedSurePromptData.name_de || selectedSurePromptData.name || selectedSurePromptData.id;
        if (catEl) catEl.innerText = selectedSurePromptData.category || "";
        if (descEl) descEl.innerText = selectedSurePromptData.description_de || selectedSurePromptData.description || "";
        updateSurePromptDetailFavIcon();
        // Formular-Felder generieren
        buildDynamicFormFields(selectedSurePromptData.form_fields || []);
        updateSurePromptLivePreview();
      } catch (e) {
        console.error("[Archon Prompt Studio] Fehler beim Laden des Schemas:", e);
      }
    }
    function applySurePromptsPreset(preset) {
      const presetsConfig = {
        analytical: {
          stepbystep: true, reasoning: true, perspectives: true, systematic: true,
          confidence: true, citations: true, cot: true, roleplay: false, examplesCount: 0
        },
        creative: {
          stepbystep: false, reasoning: false, perspectives: true, systematic: false,
          confidence: false, citations: false, cot: false, roleplay: true, examplesCount: 1
        },
        professional: {
          stepbystep: false, reasoning: true, perspectives: false, systematic: true,
          confidence: false, citations: false, cot: false, roleplay: false, examplesCount: 0
        },
        thorough: {
          stepbystep: true, reasoning: true, perspectives: true, systematic: true,
          confidence: true, citations: true, cot: true, roleplay: false, examplesCount: 2
        }
      };
      const cfg = presetsConfig[preset];
      if (!cfg) return;
      const setCheck = (id, val) => {
        const el = document.getElementById(id);
        if (el) el.checked = !!val;
      };
      setCheck("sp-opt-stepbystep", cfg.stepbystep);
      setCheck("sp-opt-reasoning", cfg.reasoning);
      setCheck("sp-opt-perspectives", cfg.perspectives);
      setCheck("sp-opt-systematic", cfg.systematic);
      setCheck("sp-opt-confidence", cfg.confidence);
      setCheck("sp-opt-citations", cfg.citations);
      setCheck("sp-opt-cot", cfg.cot);
      setCheck("sp-opt-roleplay", cfg.roleplay);
      const exCountEl = document.getElementById("sp-opt-examples-count");
      if (exCountEl) exCountEl.value = cfg.examplesCount;
      document.querySelectorAll(".sp-preset-btn").forEach(btn => {
        if (btn.dataset.preset === preset) {
          btn.classList.add("ring-2", "ring-red-600", "border-red-600", "bg-red-50/50");
        } else {
          btn.classList.remove("ring-2", "ring-red-600", "border-red-600", "bg-red-50/50");
        }
      });
      updateSurePromptLivePreview();
    }
    function resetSurePromptsAdvancedOptions() {
      const ids = [
        "sp-opt-stepbystep", "sp-opt-reasoning", "sp-opt-perspectives", "sp-opt-systematic",
        "sp-opt-confidence", "sp-opt-citations", "sp-opt-cot", "sp-opt-roleplay"
      ];
      ids.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.checked = false;
      });
      const exCount = document.getElementById("sp-opt-examples-count");
      if (exCount) exCount.value = 0;
      const ctx = document.getElementById("sp-opt-context");
      if (ctx) ctx.value = "";
      const ex = document.getElementById("sp-opt-examples");
      if (ex) ex.value = "";
      const succ = document.getElementById("sp-opt-success");
      if (succ) succ.value = "";
      document.querySelectorAll(".sp-preset-btn").forEach(btn => {
        btn.classList.remove("ring-2", "ring-red-600", "border-red-600", "bg-red-50/50");
      });
      updateSurePromptLivePreview();
    }
    function buildDynamicFormFields(fields) {
      const container = document.getElementById("sp-dynamic-fields-container");
      if (!container) return;
      container.innerHTML = "";
      surePromptsFormValues = {};
      if (!fields || fields.length === 0) {
        container.innerHTML = `<p class="text-xs text-slate-400 italic">${psT('ui.prompt_studio.no_form_vars', 'Keine zusätzlichen Formularvariablen erforderlich. Der Prompt ist direkt einsatzbereit.')}</p>`;
        return;
      }
      // Vordefinierte Auswahllisten für Dropdowns & Datalists
      const presets = {
        tone: [psT('ui.prompt_studio.tone_professional', 'Professionell & Sachlich'), psT('ui.prompt_studio.tone_persuasive', 'Überzeugend & Dynamisch'), psT('ui.prompt_studio.tone_analytical', 'Analytisch & Tiefgründig'), psT('ui.prompt_studio.tone_concise', 'Direkt & Prägnant'), psT('ui.prompt_studio.tone_inspiring', 'Inspirierend & Visionär'), psT('ui.prompt_studio.tone_casual', 'Locker & Nahbar')],
        length: [psT('ui.prompt_studio.len_compact', 'Kompakt (ca. 400-600 Wörter)'), psT('ui.prompt_studio.len_standard', 'Standard (ca. 800-1200 Wörter)'), psT('ui.prompt_studio.len_deep', 'Ausführlich / Deep Dive (1500-2500 Wörter)'), psT('ui.prompt_studio.len_whitepaper', 'Umfassendes Whitepaper / Report')],
        format: [psT('ui.prompt_studio.fmt_markdown', 'Strukturierter Markdown-Bericht'), psT('ui.prompt_studio.fmt_sop', 'Schritt-für-Schritt SOP'), psT('ui.prompt_studio.fmt_summary_tables', 'Executive Summary mit Tabellen'), psT('ui.prompt_studio.fmt_analysis_recs', 'Gegliederte Analyse mit Handlungsempfehlungen'), psT('ui.prompt_studio.fmt_bullets', 'Prägnante Bullet-Points')],
        audience: [psT('ui.prompt_studio.aud_clevel', 'Geschäftsführung / C-Level'), psT('ui.prompt_studio.aud_department', 'Fachabteilung / Teamleiter'), psT('ui.prompt_studio.aud_developers', 'Entwickler & Technische Architekten'), psT('ui.prompt_studio.aud_b2b', 'B2B-Kunden & Entscheider'), psT('ui.prompt_studio.aud_public', 'Breite Öffentlichkeit / Endnutzer')]
      };
      fields.forEach(f => {
        const fId = f.id;
        const fLabel = f.label_de || f.label || f.id;
        const placeholderText = f.placeholder_de || psT('ui.prompt_studio.field_placeholder_hint', 'z. B. {label} eingeben...', { label: fLabel });
        const isRequired = !!f.required;
        const isMultiline = f.type === "multiline" || fId.includes("description") || fId.includes("outline") || fId.includes("context") || fId.includes("details") || fId.includes("avoid") || fId.includes("tips");
        const isSelect = f.type === "select" || fId.includes("tone") || fId.includes("length") || fId.includes("format");
        const fieldWrapper = document.createElement("div");
        fieldWrapper.className = "space-y-1";
        let datalistId = `dl-${fId}`;
        let matchedPreset = null;
        if (fId.includes("tone")) matchedPreset = presets.tone;
        else if (fId.includes("length")) matchedPreset = presets.length;
        else if (fId.includes("format") || fId.includes("output")) matchedPreset = presets.format;
        else if (fId.includes("audience") || fId.includes("target")) matchedPreset = presets.audience;
        let inputHtml = "";
        if (isMultiline) {
          inputHtml = `
            <textarea 
              id="sp-input-${fId}" 
              rows="2" 
              placeholder="${placeholderText}" 
              class="w-full text-xs bg-white border border-slate-200 rounded-xl px-3 py-2 text-slate-800 placeholder:text-slate-400 focus:outline-none focus:border-red-500 shadow-2xs resize-y"
            ></textarea>
          `;
        } else if (isSelect && (matchedPreset || f.options)) {
          const opts = f.options || matchedPreset;
          inputHtml = `
            <div class="relative">
              <select 
                id="sp-input-${fId}" 
                class="w-full text-xs bg-white border border-slate-200 rounded-xl px-3 py-2 text-slate-800 focus:outline-none focus:border-red-500 shadow-2xs appearance-none pr-8 cursor-pointer"
              >
                <option value="">${psT('ui.prompt_studio.select_placeholder', '-- Bitte wählen ({state}) --', { state: isRequired ? psT('ui.prompt_studio.required_short', 'Pflicht') : psT('ui.prompt_studio.optional', 'Optional') })}</option>
                ${opts.map(opt => `<option value="${opt}">${opt}</option>`).join("")}
              </select>
              <i data-lucide="chevron-down" class="w-3.5 h-3.5 text-slate-400 absolute right-3 top-2.5 pointer-events-none"></i>
            </div>
          `;
        } else {
          inputHtml = `
            <input 
              type="text" 
              id="sp-input-${fId}" 
              list="${matchedPreset ? datalistId : ''}" 
              placeholder="${placeholderText}" 
              class="w-full text-xs bg-white border border-slate-200 rounded-xl px-3 py-2 text-slate-800 placeholder:text-slate-400 focus:outline-none focus:border-red-500 shadow-2xs"
            />
            ${matchedPreset ? `
              <datalist id="${datalistId}">
                ${matchedPreset.map(opt => `<option value="${opt}"></option>`).join("")}
              </datalist>
            ` : ''}
          `;
        }
        fieldWrapper.innerHTML = `
          <div class="flex items-center justify-between text-[11px]">
            <label for="sp-input-${fId}" class="font-semibold text-slate-700">
              ${fLabel} ${isRequired ? '<span class="text-rose-500 font-bold">*</span>' : ''}
            </label>
            <span class="text-[9.5px] ${isRequired ? 'text-rose-600 font-bold' : 'text-slate-400'}">
              ${isRequired ? psT('ui.prompt_studio.required', 'Erforderlich') : psT('ui.prompt_studio.optional', 'Optional')}
            </span>
          </div>
          ${inputHtml}
        `;
        container.appendChild(fieldWrapper);
        const el = container.querySelector(`#sp-input-${fId}`);
        if (el) {
          el.addEventListener("input", () => {
            surePromptsFormValues[fId] = el.value;
            updateSurePromptLivePreview();
          });
          el.addEventListener("change", () => {
            surePromptsFormValues[fId] = el.value;
            updateSurePromptLivePreview();
          });
        }
      });
      if (window.lucide) window.lucide.createIcons();
    }
    // =========================================================================
    // PROMPT STUDIO: CONTEXT ENGINE & FILE UPLOAD
    // =========================================================================
    let surePromptsUploadedFiles = []; // { filename, ext, char_count, extracted_text }
    function handleSpDragOver(e) {
      e.preventDefault();
      e.stopPropagation();
      const dropzone = document.getElementById("sp-file-dropzone");
      if (dropzone) dropzone.classList.add("border-red-500", "bg-red-50/40");
    }
    function handleSpDragLeave(e) {
      e.preventDefault();
      e.stopPropagation();
      const dropzone = document.getElementById("sp-file-dropzone");
      if (dropzone) dropzone.classList.remove("border-red-500", "bg-red-50/40");
    }
    function handleSpDrop(e) {
      e.preventDefault();
      e.stopPropagation();
      const dropzone = document.getElementById("sp-file-dropzone");
      if (dropzone) dropzone.classList.remove("border-red-500", "bg-red-50/40");
      if (e.dataTransfer && e.dataTransfer.files) {
        uploadFilesToPromptStudio(e.dataTransfer.files);
      }
    }
    function handleSpFileSelect(e) {
      if (e.target && e.target.files) {
        uploadFilesToPromptStudio(e.target.files);
        e.target.value = "";
      }
    }
    async function uploadFilesToPromptStudio(files) {
      if (!files || files.length === 0) return;
      const spinner = document.getElementById("sp-file-uploading");
      if (spinner) spinner.classList.remove("hidden");
      for (let i = 0; i < files.length; i++) {
        const file = files[i];
        const formData = new FormData();
        formData.append("file", file);
        try {
          const res = await fetch("/api/prompt-studio/upload-context", {
            method: "POST",
            body: formData
          });
          if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: psT('ui.prompt_studio.err_upload_failed', 'Upload fehlgeschlagen') }));
            alert(psT('ui.prompt_studio.err_upload_file', 'Fehler beim Hochladen von {file}: {detail}', { file: file.name, detail: err.detail || psT('ui.prompt_studio.unknown_error', 'Unbekannter Fehler') }));
            continue;
          }
          const data = await res.json();
          const existingIdx = surePromptsUploadedFiles.findIndex(f => f.filename === data.filename);
          if (existingIdx !== -1) {
            surePromptsUploadedFiles[existingIdx] = data;
          } else {
            surePromptsUploadedFiles.push(data);
          }
        } catch (e) {
          console.error("[Prompt Studio Context] Upload-Fehler:", e);
          alert(psT('ui.prompt_studio.err_upload_conn', 'Upload-Fehler bei {file}: {message}', { file: file.name, message: e.message }));
        }
      }
      if (spinner) spinner.classList.add("hidden");
      renderSpUploadedFilesList();
      updateSurePromptLivePreview();
    }
    function removeUploadedContextFile(idx) {
      if (idx >= 0 && idx < surePromptsUploadedFiles.length) {
        surePromptsUploadedFiles.splice(idx, 1);
        renderSpUploadedFilesList();
        updateSurePromptLivePreview();
      }
    }
    function renderSpUploadedFilesList() {
      const listEl = document.getElementById("sp-uploaded-files-list");
      const badgeEl = document.getElementById("sp-upload-char-count");
      if (!listEl) return;
      listEl.innerHTML = "";
      let totalChars = 0;
      surePromptsUploadedFiles.forEach((file, idx) => {
        totalChars += (file.char_count || 0);
        const item = document.createElement("div");
        item.className = "flex items-center justify-between p-2 rounded-xl bg-white border border-slate-200 text-xs shadow-2xs";
        
        const ext = (file.filename.split('.').pop() || 'file').toUpperCase();
        item.innerHTML = `
          <div class="flex items-center gap-2 min-w-0 pr-2">
            <span class="px-1.5 py-0.5 rounded text-[9px] font-mono font-bold bg-red-100 text-red-700">${ext}</span>
            <div class="min-w-0">
              <div class="font-medium text-slate-800 truncate" title="${file.filename}">${file.filename}</div>
              <div class="text-[9.5px] text-slate-400 font-mono">${psT('ui.prompt_studio.chars_extracted', '{count} Zeichen extrahiert', { count: (file.char_count || 0).toLocaleString(psLocale()) })}</div>
            </div>
          </div>
          <button 
            type="button" 
            onclick="removeUploadedContextFile(${idx})" 
            class="p-1 rounded-md text-slate-400 hover:text-red-600 hover:bg-slate-100 transition cursor-pointer shrink-0" 
            title="${psT('ui.prompt_studio.remove_file', 'Datei entfernen')}"
          >
            <i data-lucide="x" class="w-3.5 h-3.5"></i>
          </button>
        `;
        listEl.appendChild(item);
      });
      if (badgeEl) {
        badgeEl.innerText = psT('ui.prompt_studio.char_budget', '{count} / 25.000 Zeichen', { count: totalChars.toLocaleString(psLocale()) });
        if (totalChars > 25000) {
          badgeEl.className = "text-[10px] text-rose-600 font-mono font-bold";
        } else if (totalChars > 0) {
          badgeEl.className = "text-[10px] text-emerald-600 font-mono font-semibold";
        } else {
          badgeEl.className = "text-[10px] text-slate-500 font-mono";
        }
      }
      if (window.lucide) window.lucide.createIcons();
    }
    function buildAssembledSurePrompt() {
      if (!selectedSurePromptData) return "";
      const rawTemplate = selectedSurePromptData.archon_prompt_template || "";
      const fields = selectedSurePromptData.form_fields || [];
      // Verhalten A: Leere optionale Variablen und deren Zeilen rückstandslos entfernen
      const lines = rawTemplate.split("\n");
      const renderedLines = [];
      for (let line of lines) {
        let skipLine = false;
        // Regex für {{ var_name }}
        const regex = /\{\{\s*([a-zA-Z0-9_]+)\s*\}\}/g;
        let match;
        // Finde alle Variablen in dieser Zeile
        const varsInLine = [];
        while ((match = regex.exec(line)) !== null) {
          varsInLine.push(match[1]);
        }
        for (const varName of varsInLine) {
          const val = (surePromptsFormValues[varName] || "").trim();
          const fieldDef = fields.find(f => f.id === varName);
          const isRequired = fieldDef ? fieldDef.required : false;
          if (!val) {
            if (!isRequired) {
              // Verhalten A: Optionale leere Variable -> gesamte Zeile verwerfen!
              skipLine = true;
              break;
            } else {
              // Pflichtfeld leer: Platzhalter dezent anzeigen
              const placeholder = `[${(fieldDef?.label_de || fieldDef?.label || varName).toUpperCase()}]`;
              line = line.replace(new RegExp(`\\{\\{\\s*${varName}\\s*\\}\\}`, 'g'), placeholder);
            }
          } else {
            line = line.replace(new RegExp(`\\{\\{\\s*${varName}\\s*\\}\\}`, 'g'), val);
          }
        }
        if (!skipLine) {
          renderedLines.push(line);
        }
      }
      // Erweiterte Optionen einspeisen
      const advancedParts = [];
      // 1. Denk-Methodik
      const thinkingParts = [];
      if (document.getElementById("sp-opt-stepbystep")?.checked) {
        thinkingParts.push("- Schritt für Schritt: Durchdenken Sie das Problem systematisch in logischen Einzelschritten, bevor Sie das Endergebnis formulieren.");
      }
      if (document.getElementById("sp-opt-reasoning")?.checked) {
        thinkingParts.push("- Begründung & Herleitung: Erläutern Sie Ihre strategische Entscheidungslogik und Gedankengänge transparent.");
      }
      if (document.getElementById("sp-opt-perspectives")?.checked) {
        thinkingParts.push("- Multiperspektivität: Beleuchten Sie die Fragestellung aus mehreren relevanten Blickwinkeln und wägen Sie Gegenargumente ab.");
      }
      if (document.getElementById("sp-opt-systematic")?.checked) {
        thinkingParts.push("- Systematischer Ansatz: Wenden Sie ein klares, strukturiertes Analyse- und Handlungs-Framework an.");
      }
      if (document.getElementById("sp-opt-cot")?.checked) {
        thinkingParts.push("- Chain-of-Thought (Gedankenkette): Verknüpfen Sie alle Zwischenschritte nachvollziehbar miteinander.");
      }
      if (document.getElementById("sp-opt-roleplay")?.checked) {
        thinkingParts.push("- Vertieftes Rollenspiel: Agieren Sie strikt aus der spezifizierten Expertenperspektive mit profunder Fachsprache und Praxisexpertise.");
      }
      if (thinkingParts.length > 0) {
        advancedParts.push(`### DENK-METHODIK & STRATEGIE:\n${thinkingParts.join("\n")}`);
      }
      // 2. Ausgabe-Vorgaben & Kriterien
      const outputParts = [];
      if (document.getElementById("sp-opt-confidence")?.checked) {
        outputParts.push("- Konfidenz-Rating: Weisen Sie zentralen Empfehlungen und Thesen eine Zuverlässigkeitsbewertung (Hoch/Mittel/Niedrig) mit kurzer Begründung zu.");
      }
      if (document.getElementById("sp-opt-citations")?.checked) {
        outputParts.push("- Quellen & Belege: Untermauern Sie Fakten, Daten und Kernaussagen mit konkreten Referenzen und Nachweisen.");
      }
      const numExamples = parseInt(document.getElementById("sp-opt-examples-count")?.value || "0", 10);
      if (numExamples > 0) {
        outputParts.push(`- Praxisbeispiele: Integrieren Sie mindestens ${numExamples} konkrete, illustrative Anwendungsbeispiele.`);
      }
      if (outputParts.length > 0) {
        advancedParts.push(`### ERWEITERTE AUSGABE-VORGABEN:\n${outputParts.join("\n")}`);
      }
      // 3. Freitexte
      const contextVal = document.getElementById("sp-opt-context")?.value?.trim();
      if (contextVal) {
        advancedParts.push(`### ZUSÄTZLICHER KONTEXT & HINTERGRUND:\n${contextVal}`);
      }
      const examplesVal = document.getElementById("sp-opt-examples")?.value?.trim();
      if (examplesVal) {
        advancedParts.push(`### REFERENZ-BEISPIELE (GEWÜNSCHTER AUSGABESTIL):\n${examplesVal}`);
      }
      const successVal = document.getElementById("sp-opt-success")?.value?.trim();
      if (successVal) {
        advancedParts.push(`### ERFOLGSKRITERIEN (DEFINITION OF DONE):\n${successVal}`);
      }
      let assembled = renderedLines.join("\n").replace(/\n{3,}/g, "\n\n").trim();
      // Ergänzende Blöcke sammeln
      const appendBlocks = [];
      if (advancedParts.length > 0) {
        appendBlocks.push(advancedParts.join("\n\n"));
      }
      // 4. File-Upload Dokumenten-Kontext einspeisen (max. 25.000 Zeichen)
      if (surePromptsUploadedFiles.length > 0) {
        const fileBlocks = [];
        for (const file of surePromptsUploadedFiles) {
          const extName = (file.filename.split('.').pop() || 'txt').toLowerCase();
          fileBlocks.push(`### Datei: ${file.filename}\n\`\`\`${extName}\n${file.extracted_text}\n\`\`\``);
        }
        let docBlock = `# BEIGEFÜGTER DOKUMENTEN-KONTEXT & QUELLEN:\n${fileBlocks.join("\n\n")}`;
        if (docBlock.length > 25000) {
          docBlock = docBlock.slice(0, 24850) + "\n\n... [GEKÜRZT: MAXIMALES DOKUMENTEN-LIMIT VON 25.000 ZEICHEN ERREICHT] ...\n```";
        }
        appendBlocks.push(docBlock);
      }
      if (appendBlocks.length > 0) {
        const fullExtraBlock = appendBlocks.join("\n\n");
        if (assembled.includes("4. ARCHON OS GOVERNANCE & PHRASEN-VERBOT")) {
          assembled = assembled.replace(
            "4. ARCHON OS GOVERNANCE & PHRASEN-VERBOT",
            `${fullExtraBlock}\n\n4. ARCHON OS GOVERNANCE & PHRASEN-VERBOT`
          );
        } else {
          assembled += `\n\n${fullExtraBlock}`;
        }
      }
      return assembled.replace(/\n{3,}/g, "\n\n").trim();
    }
    function updateSurePromptLivePreview() {
      const previewEl = document.getElementById("sp-live-preview");
      if (!previewEl) return;
      previewEl.innerText = buildAssembledSurePrompt();
    }
    function applySelectedSurePrompt() {
      const promptText = buildAssembledSurePrompt();
      if (!promptText) return;
      let targetId = "master-chat-input";
      if (currentSurePromptsTarget === "agent-tab") {
        targetId = "agent-tab-chat-input";
      } else if (currentSurePromptsTarget === "agent") {
        targetId = "agent-chat-input";
      } else if (currentSurePromptsTarget === "ops-task") {
        targetId = "ops-task-body";
      }
      const textarea = document.getElementById(targetId);
      if (textarea) {
        const currentVal = textarea.value.trim();
        textarea.value = currentVal ? `${currentVal}\n\n${promptText}` : promptText;
        if (typeof autoResizeMasterChatInput === "function" && targetId === "master-chat-input") {
          autoResizeMasterChatInput(textarea);
        }
        textarea.focus();
        textarea.scrollIntoView({ behavior: "smooth", block: "nearest" });
        textarea.classList.add("ring-2", "ring-indigo-500");
        setTimeout(() => textarea.classList.remove("ring-2", "ring-indigo-500"), 1500);
      }
      if (currentSurePromptsTarget === "ops-task") {
        setTimeout(() => closeSurePromptsModal(), 350);
        return;
      }
      // Visuelles Feedback: Modal bleibt geöffnet!
      const btn = document.getElementById("sp-apply-btn");
      if (btn) {
        const origHtml = btn.innerHTML;
        btn.innerHTML = `<span>${psT('ui.prompt_studio.applied', '✓ Eingefügt')}</span><i data-lucide="check" class="w-3.5 h-3.5 text-white"></i>`;
        btn.classList.replace("bg-red-600", "bg-indigo-600");
        if (window.lucide) window.lucide.createIcons();
        setTimeout(() => {
          btn.innerHTML = origHtml;
          btn.classList.replace("bg-indigo-600", "bg-red-600");
          if (window.lucide) window.lucide.createIcons();
        }, 2200);
      }
    }
    function copyCurrentSurePromptToClipboard() {
      const text = buildAssembledSurePrompt();
      if (!text) return;
      navigator.clipboard.writeText(text).then(() => {
        const lbl = document.getElementById("sp-copy-label");
        if (lbl) {
          lbl.innerText = psT('ui.prompt_studio.copied', 'Kopiert!');
          setTimeout(() => { lbl.innerText = psT('ui.prompt_studio.copied_label', 'Kopieren'); }, 1800);
        }
      });
    }
    // =========================================================================
    // KI-PROMPT-OPTIMIZER (5-FELDER TRANSFORMER)
    // =========================================================================
    async function optimizeMasterChatPrompt(target = "master") {
      let textareaId = "master-chat-input";
      let btnId = "master-chat-optimize-btn";
      if (target === "agent-tab") {
        textareaId = "agent-tab-chat-input";
        btnId = "agent-tab-optimize-btn";
      } else if (target === "agent") {
        textareaId = "agent-chat-input";
        btnId = "agent-chat-optimize-btn";
      } else if (target === "ops-task") {
        textareaId = "ops-task-body";
        btnId = "ops-task-optimize-btn";
      }
      const textarea = document.getElementById(textareaId);
      const btn = document.getElementById(btnId);
      if (!textarea) return;
      const rawText = textarea.value.trim();
      if (!rawText) {
        alert(psT('ui.prompt_studio.err_optimizer_empty', 'Bitte gib zuerst einen Text oder Stichpunkte ein, die der KI-Optimizer in das standardisierte 5-Felder-Format transformieren soll.'));
        textarea.focus();
        return;
      }
      const originalBtnHtml = btn ? btn.innerHTML : "";
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<i data-lucide="loader" class="w-4 h-4 text-amber-500 animate-spin"></i>`;
        if (window.lucide) window.lucide.createIcons();
      }
      try {
        const res = await fetch("/api/prompts/optimize", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ prompt: rawText })
        });
        if (res.ok) {
          const data = await res.json();
          if (data.optimized_prompt) {
            textarea.value = data.optimized_prompt;
            if (typeof autoResizeMasterChatInput === "function") autoResizeMasterChatInput(textarea);
            textarea.classList.add("ring-2", "ring-amber-500");
            setTimeout(() => textarea.classList.remove("ring-2", "ring-amber-500"), 1500);
          }
        } else {
          alert(psT('ui.prompt_studio.err_optimizer_failed', 'KI-Optimizer konnte die Anfrage nicht verarbeiten. Bitte Modellverbindung prüfen.'));
        }
      } catch (err) {
        console.error("[Optimizer] Fehler:", err);
        alert(psT('ui.prompt_studio.err_optimizer_conn', 'Verbindungsfehler zum KI-Optimizer.'));
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = originalBtnHtml;
          if (window.lucide) window.lucide.createIcons();
        }
      }
    }
    window.optimizePromptWithAI = optimizeMasterChatPrompt;
    // 11. Auto-Resize für Textarea (wächst bis max 30% der Bildschirmhöhe) & Keydown
    function autoResizeMasterChatInput(el) {
      if (!el) return;
      el.style.height = "auto";
      const maxH = Math.floor(window.innerHeight * 0.30);
      el.style.height = Math.min(el.scrollHeight, maxH) + "px";
    }
    function handleMasterChatInputKey(e) {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMasterChatMessage();
      } else if (e.key === "ArrowUp" && !e.target.value.trim()) {
        e.preventDefault();
        if (window.lastSentUserChatMessage) {
          e.target.value = window.lastSentUserChatMessage;
          if (typeof autoResizeMasterChatInput === "function") autoResizeMasterChatInput(e.target);
        }
      }
    }
    // 12. Senden & SSE Streaming Consumer (/api/chat/stream)
    async function sendMasterChatMessage() {
      if (isMasterChatGenerating) return;
      const inputEl = document.getElementById("master-chat-input");
      if (!inputEl) return;
      const text = inputEl.value.trim();
      const hasAttachments = (typeof currentMasterChatAttachments !== 'undefined' && currentMasterChatAttachments.length > 0);
      if (!text && !hasAttachments) return;
      // Falls Diktat noch läuft, stoppen
      if (isMasterChatDictating) {
        toggleMasterChatDictation();
      }
      inputEl.value = "";
      autoResizeMasterChatInput(inputEl);
      if (!currentMasterChatSessionId) {
        createNewMasterChatSession();
      }
      // Datei-Upload im Hintergrund ausführen (bis zu 5 Anhänge)
      let attachmentNotice = "";
      if (hasAttachments) {
        const indicator = document.getElementById("master-chat-upload-indicator");
        if (indicator) indicator.textContent = psT('ui.prompt_studio.upload_progress', '⏳ Lade {count} Datei(en) hoch...', { count: currentMasterChatAttachments.length });
        try {
          for (const att of currentMasterChatAttachments) {
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
          if (indicator) {
            indicator.textContent = psT('ui.prompt_studio.upload_done', '✓ {count} Datei(en) bereitgestellt', { count: currentMasterChatAttachments.length });
            setTimeout(() => { if (indicator) indicator.textContent = ""; }, 4000);
          }
        } catch (err) {
          console.warn("[MasterChat Upload] Fehler:", err);
        }
        removeMasterChatAttachment();
      }
      const fullUserMessage = (text + attachmentNotice).trim();
      window.lastSentUserChatMessage = fullUserMessage;
      // User Message sofort anzeigen
      appendMasterChatMessageBubble("user", fullUserMessage);
      // Status aktualisieren
      const statusSpan = document.getElementById("master-chat-status");
      const sendBtn = document.getElementById("master-chat-send-btn");
      if (statusSpan) {
        statusSpan.innerHTML = currentMasterChatMode === "mission" 
          ? `<span class="text-[var(--foreground)] font-semibold animate-pulse">${psT('ui.prompt_studio.status_mission_creating', '● Erstelle Operations Mission...')}</span>`
          : `<span class="text-[var(--foreground)] font-semibold animate-pulse">${psT('ui.prompt_studio.status_agent_answering', '● Agent antwortet...')}</span>`;
      }
      if (sendBtn) sendBtn.disabled = true;
      isMasterChatGenerating = true;
      // Platzhalter für Assistant-Antwort erstellen
      const messagesContainer = document.getElementById("master-chat-messages");
      const assistantBubble = document.createElement("div");
      assistantBubble.className = "flex justify-start";
      
      const prof = masterChatProfiles.find(p => p.id === currentMasterChatProfileId);
      const name = prof ? (prof.person_name || prof.name) : "Hermes";
      const initials = name.substring(0, 2).toUpperCase();
      const avatarUrl = (typeof getProfileAvatarUrl === "function" && prof) ? getProfileAvatarUrl(prof) : (prof && prof.avatar ? prof.avatar : "/static/avatars/hermes_default_avatar.png");
      const liveDateFormatted = new Date().toLocaleDateString(psLocale(), { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
      const liveMsgId = `#msg-${Math.floor(1000 + Math.random() * 9000)}`;
      assistantBubble.innerHTML = `
        <div class="flex gap-3 max-w-3xl">
          <div onclick="jumpToAgentProfile('${prof ? prof.id : currentMasterChatProfileId}')" class="w-12 h-12 rounded-xl border border-[var(--border)] bg-[var(--secondary)] text-[var(--foreground)] flex items-center justify-center font-mono text-sm font-bold shrink-0 shadow-xs mt-0.5 overflow-hidden cursor-pointer hover:border-zinc-950 dark:hover:border-zinc-50 transition duration-150 group" title="${psT('ui.prompt_studio.open_profile_title', 'Profil &amp; Einstellungen im Agenten-Kader öffnen')}">
            <img src="${avatarUrl}" class="w-full h-full object-cover group-hover:opacity-90 transition" onerror="this.outerHTML='${initials}'">
          </div>
          <div class="bg-[var(--card)] border border-[var(--border)] rounded-xl rounded-tl-xs px-4 py-3 text-xs text-[var(--foreground)] space-y-2 shadow-xs leading-relaxed min-w-[260px]">
            <div class="flex items-center justify-between gap-2 mb-1 pb-1 border-b border-[var(--border)]">
              <span class="font-bold text-[var(--foreground)] text-xs font-mono">${escapeHtml(name)}</span>
              <div class="flex items-center gap-1.5">
                <button type="button" class="copy-bubble-btn text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition p-1 rounded cursor-pointer" title="In Zwischenablage kopieren" onclick="copyAgentMessageText(this)" data-text="">
                  <i data-lucide="copy" class="w-3.5 h-3.5 text-black dark:text-white"></i>
                </button>
                <button class="speaker-btn text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition p-1 rounded cursor-pointer" title="${psT('ui.prompt_studio.speak', 'Vorlesen')}" onclick="speakText(this.getAttribute('data-text'))" data-text="">
                  <i data-lucide="volume-2" class="w-3.5 h-3.5 text-black dark:text-white"></i>
                </button>
              </div>
            </div>
            <div class="chat-assistant-body font-sans leading-relaxed text-[var(--foreground)]">
              <span class="text-[var(--muted-foreground)] italic animate-pulse">${psT('ui.prompt_studio.answering', 'Antwort wird generiert...')}</span>
            </div>
            <div class="bubble-action-card"></div>
            <div class="pt-2 border-t border-[var(--border)] flex items-center justify-between text-[9.5px] font-mono text-[var(--muted-foreground)]">
              <span class="flex items-center gap-1"><i data-lucide="clock" class="w-3 h-3 text-black dark:text-white"></i>${liveDateFormatted}</span>
              <span class="font-mono font-medium text-[var(--muted-foreground)]">${liveMsgId}</span>
            </div>
          </div>
        </div>
      `;
      messagesContainer.appendChild(assistantBubble);
      messagesContainer.scrollTop = messagesContainer.scrollHeight;
      if (window.lucide && typeof lucide.createIcons === "function") lucide.createIcons();
      const bodyEl = assistantBubble.querySelector(".chat-assistant-body");
      const speakerBtn = assistantBubble.querySelector(".speaker-btn");
      const actionCardContainer = assistantBubble.querySelector(".bubble-action-card");
      let fullText = "";
      try {
        const payload = {
          agent_id: currentMasterChatProfileId,
          message: fullUserMessage,
          session_id: currentMasterChatSessionId,
          mode: currentMasterChatMode,
          provider: currentMasterChatProvider || "openrouter",
          model: currentMasterChatModel,
          reasoning_level: window.currentMasterChatReasoning || "high"
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
                messagesContainer.scrollTop = messagesContainer.scrollHeight;
              } else if (eventData.type === "mission_created") {
                fullText = eventData.content || psT('ui.prompt_studio.mission_created', 'Mission angelegt.');
                if (bodyEl) {
                  bodyEl.innerHTML = typeof formatMarkdownText === "function" ? formatMarkdownText(fullText) : escapeHtml(fullText);
                }
                if (actionCardContainer) {
                  actionCardContainer.innerHTML = `
                    <div class="mt-3 p-3 bg-[var(--secondary)] border border-[var(--border)] rounded-lg flex items-center justify-between gap-3 text-[var(--foreground)] shadow-xs">
                      <div class="text-xs font-sans font-medium flex items-center gap-1.5">
                        <i data-lucide="shield-alert" class="w-4 h-4 text-black dark:text-white"></i>
                        <span>${psT('ui.prompt_studio.mission_approval_hint', 'Diese Mission wartet im Approval Gate auf Freigabe.')}</span>
                      </div>
                      <button onclick="setTab('mission-control')" class="shadcn-btn-primary px-3 py-1 text-xs font-semibold rounded-md flex items-center gap-1.5 cursor-pointer shadow-xs transition shrink-0">
                        <i data-lucide="shield" class="w-3.5 h-3.5"></i>
                        <span>${psT('ui.prompt_studio.to_approval', 'Zur Freigabe')}</span>
                      </button>
                    </div>
                  `;
                }
                messagesContainer.scrollTop = messagesContainer.scrollHeight;
              } else if (eventData.type === "error") {
                fullText += `\n${psT('ui.prompt_studio.error_label', '❌ Fehler: {message}', { message: eventData.error })}`;
                if (bodyEl) {
                  bodyEl.innerHTML = `<span class="text-rose-600 font-semibold">${escapeHtml(fullText)}</span>`;
                }
              }
            } catch (jsonErr) {
              console.warn("[MasterChat SSE] Ungültiges Event:", trimmed, jsonErr);
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
        // Sessions neu laden, um Titel & Msg-Count in Sidebar zu aktualisieren
        loadMasterChatSessions();
      } catch (err) {
        if (bodyEl) {
          bodyEl.innerHTML = `<span class="text-rose-600 font-semibold">${psT('ui.prompt_studio.conn_error', 'Verbindungsfehler: {message}', { message: escapeHtml(err.message) })}</span>`;
        }
      } finally {
        isMasterChatGenerating = false;
        if (statusSpan) statusSpan.textContent = psT('ui.prompt_studio.status_ready', 'Bereit');
        if (sendBtn) sendBtn.disabled = false;
        if (window.lucide && typeof lucide.createIcons === "function") lucide.createIcons();
        if (inputEl) inputEl.focus();
      }
    }
    // 13. Backward-Compatible Shims
    function getMasterChatAgentList() {
      return masterChatProfiles.map(p => ({
        id: p.id,
        name: p.person_name ? `${p.person_name} (${p.name})` : p.name,
        role: p.role || "Specialist",
        model: p.model || "auto/best-coding",
        status: "online",
        active: true,
        type: "native"
      }));
    }
    function renderMasterChatAgentTabs() {
      initMasterChat();
    }
    async function switchMasterChatAgent(agentId, targetSessionId = null) {
      if (!agentId) return;
      await initMasterChat();
      
      // Zielprofil-ID robust ermitteln (unterstützt id, person_name, name)
      let resolvedId = agentId;
      const targetLower = String(agentId).toLowerCase().trim();
      const matchedProfile = (masterChatProfiles || []).find(p => 
        (p.id && p.id.toLowerCase() === targetLower) ||
        (p.person_name && p.person_name.toLowerCase() === targetLower) ||
        (p.name && p.name.toLowerCase() === targetLower)
      );
      if (matchedProfile) {
        resolvedId = matchedProfile.id;
      } else if (typeof hermesProfilesData !== "undefined" && Array.isArray(hermesProfilesData)) {
        const hp = hermesProfilesData.find(p => 
          (p.id && p.id.toLowerCase() === targetLower) ||
          (p.person_name && p.person_name.toLowerCase() === targetLower) ||
          (p.name && p.name.toLowerCase() === targetLower)
        );
        if (hp) resolvedId = hp.id;
      }

      await onMasterChatProfileChanged(resolvedId, targetSessionId);
      const sel = document.getElementById("master-chat-profile-select");
      if (sel) sel.value = resolvedId;
    }
    window.switchMasterChatAgent = switchMasterChatAgent;
    window.selectMasterChatProfile = switchMasterChatAgent;
    let currentSelectedAgentId = "";
    const agentTerminalLogs = {};
    function openTerminalForAgent(agentId, event) {
      if (event) event.stopPropagation();
      const agent = agents.find(a => a.id === agentId);
      if (!agent) return;
      
      currentSelectedAgentId = agent.id;
      if (!agentTerminalLogs[agent.id]) {
        agentTerminalLogs[agent.id] = [
          `<div class="text-neutral-500">${psT('ui.prompt_studio.terminal_init', '// Terminal Konsole für {name} ({id}) initialisiert. Bereit für Eingaben...', { name: agent.name, id: agent.id })}</div>`
        ];
      }
      const consoleOut = document.getElementById("agent-terminal-console-output");
      if (consoleOut) {
        consoleOut.innerHTML = agentTerminalLogs[agent.id].join("");
        consoleOut.scrollTop = consoleOut.scrollHeight;
      }
      // Docker-Container auf Host-System via API automatisch starten!
      fetch("/api/docker/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ container_name: agent.container_name || agent.id, id: agent.id })
      }).catch(e => console.error("Error starting docker container:", e));
      // 1. Haupt-Navigations-Items ent-markieren
      const navIds = ["nav-mission-control", "nav-paperclip", "nav-ai-mastermind", "nav-kanban", "nav-workspace-gallery"];
      navIds.forEach(id => {
        const btn = document.getElementById(id);
        if (btn) {
          btn.style.backgroundColor = "transparent";
          btn.style.borderColor = "transparent";
          btn.style.color = "var(--item-text)";
          const arrow = btn.querySelector('.active-arrow');
          if (arrow) arrow.classList.add("hidden");
        }
      });
      // 2. Alle Views ausnahmslos ausblenden
      const allViews = [
        "view-mission-control",
        "view-master-chat",
        "view-hermes-dashboard",
        "view-paperclip",
        "view-automation",
        "view-prime-agent",
        "view-ai-mastermind",
        "view-kanban",
        "view-workspace-gallery"
      ];
      allViews.forEach(id => {
        const el = document.getElementById(id);
        if (el) {
          el.classList.add("hidden");
          el.style.display = "none";
        }
      });
      const statsDash = document.getElementById("stats-dashboard");
      if (statsDash) {
        statsDash.classList.add("hidden");
        statsDash.style.display = "none";
      }
      // 3. Dedizierte Agenten-Terminal View einblenden
      const termView = document.getElementById("view-agent-terminal");
      if (termView) {
        termView.classList.remove("hidden");
        termView.style.display = "flex";
      }
      // Topbar Titel & Status anpassen
      document.getElementById("topbar-title").innerText = psT('ui.prompt_studio.topbar_agent', 'Agent');
      document.getElementById("topbar-icon").innerHTML = `<i data-lucide="bot" class="w-4 h-4 text-accent-color"></i>`;
      const statusSpan = document.getElementById("topbar-status");
      if (statusSpan) statusSpan.classList.add("hidden");
      // Header Details im Terminal
      const titleEl = document.getElementById("agent-terminal-title");
      if (titleEl) titleEl.innerText = agent.name;
      const subEl = document.getElementById("agent-terminal-subtitle");
      const displayModel = (agent.model && !agent.model.includes('/')) ? agent.model : "free-forever";
      const displayRole = (agent.role && !agent.role.includes('tcp')) ? agent.role : "Orchestrator";
      if (subEl) {
        subEl.innerText = psT('ui.prompt_studio.terminal_subtitle', 'ID: {id} | Modell: {model} | Rolle: {role}', { id: agent.id, model: displayModel, role: displayRole });
      }
      // Update active role display in logs tab
      const logsRoleEl = document.getElementById("agent-logs-active-role");
      if (logsRoleEl) logsRoleEl.innerText = displayRole;
      // Auto-inject configuration to container on select
      injectContainerConfig(agent.id, displayModel, agent.prompt || "");
      const infoEl = document.getElementById("agent-terminal-docker-info");
      if (infoEl) {
        const activeHtml = agent.active 
          ? `<span class="bg-green-500/10 border border-green-500/20 px-2 py-0.5 rounded text-green-500 font-bold tracking-wider">${psT('ui.prompt_studio.badge_active', 'AKTIV')}</span>`
          : `<span class="bg-yellow-500/10 border border-yellow-500/20 px-2 py-0.5 rounded text-yellow-500 font-bold tracking-wider">${psT('ui.prompt_studio.badge_idle', 'IDLE')}</span>`;
        
        const port = detectContainerPort(agent);
        const containerUrl = agent.url || `http://localhost:${port}`;
        infoEl.innerHTML = `
          <div class="flex flex-col items-end gap-1.5 font-mono text-[10px]">
            <!-- Zeile 1: Container-Name + Web UI Button -->
            <div class="flex items-center gap-2">
              <span class="bg-neutral-900/10 border theme-border px-2 py-0.5 rounded text-secondary-custom font-bold">${agent.id}-container</span>
              <a href="${containerUrl}" target="_blank" rel="noopener noreferrer" class="bg-indigo-500/10 hover:bg-indigo-500/20 border border-indigo-500/30 px-2 py-0.5 rounded text-indigo-400 font-bold flex items-center gap-1 transition-colors" title="${psT('ui.prompt_studio.webui_title', 'Eigenes Web UI im neuen Tab öffnen')}">
                <i data-lucide="external-link" class="w-3 h-3"></i> Web UI ↗
              </a>
            </div>
            <!-- Zeile 2: Port + Status Badge -->
            <div class="flex items-center gap-2">
              <span class="bg-neutral-900/10 border theme-border px-2 py-0.5 rounded text-secondary-custom flex items-center gap-1">
                <i data-lucide="split" class="w-3 h-3 text-muted-custom"></i> :${port}
              </span>
              ${activeHtml}
            </div>
          </div>
        `;
        lucide.createIcons();
      }
      // Prompt platzhalter & Fokus
      const promptEl = document.getElementById("agent-terminal-prompt");
      if (promptEl) {
        promptEl.placeholder = psT('ui.prompt_studio.terminal_prompt', 'Befehl an {name} senden...', { name: agent.name });
        promptEl.focus();
      }
      
      // Initialize subtab to default
      setAgentSubTab('term');
    }
    let currentAgentSubTab = "term";
    function setAgentSubTab(tabName) {
      currentAgentSubTab = tabName;
      
      const tabIds = ["term", "web", "dash", "art", "logs", "sets"];
      tabIds.forEach(id => {
        const btn = document.getElementById(`agent-tab-btn-${id}`);
        const view = document.getElementById(`agent-subview-${id}`);
        
        if (btn) {
          if (id === tabName) {
            btn.classList.add("border-accent-color", "text-primary-custom");
            btn.classList.remove("border-transparent", "text-muted-custom");
          } else {
            btn.classList.remove("border-accent-color", "text-primary-custom");
            btn.classList.add("border-transparent", "text-muted-custom");
          }
        }
        if (view) {
          if (id === tabName) {
            view.classList.remove("hidden");
          } else {
            view.classList.add("hidden");
          }
        }
      });
      // Tab specific load actions
      if (tabName === "web") {
        loadAgentWebUI();
      } else if (tabName === "art") {
        refreshAgentArtifactsList();
      } else if (tabName === "logs") {
        refreshAgentLogs();
        refreshAgentMetrics();
        const agent = agents.find(a => a.id === currentSelectedAgentId);
        if (agent) {
          const displayRole = (agent.role && !agent.role.includes('tcp')) ? agent.role : "Orchestrator";
          const logsRoleEl = document.getElementById("agent-logs-active-role");
          if (logsRoleEl) logsRoleEl.innerText = displayRole;
        }
      } else if (tabName === "sets") {
        loadAgentSettingsForForm();
      }
    }
    async function loadAgentWebUI() {
      const agent = agents.find(a => a.id === currentSelectedAgentId);
      if (!agent) return;
      
      let url = "";
      try {
        const res = await fetch(`/api/v1/container/settings?container_name=${agent.id}`);
        if (res.ok) {
          const config = await res.json();
          url = config.web_ui_url;
        }
      } catch(e) {
        console.error("Failed to load settings:", e);
      }
      
      if (!url) {
        const port = detectContainerPort(agent);
        url = agent.url || `http://localhost:${port}`;
      }
      
      document.getElementById("agent-web-url-text").innerText = `Adresse: ${url}`;
      document.getElementById("agent-web-link-open").href = url;
      const iframe = document.getElementById("agent-web-iframe");
      if (iframe) {
        iframe.removeAttribute("sandbox");
        iframe.src = url;
      }
    }
    async function refreshAgentArtifactsList() {
      const select = document.getElementById("agent-artifact-select");
      if (!select) return;
      select.innerHTML = `<option disabled>${psT('ui.prompt_studio.files_loading', 'Lade Dateien...')}</option>`;
      
      const agent = agents.find(a => a.id === currentSelectedAgentId);
      if (!agent) return;
      
      try {
        const res = await fetch(`/api/v1/container/files?container_name=${agent.id}`);
        const data = await res.json();
        select.innerHTML = "";
        
        if (data.files && data.files.length > 0) {
          data.files.forEach(f => {
            const opt = document.createElement("option");
            opt.value = f;
            opt.innerText = f;
            select.appendChild(opt);
          });
        } else {
          select.innerHTML = `<option disabled>${psT('ui.prompt_studio.files_none', 'Keine Dateien gefunden (oder gestoppt)')}</option>`;
        }
      } catch (err) {
        select.innerHTML = `<option disabled>${psT('ui.prompt_studio.load_failed_short', 'Fehler beim Laden')}</option>`;
      }
    }
    async function loadAgentArtifactContent(filepath) {
      const previewBox = document.getElementById("agent-artifact-preview-box");
      const namePreview = document.getElementById("agent-artifact-name-preview");
      const typeBadge = document.getElementById("agent-artifact-type-badge");
      const dlBtn = document.getElementById("agent-artifact-download-btn");
      
      if (!previewBox || !currentSelectedAgentId) return;
      
      previewBox.innerText = psT('ui.prompt_studio.content_loading', 'Lade Dateiinhalt...');
      namePreview.innerText = filepath;
      
      try {
        const res = await fetch(`/api/v1/container/file/content?container_name=${currentSelectedAgentId}&filepath=${encodeURIComponent(filepath)}`);
        if (!res.ok) {
          previewBox.innerText = psT('ui.prompt_studio.file_read_failed', 'Fehler beim Lesen der Datei.');
          return;
        }
        const data = await res.json();
        
        // Setup download button
        dlBtn.classList.remove("pointer-events-none", "opacity-50");
        
        const fileExt = filepath.split('.').pop().toLowerCase();
        typeBadge.innerText = fileExt;
        
        if (data.binary) {
          const mimeMap = {
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "gif": "image/gif",
            "webp": "image/webp",
            "pdf": "application/pdf"
          };
          const mime = mimeMap[fileExt] || "application/octet-stream";
          dlBtn.href = `data:${mime};base64,${data.content}`;
          
          if (["png", "jpg", "jpeg", "webp", "gif"].includes(fileExt)) {
            previewBox.innerHTML = `<img src="data:${mime};base64,${data.content}" class="max-w-full h-auto object-contain mx-auto" />`;
          } else {
            previewBox.innerText = psT('ui.prompt_studio.binary_preview_unavailable', 'Vorschau für diesen Binärdateityp nicht möglich. Nutzen Sie den Download-Button.');
          }
        } else {
          dlBtn.href = `data:text/plain;charset=utf-8,${encodeURIComponent(data.content)}`;
          
          if (fileExt === "md") {
            previewBox.innerHTML = `<div class="prose prose-sm dark:prose-invert max-w-none">${data.content.replace(/\n/g, '<br/>')}</div>`;
          } else if (fileExt === "csv") {
            const rows = data.content.split('\n').filter(r => r.trim()).map(row => row.split(','));
            let html = '<table class="w-full text-left border-collapse text-[10px]">';
            rows.forEach((row, rowIndex) => {
              html += `<tr class="${rowIndex === 0 ? 'bg-neutral-900/20 font-bold border-b theme-border' : 'border-b theme-border/45'}">`;
              row.forEach(cell => {
                html += `<td class="px-2 py-1 border-r theme-border/30 last:border-none">${cell.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")}</td>`;
              });
              html += '</tr>';
            });
            html += '</table>';
            previewBox.innerHTML = html;
          } else {
            const escaped = data.content.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
            previewBox.innerHTML = `<pre class="whitespace-pre overflow-auto">${escaped}</pre>`;
          }
        }
      } catch (err) {
        previewBox.innerText = psT('ui.prompt_studio.load_error', 'Fehler beim Laden: {message}', { message: err.message });
      }
    }
    async function refreshAgentLogs() {
      const logsPre = document.getElementById("agent-logs-output");
      if (!logsPre || !currentSelectedAgentId) return;
      
      logsPre.innerText = psT('ui.prompt_studio.logs_loading', 'Lade Logs...');
      try {
        const res = await fetch(`/api/v1/container/logs?container_name=${currentSelectedAgentId}`);
        const data = await res.json();
        logsPre.innerText = data.logs || psT('ui.prompt_studio.logs_none', 'Keine Logs vorhanden.');
        logsPre.scrollTop = logsPre.scrollHeight;
      } catch (e) {
        logsPre.innerText = psT('ui.prompt_studio.fetch_error', 'Fehler beim Abrufen: {message}', { message: e.message });
      }
    }
    async function refreshAgentMetrics() {
      const statusP = document.getElementById("agent-metric-status");
      const cpuP = document.getElementById("agent-metric-cpu");
      const ramP = document.getElementById("agent-metric-ram");
      
      if (!statusP || !currentSelectedAgentId) return;
      
      try {
        const res = await fetch(`/api/v1/container/metrics?container_name=${currentSelectedAgentId}`);
        const data = await res.json();
        
        statusP.innerText = data.status || "-";
        cpuP.innerText = `${(data.cpu || 0).toFixed(1)} %`;
        ramP.innerText = `${(data.memory_mb || 0).toFixed(1)} MB (${(data.memory_pct || 0).toFixed(1)} %)`;
      } catch (e) {
        console.error("Failed to fetch metrics:", e);
      }
    }
    async function loadAgentSettingsForForm() {
      const weburlInput = document.getElementById("agent-set-weburl");
      const modelSelect = document.getElementById("agent-set-model");
      const promptTextarea = document.getElementById("agent-set-prompt");
      
      const agent = agents.find(a => a.id === currentSelectedAgentId);
      if (!agent) return;
      
      const port = detectContainerPort(agent);
      weburlInput.value = agent.url || `http://localhost:${port}`;
      modelSelect.value = agent.model || "free-forever";
      promptTextarea.value = agent.prompt || "";
      
      try {
        const res = await fetch(`/api/v1/container/settings?container_name=${agent.id}`);
        if (res.ok) {
          const config = await res.json();
          if (config.web_ui_url) weburlInput.value = config.web_ui_url;
          if (config.model) modelSelect.value = config.model;
          if (config.prompt) promptTextarea.value = config.prompt;
        }
      } catch(e) {
        console.error("Failed to load settings:", e);
      }
    }
    async function saveAgentSettings() {
      const weburlVal = document.getElementById("agent-set-weburl").value.trim();
      const modelVal = document.getElementById("agent-set-model").value;
      const promptVal = document.getElementById("agent-set-prompt").value.trim();
      
      if (!currentSelectedAgentId) return;
      
      try {
        const payload = {
          web_ui_url: weburlVal,
          model: modelVal,
          prompt: promptVal
        };
        const res = await fetch(`/api/v1/container/settings?container_name=${currentSelectedAgentId}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        
        if (res.ok) {
          alert(psT('ui.prompt_studio.settings_saved', 'Einstellungen erfolgreich gespeichert!'));
          const agent = agents.find(a => a.id === currentSelectedAgentId);
          if (agent) {
            agent.url = weburlVal;
            agent.model = modelVal;
            agent.prompt = promptVal;
          }
          loadAgentSettingsForForm();
          
          // Re-inject updated config immediately
          injectContainerConfig(currentSelectedAgentId, modelVal, promptVal);
        } else {
          alert(psT('ui.prompt_studio.settings_save_failed', 'Fehler beim Speichern der Einstellungen.'));
        }
      } catch (err) {
        alert(psT('ui.prompt_studio.error_only', 'Fehler: {message}', { message: err.message }));
      }
    }
    async function injectContainerConfig(containerId, model, prompt) {
      try {
        const res = await fetch(`/api/v1/container/inject_config?container_name=${containerId}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ model: model, system_prompt: prompt })
        });
        const data = await res.json();
        console.log(`Config injection for ${containerId}:`, data);
      } catch (e) {
        console.error(`Failed to inject config to ${containerId}:`, e);
      }
    }
    async function controlContainerAction(action) {
      if (!currentSelectedAgentId) return;
      
      try {
        const res = await fetch("/api/v1/container/action", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ container_name: currentSelectedAgentId, action: action })
        });
        const data = await res.json();
        if (data.status === "success") {
          alert(psT('ui.prompt_studio.action_ok', "Aktion '{action}' erfolgreich übermittelt!", { action: action }));
          setTimeout(() => {
            fetchServices();
            if (currentAgentSubTab === "logs") {
              refreshAgentLogs();
              refreshAgentMetrics();
            }
          }, 2000);
        } else {
          alert(psT('ui.prompt_studio.action_failed', 'Fehler bei Containeraktion: {message}', { message: data.message }));
        }
      } catch (err) {
        alert(psT('ui.prompt_studio.conn_error', 'Verbindungsfehler: {message}', { message: err.message }));
      }
    }
    function handleAgentTerminalKey(e) {
      if (e.key === "Enter") {
        runAgentTerminalCommand();
      }
    }
    async function runAgentTerminalCommand() {
      const input = document.getElementById("agent-terminal-prompt");
      if (!input) return;
      let val = input.value.trim();
      if (!val) return;
      input.value = "";
      const agent = agents.find(a => a.id === currentSelectedAgentId) || agents[0];
      if (!agent) return;
      const consoleOut = document.getElementById("agent-terminal-console-output");
      const ts = new Date().toLocaleTimeString();
      function escapeHtml(str) {
        if (!str) return '';
        return String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
      }
      if (!agentTerminalLogs[agent.id]) {
        agentTerminalLogs[agent.id] = [];
      }
      const userEntry = `<div class="mt-3 text-white font-bold">&gt; USER @${agent.name}: ${escapeHtml(val)}</div>`;
      agentTerminalLogs[agent.id].push(userEntry);
      if (consoleOut) {
        consoleOut.innerHTML = agentTerminalLogs[agent.id].join("") + `
          <div class="text-xs text-slate-400 font-mono flex items-center gap-2 mt-1" id="agent-terminal-pending-${agent.id}">
            <div class="animate-spin rounded-full h-3 w-3 border-b-2 border-green-400"></div>
            <span>${psT('ui.prompt_studio.exec_pending', "[{time}] Verarbeite Anweisung mit Rolle '{role}'...", { time: ts, role: agent.role || 'Orchestrator' })}</span>
          </div>
        `;
        consoleOut.scrollTop = consoleOut.scrollHeight;
      }
      try {
        const res = await fetch(`/api/v1/container/exec?container_name=${agent.id}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ container_name: agent.id, command: val })
        });
        const results = await res.json();
        let responseText = "";
        let stdout = (results.stdout || "").trim();
        if (stdout && !stdout.includes("not found")) {
          responseText = `<div class="mt-2 text-green-300 whitespace-pre-wrap font-mono">${escapeHtml(stdout)}</div>`;
        } else {
          const agentRole = agent.role || "Orchestrator & System-Architekt";
          const agentModel = agent.model || "free-forever";
          responseText = `<div class="mt-2 text-green-400 whitespace-pre-wrap font-mono">${psT('ui.prompt_studio.exec_local', "[{name} - {model}]: Verarbeite Anweisung mit Rolle '{role}'...\nStatus: Anweisung erfolgreich verarbeitet.", { name: agent.name, model: agentModel, role: agentRole })}</div>`;
        }
        agentTerminalLogs[agent.id].push(responseText);
        if (consoleOut && currentSelectedAgentId === agent.id) {
          consoleOut.innerHTML = agentTerminalLogs[agent.id].join("");
          consoleOut.scrollTop = consoleOut.scrollHeight;
        }
      } catch (err) {
        const errEntry = `<div class="mt-2 text-red-400 whitespace-pre-wrap font-mono">${psT('ui.prompt_studio.error_only', 'Fehler: {message}', { message: escapeHtml(err.message) })}</div>`;
        agentTerminalLogs[agent.id].push(errEntry);
        if (consoleOut && currentSelectedAgentId === agent.id) {
          consoleOut.innerHTML = agentTerminalLogs[agent.id].join("");
          consoleOut.scrollTop = consoleOut.scrollHeight;
        }
      }
    }
    async function unloadAgent(id) {
      if (!confirm(psT('ui.prompt_studio.confirm_unload', 'Soll der Agent-Docker-Container gestoppt (Unload) werden?'))) return;
      
      // Logisch aus dem Stack entfernen oder inaktiveren
      agents = agents.filter(a => a.id !== id);
      await saveAgentsToServer();
      renderAgentsSidebar();
      renderAgentRegistryTable();
      renderSidebarPresetsSelect();
    }
    function handleAgentRoleChange(agentId, value) {
      if (value === "manage_roles") {
        openRoleManagerModal();
        renderAgentsSidebar(); // Render zurücksetzen
        return;
      }
      
      const agent = agents.find(a => a.id === agentId);
      const role = roles.find(r => r.id === value);
      if (agent && role) {
        agent.role = role.name;
        agent.prompt = role.prompt;
        saveAgentsToServer();
        
        // Inject updated model/prompt config to container immediately
        const displayModel = (agent.model && !agent.model.includes('/')) ? agent.model : "free-forever";
        injectContainerConfig(agent.id, displayModel, role.prompt);
      }
    }
    function openEditPresetModalForAgent(agentId) {
      selectedPresetId = agentId;
      openEditPresetModal();
    }
    // --- ROLE MANAGER MODAL LOGIC ---
    let currentEditingRoleId = "";
    function openRoleManagerModal() {
      populateRoleManagerDropdown();
      if (roles.length > 0) {
        loadRoleIntoEditor(roles[0].id);
      } else {
        clearRoleEditorFields();
      }
      document.getElementById("role-manager-modal").classList.remove("hidden");
    }
    function closeRoleManagerModal() {
      document.getElementById("role-manager-modal").classList.add("hidden");
    }
    function populateRoleManagerDropdown() {
      const select = document.getElementById("role-manager-select");
      if (!select) return;
      select.innerHTML = "";
      
      roles.forEach(role => {
        const opt = document.createElement("option");
        opt.value = role.id;
        opt.innerText = role.name;
        if (role.id === currentEditingRoleId) {
          opt.selected = true;
        }
        select.appendChild(opt);
      });
    }
    function loadRoleIntoEditor(roleId) {
      currentEditingRoleId = roleId;
      const role = roles.find(r => r.id === roleId);
      if (role) {
        document.getElementById("role-manager-name").value = role.name;
        document.getElementById("role-manager-prompt").value = role.prompt;
      }
      const select = document.getElementById("role-manager-select");
      if (select) select.value = roleId;
    }
    function clearRoleEditorFields() {
      document.getElementById("role-manager-name").value = "";
      document.getElementById("role-manager-prompt").value = "";
    }
    async function saveRoleManagerChanges() {
      const name = document.getElementById("role-manager-name").value.trim();
      const prompt = document.getElementById("role-manager-prompt").value.trim();
      
      if (!name) {
        alert(psT('ui.prompt_studio.role_name_required', 'Bitte einen Rollennamen eingeben.'));
        return;
      }
      
      let role = roles.find(r => r.id === currentEditingRoleId);
      if (!role || currentEditingRoleId === "new") {
        const newId = `R-0${roles.length + 1}`;
        role = { id: newId, name, prompt };
        roles.push(role);
        currentEditingRoleId = newId;
      } else {
        role.name = name;
        role.prompt = prompt;
      }
      
      // Update prompts in agents that use this role!
      agents.forEach(agent => {
        if (agent.role === role.name || agent.role === role.id) {
          agent.prompt = prompt;
        }
      });
      
      await saveRolesToServer();
      await saveAgentsToServer();
      await loadAgentsFromServer();
      populateRoleManagerDropdown();
      loadRoleIntoEditor(currentEditingRoleId);
      alert(psT('ui.prompt_studio.role_saved', 'Rolle erfolgreich gespeichert und synchronisiert.'));
    }
    function createNewRoleInManager() {
      currentEditingRoleId = "new";
      clearRoleEditorFields();
      document.getElementById("role-manager-name").placeholder = psT('ui.prompt_studio.role_placeholder', 'z.B. Planner');
      document.getElementById("role-manager-name").focus();
      
      const select = document.getElementById("role-manager-select");
      if (select) {
        const opt = document.createElement("option");
        opt.value = "new";
        opt.innerText = psT('ui.prompt_studio.new_role_option', '➕ Neue Rolle...');
        opt.selected = true;
        select.appendChild(opt);
      }
    }
    async function deleteSelectedRole() {
      if (!currentEditingRoleId || currentEditingRoleId === "new") return;
      const role = roles.find(r => r.id === currentEditingRoleId);
      if (!role) return;
      
      if (!confirm(psT('ui.prompt_studio.confirm_delete_role', 'Möchten Sie die Rolle "{name}" wirklich löschen?', { name: role.name }))) {
        return;
      }
      
      roles = roles.filter(r => r.id !== currentEditingRoleId);
      await saveRolesToServer();
      
      const defaultRole = roles.length > 0 ? roles[0].name : "Researcher";
      const defaultPrompt = roles.length > 0 ? roles[0].prompt : "";
      
      agents.forEach(agent => {
        if (agent.role === role.name) {
          agent.role = defaultRole;
          agent.prompt = defaultPrompt;
        }
      });
      await saveAgentsToServer();
      await loadAgentsFromServer();
      
      openRoleManagerModal();
    }
    async function resetRolesToDefault() {
      if (!confirm(psT('ui.prompt_studio.confirm_reset_roles', 'Möchten Sie alle Rollen auf die Standardwerte zurücksetzen? Eigene Rollen gehen verloren.'))) {
        return;
      }
      
      roles = [];
      await saveRolesToServer();
      await loadRolesFromServer();
      await loadAgentsFromServer();
      openRoleManagerModal();
    }
    async function loadRolesFromServer() {
      try {
        const res = await fetch("/api/roles");
        roles = await res.json();
      } catch (e) { console.error("Error loading roles:", e); }
    }
    async function saveRolesToServer() {
      try {
        await fetch("/api/roles", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(roles)
        });
      } catch (e) { console.error("Error saving roles:", e); }
    }
    async function loadModelsFromServer() {
      try {
        const res = await fetch("/api/models");
        modelsList = await res.json();
      } catch (e) {
        modelsList = ["free-forever", "gpt-4o", "gpt-4o-mini", "claude-3-5-sonnet", "hermes-3", "gemini-1.5-pro"];
      }
    }
    function renderAgentRegistryTable() {
      const tbody = document.getElementById("agent-registry-body");
      if (!tbody) return;
      tbody.innerHTML = "";
      if (agents.length === 0) {
        tbody.innerHTML = `<tr><td colspan="7" class="px-4 py-8 text-center text-xs text-muted-custom">${psT('ui.prompt_studio.registry_empty', 'No deployed agents. Click Deploy to add slots.')}</td></tr>`;
        return;
      }
      agents.forEach(agent => {
        const tr = document.createElement("tr");
        tr.className = "border-b theme-border hover:bg-neutral-800/10 transition-colors";
        
        const status = agent.active ? "running" : "idle";
        const dotColor = statusColor[status];
        
        tr.innerHTML = `
          <td class="px-4 py-3 text-xs font-mono text-label-custom">${agent.id}</td>
          <td class="px-4 py-3 text-xs font-semibold text-secondary-custom">
            <input type="text" value="${agent.name}" onchange="updateAgentField('${agent.id}', 'name', this.value)" class="bg-transparent border-none text-xs font-semibold focus:outline-none w-24 text-secondary-custom">
          </td>
          <td class="px-4 py-3 text-xs font-mono text-muted-custom">
            <input type="text" value="${agent.model}" onchange="updateAgentField('${agent.id}', 'model', this.value)" class="bg-transparent border-none text-xs font-mono focus:outline-none w-28 text-muted-custom">
          </td>
          <td class="px-4 py-3">
            <div class="flex items-center gap-1.5">
              <span class="w-1.5 h-1.5 rounded-full flex-shrink-0" style="background: ${dotColor}; box-shadow: 0 0 5px ${dotColor}"></span>
              <span class="text-[10px] uppercase font-mono tracking-wider" style="color: ${dotColor}">${status}</span>
            </div>
          </td>
          <td class="px-4 py-3 text-xs text-muted-custom">${agent.active ? '12' : '0'}</td>
          <td class="px-4 py-3 text-xs font-mono text-label-custom">${agent.active ? '2h 10m' : '—'}</td>
          <td class="px-4 py-3">
            <div class="flex items-center gap-1.5">
              <button onclick="toggleAgentActive('${agent.id}')" class="p-1 rounded hover:bg-black/10 transition-colors" title="${agent.active ? 'Pause' : 'Start'}">
                <i data-lucide="${agent.active ? 'pause' : 'play'}" class="w-3.5 h-3.5 text-muted-custom"></i>
              </button>
              <button onclick="restartAgent('${agent.name}')" class="p-1 rounded hover:bg-black/10 transition-colors" title="Restart">
                <i data-lucide="rotate-ccw" class="w-3.5 h-3.5 text-muted-custom"></i>
              </button>
              <button onclick="alert('System Prompt: ' + '${agent.prompt}')" class="p-1 rounded hover:bg-black/10 transition-colors" title="System Prompt">
                <i data-lucide="more-horizontal" class="w-3.5 h-3.5 text-muted-custom"></i>
              </button>
            </div>
          </td>
        `;
        tbody.appendChild(tr);
      });
      lucide.createIcons();
    }
      // MISSION CONTROL, PAPERCLIP, AI MASTERMIND & KANBAN EXTRACTED TO js/mission_control.js

    // --- WORKSPACE GALLERY & SANDBOX ---
    let activeGallerySubTab = "vault";
    function setGallerySubTab(tab) {
      activeGallerySubTab = tab;
      const tabVaultBtn = document.getElementById("gallery-sub-vault");
      const tabSandboxBtn = document.getElementById("gallery-sub-sandbox");
      
      if (tab === "vault") {
        document.getElementById("gallery-subview-vault").classList.remove("hidden");
        document.getElementById("gallery-subview-sandbox").classList.add("hidden");
        tabVaultBtn.className = "py-2 px-4 text-xs font-bold border-b-2 border-accent-color text-primary-custom";
        tabSandboxBtn.className = "py-2 px-4 text-xs font-bold border-b-2 border-transparent text-muted-custom";
        loadVaultFiles();
      } else {
        document.getElementById("gallery-subview-vault").classList.add("hidden");
        document.getElementById("gallery-subview-sandbox").classList.remove("hidden");
        tabVaultBtn.className = "py-2 px-4 text-xs font-bold border-b-2 border-transparent text-muted-custom";
        tabSandboxBtn.className = "py-2 px-4 text-xs font-bold border-b-2 border-accent-color text-primary-custom";
      }
    }
    async function loadVaultFiles() {
      try {
        const res = await fetch("/api/vault");
        vaultFiles = await res.json();
        const select = document.getElementById("vault-select");
        select.innerHTML = "";
        if (vaultFiles.length === 0) {
          select.innerHTML = `<option value="">${psT('ui.prompt_studio.vault_no_files', 'Keine Dateien')}</option>`;
          document.getElementById("vault-editor").value = "";
          document.getElementById("markdown-preview-container").classList.add("hidden");
          return;
        }
        vaultFiles.forEach(file => {
          const opt = document.createElement("option");
          opt.value = file.path;
          opt.innerText = `${file.type}: ${file.name}`;
          select.appendChild(opt);
        });
        loadFile(vaultFiles[0].path);
      } catch (e) {}
    }
    async function loadFile(path) {
      if (!path || path === "Keine Dateien" || path.startsWith("Keine")) return;
      loadedFilePath = path;
      const file = vaultFiles.find(f => f.path === path);
      try {
        const res = await fetch(`/api/vault/file?path=${encodeURIComponent(path)}`);
        const data = await res.json();
        const editor = document.getElementById("vault-editor");
        editor.value = data.content;
        const previewContainer = document.getElementById("markdown-preview-container");
        if (file && file.type === "Obsidian MD") {
          previewContainer.classList.remove("hidden");
          document.getElementById("markdown-preview").innerText = data.content;
        } else {
          previewContainer.classList.add("hidden");
        }
      } catch (e) {
        console.error("Error loading file:", e);
      }
    }
    async function saveFile() {
      if (!loadedFilePath) return;
      const content = document.getElementById("vault-editor").value;
      try {
        const res = await fetch("/api/vault/edit", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path: loadedFilePath, content })
        });
        if (res.ok) {
          alert(psT('ui.prompt_studio.file_saved', 'Datei erfolgreich gespeichert!'));
          const file = vaultFiles.find(f => f.path === loadedFilePath);
          if (file && file.type === "Obsidian MD") {
            document.getElementById("markdown-preview").innerText = content;
          }
        } else {
          alert(psT('ui.prompt_studio.file_save_failed', 'Fehler beim Speichern der Datei.'));
        }
      } catch (e) {
        alert(psT('ui.prompt_studio.error_only', 'Fehler: {message}', { message: e.message }));
      }
    }
    async function deleteFile() {
      if (!loadedFilePath) return;
      if (!confirm(psT('ui.prompt_studio.confirm_delete_file', 'Möchten Sie diese Datei wirklich löschen?'))) return;
      try {
        const res = await fetch(`/api/vault?path=${encodeURIComponent(loadedFilePath)}`, {
          method: "DELETE"
        });
        if (res.ok) {
          alert(psT('ui.prompt_studio.file_deleted', 'Datei gelöscht!'));
          await loadVaultFiles();
        } else {
          alert(psT('ui.prompt_studio.file_delete_failed', 'Fehler beim Löschen der Datei.'));
        }
      } catch (e) {
        alert(psT('ui.prompt_studio.error_only', 'Fehler: {message}', { message: e.message }));
      }
    }
    // Sandbox code runner
        async function runSandbox() {
          const filename = document.getElementById("sandbox-filename").value.trim();
          const code = document.getElementById("sandbox-code").value;
          if (!filename) return;
          const btn = document.getElementById("sandbox-btn");
          btn.innerText = psT('ui.prompt_studio.running_btn', 'Ausführen...');
          btn.disabled = true;
          try {
            const res = await fetch("/api/sandbox/execute", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ code: code, language: "python" })
            });
            const data = await res.json();

            document.getElementById("sandbox-output-block").classList.remove("hidden");
            const consolePre = document.getElementById("sandbox-console");
            // Neue Endpunkt liefert andere Keys: success/failed/timeout, exit_code, stdout, stderr, duration_seconds
            if (data.status === "success") {
              let output = psT('ui.prompt_studio.exit_code', 'Exit Code: {code}', { code: data.exit_code }) + '\n\n';
              if (data.stdout) {
                output += `--- STDOUT ---\n${data.stdout}\n`;
              }
              if (data.stderr) {
                output += `--- STDERR ---\n${data.stderr}\n`;
              }
              if (data.duration_seconds !== undefined) {
                output += '\n' + psT('ui.prompt_studio.duration', 'Dauer: {seconds}s', { seconds: data.duration_seconds });
              }
              consolePre.innerText = output;
              consolePre.style.color = "#22c55e";
            } else if (data.status === "failed") {
              let output = psT('ui.prompt_studio.exit_code', 'Exit Code: {code}', { code: data.exit_code }) + '\n\n';
              if (data.stdout) {
                output += `--- STDOUT ---\n${data.stdout}\n`;
              }
              if (data.stderr) {
                output += `--- STDERR ---\n${data.stderr}\n`;
              }
              if (data.error) {
                output += `\nFehler: ${data.error}`;
              }
              consolePre.innerText = output;
              consolePre.style.color = "#ef4444";
            } else if (data.status === "timeout") {
              consolePre.innerText = psT('ui.prompt_studio.sandbox_timeout', 'Timeout: {message}', { message: data.error || psT('ui.prompt_studio.sandbox_timeout_default', 'Ausführung überschritt das Zeitlimit.') });
              consolePre.style.color = "#ef4444";
            } else if (data.status === "disabled") {
              consolePre.innerText = psT('ui.prompt_studio.sandbox_disabled', 'Deaktiviert: {message}', { message: data.error || psT('ui.prompt_studio.sandbox_disabled_default', 'Sandbox ist deaktiviert.') });
              consolePre.style.color = "#ef4444";
            } else {
              consolePre.innerText = psT('ui.prompt_studio.error_only', 'Fehler: {message}', { message: data.error || data.message || psT('ui.prompt_studio.unknown_error', 'Unbekannter Fehler') });
              consolePre.style.color = "#ef4444";
            }
          } catch (e) {
            alert(psT('ui.prompt_studio.sandbox_conn_failed', 'Fehler bei Sandbox-Verbindung.'));
          } finally {
            btn.innerText = psT('ui.prompt_studio.run_code_btn', '🚀 Code ausführen');
            btn.disabled = false;
          }
        }