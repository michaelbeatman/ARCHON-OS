/**
 * static/js/demo_banner.js
 * Milestone 47 — "Zero-Install" Read-Only Live-Demo Banner, Showcase Modal & 403 Toast Guard.
 *
 * Automatically checks `/api/demo/status` on page load. When `demo_mode === true`:
 * 1. Renders a sleek, non-intrusive top bar badge (EN/DE) with 1-click Showcase Modal & GitHub CTA.
 * 2. Intercepts `fetch()` 403 (`demo_read_only` / `demo_blocked`) via cloned streams to show a
 *    friendly bilingual toast without breaking caller JSON parsing.
 */

(function () {
  'use strict';

  const GITHUB_URL = 'https://github.com/michaelbeatman/ARCHON-OS';
  const BANNER_ID = 'archon-live-demo-banner';
  const MODAL_ID = 'archon-live-demo-modal';
  const TOAST_HOST_ID = 'archon-live-demo-toasts';

  const COPY = {
    en: {
      badge: 'LIVE DEMO',
      bannerText: 'LIVE DEMO MODE (Read-Only · Mittelstand Muster GmbH · Zero Token Cost) — Clone on GitHub for full autonomous execution',
      inspectBtn: 'Showcase Debate & KPIs',
      githubBtn: 'Clone on GitHub',
      modalTitle: 'Mittelstand Muster Precision GmbH — Sovereign AI Showcase',
      modalSub: 'Zero-Egress Ollama + OmniRoute · 6-Phase C-Level Boardroom · GoBD SHA-256 Audit Trail',
      tabDebate: '6-Phase AI Boardroom',
      tabKanban: 'Kanban & Cost-Guard (8)',
      tabErp: 'CRM, Pipeline & GoBD ERP',
      roiHeading: 'Chairman Synthesis & Verified 2026 ROI Matrix',
      colMetric: 'KPI / Dimension',
      colBase: '2025 Baseline',
      colTarget: '2026 Archon Target',
      colImpact: 'Impact',
      kpiOllama: 'Local Ollama Share',
      kpiSaved: 'SaaS Spend Avoided',
      kpiApiCost: 'Live Demo Token Cost',
      kpiGobd: 'GoBD Merkle Integrity',
      contactsTitle: 'B2B Key Accounts (6)',
      dealsTitle: 'Active Sales Pipeline (5)',
      invoicesTitle: 'GoBD-Sealed ERP Quotes & Invoices (5)',
      closeLabel: 'Close',
      toastReadOnlyTitle: 'Read-Only Live Demo Mode',
      toastBlockedTitle: 'Security Sandbox Locked in Public Demo',
      toastDefaultBody: 'Mutations and container execution are disabled on this public node. Clone Archon OS on GitHub for full local execution.',
      loading: 'Loading showcase dataset...'
    },
    de: {
      badge: 'LIVE-DEMO',
      bannerText: 'LIVE-DEMO-MODUS (Schreibgeschützt · Mittelstand Muster GmbH · Null Token-Kosten) — Auf GitHub klonen für volle autonome Ausführung',
      inspectBtn: 'Showcase-Debatte & KPIs',
      githubBtn: 'Auf GitHub klonen',
      modalTitle: 'Mittelstand Muster GmbH — Souveränes KI-Referenzcockpit',
      modalSub: 'Zero-Egress Ollama + OmniRoute · 6-Phasen-KI-Boardroom · GoBD-SHA-256-Prüfpfad',
      tabDebate: '6-Phasen KI-Boardroom',
      tabKanban: 'Kanban & Cost-Guard (8)',
      tabErp: 'CRM, Pipeline & GoBD-ERP',
      roiHeading: 'Chairman-Synthese & Verifizierte ROI-Matrix 2026',
      colMetric: 'Kennzahl / Dimension',
      colBase: 'Ist-Zustand 2025',
      colTarget: 'Archon-Ziel 2026',
      colImpact: 'Effekt',
      kpiOllama: 'Lokaler Ollama-Anteil',
      kpiSaved: 'SaaS-Ersparnis / Monat',
      kpiApiCost: 'Live-Demo Token-Kosten',
      kpiGobd: 'GoBD-Merkle-Status',
      contactsTitle: 'B2B-Schlüsselkunden (6)',
      dealsTitle: 'Aktive Vertriebspipeline (5)',
      invoicesTitle: 'GoBD-versiegelte ERP-Belege (5)',
      closeLabel: 'Schließen',
      toastReadOnlyTitle: 'Schreibgeschützter Live-Demo-Modus',
      toastBlockedTitle: 'Sicherheits-Sperre in der öffentlichen Demo',
      toastDefaultBody: 'Schreibzugriffe und Code-Ausführung sind auf diesem Demo-Knoten gesperrt. Klonen Sie Archon OS auf GitHub für volle Ausführung.',
      loading: 'Lade Showcase-Datensatz...'
    }
  };

  let demoStatus = null;
  let showcaseCache = {};
  let activeLang = detectLang();
  let activeModalTab = 'debate';

  function detectLang() {
    const i18nLang = window.archonI18n && window.archonI18n.currentLang;
    const stored = typeof localStorage !== 'undefined' ? localStorage.getItem('archon_language') : '';
    const docLang = (typeof document !== 'undefined' && document.documentElement && document.documentElement.lang) || '';
    const raw = String(i18nLang || stored || docLang || 'en').toLowerCase();
    return raw.startsWith('de') ? 'de' : 'en';
  }

  function t(key) {
    const dict = COPY[activeLang] || COPY.en;
    return dict[key] || COPY.en[key] || key;
  }

  function escapeHtml(val) {
    return String(val == null ? '' : val)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function formatEur(amount) {
    const num = Number(amount || 0);
    try {
      return new Intl.NumberFormat(activeLang === 'de' ? 'de-DE' : 'en-US', {
        style: 'currency',
        currency: 'EUR',
        maximumFractionDigits: 0
      }).format(num);
    } catch (_err) {
      return 'EUR ' + Math.round(num).toLocaleString();
    }
  }

  function injectStyles() {
    if (document.getElementById('archon-live-demo-styles')) return;
    const style = document.createElement('style');
    style.id = 'archon-live-demo-styles';
    style.textContent = [
      '#' + BANNER_ID + ' {',
      '  position: sticky; top: 0; z-index: 9990;',
      '  display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap;',
      '  padding: 7px 14px; font-size: 12px; line-height: 1.4;',
      '  background: linear-gradient(90deg, #0f172a 0%, #1e1b4b 55%, #0f172a 100%);',
      '  color: #f8fafc; border-bottom: 1px solid rgba(99, 102, 241, 0.45);',
      '  box-shadow: 0 2px 10px rgba(2, 6, 23, 0.35); font-family: ui-sans-serif, system-ui, sans-serif;',
      '}',
      '.archon-demo-pill {',
      '  display: inline-flex; align-items: center; gap: 6px; padding: 2px 8px; border-radius: 999px;',
      '  font-size: 10px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase;',
      '  background: rgba(16, 185, 129, 0.18); color: #34d399; border: 1px solid rgba(52, 211, 153, 0.4);',
      '}',
      '.archon-demo-dot { width: 6px; height: 6px; border-radius: 50%; background: #34d399; }',
      '.archon-demo-btn {',
      '  display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; border-radius: 6px;',
      '  font-size: 11px; font-weight: 600; cursor: pointer; text-decoration: none; transition: all 0.15s ease;',
      '  border: 1px solid rgba(148, 163, 184, 0.35); background: rgba(30, 41, 59, 0.85); color: #f1f5f9;',
      '}',
      '.archon-demo-btn:hover { background: rgba(51, 65, 85, 0.95); border-color: #818cf8; }',
      '.archon-demo-btn-primary {',
      '  background: #4f46e5; border-color: #6366f1; color: #ffffff;',
      '}',
      '.archon-demo-btn-primary:hover { background: #4338ca; }',
      '#' + MODAL_ID + ' {',
      '  position: fixed; inset: 0; z-index: 9998; display: flex; align-items: center; justify-content: center;',
      '  padding: 16px; background: rgba(2, 6, 23, 0.76); backdrop-filter: blur(4px);',
      '  font-family: ui-sans-serif, system-ui, sans-serif; color: #e2e8f0;',
      '}',
      '.archon-demo-dialog {',
      '  width: 100%; max-width: 980px; max-height: 88vh; display: flex; flex-direction: column;',
      '  background: #0f172a; border: 1px solid rgba(99, 102, 241, 0.4); border-radius: 12px;',
      '  box-shadow: 0 24px 60px rgba(0, 0, 0, 0.65); overflow: hidden;',
      '}',
      '.archon-demo-card {',
      '  background: rgba(30, 41, 59, 0.65); border: 1px solid rgba(148, 163, 184, 0.2);',
      '  border-radius: 8px; padding: 12px;',
      '}',
      '#' + TOAST_HOST_ID + ' {',
      '  position: fixed; right: 16px; bottom: 16px; z-index: 9999;',
      '  display: flex; flex-direction: column; gap: 8px; max-width: 390px; pointer-events: none;',
      '}',
      '.archon-demo-toast {',
      '  pointer-events: auto; background: #0f172a; color: #f8fafc;',
      '  border: 1px solid rgba(245, 158, 11, 0.55); border-left: 4px solid #f59e0b;',
      '  border-radius: 8px; padding: 10px 12px; font-size: 12px; line-height: 1.45;',
      '  box-shadow: 0 12px 28px rgba(2, 6, 23, 0.55); font-family: ui-sans-serif, system-ui, sans-serif;',
      '}'
    ].join('\n');
    document.head.appendChild(style);
  }

  function showDemoToast(statusType, serverMessage) {
    if (typeof document === 'undefined' || !document.body) return;
    injectStyles();
    let host = document.getElementById(TOAST_HOST_ID);
    if (!host) {
      host = document.createElement('div');
      host.id = TOAST_HOST_ID;
      document.body.appendChild(host);
    }
    const isBlocked = statusType === 'demo_blocked';
    const title = isBlocked ? t('toastBlockedTitle') : t('toastReadOnlyTitle');
    const body = serverMessage || t('toastDefaultBody');
    const repoUrl = (demoStatus && demoStatus.repo_url) || GITHUB_URL;

    const toast = document.createElement('div');
    toast.className = 'archon-demo-toast';
    toast.innerHTML =
      '<div style="font-weight:700;color:#fbbf24;margin-bottom:3px;">' + escapeHtml(title) + '</div>' +
      '<div style="color:#cbd5e1;margin-bottom:6px;">' + escapeHtml(body) + '</div>' +
      '<a href="' + escapeHtml(repoUrl) + '" target="_blank" rel="noopener noreferrer" ' +
      'style="color:#818cf8;font-weight:600;text-decoration:underline;font-size:11px;">' +
      escapeHtml(t('githubBtn')) + ' →</a>';

    host.appendChild(toast);
    while (host.children.length > 3) {
      host.removeChild(host.firstChild);
    }
    setTimeout(function () {
      if (toast.parentNode) toast.parentNode.removeChild(toast);
    }, 5200);
  }

  function installFetchInterceptor() {
    if (typeof window === 'undefined' || !window.fetch || window.__archonDemoFetchPatched) return;
    const nativeFetch = window.fetch.bind(window);
    window.__archonDemoFetchPatched = true;

    window.fetch = async function (...args) {
      const response = await nativeFetch(...args);
      if (response && response.status === 403) {
        try {
          const cloned = response.clone();
          const data = await cloned.json();
          if (data && (data.status === 'demo_read_only' || data.status === 'demo_blocked' || data.demo_mode === true)) {
            showDemoToast(data.status || 'demo_read_only', data.message || data.detail);
          }
        } catch (_ignore) {
          // Non-JSON 403 response; leave untouched.
        }
      }
      return response;
    };
  }

  function renderBanner() {
    if (typeof document === 'undefined' || !document.body || !demoStatus || !demoStatus.demo_mode) return;
    injectStyles();
    let banner = document.getElementById(BANNER_ID);
    if (!banner) {
      banner = document.createElement('div');
      banner.id = BANNER_ID;
      banner.setAttribute('role', 'region');
      banner.setAttribute('aria-label', 'Archon OS Live Demo Banner');
      document.body.insertBefore(banner, document.body.firstChild);
    }
    const repoUrl = demoStatus.repo_url || GITHUB_URL;
    const nextLang = activeLang === 'de' ? 'en' : 'de';

    banner.innerHTML =
      '<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">' +
        '<span class="archon-demo-pill"><span class="archon-demo-dot"></span>' + escapeHtml(t('badge')) + '</span>' +
        '<span style="font-weight:500;color:#e2e8f0;">' + escapeHtml(t('bannerText')) + '</span>' +
      '</div>' +
      '<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">' +
        '<button type="button" id="archon-demo-lang-btn" class="archon-demo-btn" title="Switch EN / DE">' +
          escapeHtml(activeLang.toUpperCase() + ' ⇄ ' + nextLang.toUpperCase()) +
        '</button>' +
        '<button type="button" id="archon-demo-showcase-btn" class="archon-demo-btn archon-demo-btn-primary">' +
          '⚡ ' + escapeHtml(t('inspectBtn')) +
        '</button>' +
        '<a href="' + escapeHtml(repoUrl) + '" target="_blank" rel="noopener noreferrer" class="archon-demo-btn">' +
          '★ ' + escapeHtml(t('githubBtn')) +
        '</a>' +
      '</div>';

    const langBtn = document.getElementById('archon-demo-lang-btn');
    if (langBtn) {
      langBtn.onclick = function () {
        activeLang = nextLang;
        renderBanner();
        if (document.getElementById(MODAL_ID)) {
          openShowcaseModal(activeModalTab);
        }
      };
    }
    const showcaseBtn = document.getElementById('archon-demo-showcase-btn');
    if (showcaseBtn) {
      showcaseBtn.onclick = function () {
        openShowcaseModal('debate');
      };
    }
  }

  async function loadShowcase(lang) {
    if (showcaseCache[lang]) return showcaseCache[lang];
    const res = await fetch('/api/demo/showcase?lang=' + encodeURIComponent(lang));
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    showcaseCache[lang] = data;
    return data;
  }

  function renderDebateTab(data) {
    const debate = (data.boardroom_debates && data.boardroom_debates[0]) || {};
    const phases = Array.isArray(debate.phases) ? debate.phases : [];
    const roi = Array.isArray(debate.roi_table) ? debate.roi_table : [];

    const phasesHtml = phases.map(function (p) {
      return (
        '<div class="archon-demo-card" style="margin-bottom:8px;">' +
          '<div style="display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap;margin-bottom:4px;">' +
            '<strong style="color:#a5b4fc;font-size:12.5px;">' + escapeHtml(p.title) + '</strong>' +
            '<code style="font-size:11px;color:#34d399;background:rgba(16,185,129,0.12);padding:1px 6px;border-radius:4px;">' +
              escapeHtml(p.agent_handle + ' · ' + p.model) +
            '</code>' +
          '</div>' +
          '<div style="font-size:12px;color:#cbd5e1;line-height:1.5;">' + escapeHtml(p.summary) + '</div>' +
        '</div>'
      );
    }).join('');

    const roiRows = roi.map(function (r) {
      return (
        '<tr style="border-top:1px solid rgba(148,163,184,0.18);">' +
          '<td style="padding:7px 8px;font-weight:600;color:#f1f5f9;">' + escapeHtml(r.metric) + '</td>' +
          '<td style="padding:7px 8px;color:#94a3b8;">' + escapeHtml(r.baseline_2025) + '</td>' +
          '<td style="padding:7px 8px;color:#cbd5e1;">' + escapeHtml(r.archon_target_2026) + '</td>' +
          '<td style="padding:7px 8px;font-weight:700;color:#34d399;">' + escapeHtml(r.impact) + '</td>' +
        '</tr>'
      );
    }).join('');

    return (
      '<div class="archon-demo-card" style="margin-bottom:12px;border-color:rgba(99,102,241,0.45);">' +
        '<div style="font-size:11px;color:#818cf8;font-weight:700;text-transform:uppercase;margin-bottom:3px;">' +
          escapeHtml(debate.framework || '') +
        '</div>' +
        '<div style="font-size:13.5px;font-weight:700;color:#f8fafc;">' + escapeHtml(debate.task || '') + '</div>' +
      '</div>' +
      phasesHtml +
      '<div class="archon-demo-card" style="margin-top:12px;border-color:rgba(52,211,153,0.4);">' +
        '<div style="font-weight:700;color:#34d399;margin-bottom:8px;font-size:13px;">' + escapeHtml(t('roiHeading')) + '</div>' +
        '<div style="overflow-x:auto;">' +
          '<table style="width:100%;border-collapse:collapse;font-size:11.5px;text-align:left;">' +
            '<thead><tr style="color:#94a3b8;text-transform:uppercase;font-size:10px;">' +
              '<th style="padding:6px 8px;">' + escapeHtml(t('colMetric')) + '</th>' +
              '<th style="padding:6px 8px;">' + escapeHtml(t('colBase')) + '</th>' +
              '<th style="padding:6px 8px;">' + escapeHtml(t('colTarget')) + '</th>' +
              '<th style="padding:6px 8px;">' + escapeHtml(t('colImpact')) + '</th>' +
            '</tr></thead>' +
            '<tbody>' + roiRows + '</tbody>' +
          '</table>' +
        '</div>' +
      '</div>'
    );
  }

  function renderKanbanTab(data) {
    const tel = data.telemetry || {};
    const tasks = Array.isArray(data.kanban_tasks) ? data.kanban_tasks : [];

    const kpis =
      '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:8px;margin-bottom:12px;">' +
        '<div class="archon-demo-card"><div style="font-size:10.5px;color:#94a3b8;">' + escapeHtml(t('kpiOllama')) + '</div>' +
          '<div style="font-size:18px;font-weight:800;color:#34d399;">' + escapeHtml(tel.local_ollama_share_pct) + '%</div></div>' +
        '<div class="archon-demo-card"><div style="font-size:10.5px;color:#94a3b8;">' + escapeHtml(t('kpiSaved')) + '</div>' +
          '<div style="font-size:18px;font-weight:800;color:#818cf8;">' + escapeHtml(formatEur(tel.monthly_saas_cost_avoided_eur)) + '/mo</div></div>' +
        '<div class="archon-demo-card"><div style="font-size:10.5px;color:#94a3b8;">' + escapeHtml(t('kpiApiCost')) + '</div>' +
          '<div style="font-size:18px;font-weight:800;color:#38bdf8;">EUR 0.00</div></div>' +
        '<div class="archon-demo-card"><div style="font-size:10.5px;color:#94a3b8;">' + escapeHtml(t('kpiGobd')) + '</div>' +
          '<div style="font-size:18px;font-weight:800;color:#34d399;">' + escapeHtml(tel.gobd_merkle_chain_status || 'VALID') + '</div></div>' +
      '</div>';

    const taskCards = tasks.map(function (item) {
      return (
        '<div class="archon-demo-card" style="margin-bottom:8px;">' +
          '<div style="display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap;margin-bottom:4px;">' +
            '<span style="font-weight:700;color:#f1f5f9;font-size:12.5px;">' + escapeHtml(item.title) + '</span>' +
            '<span style="font-size:10.5px;font-family:monospace;color:#fbbf24;text-transform:uppercase;">[' +
              escapeHtml(item.status) + '] · ' + escapeHtml(item.assignee_handle || item.assignee) +
            '</span>' +
          '</div>' +
          '<div style="font-size:11.5px;color:#94a3b8;">' + escapeHtml(item.description) + '</div>' +
        '</div>'
      );
    }).join('');

    return kpis + taskCards;
  }

  function renderErpTab(data) {
    const contacts = Array.isArray(data.crm_contacts) ? data.crm_contacts : [];
    const deals = Array.isArray(data.deals) ? data.deals : [];
    const invoices = Array.isArray(data.invoices) ? data.invoices : [];

    const contactsHtml = contacts.map(function (c) {
      return (
        '<div class="archon-demo-card">' +
          '<div style="font-weight:700;color:#f8fafc;font-size:12px;">' + escapeHtml(c.company) + ' (' + escapeHtml(c.country) + ')</div>' +
          '<div style="font-size:11px;color:#cbd5e1;">' + escapeHtml(c.contact_name + ' · ' + c.role) + '</div>' +
          '<div style="font-size:10.5px;color:#34d399;margin-top:3px;">' + escapeHtml(c.account_tier) + ' · ' + escapeHtml(formatEur(c.annual_potential_eur)) + '/yr</div>' +
        '</div>'
      );
    }).join('');

    const dealsHtml = deals.map(function (d) {
      return (
        '<div class="archon-demo-card" style="margin-bottom:6px;display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap;">' +
          '<div><strong style="color:#f1f5f9;font-size:12px;">' + escapeHtml(d.title) + '</strong>' +
          '<div style="font-size:11px;color:#94a3b8;">' + escapeHtml(d.partner_name + ' · ' + d.assigned_agent) + '</div></div>' +
          '<div style="text-align:right;font-size:11.5px;"><span style="color:#818cf8;font-weight:700;text-transform:uppercase;">' +
            escapeHtml(d.stage) + '</span> · <strong>' + escapeHtml(formatEur(d.deal_value)) + '</strong></div>' +
        '</div>'
      );
    }).join('');

    const invHtml = invoices.map(function (inv) {
      return (
        '<div class="archon-demo-card" style="margin-bottom:6px;display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap;">' +
          '<div><strong style="color:#f8fafc;font-size:12px;">' + escapeHtml(inv.doc_number + ' · ' + inv.customer_name) + '</strong>' +
          '<div style="font-size:10.5px;font-family:monospace;color:#34d399;">GoBD ' + escapeHtml(inv.gobd_sha256_preview) + '</div></div>' +
          '<div style="text-align:right;font-size:11.5px;"><strong>' + escapeHtml(formatEur(inv.amount_gross)) + '</strong>' +
          '<div style="font-size:10.5px;color:#94a3b8;">' + escapeHtml(inv.datev_account + ' · ' + inv.status) + '</div></div>' +
        '</div>'
      );
    }).join('');

    return (
      '<h4 style="margin:0 0 8px;font-size:12.5px;color:#a5b4fc;">' + escapeHtml(t('contactsTitle')) + '</h4>' +
      '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:8px;margin-bottom:14px;">' + contactsHtml + '</div>' +
      '<h4 style="margin:0 0 8px;font-size:12.5px;color:#a5b4fc;">' + escapeHtml(t('dealsTitle')) + '</h4>' +
      dealsHtml +
      '<h4 style="margin:12px 0 8px;font-size:12.5px;color:#a5b4fc;">' + escapeHtml(t('invoicesTitle')) + '</h4>' +
      invHtml
    );
  }

  async function openShowcaseModal(tabName) {
    activeModalTab = tabName || activeModalTab || 'debate';
    injectStyles();
    let overlay = document.getElementById(MODAL_ID);
    if (!overlay) {
      overlay = document.createElement('div');
      overlay.id = MODAL_ID;
      overlay.onclick = function (ev) {
        if (ev.target === overlay) closeShowcaseModal();
      };
      document.body.appendChild(overlay);
    }

    overlay.innerHTML =
      '<div class="archon-demo-dialog">' +
        '<div style="padding:14px 18px;border-bottom:1px solid rgba(148,163,184,0.2);display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;">' +
          '<div>' +
            '<div style="font-size:15px;font-weight:800;color:#f8fafc;">' + escapeHtml(t('modalTitle')) + '</div>' +
            '<div style="font-size:11.5px;color:#94a3b8;">' + escapeHtml(t('modalSub')) + '</div>' +
          '</div>' +
          '<button type="button" id="archon-demo-modal-close" class="archon-demo-btn">✕ ' + escapeHtml(t('closeLabel')) + '</button>' +
        '</div>' +
        '<div style="padding:8px 18px;border-bottom:1px solid rgba(148,163,184,0.16);display:flex;gap:8px;flex-wrap:wrap;">' +
          '<button type="button" data-demo-tab="debate" class="archon-demo-btn ' + (activeModalTab === 'debate' ? 'archon-demo-btn-primary' : '') + '">' + escapeHtml(t('tabDebate')) + '</button>' +
          '<button type="button" data-demo-tab="kanban" class="archon-demo-btn ' + (activeModalTab === 'kanban' ? 'archon-demo-btn-primary' : '') + '">' + escapeHtml(t('tabKanban')) + '</button>' +
          '<button type="button" data-demo-tab="erp" class="archon-demo-btn ' + (activeModalTab === 'erp' ? 'archon-demo-btn-primary' : '') + '">' + escapeHtml(t('tabErp')) + '</button>' +
        '</div>' +
        '<div id="archon-demo-modal-body" style="padding:16px 18px;overflow-y:auto;flex:1;font-size:12.5px;">' +
          escapeHtml(t('loading')) +
        '</div>' +
      '</div>';

    const closeBtn = document.getElementById('archon-demo-modal-close');
    if (closeBtn) closeBtn.onclick = closeShowcaseModal;

    overlay.querySelectorAll('[data-demo-tab]').forEach(function (btn) {
      btn.onclick = function () {
        openShowcaseModal(btn.getAttribute('data-demo-tab'));
      };
    });

    const bodyEl = document.getElementById('archon-demo-modal-body');
    try {
      const data = await loadShowcase(activeLang);
      if (!bodyEl) return;
      if (activeModalTab === 'kanban') {
        bodyEl.innerHTML = renderKanbanTab(data);
      } else if (activeModalTab === 'erp') {
        bodyEl.innerHTML = renderErpTab(data);
      } else {
        bodyEl.innerHTML = renderDebateTab(data);
      }
    } catch (err) {
      if (bodyEl) bodyEl.textContent = 'Error loading showcase: ' + err.message;
    }
  }

  function closeShowcaseModal() {
    const el = document.getElementById(MODAL_ID);
    if (el && el.parentNode) el.parentNode.removeChild(el);
  }

  async function initDemoBanner() {
    activeLang = detectLang();
    try {
      const res = await fetch('/api/demo/status?lang=' + encodeURIComponent(activeLang));
      if (!res.ok) return;
      const data = await res.json();
      demoStatus = data;
      if (data && data.demo_mode === true) {
        installFetchInterceptor();
        renderBanner();
        if (window.archonI18n && typeof window.archonI18n.registerRenderer === 'function') {
          window.archonI18n.registerRenderer('archon_demo_banner', function () {
            activeLang = detectLang();
            renderBanner();
          });
        }
      }
    } catch (_err) {
      // Silent no-op when offline or endpoint not wired yet.
    }
  }

  if (typeof window !== 'undefined') {
    window.archonDemoBanner = {
      init: initDemoBanner,
      openShowcaseModal: openShowcaseModal,
      closeShowcaseModal: closeShowcaseModal,
      showDemoToast: showDemoToast
    };
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', initDemoBanner);
    } else {
      initDemoBanner();
    }
  }
})();
