// Archon v2 Capabilities UI Bridge (M32-M94)
(function () {
  function esc(str) {
    return String(str == null ? '' : str)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  async function renderControlPanel(container) {
    if (!container) return;
    container.innerHTML = '<div class="p-4 text-xs text-slate-400">Lade Archon v2 Module...</div>';
    try {
      const [tplRes, taintRes, deckRes] = await Promise.all([
        fetch('/api/v2/operations/templates').then(r => r.json()).catch(() => ({ templates: [] })),
        fetch('/api/v1/guardian/taint/approvals').then(r => r.json()).catch(() => ({ approvals: [] })),
        fetch('/api/v2/eval/gold-deck').then(r => r.json()).catch(() => ({ deck: [] })),
      ]);

      const templates = tplRes.templates || [];
      const approvals = taintRes.approvals || [];
      const deck = deckRes.deck || [];

      container.innerHTML = `
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4 p-4">
          <div class="p-4 rounded-xl border border-[var(--border)] bg-[var(--card)] space-y-2">
            <h4 class="text-xs font-bold uppercase tracking-wider">Offene Taint-HITL-Freigaben (M89)</h4>
            <div class="text-xs text-[var(--muted-foreground)]">${esc(approvals.length)} ausstehende Freigabe(n)</div>
          </div>
          <div class="p-4 rounded-xl border border-[var(--border)] bg-[var(--card)] space-y-2">
            <h4 class="text-xs font-bold uppercase tracking-wider">Operations-Vorlagen (M62)</h4>
            <div class="text-xs text-[var(--muted-foreground)]">${esc(templates.length)} aktive Vorlagen verfuegbar</div>
          </div>
          <div class="p-4 rounded-xl border border-[var(--border)] bg-[var(--card)] space-y-2">
            <h4 class="text-xs font-bold uppercase tracking-wider">Eval-Benchmark-Deck (M50)</h4>
            <div class="text-xs text-[var(--muted-foreground)]">${esc(deck.length)} Referenz-Aufgaben geladen</div>
          </div>
        </div>`;
    } catch (err) {
      container.innerHTML = `<div class="p-4 text-xs text-red-400">Fehler beim Laden: ${esc(err.message)}</div>`;
    }
  }

  window.archonV2Panel = { renderControlPanel };
})();
