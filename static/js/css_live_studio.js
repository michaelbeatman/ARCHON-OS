
    // --- i18n-Helfer (Tranche 4) ---------------------------------------------
    // cssT() liefert den Katalogtext mit PFLICHT-Fallback: fehlt der Key in der
    // aktiven Sprache und in de, bleibt der deutsche Text stehen - nie "".
    // {platzhalter} werden aus params gefuellt (Zahlen stehen nie im Key).
    function cssT(key, fallback, params) {
      const i18n = window.archonI18n;
      let text = i18n ? i18n.t(key, fallback) : fallback;
      if (params) {
        Object.keys(params).forEach(name => {
          text = text.split(`{${name}}`).join(String(params[name]));
        });
      }
      return text;
    }

    // ====================================================
    // NATIVE LIVE VISUAL DESIGNER & FREEZE SYSTEM
    // ====================================================
    let isLiveTextEditingActive = false;
    let activeInspectorElement = null;
    let liveModifiedElementsSet = new Set();
    // =========================================================================
    // ARCHON VISUAL CSS LIVE STUDIO & DOM INSPECTOR ENGINE (Full In-Place Suite)
    // =========================================================================
    function rgbToHex(rgb) {
      if (!rgb || typeof rgb !== 'string') return '#000000';
      if (rgb.startsWith('#')) return rgb;
      const parts = rgb.match(/\d+/g);
      if (!parts || parts.length < 3) return '#000000';
      return '#' + parts.slice(0, 3).map(x => {
        const h = parseInt(x, 10).toString(16);
        return h.length === 1 ? '0' + h : h;
      }).join('');
    }
    let isCssStudioOpen = false;
    let isStudioMinimized = false;
    let isStudioInspectorActive = false;
    let isStudioTextModeActive = false;
    let isStudioGizmoActive = true;
    let studioSelectedElement = null;
    let studioSelectedSelector = "";
    let studioRules = {}; // { selector: { property: value } }
    let studioTextOverrides = {}; // { originalText: newText }
    let studioHtmlOverrides = {}; // { selector: newHtml }
    let studioActiveTab = "visual";
    let studioSaveTimeout = null;
    // Expose on window for external triggers and debugging
    window.toggleCssStudio = toggleCssStudio;
    window.enableStudioInspector = enableStudioInspector;
    window.disableStudioInspector = disableStudioInspector;
    window.toggleStudioInspector = toggleStudioInspector;
    window.toggleStudioGizmo = toggleStudioGizmo;
    window.selectStudioElement = selectStudioElement;
    window.toggleStudioElementHide = toggleStudioElementHide;
    window.toggleStudioAnimationStop = toggleStudioAnimationStop;
    window.applyStudioSymbolPreset = applyStudioSymbolPreset;
    window.setStudioElementHtml = setStudioElementHtml;
    window.resetStudioElementHtml = resetStudioElementHtml;
    window.unhideStudioElement = unhideStudioElement;
    window.renderStudioSymbolsTab = renderStudioSymbolsTab;
    window.ensureGoogleFontLoaded = ensureGoogleFontLoaded;
    window.onStudioFontFamilySelect = onStudioFontFamilySelect;
    window.applyStudioGlobalFont = applyStudioGlobalFont;
    window.saveStudioOverrides = saveStudioOverrides;
    window.bakeStudioIntoMainDesign = bakeStudioIntoMainDesign;
    window.exportStudioCss = exportStudioCss;
    window.resetAllStudioStyles = resetAllStudioStyles;
    window.resetSelectedElementStyles = resetSelectedElementStyles;
    // Initialize Studio & Load Persistence
    window.ARCHON_LEGACY_STUDIO_DISABLED = false;
    async function initArchonCssStudio() {
      // 1. Try loading from localStorage first (Niemals automatisch löschen)
      try {
        const cached = localStorage.getItem("archon_theme_live_overrides");
        if (cached) {
          const parsed = JSON.parse(cached);
          if (parsed.rules) studioRules = parsed.rules;
          if (parsed.textOverrides) studioTextOverrides = parsed.textOverrides;
        }
        const cachedHtml = localStorage.getItem("archon_theme_html_overrides");
        if (cachedHtml) {
          studioHtmlOverrides = JSON.parse(cachedHtml) || {};
          applyStudioHtmlOverridesToDOM();
        }
      } catch (e) {
        console.warn("Could not load local live overrides:", e);
      }
      // 2. Fetch latest from Server (defensiver Fallback mit sicherem Merge)
      try {
        const res = await fetch("/api/theme/live-overrides");
        if (res.ok) {
          const data = await res.json();
          if (data) {
            if (data.migration_version && data.migration_version !== localStorage.getItem("archon_theme_migration_version")) {
              studioRules = data.rules || {};
              studioTextOverrides = data.textOverrides || {};
              studioHtmlOverrides = data.htmlOverrides || {};
              localStorage.setItem("archon_theme_migration_version", data.migration_version);
              if (data.reset_all || Object.keys(studioRules).length === 0) {
                studioRules = {};
                studioTextOverrides = {};
                studioHtmlOverrides = {};
                localStorage.removeItem("archon_theme_live_overrides");
                localStorage.removeItem("archon_theme_html_overrides");
              } else {
                localStorage.setItem("archon_theme_live_overrides", JSON.stringify({
                  rules: studioRules,
                  textOverrides: studioTextOverrides,
                  htmlOverrides: studioHtmlOverrides
                }));
                localStorage.setItem("archon_theme_html_overrides", JSON.stringify(studioHtmlOverrides));
              }
            } else if (data.rules) {
              const mergedRules = { ...data.rules };
              for (const [sel, props] of Object.entries(studioRules || {})) {
                mergedRules[sel] = { ...(mergedRules[sel] || {}), ...props };
              }
              studioRules = mergedRules;
              if (data.textOverrides) {
                studioTextOverrides = { ...data.textOverrides, ...(studioTextOverrides || {}) };
              }
              if (data.htmlOverrides) {
                studioHtmlOverrides = { ...data.htmlOverrides, ...(studioHtmlOverrides || {}) };
                localStorage.setItem("archon_theme_html_overrides", JSON.stringify(studioHtmlOverrides));
              }
              localStorage.setItem("archon_theme_live_overrides", JSON.stringify({
                rules: studioRules,
                textOverrides: studioTextOverrides,
                htmlOverrides: studioHtmlOverrides
              }));
              const localCount = Object.values(studioRules).reduce((a, c) => a + Object.keys(c).length, 0);
              const serverCount = Object.values(data.rules || {}).reduce((a, c) => a + Object.keys(c).length, 0);
              // FIX 10.10.2026: alte Bedingung "(serverCount === 0 && !data.rules)" konnte
              // NIE zutreffen (leeres Objekt ist truthy) → Server-Resets wurden nie erkannt
              // und die lokalen Alt-Regeln per POST zurückerzeugt (Resurrection-Schleife).
              if (data.reset_all || serverCount === 0) {
                // FIX 11.10.2026 (User-Fall: lokale Regeln verschwanden bei
                // leerem Server bei JEDEM F5): WIPE nur bei EKPLIZITEM
                // reset_all-Signal (der DELETE-Endpoint setzt es). Server
                // "leer" kann auch 'nie gespeichert' bedeuten - lokale
                // Altregeln duerfen dann NICHT zerstoert werden.
                if (data.reset_all) {
                  studioRules = {};
                  studioTextOverrides = {};
                  studioHtmlOverrides = {};
                  localStorage.removeItem("archon_theme_live_overrides");
                  localStorage.removeItem("archon_theme_html_overrides");
                } else if (localCount > serverCount) {
                  saveStudioOverrides(true); // lokale Regeln nach oben synchronisieren
                }
              } else if (localCount > serverCount) {
                saveStudioOverrides(true);
              }
            }
          }
        }
      } catch (e) {
        // Normaler Fallback auf localStorage
      }
      // 3. Sanitize: Migriere #nav-master-chat auf .archon-nav-item.nav-item-active falls in localStorage
      if (studioRules && studioRules["#nav-master-chat"]) {
        delete studioRules["#nav-master-chat"];
        studioRules[".archon-nav-item.nav-item-active"] = {
          "box-shadow": "0 4px 6px -1px rgba(0,0,0,0.1), 0 2px 4px -2px rgba(0,0,0,0.1) !important",
          "border-color": "rgb(100, 116, 139) !important",
          "border-width": "2px !important"
        };
        try {
          localStorage.setItem("archon_theme_live_overrides", JSON.stringify({
            rules: studioRules,
            textOverrides: studioTextOverrides
          }));
        } catch (e) {}
      }
      // 4. Compile & Apply Live Stylesheet
      applyStudioRulesToDOM();
      applyStudioTextOverridesToDOM();
      applyStudioHtmlOverridesToDOM();
      updateStudioActiveRulesCounters();
      // 4. Setup Header Dragging & Gizmo Handlers
      setupStudioDraggable();
      setupStudioGizmoListeners();
    }
    // Top-Level Immediate Shortcut
    window.addEventListener("keydown", (e) => {
      if (e.altKey && (e.key === "s" || e.key === "S" || e.code === "KeyS")) {
        e.preventDefault();
        toggleCssStudio();
      }
      if ((e.ctrlKey || e.metaKey) && (e.key === "s" || e.key === "S" || e.code === "KeyS")) {
        const studio = document.getElementById("archon-css-studio");
        if (studio && !studio.classList.contains("hidden")) {
          e.preventDefault();
          saveStudioOverrides();
        }
      }
    });
    // Toggle Studio Open/Closed
    async function toggleCssStudio() {
      let studio = document.getElementById("archon-css-studio");
      if (!studio) {
        try {
          const r = await fetch("/static/views/view_app_frame_studio.html?v=" + Date.now());
          const h = await r.text();
          const m = document.getElementById("view-app-frame-studio-mount");
          if (m) m.outerHTML = h;
          else {
             const div = document.createElement("div");
             div.innerHTML = h;
             document.body.appendChild(div);
          }
          studio = document.getElementById("archon-css-studio");
        } catch(e) {}
      }
      // 10.10.2026: 'const studio' hier entfernt — 'studio' existiert seit
      // Zeile 164 (let) und wurde oben ggf. nachgeladen; eine zweite Deklaration
      // in derselben Funktion ist ein SyntaxError und tötet die ganze Datei.
      const minPill = document.getElementById("archon-css-studio-minimized");
      const btn = document.getElementById("btn-toggle-css-studio");
      if (!studio) return;
      isCssStudioOpen = !isCssStudioOpen;
      window.isCssStudioOpen = isCssStudioOpen;
      if (isCssStudioOpen) {
        studio.classList.remove("hidden");
        if (minPill) minPill.classList.add("hidden");
        if (btn) btn.classList.add("ring-2", "ring-indigo-500", "bg-indigo-500/30");
        setupStudioDraggable();
        lucide.createIcons();
        if (studioSelectedElement) {
          updateStudioGizmoPosition();
        }
      } else {
        studio.classList.add("hidden");
        if (minPill) minPill.classList.add("hidden");
        if (btn) btn.classList.remove("ring-2", "ring-indigo-500", "bg-indigo-500/30");
        if (isStudioInspectorActive) disableStudioInspector();
        if (isStudioTextModeActive) disableStudioTextMode();
        const gizmo = document.getElementById("archon-css-gizmo");
        if (gizmo) gizmo.classList.add("hidden");
      }
    }
    function minimizeCssStudio() {
      const studio = document.getElementById("archon-css-studio");
      const minPill = document.getElementById("archon-css-studio-minimized");
      const gizmo = document.getElementById("archon-css-gizmo");
      if (studio) studio.classList.add("hidden");
      if (minPill) minPill.classList.remove("hidden");
      if (gizmo) gizmo.classList.add("hidden");
      isStudioMinimized = true;
      if (isStudioInspectorActive) disableStudioInspector();
      lucide.createIcons();
    }
    function restoreCssStudio() {
      const studio = document.getElementById("archon-css-studio");
      const minPill = document.getElementById("archon-css-studio-minimized");
      if (studio) studio.classList.remove("hidden");
      if (minPill) minPill.classList.add("hidden");
      isStudioMinimized = false;
      updateStudioGizmoPosition();
      lucide.createIcons();
    }
    // ==========================================
    // INTERACTIVE DRAG & CORNER GIZMO CONTROLLER
    // ==========================================
    function toggleStudioGizmo() {
      if (isStudioGizmoActive) {
        disableStudioGizmo();
      } else {
        enableStudioGizmo();
      }
    }
    function enableStudioGizmo() {
      isStudioGizmoActive = true;
      const btn = document.getElementById("btn-studio-gizmo-mode");
      if (btn) {
        btn.classList.add("bg-indigo-600", "text-white", "border-indigo-400");
        btn.classList.remove("bg-indigo-600/30", "text-cyan-300", "border-cyan-500/40");
      }
      updateStudioGizmoPosition();
    }
    function disableStudioGizmo() {
      isStudioGizmoActive = false;
      const btn = document.getElementById("btn-studio-gizmo-mode");
      const gizmo = document.getElementById("archon-css-gizmo");
      if (btn) {
        btn.classList.remove("bg-indigo-600", "text-white", "border-indigo-400");
        btn.classList.add("bg-indigo-600/30", "text-cyan-300", "border-cyan-500/40");
      }
      if (gizmo) gizmo.classList.add("hidden");
    }
    function updateStudioGizmoPosition() {
      const gizmo = document.getElementById("archon-css-gizmo");
      if (!gizmo) return;
      if (!isStudioGizmoActive || !isCssStudioOpen || !studioSelectedElement || isStudioInspectorActive) {
        gizmo.classList.add("hidden");
        return;
      }
      const el = studioSelectedElement;
      if (!document.body.contains(el) || el === document.body || el === document.documentElement || el.id === 'main-viewport-scroll') {
        gizmo.classList.add("hidden");
        return;
      }
      const rect = el.getBoundingClientRect();
      if (rect.width === 0 && rect.height === 0) {
        gizmo.classList.add("hidden");
        return;
      }
      gizmo.style.top = `${rect.top}px`;
      gizmo.style.left = `${rect.left}px`;
      gizmo.style.width = `${rect.width}px`;
      gizmo.style.height = `${rect.height}px`;
      gizmo.classList.remove("hidden");
      // Update info badge
      const computed = window.getComputedStyle(el);
      const bRad = computed.borderRadius || '0px';
      const badge = document.getElementById("gizmo-info-badge");
      if (badge) {
        badge.innerText = `W: ${Math.round(rect.width)}px × H: ${Math.round(rect.height)}px | Radius: ${bRad}`;
      }
    }
    // Keep Gizmo synced on window scroll or resize (throttled via requestAnimationFrame)
    let gizmoRafId = null;
    function scheduleGizmoUpdate() {
      if (!isStudioGizmoActive || !studioSelectedElement) return;
      if (gizmoRafId) return;
      gizmoRafId = requestAnimationFrame(() => {
        gizmoRafId = null;
        if (isStudioGizmoActive && studioSelectedElement) {
          updateStudioGizmoPosition();
        }
      });
    }
    window.addEventListener("scroll", scheduleGizmoUpdate, { passive: true, capture: true });
    window.addEventListener("resize", scheduleGizmoUpdate, { passive: true });
    // Setup Gizmo Interactive Event Listeners
    function setupStudioGizmoListeners() {
      const gizmo = document.getElementById("archon-css-gizmo");
      if (!gizmo) return;
      // 1. Position Drag (Move handle)
      const moveHandle = document.getElementById("gizmo-handle-move");
      if (moveHandle) {
        moveHandle.addEventListener("mousedown", onGizmoMoveMouseDown);
      }
      // 2. Corner Resize handles
      gizmo.querySelectorAll(".gizmo-handle-corner").forEach(h => {
        h.addEventListener("mousedown", (e) => onGizmoResizeMouseDown(e, h.dataset.corner, 'corner'));
      });
      // 3. Edge Resize handles
      gizmo.querySelectorAll(".gizmo-handle-edge").forEach(h => {
        h.addEventListener("mousedown", (e) => onGizmoResizeMouseDown(e, h.dataset.edge, 'edge'));
      });
      // 4. Corner Radius Knobs
      gizmo.querySelectorAll(".gizmo-handle-radius").forEach(h => {
        h.addEventListener("mousedown", (e) => onGizmoRadiusMouseDown(e, h.dataset.radius));
      });
    }
    // --- Move Position Handler (Drag & Drop) ---
    function onGizmoMoveMouseDown(e) {
      if (!studioSelectedElement) return;
      e.preventDefault();
      e.stopPropagation();
      const el = studioSelectedElement;
      const startX = e.clientX;
      const startY = e.clientY;
      const computed = window.getComputedStyle(el);
      const isPos = computed.position === 'absolute' || computed.position === 'fixed';
      
      let initLeft = parseFloat(computed.left) || 0;
      let initTop = parseFloat(computed.top) || 0;
      if (!isPos && computed.position === 'static') {
        initLeft = 0;
        initTop = 0;
      }
      function onMouseMove(moveEvt) {
        const dx = moveEvt.clientX - startX;
        const dy = moveEvt.clientY - startY;
        const newLeft = initLeft + dx;
        const newTop = initTop + dy;
        if (computed.position === 'static') {
          el.style.position = 'relative';
        }
        el.style.left = `${newLeft}px`;
        el.style.top = `${newTop}px`;
        updateStudioGizmoPosition();
      }
      function onMouseUp(upEvt) {
        document.removeEventListener("mousemove", onMouseMove);
        document.removeEventListener("mouseup", onMouseUp);
        const dx = upEvt.clientX - startX;
        const dy = upEvt.clientY - startY;
        if (dx !== 0 || dy !== 0) {
          if (computed.position === 'static') {
            onStudioPropChange('position', 'relative');
          }
          onStudioPropChange('left', `${initLeft + dx}px`);
          onStudioPropChange('top', `${initTop + dy}px`);
        }
      }
      document.addEventListener("mousemove", onMouseMove);
      document.addEventListener("mouseup", onMouseUp);
    }
    // --- Resize Handler (Ecken & Kanten ziehen) ---
    function onGizmoResizeMouseDown(e, dir, type) {
      if (!studioSelectedElement) return;
      e.preventDefault();
      e.stopPropagation();
      const el = studioSelectedElement;
      const startX = e.clientX;
      const startY = e.clientY;
      const startW = el.offsetWidth;
      const startH = el.offsetHeight;
      function onMouseMove(moveEvt) {
        const dx = moveEvt.clientX - startX;
        const dy = moveEvt.clientY - startY;
        let newW = startW;
        let newH = startH;
        if (dir.includes('e')) newW = Math.max(16, startW + dx);
        if (dir.includes('w')) newW = Math.max(16, startW - dx);
        if (dir.includes('s')) newH = Math.max(16, startH + dy);
        if (dir.includes('n')) newH = Math.max(16, startH - dy);
        el.style.width = `${newW}px`;
        el.style.height = `${newH}px`;
        updateStudioGizmoPosition();
      }
      function onMouseUp(upEvt) {
        document.removeEventListener("mousemove", onMouseMove);
        document.removeEventListener("mouseup", onMouseUp);
        const dx = upEvt.clientX - startX;
        const dy = upEvt.clientY - startY;
        let newW = startW;
        let newH = startH;
        if (dir.includes('e')) newW = Math.max(16, startW + dx);
        if (dir.includes('w')) newW = Math.max(16, startW - dx);
        if (dir.includes('s')) newH = Math.max(16, startH + dy);
        if (dir.includes('n')) newH = Math.max(16, startH - dy);
        if (newW !== startW) onStudioPropChange('width', `${newW}px`);
        if (newH !== startH) onStudioPropChange('height', `${newH}px`);
      }
      document.addEventListener("mousemove", onMouseMove);
      document.addEventListener("mouseup", onMouseUp);
    }
    // --- Radius Handler (Ecken-Rundung per Drag) ---
    function onGizmoRadiusMouseDown(e, corner) {
      if (!studioSelectedElement) return;
      e.preventDefault();
      e.stopPropagation();
      const el = studioSelectedElement;
      const startX = e.clientX;
      const startY = e.clientY;
      const computed = window.getComputedStyle(el);
      const initRadius = parseFloat(computed.borderRadius) || 0;
      function onMouseMove(moveEvt) {
        const dx = moveEvt.clientX - startX;
        const dy = moveEvt.clientY - startY;
        let delta = 0;
        if (corner === 'tl') delta = (dx + dy) / 2;
        else if (corner === 'tr') delta = (-dx + dy) / 2;
        else if (corner === 'br') delta = (-dx - dy) / 2;
        else if (corner === 'bl') delta = (dx - dy) / 2;
        const newRadius = Math.max(0, Math.min(100, Math.round(initRadius + delta)));
        el.style.borderRadius = `${newRadius}px`;
        const badge = document.getElementById("gizmo-info-badge");
        if (badge) {
          badge.innerText = `Radius: ${newRadius}px`;
        }
      }
      function onMouseUp(upEvt) {
        document.removeEventListener("mousemove", onMouseMove);
        document.removeEventListener("mouseup", onMouseUp);
        const dx = upEvt.clientX - startX;
        const dy = upEvt.clientY - startY;
        let delta = 0;
        if (corner === 'tl') delta = (dx + dy) / 2;
        else if (corner === 'tr') delta = (-dx + dy) / 2;
        else if (corner === 'br') delta = (-dx - dy) / 2;
        else if (corner === 'bl') delta = (dx - dy) / 2;
        const newRadius = Math.max(0, Math.min(100, Math.round(initRadius + delta)));
        onStudioPropChange('border-radius', `${newRadius}px`);
        updateStudioGizmoPosition();
      }
      document.addEventListener("mousemove", onMouseMove);
      document.addEventListener("mouseup", onMouseUp);
    }
    function restoreCssStudio() {
      const studio = document.getElementById("archon-css-studio");
      const minPill = document.getElementById("archon-css-studio-minimized");
      if (studio) studio.classList.remove("hidden");
      if (minPill) minPill.classList.add("hidden");
      isStudioMinimized = false;
      lucide.createIcons();
    }
    // Tab Switching
    function setStudioTab(tabName) {
      studioActiveTab = tabName;
      ['visual', 'symbols', 'rules', 'code', 'texts'].forEach(t => {
        const btn = document.getElementById(`studio-tab-btn-${t}`);
        const content = document.getElementById(`studio-tab-content-${t}`);
        if (btn) {
          if (t === tabName) {
            btn.className = "studio-tab-btn px-2.5 py-1.5 font-bold border-b-2 border-zinc-200 text-zinc-100 transition flex items-center gap-1 cursor-pointer shrink-0";
          } else {
            btn.className = "studio-tab-btn px-2.5 py-1.5 font-bold border-b-2 border-transparent text-zinc-400 hover:text-zinc-200 transition flex items-center gap-1 cursor-pointer shrink-0";
          }
        }
        if (content) {
          content.classList.toggle("hidden", t !== tabName);
        }
      });
      if (tabName === 'symbols') renderStudioSymbolsTab();
      if (tabName === 'rules') renderStudioRulesList();
      if (tabName === 'code') renderStudioRawCss();
      if (tabName === 'texts') renderStudioTextsList();
      lucide.createIcons();
    }
    // ==========================================
    // INTERACTIVE HOVER & CLICK INSPECTOR
    // ==========================================
    function toggleStudioInspector() {
      if (isStudioInspectorActive) {
        disableStudioInspector();
      } else {
        enableStudioInspector();
      }
    }
    function enableStudioInspector() {
      isStudioInspectorActive = true;
      window.isStudioInspectorActive = true;
      const btn = document.getElementById("btn-studio-pick-element");
      const lbl = document.getElementById("lbl-studio-pick");
      if (btn) {
        btn.classList.remove("bg-zinc-100", "text-zinc-900", "hover:bg-white");
        btn.classList.add("bg-zinc-200", "text-zinc-950", "ring-2", "ring-zinc-400", "animate-pulse");
      }
      if (lbl) lbl.innerText = cssT("ui.css_live_studio.pick_active", "🎯 Klicke ein Element an...");
      document.body.style.cursor = "crosshair";
      document.addEventListener("mousemove", onStudioInspectorMouseMove, true);
      document.addEventListener("click", onStudioInspectorClick, true);
    }
    function disableStudioInspector() {
      isStudioInspectorActive = false;
      window.isStudioInspectorActive = false;
      const highlighter = document.getElementById("archon-css-highlighter");
      if (highlighter) highlighter.classList.add("hidden");
      const btn = document.getElementById("btn-studio-pick-element");
      const lbl = document.getElementById("lbl-studio-pick");
      if (btn) {
        btn.classList.remove("bg-zinc-200", "text-zinc-950", "ring-2", "ring-zinc-400", "animate-pulse");
        btn.classList.add("bg-zinc-100", "text-zinc-900", "hover:bg-white");
      }
      if (lbl) lbl.innerText = cssT("ui.css_live_studio.pick_idle", "🎯 Element Auswählen");
      document.body.style.cursor = "";
      document.removeEventListener("mousemove", onStudioInspectorMouseMove, true);
      document.removeEventListener("click", onStudioInspectorClick, true);
    }
    function onStudioInspectorMouseMove(e) {
      if (!isStudioInspectorActive) return;
      const target = e.target;
      if (!target || target.closest("#archon-css-studio") || target.closest("#archon-css-studio-minimized") || target.closest("#archon-css-highlighter")) {
        return;
      }
      const highlighter = document.getElementById("archon-css-highlighter");
      const badge = document.getElementById("archon-highlighter-badge");
      if (!highlighter) return;
      const rect = target.getBoundingClientRect();
      highlighter.style.top = `${rect.top}px`;
      highlighter.style.left = `${rect.left}px`;
      highlighter.style.width = `${rect.width}px`;
      highlighter.style.height = `${rect.height}px`;
      highlighter.classList.remove("hidden");
      if (badge) {
        let tagInfo = target.tagName.toLowerCase();
        if (target.id) tagInfo += `#${target.id}`;
        else if (target.className && typeof target.className === 'string') {
          const firstClass = target.className.split(' ').filter(c => c && !c.startsWith('live-') && !c.includes(':'))[0];
          if (firstClass) tagInfo += `.${firstClass}`;
        }
        badge.innerText = `${tagInfo} (${Math.round(rect.width)} × ${Math.round(rect.height)}px)`;
      }
    }
    function onStudioInspectorClick(e) {
      if (!isStudioInspectorActive) return;
      const target = e.target;
      if (!target || target.closest("#archon-css-studio") || target.closest("#archon-css-studio-minimized") || target.closest("#archon-css-highlighter")) {
        return;
      }
      e.preventDefault();
      e.stopPropagation();
      disableStudioInspector();
      selectStudioElement(target);
    }
    // Select Element and Generate Selector
    function selectStudioElement(el) {
      if (!el) return;
      if (el.tagName && ['path', 'circle', 'line', 'polygon', 'polyline', 'rect'].includes(el.tagName.toLowerCase())) {
        if (el.closest('button')) {
          el = el.closest('button');
        } else if (el.closest('svg')) {
          el = el.closest('svg');
        }
      }
      studioSelectedElement = el;
      window.studioSelectedElement = el;
      // Smart Selector Construction
      let selector = "";
      if (el.classList && el.classList.contains("archon-nav-item")) {
        selector = el.classList.contains("nav-item-active") ? ".archon-nav-item.nav-item-active" : ".archon-nav-item";
      } else if (el.id) {
        selector = `#${el.id}`;
      } else if (el.dataset && el.dataset.role) {
        selector = `[data-role="${el.dataset.role}"]`;
      } else {
        // Find best unique class or fallback to hierarchy path
        const classes = (el.className && typeof el.className === 'string')
          ? el.className.split(/\s+/).filter(c => c && !c.startsWith('live-') && !c.includes(':') && !c.includes('/') && !c.includes('[') && !c.includes(']') && !c.includes('.'))
          : [];
        
        let foundUnique = false;
        for (const cls of classes) {
          try {
            const escaped = window.CSS && CSS.escape ? CSS.escape(cls) : cls;
            if (document.querySelectorAll(`.${escaped}`).length === 1) {
              selector = `.${escaped}`;
              foundUnique = true;
              break;
            }
          } catch (err) {}
        }
        if (!foundUnique) {
          // Construct hierarchy
          let path = [];
          let cur = el;
          while (cur && cur !== document.body && path.length < 3) {
            let part = cur.tagName.toLowerCase();
            if (cur.id) {
              part += `#${cur.id}`;
              path.unshift(part);
              break;
            }
            if (cur.className && typeof cur.className === 'string') {
              const mainCls = cur.className.split(/\s+/).filter(c => c && !c.startsWith('live-') && !c.includes(':') && !c.includes('/') && !c.includes('[') && !c.includes(']'))[0];
              if (mainCls) {
                const escCls = window.CSS && CSS.escape ? CSS.escape(mainCls) : mainCls;
                part += `.${escCls}`;
              }
            }
            path.unshift(part);
            cur = cur.parentElement;
          }
          selector = path.join(" > ");
        }
      }
      studioSelectedSelector = selector;
      const selectorInput = document.getElementById("studio-target-selector");
      const tagBadge = document.getElementById("studio-element-tag-badge");
      if (selectorInput) selectorInput.value = selector;
      if (tagBadge) tagBadge.innerText = `<${el.tagName.toLowerCase()}>`;
      // Populate Visual Controls
      populateVisualControlsFromElement(el, selector);
      // Update Quick Action Buttons & Symbols state
      updateStudioQuickActionButtons();
      // Update Transform Gizmo
      updateStudioGizmoPosition();
    }
    function onStudioSelectorInputChange(val) {
      studioSelectedSelector = val.trim();
      if (studioSelectedSelector) {
        try {
          const el = document.querySelector(studioSelectedSelector);
          if (el) {
            studioSelectedElement = el;
            populateVisualControlsFromElement(el, studioSelectedSelector);
            updateStudioQuickActionButtons();
          }
        } catch (e) {}
      }
    }
    // Populate all UI accordions with element's computed & overridden values
    function populateVisualControlsFromElement(el, selector) {
      const computed = window.getComputedStyle(el);
      const activeOverrides = studioRules[selector] || {};
      // 1. Typography
      const fFam = activeOverrides['font-family'] || computed.fontFamily || "inherit";
      setControlValue("st-input-font-family", fFam);
      const selFam = document.getElementById("st-select-font-family");
      if (selFam) {
        let found = false;
        const cleanFFam = fFam.replace(/['"\s]/g, '').toLowerCase();
        for (let i = 0; i < selFam.options.length; i++) {
          const opt = selFam.options[i];
          if (opt.value !== 'custom' && (
            opt.value.replace(/['"\s]/g, '').toLowerCase() === cleanFFam ||
            cleanFFam.includes(opt.text.split(' ')[0].toLowerCase())
          )) {
            selFam.selectedIndex = i;
            found = true;
            break;
          }
        }
        if (!found) selFam.value = "custom";
      }
      const color = activeOverrides['color'] || rgbToHex(computed.color) || "#000000";
      setControlValue("st-prop-color-picker", rgbToHex(color));
      setControlValue("st-prop-color-hex", color);
      const fSize = activeOverrides['font-size'] || computed.fontSize || "14px";
      const fSizeNum = parseFloat(fSize) || 14;
      setControlValue("st-range-font-size", fSizeNum);
      setControlValue("st-input-font-size", fSize);
      setControlText("st-val-font-size", fSize);
      setControlValue("st-select-font-weight", activeOverrides['font-weight'] || computed.fontWeight || "normal");
      setControlValue("st-input-line-height", activeOverrides['line-height'] || (computed.lineHeight !== 'normal' ? computed.lineHeight : ''));
      setControlValue("st-select-text-align", activeOverrides['text-align'] || computed.textAlign || "inherit");
      setControlValue("st-select-text-transform", activeOverrides['text-transform'] || computed.textTransform || "none");
      setControlValue("st-input-letter-spacing", activeOverrides['letter-spacing'] || (computed.letterSpacing !== 'normal' ? computed.letterSpacing : ''));
      setControlValue("st-select-text-decoration", activeOverrides['text-decoration'] || computed.textDecorationLine || "none");
      // 2. Background
      const bg = activeOverrides['background-color'] || (computed.backgroundColor !== 'rgba(0, 0, 0, 0)' && computed.backgroundColor !== 'transparent' ? rgbToHex(computed.backgroundColor) : '#ffffff');
      setControlValue("st-prop-bg-picker", bg.startsWith('#') ? bg : '#ffffff');
      setControlValue("st-prop-bg-hex", activeOverrides['background-color'] || (computed.backgroundColor !== 'rgba(0, 0, 0, 0)' ? computed.backgroundColor : ''));
      setControlValue("st-input-bg-image", activeOverrides['background-image'] || (computed.backgroundImage !== 'none' ? computed.backgroundImage : ''));
      setControlValue("st-select-bg-size", activeOverrides['background-size'] || computed.backgroundSize || "auto");
      setControlValue("st-select-bg-repeat", activeOverrides['background-repeat'] || computed.backgroundRepeat || "no-repeat");
      setControlValue("st-range-opacity", activeOverrides['opacity'] || computed.opacity || "1");
      setControlValue("st-input-backdrop-blur", activeOverrides['backdrop-filter'] || (computed.backdropFilter !== 'none' ? computed.backdropFilter : ''));
      // 3. Borders & Radius
      const borderColor = activeOverrides['border-color'] || (computed.borderColor !== 'rgba(0, 0, 0, 0)' ? rgbToHex(computed.borderColor) : '#cbd5e1');
      setControlValue("st-prop-border-color-picker", borderColor.startsWith('#') ? borderColor : '#cbd5e1');
      setControlValue("st-prop-border-color-hex", activeOverrides['border-color'] || (computed.borderColor !== 'rgba(0, 0, 0, 0)' ? computed.borderColor : ''));
      const bWidth = activeOverrides['border-width'] || computed.borderWidth || "0px";
      const bWidthNum = parseFloat(bWidth) || 0;
      setControlValue("st-range-border-width", bWidthNum);
      setControlText("st-val-border-width", `${bWidthNum}px`);
      setControlValue("st-select-border-style", activeOverrides['border-style'] || (computed.borderStyle !== 'none' ? computed.borderStyle : 'solid'));
      const bRadius = activeOverrides['border-radius'] || computed.borderRadius || "0px";
      const bRadiusNum = parseFloat(bRadius) || 0;
      setControlValue("st-range-border-radius", bRadiusNum);
      setControlText("st-val-border-radius", `${bRadiusNum}px`);
      setControlValue("st-input-radius-tl", activeOverrides['border-top-left-radius'] || computed.borderTopLeftRadius || "");
      setControlValue("st-input-radius-tr", activeOverrides['border-top-right-radius'] || computed.borderTopRightRadius || "");
      setControlValue("st-input-radius-br", activeOverrides['border-bottom-right-radius'] || computed.borderBottomRightRadius || "");
      setControlValue("st-input-radius-bl", activeOverrides['border-bottom-left-radius'] || computed.borderBottomLeftRadius || "");
      // 4. Spacing Box Model
      setControlValue("st-box-mt", activeOverrides['margin-top'] || (computed.marginTop !== '0px' ? computed.marginTop : ''));
      setControlValue("st-box-mr", activeOverrides['margin-right'] || (computed.marginRight !== '0px' ? computed.marginRight : ''));
      setControlValue("st-box-mb", activeOverrides['margin-bottom'] || (computed.marginBottom !== '0px' ? computed.marginBottom : ''));
      setControlValue("st-box-ml", activeOverrides['margin-left'] || (computed.marginLeft !== '0px' ? computed.marginLeft : ''));
      setControlValue("st-box-pt", activeOverrides['padding-top'] || (computed.paddingTop !== '0px' ? computed.paddingTop : ''));
      setControlValue("st-box-pr", activeOverrides['padding-right'] || (computed.paddingRight !== '0px' ? computed.paddingRight : ''));
      setControlValue("st-box-pb", activeOverrides['padding-bottom'] || (computed.paddingBottom !== '0px' ? computed.paddingBottom : ''));
      setControlValue("st-box-pl", activeOverrides['padding-left'] || (computed.paddingLeft !== '0px' ? computed.paddingLeft : ''));
      setControlValue("st-input-width", activeOverrides['width'] || el.style.width || "");
      setControlValue("st-input-height", activeOverrides['height'] || el.style.height || "");
      setControlValue("st-input-min-width", activeOverrides['min-width'] || (computed.minWidth !== '0px' ? computed.minWidth : ''));
      setControlValue("st-input-max-width", activeOverrides['max-width'] || (computed.maxWidth !== 'none' ? computed.maxWidth : ''));
      // 5. Layout & Flex
      setControlValue("st-select-display", activeOverrides['display'] || computed.display || "inherit");
      setControlValue("st-select-position", activeOverrides['position'] || computed.position || "static");
      setControlValue("st-select-flex-direction", activeOverrides['flex-direction'] || computed.flexDirection || "row");
      setControlValue("st-input-gap", activeOverrides['gap'] || (computed.gap !== 'normal' ? computed.gap : ''));
      setControlValue("st-select-align-items", activeOverrides['align-items'] || computed.alignItems || "center");
      setControlValue("st-select-justify-content", activeOverrides['justify-content'] || computed.justifyContent || "flex-start");
      setControlValue("st-select-overflow", activeOverrides['overflow'] || computed.overflow || "visible");
      setControlValue("st-input-z-index", activeOverrides['z-index'] || (computed.zIndex !== 'auto' ? computed.zIndex : ''));
      // 6. Effects & Shadow
      setControlValue("st-input-box-shadow", activeOverrides['box-shadow'] || (computed.boxShadow !== 'none' ? computed.boxShadow : ''));
      setControlValue("st-select-cursor", activeOverrides['cursor'] || computed.cursor || "auto");
      setControlValue("st-input-transition", activeOverrides['transition'] || (computed.transition !== 'all 0s ease 0s' ? computed.transition : ''));
    }
    function setControlValue(id, val) {
      const el = document.getElementById(id);
      if (el) el.value = val || "";
    }
    function setControlText(id, text) {
      const el = document.getElementById(id);
      if (el) el.innerText = text || "";
    }
    // ==========================================
    // INSET-SCHATTEN (Mulde/Absenkung) — User-Wunsch 10.10.2026
    // Schaltet den aktuellen box-shadow des gewählten Elements zwischen
    // erhaben (Außen) und Mulde (inset) um. Bei Mehrfach-Schichten bekommt
    // jede Schicht ihr eigenes inset.
    // ==========================================
    function toggleShadowInset() {
      const inp = document.getElementById("st-input-box-shadow");
      if (!inp) return;
      const raw = (inp.value || "").trim();
      if (!raw || raw === "none") {
        // Kein Schatten gesetzt -> Standard-Mulde direkt anbieten
        const defaultInset = "inset 0 2px 6px rgba(0,0,0,0.2), inset 0 1px 2px rgba(0,0,0,0.15)";
        inp.value = defaultInset;
        onStudioPropChange("box-shadow", defaultInset);
        return;
      }
      const layers = raw.split(",").map(l => l.trim()).filter(Boolean);
      const isInset = layers.every(l => l.startsWith("inset")) || layers.some(l => l.startsWith("inset"));
      let next;
      if (isInset) {
        // Mulde -> erhaben: alle inset-Präfixe entfernen
        next = layers.map(l => l.replace(/^inset\s+/i, "")).join(", ");
      } else {
        // erhaben -> Mulde: jede Schicht mit inset versehen
        next = layers.map(l => l.startsWith("inset") ? l : "inset " + l).join(", ");
      }
      inp.value = next;
      onStudioPropChange("box-shadow", next);
    }
    window.toggleShadowInset = toggleShadowInset;
    // ==========================================
    // HINTERGRUND-BILD-UPLOAD (User-Wunsch 10.10.2026: JPG statt Füllung)
    // Lädt ein lokales Bild über /api/studio/upload-bg hoch und setzt es
    // sofort als background-image des gewählten Elements.
    // ==========================================
    async function onStudioBgFileChosen(inputEl) {
      const status = document.getElementById("st-bg-upload-status");
      const file = inputEl && inputEl.files && inputEl.files[0];
      if (!file) return;
      try {
        if (status) { status.classList.remove("hidden", "text-emerald-400", "text-rose-400"); status.classList.add("text-zinc-400"); status.textContent = "⏳ Lade hoch…"; }
        const fd = new FormData();
        fd.append("file", file);
        const res = await fetch("/api/studio/upload-bg", { method: "POST", body: fd });
        const data = await res.json();
        if (!res.ok || data.status !== "success") {
          throw new Error(data.detail || `HTTP ${res.status}`);
        }
        const cssVal = `url("${data.url}")`;
        const inp = document.getElementById("st-input-bg-image");
        if (inp) inp.value = cssVal;
        // 11.10.2026 FIX (User-Fall "nur Laden, Entfernen nichts"): ohne
        // vorherige Element-Wahl brach onStudioPropChange mit Alert ab -
        // Status log "✓ gesetzt", aber ES KAM KEINE REGEL (Schein-Erfolg).
        // Hintergrund-Upload bekommt jetzt body als Standardziel.
        let bgZielHinweis = "";
        if (!studioSelectedSelector) {
          studioSelectedSelector = "body";
          studioSelectedElement = document.body;
          bgZielHinweis = cssT("ui.css_live_studio.bg_target_hint", " (Ziel: body - kein Element zuvor gewählt)");
        }
        onStudioPropChange("background-image", cssVal);
        // Sinnvolle Defaults für ein Vollflächen-Hintergrundbild
        const selSize = document.getElementById("st-select-bg-size");
        const selRepeat = document.getElementById("st-select-bg-repeat");
        if (selSize && !selSize.value.includes("cover")) { selSize.value = "cover"; onStudioPropChange("background-size", "cover"); }
        if (selRepeat && selRepeat.value !== "no-repeat") { selRepeat.value = "no-repeat"; onStudioPropChange("background-repeat", "no-repeat"); }
        if (status) {
          status.classList.remove("hidden", "text-zinc-400", "text-rose-400");
          status.classList.add("text-emerald-400");
          status.textContent = `✓ ${data.filename} (${Math.round((data.size || 0) / 1024)} KB) als Hintergrund gesetzt${bgZielHinweis}`;
        }
      } catch (err) {
        if (status) {
          status.classList.remove("hidden", "text-zinc-400", "text-emerald-400");
          status.classList.add("text-rose-400");
          status.textContent = `⚠ Upload fehlgeschlagen: ${err.message}`;
        }
        console.error("[CSS Studio] BG-Upload error:", err);
      } finally {
        inputEl.value = "";
      }
    }
    window.onStudioBgFileChosen = onStudioBgFileChosen;
    // ==========================================
    // HINTERGRUND-BILD ENTFERNEN (User-Wunsch 10.10.2026: Gegenstück zum Upload)
    // Entfernt background-image (+ die vom Upload erzwungenen Begleit-Defaults
    // cover/no-repeat) aus ALLEN Studio-Regeln, aktualisiert den Runtime-Tag
    // und speichert (localStorage + Server + kompilierte Datei) dauerhaft.
    // ==========================================
    function removeStudioBackground() {
      const status = document.getElementById("st-bg-remove-status");
      let removed = 0;
      const rules = studioRules || {};
      for (const [sel, props] of Object.entries(rules)) {
        if (props && props["background-image"]) {
          delete props["background-image"];
          // Nur die Begleit-Werte zurücksetzen, die der Upload-Flow selbst erzwungen hat
          if (props["background-size"] === "cover" || props["background-size"] === "contain") delete props["background-size"];
          if (props["background-repeat"] === "no-repeat") delete props["background-repeat"];
          removed++;
          if (Object.keys(props).length === 0) delete rules[sel];
        }
      }
      studioRules = rules;
      // c) Das Studio schreibt Regeln zusätzlich INLINE (!important) auf das
      // Ziel-Element — auch aufräumen, wenn die Regel längst aus dem Store ist
      // (sonst überlebt das Bild jeden Reset, so wie beim User-Fall).
      let inlineCleared = 0;
      // WICHTIG: "body, body *" — der body selbst wird sonst NICHT erfasst
      // (dort hängt das Hintergrundbild im User-Fall!).
      document.querySelectorAll("body, body *").forEach(el => {
        if (!el.style || !el.style.backgroundImage) return;
        if (!/url\(/.test(el.style.backgroundImage)) return;
        el.style.removeProperty("background-image");
        if (el.style.backgroundSize === "cover" || el.style.backgroundSize === "contain") el.style.removeProperty("background-size");
        if (el.style.backgroundRepeat === "no-repeat") el.style.removeProperty("background-repeat");
        inlineCleared++;
      });
      // Eingabefelder auf Leerzustand zurücksetzen
      const inp = document.getElementById("st-input-bg-image");
      if (inp) inp.value = "";
      const selSize = document.getElementById("st-select-bg-size");
      if (selSize) selSize.value = "auto";
      const selRepeat = document.getElementById("st-select-bg-repeat");
      if (selRepeat) selRepeat.value = "repeat";
      // QUELLE 3: Design-Reiter/CSS-Editor ('archon_custom_user_css') -
      // eigenes Speicher-System, NICHT von saveStudioOverrides erfasst
      // (User-Fall 11.10: Bild dort - Remove wirkte nicht, Speichern half
      // nicht, F5 liess es via initCustomCSS zurueckkehren).
      let customCssCleared = 0;
      try {
        const ckey = "archon_custom_user_css";
        const ccss = localStorage.getItem(ckey) || "";
        if (ccss && /background-image\s*:/i.test(ccss)) {
          const neu = ccss.replace(/background-image\s*:\s*url\([^)]*\)\s*;?/gi, " ");
          if (neu !== ccss) {
            customCssCleared = (ccss.match(/background-image\s*:/gi) || []).length;
            localStorage.setItem(ckey, neu);
            try { if (typeof initCustomCSS === "function") initCustomCSS(); } catch (e2) {}
            const taCss = document.getElementById("custom-user-css");
            if (taCss && taCss !== document.activeElement) taCss.value = neu;
          }
        }
      } catch (e3) { console.warn("[CSS Studio] custom_user_css cleanup:", e3); }
      // 1. Runtime-Tag sofort aktualisieren, 2. dauerhaft speichern (stumm)
      try { applyStudioRulesToDOM(); } catch (e) { console.warn("[CSS Studio] apply failed:", e); }
      if (typeof saveStudioOverrides === "function") saveStudioOverrides(true);
      if (typeof updateStudioActiveRulesCounters === "function") updateStudioActiveRulesCounters();
      if (status) {
        status.classList.remove("hidden", "text-rose-400", "text-zinc-400");
        status.classList.add((removed || inlineCleared || customCssCleared) ? "text-emerald-400" : "text-zinc-400");
        status.textContent = (removed || inlineCleared || customCssCleared)
          ? `✓ Hintergrundbild entfernt (${removed} Studio-Regel(n) + ${inlineCleared} Inline-Style(s) + ${customCssCleared} Design-Editor-Regel(n) bereinigt, dauerhaft gespeichert)`
          : "Kein Hintergrundbild gefunden - weder in Studio-Regeln, Inline-Styles noch im Design-Editor-CSS";
      }
      return removed + inlineCleared;
    }
    window.removeStudioBackground = removeStudioBackground;
    // ==========================================
    // APPLY PROPERTY LIVE & RECOMPILE STYLESHEET
    // ==========================================
    function onStudioPropChange(property, value) {
      if (!studioSelectedSelector) {
        alert(cssT("ui.css_live_studio.alert_no_target", "Bitte wähle zuerst ein CSS-Ziel aus oder klicke oben auf '🎯 Element Auswählen'!"));
        return;
      }
      if (!studioRules[studioSelectedSelector]) {
        studioRules[studioSelectedSelector] = {};
      }
      // 'url("")' / leere url() = manuelles Leeren im Feld = LOESCHEN
      const isEmptyUrl = typeof value === 'string' && /^url\(\s*["']?\s*["']?\s*\)$/.test(String(value).trim());
      if (!value || value === 'none' || value === 'inherit' || isEmptyUrl || (value === 'auto' && property === 'width')) {
        if (value === '' || isEmptyUrl) {
          delete studioRules[studioSelectedSelector][property];
          if (Object.keys(studioRules[studioSelectedSelector]).length === 0) {
            delete studioRules[studioSelectedSelector];
          }
        } else {
          studioRules[studioSelectedSelector][property] = value;
        }
      } else {
        studioRules[studioSelectedSelector][property] = value;
      }
      // Direct DOM Sync to selected element
      if (studioSelectedElement && studioSelectedElement instanceof HTMLElement) {
        if (value && value !== 'none' && value !== 'inherit' && !isEmptyUrl) {
          const cleanV = String(value).replace('!important', '').trim();
          studioSelectedElement.style.setProperty(property, cleanV, 'important');
        } else if (value === '' || value === 'none' || isEmptyUrl) {
          studioSelectedElement.style.removeProperty(property);
        }
      }
      // Sync dual controls
      if (property === 'font-family') {
        ensureGoogleFontLoaded(value);
        const inpFam = document.getElementById("st-input-font-family");
        if (inpFam && inpFam !== document.activeElement) inpFam.value = value;
      }
      if (property === 'color') {
        const hexInput = document.getElementById("st-prop-color-hex");
        const picker = document.getElementById("st-prop-color-picker");
        if (hexInput && hexInput !== document.activeElement) hexInput.value = value;
        if (picker && value.startsWith('#')) picker.value = value;
      }
      if (property === 'background-color') {
        const hexInput = document.getElementById("st-prop-bg-hex");
        const picker = document.getElementById("st-prop-bg-picker");
        if (hexInput && hexInput !== document.activeElement) hexInput.value = value;
        if (picker && value.startsWith('#')) picker.value = value;
      }
      if (property === 'border-color') {
        const hexInput = document.getElementById("st-prop-border-color-hex");
        const picker = document.getElementById("st-prop-border-color-picker");
        if (hexInput && hexInput !== document.activeElement) hexInput.value = value;
        if (picker && value.startsWith('#')) picker.value = value;
      }
      if (property === 'font-size') {
        setControlText("st-val-font-size", value);
        const range = document.getElementById("st-range-font-size");
        const input = document.getElementById("st-input-font-size");
        if (range && range !== document.activeElement) range.value = parseFloat(value) || 14;
        if (input && input !== document.activeElement) input.value = value;
      }
      if (property === 'border-width') {
        setControlText("st-val-border-width", value);
        const range = document.getElementById("st-range-border-width");
        if (range && range !== document.activeElement) range.value = parseFloat(value) || 0;
      }
      if (property === 'border-radius') {
        setControlText("st-val-border-radius", value);
        const range = document.getElementById("st-range-border-radius");
        if (range && range !== document.activeElement) range.value = parseFloat(value) || 0;
      }
      applyStudioRulesToDOM();
      updateStudioActiveRulesCounters();
      updateStudioGizmoPosition();
      debounceAutoSave();
    }
    function addCustomStudioProp() {
      const nameInput = document.getElementById("st-custom-prop-name");
      const valInput = document.getElementById("st-custom-prop-val");
      if (!nameInput || !valInput) return;
      const prop = nameInput.value.trim().toLowerCase();
      const val = valInput.value.trim();
      if (!prop || !val) {
        alert(cssT("ui.css_live_studio.alert_prop_and_value", "Bitte gib sowohl einen CSS-Eigenschaftsnamen als auch einen Wert ein!"));
        return;
      }
      onStudioPropChange(prop, val);
      nameInput.value = "";
      valInput.value = "";
    }
    // Compile studioRules object into CSS String and inject into style tag
    function applyStudioRulesToDOM() {
      let styleTag = document.getElementById("archon-live-custom-styles");
      if (!styleTag) {
        styleTag = document.createElement("style");
        styleTag.id = "archon-live-custom-styles";
        document.head.appendChild(styleTag);
      }
      let cssText = "/* Archon CSS Live Studio Overrides */\n";
      for (const [sel, props] of Object.entries(studioRules)) {
        if (!props || Object.keys(props).length === 0) continue;
        cssText += `${sel} {\n`;
        for (const [p, v] of Object.entries(props)) {
          if (v !== undefined && v !== "") {
            const hasImportant = String(v).includes("!important");
            cssText += `  ${p}: ${v}${hasImportant ? '' : ' !important'};\n`;
          }
        }
        cssText += `}\n\n`;
        // Direct DOM sync on all matching elements
        try {
          const matchedEls = document.querySelectorAll(sel);
          matchedEls.forEach(el => {
            if (el instanceof HTMLElement) {
              for (const [p, v] of Object.entries(props)) {
                if (v !== undefined && v !== "" && v !== 'none' && v !== 'inherit') {
                  const cleanVal = String(v).replace('!important', '').trim();
                  el.style.setProperty(p, cleanVal, 'important');
                }
              }
            }
          });
        } catch (e) {}
      }
      styleTag.innerHTML = cssText;
      const rawEditor = document.getElementById("studio-raw-css-editor");
      if (rawEditor && rawEditor !== document.activeElement) {
        rawEditor.value = cssText;
      }
    }
    function updateStudioActiveRulesCounters() {
      let count = 0;
      for (const [sel, props] of Object.entries(studioRules)) {
        count += Object.keys(props).length;
      }
      const countBadge = document.getElementById("studio-active-rules-count");
      const minBadge = document.getElementById("studio-min-badge");
      if (countBadge) {
        countBadge.innerText = `${count} aktive ${count === 1 ? 'Regel' : 'Regeln'}`;
        countBadge.title = `${count} aktive CSS-Regeln auf dem Server gespeichert`;
      }
      if (minBadge) minBadge.innerText = count;
      const textCountBadge = document.getElementById("studio-text-count");
      if (textCountBadge) textCountBadge.innerText = Object.keys(studioTextOverrides).length;
    }
    // ==========================================
    // TAB 2: ACTIVE RULES LIST VIEW
    // ==========================================
    function renderStudioRulesList() {
      const container = document.getElementById("studio-rules-list-container");
      if (!container) return;
      const selectors = Object.keys(studioRules);
      if (selectors.length === 0) {
        container.innerHTML = `<div class="text-slate-500 text-center py-6 text-xs">${cssT("ui.css_live_studio.rules_empty", "Noch keine CSS-Regeln definiert. Wähle ein Element im Visual Builder aus.")}</div>`;
        return;
      }
      let html = "";
      selectors.forEach(sel => {
        const props = studioRules[sel] || {};
        const propKeys = Object.keys(props);
        if (propKeys.length === 0) return;
        html += `
          <div class="bg-slate-900 border border-slate-800 rounded-xl p-2.5 space-y-2">
            <div class="flex items-center justify-between">
              <span class="text-amber-300 font-bold text-xs truncate max-w-[280px]" title="${sel}">${sel}</span>
              <div class="flex items-center gap-1">
                <button type="button" onclick="selectStudioRule('${sel}')" class="px-2 py-0.5 rounded bg-indigo-600/30 hover:bg-indigo-600 text-indigo-300 hover:text-white text-[10px] cursor-pointer">${cssT("ui.css_live_studio.btn_edit", "Bearbeiten")}</button>
                <button type="button" onclick="deleteStudioSelectorRule('${sel}')" class="px-2 py-0.5 rounded bg-rose-900/30 hover:bg-rose-900 text-rose-300 text-[10px] cursor-pointer">${cssT("ui.css_live_studio.btn_delete", "Löschen")}</button>
              </div>
            </div>
            <div class="bg-slate-950 p-2 rounded-lg text-[11px] text-slate-300 space-y-1">
        `;
        propKeys.forEach(p => {
          html += `
            <div class="flex items-center justify-between">
              <span class="text-slate-400">${p}:</span>
              <span class="text-emerald-400 font-bold">${props[p]}</span>
            </div>
          `;
        });
        html += `</div></div>`;
      });
      container.innerHTML = html;
    }
    function selectStudioRule(sel) {
      setStudioTab('visual');
      const input = document.getElementById("studio-target-selector");
      if (input) input.value = sel;
      onStudioSelectorInputChange(sel);
    }
    function deleteStudioSelectorRule(sel) {
      const oldProps = studioRules[sel];
      if (oldProps) {
        try {
          const els = document.querySelectorAll(sel);
          els.forEach(el => {
            if (el instanceof HTMLElement) {
              for (const p of Object.keys(oldProps)) {
                el.style.removeProperty(p);
              }
            }
          });
        } catch (e) {}
      }
      delete studioRules[sel];
      applyStudioRulesToDOM();
      updateStudioActiveRulesCounters();
      renderStudioRulesList();
      debounceAutoSave();
    }
    // ==========================================
    // TAB 3: RAW CSS CODE EDITOR
    // ==========================================
    function renderStudioRawCss() {
      const rawEditor = document.getElementById("studio-raw-css-editor");
      const styleTag = document.getElementById("archon-live-custom-styles");
      if (rawEditor && styleTag) {
        rawEditor.value = styleTag.innerHTML;
      }
    }
    function onStudioRawCssInput(rawCss) {
      let styleTag = document.getElementById("archon-live-custom-styles");
      if (styleTag) {
        styleTag.innerHTML = rawCss;
      }
      debounceAutoSave();
    }
    function copyStudioCss() {
      const styleTag = document.getElementById("archon-live-custom-styles");
      const cssText = styleTag ? styleTag.innerHTML : "";
      if (navigator.clipboard) {
        navigator.clipboard.writeText(cssText);
        alert(cssT("ui.css_live_studio.copy_success", "✅ CSS-Regeln erfolgreich in die Zwischenablage kopiert!"));
      }
    }
    function exportStudioCss() {
      const styleTag = document.getElementById("archon-live-custom-styles");
      const cssText = styleTag ? styleTag.innerHTML : "/* Archon CSS Live Studio */";
      const blob = new Blob([cssText], { type: "text/css" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "archon-custom-theme.css";
      a.click();
      URL.revokeObjectURL(url);
    }
    // ==========================================
    // TAB 4 & IN-PLACE TEXT EDITING MODE
    // ==========================================
    function toggleStudioTextMode() {
      if (isStudioTextModeActive) {
        disableStudioTextMode();
      } else {
        enableStudioTextMode();
      }
    }
    function enableStudioTextMode() {
      isStudioTextModeActive = true;
      const btn = document.getElementById("btn-studio-text-mode");
      if (btn) {
        btn.classList.add("bg-amber-600", "text-slate-950", "animate-pulse");
      }
      const selector = "h1, h2, h3, h4, h5, h6, label, p, span, button, a, th, td";
      document.querySelectorAll(selector).forEach(el => {
        if (el.closest("#archon-css-studio") || el.closest("#archon-css-studio-minimized") || el.closest("script") || el.closest("style") || el.closest("input") || el.closest("textarea")) {
          return;
        }
        const directText = Array.from(el.childNodes)
          .filter(n => n.nodeType === Node.TEXT_NODE)
          .map(n => n.textContent.trim())
          .filter(t => t.length > 0)
          .join(" ");
        if (directText.length > 0) {
          if (!el.dataset.origText) el.dataset.origText = directText;
          el.setAttribute("contenteditable", "true");
          el.setAttribute("spellcheck", "false");
          el.classList.add("hover:outline", "hover:outline-1", "hover:outline-amber-400");
          el.addEventListener("input", onStudioTextElementInput);
        }
      });
    }
    function disableStudioTextMode() {
      isStudioTextModeActive = false;
      const btn = document.getElementById("btn-studio-text-mode");
      if (btn) {
        btn.classList.remove("bg-amber-600", "text-slate-950", "animate-pulse");
      }
      document.querySelectorAll("[contenteditable='true']").forEach(el => {
        if (!el.closest("#archon-css-studio")) {
          el.removeAttribute("contenteditable");
          el.removeAttribute("spellcheck");
          el.classList.remove("hover:outline", "hover:outline-1", "hover:outline-amber-400");
        }
      });
    }
    function onStudioTextElementInput(e) {
      const el = e.currentTarget;
      const orig = el.dataset.origText;
      const current = Array.from(el.childNodes)
        .filter(n => n.nodeType === Node.TEXT_NODE)
        .map(n => n.textContent.trim())
        .filter(t => t.length > 0)
        .join(" ");
      if (orig && current && orig !== current) {
        studioTextOverrides[orig] = current;
      } else if (orig && orig === current) {
        delete studioTextOverrides[orig];
      }
      updateStudioActiveRulesCounters();
      debounceAutoSave();
    }
    function applyStudioTextOverridesToDOM() {
      if (Object.keys(studioTextOverrides).length === 0) return;
      const selector = "h1, h2, h3, h4, h5, h6, label, p, span, button, a, th, td";
      document.querySelectorAll(selector).forEach(el => {
        if (el.closest("#archon-css-studio") || el.closest("#archon-css-studio-minimized")) return;
        Array.from(el.childNodes).forEach(n => {
          if (n.nodeType === Node.TEXT_NODE) {
            const txt = n.textContent.trim();
            if (studioTextOverrides[txt]) {
              n.textContent = studioTextOverrides[txt];
            }
          }
        });
      });
    }
    function renderStudioTextsList() {
      const container = document.getElementById("studio-texts-list-container");
      if (!container) return;
      const keys = Object.keys(studioTextOverrides);
      if (keys.length === 0) {
        container.innerHTML = `<div class="text-slate-500 text-center py-6 text-xs">${cssT("ui.css_live_studio.texts_empty", "Noch keine Texte verändert. Aktiviere oben „✏️ Text-Modus“.")}</div>`;
        return;
      }
      let html = "";
      keys.forEach(orig => {
        const val = studioTextOverrides[orig];
        html += `
          <div class="bg-slate-900 border border-slate-800 rounded-xl p-2 flex items-center justify-between gap-2">
            <div class="min-w-0 flex-1 font-mono text-[11px]">
              <span class="text-slate-500 line-through truncate block">${orig}</span>
              <span class="text-emerald-400 font-bold truncate block">➔ ${val}</span>
            </div>
            <button type="button" onclick="removeStudioTextOverride('${orig.replace(/'/g, "\\'")}')" class="px-2 py-1 rounded bg-rose-900/30 hover:bg-rose-900 text-rose-300 text-[10px] cursor-pointer shrink-0">Reset</button>
          </div>
        `;
      });
      container.innerHTML = html;
    }
    function removeStudioTextOverride(orig) {
      delete studioTextOverrides[orig];
      updateStudioActiveRulesCounters();
      renderStudioTextsList();
      debounceAutoSave();
    }
    function clearAllStudioTextOverrides() {
      studioTextOverrides = {};
      updateStudioActiveRulesCounters();
      renderStudioTextsList();
      debounceAutoSave();
    }
    // ==========================================
    // TAB 5: SYMBOLS, ICONS & HTML-OVERRIDES
    // ==========================================
    function updateStudioQuickActionButtons() {
      const hideBtn = document.getElementById("btn-studio-quick-hide");
      const hideLbl = document.getElementById("lbl-studio-quick-hide");
      const symBadge = document.getElementById("studio-symbols-vis-badge");
      const symHideBtn = document.getElementById("btn-studio-symbols-hide-toggle");
      const symHideLbl = document.getElementById("lbl-studio-symbols-hide");
      const htmlEditor = document.getElementById("studio-selected-html-editor");

      if (!studioSelectedElement) {
        if (hideLbl) hideLbl.innerText = "🚫 Ausblenden";
        if (htmlEditor) htmlEditor.value = "";
        return;
      }

      const isHidden = (studioRules[studioSelectedSelector] && studioRules[studioSelectedSelector]["display"] === "none !important") ||
                       (studioSelectedElement.style.display === "none") ||
                       (window.getComputedStyle(studioSelectedElement).display === "none");

      if (hideBtn && hideLbl) {
        if (isHidden) {
          hideBtn.className = "flex-1 py-1 px-2 rounded-lg bg-emerald-950/80 hover:bg-emerald-900 border border-emerald-800/80 text-emerald-300 font-mono text-[11px] font-bold transition flex items-center justify-center gap-1 cursor-pointer shadow-xs";
          hideBtn.innerHTML = `<i data-lucide="eye" class="w-3.5 h-3.5 text-emerald-400"></i><span id="lbl-studio-quick-hide">👁️ Einblenden</span>`;
        } else {
          hideBtn.className = "flex-1 py-1 px-2 rounded-lg bg-rose-950/80 hover:bg-rose-900 border border-rose-800/80 text-rose-300 font-mono text-[11px] font-bold transition flex items-center justify-center gap-1 cursor-pointer shadow-xs";
          hideBtn.innerHTML = `<i data-lucide="eye-off" class="w-3.5 h-3.5 text-rose-400"></i><span id="lbl-studio-quick-hide">🚫 Ausblenden</span>`;
        }
      }

      if (symBadge) {
        symBadge.className = isHidden 
          ? "px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-rose-950 text-rose-400 border border-rose-800"
          : "px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-emerald-950 text-emerald-400 border border-emerald-800";
        symBadge.innerText = isHidden ? "Ausgeblendet" : "Sichtbar";
      }

      if (symHideBtn && symHideLbl) {
        if (isHidden) {
          symHideBtn.className = "w-full py-2 px-3 rounded-lg bg-emerald-950/70 hover:bg-emerald-900 border border-emerald-800 text-emerald-300 font-bold text-xs transition flex items-center justify-center gap-2 cursor-pointer shadow-xs";
          symHideBtn.innerHTML = `<i data-lucide="eye" class="w-4 h-4"></i><span id="lbl-studio-symbols-hide">Element wieder einblenden (display: initial)</span>`;
        } else {
          symHideBtn.className = "w-full py-2 px-3 rounded-lg bg-rose-950/70 hover:bg-rose-900 border border-rose-800 text-rose-300 font-bold text-xs transition flex items-center justify-center gap-2 cursor-pointer shadow-xs";
          symHideBtn.innerHTML = `<i data-lucide="trash-2" class="w-4 h-4"></i><span id="lbl-studio-symbols-hide">Element ausblenden / entfernen (display: none)</span>`;
        }
      }

      if (htmlEditor && studioSelectedElement) {
        htmlEditor.value = studioSelectedElement.innerHTML || "";
      }
      if (window.lucide) {
        try { window.lucide.createIcons(); } catch (e) {}
      }
    }

    function toggleStudioElementHide() {
      if (!studioSelectedSelector) {
        alert(cssT("ui.css_live_studio.alert_no_element", "Bitte wähle zuerst ein Element mit dem Inspektor aus!"));
        return;
      }
      if (!studioRules[studioSelectedSelector]) {
        studioRules[studioSelectedSelector] = {};
      }
      const isCurrentlyHidden = studioRules[studioSelectedSelector]["display"] === "none !important";
      if (isCurrentlyHidden) {
        delete studioRules[studioSelectedSelector]["display"];
        if (Object.keys(studioRules[studioSelectedSelector]).length === 0) {
          delete studioRules[studioSelectedSelector];
        }
        if (studioSelectedElement && studioSelectedElement instanceof HTMLElement) {
          studioSelectedElement.style.removeProperty("display");
        }
        if (typeof showArchonToast === "function") {
          showArchonToast(cssT("ui.css_live_studio.element_shown", "Element '{selector}' wieder eingeblendet.", { selector: studioSelectedSelector }), "success");
        }
      } else {
        studioRules[studioSelectedSelector]["display"] = "none !important";
        if (studioSelectedElement && studioSelectedElement instanceof HTMLElement) {
          studioSelectedElement.style.setProperty("display", "none", "important");
        }
        if (typeof showArchonToast === "function") {
          showArchonToast(cssT("ui.css_live_studio.element_hidden", "Element '{selector}' ausgeblendet.", { selector: studioSelectedSelector }), "info");
        }
      }
      applyStudioRulesToDOM();
      updateStudioQuickActionButtons();
      updateStudioActiveRulesCounters();
      renderStudioHiddenElementsList();
      debounceAutoSave();
    }

    function toggleStudioAnimationStop() {
      if (!studioSelectedSelector) return;
      if (!studioRules[studioSelectedSelector]) studioRules[studioSelectedSelector] = {};
      studioRules[studioSelectedSelector]["animation"] = "none !important";
      if (studioSelectedElement && studioSelectedElement instanceof HTMLElement) {
        studioSelectedElement.classList.remove("animate-pulse", "animate-ping", "animate-spin", "animate-bounce");
        studioSelectedElement.style.setProperty("animation", "none", "important");
      }
      applyStudioRulesToDOM();
      debounceAutoSave();
      if (typeof showArchonToast === "function") {
        showArchonToast(cssT("ui.css_live_studio.anim_stopped", "Animationen für '{selector}' gestoppt.", { selector: studioSelectedSelector }), "info");
      }
    }

    // Nur diese Familien liegen lokal unter static/vendor/fonts/fonts.css.
    // Kein Google-Fonts-Nachladen mehr -> Studio ist offline- und DSGVO-fest.
    const LOCAL_FONT_FAMILIES = [
      'inter', 'outfit', 'julius sans one', 'jetbrains mono', 'playfair display',
      'montserrat', 'fira code', 'cinzel', 'space grotesk', 'plus jakarta sans'
    ];

    function ensureGoogleFontLoaded(fontFamily) {
      if (!fontFamily || fontFamily === 'inherit' || fontFamily === 'none') return;
      const match = fontFamily.match(/["']?([^,"']+)["']?/);
      if (!match) return;
      const name = match[1].trim();
      const key = name.toLowerCase();
      if (LOCAL_FONT_FAMILIES.includes(key)) return;
      const known = ['sans-serif', 'serif', 'monospace', 'system-ui', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'Arial', 'Georgia', 'inherit'];
      if (known.includes(key)) return;
      if (typeof showArchonToast === 'function') {
        showArchonToast(cssT("ui.css_live_studio.font_not_local", "Schrift '{font}' ist nicht lokal verfügbar. Bitte eine der 10 Studio-Schriften wählen.", { font: name }), "info");
      }
    }

    function onStudioFontFamilySelect(val) {
      const inpFam = document.getElementById("st-input-font-family");
      if (val === 'custom') {
        if (inpFam) {
          inpFam.focus();
          inpFam.select();
        }
        return;
      }
      if (inpFam) inpFam.value = val;
      onStudioPropChange('font-family', val);
    }

    function applyStudioGlobalFont(fontFamily) {
      if (!fontFamily || fontFamily === 'inherit') {
        alert(cssT("ui.css_live_studio.alert_no_font", "Bitte wähle zuerst eine konkrete Schriftart aus!"));
        return;
      }
      ensureGoogleFontLoaded(fontFamily);
      // 1. Setze CSS Custom Property auf HTML Root
      document.documentElement.style.setProperty('--font-family', fontFamily);
      // 2. Schreibe Rule in studioRules für body und :root
      if (!studioRules['body']) studioRules['body'] = {};
      studioRules['body']['font-family'] = `${fontFamily} !important`;
      
      applyStudioRulesToDOM();
      updateStudioActiveRulesCounters();
      debounceAutoSave();
      
      if (typeof showArchonToast === "function") {
        showArchonToast(cssT("ui.css_live_studio.global_font_set", "Globale Schriftart dauerhaft auf '{font}' umgestellt!", { font: fontFamily }), "success");
      } else {
        alert(cssT("ui.css_live_studio.global_font_set_alert", "Globale Schriftart erfolgreich auf '{font}' umgestellt!", { font: fontFamily }));
      }
    }

    function applyStudioSymbolPreset(type, iconName = '') {
      if (!studioSelectedSelector || !studioSelectedElement) {
        alert(cssT("ui.css_live_studio.alert_no_element", "Bitte wähle zuerst ein Element mit dem Inspektor aus!"));
        return;
      }
      let newHtml = '';
      if (type === 'none') {
        newHtml = '';
      } else if (type === 'dot') {
        newHtml = '<span class="inline-block w-2 h-2 rounded-full bg-slate-400"></span>';
      } else if (type === 'pulse_dot') {
        const col = iconName || 'emerald-500';
        newHtml = `<span class="inline-block w-2.5 h-2.5 rounded-full bg-${col} animate-pulse"></span>`;
      } else if (type === 'ping_dot') {
        const col = iconName || 'emerald-500';
        newHtml = `<span class="relative flex h-2.5 w-2.5 inline-block"><span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-${col} opacity-75"></span><span class="relative inline-flex rounded-full h-2.5 w-2.5 bg-${col}"></span></span>`;
      } else if (type === 'lucide' && iconName) {
        newHtml = `<i data-lucide="${iconName}" class="w-4 h-4"></i>`;
      }
      setStudioElementHtml(newHtml);
    }

    function setStudioElementHtml(newHtml) {
      if (!studioSelectedSelector || !studioSelectedElement) {
        alert(cssT("ui.css_live_studio.alert_pick_element", "Bitte wähle zuerst ein Element aus!"));
        return;
      }
      studioSelectedElement.innerHTML = newHtml;
      if (!studioHtmlOverrides) studioHtmlOverrides = {};
      studioHtmlOverrides[studioSelectedSelector] = newHtml;
      localStorage.setItem("archon_theme_html_overrides", JSON.stringify(studioHtmlOverrides));
      const htmlEditor = document.getElementById("studio-selected-html-editor");
      if (htmlEditor) htmlEditor.value = newHtml;
      if (window.lucide) {
        try { window.lucide.createIcons(); } catch (e) {}
      }
      if (typeof showArchonToast === "function") {
        showArchonToast(cssT("ui.css_live_studio.html_updated", "HTML für '{selector}' aktualisiert.", { selector: studioSelectedSelector }), "success");
      }
      debounceAutoSave();
    }

    function resetStudioElementHtml() {
      if (!studioSelectedSelector) return;
      if (studioHtmlOverrides && studioHtmlOverrides[studioSelectedSelector]) {
        delete studioHtmlOverrides[studioSelectedSelector];
        localStorage.setItem("archon_theme_html_overrides", JSON.stringify(studioHtmlOverrides));
      }
      if (typeof showArchonToast === "function") {
        showArchonToast(cssT("ui.css_live_studio.html_override_removed", "HTML-Override für '{selector}' entfernt.", { selector: studioSelectedSelector }), "info");
      }
    }

    function applyStudioHtmlOverridesToDOM() {
      if (!studioHtmlOverrides) return;
      for (const [sel, html] of Object.entries(studioHtmlOverrides)) {
        try {
          const targets = document.querySelectorAll(sel);
          targets.forEach(t => {
            t.innerHTML = html;
          });
        } catch (e) {}
      }
      if (window.lucide) {
        try { window.lucide.createIcons(); } catch (e) {}
      }
    }

    function renderStudioSymbolsTab() {
      updateStudioQuickActionButtons();
      renderStudioHiddenElementsList();
    }

    function renderStudioHiddenElementsList() {
      const container = document.getElementById("studio-hidden-elements-list");
      const countBadge = document.getElementById("studio-hidden-count");
      if (!container) return;

      const hiddenSelectors = Object.keys(studioRules).filter(sel => studioRules[sel] && studioRules[sel]["display"] === "none !important");
      if (countBadge) countBadge.innerText = hiddenSelectors.length;

      if (hiddenSelectors.length === 0) {
        container.innerHTML = `<div class="text-zinc-500 text-center py-4 text-[11px]">${cssT("ui.css_live_studio.hidden_empty", "Keine Elemente ausgeblendet.")}</div>`;
        return;
      }

      let html = "";
      hiddenSelectors.forEach(sel => {
        html += `
          <div class="flex items-center justify-between p-2 rounded-lg bg-zinc-950 border border-zinc-800">
            <span class="text-rose-300 text-[11px] truncate max-w-[240px]" title="${sel}">${sel}</span>
            <button type="button" onclick="unhideStudioElement('${sel.replace(/'/g, "\\'")}')" class="px-2 py-0.5 rounded bg-emerald-950 hover:bg-emerald-900 text-emerald-400 border border-emerald-800 text-[10px] font-bold cursor-pointer">
              ${cssT("ui.css_live_studio.btn_restore", "Wiederherstellen")}
            </button>
          </div>
        `;
      });
      container.innerHTML = html;
    }

    function unhideStudioElement(sel) {
      if (studioRules[sel]) {
        delete studioRules[sel]["display"];
        if (Object.keys(studioRules[sel]).length === 0) {
          delete studioRules[sel];
        }
      }
      try {
        const targets = document.querySelectorAll(sel);
        targets.forEach(t => {
          if (t instanceof HTMLElement) t.style.removeProperty("display");
        });
      } catch (e) {}
      applyStudioRulesToDOM();
      updateStudioActiveRulesCounters();
      updateStudioQuickActionButtons();
      renderStudioHiddenElementsList();
      debounceAutoSave();
      if (typeof showArchonToast === "function") {
        showArchonToast(cssT("ui.css_live_studio.element_shown", "Element '{selector}' wieder eingeblendet.", { selector: sel }), "success");
      }
    }

    // ==========================================
    // PERSISTENCE & RESET ACTIONS
    // ==========================================
    function debounceAutoSave() {
      if (studioSaveTimeout) clearTimeout(studioSaveTimeout);
      studioSaveTimeout = setTimeout(() => {
        localStorage.setItem("archon_theme_live_overrides", JSON.stringify({
          rules: studioRules,
          textOverrides: studioTextOverrides
        }));
        localStorage.setItem("archon_theme_html_overrides", JSON.stringify(studioHtmlOverrides));
        saveStudioOverrides(true);
      }, 800);
    }
    let activeSaveAbortController = null;

    async function saveStudioOverrides(silent = false) {
      if (activeSaveAbortController) {
        activeSaveAbortController.abort();
      }
      activeSaveAbortController = new AbortController();
      const signal = activeSaveAbortController.signal;

      const payload = {
        rules: studioRules,
        textOverrides: studioTextOverrides,
        htmlOverrides: studioHtmlOverrides
      };
      localStorage.setItem("archon_theme_live_overrides", JSON.stringify(payload));
      localStorage.setItem("archon_theme_html_overrides", JSON.stringify(studioHtmlOverrides));
      try {
        const res = await fetch("/api/theme/live-overrides", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
          signal: signal
        });
        if (res.ok && !silent) {
          ['btn-studio-header-save', 'btn-studio-ribbon-save', 'btn-studio-footer-save'].forEach(id => {
            const b = document.getElementById(id);
            if (b) {
              const prevText = b.innerHTML;
              b.innerHTML = '<span>' + cssT("ui.css_live_studio.saved_on_server", "✓ Auf Server gesichert") + '</span>';
              setTimeout(() => { b.innerHTML = prevText; if (window.lucide && lucide.createIcons) lucide.createIcons(); }, 2500);
            }
          });
          if (typeof showNotification === "function") {
            const totalCount = Object.values(studioRules).reduce((a, c) => a + Object.keys(c).length, 0);
            showNotification(cssT("ui.css_live_studio.saved_title", "Gespeichert"), cssT("ui.css_live_studio.saved_body", "Alle {count} aktiven CSS-Regeln dauerhaft auf dem Server gesichert.", { count: totalCount }), "success");
          }
        }
      } catch (e) {
        if (e.name === 'AbortError') return;
        console.error("Save overrides error:", e);
        if (!silent && typeof showNotification === "function") {
          showNotification(cssT("ui.css_live_studio.save_failed_title", "Speichern fehlgeschlagen"), cssT("ui.css_live_studio.save_failed_body", "Verbindungsfehler beim Speichern der Overrides."), "error");
        }
      }
    }
    async function bakeStudioIntoMainDesign() {
      const activeCount = Object.values(studioRules).reduce((acc, props) => acc + Object.keys(props || {}).length, 0);
      const selCount = Object.keys(studioRules).length;
      if (activeCount === 0) {
        if (typeof showNotification === "function") {
          showNotification(cssT("ui.css_live_studio.no_changes_title", "Keine Live-Änderungen"), cssT("ui.css_live_studio.no_changes_body", "Es gibt aktuell keine aktiven Studio-Regeln zum Einbrennen (Zähler ist bereits 0)."), "info");
        } else {
          alert(cssT("ui.css_live_studio.no_changes_alert", "Es gibt aktuell keine aktiven Live-Regeln (Zähler ist bereits 0)."));
        }
        return;
      }

      const confirmMsg = cssT("ui.css_live_studio.bake_confirm", "Möchtest du alle {rules} aktiven CSS-Regeln ({selectors} Selektoren) dauerhaft in das Hauptdesign (custom_studio.css) einbrennen?\n\nDadurch werden die Regeln fest ins System übernommen und der Live-Zähler wird auf 0 zurückgesetzt.", { rules: activeCount, selectors: selCount });
      if (!confirm(confirmMsg)) return;

      const payload = {
        rules: studioRules,
        textOverrides: studioTextOverrides,
        htmlOverrides: studioHtmlOverrides
      };

      try {
        const res = await fetch("/api/theme/bake-into-main-design", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });

        if (!res.ok) {
          throw new Error(`Server-Fehler HTTP ${res.status}`);
        }

        const data = await res.json();
        const bakedCount = data.baked_rules_count || activeCount;

        // 1. Entferne injizierte Inline-Styles von betroffenen Elementen im DOM,
        // da diese ab sofort direkt über custom_studio.css geladen werden
        for (const [sel, props] of Object.entries(studioRules)) {
          try {
            const els = document.querySelectorAll(sel);
            els.forEach(el => {
              if (el instanceof HTMLElement) {
                for (const p of Object.keys(props || {})) {
                  el.style.removeProperty(p);
                }
              }
            });
          } catch (e) {}
        }

        // 2. Leere temporären Runtime-<style> Tag
        const liveStyleTag = document.getElementById("archon-live-custom-styles");
        if (liveStyleTag) {
          liveStyleTag.textContent = "/* Archon CSS Live Studio Overrides — Reset after bake */";
        }

        // 3. Leere interne Studio-Regeln
        studioRules = {};

        // 4. Speicherzustand bereinigen
        localStorage.removeItem("archon_theme_live_overrides");
        localStorage.setItem("archon_theme_live_overrides", JSON.stringify({
          rules: {},
          textOverrides: studioTextOverrides,
          htmlOverrides: studioHtmlOverrides
        }));

        // 5. Aktualisiere den Link-Tag im Head, um die neu eingebrannte custom_studio.css sofort frisch zu laden
        const studioCssLink = document.getElementById("archon-custom-studio-css") || document.querySelector('link[href*="custom_studio.css"]');
        if (studioCssLink) {
          const baseHref = studioCssLink.href.split("?")[0];
          studioCssLink.href = `${baseHref}?v=${Date.now()}`;
        }

        // 6. Zähler und UI aktualisieren
        updateStudioActiveRulesCounters();
        renderStudioRulesList();
        if (studioSelectedElement && studioSelectedSelector) {
          populateVisualControlsFromElement(studioSelectedElement, studioSelectedSelector);
        }

        if (typeof showNotification === "function") {
          showNotification(
            cssT("ui.css_live_studio.bake_done_title", "Permanent ins Hauptdesign übernommen"),
            cssT("ui.css_live_studio.bake_done_body", "Alle {count} CSS-Regeln wurden dauerhaft in custom_studio.css eingebrannt. Der Live-Zähler steht jetzt wieder auf 0.", { count: bakedCount }),
            "success"
          );
        } else {
          alert(cssT("ui.css_live_studio.bake_done_alert", "Erfolg: {count} CSS-Regeln wurden dauerhaft ins Hauptdesign eingebrannt. Der Zähler steht wieder auf 0.", { count: bakedCount }));
        }
      } catch (err) {
        console.error("[CSS Studio] Fehler beim Einbrennen ins Hauptdesign:", err);
        if (typeof showNotification === "function") {
          showNotification(cssT("ui.css_live_studio.bake_failed_title", "Fehler beim Einbrennen"), cssT("ui.css_live_studio.bake_failed_body", "Konnte nicht gespeichert werden: {message}", { message: err.message }), "error");
        } else {
          alert(cssT("ui.css_live_studio.bake_failed_alert", "Fehler beim Einbrennen ins Hauptdesign: {message}", { message: err.message }));
        }
      }
    }

    function resetSelectedElementStyles() {
      if (!studioSelectedSelector) return;
      const oldProps = studioRules[studioSelectedSelector];
      if (oldProps) {
        try {
          const els = document.querySelectorAll(studioSelectedSelector);
          els.forEach(el => {
            if (el instanceof HTMLElement) {
              for (const p of Object.keys(oldProps)) {
                el.style.removeProperty(p);
              }
            }
          });
        } catch (e) {}
      }
      delete studioRules[studioSelectedSelector];
      applyStudioRulesToDOM();
      updateStudioActiveRulesCounters();
      if (studioSelectedElement) {
        populateVisualControlsFromElement(studioSelectedElement, studioSelectedSelector);
      }
      debounceAutoSave();
    }
    async function resetAllStudioStyles() {
      if (confirm(cssT("ui.css_live_studio.reset_confirm", "Möchtest du wirklich ALLE benutzerdefinierten CSS-, Text- und HTML-Anpassungen unwiderruflich zurücksetzen?"))) {
        for (const [sel, props] of Object.entries(studioRules)) {
          try {
            const els = document.querySelectorAll(sel);
            els.forEach(el => {
              if (el instanceof HTMLElement) {
                for (const p of Object.keys(props)) {
                  el.style.removeProperty(p);
                }
              }
            });
          } catch (e) {}
        }
        studioRules = {};
        studioTextOverrides = {};
        studioHtmlOverrides = {};
        localStorage.removeItem("archon_theme_live_overrides");
        localStorage.removeItem("archon_theme_html_overrides");
        applyStudioRulesToDOM();
        updateStudioActiveRulesCounters();
        try {
          await fetch("/api/theme/live-overrides", { method: "DELETE" });
        } catch (e) {}
        if (studioSelectedElement) {
          populateVisualControlsFromElement(studioSelectedElement, studioSelectedSelector);
        }
        renderStudioRulesList();
        renderStudioTextsList();
        renderStudioSymbolsTab();
        alert(cssT("ui.css_live_studio.reset_done", "Alle Overrides wurden vollständig zurückgesetzt."));
      }
    }
    // ==========================================
    // DRAGGABLE WINDOW UTILITY FOR STUDIO
    // ==========================================
    let isStudioDragging = false;
    let studioDragShiftX = 0;
    let studioDragShiftY = 0;
    function setupStudioDraggable() {
      const studio = document.getElementById("archon-css-studio");
      const handle = document.getElementById("studio-drag-header");
      if (!studio || !handle) return;
      if (handle.dataset.dragInit === "true") return;
      handle.dataset.dragInit = "true";
      handle.style.touchAction = "none";
      handle.addEventListener("pointerdown", (e) => {
        if (e.target.closest("button") || e.target.closest("input") || e.target.closest("select")) {
          return;
        }
        e.preventDefault();
        isStudioDragging = true;
        
        try {
          handle.setPointerCapture(e.pointerId);
        } catch (_) {}
        const rect = studio.getBoundingClientRect();
        studioDragShiftX = e.clientX - rect.left;
        studioDragShiftY = e.clientY - rect.top;
        handle.style.cursor = "grabbing";
      });
      handle.addEventListener("pointermove", (e) => {
        if (!isStudioDragging) return;
        e.preventDefault();
        const studioWidth = studio.offsetWidth || 560;
        let newLeft = e.clientX - studioDragShiftX;
        let newTop = e.clientY - studioDragShiftY;
        // Keep inside viewport
        newLeft = Math.max(10, Math.min(window.innerWidth - studioWidth - 10, newLeft));
        newTop = Math.max(10, Math.min(window.innerHeight - 80, newTop));
        studio.style.left = `${newLeft}px`;
        studio.style.top = `${newTop}px`;
        studio.style.right = "auto";
        studio.style.bottom = "auto";
      });
      const onPointerEnd = (e) => {
        if (isStudioDragging) {
          isStudioDragging = false;
          try {
            handle.releasePointerCapture(e.pointerId);
          } catch (_) {}
          handle.style.cursor = "";
        }
      };
      handle.addEventListener("pointerup", onPointerEnd);
      handle.addEventListener("pointercancel", onPointerEnd);
      // Minimized pill draggable
      const minPill = document.getElementById("archon-css-studio-minimized");
      if (minPill && minPill.dataset.dragInit !== "true") {
        minPill.dataset.dragInit = "true";
        minPill.style.touchAction = "none";
        let isMinDrag = false;
        let minShiftX = 0, minShiftY = 0;
        let minMoved = false;
        minPill.addEventListener("pointerdown", (e) => {
          isMinDrag = true;
          minMoved = false;
          try { minPill.setPointerCapture(e.pointerId); } catch (_) {}
          const rect = minPill.getBoundingClientRect();
          minShiftX = e.clientX - rect.left;
          minShiftY = e.clientY - rect.top;
        });
        minPill.addEventListener("pointermove", (e) => {
          if (!isMinDrag) return;
          minMoved = true;
          let nl = Math.max(10, Math.min(window.innerWidth - minPill.offsetWidth - 10, e.clientX - minShiftX));
          let nt = Math.max(10, Math.min(window.innerHeight - minPill.offsetHeight - 10, e.clientY - minShiftY));
          minPill.style.left = `${nl}px`;
          minPill.style.top = `${nt}px`;
          minPill.style.right = "auto";
          minPill.style.bottom = "auto";
        });
        minPill.addEventListener("pointerup", (e) => {
          if (isMinDrag) {
            isMinDrag = false;
            try { minPill.releasePointerCapture(e.pointerId); } catch (_) {}
            if (!minMoved) {
              restoreCssStudio();
            }
          }
        });
      }
    }
    // Attach to page load
// Guardian-Logik am 09.10.2026 nach static/js/guardian.js ausgelagert.

// --- THEME MANAGER LOGIC ---
async function fetchThemeProfiles() {
    try {
        const res = await fetch('/api/themes');
        if (!res.ok) return;
        const data = await res.json();
        const select = document.getElementById('studio-theme-select');
        if (!select) return;
        
        const currentValue = select.value;
        select.innerHTML = '<option value="">' + cssT("ui.css_live_studio.theme_select_none", "-- Theme wählen --") + '</option>';
        
        data.themes.forEach(theme => {
            const opt = document.createElement('option');
            opt.value = theme;
            opt.textContent = theme;
            select.appendChild(opt);
        });
        
        if (data.themes.includes(currentValue)) {
            select.value = currentValue;
        }
    } catch (e) {
        console.error("Fehler beim Laden der Themes:", e);
    }
}

async function loadSelectedThemeProfile(themeName) {
    if (!themeName) return;
    try {
        const res = await fetch('/api/themes/' + encodeURIComponent(themeName));
        if (!res.ok) return;
        const themeData = await res.json();
        
        // Use existing function to apply
        if (typeof applyDesignPreset === 'function') {
            // Apply it manually
            Object.keys(themeData).forEach(k => {
                themeSettings[k] = themeData[k];
            });
            syncInputsWithSettings(); // Update UI inputs
            
            // Reapply CSS vars
            if (themeSettings.sidebarWidth) document.documentElement.style.setProperty('--sidebar-width', themeSettings.sidebarWidth + 'px');
            if (themeSettings.borderRadius) document.documentElement.style.setProperty('--border-radius', themeSettings.borderRadius + 'px');
            if (themeSettings.colorSidebar) document.documentElement.style.setProperty('--sidebar-bg', themeSettings.colorSidebar);
            if (themeSettings.colorCard) document.documentElement.style.setProperty('--card-bg', themeSettings.colorCard);
            if (themeSettings.colorBg) document.documentElement.style.setProperty('--page-bg', themeSettings.colorBg);
            if (themeSettings.colorAccent) document.documentElement.style.setProperty('--accent-color', themeSettings.colorAccent);
            // etc... this handles the basic keys from customizer.js
            
            // We should also apply the new studio styles if they exist
            if (typeof liveApplyCustomCSS === 'function') {
                saveThemeToServer(true); // save as active theme
                showNotification(cssT("ui.css_live_studio.theme_loaded_title", "Theme geladen"), cssT("ui.css_live_studio.theme_loaded_body", "Das Theme '{name}' wurde erfolgreich geladen.", { name: themeName }), "success");
            }
        }
    } catch (e) {
        console.error(e);
        showNotification(cssT("ui.css_live_studio.notify_error", "Fehler"), cssT("ui.css_live_studio.theme_load_failed", "Theme konnte nicht geladen werden."), "error");
    }
}

async function saveThemeProfile() {
    const select = document.getElementById('studio-theme-select');
    let name = select.value;
    
    name = prompt(cssT("ui.css_live_studio.theme_name_prompt", "Unter welchem Namen soll dieses Theme gespeichert werden?"), name || cssT("ui.css_live_studio.theme_name_default", "Mein Custom Theme"));
    if (!name) return;
    
    // Format name (remove special chars, make safe for filename)
    name = name.replace(/[^a-zA-Z0-9_-]/g, "_").toLowerCase();
    
    try {
        const res = await fetch('/api/themes/' + encodeURIComponent(name), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(themeSettings) // themeSettings is global in customizer.js
        });

        if (res.ok) {
            showNotification(cssT("ui.css_live_studio.theme_saved_title", "Theme gespeichert"), cssT("ui.css_live_studio.theme_saved_body", "Theme '{name}' erfolgreich gesichert!", { name: name }), "success");
            await fetchThemeProfiles();
            select.value = name;
        }
    } catch (e) {
        showNotification(cssT("ui.css_live_studio.notify_error", "Fehler"), cssT("ui.css_live_studio.theme_save_failed", "Theme konnte nicht gespeichert werden."), "error");
    }
}

async function deleteThemeProfile() {
    const select = document.getElementById('studio-theme-select');
    const name = select.value;
    if (!name) {
        alert(cssT("ui.css_live_studio.alert_pick_theme", "Bitte zuerst ein Theme auswählen!"));
        return;
    }
    
    if (!confirm(cssT("ui.css_live_studio.theme_delete_confirm", "Möchtest du das Theme '{name}' wirklich löschen?", { name: name }))) return;

    try {
        const res = await fetch('/api/themes/' + encodeURIComponent(name), { method: 'DELETE' });
        if (res.ok) {
            showNotification(cssT("ui.css_live_studio.theme_deleted_title", "Theme gelöscht"), cssT("ui.css_live_studio.theme_deleted_body", "Theme '{name}' wurde entfernt.", { name: name }), "success");
            select.value = "";
            await fetchThemeProfiles();
        }
    } catch (e) {
        showNotification(cssT("ui.css_live_studio.notify_error", "Fehler"), cssT("ui.css_live_studio.theme_delete_failed", "Konnte nicht gelöscht werden."), "error");
    }
}

// Call fetch on load
setTimeout(fetchThemeProfiles, 2000);

// ============================================================
// AUTO-INIT (11.10.2026 - "gravierender Bug"): Der EINZIGE fruehere
// Aufruf stand in appshell_architect.js als
//   try { await initArchonCssStudio(); } catch (e) {}
// in einer window.onload-Kette mit STUMMEN catchs - scheiterte oder
// hing ein Schritt davor (z.B. loadBoardroomFrameworks ohne
// Timeout), lief das Studio-Init NIE: die Regeln kamen nie im
// Browser an, removeStudioBackground meldete "Kein Hintergrundbild"
// obwohl der Server Regeln hatte. Jetzt: unabhaengiger Start +
// sichtbare Fehler statt stummer catchs.
let archonStudioInitRunning = false;
let archonStudioInitTried = false;
window.archonStudioAutoInit = async function archonStudioAutoInit() {
  if (archonStudioInitRunning) return;
  archonStudioInitRunning = true;
  archonStudioInitTried = true;
  try {
    await initArchonCssStudio();
  } catch (e) {
    console.error("[CSS Studio] Init fehlgeschlagen - Studio-Regeln konnten nicht geladen werden:", e);
    archonStudioInitTried = false;   // erlaubt spaeteren Erneutversuch
  } finally {
    archonStudioInitRunning = false;
  }
};
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => window.archonStudioAutoInit());
} else {
  window.archonStudioAutoInit();
}
// Spaetversuch, falls der erste Lauf im toten onload-Race landete
setTimeout(() => { if (!archonStudioInitTried) window.archonStudioAutoInit(); }, 4000);

