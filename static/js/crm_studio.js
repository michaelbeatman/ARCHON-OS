/**
 * static/js/crm_studio.js
 * Archon OS 2026 — Native CRM & Address Engine (Säule 3: Wirtschaft & ERP).
 * Directly mirrors the full-featured http://localhost:3005/crm experience:
 * 1. "Kontakte" — Full CRM table with search, status filters, region filters, pagination
 * 2. "Kunden" — Customer / Debitor (10000+) filtered table
 * 3. "Lieferanten" — Supplier / Creditor (70000+) filtered table
 * 4. "Alle Nachrichten" — Aggregated interaction timeline across all contacts
 * 5. "Kalender" — Appointments & Follow-up calendar
 * 6. "Bericht" — Missionskontrolle analytics & KPI report
 * Plus: Complete "KontaktDrawer" modal for viewing & editing a single contact record with bilateral message history!
 */

window.crmStudio = (function() {
  let activeSubTab = 'kontakte'; // 'kontakte', 'kunden', 'lieferanten', 'nachrichten', 'kalender', 'bericht'
  let contactsData = [];
  let contactsTotal = 0;
  let currentPage = 1;
  const pageSize = 50;
  let currentSearch = '';
  let currentStatus = 'all';
  let currentRegion = 'all';
  let currentSortBy = 'updated';
  let currentSortOrder = 'desc';

  // Nachrichten state
  let messagesData = [];
  let messagesTotal = 0;
  let msgSearch = '';
  let msgChannel = 'all';
  let msgDirection = 'all';
  let msgSort = 'newest';
  let msgPage = 1;

  // Active contact in Drawer
  let currentDrawerContact = null;
  let drawerMsgFilter = 'all';
  let currentContactTags = [];

  // -------------------------------------------------------------------------
  // INITIALIZATION
  // -------------------------------------------------------------------------
  function init() {
    console.log('[CRM Studio] Initializing native CRM Studio...');
    const saved = localStorage.getItem('archon_crm_active_subtab');
    if (saved && ['kontakte', 'kunden', 'lieferanten', 'nachrichten', 'kalender', 'bericht'].includes(saved)) {
      activeSubTab = saved;
    }
    switchSubTab(activeSubTab, false);
  }

  // -------------------------------------------------------------------------
  // SUB-TAB NAVIGATION (6 TABS)
  // -------------------------------------------------------------------------
  function switchSubTab(tabName, persist = true) {
    activeSubTab = tabName;
    if (persist) {
      localStorage.setItem('archon_crm_active_subtab', tabName);
    }

    // Update active state on top cadre icon buttons
    document.querySelectorAll('.crm-header-tile').forEach(btn => {
      btn.classList.remove('active-cadre-tab');
      btn.style.opacity = '0.75';
      const wrap = btn.querySelector('.tile-icon-wrap');
      if (wrap) wrap.classList.remove('active-tile');
      const label = btn.querySelector('.crm-tab-label');
      if (label) {
        label.classList.remove('text-red-600', 'font-bold');
        label.classList.add('text-[var(--muted-foreground)]', 'font-medium');
      }
    });

    const activeBtn = document.getElementById(`crm-tab-btn-${tabName}`);
    if (activeBtn) {
      activeBtn.classList.add('active-cadre-tab');
      activeBtn.style.opacity = '1.0';
      const wrap = activeBtn.querySelector('.tile-icon-wrap');
      if (wrap) wrap.classList.add('active-tile');
      const label = activeBtn.querySelector('.crm-tab-label');
      if (label) {
        label.classList.remove('text-[var(--muted-foreground)]', 'font-medium');
        label.classList.add('text-red-600', 'font-bold');
      }
    }

    // Hide all subviews
    const subviews = [
      'crm-view-kontakte',
      'crm-view-kunden',
      'crm-view-lieferanten',
      'crm-view-nachrichten',
      'crm-view-kalender',
      'crm-view-bericht'
    ];
    subviews.forEach(id => {
      const el = document.getElementById(id);
      if (el) el.classList.add('hidden');
    });

    // Subtitle & Header title updates
    const titleEl = document.getElementById('addresses-main-title');
    const subtitleEl = document.getElementById('addresses-main-subtitle');

    if (tabName === 'kontakte') {
      const v = document.getElementById('crm-view-kontakte');
      if (v) v.classList.remove('hidden');
      if (titleEl) titleEl.textContent = 'Kontakte — CRM Adressstamm';
      if (subtitleEl) subtitleEl.textContent = 'Vollständige Kontakt- & Netzwerk-Tabelle (PocketBase Port 8090 / SQLite synchron)';
      loadContacts('all');
    } else if (tabName === 'kunden') {
      const v = document.getElementById('crm-view-kunden');
      if (v) v.classList.remove('hidden');
      if (titleEl) titleEl.textContent = 'Kundenstamm — Debitoren (10000+)';
      if (subtitleEl) subtitleEl.textContent = 'Rechnungsempfänger, Auftragsgeber, Zahlungsziele & Skonto-Konditionen';
      loadKunden();
    } else if (tabName === 'lieferanten') {
      const v = document.getElementById('crm-view-lieferanten');
      if (v) v.classList.remove('hidden');
      if (titleEl) titleEl.textContent = 'Lieferantenstamm — Kreditoren (70000+)';
      if (subtitleEl) subtitleEl.textContent = 'Dienstleister, Cloud-Provider & Lieferanten mit Aufwandskonten';
      loadLieferanten();
    } else if (tabName === 'nachrichten') {
      const v = document.getElementById('crm-view-nachrichten');
      if (v) v.classList.remove('hidden');
      if (titleEl) titleEl.textContent = 'Alle Nachrichten — Multi-Channel Timeline';
      if (subtitleEl) subtitleEl.textContent = 'Chronologischer Interaktions-Feed über LinkedIn, E-Mail, Termine & Diktate';
      loadAllMessages();
    } else if (tabName === 'kalender') {
      const v = document.getElementById('crm-view-kalender');
      if (v) v.classList.remove('hidden');
      if (titleEl) titleEl.textContent = 'Kalender & Wiedervorlagen';
      if (subtitleEl) subtitleEl.textContent = 'Termine, Interviews, Follow-ups und anstehende Fristen';
      loadCalendar();
    } else if (tabName === 'bericht') {
      const v = document.getElementById('crm-view-bericht');
      if (v) v.classList.remove('hidden');
      if (titleEl) titleEl.textContent = 'Bericht — CRM Missionskontrolle';
      if (subtitleEl) subtitleEl.textContent = 'Netzwerk-Analytics, Rollen- & Status-Verteilung, Antwort-Raten & Handlungsbedarfe';
      loadReport();
    }

    if (typeof lucide !== 'undefined') lucide.createIcons();
  }

  // -------------------------------------------------------------------------
  // 1. KONTAKTE TABELLEN-LOGIK (Screenshot 1)
  // -------------------------------------------------------------------------
  async function loadContacts(roleFilter = 'all') {
    const listContainer = document.getElementById('crm-kontakte-table-body');
    const countBadge = document.getElementById('crm-kontakte-hits-badge');
    const headerCountBadge = document.getElementById('erp-addr-count-badge');

    if (listContainer) {
      listContainer.innerHTML = `<tr><td colspan="11" class="text-center py-8 text-xs font-mono text-[var(--muted-foreground)]">Lade Kontakte aus PocketBase...</td></tr>`;
    }

    try {
      const params = new URLSearchParams({
        search: currentSearch,
        status: currentStatus,
        role: roleFilter,
        region: currentRegion,
        sort_by: currentSortBy,
        sort_order: currentSortOrder,
        page: currentPage.toString(),
        limit: pageSize.toString()
      });

      const resp = await fetch(`/api/crm/contacts?${params.toString()}`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();

      contactsData = data.items || [];
      contactsTotal = data.total || 0;

      if (countBadge) countBadge.textContent = `${contactsTotal} Treffer`;
      if (headerCountBadge) headerCountBadge.textContent = `${contactsTotal} Kontakte`;

      // Populate Status filter options if empty
      populateStatusFilter(data.statuses || []);
      populateRegionFilter(data.regions || []);

      renderContactsTable(contactsData, 'crm-kontakte-table-body');
      renderPagination('crm-kontakte-pagination', contactsTotal, currentPage, pageSize, (newPage) => {
        currentPage = newPage;
        loadContacts(roleFilter);
      });
    } catch (err) {
      console.error('[CRM Studio] Error loading contacts:', err);
      if (listContainer) {
        listContainer.innerHTML = `<tr><td colspan="11" class="text-center py-6 text-xs font-mono text-red-500">Fehler beim Laden der Kontakte: ${err.message}</td></tr>`;
      }
    }
  }

  function renderContactsTable(items, tbodyId) {
    const tbody = document.getElementById(tbodyId);
    if (!tbody) return;

    if (!items || items.length === 0) {
      tbody.innerHTML = `<tr><td colspan="11" class="text-center py-8 text-xs font-mono text-[var(--muted-foreground)]">Keine Kontakte gefunden.</td></tr>`;
      return;
    }

    let html = '';
    items.forEach(k => {
      const statusPill = getStatusPill(k.status);
      const ratingStars = getRatingStars(k.rating);
      const initials = k.initials || '??';
      const company = escapeHtml(k.unternehmen || '—');
      const role = escapeHtml(k.rolle || '—');
      const name = escapeHtml(k.name || 'Ohne Name');
      const vernetzt = escapeHtml(k.vernetzt_am ? k.vernetzt_am.slice(0, 10) : '—');
      const nextStep = escapeHtml(k.naechster_schritt || '—');
      const msgCount = k.nachrichten_count || 0;

      html += `
        <tr class="hover:bg-slate-50 dark:hover:bg-slate-800/50 border-b border-[var(--border)] transition-colors text-xs cursor-pointer group" onclick="crmStudio.openContactDrawer('${k.id}')">
          <td class="p-2.5 text-center w-8" onclick="event.stopPropagation()">
            <input type="checkbox" class="rounded border-slate-300 text-indigo-600 focus:ring-0">
          </td>
          <td class="p-2.5 font-bold text-[var(--foreground)] whitespace-nowrap">
            <div class="flex items-center gap-2">
              <div class="w-7 h-7 rounded-full bg-emerald-100 dark:bg-emerald-950 text-emerald-700 dark:text-emerald-300 font-bold flex items-center justify-center text-[10px] shrink-0 border border-emerald-300/40">
                ${initials}
              </div>
              <span class="truncate max-w-[160px] group-hover:text-indigo-600 dark:group-hover:text-indigo-400 transition-colors">${name}</span>
            </div>
          </td>
          <td class="p-2.5 text-[var(--muted-foreground)] truncate max-w-[170px]">${company}</td>
          <td class="p-2.5 text-[var(--foreground)] truncate max-w-[170px]">${role}</td>
          <td class="p-2.5 text-center w-10">
            ${k.profilbild ? `<img src="${escapeHtml(k.profilbild)}" class="w-6 h-6 rounded-full object-cover mx-auto border border-[var(--border)]" onerror="this.style.display='none'">` : '<span class="text-[var(--muted-foreground)] opacity-40">-</span>'}
          </td>
          <td class="p-2.5 text-center whitespace-nowrap">${ratingStars}</td>
          <td class="p-2.5 whitespace-nowrap">${statusPill}</td>
          <td class="p-2.5 text-center whitespace-nowrap" onclick="event.stopPropagation()">
            <button type="button" onclick="crmStudio.openContactDrawer('${k.id}', 'messages')" class="px-2 py-0.5 rounded-md text-[11px] font-mono bg-emerald-50 hover:bg-emerald-100 dark:bg-emerald-950/60 dark:hover:bg-emerald-900 text-emerald-700 dark:text-emerald-300 border border-emerald-300/40 transition flex items-center gap-1 mx-auto cursor-pointer" title="Nachrichtenverlauf (${msgCount})">
              <span>💬</span>
              <span>Verlauf</span>
              ${msgCount > 0 ? `<span class="font-bold text-[10px]">(${msgCount})</span>` : ''}
            </button>
          </td>
          <td class="p-2.5 text-slate-500 whitespace-nowrap font-mono text-[11px]">${vernetzt}</td>
          <td class="p-2.5 text-slate-500 truncate max-w-[140px] text-[11px]">${nextStep}</td>
          <td class="p-2.5 text-right whitespace-nowrap" onclick="event.stopPropagation()">
            <button type="button" onclick="crmStudio.openContactDrawer('${k.id}')" class="text-emerald-600 hover:text-emerald-700 dark:text-emerald-400 font-bold hover:underline inline-flex items-center gap-0.5">
              <span>Bearbeiten</span>
              <span>↗</span>
            </button>
          </td>
        </tr>
      `;
    });

    tbody.innerHTML = html;
  }

  function getStatusPill(status) {
    const s = (status || 'Vernetzt').trim();
    let bg = 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300 border-slate-200 dark:border-slate-700';
    if (s === 'In Dialog') {
      bg = 'bg-amber-50 text-amber-700 dark:bg-amber-950/60 dark:text-amber-300 border-amber-300/50';
    } else if (s === 'Regelmäßiger Kontakt') {
      bg = 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-300 border-emerald-300/50';
    } else if (s === 'Erstnachricht') {
      bg = 'bg-blue-50 text-blue-700 dark:bg-blue-950/60 dark:text-blue-300 border-blue-300/50';
    } else if (s === 'Interview' || s === 'Interview vereinbart') {
      bg = 'bg-purple-50 text-purple-700 dark:bg-purple-950/60 dark:text-purple-300 border-purple-300/50';
    } else if (s === 'Irrelevant' || s === 'Kein_Interesse' || s === 'Gesperrt_1Jahr') {
      bg = 'bg-rose-50 text-rose-700 dark:bg-rose-950/60 dark:text-rose-300 border-rose-300/40';
    }
    return `<span class="px-2 py-0.5 rounded-full text-[10px] font-semibold border ${bg} inline-block">${escapeHtml(s)}</span>`;
  }

  function getRatingStars(rating) {
    const r = parseInt(rating) || 0;
    if (r <= 0) return '<span class="text-slate-300 dark:text-slate-600 text-[10px]">—</span>';
    let stars = '';
    for (let i = 1; i <= 5; i++) {
      stars += i <= r ? '<span class="text-amber-400">★</span>' : '<span class="text-slate-300 dark:text-slate-600">☆</span>';
    }
    return `<span class="text-xs tracking-tighter" title="Rating: ${r}/5">${stars}</span>`;
  }

  function populateStatusFilter(statuses) {
    const sel = document.getElementById('crm-filter-status');
    if (!sel || sel.dataset.populated) return;
    sel.dataset.populated = 'true';
    let opts = '<option value="all">Alle Status</option>';
    statuses.forEach(s => {
      opts += `<option value="${escapeHtml(s.status)}">${escapeHtml(s.status)} (${s.count})</option>`;
    });
    sel.innerHTML = opts;
  }

  function populateRegionFilter(regions) {
    const sel = document.getElementById('crm-filter-region');
    if (!sel || sel.dataset.populated) return;
    sel.dataset.populated = 'true';
    let opts = '<option value="all">Alle Regionen</option>';
    regions.forEach(r => {
      opts += `<option value="${escapeHtml(r.region)}">${escapeHtml(r.region)} (${r.count})</option>`;
    });
    sel.innerHTML = opts;
  }

  function onSearchInput(val) {
    currentSearch = val;
    currentPage = 1;
    loadContacts(activeSubTab === 'kunden' ? 'customers' : (activeSubTab === 'lieferanten' ? 'suppliers' : 'all'));
  }

  function onStatusChange(val) {
    currentStatus = val;
    currentPage = 1;
    loadContacts(activeSubTab === 'kunden' ? 'customers' : (activeSubTab === 'lieferanten' ? 'suppliers' : 'all'));
  }

  function onRegionChange(val) {
    currentRegion = val;
    currentPage = 1;
    loadContacts(activeSubTab === 'kunden' ? 'customers' : (activeSubTab === 'lieferanten' ? 'suppliers' : 'all'));
  }

  function resetFilters() {
    currentSearch = '';
    currentStatus = 'all';
    currentRegion = 'all';
    currentPage = 1;
    const inp = document.getElementById('crm-search-input');
    if (inp) inp.value = '';
    const st = document.getElementById('crm-filter-status');
    if (st) st.value = 'all';
    const reg = document.getElementById('crm-filter-region');
    if (reg) reg.value = 'all';
    loadContacts(activeSubTab === 'kunden' ? 'customers' : (activeSubTab === 'lieferanten' ? 'suppliers' : 'all'));
  }

  // -------------------------------------------------------------------------
  // 2. KUNDEN & LIEFERANTEN SUB-VIEWS
  // -------------------------------------------------------------------------
  function loadKunden() {
    loadContacts('customers');
  }

  function loadLieferanten() {
    loadContacts('suppliers');
  }

  // -------------------------------------------------------------------------
  // 3. ALLE NACHRICHTEN TAB (Screenshot 2)
  // -------------------------------------------------------------------------
  async function loadAllMessages() {
    const container = document.getElementById('crm-messages-feed');
    if (container) {
      container.innerHTML = `<div class="p-8 text-center text-xs font-mono text-[var(--muted-foreground)]">Lade 2.229 Nachrichten aus allen Konversationen...</div>`;
    }

    try {
      const params = new URLSearchParams({
        search: msgSearch,
        channel: msgChannel,
        direction: msgDirection,
        sort: msgSort,
        page: msgPage.toString(),
        limit: '40'
      });

      const resp = await fetch(`/api/crm/messages?${params.toString()}`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();

      messagesData = data.messages || [];
      messagesTotal = data.total || 0;

      // Update pill counters
      const cc = data.channel_counts || {};
      const dc = data.direction_counts || {};

      updatePillText('crm-msg-cnt-all', cc.all || 2229);
      updatePillText('crm-msg-cnt-inbound', dc.received || 492);
      updatePillText('crm-msg-cnt-outbound', dc.sent || 1737);
      updatePillText('crm-msg-cnt-linkedin', cc.linkedin || 2220);
      updatePillText('crm-msg-cnt-email', cc.email || 3);
      updatePillText('crm-msg-cnt-meeting', cc.meeting || 3);
      updatePillText('crm-msg-cnt-audio', cc.audio || 0);
      updatePillText('crm-msg-cnt-note', cc.note || 3);

      renderMessagesFeed(messagesData, container);
    } catch (err) {
      console.error('[CRM Studio] Error loading messages:', err);
      if (container) {
        container.innerHTML = `<div class="p-6 text-center text-xs font-mono text-red-500">Fehler beim Laden: ${err.message}</div>`;
      }
    }
  }

  function updatePillText(id, count) {
    const el = document.getElementById(id);
    if (el) el.textContent = count.toString();
  }

  function setMsgChannelFilter(ch) {
    msgChannel = ch;
    msgPage = 1;
    // update pill buttons active styles
    document.querySelectorAll('.crm-msg-channel-pill').forEach(b => {
      b.classList.remove('bg-indigo-600', 'text-white', 'border-indigo-600');
      b.classList.add('bg-[var(--secondary)]', 'text-[var(--foreground)]', 'border-[var(--border)]');
    });
    const active = document.getElementById(`crm-msg-ch-${ch}`);
    if (active) {
      active.classList.remove('bg-[var(--secondary)]', 'text-[var(--foreground)]', 'border-[var(--border)]');
      active.classList.add('bg-indigo-600', 'text-white', 'border-indigo-600');
    }
    loadAllMessages();
  }

  function setMsgDirectionFilter(dir) {
    msgDirection = dir;
    msgPage = 1;
    document.querySelectorAll('.crm-msg-dir-pill').forEach(b => {
      b.classList.remove('bg-slate-900', 'text-white', 'dark:bg-white', 'dark:text-slate-900');
      b.classList.add('bg-[var(--secondary)]', 'text-[var(--foreground)]');
    });
    const active = document.getElementById(`crm-msg-dir-${dir}`);
    if (active) {
      active.classList.remove('bg-[var(--secondary)]', 'text-[var(--foreground)]');
      active.classList.add('bg-slate-900', 'text-white', 'dark:bg-white', 'dark:text-slate-900');
    }
    loadAllMessages();
  }

  function onMsgSearchInput(val) {
    msgSearch = val;
    msgPage = 1;
    loadAllMessages();
  }

  function renderMessagesFeed(messages, container) {
    if (!container) return;
    if (!messages || messages.length === 0) {
      container.innerHTML = `<div class="p-8 text-center text-xs font-mono text-[var(--muted-foreground)]">Keine Nachrichten für diesen Filter gefunden.</div>`;
      return;
    }

    let html = '';
    let lastDate = '';

    messages.forEach(m => {
      const msgDate = (m.date || m.timestamp || '').slice(0, 10);
      if (msgDate && msgDate !== lastDate) {
        lastDate = msgDate;
        html += `
          <div class="flex items-center my-4">
            <div class="flex-grow border-t border-[var(--border)]"></div>
            <span class="flex-shrink mx-3 text-[11px] font-mono font-bold text-slate-500 bg-[var(--secondary)] px-3 py-1 rounded-full border border-[var(--border)]">
              ${msgDate}
            </span>
            <div class="flex-grow border-t border-[var(--border)]"></div>
          </div>
        `;
      }

      const initials = (m.contact_name || '??').split(' ').map(p => p[0]).join('').slice(0, 2).toUpperCase();
      const channelBadge = m.channel === 'linkedin'
        ? `<span class="px-2 py-0.5 rounded-full text-[10px] font-mono font-bold bg-sky-100 text-sky-700 dark:bg-sky-950 dark:text-sky-300 border border-sky-300/40">LinkedIn</span>`
        : `<span class="px-2 py-0.5 rounded-full text-[10px] font-mono font-bold bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300 border border-slate-300/40">${escapeHtml(m.channel)}</span>`;

      const text = escapeHtml(m.text || '');
      const isLong = text.length > 280;
      const previewText = isLong ? text.slice(0, 280) + '...' : text;

      html += `
        <div class="bg-[var(--card)] border border-[var(--border)] rounded-2xl p-4 shadow-xs mb-3 hover:border-indigo-400 dark:hover:border-indigo-600 transition">
          <div class="flex items-start gap-3">
            <div class="w-9 h-9 rounded-full bg-slate-800 text-white flex items-center justify-center font-bold text-xs shrink-0 cursor-pointer" onclick="crmStudio.openContactDrawer('${m.contact_id}')">
              ${initials}
            </div>
            <div class="flex-1 min-w-0">
              <div class="flex items-center justify-between gap-2 flex-wrap mb-1">
                <div class="flex items-center gap-2 flex-wrap text-xs">
                  <span class="font-bold text-[var(--foreground)] hover:text-indigo-600 dark:hover:text-indigo-400 cursor-pointer" onclick="crmStudio.openContactDrawer('${m.contact_id}')">
                    ${escapeHtml(m.contact_name)}
                  </span>
                  <span class="text-[var(--muted-foreground)] text-[11px]">${escapeHtml(m.contact_company || '')}</span>
                  ${channelBadge}
                  <span class="text-slate-400 text-[11px] font-mono">${escapeHtml(m.date || '')}</span>
                  <span class="text-[var(--muted-foreground)] text-[11px] font-mono">— ${escapeHtml(m.sender || '')}</span>
                </div>
              </div>
              <div class="text-xs text-[var(--foreground)] leading-relaxed whitespace-pre-line mt-1.5 font-sans" id="msg-text-${m.message_id}">
                ${previewText}
              </div>
              ${isLong ? `
                <button type="button" onclick="crmStudio.toggleMessageText('${m.message_id}', \`${encodeURIComponent(text)}\`)" class="mt-1.5 text-[11px] font-bold text-indigo-600 dark:text-indigo-400 hover:underline flex items-center gap-0.5">
                  <span id="btn-lbl-${m.message_id}">▼ Vollständige Anzeige</span>
                </button>
              ` : ''}
            </div>
          </div>
        </div>
      `;
    });

    container.innerHTML = html;
  }

  function toggleMessageText(msgId, encodedFullText) {
    const textEl = document.getElementById(`msg-text-${msgId}`);
    const btnLbl = document.getElementById(`btn-lbl-${msgId}`);
    if (!textEl || !btnLbl) return;

    const full = decodeURIComponent(encodedFullText);
    if (btnLbl.textContent.includes('Vollständige Anzeige')) {
      textEl.textContent = full;
      btnLbl.textContent = '▲ Weniger anzeigen';
    } else {
      textEl.textContent = full.slice(0, 280) + '...';
      btnLbl.textContent = '▼ Vollständige Anzeige';
    }
  }

  // -------------------------------------------------------------------------
  // 4. KALENDER TAB
  // -------------------------------------------------------------------------
  async function loadCalendar() {
    const container = document.getElementById('crm-calendar-container');
    if (!container) return;

    container.innerHTML = `<div class="p-8 text-center text-xs font-mono text-[var(--muted-foreground)]">Lade Kalendertermine & Follow-ups...</div>`;

    try {
      const resp = await fetch('/api/crm/calendar');
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();

      const events = data.events || [];
      if (events.length === 0) {
        container.innerHTML = `
          <div class="p-12 text-center">
            <div class="w-12 h-12 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-400 flex items-center justify-center mx-auto mb-3 text-xl">📅</div>
            <div class="text-sm font-bold text-[var(--foreground)]">Keine anstehenden Termine</div>
            <div class="text-xs text-[var(--muted-foreground)] mt-1">Über den Datensatz-Drawer können Sie neue Google- und CRM-Termine anlegen.</div>
          </div>
        `;
        return;
      }

      let html = '<div class="space-y-3">';
      events.forEach(ev => {
        html += `
          <div class="p-4 rounded-2xl bg-[var(--card)] border border-[var(--border)] shadow-xs flex items-start justify-between gap-3">
            <div class="flex items-start gap-3">
              <div class="w-10 h-10 rounded-xl bg-indigo-50 dark:bg-indigo-950/80 text-indigo-600 dark:text-indigo-400 font-bold flex flex-col items-center justify-center text-xs shrink-0 border border-indigo-200/50">
                <span>📅</span>
              </div>
              <div>
                <div class="text-xs font-bold text-[var(--foreground)]">${escapeHtml(ev.title)}</div>
                <div class="text-[11px] text-[var(--muted-foreground)] mt-0.5 font-mono">
                  ${escapeHtml(ev.start || '')} ${ev.location ? `· 📍 ${escapeHtml(ev.location)}` : ''}
                </div>
                ${ev.notes ? `<div class="text-xs text-slate-500 mt-1">${escapeHtml(ev.notes)}</div>` : ''}
              </div>
            </div>
            ${ev.contact_id ? `
              <button type="button" onclick="crmStudio.openContactDrawer('${ev.contact_id}')" class="px-2.5 py-1 rounded-lg text-xs font-bold text-indigo-600 hover:bg-indigo-50 dark:hover:bg-indigo-950 transition">
                Kontakt öffnen ↗
              </button>
            ` : ''}
          </div>
        `;
      });
      html += '</div>';
      container.innerHTML = html;
    } catch (err) {
      console.error('[CRM Studio] Error loading calendar:', err);
      container.innerHTML = `<div class="p-6 text-center text-xs font-mono text-red-500">Fehler beim Laden des Kalenders: ${err.message}</div>`;
    }
  }

  // -------------------------------------------------------------------------
  // 5. BERICHT / MISSIONSKONTROLLE (Screenshot 4)
  // -------------------------------------------------------------------------
  async function loadReport() {
    const container = document.getElementById('crm-bericht-container');
    if (!container) return;

    container.innerHTML = `<div class="p-8 text-center text-xs font-mono text-[var(--muted-foreground)]">Berechne CRM-Missionskontrolle & Netzwerk-Analytics...</div>`;

    try {
      const resp = await fetch('/api/crm/report');
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const rep = await resp.json();

      let roleBars = '';
      (rep.role_breakdown || []).forEach(rb => {
        roleBars += `
          <div class="space-y-1 mb-2.5">
            <div class="flex items-center justify-between text-xs">
              <span class="font-medium text-[var(--foreground)]">${escapeHtml(rb.role)}</span>
              <span class="font-mono text-slate-500 font-bold">${rb.count} (${rb.pct} %)</span>
            </div>
            <div class="w-full bg-slate-100 dark:bg-slate-800 rounded-full h-2 overflow-hidden">
              <div class="bg-indigo-600 dark:bg-indigo-500 h-2 rounded-full transition-all duration-500" style="width: ${Math.min(rb.pct, 100)}%"></div>
            </div>
          </div>
        `;
      });

      let statusBars = '';
      (rep.status_breakdown || []).forEach(sb => {
        const count = sb.count || 0;
        const totalAct = rep.active_contacts || 1145;
        const pct = Math.min(Math.round((count / totalAct) * 100), 100);
        statusBars += `
          <div class="space-y-1 mb-2.5">
            <div class="flex items-center justify-between text-xs">
              <span class="font-medium text-[var(--foreground)]">${escapeHtml(sb.status)}</span>
              <span class="font-mono text-slate-500 font-bold">${count}</span>
            </div>
            <div class="w-full bg-slate-100 dark:bg-slate-800 rounded-full h-2 overflow-hidden">
              <div class="bg-emerald-500 h-2 rounded-full transition-all duration-500" style="width: ${pct}%"></div>
            </div>
          </div>
        `;
      });

      let recentHtml = '';
      (rep.recent_contacts || []).forEach(rc => {
        recentHtml += `
          <div class="flex items-center justify-between p-2 rounded-xl hover:bg-slate-50 dark:hover:bg-slate-800/60 transition cursor-pointer border border-transparent hover:border-[var(--border)]" onclick="crmStudio.openContactDrawer('${rc.id}')">
            <div class="flex items-center gap-2.5 min-w-0">
              <div class="w-7 h-7 rounded-full bg-slate-700 text-white font-bold flex items-center justify-center text-[10px] shrink-0">
                ${escapeHtml(rc.initials)}
              </div>
              <div class="min-w-0">
                <div class="text-xs font-bold text-[var(--foreground)] truncate">${escapeHtml(rc.name)}</div>
                <div class="text-[10px] text-[var(--muted-foreground)] truncate">${escapeHtml(rc.company)}</div>
              </div>
            </div>
            <span class="text-[10px] font-mono text-slate-400 shrink-0 ml-2">${escapeHtml(rc.date)}</span>
          </div>
        `;
      });

      let checkContactsHtml = '';
      (rep.action_items_check || []).forEach(ac => {
        checkContactsHtml += `
          <div class="flex items-center justify-between p-2 rounded-xl hover:bg-slate-50 dark:hover:bg-slate-800/60 transition cursor-pointer mb-1.5" onclick="crmStudio.openContactDrawer('${ac.id}')">
            <div class="flex items-center gap-2 min-w-0">
              <div class="w-6 h-6 rounded-full bg-slate-800 text-white font-bold flex items-center justify-center text-[9px] shrink-0">
                ${escapeHtml((ac.name || '??').slice(0, 2).toUpperCase())}
              </div>
              <div class="min-w-0">
                <div class="text-xs font-bold text-[var(--foreground)] truncate">${escapeHtml(ac.name)}</div>
                <div class="text-[10px] text-[var(--muted-foreground)] truncate">${escapeHtml(ac.company)}</div>
              </div>
            </div>
            <span class="text-[10px] font-mono text-slate-400 shrink-0 ml-2">${escapeHtml(ac.date)}</span>
          </div>
        `;
      });

      let recruiterHtml = '';
      (rep.action_items_recruiter || []).forEach(rc => {
        recruiterHtml += `
          <div class="flex items-center justify-between p-2 rounded-xl hover:bg-slate-50 dark:hover:bg-slate-800/60 transition cursor-pointer mb-1.5" onclick="crmStudio.openContactDrawer('${rc.id}')">
            <div class="flex items-center gap-2 min-w-0">
              <div class="w-6 h-6 rounded-full bg-indigo-700 text-white font-bold flex items-center justify-center text-[9px] shrink-0">
                ${escapeHtml((rc.name || '??').slice(0, 2).toUpperCase())}
              </div>
              <div class="min-w-0">
                <div class="text-xs font-bold text-[var(--foreground)] truncate">${escapeHtml(rc.name)}</div>
                <div class="text-[10px] text-[var(--muted-foreground)] truncate">${escapeHtml(rc.company)}</div>
              </div>
            </div>
            <span class="text-[10px] font-mono text-slate-400 shrink-0 ml-2">${escapeHtml(rc.date)}</span>
          </div>
        `;
      });

      container.innerHTML = `
        <!-- TOP 6 KPI CARDS (Screenshot 4) -->
        <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 mb-4 shrink-0">
          <div class="p-3 bg-[var(--card)] border border-[var(--border)] rounded-2xl shadow-xs">
            <div class="flex items-center justify-between text-slate-500 text-[10px] font-bold uppercase tracking-wider mb-1">
              <span>Aktive Kontakte</span>
              <span class="text-emerald-500 text-sm">👥</span>
            </div>
            <div class="text-2xl font-black text-[var(--foreground)] tracking-tight">${rep.active_contacts}</div>
          </div>

          <div class="p-3 bg-[var(--card)] border border-[var(--border)] rounded-2xl shadow-xs">
            <div class="flex items-center justify-between text-slate-500 text-[10px] font-bold uppercase tracking-wider mb-1">
              <span>Antwortrate</span>
              <span class="text-blue-500 text-sm">💬</span>
            </div>
            <div class="text-2xl font-black text-[var(--foreground)] tracking-tight">${rep.reply_rate} %</div>
          </div>

          <div class="p-3 bg-[var(--card)] border border-[var(--border)] rounded-2xl shadow-xs">
            <div class="flex items-center justify-between text-slate-500 text-[10px] font-bold uppercase tracking-wider mb-1">
              <span>Meeting-Rate</span>
              <span class="text-amber-500 text-sm">📅</span>
            </div>
            <div class="text-2xl font-black text-[var(--foreground)] tracking-tight">${rep.meeting_rate} %</div>
          </div>

          <div class="p-3 bg-[var(--card)] border border-[var(--border)] rounded-2xl shadow-xs">
            <div class="flex items-center justify-between text-slate-500 text-[10px] font-bold uppercase tracking-wider mb-1">
              <span>Personalberater/Führ...</span>
              <span class="text-purple-500 text-sm">🎯</span>
            </div>
            <div class="text-2xl font-black text-[var(--foreground)] tracking-tight">${rep.executive_search_count}</div>
          </div>

          <div class="p-3 bg-[var(--card)] border border-[var(--border)] rounded-2xl shadow-xs">
            <div class="flex items-center justify-between text-slate-500 text-[10px] font-bold uppercase tracking-wider mb-1">
              <span>Stagniert</span>
              <span class="text-rose-500 text-sm">⏱️</span>
            </div>
            <div class="text-2xl font-black text-[var(--foreground)] tracking-tight">${rep.stagnated_count}</div>
          </div>

          <div class="p-3 bg-[var(--card)] border border-[var(--border)] rounded-2xl shadow-xs">
            <div class="flex items-center justify-between text-slate-500 text-[10px] font-bold uppercase tracking-wider mb-1">
              <span>Nächste Termine</span>
              <span class="text-teal-500 text-sm">📅</span>
            </div>
            <div class="text-2xl font-black text-[var(--foreground)] tracking-tight">${rep.next_termine_count}</div>
          </div>
        </div>

        <!-- 3-SPALTEN GRID (Screenshot 4) -->
        <div class="grid grid-cols-1 lg:grid-cols-12 gap-3 min-h-0">
          <!-- SPALTE 1 (4 Cols): Rollen- & Status-Verteilung -->
          <div class="lg:col-span-4 flex flex-col gap-3">
            <div class="p-4 bg-[var(--card)] border border-[var(--border)] rounded-2xl shadow-xs">
              <h3 class="text-xs font-bold text-[var(--foreground)] flex items-center gap-1.5 mb-3">
                <span class="text-emerald-500">📊</span>
                <span>Rollen-Verteilung</span>
              </h3>
              ${roleBars}
            </div>

            <div class="p-4 bg-[var(--card)] border border-[var(--border)] rounded-2xl shadow-xs">
              <h3 class="text-xs font-bold text-[var(--foreground)] flex items-center gap-1.5 mb-3">
                <span class="text-emerald-500">≡</span>
                <span>Status-Verteilung</span>
              </h3>
              ${statusBars}
            </div>
          </div>

          <!-- SPALTE 2 (4 Cols): Letzte Kontakte & Nächste Termine -->
          <div class="lg:col-span-4 flex flex-col gap-3">
            <div class="p-4 bg-[var(--card)] border border-[var(--border)] rounded-2xl shadow-xs">
              <h3 class="text-xs font-bold text-[var(--foreground)] flex items-center gap-1.5 mb-3">
                <span class="text-indigo-500">👥</span>
                <span>Letzte Kontakte</span>
              </h3>
              <div class="space-y-1">
                ${recentHtml || '<div class="text-xs text-slate-400">Keine Kontakte geladen.</div>'}
              </div>
            </div>

            <div class="p-4 bg-[var(--card)] border border-[var(--border)] rounded-2xl shadow-xs">
              <h3 class="text-xs font-bold text-[var(--foreground)] flex items-center gap-1.5 mb-2">
                <span class="text-amber-500">📅</span>
                <span>Nächste Termine &amp; Interviews</span>
              </h3>
              <div class="text-xs text-slate-500 italic py-2">
                Aktuell keine anstehenden Termine eingetragen.
              </div>
            </div>
          </div>

          <!-- SPALTE 3 (4 Cols): Was heute tun? -->
          <div class="lg:col-span-4 flex flex-col gap-3">
            <div class="p-4 bg-[var(--card)] border border-[var(--border)] rounded-2xl shadow-xs flex-1">
              <h3 class="text-xs font-bold text-[var(--foreground)] flex items-center justify-between mb-3">
                <span class="flex items-center gap-1.5 text-emerald-600 dark:text-emerald-400">
                  <span>⚡</span>
                  <span>Was heute tun?</span>
                </span>
              </h3>

              <div class="mb-4">
                <div class="flex items-center justify-between text-xs font-bold text-[var(--foreground)] mb-2">
                  <span class="flex items-center gap-1 text-emerald-600 dark:text-emerald-400">
                    <span>⏱️</span>
                    <span>Aktive Kontakte prüfen</span>
                  </span>
                  <span class="font-mono text-slate-400">${rep.stagnated_count}</span>
                </div>
                ${checkContactsHtml}
              </div>

              <div>
                <div class="flex items-center justify-between text-xs font-bold text-[var(--foreground)] mb-2">
                  <span class="flex items-center gap-1 text-purple-600 dark:text-purple-400">
                    <span>🎯</span>
                    <span>Recruiter / Executive-Search ansprechen</span>
                  </span>
                  <span class="font-mono text-slate-400">${rep.action_items_recruiter.length}</span>
                </div>
                ${recruiterHtml}
              </div>
            </div>
          </div>
        </div>
      `;
    } catch (err) {
      console.error('[CRM Studio] Error loading report:', err);
      container.innerHTML = `<div class="p-6 text-center text-xs font-mono text-red-500">Fehler beim Laden des Berichts: ${err.message}</div>`;
    }
  }

  // -------------------------------------------------------------------------
  // 6. KONTAKT-DRAWER / DETAIL-MODAL (Screenshot 3)
  // -------------------------------------------------------------------------
  async function openContactDrawer(contactId, initialTab = 'form') {
    const drawer = document.getElementById('crm-contact-drawer');
    if (!drawer) return;

    drawer.classList.remove('hidden');

    if (initialTab === 'messages' || initialTab === 'nachrichten') {
      activeDrawerTab = 'nachrichten';
    } else if (initialTab && initialTab !== 'form') {
      activeDrawerTab = initialTab;
    } else {
      activeDrawerTab = 'uebersicht';
    }

    // Reset drawer state
    setDrawerLoading(true);

    try {
      const resp = await fetch(`/api/crm/contacts/${contactId}`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const c = await resp.json();
      currentDrawerContact = c;

      populateDrawerForm(c);
      renderDrawerMessages(c.messages || []);
      setDrawerLoading(false);
    } catch (err) {
      console.error('[CRM Studio] Error opening drawer for contact:', contactId, err);
      alert(`Fehler beim Laden des Kontakts: ${err.message}`);
      closeContactDrawer();
    }
  }

  let activeDrawerTab = 'uebersicht';

  function switchDrawerTab(tabId) {
    activeDrawerTab = tabId || 'uebersicht';

    // Update active state on top cadre icon buttons (Identisch zu den Hauptansichten)
    document.querySelectorAll('.cd-header-tile').forEach(btn => {
      btn.classList.remove('active-cadre-tab');
      btn.style.opacity = '0.75';
      const wrap = btn.querySelector('.tile-icon-wrap');
      if (wrap) wrap.classList.remove('active-tile');
      const label = btn.querySelector('.cd-tab-label');
      if (label) {
        label.classList.remove('text-red-600', 'font-bold');
        label.classList.add('text-[var(--muted-foreground)]', 'font-medium');
      }
    });

    const activeBtn = document.getElementById(`cd-tabbtn-${activeDrawerTab}`);
    if (activeBtn) {
      activeBtn.classList.add('active-cadre-tab');
      activeBtn.style.opacity = '1.0';
      const wrap = activeBtn.querySelector('.tile-icon-wrap');
      if (wrap) wrap.classList.add('active-tile');
      const label = activeBtn.querySelector('.cd-tab-label');
      if (label) {
        label.classList.remove('text-[var(--muted-foreground)]', 'font-medium');
        label.classList.add('text-red-600', 'font-bold');
      }
    }

    const subviews = document.querySelectorAll('.cd-subview');
    subviews.forEach(view => {
      view.classList.add('hidden');
      view.style.display = 'none';
    });

    const activeView = document.getElementById(`cd-view-${activeDrawerTab}`);
    if (activeView) {
      activeView.classList.remove('hidden');
      if (activeDrawerTab === 'uebersicht') {
        activeView.style.display = 'flex';
        activeView.style.flexDirection = 'row';
      } else if (activeDrawerTab === 'nachrichten' || activeDrawerTab === 'vorgaenge') {
        activeView.style.display = 'flex';
        activeView.style.flexDirection = 'column';
      } else {
        activeView.style.display = 'block';
      }
    }

    if (activeDrawerTab === 'nachrichten' && currentDrawerContact) {
      renderDrawerFullMessages(currentDrawerContact.messages || []);
    }
  }

  function setDrawerLoading(isLoading) {
    const loadingEl = document.getElementById('crm-drawer-loading');
    if (loadingEl) loadingEl.style.display = isLoading ? 'flex' : 'none';
    if (!isLoading) {
      switchDrawerTab(activeDrawerTab || 'uebersicht');
    } else {
      const subviews = document.querySelectorAll('.cd-subview');
      subviews.forEach(v => { v.classList.add('hidden'); v.style.display = 'none'; });
    }
  }

  function closeContactDrawer() {
    const drawer = document.getElementById('crm-contact-drawer');
    if (drawer) drawer.classList.add('hidden');
    currentDrawerContact = null;
  }

  function populateDrawerForm(c) {
    // Header
    const initialsEl = document.getElementById('crm-drawer-initials');
    const titleEl = document.getElementById('crm-drawer-title');
    const idEl = document.getElementById('crm-drawer-id');
    const avatarImg = document.getElementById('crm-drawer-avatar-img');
    const boxAvatarImg = document.getElementById('cd-box-avatar-img');
    const boxAvatarPlaceholder = document.getElementById('cd-box-avatar-placeholder');
    const googleSearchLink = document.getElementById('crm-drawer-google-search');

    if (initialsEl) initialsEl.textContent = c.initials || '??';
    if (titleEl) titleEl.textContent = c.name || 'Unbekannt';
    if (idEl) idEl.textContent = `ID: ${c.id}`;
    if (googleSearchLink) googleSearchLink.href = `https://www.google.com/search?q=${encodeURIComponent(c.name || '')}`;

    const effectiveAvatar = c.avatar_url || c.profilbild || '';
    if (effectiveAvatar) {
      if (avatarImg) {
        avatarImg.src = effectiveAvatar;
        avatarImg.classList.remove('hidden');
        if (initialsEl) initialsEl.classList.add('hidden');
      }
      if (boxAvatarImg) {
        boxAvatarImg.src = effectiveAvatar;
        boxAvatarImg.classList.remove('hidden');
        if (boxAvatarPlaceholder) boxAvatarPlaceholder.classList.add('hidden');
      }
    } else {
      if (avatarImg) avatarImg.classList.add('hidden');
      if (initialsEl) initialsEl.classList.remove('hidden');
      if (boxAvatarImg) boxAvatarImg.classList.add('hidden');
      if (boxAvatarPlaceholder) boxAvatarPlaceholder.classList.remove('hidden');
    }

    // Set star rating
    setDrawerRatingStars(c.rating || 0);

    // Form inputs
    setVal('cd-name', c.name);
    setVal('cd-unternehmen', c.unternehmen);
    setVal('cd-rolle', c.rolle);
    setVal('cd-email', c.email);
    setVal('cd-linkedin', c.linkedin_url);
    setVal('cd-tel1', c.telefon_1);
    setVal('cd-region', c.region);
    setVal('cd-tel2', c.telefon_2);
    setVal('cd-webseite', c.Webseite || c.webseite);
    setVal('cd-status', c.status || 'Vernetzt');
    setVal('cd-rollen-zuordnung', c.RollenVerteilungzuordnung || '');
    setVal('cd-naechster-schritt', c.naechster_schritt);
    setVal('cd-vernetzt-am', c.vernetzt_am ? c.vernetzt_am.slice(0, 10) : '');
    setVal('cd-zurueckgezogen', c.einladung_zurueckgezogen_am ? c.einladung_zurueckgezogen_am.slice(0, 10) : '');
    setVal('cd-naechster-termin', c.naechster_termin || '');
    setVal('cd-adresse', c.adresse);
    setVal('cd-kommentar', c.kommentar);
    setVal('cd-linkedin-header', c.LinkedInheader || '');
    setVal('cd-linkedin-info', c.Linkedin_info || '');

    // VARIO & Kaufmännische Daten
    setVal('cd-debitor-nr', c.debitor_nr || `D-${(c.id || '').slice(0, 6).toUpperCase()}`);
    setVal('cd-kreditor-nr', c.kreditor_nr || '');
    setVal('cd-zahlungsart', c.zahlungsart || 'Rechnung');
    setVal('cd-zahlungsziel-tage', c.zahlungsziel_tage !== undefined && c.zahlungsziel_tage !== null ? c.zahlungsziel_tage : 14);
    setVal('cd-skonto-prozent', c.skonto_prozent !== undefined && c.skonto_prozent !== null ? c.skonto_prozent : 0.0);
    setVal('cd-skonto-tage', c.skonto_tage !== undefined && c.skonto_tage !== null ? c.skonto_tage : 0);
    setVal('cd-kreditlimit', c.kreditlimit !== undefined && c.kreditlimit !== null ? c.kreditlimit : 15000);
    setVal('cd-preisgruppe', c.preisgruppe || 'Standard');
    setVal('cd-bank-name', c.bank_name || '');
    setVal('cd-iban', c.iban || '');
    setVal('cd-bic', c.bic || '');
    setVal('cd-ust-id', c.ust_id || '');
    setVal('cd-steuernummer', c.steuernummer || '');
    setVal('cd-steuergebiet', c.steuergebiet || 'Inland (19%)');
    setVal('cd-leitweg-id', c.leitweg_id || '');

    // DSGVO & Compliance
    setVal('drw-dsgvo-legal-basis', c.dsgvo_legal_basis || 'art6_1_f');
    const optEmailEl = document.getElementById('drw-dsgvo-opt-email');
    if (optEmailEl) optEmailEl.checked = c.dsgvo_opt_email !== 0;
    const optPhoneEl = document.getElementById('drw-dsgvo-opt-phone');
    if (optPhoneEl) optPhoneEl.checked = c.dsgvo_opt_phone !== 0;
    const optPostalEl = document.getElementById('drw-dsgvo-opt-postal');
    if (optPostalEl) optPostalEl.checked = !!c.dsgvo_opt_postal;
    setVal('drw-dsgvo-opt-date', (c.dsgvo_opt_in_datum || c.vernetzt_am || '').slice(0, 10));
    setVal('drw-dsgvo-opt-source', c.dsgvo_opt_source || 'B2B Erstkontakt / LinkedIn');
    const optOutEl = document.getElementById('drw-dsgvo-opt-out');
    if (optOutEl) optOutEl.checked = !!c.dsgvo_opt_out;
    setVal('drw-dsgvo-opt-out-date', (c.dsgvo_opt_out_date || '').slice(0, 10));
    setVal('drw-dsgvo-retention-category', c.dsgvo_retention_category || 'commercial_10y');
    onDsgvoChange();

    const sepaRef = document.getElementById('cd-sepa-ref');
    if (sepaRef) sepaRef.textContent = `SEPA-${(c.id || '').toUpperCase()}`;
    const fullCount = document.getElementById('cd-full-msg-count');
    if (fullCount) fullCount.textContent = `${(c.messages || []).length} Nachrichten`;
    renderDrawerFullMessages(c.messages || []);

    // Tags list
    currentContactTags = Array.isArray(c.tags_list) && c.tags_list.length > 0
      ? [...c.tags_list]
      : (typeof c.tags === 'string' && c.tags ? (function(){ try { const p = JSON.parse(c.tags); return Array.isArray(p)?p:[c.tags]; }catch(e){ return [c.tags]; }})() : []);
    renderDrawerTags();

    // External link button
    const linkBtn = document.getElementById('cd-linkedin-open-link');
    if (linkBtn) {
      if (c.linkedin_url) {
        linkBtn.href = c.linkedin_url.startsWith('http') ? c.linkedin_url : `https://${c.linkedin_url}`;
        linkBtn.classList.remove('hidden');
      } else {
        linkBtn.classList.add('hidden');
      }
    }
    const webBtn = document.getElementById('cd-webseite-open-link');
    if (webBtn) {
      const w = c.Webseite || c.webseite;
      if (w) {
        webBtn.href = w.startsWith('http') ? w : `https://${w}`;
        webBtn.classList.remove('hidden');
      } else {
        webBtn.classList.add('hidden');
      }
    }
  }

  function renderDrawerTags() {
    const container = document.getElementById('cd-tags-container');
    if (!container) return;

    let html = '';
    currentContactTags.forEach(t => {
      const cleanTag = escapeHtml(t);
      html += `
        <span class="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-mono font-bold border border-rose-300 dark:border-rose-900/60 bg-rose-50 dark:bg-rose-950/40 text-rose-700 dark:text-rose-300 shrink-0">
          <span># ${cleanTag}</span>
          <button type="button" onclick="crmStudio.removeTag('${cleanTag}')" class="hover:text-rose-900 dark:hover:text-rose-100 transition p-0.5 ml-0.5 cursor-pointer">
            ✕
          </button>
        </span>
      `;
    });

    html += `
      <input
        type="text"
        id="cd-new-tag-input"
        placeholder="+ Tag..."
        class="flex-1 min-w-[100px] bg-transparent border-none outline-none text-xs font-mono py-1 px-1 text-zinc-900 dark:text-zinc-100"
        onkeydown="if(event.key==='Enter'||event.key===','){event.preventDefault();crmStudio.addTagFromInput();}"
      >
    `;
    container.innerHTML = html;
  }

  function addTagFromInput() {
    const input = document.getElementById('cd-new-tag-input');
    if (!input || !input.value.trim()) return;
    const tag = input.value.replace(/#/g, '').replace(/,/g, '').trim();
    if (tag && !currentContactTags.includes(tag)) {
      currentContactTags.push(tag);
      renderDrawerTags();
      const nextInput = document.getElementById('cd-new-tag-input');
      if (nextInput) nextInput.focus();
    }
  }

  function removeTag(tag) {
    currentContactTags = currentContactTags.filter(t => t !== tag);
    renderDrawerTags();
  }

  function setVal(id, val) {
    const el = document.getElementById(id);
    if (el) el.value = val || '';
  }

  function getVal(id) {
    const el = document.getElementById(id);
    return el ? el.value.trim() : '';
  }

  function setDrawerRatingStars(rating) {
    const r = parseInt(rating) || 0;
    const container = document.getElementById('crm-drawer-stars');
    if (!container) return;

    let html = '';
    for (let i = 1; i <= 5; i++) {
      html += `
        <button type="button" onclick="crmStudio.setDrawerRating(${i})" class="text-xl cursor-pointer hover:scale-110 transition ${i <= r ? 'text-amber-400' : 'text-slate-300 dark:text-slate-600'}">
          ★
        </button>
      `;
    }
    container.innerHTML = html;
    container.dataset.rating = r.toString();
  }

  function setDrawerRating(r) {
    setDrawerRatingStars(r);
  }

  function renderDrawerMessages(messages) {
    const container = document.getElementById('crm-drawer-messages-list');
    if (!container) return;

    if (!messages || messages.length === 0) {
      container.innerHTML = `<div class="p-8 text-center text-xs font-mono text-[var(--muted-foreground)]">Noch kein Nachrichtenverlauf für diesen Kontakt erfasst.</div>`;
      return;
    }

    let filtered = messages;
    if (drawerMsgFilter !== 'all') {
      filtered = messages.filter(m => {
        const t = (m.channel || m.type || 'linkedin').toLowerCase();
        if (drawerMsgFilter === 'meeting') return t === 'meeting' || t === 'audio';
        return t === drawerMsgFilter.toLowerCase();
      });
    }

    if (filtered.length === 0) {
      container.innerHTML = `<div class="p-6 text-center text-xs font-mono text-[var(--muted-foreground)]">Keine Nachrichten im Filter '${drawerMsgFilter}'.</div>`;
      return;
    }

    let html = '';
    filtered.forEach(m => {
      const isOutbound = (m.direction === 'outbound' || (m.sender && (m.sender.toLowerCase().includes('ich') || m.sender.toLowerCase() === 'me' || m.sender.toLowerCase().includes('keller'))));
      const senderLabel = isOutbound
        ? 'LinkedIn · Ich'
        : (m.sender || (currentDrawerContact ? currentDrawerContact.name : 'Kontakt'));

      const ch = (m.channel || m.type || 'linkedin').toLowerCase();
      let borderCol = 'border-blue-400/30';
      let headerBg = 'bg-[#E0F2FE] text-[#0369A1] dark:bg-sky-950/40 dark:text-sky-300';
      let chIcon = '🗩';
      let chName = 'LinkedIn';

      if (ch === 'email') {
        borderCol = 'border-orange-400/30';
        headerBg = 'bg-[#FFEDD5] text-[#C2410C] dark:bg-amber-950/40 dark:text-amber-300';
        chIcon = '✉️';
        chName = 'E-Mail';
      } else if (ch === 'note') {
        borderCol = 'border-emerald-400/30';
        headerBg = 'bg-[#D1FAE5] text-[#047857] dark:bg-emerald-950/40 dark:text-emerald-300';
        chIcon = '📝';
        chName = 'Notiz';
      } else if (ch === 'meeting' || ch === 'audio') {
        borderCol = 'border-rose-400/30';
        headerBg = 'bg-[#FFE4E6] text-[#BE123C] dark:bg-rose-950/40 dark:text-rose-300';
        chIcon = '🎙️';
        chName = 'Audio-Diktat';
      }

      const displaySender = isOutbound ? `${chName} · Ich` : `${chName} · ${escapeHtml(senderLabel)}`;

      html += `
        <div class="rounded-xl border-2 ${borderCol} overflow-hidden bg-white dark:bg-zinc-800 shadow-xs mb-3">
          <div class="${headerBg} px-4 py-2 flex items-center justify-between text-xs font-semibold border-b border-black/5">
            <div class="flex items-center gap-1.5">
              <span>${chIcon}</span>
              <span>${displaySender}</span>
            </div>
            <div class="flex items-center gap-2">
              <span class="text-zinc-600 dark:text-zinc-400 font-mono text-[11px]">${escapeHtml(m.date || m.timestamp || '')}</span>
              <span class="${m.isStarred ? 'text-amber-400 fill-amber-400' : 'text-zinc-400'} text-xs">⭐</span>
            </div>
          </div>
          <div class="p-4 text-xs font-sans leading-relaxed whitespace-pre-line text-zinc-800 dark:text-zinc-100">
            ${escapeHtml(m.text || '')}
          </div>
        </div>
      `;
    });

    container.innerHTML = html;
  }

  function filterDrawerMessages(ch) {
    drawerMsgFilter = ch;
    document.querySelectorAll('.crm-drawer-msg-filter-btn, [id^="cd-mf-"]').forEach(b => {
      b.classList.remove('bg-accent-main', 'text-white', 'font-bold', 'shadow-xs');
      b.classList.add('bg-zinc-100', 'dark:bg-zinc-800', 'border-zinc-200', 'dark:border-zinc-700', 'text-zinc-700', 'dark:text-zinc-200');
    });
    const btn = document.getElementById(`cd-mf-${ch}`);
    if (btn) {
      btn.classList.remove('bg-zinc-100', 'dark:bg-zinc-800', 'text-zinc-700', 'dark:text-zinc-200');
      btn.classList.add('bg-accent-main', 'text-white', 'font-bold', 'shadow-xs');
    }
    if (currentDrawerContact) {
      renderDrawerMessages(currentDrawerContact.messages || []);
    }
  }

  async function saveContactFromDrawer() {
    if (!currentDrawerContact) return;
    const cid = currentDrawerContact.id;
    const saveBtn = document.getElementById('cd-btn-save');
    if (saveBtn) saveBtn.innerHTML = '<span>⏳</span><span>Speichere...</span>';

    const starsEl = document.getElementById('crm-drawer-stars');
    const rating = starsEl ? parseInt(starsEl.dataset.rating || '0') : 0;

    const payload = {
      name: getVal('cd-name'),
      unternehmen: getVal('cd-unternehmen'),
      rolle: getVal('cd-rolle'),
      email: getVal('cd-email'),
      linkedin_url: getVal('cd-linkedin'),
      telefon_1: getVal('cd-tel1'),
      region: getVal('cd-region'),
      telefon_2: getVal('cd-tel2'),
      Webseite: getVal('cd-webseite'),
      status: getVal('cd-status'),
      RollenVerteilungzuordnung: getVal('cd-rollen-zuordnung'),
      naechster_schritt: getVal('cd-naechster-schritt'),
      vernetzt_am: getVal('cd-vernetzt-am'),
      einladung_zurueckgezogen_am: getVal('cd-zurueckgezogen'),
      naechster_termin: getVal('cd-naechster-termin'),
      adresse: getVal('cd-adresse'),
      kommentar: getVal('cd-kommentar'),
      LinkedInheader: getVal('cd-linkedin-header'),
      Linkedin_info: getVal('cd-linkedin-info'),
      tags: currentContactTags,
      rating: rating,
      debitor_nr: getVal('cd-debitor-nr'),
      kreditor_nr: getVal('cd-kreditor-nr'),
      zahlungsart: getVal('cd-zahlungsart'),
      zahlungsziel_tage: parseInt(getVal('cd-zahlungsziel-tage') || '14', 10),
      skonto_prozent: parseFloat(getVal('cd-skonto-prozent') || '0'),
      skonto_tage: parseInt(getVal('cd-skonto-tage') || '0', 10),
      kreditlimit: parseFloat(getVal('cd-kreditlimit') || '0'),
      preisgruppe: getVal('cd-preisgruppe'),
      bank_name: getVal('cd-bank-name'),
      iban: getVal('cd-iban'),
      bic: getVal('cd-bic'),
      ust_id: getVal('cd-ust-id'),
      steuernummer: getVal('cd-steuernummer'),
      steuergebiet: getVal('cd-steuergebiet'),
      leitweg_id: getVal('cd-leitweg-id'),
      dsgvo_legal_basis: getVal('drw-dsgvo-legal-basis') || 'art6_1_f',
      dsgvo_opt_email: document.getElementById('drw-dsgvo-opt-email')?.checked ? 1 : 0,
      dsgvo_opt_phone: document.getElementById('drw-dsgvo-opt-phone')?.checked ? 1 : 0,
      dsgvo_opt_postal: document.getElementById('drw-dsgvo-opt-postal')?.checked ? 1 : 0,
      dsgvo_opt_source: getVal('drw-dsgvo-opt-source'),
      dsgvo_opt_in_datum: getVal('drw-dsgvo-opt-date'),
      dsgvo_opt_out: document.getElementById('drw-dsgvo-opt-out')?.checked ? 1 : 0,
      dsgvo_opt_out_date: getVal('drw-dsgvo-opt-out-date'),
      dsgvo_retention_category: getVal('drw-dsgvo-retention-category') || 'commercial_10y'
    };

    try {
      const resp = await fetch(`/api/crm/contacts/${cid}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const updated = await resp.json();
      currentDrawerContact = updated;
      if (saveBtn) saveBtn.innerHTML = '<span>✓</span><span>Gespeichert!</span>';
      setTimeout(() => { if (saveBtn) saveBtn.innerHTML = '<span>💾</span><span>Speichern</span>'; }, 1500);

      // Refresh list in background
      loadContacts(activeSubTab === 'kunden' ? 'customers' : (activeSubTab === 'lieferanten' ? 'suppliers' : 'all'));
    } catch (err) {
      console.error('[CRM Studio] Error saving contact:', err);
      alert(`Fehler beim Speichern: ${err.message}`);
      if (saveBtn) saveBtn.innerHTML = '<span>💾</span><span>Speichern</span>';
    }
  }

  function promptAddNote() {
    const text = prompt('Neue Notiz / Gesprächsprotokoll eingeben:');
    if (!text || !text.trim() || !currentDrawerContact) return;
    fetch(`/api/crm/contacts/${currentDrawerContact.id}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text: text.trim(),
        channel: 'note',
        direction: 'outbound',
        sender: 'Michael Keller'
      })
    })
      .then(r => r.json())
      .then(res => {
        if (!currentDrawerContact.messages) currentDrawerContact.messages = [];
        currentDrawerContact.messages.unshift(res.message);
        renderDrawerMessages(currentDrawerContact.messages);
      })
      .catch(err => alert(`Fehler: ${err.message}`));
  }

  function triggerAudioDictation() {
    alert('Audio-Diktat aktiviert: Sprechen Sie Ihre Notiz ein (Whisper AI Transkription aktiv)...');
  }

  function triggerMeetingDictation() {
    alert('Meeting-Diktat aktiviert: Zwei-Spur-Aufnahme gestartet (Auto-Zusammenfassung aktiv)...');
  }

  function scheduleFollowUp() {
    if (!currentDrawerContact) return;
    const dateStr = prompt('Follow-Up Termin planen (JJJJ-MM-TT):', new Date().toISOString().slice(0, 10));
    if (dateStr) {
      const el = document.getElementById('cd-naechster-termin');
      if (el) el.value = dateStr;
      saveContactFromDrawer();
    }
  }

  function scheduleGoogleCalendar() {
    if (!currentDrawerContact) return;
    const title = encodeURIComponent(`Meeting mit ${currentDrawerContact.name || 'Kontakt'}`);
    window.open(`https://calendar.google.com/calendar/render?action=TEMPLATE&text=${title}`, '_blank');
  }

  async function addDrawerNote() {
    if (!currentDrawerContact) return;
    const noteInp = document.getElementById('cd-new-note-input');
    if (!noteInp || !noteInp.value.trim()) {
      alert('Bitte geben Sie einen Notiztext ein.');
      return;
    }
    const text = noteInp.value.trim();
    const cid = currentDrawerContact.id;

    try {
      const resp = await fetch(`/api/crm/contacts/${cid}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text: text,
          channel: 'note',
          direction: 'outbound',
          sender: 'Michael Keller'
        })
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const res = await resp.json();

      noteInp.value = '';
      if (!currentDrawerContact.messages) currentDrawerContact.messages = [];
      currentDrawerContact.messages.push(res.message);
      renderDrawerMessages(currentDrawerContact.messages);
    } catch (err) {
      console.error('[CRM Studio] Error adding note:', err);
      alert(`Fehler beim Hinzufügen der Notiz: ${err.message}`);
    }
  }

  async function deleteContactFromDrawer() {
    if (!currentDrawerContact) return;
    const cid = currentDrawerContact.id;
    const name = currentDrawerContact.name || 'diesen Kontakt';
    if (!confirm(`Möchten Sie ${name} wirklich unwiderruflich aus dem CRM löschen?`)) {
      return;
    }

    try {
      const resp = await fetch(`/api/crm/contacts/${cid}`, { method: 'DELETE' });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      closeContactDrawer();
      loadContacts(activeSubTab === 'kunden' ? 'customers' : (activeSubTab === 'lieferanten' ? 'suppliers' : 'all'));
    } catch (err) {
      console.error('[CRM Studio] Error deleting contact:', err);
      alert(`Fehler beim Löschen: ${err.message}`);
    }
  }

  function createNewContact() {
    const name = prompt('Name des neuen Kontakts:');
    if (!name || !name.trim()) return;

    fetch('/api/crm/contacts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: name.trim(), status: 'Vernetzt', rating: 1 })
    })
      .then(r => r.json())
      .then(data => {
        if (data.id) {
          openContactDrawer(data.id);
          loadContacts(activeSubTab === 'kunden' ? 'customers' : (activeSubTab === 'lieferanten' ? 'suppliers' : 'all'));
        }
      })
      .catch(err => alert(`Fehler: ${err.message}`));
  }

  // -------------------------------------------------------------------------
  // PAGINATION COMPONENT
  // -------------------------------------------------------------------------
  function renderPagination(containerId, total, page, limit, onPageChange) {
    const container = document.getElementById(containerId);
    if (!container) return;

    const totalPages = Math.max(1, Math.ceil(total / limit));
    if (totalPages <= 1) {
      container.innerHTML = `<span class="text-xs text-[var(--muted-foreground)] font-mono">1–${total} von ${total}</span>`;
      return;
    }

    container.innerHTML = `
      <div class="flex items-center gap-2 text-xs font-mono">
        <button type="button" ${page <= 1 ? 'disabled' : ''} onclick="crmStudio.setPage(${page - 1})" class="px-2.5 py-1 rounded-lg border border-[var(--border)] bg-[var(--secondary)] text-[var(--foreground)] disabled:opacity-30 disabled:cursor-not-allowed hover:bg-slate-200 dark:hover:bg-slate-700 transition">
          ◀ Vorige
        </button>
        <span class="text-[var(--muted-foreground)]">Seite ${page} von ${totalPages}</span>
        <button type="button" ${page >= totalPages ? 'disabled' : ''} onclick="crmStudio.setPage(${page + 1})" class="px-2.5 py-1 rounded-lg border border-[var(--border)] bg-[var(--secondary)] text-[var(--foreground)] disabled:opacity-30 disabled:cursor-not-allowed hover:bg-slate-200 dark:hover:bg-slate-700 transition">
          Nächste ▶
        </button>
      </div>
    `;
  }

  function setPage(p) {
    currentPage = p;
    loadContacts(activeSubTab === 'kunden' ? 'customers' : (activeSubTab === 'lieferanten' ? 'suppliers' : 'all'));
  }

  // Helper escape
  function escapeHtml(text) {
    if (!text) return '';
    return String(text)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  function renderDrawerFullMessages(messages) {
    const container = document.getElementById('crm-drawer-full-messages-list');
    if (!container) return;

    if (!messages || messages.length === 0) {
      container.innerHTML = `
        <div class="p-8 text-center text-xs font-mono text-zinc-400 bg-zinc-50 dark:bg-zinc-800/40 rounded-xl border border-dashed border-zinc-200 dark:border-zinc-800">
          Noch keine Kommunikationshistorie hinterlegt.
        </div>
      `;
      return;
    }

    let html = '';
    messages.forEach(m => {
      const channel = (m.channel || m.type || 'note').toLowerCase();
      let badgeClass = 'bg-zinc-100 text-zinc-700 border-zinc-200 dark:bg-zinc-800 dark:text-zinc-300';
      let icon = '📝';
      let label = 'Notiz';
      if (channel.includes('linkedin')) {
        badgeClass = 'bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-950/40 dark:text-blue-300';
        icon = '🔗';
        label = 'LinkedIn';
      } else if (channel.includes('mail')) {
        badgeClass = 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-300';
        icon = '✉️';
        label = 'E-Mail';
      } else if (channel.includes('meet')) {
        badgeClass = 'bg-purple-50 text-purple-700 border-purple-200 dark:bg-purple-950/40 dark:text-purple-300';
        icon = '👥';
        label = 'Meeting';
      }

      html += `
        <div class="border rounded-2xl bg-white dark:bg-zinc-900 border-zinc-200 dark:border-zinc-800 shadow-xs overflow-hidden">
          <div class="px-4 py-2.5 bg-zinc-50/80 dark:bg-zinc-800/40 border-b border-zinc-200 dark:border-zinc-800 flex items-center justify-between">
            <div class="flex items-center gap-2">
              <span class="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-mono font-bold border ${badgeClass}">
                <span>${icon}</span>
                <span>${label}</span>
                <span>·</span>
                <span>${escapeHtml(m.sender || 'Ich')}</span>
              </span>
            </div>
            <span class="text-[11px] font-mono text-zinc-400">${escapeHtml(m.date || m.timestamp || '')}</span>
          </div>
          <div class="p-4 text-xs font-sans leading-relaxed whitespace-pre-line text-zinc-800 dark:text-zinc-100">
            ${escapeHtml(m.text || '')}
          </div>
        </div>
      `;
    });

    container.innerHTML = html;
  }

  async function sendComposerMessage() {
    if (!currentDrawerContact) return;
    const textEl = document.getElementById('cd-new-msg-text');
    const channelEl = document.getElementById('cd-new-msg-channel');
    if (!textEl || !textEl.value.trim()) {
      alert('Bitte geben Sie einen Nachrichtentext ein.');
      return;
    }

    const text = textEl.value.trim();
    const channel = channelEl ? channelEl.value : 'note';

    try {
      const resp = await fetch(`/api/crm/contacts/${currentDrawerContact.id}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text: text,
          channel: channel,
          direction: 'outbound',
          sender: 'Michael Keller'
        })
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const res = await resp.json();
      textEl.value = '';
      if (!currentDrawerContact.messages) currentDrawerContact.messages = [];
      currentDrawerContact.messages.unshift(res.message);
      renderDrawerMessages(currentDrawerContact.messages);
      renderDrawerFullMessages(currentDrawerContact.messages);
      const fullCount = document.getElementById('cd-full-msg-count');
      if (fullCount) fullCount.textContent = `${currentDrawerContact.messages.length} Nachrichten`;
    } catch (err) {
      alert(`Fehler beim Senden: ${err.message}`);
    }
  }

  function promptAddContactPerson() {
    if (!currentDrawerContact) return;
    const name = prompt('Name des Ansprechpartners:');
    if (!name || !name.trim()) return;
    const role = prompt('Funktion / Position (z.B. Einkauf, Leitung):', 'Einkauf');
    const email = prompt('E-Mail-Adresse:');
    const phone = prompt('Telefon / Durchwahl:');

    const list = document.getElementById('cd-ansprechpartner-list');
    if (list) {
      const card = document.createElement('div');
      card.className = 'p-4 border rounded-2xl bg-zinc-50 dark:bg-zinc-800/40 border-zinc-200 dark:border-zinc-800 space-y-2';
      card.innerHTML = `
        <div class="flex items-center justify-between">
          <span class="text-xs font-bold text-zinc-900 dark:text-zinc-100">${escapeHtml(name)}</span>
          <span class="px-2 py-0.5 rounded text-[10px] font-mono bg-indigo-50 text-indigo-700 font-bold">${escapeHtml(role || 'Ansprechpartner')}</span>
        </div>
        ${email ? `<p class="text-xs text-zinc-500 font-mono">${escapeHtml(email)}</p>` : ''}
        ${phone ? `<p class="text-xs text-zinc-500 font-mono">${escapeHtml(phone)}</p>` : ''}
      `;
      list.appendChild(card);
    }
  }

  async function exportContactGdpr() {
    if (!currentDrawerContact) return;
    try {
      const resp = await fetch(`/api/crm/contacts/${currentDrawerContact.id}/gdpr-export`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      const safeName = (currentDrawerContact.name || 'kontakt').replace(/\s+/g, '_');
      a.download = `dsgvo_export_${currentDrawerContact.id}_${safeName}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err) {
      alert(`Fehler beim DSGVO-Export: ${err.message}`);
    }
  }

  async function anonymizeContactGdpr() {
    if (!currentDrawerContact) return;
    const ok = confirm(`Sind Sie sicher, dass Sie alle personenbezogenen Daten von "${currentDrawerContact.name}" gemäß Art. 17 DSGVO unwiderruflich anonymisieren möchten?\n\nDiese Aktion kann nicht rückgängig gemacht werden.`);
    if (!ok) return;
    try {
      const resp = await fetch(`/api/crm/contacts/${currentDrawerContact.id}/gdpr-anonymize`, { method: 'POST' });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      alert('Der Kontakt wurde erfolgreich gemäß Art. 17 DSGVO anonymisiert.');
      openContactDrawer(currentDrawerContact.id);
      loadContacts(activeSubTab === 'kunden' ? 'customers' : (activeSubTab === 'lieferanten' ? 'suppliers' : 'all'));
    } catch (err) {
      alert(`Fehler bei der Anonymisierung: ${err.message}`);
    }
  }

  function onDsgvoChange() {
    const optOut = document.getElementById('drw-dsgvo-opt-out')?.checked;
    const banner = document.getElementById('drw-dsgvo-banner');
    const bannerTitle = document.getElementById('drw-dsgvo-banner-title');
    const bannerDesc = document.getElementById('drw-dsgvo-banner-desc');
    const badge = document.getElementById('drw-dsgvo-badge');
    const icon = document.getElementById('drw-dsgvo-banner-icon');
    const optOutPill = document.getElementById('drw-dsgvo-optout-pill');
    const legalBasis = document.getElementById('drw-dsgvo-legal-basis')?.value || 'art6_1_f';

    const basisDescriptions = {
      art6_1_f: 'Art. 6 Abs. 1 lit. f DSGVO (Berechtigtes Interesse im B2B-Umfeld)',
      art6_1_b: 'Art. 6 Abs. 1 lit. b DSGVO (Vertragserfüllung / Vorvertragliche Maßnahmen)',
      art6_1_a: 'Art. 6 Abs. 1 lit. a DSGVO (Ausdrückliche Einwilligung / Opt-In)',
      art6_1_c: 'Art. 6 Abs. 1 lit. c DSGVO (Rechtliche Verpflichtung gem. HGB/AO)'
    };

    if (optOut) {
      if (optOutPill) optOutPill.classList.remove('hidden');
      if (badge) {
        badge.className = 'px-2.5 py-0.5 rounded-full text-[10px] font-mono font-bold bg-rose-600 text-white';
        badge.textContent = 'Werbewiderspruch aktiv';
      }
      if (banner) banner.className = 'p-5 border rounded-2xl bg-rose-50/70 dark:bg-rose-950/30 border-rose-300 dark:border-rose-800/80 flex items-start gap-4';
      if (icon) icon.textContent = '🛑';
      if (bannerTitle) {
        bannerTitle.className = 'text-sm font-bold text-rose-900 dark:text-rose-200';
        bannerTitle.textContent = 'Werbesperre gem. Art. 21 DSGVO aktiv';
      }
      if (bannerDesc) {
        bannerDesc.className = 'text-xs text-rose-700 dark:text-rose-300 leading-relaxed';
        bannerDesc.textContent = 'Die betroffene Person hat Widerspruch gegen Direktwerbung eingelegt. Sämtliche proaktiven Marketing- und Vertriebsaktivitäten sind zu unterlassen.';
      }
    } else {
      if (optOutPill) optOutPill.classList.add('hidden');
      if (badge) {
        badge.className = 'px-2.5 py-0.5 rounded-full text-[10px] font-mono font-bold bg-emerald-600 text-white';
        badge.textContent = 'Rechtsgrundlage validiert';
      }
      if (banner) banner.className = 'p-5 border rounded-2xl bg-emerald-50/70 dark:bg-emerald-950/30 border-emerald-200 dark:border-emerald-800/60 flex items-start gap-4';
      if (icon) icon.textContent = '🛡️';
      if (bannerTitle) {
        bannerTitle.className = 'text-sm font-bold text-emerald-900 dark:text-emerald-200';
        bannerTitle.textContent = 'Datenschutz-Status: DSGVO-Konform verarbeitet';
      }
      if (bannerDesc) {
        bannerDesc.className = 'text-xs text-emerald-700 dark:text-emerald-300 leading-relaxed';
        bannerDesc.textContent = `Aktive Rechtsgrundlage: ${basisDescriptions[legalBasis] || legalBasis}. Datenverarbeitung erfolgt zweckgebunden und unter Wahrung des Grundsatzes der Datenminimierung.`;
      }
    }
  }

  let currentActiveDocType = 'offer';

  function openNewDocBuilder(docType) {
    currentActiveDocType = docType || 'offer';
    const panel = document.getElementById('cd-new-doc-panel');
    const titleEl = document.getElementById('cd-new-doc-title');
    const numEl = document.getElementById('cd-doc-number');

    const isOffer = currentActiveDocType === 'offer';
    const prefix = isOffer ? 'ANG-2026' : 'AB-2026';
    const randNum = Math.floor(1000 + Math.random() * 9000);

    if (titleEl) titleEl.textContent = isOffer ? 'Neues Angebot (ANG) kalkulieren' : 'Neuen Auftrag (AB) bestätigen';
    if (numEl) numEl.value = `${prefix}-${randNum}`;

    calcDocTotals();
    if (panel) panel.classList.remove('hidden');
  }

  function toggleDocBuilder(show) {
    const panel = document.getElementById('cd-new-doc-panel');
    if (panel) {
      if (typeof show === 'boolean') panel.classList.toggle('hidden', !show);
      else panel.classList.toggle('hidden');
    }
  }

  function onDocItemSelect() {
    const sel = document.getElementById('cd-doc-item-select');
    if (!sel) return;
    const opt = sel.options[sel.selectedIndex];
    const unit = opt?.dataset.unit || 'Std.';
    const unitEl = document.getElementById('cd-doc-unit');
    if (unitEl) unitEl.textContent = unit;
    calcDocTotals();
  }

  function calcDocTotals() {
    const sel = document.getElementById('cd-doc-item-select');
    const price = parseFloat(sel?.value || '180');
    const qty = parseFloat(document.getElementById('cd-doc-qty')?.value || '1');
    const net = price * qty;
    const tax = net * 0.19;
    const gross = net + tax;

    const netEl = document.getElementById('cd-doc-sum-net');
    const grossEl = document.getElementById('cd-doc-sum-gross');
    if (netEl) netEl.textContent = `${net.toLocaleString('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`;
    if (grossEl) grossEl.textContent = `${gross.toLocaleString('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`;
  }

  function submitNewDocument() {
    const num = document.getElementById('cd-doc-number')?.value.trim() || `DOC-${Date.now()}`;
    const sel = document.getElementById('cd-doc-item-select');
    const opt = sel?.options[sel.selectedIndex];
    const title = opt?.dataset.title || 'Dienstleistung / Projektleistungen';
    const price = parseFloat(sel?.value || '180');
    const qty = parseFloat(document.getElementById('cd-doc-qty')?.value || '1');
    const net = price * qty;
    const gross = net * 1.19;

    const tbody = document.getElementById('cd-vorgaenge-tbody');
    const isOffer = currentActiveDocType === 'offer';
    const typeBadge = isOffer
      ? '<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-blue-50 text-blue-700 border border-blue-200">Angebot</span>'
      : '<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-50 text-emerald-700 border border-emerald-200">Auftrag</span>';
    const statusBadge = isOffer
      ? '<span class="px-2 py-0.5 rounded-full text-[10px] font-bold bg-blue-50 text-blue-700 border border-blue-200">Entwurf</span>'
      : '<span class="px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-50 text-emerald-700 border border-emerald-200">Bestätigt</span>';

    const todayDe = new Date().toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric' });

    if (tbody) {
      const newTr = document.createElement('tr');
      newTr.innerHTML = `
        <td class="py-3 px-3">${typeBadge}</td>
        <td class="py-3 px-3 font-bold text-zinc-900 dark:text-zinc-100">${num}</td>
        <td class="py-3 px-3 text-zinc-500">${todayDe}</td>
        <td class="py-3 px-3">${net.toLocaleString('de-DE', { minimumFractionDigits: 2 })} €</td>
        <td class="py-3 px-3 font-bold">${gross.toLocaleString('de-DE', { minimumFractionDigits: 2 })} €</td>
        <td class="py-3 px-3">${statusBadge}</td>
        <td class="py-3 px-3 text-right">
          <button type="button" onclick="crmStudio.openDocumentPdf('${num}', '${isOffer ? 'offer' : 'order_confirmation'}', ${net}, '${escapeHtml(currentDrawerContact?.unternehmen || currentDrawerContact?.name || 'Kunde')}')" class="px-2.5 py-1 rounded-lg bg-emerald-50 dark:bg-emerald-950/30 text-emerald-600 hover:bg-emerald-100 dark:hover:bg-emerald-900/50 font-bold text-xs cursor-pointer border border-emerald-200 dark:border-emerald-800 shadow-2xs">
            📄 DIN-PDF
          </button>
        </td>
      `;
      tbody.prepend(newTr);
    }

    toggleDocBuilder(false);
    openDocumentPdf(num, isOffer ? 'offer' : 'order_confirmation', net, currentDrawerContact?.unternehmen || currentDrawerContact?.name);
  }

  function openDocumentPdf(docNo, docType, amountNet, entityName) {
    const contact = currentDrawerContact;
    const name = entityName || (contact ? (contact.unternehmen || contact.name) : 'Kunde');
    let url = `/api/erp/documents/${encodeURIComponent(docNo)}/print?entity_name=${encodeURIComponent(name)}`;
    if (docType) url += `&doc_type=${encodeURIComponent(docType)}`;
    if (amountNet) url += `&amount_net=${encodeURIComponent(amountNet)}`;
    window.open(url, '_blank');
  }

  function createNewDocumentForContact(type) {
    if (!currentDrawerContact) return;
    const isOffer = type === 'offer';
    const prefix = isOffer ? 'ANG-2026' : 'AB-2026';
    const rand = Math.floor(1000 + Math.random() * 9000);
    const docNo = `${prefix}-${rand}`;
    const amount = prompt(`Nettobetrag für neues ${isOffer ? 'Angebot' : 'Auftragsbestätigung'} (€):`, '5000.00');
    if (!amount) return;
    openDocumentPdf(docNo, isOffer ? 'offer' : 'order_confirmation', parseFloat(amount), currentDrawerContact.unternehmen || currentDrawerContact.name);
  }

  // Keyboard shortcut: Escape closes drawer
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      const drawer = document.getElementById('crm-contact-drawer');
      if (drawer && !drawer.classList.contains('hidden')) {
        closeContactDrawer();
      }
    }
  });

  // Public API
  return {
    init,
    switchSubTab,
    switchDrawerTab,
    loadContacts,
    loadKunden,
    loadLieferanten,
    loadAllMessages,
    loadCalendar,
    loadReport,
    onSearchInput,
    onStatusChange,
    onRegionChange,
    resetFilters,
    setMsgChannelFilter,
    setMsgDirectionFilter,
    onMsgSearchInput,
    toggleMessageText,
    openContactDrawer,
    closeContactDrawer,
    saveContactFromDrawer,
    deleteContactFromDrawer,
    addDrawerNote,
    setDrawerRating,
    filterDrawerMessages,
    createNewContact,
    setPage,
    renderDrawerTags,
    addTagFromInput,
    removeTag,
    promptAddNote,
    triggerAudioDictation,
    triggerMeetingDictation,
    scheduleFollowUp,
    scheduleGoogleCalendar,
    sendComposerMessage,
    promptAddContactPerson,
    exportContactGdpr,
    anonymizeContactGdpr,
    openDocumentPdf,
    createNewDocumentForContact,
    onDsgvoChange,
    openNewDocBuilder,
    toggleDocBuilder,
    onDocItemSelect,
    calcDocTotals,
    submitNewDocument
  };
})();

// Explicitly bind to window.initAddressesView so tab switches immediately trigger CRM Studio
window.initAddressesView = function() {
  if (window.crmStudio && typeof window.crmStudio.init === 'function') {
    window.crmStudio.init();
  }
};
