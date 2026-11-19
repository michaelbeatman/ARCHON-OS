// M78: Mission Control Kanban — Gantt-Timeline & Dependency-Graph Views
(function () {
  function escHtml(str) {
    return String(str == null ? '' : str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function statusColor(status) {
    const s = String(status || '').toLowerCase();
    if (s === 'done') return '#10b981';
    if (s === 'in_progress') return '#3b82f6';
    if (s === 'blocked' || s === 'failed') return '#ef4444';
    return '#64748b';
  }

  async function renderGantt(container) {
    if (!container) return;
    container.innerHTML = '<div class="p-4 text-sm text-slate-400">Lade Gantt-Timeline...</div>';
    try {
      const res = await fetch('/api/operations/kanban/gantt');
      const data = await res.json();
      const items = data.items || [];
      if (!items.length) {
        container.innerHTML = '<div class="p-6 text-sm text-slate-400">Keine Kanban-Tasks fuer die Gantt-Timeline vorhanden.</div>';
        return;
      }
      const times = items.flatMap(i => [new Date(i.start).getTime(), new Date(i.end).getTime()]);
      const minT = Math.min(...times);
      const maxT = Math.max(...times);
      const span = Math.max(1, maxT - minT);

      const rows = items.map(item => {
        const s = new Date(item.start).getTime();
        const e = new Date(item.end).getTime();
        const leftPct = Math.max(0, Math.min(96, ((s - minT) / span) * 100));
        const widthPct = Math.max(3, Math.min(100 - leftPct, ((e - s) / span) * 100));
        const color = statusColor(item.status);
        return `
          <div class="flex items-center gap-3 py-1.5 border-b border-slate-800/60 text-xs">
            <div class="w-56 shrink-0 truncate font-medium text-slate-200" title="${escHtml(item.title)}">${escHtml(item.title)}</div>
            <div class="w-24 shrink-0 text-slate-400 truncate">${escHtml(item.assignee || '—')}</div>
            <div class="flex-1 h-5 bg-slate-900/80 rounded relative overflow-hidden">
              <div style="left:${leftPct.toFixed(1)}%;width:${widthPct.toFixed(1)}%;background:${color};"
                   class="absolute top-0.5 bottom-0.5 rounded opacity-90"
                   title="${escHtml(item.start)} -> ${escHtml(item.end)} (${escHtml(item.duration_hours)}h)"></div>
            </div>
            <div class="w-16 shrink-0 text-right text-slate-400">${escHtml(item.duration_hours)}h</div>
          </div>`;
      }).join('');

      container.innerHTML = `<div class="p-4 bg-slate-950/60 rounded-xl border border-slate-800 overflow-x-auto">${rows}</div>`;
    } catch (err) {
      container.innerHTML = `<div class="p-4 text-sm text-red-400">Gantt-Fehler: ${escHtml(err.message)}</div>`;
    }
  }

  async function renderGraph(container) {
    if (!container) return;
    container.innerHTML = '<div class="p-4 text-sm text-slate-400">Lade Dependency-Graph...</div>';
    try {
      const res = await fetch('/api/operations/kanban/graph');
      const data = await res.json();
      const nodes = data.nodes || [];
      const edges = data.edges || [];
      if (!nodes.length) {
        container.innerHTML = '<div class="p-6 text-sm text-slate-400">Keine Tasks fuer den Dependency-Graph vorhanden.</div>';
        return;
      }

      const byLayer = new Map();
      nodes.forEach(n => {
        const l = Number(n.layer || 0);
        if (!byLayer.has(l)) byLayer.set(l, []);
        byLayer.get(l).push(n);
      });

      const layersHtml = [...byLayer.entries()].sort((a, b) => a[0] - b[0]).map(([layer, list]) => {
        const cards = list.map(n => `
          <div class="p-2.5 rounded-lg bg-slate-900 border border-slate-700/80 text-xs shadow-sm">
            <div class="flex items-center justify-between gap-2 mb-1">
              <span class="font-mono text-[10px] text-slate-400">${escHtml(n.id)}</span>
              <span class="px-1.5 py-0.5 rounded text-[10px] text-white" style="background:${statusColor(n.status)}">${escHtml(n.status)}</span>
            </div>
            <div class="font-medium text-slate-100 line-clamp-2">${escHtml(n.title)}</div>
            <div class="mt-1 text-[10px] text-slate-400">Abhaengig von: ${escHtml((n.blocked_by || []).length)} | Blockiert: ${escHtml((n.blocks || []).length)}</div>
          </div>`).join('');
        return `
          <div class="min-w-[220px] flex-1 space-y-2">
            <div class="text-[11px] font-semibold uppercase tracking-wider text-slate-400 px-1">Phase ${escHtml(layer + 1)}</div>
            ${cards}
          </div>`;
      }).join('');

      container.innerHTML = `
        <div class="p-4 bg-slate-950/60 rounded-xl border border-slate-800 space-y-3">
          <div class="text-xs text-slate-400">Knoten: ${escHtml(nodes.length)} | Abhaengigkeits-Kanten: ${escHtml(edges.length)}</div>
          <div class="flex gap-4 overflow-x-auto pb-2">${layersHtml}</div>
        </div>`;
    } catch (err) {
      container.innerHTML = `<div class="p-4 text-sm text-red-400">Graph-Fehler: ${escHtml(err.message)}</div>`;
    }
  }

  function setOpsKanbanViewMode(mode) {
    const m = ['board', 'gantt', 'graph'].includes(mode) ? mode : 'board';
    const boardEl = document.getElementById('ops-kanban-columns-container');
    const altEl = document.getElementById('ops-kanban-alt-view');
    const btns = {
      board: document.getElementById('btn-kanban-mode-board'),
      gantt: document.getElementById('btn-kanban-mode-gantt'),
      graph: document.getElementById('btn-kanban-mode-graph'),
    };
    Object.entries(btns).forEach(([k, btn]) => {
      if (!btn) return;
      const active = k === m;
      btn.className = active
        ? 'h-7 px-2.5 rounded-md font-bold bg-[var(--primary)] text-[var(--primary-foreground)] transition cursor-pointer'
        : 'h-7 px-2.5 rounded-md font-medium text-muted-custom hover:text-primary-custom transition cursor-pointer';
    });
    if (m === 'board') {
      if (boardEl) boardEl.classList.remove('hidden');
      if (altEl) altEl.classList.add('hidden');
      return;
    }
    if (boardEl) boardEl.classList.add('hidden');
    if (altEl) {
      altEl.classList.remove('hidden');
      if (m === 'gantt') renderGantt(altEl);
      else if (m === 'graph') renderGraph(altEl);
    }
  }

  window.setOpsKanbanViewMode = setOpsKanbanViewMode;
  window.archonKanbanViews = { renderGantt, renderGraph, setOpsKanbanViewMode };
})();
