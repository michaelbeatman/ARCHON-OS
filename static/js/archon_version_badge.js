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
    if (!row) {
      const ledsRow = document.getElementById("sidebar-update-leds-row");
      const hermesUpdateBtn = document.getElementById("status-badge-update");
      const parent = ledsRow || (hermesUpdateBtn ? hermesUpdateBtn.parentElement : null);
      if (!parent) return null;

      row = document.createElement("button");
      row.type = "button";
      row.id = ROW_ID;
      row.className =
        "flex items-center gap-1 hover:text-[var(--foreground)] transition cursor-pointer select-none py-0.5 min-w-0";
      row.title = "Archon OS Update-Status wird geprüft...";
      row.innerHTML =
        '<span id="dot-archon-update" class="w-1.5 h-1.5 rounded-full bg-zinc-400 shrink-0 transition-colors"></span><span>Archon</span><span id="sidebar-archon-version-text" class="truncate"></span>';
      parent.insertBefore(row, hermesUpdateBtn || parent.firstChild);
    }

    row.onclick = openArchonUpdateSettings;

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

    const dotEl = document.getElementById("dot-archon-update");
    const verEl = document.getElementById("sidebar-archon-version-text");
    if (!dotEl) return;

    const curVer = data.version || "v0.5.7";
    if (verEl) verEl.textContent = curVer;

    if (isLocalOnly) {
      dotEl.className = "w-1.5 h-1.5 rounded-full bg-sky-500 animate-pulse shrink-0 transition-colors";
      if (verEl) verEl.className = "truncate text-sky-600 dark:text-sky-400";
      row.title = `Archon OS ${curVer} — prüfe GitHub-Status...`;
      return;
    }

    if (data.status === "offline_or_error" || data.status === "error") {
      dotEl.className = "w-1.5 h-1.5 rounded-full bg-zinc-400 shrink-0 transition-colors";
      if (verEl) verEl.className = "truncate text-[var(--muted-foreground)]";
      row.className =
        "flex items-center gap-1 hover:text-[var(--foreground)] transition cursor-pointer select-none py-0.5 min-w-0";
      row.title = `Archon OS ${curVer} (${data.message || "GitHub offline"}) — Klick öffnet System-Update`;
      return;
    }

    if (data.update_available) {
      const remoteVer = data.remote_version && data.remote_version !== curVer ? data.remote_version : null;
      const behind = Number(data.commits_behind || 0);
      dotEl.className = "w-1.5 h-1.5 rounded-full bg-rose-500 animate-pulse shrink-0 transition-colors";
      if (verEl) {
        verEl.textContent = remoteVer || curVer;
        verEl.className = "truncate text-rose-600 dark:text-rose-400 font-semibold";
      }
      row.className =
        "flex items-center gap-1 hover:text-[var(--foreground)] transition cursor-pointer select-none py-0.5 min-w-0";
      row.title = `Archon OS Update verfügbar (${remoteVer || "+" + (behind || 1) + " Commits"}, aktuell ${curVer}) — Klick öffnet Settings -> System-Update`;
    } else {
      dotEl.className = "w-1.5 h-1.5 rounded-full bg-emerald-500 shrink-0 transition-colors";
      if (verEl) verEl.className = "truncate text-emerald-600 dark:text-emerald-400";
      row.className =
        "flex items-center gap-1 hover:text-[var(--foreground)] transition cursor-pointer select-none py-0.5 min-w-0";
      row.title = `Archon OS ${curVer} ist aktuell — Klick öffnet Settings -> System-Update`;
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

  setInterval(() => {
    if (typeof document !== "undefined" && document.hidden) return;
    checkArchonVersionBadge(false);
  }, 5 * 60 * 1000);
})();
