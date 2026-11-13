// =========================================================================
    // APPSHELL ARCHITECT & LAYOUT EDITOR CONTROLLER
    // =========================================================================
    // --- i18n-Helfer (Tranche 7) -------------------------------------------
    // astT() liefert den Katalogtext mit PFLICHT-Fallback: fehlt der Key in der
    // aktiven Sprache und in de, bleibt der deutsche Text stehen - nie "".
    // {platzhalter} werden aus params gefuellt (Zahlen stehen nie im Key).
    function astT(key, fallback, params) {
      const i18n = window.archonI18n;
      let text = i18n ? i18n.t(key, fallback) : fallback;
      if (params) {
        Object.keys(params).forEach(name => {
          text = text.split(`{${name}}`).join(String(params[name]));
        });
      }
      return text;
    }

    let appShellConfig = {
      headerHeight: 80,
      canvasPadding: 24,
      headerMode: 'full-bleed',
      syncLogo: true
    };

    function initAppShellConfig() {
      try {
        const stored = localStorage.getItem("archon_appshell_config");
        if (stored) {
          const parsed = JSON.parse(stored);
          if (parsed && typeof parsed.headerHeight === "number") {
            // Auto-upgrade legacy header heights (< 80px) to new unified 80px standard
            if (parsed.headerHeight < 80) {
              parsed.headerHeight = 80;
              try { localStorage.setItem("archon_appshell_config", JSON.stringify({ ...appShellConfig, ...parsed })); } catch(e){}
            }
            appShellConfig = { ...appShellConfig, ...parsed };
          }
        } else {
          try { localStorage.setItem("archon_appshell_config", JSON.stringify(appShellConfig)); } catch(e){}
        }
      } catch (e) {
        console.warn("Could not load appshell config:", e);
      }
      if (appShellConfig.headerHeight < 80) appShellConfig.headerHeight = 80;
      applyAppShellVisuals(false);
    }

    function applyAppShellVisuals(showToastNotice = false) {
      // 1. Update CSS Custom Properties on :root
      document.documentElement.style.setProperty("--appshell-header-height", `${appShellConfig.headerHeight}px`);
      document.documentElement.style.setProperty("--appshell-canvas-padding", `${appShellConfig.canvasPadding}px`);

      // 2. Synchronize Sidebar Logo Header if enabled
      const sidebarLogoHeader = document.getElementById("sidebar-logo-header");
      if (sidebarLogoHeader) {
        if (appShellConfig.syncLogo) {
          sidebarLogoHeader.style.setProperty("height", `${appShellConfig.headerHeight}px`, "important");
          sidebarLogoHeader.style.setProperty("min-height", `${appShellConfig.headerHeight}px`, "important");
          sidebarLogoHeader.style.setProperty("max-height", `${appShellConfig.headerHeight}px`, "important");
        } else {
          sidebarLogoHeader.style.removeProperty("height");
          sidebarLogoHeader.style.removeProperty("min-height");
          sidebarLogoHeader.style.removeProperty("max-height");
        }
      }

      // 3. Update Inputs & Badges in Controls
      const heightSlider = document.getElementById("appshell-height-slider");
      const heightBadge = document.getElementById("appshell-height-badge");
      if (heightSlider) heightSlider.value = appShellConfig.headerHeight;
      if (heightBadge) heightBadge.textContent = `${appShellConfig.headerHeight}px`;

      const paddingSlider = document.getElementById("appshell-padding-slider");
      const paddingBadge = document.getElementById("appshell-padding-badge");
      if (paddingSlider) paddingSlider.value = appShellConfig.canvasPadding;
      if (paddingBadge) paddingBadge.textContent = `${appShellConfig.canvasPadding}px`;

      const syncLogoCheck = document.getElementById("appshell-sync-logo");
      if (syncLogoCheck) syncLogoCheck.checked = appShellConfig.syncLogo;

      // Update Height preset button styles
      [48, 52, 56, 64].forEach(h => {
        const btn = document.getElementById(`btn-preset-h-${h}`);
        if (btn) {
          if (appShellConfig.headerHeight === h) {
            btn.className = "px-2 py-1.5 rounded border-2 border-indigo-600 bg-indigo-50 text-xs font-mono font-bold text-indigo-700 text-center cursor-pointer transition";
          } else {
            btn.className = "px-2 py-1.5 rounded border border-[var(--border-default)] bg-[var(--bg-canvas)] text-xs font-mono font-semibold hover:border-indigo-400 text-center cursor-pointer transition";
          }
        }
      });

      // Update Padding preset button styles
      [0, 16, 24, 32].forEach(p => {
        const btn = document.getElementById(`btn-preset-p-${p}`);
        if (btn) {
          if (appShellConfig.canvasPadding === p) {
            btn.className = "px-2 py-1.5 rounded border-2 border-indigo-600 bg-indigo-50 text-xs font-mono font-bold text-indigo-700 text-center cursor-pointer transition";
          } else {
            btn.className = "px-2 py-1.5 rounded border border-[var(--border-default)] bg-[var(--bg-canvas)] text-xs font-mono font-semibold hover:border-indigo-400 text-center cursor-pointer transition";
          }
        }
      });

      // Update Mode toggle cards
      const optFull = document.getElementById("mode-opt-fullbleed");
      const optIsland = document.getElementById("mode-opt-island");
      const iconFull = document.getElementById("mode-icon-fullbleed");
      const iconIsland = document.getElementById("mode-icon-island");

      if (appShellConfig.headerMode === "full-bleed") {
        if (optFull) optFull.className = "p-3 rounded-lg border-2 border-indigo-600 bg-indigo-50/50 flex flex-col gap-1 cursor-pointer transition";
        if (optIsland) optIsland.className = "p-3 rounded-lg border border-[var(--border-default)] bg-[var(--bg-canvas)] flex flex-col gap-1 cursor-pointer transition opacity-75 hover:opacity-100";
        if (iconFull) iconFull.setAttribute("data-lucide", "check-circle");
        if (iconIsland) iconIsland.setAttribute("data-lucide", "circle");
      } else {
        if (optFull) optFull.className = "p-3 rounded-lg border border-[var(--border-default)] bg-[var(--bg-canvas)] flex flex-col gap-1 cursor-pointer transition opacity-75 hover:opacity-100";
        if (optIsland) optIsland.className = "p-3 rounded-lg border-2 border-indigo-600 bg-indigo-50/50 flex flex-col gap-1 cursor-pointer transition";
        if (iconFull) iconFull.setAttribute("data-lucide", "circle");
        if (iconIsland) iconIsland.setAttribute("data-lucide", "check-circle");
      }

      // 4. Update Scaled Miniature Simulation Box
      const simSpecs = document.getElementById("appshell-sim-specs");
      if (simSpecs) simSpecs.textContent = astT(
        'ui.appshell_architect.spec_line',
        '{height}px Header · {padding}px Padding · {mode}',
        {
          height: appShellConfig.headerHeight,
          padding: appShellConfig.canvasPadding,
          mode: appShellConfig.headerMode === 'full-bleed'
            ? astT('ui.appshell_architect.mode_full_bleed', 'Durchgezogen')
            : astT('ui.appshell_architect.mode_island', 'Insel')
        }
      );

      const simLogo = document.getElementById("sim-mini-logo");
      const simHeader = document.getElementById("sim-mini-header");
      const simCanvas = document.getElementById("sim-mini-canvas");
      const simHTag = document.getElementById("sim-mini-h-tag");
      const simPTag = document.getElementById("sim-mini-p-tag");

      const scaledH = Math.max(30, Math.round(appShellConfig.headerHeight * 0.7));
      const scaledP = Math.max(0, Math.round(appShellConfig.canvasPadding * 0.5));

      if (simLogo) {
        simLogo.style.height = appShellConfig.syncLogo ? `${scaledH}px` : "38px";
      }

      if (simHeader) {
        simHeader.style.height = `${scaledH}px`;
        if (appShellConfig.headerMode === "full-bleed") {
          simHeader.style.margin = "0";
          simHeader.style.width = "100%";
          simHeader.style.borderRadius = "0";
          simHeader.style.borderBottom = "1px solid #e2e8f0";
          simHeader.style.borderTop = "none";
          simHeader.style.borderLeft = "none";
          simHeader.style.borderRight = "none";
        } else {
          simHeader.style.margin = "4px 8px";
          simHeader.style.width = "calc(100% - 16px)";
          simHeader.style.borderRadius = "6px";
          simHeader.style.border = "1px solid #e2e8f0";
        }
      }

      if (simCanvas) {
        simCanvas.style.padding = `${scaledP}px`;
      }
      if (simHTag) simHTag.textContent = `${appShellConfig.headerHeight}px`;
      if (simPTag) simPTag.textContent = `p: ${appShellConfig.canvasPadding}px`;

      // 5. Update Real-time JSON preview
      const jsonElem = document.getElementById("appshell-json-preview");
      if (jsonElem) {
        const schemaObj = {
          "$schema": "archon-appshell-v2",
          "header": {
            "height": appShellConfig.headerHeight,
            "mode": appShellConfig.headerMode,
            "borderBottom": "1px solid var(--border-default)",
            "syncWithSidebarLogo": appShellConfig.syncLogo
          },
          "canvas": {
            "padding": appShellConfig.canvasPadding,
            "background": "var(--bg-canvas)"
          }
        };
        jsonElem.textContent = JSON.stringify(schemaObj, null, 2);
      }

      if (window.lucide) {
        try { window.lucide.createIcons(); } catch (e) {}
      }

      if (showToastNotice && typeof showArchonToast === "function") {
        showArchonToast(astT(
          'ui.appshell_architect.saved_toast',
          'AppShell gespeichert: {height}px Header / {padding}px Padding',
          { height: appShellConfig.headerHeight, padding: appShellConfig.canvasPadding }
        ), "success");
      }
    }

    function onAppShellSliderChange(type, value) {
      const num = parseInt(value, 10);
      if (type === "height") appShellConfig.headerHeight = num;
      if (type === "padding") appShellConfig.canvasPadding = num;
      applyAppShellVisuals(false);
    }

    function setAppShellHeightPreset(h) {
      appShellConfig.headerHeight = h;
      applyAppShellVisuals(false);
    }

    function setAppShellPaddingPreset(p) {
      appShellConfig.canvasPadding = p;
      applyAppShellVisuals(false);
    }

    function setAppShellHeaderMode(mode) {
      appShellConfig.headerMode = mode;
      applyAppShellVisuals(false);
    }

    function onAppShellSyncLogoToggle(checked) {
      appShellConfig.syncLogo = checked;
      applyAppShellVisuals(false);
    }

    function saveAppShellConfig(showToastNotice = true) {
      localStorage.setItem("archon_appshell_config", JSON.stringify(appShellConfig));
      applyAppShellVisuals(showToastNotice);
    }

    function resetAppShellConfig() {
      appShellConfig = {
        headerHeight: 56,
        canvasPadding: 24,
        headerMode: 'full-bleed',
        syncLogo: true
      };
      saveAppShellConfig(true);
    }

    async function copyAppShellJson() {
      const jsonElem = document.getElementById("appshell-json-preview");
      if (!jsonElem) return;
      try {
        await navigator.clipboard.writeText(jsonElem.textContent);
        const btn = document.getElementById("btn-copy-appshell-json");
        if (btn) {
          const oldHtml = btn.innerHTML;
          btn.innerHTML = `<i data-lucide="check" class="w-3 h-3 text-emerald-600"></i><span class="text-emerald-600">${astT('ui.appshell_architect.copied', 'Kopiert!')}</span>`;
          if (window.lucide) window.lucide.createIcons();
          setTimeout(() => { btn.innerHTML = oldHtml; if (window.lucide) window.lucide.createIcons(); }, 2000);
        }
      } catch (err) {
        console.error("Clipboard copy failed:", err);
      }
    }

    window.onAppShellSliderChange = onAppShellSliderChange;
    window.setAppShellHeightPreset = setAppShellHeightPreset;
    window.setAppShellPaddingPreset = setAppShellPaddingPreset;
    window.setAppShellHeaderMode = setAppShellHeaderMode;
    window.onAppShellSyncLogoToggle = onAppShellSyncLogoToggle;
    window.saveAppShellConfig = saveAppShellConfig;
    window.resetAppShellConfig = resetAppShellConfig;
    window.copyAppShellJson = copyAppShellJson;
    window.initAppShellConfig = initAppShellConfig;

    // Sprachwechsel: Vorschau-Werte neu beschriften (JS-Template-Strings).
    window.addEventListener('archon:language-changed', () => {
      applyAppShellVisuals(false);
    });

    const originalOnload = window.onload;
    window.onload = async () => {
      if (originalOnload) {
        try { await originalOnload(); } catch (e) { console.error("Initial onload error:", e); }
      }
      // 11.10.2026: hing/fehlschlag ein Schritt, starb die GANZE Kette
      // still (stumme catchs) -> Studio-Init lief nie. Jetzt: harte
      // Timeouts + sichtbare Fehler; das Studio-Init laeuft zusaetzlich
      // unabhaengig ueber window.archonStudioAutoInit (css_live_studio.js).
      const _withTimeout = (p, ms, name) => Promise.race([
        Promise.resolve(p),
        new Promise((_, rej) => setTimeout(() => rej(new Error(name + " Timeout nach " + ms + "ms")), ms))
      ]);
      try { await _withTimeout(loadBoardroomFrameworks(), 10000, "loadBoardroomFrameworks"); }
      catch (e) { console.error("[AppShell] loadBoardroomFrameworks:", e); }
      try { await _withTimeout(window.archonStudioAutoInit ? window.archonStudioAutoInit() : initArchonCssStudio(), 15000, "initArchonCssStudio"); }
      catch (e) { console.error("[AppShell] initArchonCssStudio:", e); }
      try { initAppShellConfig(); } catch (e) { console.error("[AppShell] initAppShellConfig:", e); }
      try { await _withTimeout(fetchMissionControlData(false), 12000, "fetchMissionControlData"); }
      catch (e) { console.error("[AppShell] fetchMissionControlData:", e); }
      startMissionControlStopwatches();
      if (!window.__mc_poll_interval) {
        window.__mc_poll_interval = setInterval(() => {
          if (document.hidden) return;
          if (typeof currentTab !== "undefined" && currentTab !== "mission-control") return;
          fetchMissionControlData(false);
        }, 30000);
      }
    };