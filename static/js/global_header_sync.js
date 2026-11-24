/* Global Header Sync Button & Unified View Header Polish */
(function () {
  if (window.__archonGlobalHeaderSyncInit) return;
  window.__archonGlobalHeaderSyncInit = true;

  function triggerSpin(btn) {
    if (!btn) return;
    const img = btn.querySelector('img');
    if (!img) return;
    if (typeof img.animate === 'function') {
      img.animate(
        [{ transform: 'rotate(0deg)' }, { transform: 'rotate(-360deg)' }],
        { duration: 750, easing: 'ease-in-out' }
      );
    }
  }

  async function syncActiveView(btn) {
    triggerSpin(btn);
    const tab = (typeof currentTab !== 'undefined' && currentTab) ? currentTab : 'mission-control';
    try {
      const loaders = {
        'mission-control': () => typeof fetchMissionControlData === 'function' && fetchMissionControlData(),
        'operations': () => typeof loadOperationsData === 'function' && loadOperationsData(),
        'plugins': () => {
          if (typeof loadPluginSettingsRegistry === 'function') loadPluginSettingsRegistry();
          if (typeof loadSystemSettings === 'function') loadSystemSettings();
        },
        'guardian': () => typeof loadGuardianConfig === 'function' && loadGuardianConfig(),
        'log-stream': () => typeof loadAuditLogs === 'function' && loadAuditLogs(),
        'inbox': () => typeof loadInboxData === 'function' && loadInboxData(),
        'agent-profiles': () => typeof loadAgentProfiles === 'function' && loadAgentProfiles(),
        'library': () => typeof loadLibraryData === 'function' && loadLibraryData(),
        'watchdog': () => typeof initWatchdogView === 'function' && initWatchdogView(),
        'finance': () => typeof initFinanceView === 'function' && initFinanceView(),
        'approval-policies': () => typeof initApprovalPoliciesView === 'function' && initApprovalPoliciesView(),
        'addresses': () => typeof initAddressesView === 'function' && initAddressesView(),
        'items': () => typeof initItemsView === 'function' && initItemsView(),
        'operations-erp': () => typeof initOperationsErpView === 'function' && initOperationsErpView(),
        'corporate': () => typeof initCorporateView === 'function' && initCorporateView(),
        'research': () => typeof loadResearchProjects === 'function' && loadResearchProjects(),
        'showroom': () => typeof loadShowroomArtifacts === 'function' && loadShowroomArtifacts(),
      };
      const fn = loaders[tab];
      if (fn) {
        await Promise.resolve(fn());
      }
      if (typeof fetchSystemHealth === 'function') {
        fetchSystemHealth(true);
      }
    } catch (err) {
      console.warn('[GlobalSync] Aktualisierung fehlgeschlagen:', err);
    }
  }

  window.syncActiveView = syncActiveView;

  function createSyncButton() {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'archon-global-sync-btn px-1.5 py-1 border-0 bg-transparent hover:opacity-80 transition cursor-pointer flex flex-col items-center justify-center gap-0.5 shrink-0';
    btn.title = 'Inhalte aktualisieren (Sync)';
    btn.setAttribute('aria-label', 'Sync');
    btn.onclick = function () { syncActiveView(btn); };
    btn.innerHTML = '<img src="/static/img/sync_icon.png" alt="Sync" class="w-7 h-7 object-contain pointer-events-none"><span class="font-bold uppercase pointer-events-none" style="font-size: 9px; line-height: 1; letter-spacing: 0.06em; color: #DE2A34;">SYNC</span>';
    return btn;
  }

  function enhanceViewHeaders() {
    const main = document.querySelector('main');
    if (!main) return;
    // Find top-level view containers (#view-*) and ensure their first header bar has the rightmost SYNC button
    const views = main.querySelectorAll('[id^="view-"]:not([id$="-mount"])');
    views.forEach((view) => {
      // Locate the top header bar (<div id="*-global-header"> or <header id="*-global-header">)
      const header = Array.from(view.children).find((el) =>
        (el.tagName === 'DIV' || el.tagName === 'HEADER') &&
        ((el.id && el.id.endsWith('-global-header')) ||
          (el.classList.contains('border-b') && (el.classList.contains('flex') || el.classList.contains('justify-between'))))
      );
      if (!header) return;

      const isAgentProfiles = header.id === 'agent-profiles-global-header';
      if (!isAgentProfiles) {
        // Clean borderless Operations-Header-Look
        header.style.setProperty('border-width', '0px', 'important');
        header.style.setProperty('border-bottom-width', '0px', 'important');

        const titleEl = header.querySelector('h1, h2');
        if (titleEl && !titleEl.dataset.archonStyled) {
          titleEl.dataset.archonStyled = '1';
          titleEl.classList.remove('text-sm', 'text-base', 'text-lg', 'uppercase', 'font-mono', 'font-black');
          titleEl.classList.add('tracking-tight', 'leading-none');
          titleEl.style.setProperty('font-size', '28px', 'important');
          titleEl.style.setProperty('font-weight', '500', 'important');
          titleEl.style.setProperty('line-height', '1.05', 'important');
          titleEl.style.setProperty('margin', '0', 'important');
        }
        const helpBtn = header.querySelector('button[onclick*="openContextHelp"]');
        if (helpBtn && !helpBtn.dataset.archonStyled) {
          helpBtn.dataset.archonStyled = '1';
          helpBtn.classList.remove('w-5', 'h-5', 'rounded-md');
          helpBtn.classList.add('w-4', 'h-4', 'rounded-full', 'self-start');
          helpBtn.style.setProperty('margin-top', '-2px', 'important');
        }
        const subEl = header.querySelector('[id$="-main-subtitle"]');
        if (subEl && subEl.textContent && /^[•·]\s*/.test(subEl.textContent.trim())) {
          subEl.textContent = subEl.textContent.trim().replace(/^[•·]\s*/, '');
        }
      }

      if (view.querySelector('.archon-global-sync-btn')) return;

      // Append global SYNC button as the outermost right element
      const children = Array.from(header.children).filter((c) => !c.classList.contains('hidden'));
      const rightGroup = children.length >= 2 ? children[children.length - 1] : null;
      if (rightGroup && rightGroup.classList.contains('flex')) {
        rightGroup.appendChild(createSyncButton());
      } else {
        const wrap = document.createElement('div');
        wrap.className = 'flex items-center gap-2 shrink-0 ml-auto';
        wrap.appendChild(createSyncButton());
        header.appendChild(wrap);
      }
    });
  }

  document.addEventListener('DOMContentLoaded', () => {
    enhanceViewHeaders();
    // Re-run when lazy views mount into the DOM
    const main = document.querySelector('main');
    if (main && typeof MutationObserver !== 'undefined') {
      let timer = null;
      const obs = new MutationObserver(() => {
        if (timer) clearTimeout(timer);
        timer = setTimeout(enhanceViewHeaders, 80);
      });
      obs.observe(main, { childList: true, subtree: true });
    }
  });
})();
