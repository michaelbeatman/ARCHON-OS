/**
 * static/js/watchdog_controller.js
 * Controller für den Internet-Watchdog (Kognition: Säule 4).
 * Beinhaltet:
 * 1. Quellen- und Funde-Verwaltung
 * 2. Sammelkorb (Basket) für Multi-Fund-Bündelung & Content-Synthese
 * 3. Quick-Actions: LinkedIn-Post, Robert-Dossier, Freies Prompting
 * 4. Priority-Keywords für Sofort-Pings auf Telegram
 */

(function() {
  // --- i18n-Helfer (Tranche 7) ---------------------------------------------
  // wdT() liefert den Katalogtext mit PFLICHT-Fallback: fehlt der Key in der
  // aktiven Sprache und in de, bleibt der deutsche Text stehen - nie "".
  // {platzhalter} werden aus params gefuellt (Zahlen stehen nie im Key).
  function wdT(key, fallback, params) {
    const i18n = window.archonI18n;
    let text = i18n ? i18n.t(key, fallback) : fallback;
    if (params) {
      Object.keys(params).forEach(name => {
        text = text.split(`{${name}}`).join(String(params[name]));
      });
    }
    return text;
  }

  // Aktive Sprache fuer Intl-Formatierung; "de" ist der Referenz-Fallback.
  function wdLocale() {
    return (window.archonI18n && window.archonI18n.currentLang) || 'de';
  }

  let watchdogConfig = null;
  let activeCategory = 'all';
  let searchQuery = '';
  let selectedFindingId = null;
  let currentWatchdogTab = 'radar';

  const WATCHDOG_HEADER_META = {
    radar: {
      titleKey: 'ui.watchdog_controller.header_radar_title',
      title: "Internet-Watchdog — Radar",
      subtitleKey: 'ui.watchdog_controller.header_radar_subtitle',
      subtitle: "Token-freie, autonome Dauerüberwachung für Markt, Bau, KI und Wettbewerbs-Quellen",
      icon: "/static/img/cadre_icons/watchdog_radar.png"
    },
    basket: {
      titleKey: 'ui.watchdog_controller.header_basket_title',
      title: "Internet-Watchdog — Sammelkorb",
      subtitleKey: 'ui.watchdog_controller.header_basket_subtitle',
      subtitle: "Multi-Fund-Bündelung & Content-Synthese für Dossiers und LinkedIn-Posts",
      icon: "/static/img/cadre_icons/watchdog_basket.png"
    },
    sources: {
      titleKey: 'ui.watchdog_controller.header_sources_title',
      title: "Internet-Watchdog — Quellen & Feeds",
      subtitleKey: 'ui.watchdog_controller.header_sources_subtitle',
      subtitle: "Konfiguration aller Google News Queries, RSS-Feeds und Webseiten-Diffs",
      icon: "/static/img/cadre_icons/watchdog_sources.png"
    },
    settings: {
      titleKey: 'ui.watchdog_controller.header_settings_title',
      title: "Internet-Watchdog — Optionen & Alarm",
      subtitleKey: 'ui.watchdog_controller.header_settings_subtitle',
      subtitle: "Taktung, Prioritäts-Keywords & Benachrichtigungen konfigurieren",
      icon: "/static/img/cadre_icons/watchdog_settings.png"
    }
  };

  async function fetchWatchdogConfig() {
    try {
      const res = await fetch('/api/v1/watchdog/config');
      if (res.ok) {
        watchdogConfig = await res.json();
        renderWatchdogView();
      }
    } catch (e) {
      console.error('[Watchdog] Fehler beim Laden:', e);
    }
  }

  function renderWatchdogView() {
    if (!watchdogConfig) return;

    // 1. Zähler & Badges
    const sourcesCount = (watchdogConfig.targets || []).length;
    const activeSourcesCount = (watchdogConfig.targets || []).filter(t => t.active).length;
    const findingsCount = (watchdogConfig.recent_findings || []).length;
    const basket = watchdogConfig.basket || [];
    const threshold = parseInt(watchdogConfig.basket_threshold || 3, 10);

    const sourcesBadge = document.getElementById('wd-sources-count-badge');
    if (sourcesBadge) sourcesBadge.textContent = sourcesCount;

    const sourcesActiveRatio = document.getElementById('wd-sources-active-ratio');
    if (sourcesActiveRatio) sourcesActiveRatio.textContent = wdT('ui.watchdog_controller.sources_active_ratio', '{active}/{total} aktiv', { active: activeSourcesCount, total: sourcesCount });

    const totalFindingsBadge = document.getElementById('wd-findings-total-badge');
    if (totalFindingsBadge) totalFindingsBadge.textContent = wdT('ui.watchdog_controller.findings_total', '{count} Funde', { count: findingsCount });

    const findingsCounterLabel = document.getElementById('wd-findings-counter-label');
    if (findingsCounterLabel) findingsCounterLabel.textContent = wdT('ui.watchdog_controller.findings_counter', '{count} Treffer', { count: findingsCount });

    const lastScanTime = document.getElementById('wd-last-scan-time-badge');
    if (lastScanTime) {
      lastScanTime.textContent = watchdogConfig.last_run 
        ? wdT('ui.watchdog_controller.last_scan_at', 'Letzter Scan: {time} Uhr', { time: new Date(watchdogConfig.last_run).toLocaleTimeString(wdLocale()) }) 
        : wdT('ui.watchdog_controller.last_scan_never', 'Letzter Scan: Noch keiner');
    }

    const footerInterval = document.getElementById('wd-sources-footer-interval');
    if (footerInterval) {
      footerInterval.textContent = wdT('ui.watchdog_controller.interval_minutes', '{count} Min.', { count: watchdogConfig.interval_minutes || 30 });
    }

    // 2. Sammelkorb Widget
    const basketCountEl = document.getElementById('wd-basket-count');
    const basketMaxEl = document.getElementById('wd-basket-max');
    const dispatchBasketBtn = document.getElementById('btn-wd-dispatch-basket');
    if (basketCountEl) basketCountEl.textContent = basket.length;
    if (basketMaxEl) basketMaxEl.textContent = threshold;
    if (dispatchBasketBtn) {
      dispatchBasketBtn.disabled = basket.length === 0;
      if (basket.length >= threshold) {
        dispatchBasketBtn.className = "px-2 py-0.5 rounded bg-amber-600 hover:bg-amber-500 text-white font-mono text-[10.5px] font-bold transition cursor-pointer shadow-xs animate-pulse";
      } else {
        dispatchBasketBtn.className = "px-2 py-0.5 rounded bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900 hover:opacity-90 font-mono text-[10.5px] font-bold transition cursor-pointer shadow-2xs disabled:opacity-40";
      }
    }

    // 3. Status Pill
    const statusPill = document.getElementById('wd-status-pill');
    const statusText = document.getElementById('wd-status-pill-text');
    if (statusPill && statusText) {
      if (watchdogConfig.enabled) {
        statusPill.className = "h-7 px-2 rounded-lg border text-[10.5px] font-mono font-bold flex items-center gap-1 transition cursor-pointer bg-emerald-500/10 border-emerald-500/25 text-emerald-600 dark:text-emerald-400";
        statusText.textContent = wdT('ui.watchdog_controller.status_active', 'Aktiv');
      } else {
        statusPill.className = "h-7 px-2 rounded-lg border text-[10.5px] font-mono font-bold flex items-center gap-1 transition cursor-pointer bg-zinc-500/10 border-zinc-500/25 text-zinc-400";
        statusText.textContent = wdT('ui.watchdog_controller.status_paused', 'Pausiert');
      }
    }

    // 4. Render Quellen & Funde
    renderWatchdogSources();
    renderWatchdogFindings();
    renderWatchdogSettingsModal();
    renderWatchdogBasketFull();
    renderWatchdogSourcesFull();

    if (window.lucide && typeof window.lucide.createIcons === 'function') {
      window.lucide.createIcons();
    }
  }

  function renderWatchdogSources() {
    const list = document.getElementById('wd-sources-list');
    if (!list || !watchdogConfig) return;

    const targets = watchdogConfig.targets || [];
    const filtered = activeCategory === 'all' 
      ? targets 
      : targets.filter(t => (t.category || '').toLowerCase() === activeCategory.toLowerCase());

    if (filtered.length === 0) {
      list.innerHTML = '<div class="text-center py-6 text-xs font-mono text-[var(--muted-foreground)]">' + wdT('ui.watchdog_controller.sources_empty', 'Keine Quellen in dieser Kategorie.') + '</div>';
      return;
    }

    list.innerHTML = filtered.map(t => `
      <div class="p-2 rounded-xl border border-[var(--border)] bg-[var(--card)] hover:bg-[var(--secondary)]/30 flex items-center justify-between gap-2 transition ${t.active ? '' : 'opacity-60'}">
        <div class="flex items-center gap-2 min-w-0 flex-1">
          <button 
            type="button" 
            onclick="toggleWatchdogTarget('${t.id}')"
            class="w-4 h-4 rounded flex items-center justify-center border transition shrink-0 cursor-pointer ${t.active ? 'bg-zinc-900 border-zinc-900 text-white dark:bg-zinc-100 dark:border-zinc-100 dark:text-zinc-900' : 'border-[var(--border)] hover:border-[var(--foreground)]'}"
            title="${t.active ? wdT('ui.watchdog_controller.toggle_deactivate', 'Deaktivieren') : wdT('ui.watchdog_controller.toggle_activate', 'Aktivieren')}"
          >
            ${t.active ? '<span class="text-[9px] font-bold">✓</span>' : ''}
          </button>
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-1.5 truncate">
              <span class="font-bold text-xs text-[var(--foreground)] truncate">${escapeHtml(t.name)}</span>
            </div>
            <div class="text-[10px] font-mono text-[var(--muted-foreground)] truncate mt-0.5">
              ${escapeHtml(t.query_or_url)}
            </div>
          </div>
        </div>

        <div class="flex items-center gap-1 shrink-0">
          <button 
            type="button" 
            onclick="deleteWatchdogTarget('${t.id}')" 
            class="w-5 h-5 rounded hover:bg-rose-500/15 text-[var(--muted-foreground)] hover:text-rose-500 flex items-center justify-center transition cursor-pointer text-xs"
            title="${wdT('ui.watchdog_controller.remove_source', 'Quelle entfernen')}"
          >
            ✕
          </button>
        </div>
      </div>
    `).join('');
  }

  function renderWatchdogFindings() {
    const container = document.getElementById('wd-findings-stream-container');
    if (!container || !watchdogConfig) return;

    let findings = watchdogConfig.recent_findings || [];
    const basket = watchdogConfig.basket || [];
    const basketIds = new Set(basket.map(b => b.id));

    if (activeCategory !== 'all') {
      findings = findings.filter(f => (f.category || '').toLowerCase() === activeCategory.toLowerCase());
    }
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      findings = findings.filter(f => 
        (f.title || '').toLowerCase().includes(q) || 
        (f.target_name || '').toLowerCase().includes(q) ||
        (f.snippet || '').toLowerCase().includes(q)
      );
    }

    if (findings.length === 0) {
      container.innerHTML = `
        <div class="py-16 text-center text-xs font-mono text-[var(--muted-foreground)] space-y-2">
          <i data-lucide="radio" class="w-8 h-8 mx-auto opacity-40"></i>
          <p>${wdT("ui.watchdog_controller.findings_empty", "Noch keine Funde in dieser Auswahl. Klicke auf \"Prüfen\", um den Scan zu starten.")}</p>
        </div>
      `;
      return;
    }

    container.innerHTML = findings.map(f => {
      const isSelected = f.id === selectedFindingId;
      const inBasket = basketIds.has(f.id);
      const isPrio = !!f.is_priority;

      return `
        <div 
          onclick="selectWatchdogFinding('${f.id}')"
          class="p-3 rounded-xl border transition cursor-pointer flex flex-col gap-1.5 ${
            isPrio 
              ? 'border-rose-500/40 bg-rose-500/5' 
              : isSelected 
                ? 'border-[var(--foreground)] bg-[var(--secondary)]/50 shadow-xs' 
                : 'border-[var(--border)] bg-[var(--card)] hover:bg-[var(--secondary)]/30'
          }"
        >
          <div class="flex items-center justify-between gap-2">
            <div class="flex items-center gap-2 min-w-0">
              ${isPrio ? `
                <span class="text-[9.5px] px-1.5 py-0.5 rounded font-mono font-bold bg-rose-500/15 text-rose-600 dark:text-rose-400 border border-rose-500/30 flex items-center gap-1 shrink-0">
                  <span class="w-1.5 h-1.5 rounded-full bg-rose-500 animate-ping"></span>
                  ${wdT('ui.watchdog_controller.badge_instant_alarm', 'SOFORT-ALARM')}
                </span>
              ` : `
                <span class="text-[9.5px] px-1.5 py-0.5 rounded font-mono font-bold bg-[var(--secondary)] text-[var(--foreground)] border border-[var(--border)] shrink-0">
                  ${escapeHtml(f.category || wdT('ui.watchdog_controller.category_radar', 'Radar'))}
                </span>
              `}
              <span class="text-[11px] font-mono text-[var(--muted-foreground)] truncate">
                ${escapeHtml(f.target_name || wdT('ui.watchdog_controller.source_fallback', 'Quelle'))}
              </span>
            </div>

            <!-- Schnell-Korb Toggle Checkbox -->
            <button 
              type="button" 
              onclick="event.stopPropagation(); toggleFindingInBasket('${f.id}')"
              class="px-2 py-0.5 rounded font-mono text-[10px] flex items-center gap-1 transition cursor-pointer ${
                inBasket 
                  ? 'bg-amber-500/20 text-amber-600 dark:text-amber-400 border border-amber-500/40 font-bold' 
                  : 'bg-[var(--secondary)] text-[var(--muted-foreground)] hover:text-[var(--foreground)] border border-[var(--border)]'
              }"
              title="${inBasket ? wdT('ui.watchdog_controller.basket_remove', 'Aus Sammelkorb entfernen') : wdT('ui.watchdog_controller.basket_add_hint', 'In Sammelkorb für Content-Synthese legen')}"
            >
              <span>${inBasket ? wdT('ui.watchdog_controller.basket_in', '🧺 Im Korb') : wdT('ui.watchdog_controller.basket_add', '+ Korb')}</span>
            </button>
          </div>

          <div class="text-xs font-bold text-[var(--foreground)] leading-snug">
            ${escapeHtml(f.title || wdT('ui.watchdog_controller.finding_fallback', 'Fund'))}
          </div>

          ${f.snippet ? `
            <div class="text-[11.5px] text-[var(--muted-foreground)] line-clamp-2 leading-relaxed">
              ${escapeHtml(f.snippet)}
            </div>
          ` : ''}

          <div class="flex items-center justify-between pt-1 border-t border-[var(--border)]/60 text-[10.5px] font-mono">
            <span class="text-[var(--muted-foreground)]">${escapeHtml(f.detected_at || '')}</span>
            ${f.link ? `
              <a 
                href="${escapeHtml(f.link)}" 
                target="_blank" 
                rel="noreferrer" 
                onclick="event.stopPropagation()"
                class="hover:underline flex items-center gap-1 text-[var(--foreground)] font-semibold"
              >
                <span>${wdT('ui.watchdog_controller.open_link', 'Öffnen ↗')}</span>
              </a>
            ` : ''}
          </div>
        </div>
      `;
    }).join('');
  }

  function renderWatchdogSettingsModal() {
    if (!watchdogConfig) return;

    // Keywords
    const kwInput = document.getElementById('wd-cfg-priority-keywords');
    if (kwInput) {
      kwInput.value = (watchdogConfig.priority_keywords || []).join(', ');
    }

    // Threshold
    const threshInput = document.getElementById('wd-cfg-basket-threshold');
    if (threshInput) {
      threshInput.value = watchdogConfig.basket_threshold || 3;
    }

    // Intervall Buttons
    const cur = watchdogConfig.interval_minutes || 30;
    document.querySelectorAll('.wd-interval-btn').forEach(btn => {
      const val = parseInt(btn.getAttribute('data-interval') || '30', 10);
      if (val === cur) {
        btn.className = "wd-interval-btn px-2.5 py-1 rounded-lg border border-[var(--border)] font-mono text-xs cursor-pointer bg-[var(--secondary)] text-[var(--foreground)] font-bold shadow-xs";
      } else {
        btn.className = "wd-interval-btn px-2.5 py-1 rounded-lg border border-[var(--border)] font-mono text-xs hover:bg-[var(--secondary)] cursor-pointer text-[var(--muted-foreground)]";
      }
    });

    // Telegram Checkbox
    const tg = document.getElementById('wd-modal-chan-telegram');
    if (tg) tg.checked = Boolean(watchdogConfig.channels?.telegram ?? true);
  }

  async function saveWatchdogConfig(updated) {
    watchdogConfig = updated;
    renderWatchdogView();
    try {
      await fetch('/api/v1/watchdog/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updated)
      });
    } catch (e) {
      console.error('[Watchdog] Fehler beim Speichern:', e);
    }
  }

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // --- Globale Aktionen ---

  function switchWatchdogSubTab(tab) {
    if (!tab) tab = "radar";
    currentWatchdogTab = tab;
    const tabs = ["radar", "basket", "sources", "settings"];

    const meta = WATCHDOG_HEADER_META[tab] || WATCHDOG_HEADER_META.radar;
    const titleEl = document.getElementById("watchdog-main-title");
    const subtitleEl = document.getElementById("watchdog-main-subtitle");
    const headerImgEl = document.getElementById("watchdog-main-header-img");
    if (titleEl) titleEl.textContent = wdT(meta.titleKey, meta.title);
    if (subtitleEl) subtitleEl.textContent = wdT(meta.subtitleKey, meta.subtitle);
    if (headerImgEl) headerImgEl.src = meta.icon;

    tabs.forEach(t => {
      const btn = document.getElementById(`watchdog-subtab-btn-${t}`);
      const view = document.getElementById(`watchdog-subtab-${t}`);
      const iconWrap = btn ? btn.querySelector(".tile-icon-wrap") : null;
      const label = btn ? btn.querySelector(".watchdog-tab-label") : null;

      if (t === tab) {
        if (btn) {
          btn.className = "watchdog-header-tile active-cadre-tab flex flex-col items-center justify-between min-w-[56px] sm:min-w-[62px] h-[72px] py-1 px-0.5 bg-transparent border-0 shadow-none opacity-100 cursor-pointer select-none transition-transform hover:scale-105 duration-150";
        }
        if (iconWrap) iconWrap.classList.add("active-tile");
        if (label) {
          label.className = "watchdog-tab-label text-[10px] font-mono tracking-tight text-center whitespace-nowrap text-red-600 font-bold leading-none";
        }
        if (view) view.classList.remove("hidden");
      } else {
        if (btn) {
          btn.className = "watchdog-header-tile flex flex-col items-center justify-between min-w-[56px] sm:min-w-[62px] h-[72px] py-1 px-0.5 bg-transparent border-0 shadow-none opacity-80 hover:opacity-100 cursor-pointer select-none transition-transform hover:scale-105 duration-150";
        }
        if (iconWrap) iconWrap.classList.remove("active-tile");
        if (label) {
          label.className = "watchdog-tab-label text-[10px] font-mono tracking-tight text-center whitespace-nowrap text-[var(--muted-foreground)] font-medium leading-none";
        }
        if (view) view.classList.add("hidden");
      }
    });

    if (tab === "basket") {
      renderWatchdogBasketFull();
    } else if (tab === "sources") {
      renderWatchdogSourcesFull();
    } else if (tab === "settings") {
      renderWatchdogSettingsModal();
    } else if (tab === "radar") {
      renderWatchdogFindings();
      renderWatchdogSources();
    }

    if (window.lucide && typeof window.lucide.createIcons === 'function') {
      window.lucide.createIcons();
    }
  }

  function renderWatchdogBasketFull() {
    const grid = document.getElementById('wd-basket-full-grid');
    if (!grid || !watchdogConfig) return;

    const basket = watchdogConfig.basket || [];
    if (basket.length === 0) {
      grid.innerHTML = `
        <div class="py-16 text-center text-xs font-mono text-[var(--muted-foreground)] space-y-2">
          <i data-lucide="shopping-bag" class="w-8 h-8 mx-auto opacity-40"></i>
          <p>${wdT("ui.watchdog_controller.basket_empty", "Der Sammelkorb ist leer. Markiere Funde im Radar mit \"+ Korb\", um sie für eine Bündel-Synthese vorzumerken.")}</p>
        </div>
      `;
      if (window.lucide) window.lucide.createIcons();
      return;
    }

    grid.innerHTML = basket.map((f, idx) => `
      <div class="p-3.5 rounded-xl border border-[var(--border)] bg-[var(--card)] hover:bg-[var(--secondary)]/20 transition flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
        <div class="min-w-0 flex-1 space-y-1">
          <div class="flex items-center gap-2">
            <span class="text-[9.5px] px-2 py-0.5 rounded font-mono font-bold bg-amber-500/15 text-amber-600 dark:text-amber-400 border border-amber-500/30 shrink-0">
              ${wdT('ui.watchdog_controller.basket_position', 'Pos. {index}', { index: idx + 1 })}
            </span>
            <span class="text-[9.5px] px-2 py-0.5 rounded font-mono font-bold bg-[var(--secondary)] text-[var(--foreground)] border border-[var(--border)] shrink-0">
              ${escapeHtml(f.category || wdT('ui.watchdog_controller.category_radar', 'Radar'))}
            </span>
            <span class="text-xs font-mono text-[var(--muted-foreground)] truncate">
              ${escapeHtml(f.target_name || wdT('ui.watchdog_controller.source_fallback', 'Quelle'))}
            </span>
            <span class="text-[10px] font-mono text-[var(--muted-foreground)] ml-auto shrink-0 hidden sm:inline">
              ${escapeHtml(f.detected_at || '')}
            </span>
          </div>

          <h4 class="text-xs sm:text-sm font-bold text-[var(--foreground)] leading-snug">
            ${escapeHtml(f.title || wdT('ui.watchdog_controller.finding_fallback', 'Fund'))}
          </h4>

          ${f.snippet ? `
            <p class="text-xs text-[var(--muted-foreground)] line-clamp-2 leading-relaxed">
              ${escapeHtml(f.snippet)}
            </p>
          ` : ''}

          ${f.link ? `
            <div class="pt-1">
              <a href="${escapeHtml(f.link)}" target="_blank" rel="noreferrer" class="text-[11px] font-mono text-[var(--foreground)] hover:underline inline-flex items-center gap-1 font-semibold">
                ${wdT('ui.watchdog_controller.open_source', 'Originalquelle öffnen ↗')}
              </a>
            </div>
          ` : ''}
        </div>

        <div class="flex items-center gap-2 shrink-0 self-end sm:self-center">
          <button 
            type="button" 
            onclick="toggleFindingInBasket('${f.id}'); renderWatchdogBasketFull();" 
            class="px-2.5 py-1.5 rounded-lg border border-rose-500/30 hover:bg-rose-500/10 text-rose-600 dark:text-rose-400 font-mono text-xs font-bold transition cursor-pointer flex items-center gap-1"
            title="${wdT('ui.watchdog_controller.basket_remove', 'Aus Sammelkorb entfernen')}"
          >
            <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
            <span>${wdT('ui.watchdog_controller.remove', 'Entfernen')}</span>
          </button>
        </div>
      </div>
    `).join('');

    if (window.lucide) window.lucide.createIcons();
  }

  function renderWatchdogSourcesFull() {
    const list = document.getElementById('wd-sources-full-list');
    if (!list || !watchdogConfig) return;

    const targets = watchdogConfig.targets || [];
    if (targets.length === 0) {
      list.innerHTML = `
        <div class="py-16 text-center text-xs font-mono text-[var(--muted-foreground)] space-y-2">
          <i data-lucide="radio" class="w-8 h-8 mx-auto opacity-40"></i>
          <p>${wdT("ui.watchdog_controller.sources_none_configured", "Keine Überwachungsquellen konfiguriert. Klicke auf \"Neue Quelle\", um einen Feed oder Suchbegriff hinzuzufügen.")}</p>
        </div>
      `;
      if (window.lucide) window.lucide.createIcons();
      return;
    }

    list.innerHTML = targets.map(t => `
      <div class="p-3 rounded-xl border border-[var(--border)] bg-[var(--card)] hover:bg-[var(--secondary)]/20 transition flex items-center justify-between gap-3 ${t.active ? '' : 'opacity-60'}">
        <div class="flex items-center gap-3 min-w-0 flex-1">
          <button 
            type="button" 
            onclick="toggleWatchdogTarget('${t.id}'); renderWatchdogSourcesFull();" 
            class="w-5 h-5 rounded flex items-center justify-center border transition shrink-0 cursor-pointer ${t.active ? 'bg-zinc-900 border-zinc-900 text-white dark:bg-zinc-100 dark:border-zinc-100 dark:text-zinc-900' : 'border-[var(--border)] hover:border-[var(--foreground)]'}"
            title="${t.active ? wdT('ui.watchdog_controller.toggle_deactivate', 'Deaktivieren') : wdT('ui.watchdog_controller.toggle_activate', 'Aktivieren')}"
          >
            ${t.active ? '<span class="text-[10px] font-bold">✓</span>' : ''}
          </button>
          
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-2">
              <span class="font-bold text-xs sm:text-sm text-[var(--foreground)] truncate">${escapeHtml(t.name)}</span>
              <span class="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-[var(--secondary)] text-[var(--foreground)] border border-[var(--border)] shrink-0">
                ${escapeHtml(t.category || wdT('ui.watchdog_controller.category_general', 'Allgemein'))}
              </span>
              <span class="px-1.5 py-0.5 rounded text-[9.5px] font-mono uppercase bg-sky-500/10 text-sky-600 dark:text-sky-400 border border-sky-500/25 shrink-0 hidden sm:inline">
                ${escapeHtml(t.type || 'search_feed')}
              </span>
            </div>
            <div class="text-[11px] font-mono text-[var(--muted-foreground)] truncate mt-0.5">
              ${escapeHtml(t.query_or_url)}
            </div>
          </div>
        </div>

        <div class="flex items-center gap-2 shrink-0">
          <span class="text-[10px] font-mono text-[var(--muted-foreground)] hidden md:inline">
            ${t.last_status ? escapeHtml(t.last_status) : wdT('ui.watchdog_controller.status_ready', 'Bereit')}
          </span>
          <button 
            type="button" 
            onclick="deleteWatchdogTarget('${t.id}'); renderWatchdogSourcesFull();" 
            class="px-2 py-1 rounded-lg border border-rose-500/30 hover:bg-rose-500/10 text-rose-600 dark:text-rose-400 font-mono text-xs font-semibold transition cursor-pointer flex items-center gap-1"
            title="${wdT('ui.watchdog_controller.remove_source', 'Quelle entfernen')}"
          >
            <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
            <span class="hidden sm:inline">${wdT('ui.watchdog_controller.delete', 'Löschen')}</span>
          </button>
        </div>
      </div>
    `).join('');

    if (window.lucide) window.lucide.createIcons();
  }

  window.switchWatchdogSubTab = switchWatchdogSubTab;
  window.renderWatchdogBasketFull = renderWatchdogBasketFull;
  window.renderWatchdogSourcesFull = renderWatchdogSourcesFull;

  window.initWatchdogView = function() {
    fetchWatchdogConfig();
  };

  window.selectWatchdogFinding = function(findingId) {
    selectedFindingId = findingId;
    renderWatchdogFindings();

    const finding = (watchdogConfig?.recent_findings || []).find(f => f.id === findingId);
    const preview = document.getElementById('wd-finding-preview-body');
    if (!preview || !finding) return;

    const basket = watchdogConfig.basket || [];
    const inBasket = basket.some(b => b.id === finding.id);

    preview.innerHTML = `
      <div class="space-y-3">
        <div class="flex items-center justify-between gap-2">
          <span class="text-[9.5px] px-2 py-0.5 rounded-full font-mono font-bold bg-[var(--secondary)] text-[var(--foreground)] border border-[var(--border)]">
            ${escapeHtml(finding.category || wdT('ui.watchdog_controller.category_radar', 'Radar'))}
          </span>
          <span class="text-[11px] font-mono text-[var(--muted-foreground)]">
            ${escapeHtml(finding.detected_at || '')}
          </span>
        </div>

        <h3 class="text-sm font-bold text-[var(--foreground)] leading-snug">
          ${escapeHtml(finding.title || '')}
        </h3>

        <div class="p-2.5 rounded-xl border border-[var(--border)] bg-[var(--secondary)]/30 space-y-1">
          <div class="text-[10px] font-mono text-[var(--muted-foreground)] uppercase">${wdT('ui.watchdog_controller.preview_source', 'Überwachungs-Quelle')}</div>
          <div class="text-xs font-semibold text-[var(--foreground)]">${escapeHtml(finding.target_name || '')}</div>
        </div>

        ${finding.snippet ? `
          <div class="space-y-1">
            <div class="text-[10px] font-mono text-[var(--muted-foreground)] uppercase">${wdT('ui.watchdog_controller.preview_snippet', 'Inhalts-Auszug')}</div>
            <p class="text-xs text-[var(--foreground)] leading-relaxed bg-[var(--card)] p-2.5 rounded-xl border border-[var(--border)]">
              ${escapeHtml(finding.snippet)}
            </p>
          </div>
        ` : ''}

        <!-- AKTIONEN & PROMPTING FÜR DIESEN EINZELFUND -->
        <div class="space-y-2 pt-2 border-t border-[var(--border)]">
          <div class="text-[10px] font-mono font-bold uppercase tracking-wider text-[var(--foreground)]">${wdT('ui.watchdog_controller.actions_title', 'Aktionen & Content-Generierung')}</div>
          
          <!-- 1. LinkedIn Post generieren -->
          <button 
            type="button" 
            onclick="triggerSingleFindingAction('${finding.id}', 'linkedin_post')"
            class="w-full py-2 px-3 rounded-xl bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900 hover:opacity-90 font-mono text-xs font-bold flex items-center justify-center gap-2 transition shadow-xs cursor-pointer"
          >
            <i data-lucide="share-2" class="w-3.5 h-3.5"></i>
            <span>${wdT('ui.watchdog_controller.action_linkedin', '📱 Als LinkedIn-Post generieren')}</span>
          </button>

          <!-- 2. Strategie-Dossier für Robert -->
          <button 
            type="button" 
            onclick="triggerSingleFindingAction('${finding.id}', 'robert_dossier')"
            class="w-full py-1.5 px-3 rounded-xl border border-[var(--border)] hover:bg-[var(--secondary)] text-[var(--foreground)] font-mono text-xs font-semibold flex items-center justify-center gap-2 transition cursor-pointer shadow-2xs"
          >
            <i data-lucide="file-check" class="w-3.5 h-3.5"></i>
            <span>${wdT('ui.watchdog_controller.action_dossier', '📊 Strategische Analyse für Robert')}</span>
          </button>

          <!-- 3. In Sammelkorb legen / entfernen -->
          <button 
            type="button" 
            onclick="toggleFindingInBasket('${finding.id}')"
            class="w-full py-1.5 px-3 rounded-xl border border-[var(--border)] hover:bg-[var(--secondary)] text-[var(--foreground)] font-mono text-xs font-medium flex items-center justify-center gap-2 transition cursor-pointer"
          >
            <i data-lucide="shopping-bag" class="w-3.5 h-3.5 text-amber-500"></i>
            <span>${inBasket ? wdT('ui.watchdog_controller.basket_remove', 'Aus Sammelkorb entfernen') : wdT('ui.watchdog_controller.basket_add_bundle', 'In Sammelkorb für Bündel-Post')}</span>
          </button>

          ${finding.link ? `
            <a 
              href="${escapeHtml(finding.link)}" 
              target="_blank" 
              rel="noreferrer" 
              class="w-full py-1 px-3 text-center text-[11px] font-mono text-[var(--muted-foreground)] hover:text-[var(--foreground)] hover:underline block pt-1"
            >
              ${wdT('ui.watchdog_controller.open_article', 'Originalartikel im Browser aufrufen ↗')}
            </a>
          ` : ''}
        </div>
      </div>
    `;

    if (window.lucide) window.lucide.createIcons();
  };

  window.toggleFindingInBasket = function(findingId) {
    if (!watchdogConfig) return;
    const basket = [...(watchdogConfig.basket || [])];
    const idx = basket.findIndex(b => b.id === findingId);

    if (idx >= 0) {
      basket.splice(idx, 1);
    } else {
      const finding = (watchdogConfig.recent_findings || []).find(f => f.id === findingId);
      if (finding) basket.push(finding);
    }

    saveWatchdogConfig({ ...watchdogConfig, basket });
  };

  window.dispatchWatchdogBasket = async function() {
    if (!watchdogConfig) return;
    const basket = watchdogConfig.basket || [];
    if (basket.length === 0) return;

    const btn = document.getElementById('btn-wd-dispatch-basket');
    if (btn) {
      btn.disabled = true;
      btn.textContent = wdT('ui.watchdog_controller.dispatch_busy', 'Übergebe...');
    }

    try {
      const res = await fetch('/api/v1/watchdog/dispatch_action', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action_type: 'bundle_content',
          findings: basket,
          target_profile: 'storyteller_ghostwriter'
        })
      });

      if (res.ok) {
        const data = await res.json();
        alert(wdT('ui.watchdog_controller.dispatch_success', 'Bündel aus {count} Funden erfolgreich an Storyteller & Ghostwriter übergeben!\nTask-ID: {taskId}', { count: basket.length, taskId: data.task_id }));
        // Leere den Korb nach erfolgreichem Versand
        saveWatchdogConfig({ ...watchdogConfig, basket: [] });
      }
    } catch (e) {
      alert(wdT('ui.watchdog_controller.dispatch_error', 'Fehler bei der Übergabe: {message}', { message: e }));
    } finally {
      if (btn) btn.textContent = wdT('ui.watchdog_controller.dispatch_start', 'Synthese starten');
    }
  };

  window.triggerSingleFindingAction = async function(findingId, actionType) {
    const finding = (watchdogConfig?.recent_findings || []).find(f => f.id === findingId);
    if (!finding) return;

    try {
      const res = await fetch('/api/v1/watchdog/dispatch_action', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action_type: actionType,
          findings: [finding]
        })
      });

      if (res.ok) {
        const data = await res.json();
        const roleLabel = actionType === 'linkedin_post' ? 'Storyteller & Ghostwriter' : 'Robert (CEO)';
        alert(wdT('ui.watchdog_controller.task_success', 'Aufgabe erfolgreich an {role} übergeben!\nTask-ID: {taskId}\nTitel: {title}', { role: roleLabel, taskId: data.task_id, title: data.title }));
      }
    } catch (e) {
      alert(wdT('ui.watchdog_controller.task_error', 'Fehler bei der Aufgaben-Erstellung: {message}', { message: e }));
    }
  };

  window.toggleWatchdogSourcesCollapse = function() {
    const col = document.getElementById('watchdog-sources-col');
    const expHead = document.getElementById('watchdog-sources-expanded-header');
    const colHead = document.getElementById('watchdog-sources-collapsed-header');
    const body = document.getElementById('watchdog-sources-body');
    const footer = document.getElementById('watchdog-sources-footer');

    if (!col) return;
    const isCollapsed = col.classList.contains('w-[56px]');

    if (isCollapsed) {
      col.classList.remove('w-[56px]', 'min-w-[56px]', 'max-w-[56px]');
      col.classList.add('w-[240px]', 'min-w-[240px]', 'max-w-[240px]');
      if (expHead) expHead.classList.remove('hidden');
      if (colHead) colHead.classList.add('hidden');
      if (body) body.classList.remove('hidden');
      if (footer) footer.classList.remove('hidden');
    } else {
      col.classList.remove('w-[240px]', 'min-w-[240px]', 'max-w-[240px]');
      col.classList.add('w-[56px]', 'min-w-[56px]', 'max-w-[56px]');
      if (expHead) expHead.classList.add('hidden');
      if (colHead) colHead.classList.remove('hidden');
      if (body) body.classList.add('hidden');
      if (footer) footer.classList.add('hidden');
    }
    if (window.lucide) window.lucide.createIcons();
  };

  window.filterWatchdogByCategory = function(cat) {
    activeCategory = cat;
    const label = document.getElementById('wd-cat-active-label');
    if (label) label.textContent = cat === 'all' ? wdT('ui.watchdog_controller.filter_all', 'Alle') : cat;

    document.querySelectorAll('.wd-cat-btn').forEach(btn => {
      const match = (btn.getAttribute('onclick') || '').includes(`'${cat}'`);
      if (match) {
        btn.className = "wd-cat-btn px-2 py-0.5 rounded text-[10px] font-mono border border-[var(--border)] bg-[var(--secondary)] text-[var(--foreground)] font-bold cursor-pointer transition";
      } else {
        btn.className = "wd-cat-btn px-2 py-0.5 rounded text-[10px] font-mono border border-[var(--border)] hover:bg-[var(--secondary)] text-[var(--muted-foreground)] cursor-pointer transition";
      }
    });

    renderWatchdogSources();
    renderWatchdogFindings();
  };

  window.filterWatchdogFindingsList = function(q) {
    searchQuery = q.trim();
    renderWatchdogFindings();
  };

  window.toggleWatchdogAddForm = function(force) {
    const form = document.getElementById('wd-inline-add-form');
    if (!form) return;
    if (typeof force === 'boolean') {
      if (force) form.classList.remove('hidden');
      else form.classList.add('hidden');
    } else {
      form.classList.toggle('hidden');
    }
  };

  window.submitWatchdogNewTarget = function() {
    if (!watchdogConfig) return;
    const nameInput = document.getElementById('wd-input-name');
    const catInput = document.getElementById('wd-input-category');
    const typeSelect = document.getElementById('wd-input-type');
    const queryInput = document.getElementById('wd-input-query');

    const name = nameInput ? nameInput.value.trim() : '';
    const query = queryInput ? queryInput.value.trim() : '';
    if (!name || !query) {
      alert(wdT('ui.watchdog_controller.add_target_validation', 'Bitte Name und Suchbegriff/URL eingeben.'));
      return;
    }

    const newTarget = {
      id: `target-${Date.now().toString(36)}`,
      name: name,
      category: catInput ? catInput.value.trim() || 'Markt & Bau' : 'Markt & Bau',
      type: typeSelect ? typeSelect.value : 'search_feed',
      query_or_url: query,
      active: true,
      last_check: null,
      last_status: 'Neu angelegt'
    };

    const updated = {
      ...watchdogConfig,
      targets: [...(watchdogConfig.targets || []), newTarget]
    };

    saveWatchdogConfig(updated);
    if (nameInput) nameInput.value = '';
    if (queryInput) queryInput.value = '';
    window.toggleWatchdogAddForm(false);
  };

  window.toggleWatchdogGlobalEnabled = function() {
    if (!watchdogConfig) return;
    saveWatchdogConfig({ ...watchdogConfig, enabled: !watchdogConfig.enabled });
  };

  window.toggleWatchdogTarget = function(targetId) {
    if (!watchdogConfig) return;
    const targets = (watchdogConfig.targets || []).map(t => 
      t.id === targetId ? { ...t, active: !t.active } : t
    );
    saveWatchdogConfig({ ...watchdogConfig, targets });
  };

  window.deleteWatchdogTarget = function(targetId) {
    if (!watchdogConfig) return;
    const targets = (watchdogConfig.targets || []).filter(t => t.id !== targetId);
    saveWatchdogConfig({ ...watchdogConfig, targets });
  };

  window.setWatchdogInterval = function(mins) {
    if (!watchdogConfig) return;
    saveWatchdogConfig({ ...watchdogConfig, interval_minutes: mins });
  };

  window.toggleWatchdogChannel = function(chan, enabled) {
    if (!watchdogConfig) return;
    const channels = { ...(watchdogConfig.channels || {}), [chan]: enabled };
    saveWatchdogConfig({ ...watchdogConfig, channels });
  };

  window.triggerWatchdogRunNow = async function() {
    const icon = document.getElementById('wd-scan-spin-icon');
    const label = document.getElementById('wd-scan-btn-label');
    if (icon) icon.classList.add('animate-spin');
    if (label) label.textContent = wdT('ui.watchdog_controller.scan_running', 'Scannt...');

    try {
      const res = await fetch('/api/v1/watchdog/run_now', { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        if (data.config) {
          watchdogConfig = data.config;
          renderWatchdogView();
        }
      }
    } catch (e) {
      console.error('[Watchdog] Scan-Fehler:', e);
    } finally {
      setTimeout(() => {
        if (icon) icon.classList.remove('animate-spin');
        if (label) label.textContent = wdT('ui.watchdog_controller.scan_button', 'Prüfen');
      }, 1500);
    }
  };

  // Optionen Modal
  window.openWatchdogSettingsModal = function() {
    const modal = document.getElementById('watchdog-settings-modal');
    if (modal) {
      modal.classList.remove('hidden');
      renderWatchdogSettingsModal();
      if (window.lucide) window.lucide.createIcons();
    }
  };

  window.closeWatchdogSettingsModal = function() {
    const modal = document.getElementById('watchdog-settings-modal');
    if (modal) modal.classList.add('hidden');
  };

  window.saveAndCloseWatchdogSettingsModal = function() {
    if (!watchdogConfig) return;
    const kwInput = document.getElementById('wd-cfg-priority-keywords');
    const threshInput = document.getElementById('wd-cfg-basket-threshold');

    const rawKws = kwInput ? kwInput.value : '';
    const kws = rawKws.split(',').map(s => s.strip ? s.strip() : s.trim()).filter(Boolean);
    const thresh = threshInput ? Math.max(1, parseInt(threshInput.value || '3', 10)) : 3;

    saveWatchdogConfig({
      ...watchdogConfig,
      priority_keywords: kws,
      basket_threshold: thresh
    });
    window.closeWatchdogSettingsModal();
  };

  // Sprachwechsel: sichtbare Reste neu lokalisieren (Engine uebersetzt nur
  // data-i18n*-Anker, dieser Controller rendert eigene Template-Strings).
  window.addEventListener('archon:language-changed', () => {
    if (!watchdogConfig) return;
    renderWatchdogView();
    switchWatchdogSubTab(currentWatchdogTab);
  });

  window.openWatchdogModal = function() {
    if (typeof window.setTab === 'function') {
      window.setTab('watchdog');
    }
  };

})();
