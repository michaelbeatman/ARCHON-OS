
    // --- CUSTOMIZER STEUERUNG & LIVE-UPDATE ---
    let customizerOpen = false;
    const defaultTheme = {
      sidebarWidth: 240,
      borderRadius: 8,
      cardPadding: 16,
      fontSize: 14,
      fontFamily: "'Inter', sans-serif",
      borderWidth: 1,
      
      // Global Colors
      colorBg: "#f8fafc",
      colorSidebar: "#ffffff",
      colorCard: "#ffffff",
      colorInput: "#ffffff",
      colorBorder: "#e2e8f0",
      colorBorderStrong: "#cbd5e1",
      colorAccent: "#ef233c",
      colorTextPrimary: "#0f172a",
      colorTextSecondary: "#475569",
      colorTextMuted: "#94a3b8",
      colorTextLabel: "#64748b",
      // Tags & Badges
      tagBg: "#fff1f2",
      tagText: "#9f1239",
      tagBorder: "#fecdd3",
      tagRadius: 6,
      catPillBg: "#f1f5f9",
      catPillText: "#334155",
      catPillBorder: "#cbd5e1",
      catPillActiveBg: "#0f172a",
      catPillActiveText: "#ffffff",
      catPillActiveBorder: "#0f172a",
      // Agentenprofile
      profPanelBg: "var(--card)",
      profPanelBorder: "var(--border)",
      profCardBg: "var(--card)",
      profCardBorder: "var(--border)",
      profCardSelectedBg: "var(--secondary)",
      profCardSelectedBorder: "var(--foreground)",
      profSkillBg: "var(--secondary)",
      profSkillText: "var(--foreground)",
      profSkillBorder: "var(--border)",
      profInputBg: "var(--background)",
      profInputBorder: "var(--border)",
      profInputText: "var(--foreground)",
      profTitleColor: "var(--foreground)",
      profRoleColor: "var(--muted-foreground)",
      profLabelColor: "var(--foreground)",
      profDescColor: "var(--muted-foreground)",
      profToolActiveBg: "var(--secondary)",
      profToolActiveBorder: "var(--border)",
      profToolActiveText: "var(--foreground)",
      profToolInactiveBg: "var(--background)",
      profToolInactiveBorder: "var(--border)",
      profToolInactiveText: "var(--muted-foreground)",
      buttonShadow: "0 2px 4px rgba(0,0,0,0.06)",
      panelShadow: "0 4px 20px -4px rgba(0,0,0,0.06), 0 2px 6px -1px rgba(0,0,0,0.03)",
      // AI Mastermind
      mmCardBg: "#ffffff",
      mmBubbleBg: "#f8fafc",
      mmBubbleBorder: "#e2e8f0",
      mmBubbleText: "#0f172a",
      // Pipeline
      kanbanColBg: "#f1f5f9",
      kanbanColBorder: "#e2e8f0",
      kanbanCardBg: "#ffffff",
      kanbanCardBorder: "#e2e8f0",
      kanbanCardText: "#0f172a",
      // Dashboard
      dashCardBg: "#ffffff",
      dashCardBorder: "#e2e8f0",
      dashTerminalBg: "#090d16",
      dashTerminalText: "#22c55e",
      // Digitale Personalakte (Theme Default)
      paModalBg: "#ffffff",
      paModalBorder: "#e2e8f0",
      paModalRadius: 16,
      paHeaderBg: "#f8fafc",
      paCardBg: "#ffffff",
      paCardBorder: "#e2e8f0",
      paTitleText: "#000000",
      paBodyText: "#000000",
      paMutedText: "#000000",
      paAccentColor: "#ef233c",
      paBackdropOpacity: 70,
      gradientEnable: false,
      gradientStart: "#4f46e5",
      gradientEnd: "#6b7cff",
      logoUrl: "/static/logo.png",
      bgImageUrl: "",
      bgOpacity: 100
    };
    let themeSettings = { ...defaultTheme };
    const CUSTOMIZER_TOKENS = {
      sidebarWidth: { var: '--sidebar-width', unit: 'px' },
      borderRadius: { var: '--border-radius', unit: 'px' },
      cardPadding: { var: '--card-padding', unit: 'px' },
      fontSize: { var: '--font-size', unit: 'px' },
      fontFamily: { var: '--font-family', unit: '' },
      borderWidth: { var: '--border-width', unit: 'px' },
      // Global Colors
      colorBg: { var: '--page-bg', unit: '' },
      colorSidebar: { var: '--sidebar-bg', unit: '' },
      colorCard: { var: '--card-bg', unit: '' },
      colorInput: { var: '--input-bg', unit: '' },
      colorBorder: { var: '--border', unit: '' },
      colorBorderStrong: { var: '--border-strong', unit: '' },
      colorAccent: { var: '--accent', unit: '' },
      colorTextPrimary: { var: '--text-primary', unit: '' },
      colorTextSecondary: { var: '--text-secondary', unit: '' },
      colorTextMuted: { var: '--text-muted', unit: '' },
      colorTextLabel: { var: '--text-label', unit: '' },
      colorTextCode: { var: '--text-code', unit: '' },
      // Tags & Badges
      tagBg: { var: '--tag-bg', unit: '' },
      tagText: { var: '--tag-text', unit: '' },
      tagBorder: { var: '--tag-border', unit: '' },
      tagRadius: { var: '--tag-radius', unit: 'px' },
      tagFontSize: { var: '--tag-font-size', unit: 'px' },
      catPillBg: { var: '--cat-pill-bg', unit: '' },
      catPillText: { var: '--cat-pill-text', unit: '' },
      catPillBorder: { var: '--cat-pill-border', unit: '' },
      catPillActiveBg: { var: '--cat-pill-active-bg', unit: '' },
      catPillActiveText: { var: '--cat-pill-active-text', unit: '' },
      catPillActiveBorder: { var: '--cat-pill-active-border', unit: '' },
      // Agentenprofile
      profPanelBg: { var: '--prof-panel-bg', unit: '' },
      profPanelBorder: { var: '--prof-panel-border', unit: '' },
      profCardBg: { var: '--prof-card-bg', unit: '' },
      profCardBorder: { var: '--prof-card-border', unit: '' },
      profCardSelectedBg: { var: '--prof-card-selected-bg', unit: '' },
      profCardSelectedBorder: { var: '--prof-card-selected-border', unit: '' },
      profSkillBg: { var: '--prof-skill-bg', unit: '' },
      profSkillText: { var: '--prof-skill-text', unit: '' },
      profSkillBorder: { var: '--prof-skill-border', unit: '' },
      profInputBg: { var: '--prof-input-bg', unit: '' },
      profInputBorder: { var: '--prof-input-border', unit: '' },
      profInputText: { var: '--prof-input-text', unit: '' },
      profTitleColor: { var: '--prof-title-color', unit: '' },
      profRoleColor: { var: '--prof-role-color', unit: '' },
      profLabelColor: { var: '--prof-label-color', unit: '' },
      profDescColor: { var: '--prof-desc-color', unit: '' },
      profToolActiveBg: { var: '--prof-tool-active-bg', unit: '' },
      profToolActiveBorder: { var: '--prof-tool-active-border', unit: '' },
      profToolActiveText: { var: '--prof-tool-active-text', unit: '' },
      profToolInactiveBg: { var: '--prof-tool-inactive-bg', unit: '' },
      profToolInactiveBorder: { var: '--prof-tool-inactive-border', unit: '' },
      profToolInactiveText: { var: '--prof-tool-inactive-text', unit: '' },
      buttonShadow: { var: '--button-shadow', unit: '' },
      panelShadow: { var: '--panel-shadow', unit: '' },
      // AI Mastermind
      mmCardBg: { var: '--mm-card-bg', unit: '' },
      mmBubbleBg: { var: '--mm-bubble-bg', unit: '' },
      mmBubbleBorder: { var: '--mm-bubble-border', unit: '' },
      mmBubbleText: { var: '--mm-bubble-text', unit: '' },
      // Pipeline
      kanbanColBg: { var: '--kanban-col-bg', unit: '' },
      kanbanColBorder: { var: '--kanban-col-border', unit: '' },
      kanbanCardBg: { var: '--kanban-card-bg', unit: '' },
      kanbanCardBorder: { var: '--kanban-card-border', unit: '' },
      kanbanCardText: { var: '--kanban-card-text', unit: '' },
      // Dashboard
      dashCardBg: { var: '--dash-card-bg', unit: '' },
      dashCardBorder: { var: '--dash-card-border', unit: '' },
      dashTerminalBg: { var: '--dash-terminal-bg', unit: '' },
      dashTerminalText: { var: '--dash-terminal-text', unit: '' },
      // Digitale Personalakte
      paModalBg: { var: '--pa-modal-bg', unit: '' },
      paModalBorder: { var: '--pa-modal-border', unit: '' },
      paModalRadius: { var: '--pa-modal-radius', unit: 'px' },
      paHeaderBg: { var: '--pa-header-bg', unit: '' },
      paCardBg: { var: '--pa-card-bg', unit: '' },
      paCardBorder: { var: '--pa-card-border', unit: '' },
      paTitleText: { var: '--pa-title-text', unit: '' },
      paBodyText: { var: '--pa-body-text', unit: '' },
      paMutedText: { var: '--pa-muted-text', unit: '' },
      paAccentColor: { var: '--pa-accent-color', unit: '' },
      paBackdropOpacity: { var: '--pa-backdrop-opacity', unit: '%' }
    };
    function onCustomizerFieldInput(key, value) {
      applyCustomizerSetting(key, value, true);
    }
    function applyCustomizerSetting(key, value, shouldAutoSave = true) {
      themeSettings[key] = value;
      const spinalKey = key.replace(/([A-Z])/g, "-$1").toLowerCase();
      
      // Update CSS Variable auf :root
      if (CUSTOMIZER_TOKENS[key]) {
        const token = CUSTOMIZER_TOKENS[key];
        if (token.var.startsWith('--prof-') && (!value || value.startsWith('var(') || ['#ffffff','#000000','#ef233c','#fff1f2','#9f1239','#ecfdf5','#f8fafc','#e2e8f0','#cbd5e1'].includes(value) || value.startsWith('rgba(239'))) {
          document.documentElement.style.removeProperty(token.var);
        } else {
          const valWithUnit = token.unit ? `${value}${token.unit}` : value;
          document.documentElement.style.setProperty(token.var, valWithUnit);
        }
        
        if (key === 'colorAccent') {
          document.documentElement.style.setProperty('--accent-bg', hexToRgba(value, 0.1));
          document.documentElement.style.setProperty('--accent-border', hexToRgba(value, 0.25));
        }
      }
      // Synchronisiere UI Elemente im Settings Modal
      const circle = document.getElementById(`circle-${spinalKey}`);
      if (circle) circle.style.backgroundColor = value;
      const hexInp = document.getElementById(`hex-${spinalKey}`);
      if (hexInp && hexInp.value !== value) hexInp.value = value;
      const picker = document.getElementById(`picker-${spinalKey}`);
      if (picker && value && value.startsWith('#') && (value.length === 4 || value.length === 7) && picker.value !== value) {
        picker.value = value;
      }
      const valSpan = document.getElementById(`val-${spinalKey}`);
      if (valSpan) {
        const unit = CUSTOMIZER_TOKENS[key]?.unit || '';
        valSpan.innerText = `${value}${unit}`;
      }
      const rangeInp = document.getElementById(`opt-${spinalKey}`);
      if (rangeInp && rangeInp.value != value) rangeInp.value = value;
      const selectInp = document.getElementById(`opt-${spinalKey}`) || document.getElementById(`select-${spinalKey}`);
      if (selectInp && selectInp.tagName === 'SELECT' && selectInp.value !== value) selectInp.value = value;
      if (key === 'sidebarWidth') {
        const aside = document.querySelector("aside");
        if (aside) aside.style.width = `${value}px`;
      }
      else if (key === 'logoUrl') {
        updateLogo(value);
        updateLogoPreviewUI(value);
      }
      else if (key === 'bgImageUrl' || key === 'bgOpacity') {
        updateBackgroundImage();
      }
      if (shouldAutoSave) {
        autoSaveTheme();
      }
    }
    function hexToRgba(hex, alpha) {
      if (!hex || !hex.startsWith("#") || hex.length < 7) return `rgba(239, 35, 60, ${alpha})`;
      const r = parseInt(hex.slice(1, 3), 16);
      const g = parseInt(hex.slice(3, 5), 16);
      const b = parseInt(hex.slice(5, 7), 16);
      return `rgba(${r}, ${g}, ${b}, ${alpha})`;
    }
    function updateLogo(url) {
      const logoImg = document.getElementById("sidebar-logo-img");
      if (logoImg) {
        logoImg.src = url || "/static/logo.png";
      }
    }
    function updateBackgroundImage() {
      const url = themeSettings.bgImageUrl;
      const opacity = themeSettings.bgOpacity !== undefined ? themeSettings.bgOpacity : 100;
      let bgDiv = document.getElementById("custom-page-bg-image");
      
      if (url) {
        if (!bgDiv) {
          bgDiv = document.createElement("div");
          bgDiv.id = "custom-page-bg-image";
          bgDiv.className = "fixed inset-0 pointer-events-none z-[-1] bg-cover bg-center transition-all duration-300";
          document.body.appendChild(bgDiv);
        }
        bgDiv.style.backgroundImage = `url('${url}')`;
        bgDiv.style.opacity = `${opacity / 100}`;
      } else if (bgDiv) {
        bgDiv.remove();
      }
    }
    let themeSaveTimeout = null;
    function autoSaveTheme() {
      try {
        localStorage.setItem("archon_theme_custom", JSON.stringify(themeSettings));
      } catch (e) {}
      clearTimeout(themeSaveTimeout);
      themeSaveTimeout = setTimeout(() => {
        saveThemeToServer(true);
      }, 500);
    }
    async function loadThemeFromServer() {
      try {
        const cached = localStorage.getItem("archon_theme_custom");
        if (cached) {
          const parsed = JSON.parse(cached);
          if (parsed && typeof parsed === "object") {
            if (parsed.profTitleColor === "#0f172a" || !parsed.profTitleColor) parsed.profTitleColor = "#000000";
            if (parsed.profRoleColor === "#0f172a" || !parsed.profRoleColor) parsed.profRoleColor = "#000000";
            if (parsed.profLabelColor === "#1e293b" || !parsed.profLabelColor) parsed.profLabelColor = "#000000";
            if (parsed.profDescColor === "#334155" || !parsed.profDescColor) parsed.profDescColor = "#000000";
            if (!parsed.profInputText) parsed.profInputText = "#000000";
            themeSettings = { ...defaultTheme, ...parsed };
            Object.keys(themeSettings).forEach(key => {
              applyCustomizerSetting(key, themeSettings[key], false);
            });
          }
        }
      } catch (e) {
        console.warn("Fehler beim Lesen aus localStorage:", e);
      }
      try {
        const res = await fetch("/api/theme");
        if (res.ok) {
          const serverTheme = await res.json();
          if (serverTheme && typeof serverTheme === "object" && Object.keys(serverTheme).length > 0) {
            if (serverTheme.profTitleColor === "#0f172a" || !serverTheme.profTitleColor) serverTheme.profTitleColor = "#000000";
            if (serverTheme.profRoleColor === "#0f172a" || !serverTheme.profRoleColor) serverTheme.profRoleColor = "#000000";
            if (serverTheme.profLabelColor === "#1e293b" || !serverTheme.profLabelColor) serverTheme.profLabelColor = "#000000";
            if (serverTheme.profDescColor === "#334155" || !serverTheme.profDescColor) serverTheme.profDescColor = "#000000";
            if (!serverTheme.profInputText) serverTheme.profInputText = "#000000";
            themeSettings = { ...defaultTheme, ...serverTheme };
            Object.keys(themeSettings).forEach(key => {
              applyCustomizerSetting(key, themeSettings[key], false);
            });
            try {
              localStorage.setItem("archon_theme_custom", JSON.stringify(themeSettings));
            } catch (e) {}
          }
        }
      } catch (e) {
        console.error("Fehler beim Laden des Themes vom Server:", e);
      }
      syncInputsWithSettings();
      initCustomCSS();
    }
    function syncInputsWithSettings() {
      Object.keys(themeSettings).forEach(key => {
        applyCustomizerSetting(key, themeSettings[key], false);
      });
      updateLogoPreviewUI(themeSettings.logoUrl);
    }
    async function saveThemeToServer(silent = false) {
      try {
        localStorage.setItem("archon_theme_custom", JSON.stringify(themeSettings));
      } catch (e) {}
      try {
        const res = await fetch("/api/theme", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(themeSettings)
        });
        if (res.ok) {
          if (!silent) alert("Theme-Einstellungen erfolgreich gespeichert!");
        }
      } catch (e) {}
    }
    // --- CRM-STYLE DESIGN & FARBEN CONTROLLER & LIVE CSS ENGINE ---
    let currentDesignSubTab = "global";
    const DESIGN_PRESETS = {
      "crm_standard": {
        colorBg: "#f8fafc",
        colorSidebar: "#ffffff",
        colorCard: "#ffffff",
        colorInput: "#ffffff",
        colorBorder: "#e2e8f0",
        colorAccent: "#ef233c",
        colorTextPrimary: "#0f172a",
        colorTextSecondary: "#475569",
        colorTextMuted: "#94a3b8",
        tagBg: "#fff1f2",
        tagText: "#9f1239",
        tagBorder: "#fecdd3",
        tagRadius: 6,
        catPillBg: "#f1f5f9",
        catPillText: "#334155",
        catPillBorder: "#cbd5e1",
        catPillActiveBg: "#0f172a",
        catPillActiveText: "#ffffff",
        catPillActiveBorder: "#0f172a",
        profPanelBg: "#ffffff",
        profPanelBorder: "#e2e8f0",
        profCardBg: "#ffffff",
        profCardBorder: "#e2e8f0",
        profCardSelectedBg: "rgba(239, 35, 60, 0.06)",
        profCardSelectedBorder: "#ef233c",
        profSkillBg: "#fff1f2",
        profSkillText: "#9f1239",
        profSkillBorder: "#fecdd3",
        profInputBg: "#ffffff",
        profInputBorder: "#e2e8f0",
        profTitleColor: "#0f172a",
        profRoleColor: "#0f172a",
        profLabelColor: "#1e293b",
        profDescColor: "#334155",
        profToolActiveBg: "#ecfdf5",
        profToolActiveBorder: "#a7f3d0",
        profToolActiveText: "#065f46",
        profToolInactiveBg: "#f8fafc",
        profToolInactiveBorder: "#e2e8f0",
        profToolInactiveText: "#64748b",
        buttonShadow: "0 2px 4px rgba(0,0,0,0.06)",
        panelShadow: "0 4px 20px -4px rgba(0,0,0,0.06), 0 2px 6px -1px rgba(0,0,0,0.03)",
        paModalBg: "#ffffff",
        paModalBorder: "#e2e8f0",
        paModalRadius: 16,
        paHeaderBg: "#f8fafc",
        paCardBg: "#ffffff",
        paCardBorder: "#e2e8f0",
        paTitleText: "#0f172a",
        paBodyText: "#334155",
        paMutedText: "#64748b",
        paAccentColor: "#ef233c",
        paBackdropOpacity: 70
      },
      "slate_pro": {
        colorBg: "#f1f5f9",
        colorSidebar: "#0f172a",
        colorCard: "#ffffff",
        colorInput: "#ffffff",
        colorBorder: "#cbd5e1",
        colorAccent: "#3b82f6",
        colorTextPrimary: "#0f172a",
        colorTextSecondary: "#334155",
        colorTextMuted: "#64748b",
        tagBg: "#eff6ff",
        tagText: "#1d4ed8",
        tagBorder: "#bfdbfe",
        tagRadius: 6,
        catPillBg: "#e2e8f0",
        catPillText: "#1e293b",
        catPillBorder: "#94a3b8",
        catPillActiveBg: "#0f172a",
        catPillActiveText: "#ffffff",
        catPillActiveBorder: "#0f172a",
        profPanelBg: "#ffffff",
        profPanelBorder: "#cbd5e1",
        profCardBg: "#ffffff",
        profCardBorder: "#cbd5e1",
        profCardSelectedBg: "rgba(59, 130, 246, 0.08)",
        profCardSelectedBorder: "#3b82f6",
        profSkillBg: "#eff6ff",
        profSkillText: "#1d4ed8",
        profSkillBorder: "#bfdbfe",
        profInputBg: "#ffffff",
        profInputBorder: "#cbd5e1",
        profTitleColor: "#0f172a",
        profRoleColor: "#0f172a",
        profLabelColor: "#1e293b",
        profDescColor: "#334155",
        profToolActiveBg: "#eff6ff",
        profToolActiveBorder: "#bfdbfe",
        profToolActiveText: "#1d4ed8",
        profToolInactiveBg: "#f8fafc",
        profToolInactiveBorder: "#cbd5e1",
        profToolInactiveText: "#64748b",
        buttonShadow: "0 2px 4px rgba(0,0,0,0.06)",
        panelShadow: "0 4px 20px -4px rgba(0,0,0,0.06), 0 2px 6px -1px rgba(0,0,0,0.03)",
        paModalBg: "#ffffff",
        paModalBorder: "#cbd5e1",
        paModalRadius: 16,
        paHeaderBg: "#f8fafc",
        paCardBg: "#ffffff",
        paCardBorder: "#cbd5e1",
        paTitleText: "#0f172a",
        paBodyText: "#334155",
        paMutedText: "#64748b",
        paAccentColor: "#3b82f6",
        paBackdropOpacity: 70
      },
      "obsidian_dark": {
        colorBg: "#090d16",
        colorSidebar: "#090d16",
        colorCard: "#111827",
        colorInput: "#111827",
        colorBorder: "rgba(255, 255, 255, 0.08)",
        colorAccent: "#ef233c",
        colorTextPrimary: "#f8fafc",
        colorTextSecondary: "#cbd5e1",
        colorTextMuted: "#64748b",
        tagBg: "rgba(239, 35, 60, 0.15)",
        tagText: "#fca5a5",
        tagBorder: "rgba(239, 35, 60, 0.35)",
        tagRadius: 6,
        catPillBg: "#1e293b",
        catPillText: "#cbd5e1",
        catPillBorder: "#334155",
        catPillActiveBg: "#ffffff",
        catPillActiveText: "#090d16",
        catPillActiveBorder: "#ffffff",
        profPanelBg: "#18181b",
        profPanelBorder: "#27272a",
        profCardBg: "#1f1f23",
        profCardBorder: "#27272a",
        profCardSelectedBg: "rgba(239, 35, 60, 0.15)",
        profCardSelectedBorder: "#ef233c",
        profSkillBg: "rgba(239, 35, 60, 0.15)",
        profSkillText: "#fca5a5",
        profSkillBorder: "rgba(239, 35, 60, 0.35)",
        profInputBg: "#121215",
        profInputBorder: "#27272a",
        profTitleColor: "#f8fafc",
        profRoleColor: "#f8fafc",
        profLabelColor: "#cbd5e1",
        profDescColor: "#94a3b8",
        profToolActiveBg: "rgba(16, 185, 129, 0.15)",
        profToolActiveBorder: "rgba(16, 185, 129, 0.35)",
        profToolActiveText: "#6ee7b7",
        profToolInactiveBg: "rgba(255, 255, 255, 0.03)",
        profToolInactiveBorder: "rgba(255, 255, 255, 0.08)",
        profToolInactiveText: "#94a3b8",
        buttonShadow: "0 2px 6px rgba(0,0,0,0.4)",
        panelShadow: "0 4px 20px -4px rgba(0,0,0,0.4)",
        paModalBg: "#111827",
        paModalBorder: "rgba(255, 255, 255, 0.12)",
        paModalRadius: 16,
        paHeaderBg: "#0b0f19",
        paCardBg: "#181f30",
        paCardBorder: "rgba(255, 255, 255, 0.08)",
        paTitleText: "#f8fafc",
        paBodyText: "#cbd5e1",
        paMutedText: "#94a3b8",
        paAccentColor: "#ef233c",
        paBackdropOpacity: 75
      },
      "emerald_corporate": {
        colorBg: "#f0fdf4",
        colorSidebar: "#064e3b",
        colorCard: "#ffffff",
        colorInput: "#ffffff",
        colorBorder: "#bbf7d0",
        colorAccent: "#10b981",
        colorTextPrimary: "#0f172a",
        colorTextSecondary: "#065f46",
        colorTextMuted: "#047857",
        tagBg: "#ecfdf5",
        tagText: "#047857",
        tagBorder: "#a7f3d0",
        tagRadius: 6,
        catPillBg: "#dcfce7",
        catPillText: "#064e3b",
        catPillBorder: "#86efac",
        catPillActiveBg: "#064e3b",
        catPillActiveText: "#ffffff",
        catPillActiveBorder: "#064e3b",
        profPanelBg: "#ffffff",
        profPanelBorder: "#bbf7d0",
        profCardBg: "#ffffff",
        profCardBorder: "#bbf7d0",
        profCardSelectedBg: "rgba(16, 185, 129, 0.08)",
        profCardSelectedBorder: "#10b981",
        profSkillBg: "#ecfdf5",
        profSkillText: "#047857",
        profSkillBorder: "#a7f3d0",
        profInputBg: "#f0fdf4",
        profInputBorder: "#bbf7d0",
        profTitleColor: "#0f172a",
        profRoleColor: "#0f172a",
        profLabelColor: "#064e3b",
        profDescColor: "#065f46",
        profToolActiveBg: "#ecfdf5",
        profToolActiveBorder: "#a7f3d0",
        profToolActiveText: "#047857",
        profToolInactiveBg: "#f0fdf4",
        profToolInactiveBorder: "#bbf7d0",
        profToolInactiveText: "#065f46",
        buttonShadow: "0 2px 4px rgba(0,0,0,0.06)",
        panelShadow: "0 4px 20px -4px rgba(0,0,0,0.06), 0 2px 6px -1px rgba(0,0,0,0.03)",
        paModalBg: "#ffffff",
        paModalBorder: "#bbf7d0",
        paModalRadius: 16,
        paHeaderBg: "#f0fdf4",
        paCardBg: "#ffffff",
        paCardBorder: "#bbf7d0",
        paTitleText: "#064e3b",
        paBodyText: "#065f46",
        paMutedText: "#047857",
        paAccentColor: "#10b981",
        paBackdropOpacity: 70
      },
      "cyberpunk_neon": {
        colorBg: "#05050a",
        colorSidebar: "#05050a",
        colorCard: "#0d0e17",
        colorInput: "#0d0e17",
        colorBorder: "rgba(236, 72, 153, 0.3)",
        colorAccent: "#ec4899",
        colorTextPrimary: "#fdf4ff",
        colorTextSecondary: "#c084fc",
        colorTextMuted: "#9333ea",
        tagBg: "rgba(236, 72, 153, 0.15)",
        tagText: "#f472b6",
        tagBorder: "rgba(236, 72, 153, 0.4)",
        tagRadius: 6,
        catPillBg: "#180d2b",
        catPillText: "#d8b4fe",
        catPillBorder: "#7e22ce",
        catPillActiveBg: "#ec4899",
        catPillActiveText: "#ffffff",
        catPillActiveBorder: "#ec4899",
        profCardBg: "#0d0e17",
        profCardBorder: "rgba(236, 72, 153, 0.25)",
        profCardSelectedBg: "rgba(236, 72, 153, 0.15)",
        profCardSelectedBorder: "#ec4899",
        profSkillBg: "rgba(236, 72, 153, 0.15)",
        profSkillText: "#f472b6",
        profSkillBorder: "rgba(236, 72, 153, 0.4)",
        paModalBg: "#0d0e17",
        paModalBorder: "rgba(236, 72, 153, 0.35)",
        paModalRadius: 16,
        paHeaderBg: "#05050a",
        paCardBg: "#180d2b",
        paCardBorder: "rgba(236, 72, 153, 0.25)",
        paTitleText: "#fdf4ff",
        paBodyText: "#d8b4fe",
        paMutedText: "#9333ea",
        paAccentColor: "#ec4899",
        paBackdropOpacity: 85
      }
    };
    function setDesignSubTab(tabName) {
      currentDesignSubTab = tabName;
      const subTabs = ["global", "tags", "profiles", "personalakte", "mastermind", "pipeline", "dashboard", "customcss"];
      subTabs.forEach(t => {
        const btn = document.getElementById(`subtab-btn-${t}`);
        const content = document.getElementById(`subtab-content-${t}`);
        if (t === tabName) {
          if (btn) {
            btn.className = "design-subtab-btn px-2.5 py-1.5 font-bold border-b-2 border-[#EF233C] text-[#EF233C] transition shrink-0";
          }
          if (content) content.classList.remove("hidden");
        } else {
          if (btn) {
            btn.className = "design-subtab-btn px-2.5 py-1.5 font-bold border-b-2 border-transparent text-muted-custom hover:text-primary-custom transition shrink-0";
          }
          if (content) content.classList.add("hidden");
        }
      });
      lucide.createIcons();
    }
    function applyDesignPreset(presetKey) {
      const preset = DESIGN_PRESETS[presetKey];
      if (!preset) return;
      Object.keys(preset).forEach(k => {
        applyCustomizerSetting(k, preset[k], false);
      });
      autoSaveTheme();
    }
    function saveCustomDesignPreset() {
      const nameInp = document.getElementById("new-preset-name");
      if (!nameInp || !nameInp.value.trim()) {
        alert("Bitte gib einen Namen für die neue Design-Vorlage ein.");
        return;
      }
      const pName = nameInp.value.trim();
      const currentConfig = { ...themeSettings };
      const select = document.getElementById("design-preset-select");
      if (select) {
        const opt = document.createElement("option");
        opt.value = pName.toLowerCase().replace(/\s+/g, '_');
        opt.innerText = pName;
        opt.selected = true;
        select.appendChild(opt);
      }
      DESIGN_PRESETS[pName.toLowerCase().replace(/\s+/g, '_')] = currentConfig;
      alert(`Design-Vorlage '${pName}' erfolgreich gespeichert!`);
      nameInp.value = "";
    }
    function liveApplyCustomCSS(cssText) {
      let styleTag = document.getElementById("archon-custom-user-css");
      if (!styleTag) {
        styleTag = document.createElement("style");
        styleTag.id = "archon-custom-user-css";
        document.head.appendChild(styleTag);
      }
      styleTag.innerHTML = cssText;
    }
    function saveCustomCSSToStorage() {
      const editor = document.getElementById("custom-user-css-editor");
      if (!editor) return;
      const cssText = editor.value;
      localStorage.setItem("archon_custom_user_css", cssText);
      liveApplyCustomCSS(cssText);
      alert("✅ Custom CSS erfolgreich gespeichert und angewendet!");
    }
    function insertCssSnippet(selector) {
      const editor = document.getElementById("custom-user-css-editor");
      if (!editor) return;
      const snippet = `\n/* Styling für ${selector} */\n${selector} {\n  \n}\n`;
      editor.value += snippet;
      liveApplyCustomCSS(editor.value);
      editor.focus();
    }
    function initCustomCSS() {
      const savedCss = localStorage.getItem("archon_custom_user_css") || "";
      const editor = document.getElementById("custom-user-css-editor");
      if (editor) editor.value = savedCss;
      if (savedCss) liveApplyCustomCSS(savedCss);
    }
    function handleCrmLogoUpload(event) {
      const file = event.target.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = (e) => {
        const dataUrl = e.target.result;
        applyCustomizerSetting('logoUrl', dataUrl, true);
        const prev = document.getElementById("crm-modal-logo-preview");
        if (prev) {
          prev.src = dataUrl;
          prev.style.display = "block";
          const fallback = document.getElementById("crm-modal-logo-fallback");
          if (fallback) fallback.style.display = "none";
        }
      };
      reader.readAsDataURL(file);
    }
    function resetCrmLogo() {
      applyCustomizerSetting('logoUrl', "", true);
      const prev = document.getElementById("crm-modal-logo-preview");
      if (prev) {
        prev.src = "/static/logo.png";
      }
    }
    function resetTheme() {
      if (confirm("Möchten Sie alle Designanpassungen zurücksetzen?")) {
        try { 
          localStorage.removeItem("archon_theme_custom"); 
          localStorage.removeItem("archon_custom_user_css");
        } catch(e) {}
        
        const styleTag = document.getElementById("archon-custom-user-css");
        if (styleTag) styleTag.innerHTML = "";
        const editor = document.getElementById("custom-user-css-editor");
        if (editor) editor.value = "";
        applyDesignPreset("crm_standard");
        alert("Design auf CRM-Standard zurückgesetzt.");
      }
    }