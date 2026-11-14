/**
 * static/js/archon_version_badge.js
 * M56 — Archon OS Versionsanzeige & GitHub-Update-Badge unten links in der Sidebar
 * (analog zur Hermes-Agent-Versionsanzeige) mit 1-Klick-Sprung in Settings -> System-Update.
 * Eigene SVG-Icons in Markenfarben (Rot/Orange/Gelb), kein Emoji-Einsatz.
 */
(function () {
  "use strict";

  const ROW_ID = "sidebar-archon-version-row";
  let isCheckingArchon = false;

  const ARCHON_ICON_SVG =
    '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/></svg>';

  const ARROW_UP_SVG =
    '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5"/><path d="m5 12 7-7 7 7"/></svg>';

  function esc(v) {
    return String(v == null ? "" : v)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function openArchonUpdateSettings() {
    if (typeof window.openSystemSettingsModal === "function") {
      window.openSystemSettingsModal("update");
      if (typeof window.checkArchonSystemUpdate === "function") {
        setTimeout(() => window.checkArchonSystemUpdate(false), 150);
      }
    }
  }

  function ensureSidebarRow() {
    let row = document.getElementById(ROW_ID);
    if (row) return row;

    const hermesUpdateBtn = document.getElementById("status-badge-update");
    const statusStrip = hermesUpdateBtn ? hermesUpdateBtn.parentElement : null;
    if (!statusStrip || !statusStrip.parentElement) return null;

    row = document.createElement("button");
    row.type = "button";
    row.id = ROW_ID;
    row.className =
      "w-full flex items-center justify-between gap-1.5 px-2 py-1 rounded-lg border border-[var(--border)]/70 hover:border-amber-500/50 bg-black/[0.02] dark:bg-white/[0.02] hover:bg-amber-500/5 transition cursor-pointer select-none text-[10px] font-mono";
    row.title = "Archon OS Version & GitHub-Update prüfen (öffnet Settings -> System-Update)";
    row.innerHTML = `
      <span class="flex items-center gap-1.5 min-w-0">
        ${ARCHON_ICON_SVG}
        <span class="text-[var(--muted-foreground)]">Archon</span>
        <strong id="sidebar-archon-version-text" class="text-[var(--foreground)] font-bold truncate">...</strong>
      </span>
      <span id="sidebar-archon-update-pill" class="px-1.5 py-0.5 rounded text-[9.5px] font-semibold border border-[var(--border)] text-[var(--muted-foreground)] shrink-0">
        Prüfe...
      </span>`;
    row.onclick = openArchonUpdateSettings;

    statusStrip.parentElement.insertBefore(row, statusStrip);

    const syncBtn = document.getElementById("btn-sidebar-sync");
    if (syncBtn && !syncBtn.dataset.archonSyncBound) {
      syncBtn.dataset.archonSyncBound = "1";
      syncBtn.addEventListener("click", () => checkArchonVersionBadge(true));
    }

    return row;
  }

  function applyBadgeState(data, isLocalOnly) {
    const row = ensureSidebarRow();
    if (!row || !data) return;

    const verEl = document.getElementById("sidebar-archon-version-text");
    const pillEl = document.getElementById("sidebar-archon-update-pill");
    if (!verEl || !pillEl) return;

    const curVer = data.version || "v0.5.2.1";
    verEl.textContent = curVer;

    if (isLocalOnly) {
      pillEl.className =
        "px-1.5 py-0.5 rounded text-[9.5px] font-medium border border-[var(--border)] text-[var(--muted-foreground)] shrink-0";
      pillEl.textContent = "GitHub...";
      return;
    }

    if (data.status === "offline_or_error" || data.status === "error") {
      pillEl.className =
        "px-1.5 py-0.5 rounded text-[9.5px] font-medium border border-zinc-500/30 text-zinc-400 shrink-0";
      pillEl.textContent = "Lokal";
      row.title = `Archon OS ${curVer} (${data.message || "GitHub offline"}) — Klick öffnet System-Update`;
      return;
    }

    if (data.update_available) {
      const remoteVer = data.remote_version && data.remote_version !== curVer ? data.remote_version : null;
      const behind = Number(data.commits_behind || 0);
      const badgeLabel = remoteVer ? `Update ${esc(remoteVer)}` : `Update +${behind || 1}`;

      pillEl.className =
        "inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[9.5px] font-bold bg-gradient-to-r from-red-600 to-amber-500 text-white shadow-xs animate-pulse shrink-0";
      pillEl.innerHTML = `${ARROW_UP_SVG}<span>${badgeLabel}</span>`;
      row.className =
        "w-full flex items-center justify-between gap-1.5 px-2 py-1 rounded-lg border border-amber-500/60 bg-amber-500/10 hover:bg-amber-500/15 transition cursor-pointer select-none text-[10px] font-mono";
      row.title = `Neue Archon-Version auf GitHub verfügbar (${remoteVer || behind + " Commits"}) — Klick öffnet Settings -> System-Update`;
    } else {
      pillEl.className =
        "inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[9.5px] font-semibold bg-emerald-500/10 text-emerald-500 border border-emerald-500/25 shrink-0";
      pillEl.innerHTML = `<span class="w-1.5 h-1.5 rounded-full bg-emerald-500"></span><span>Aktuell</span>`;
      row.className =
        "w-full flex items-center justify-between gap-1.5 px-2 py-1 rounded-lg border border-[var(--border)]/70 hover:border-amber-500/40 bg-black/[0.02] dark:bg-white/[0.02] transition cursor-pointer select-none text-[10px] font-mono";
      row.title = `Archon OS ${curVer} ist auf dem neuesten GitHub-Stand — Klick öffnet Settings -> System-Update`;
    }
  }

  async function checkArchonVersionBadge(force = false) {
    ensureSidebarRow();
    if (isCheckingArchon) return;
    isCheckingArchon = true;

    try {
      // Phase 1: Sofort lokale Version anzeigen (<10ms)
      try {
        const localRes = await fetch("/api/v1/system/update/check?local_only=true");
        if (localRes.ok) {
          const localData = await localRes.json();
          applyBadgeState(localData, true);
        }
      } catch (_) {}

      // Phase 2: GitHub Remote-Stand prüfen
      const url = force ? "/api/v1/system/update/check?force=true" : "/api/v1/system/update/check";
      const res = await fetch(url);
      if (res.ok) {
        const fullData = await res.json();
        applyBadgeState(fullData, false);
      }
    } catch (_) {
    } finally {
      isCheckingArchon = false;
    }
  }

  window.checkArchonVersionBadge = checkArchonVersionBadge;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      ensureSidebarRow();
      setTimeout(() => checkArchonVersionBadge(false), 1200);
    });
  } else {
    ensureSidebarRow();
    setTimeout(() => checkArchonVersionBadge(false), 1200);
  }

  setInterval(() => checkArchonVersionBadge(false), 5 * 60 * 1000);
})();
