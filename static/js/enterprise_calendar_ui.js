// M55: Enterprise-Kalender UI (Tag / Woche / Monat + Agenten-Ansicht)
(function () {
  function esc(str) {
    return String(str == null ? '' : str)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function renderGrid(container, events, view) {
    if (!container) return;
    const list = Array.isArray(events) ? events : [];
    const byDay = new Map();
    list.forEach(ev => {
      const d = String(ev.start || '').slice(0, 10) || 'Ungeplant';
      if (!byDay.has(d)) byDay.set(d, []);
      byDay.get(d).push(ev);
    });
    const cols = [...byDay.entries()].sort((a, b) => a[0].localeCompare(b[0])).map(([day, items]) => {
      const cards = items.map(it =>
        `<div draggable="true" data-event-id="${esc(it.id)}" class="p-2 rounded-lg bg-slate-900 border border-slate-700 text-xs">
           <div class="font-medium text-slate-100">${esc(it.title || it.id)}</div>
           <div class="text-[10px] text-slate-400">${esc(it.assignee || 'System')} · ${esc(String(it.start || '').slice(11, 16))}</div>
         </div>`
      ).join('');
      return `<div class="min-w-[180px] flex-1 space-y-2"><div class="text-xs font-semibold text-slate-300 border-b border-slate-800 pb-1">${esc(day)}</div>${cards}</div>`;
    }).join('');
    container.innerHTML = `<div class="p-3 rounded-xl border border-slate-800 bg-slate-950/60"><div class="text-[11px] text-slate-400 mb-2">Ansicht: ${esc(view || 'week')}</div><div class="flex gap-3 overflow-x-auto">${cols || '<div class="text-xs text-slate-400">Keine Termine.</div>'}</div></div>`;
  }

  window.archonEnterpriseCalendar = { renderGrid };
})();
