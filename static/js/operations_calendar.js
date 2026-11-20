/**
 * static/js/operations_calendar.js
 * M25 — Operations-Kalender UI (Kachel in Operations + Modal für ERP, Kanban, n8n & Termine)
 */
(function () {
  "use strict";

  const MODAL_ID = "archon-calendar-modal";
  let activeSource = "all";

  function _calT(key, fallback) {
    if (window.archonI18n && typeof window.archonI18n.t === "function") {
      return window.archonI18n.t(key, fallback);
    }
    return fallback;
  }

  function _escCal(str) {
    return String(str ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  async function api(url, opts) {
    const res = await fetch(url, opts);
    if (!res.ok) {
      const msg = await res.text().catch(() => "");
      throw new Error(msg || `HTTP ${res.status}`);
    }
    return await res.json();
  }

  function applyModalTranslations(modal) {
    if (!modal) return;
    const titleEl = modal.querySelector("#cal-modal-title");
    if (titleEl) titleEl.textContent = _calT("ui.operations_calendar.modal_title", "Operations-Kalender (Kanban, ERP, n8n & Termine)");
    const closeBtn = modal.querySelector("#cal-close-btn");
    if (closeBtn) closeBtn.textContent = _calT("ui.operations_calendar.close_btn", "Schließen");
    const filterMap = {
      all: ["ui.operations_calendar.filter_all", "Alle"],
      kanban: ["ui.operations_calendar.filter_kanban", "Kanban"],
      erp: ["ui.operations_calendar.filter_erp", "ERP-Fälligkeiten"],
      n8n: ["ui.operations_calendar.filter_n8n", "n8n-Crons"],
      custom: ["ui.operations_calendar.filter_custom", "Eigene Termine"],
    };
    modal.querySelectorAll(".cal-filter").forEach((b) => {
      const spec = filterMap[b.dataset.calsrc];
      if (spec) b.textContent = _calT(spec[0], spec[1]);
    });
    const newTitleInput = modal.querySelector("#cal-new-title");
    if (newTitleInput) newTitleInput.placeholder = _calT("ui.operations_calendar.ph_new_title", "Neuer Termin / Geburtstag / Frist...");
    const addBtn = modal.querySelector("#cal-add-btn");
    if (addBtn) addBtn.textContent = _calT("ui.operations_calendar.add_btn", "+ Anlegen");
  }

  function ensureModal() {
    let modal = document.getElementById(MODAL_ID);
    if (modal) {
      applyModalTranslations(modal);
      return modal;
    }
    modal = document.createElement("div");
    modal.id = MODAL_ID;
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");
    modal.className = "fixed inset-0 z-50 hidden items-center justify-center bg-black/60 p-4";
    modal.innerHTML = `
      <div class="w-full max-w-3xl rounded-xl border theme-border bg-white dark:bg-zinc-900 p-5 shadow-2xl max-h-[88vh] flex flex-col gap-3">
        <div class="flex items-center justify-between border-b theme-border pb-2">
          <h2 id="cal-modal-title" class="text-base font-bold"></h2>
          <button id="cal-close-btn" class="px-2 py-1 text-xs rounded border theme-border"></button>
        </div>
        <div class="flex flex-wrap gap-1.5 text-xs">
          <button data-calsrc="all" class="cal-filter px-2.5 py-1 rounded border theme-border font-semibold"></button>
          <button data-calsrc="kanban" class="cal-filter px-2.5 py-1 rounded border theme-border"></button>
          <button data-calsrc="erp" class="cal-filter px-2.5 py-1 rounded border theme-border"></button>
          <button data-calsrc="n8n" class="cal-filter px-2.5 py-1 rounded border theme-border"></button>
          <button data-calsrc="custom" class="cal-filter px-2.5 py-1 rounded border theme-border"></button>
        </div>
        <div class="flex flex-wrap gap-2 items-center text-xs border theme-border rounded p-2">
          <input id="cal-new-title" class="flex-1 min-w-[160px] p-1.5 rounded border theme-border bg-transparent" />
          <input id="cal-new-date" type="date" class="p-1.5 rounded border theme-border bg-transparent" />
          <input id="cal-new-time" type="time" class="p-1.5 rounded border theme-border bg-transparent" />
          <button id="cal-add-btn" class="px-3 py-1.5 rounded bg-indigo-600 text-white font-semibold"></button>
        </div>
        <div id="cal-list" class="overflow-y-auto flex-1 space-y-1.5 text-xs"></div>
      </div>`;
    document.body.appendChild(modal);
    applyModalTranslations(modal);

    modal.querySelector("#cal-close-btn").onclick = () => {
      modal.classList.add("hidden");
      modal.classList.remove("flex");
    };
    modal.querySelectorAll(".cal-filter").forEach((b) => {
      b.onclick = () => {
        activeSource = b.dataset.calsrc;
        loadEvents();
      };
    });
    modal.querySelector("#cal-add-btn").onclick = async () => {
      const title = document.getElementById("cal-new-title").value.trim();
      const date = document.getElementById("cal-new-date").value;
      const time = document.getElementById("cal-new-time").value;
      if (!title || !date) return;
      await api("/api/v1/calendar/events", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, date, time, category: "appointment" }),
      });
      document.getElementById("cal-new-title").value = "";
      loadEvents();
    };
    return modal;
  }

  async function loadEvents() {
    const listEl = document.getElementById("cal-list");
    if (!listEl) return;
    const data = await api(`/api/v1/calendar/events?source=${encodeURIComponent(activeSource)}`);
    const events = data.events || [];
    if (!events.length) {
      listEl.innerHTML = `<div class="opacity-60 p-3">${_escCal(_calT("ui.operations_calendar.empty_list", "Keine Einträge für diesen Filter."))}</div>`;
      return;
    }
    const delLabel = _escCal(_calT("ui.operations_calendar.delete_btn", "Löschen"));
    listEl.innerHTML = events
      .map(
        (ev) => `
      <div class="p-2.5 rounded border theme-border flex items-center justify-between gap-2">
        <div>
          <span class="font-mono font-semibold">${_escCal(ev.date)}${ev.time ? " " + _escCal(ev.time) : ""}</span>
          <span class="ml-2 font-medium">${_escCal(ev.title)}</span>
          <span class="ml-2 opacity-60">[${_escCal(ev.source)}]</span>
        </div>
        ${
          ev.source === "custom"
            ? `<button data-caldel="${_escCal(ev.id)}" class="px-2 py-0.5 rounded border theme-border text-[11px]">${delLabel}</button>`
            : ""
        }
      </div>`
      )
      .join("");
    listEl.querySelectorAll("[data-caldel]").forEach((b) => {
      b.onclick = async () => {
        if (!confirm(_calT("ui.operations_calendar.confirm_delete", "Diesen Termin wirklich löschen?"))) return;
        await api(`/api/v1/calendar/events/${encodeURIComponent(b.dataset.caldel)}`, { method: "DELETE" });
        loadEvents();
      };
    });
  }

  window.openOperationsCalendar = function () {
    const m = ensureModal();
    m.classList.remove("hidden");
    m.classList.add("flex");
    loadEvents();
  };

  function updateTileLabel() {
    const btn = document.getElementById("ops-subtab-calendar");
    if (!btn) return;
    btn.title = _calT("ui.operations_calendar.tile_title", "Operations-Kalender (M25)");
    const lbl = btn.querySelector(".ops-tab-label");
    if (lbl) lbl.textContent = _calT("ui.operations_calendar.tile_label", "Kalender");
  }

  function injectCalendarTile() {
    if (document.getElementById("ops-subtab-calendar")) {
      updateTileLabel();
      return true;
    }
    const anchor =
      document.getElementById("ops-subtab-playbooks") ||
      document.getElementById("ops-subtab-org") ||
      document.getElementById("ops-subtab-kanban");
    if (!anchor || !anchor.parentNode) return false;

    const btn = document.createElement("button");
    btn.type = "button";
    btn.id = "ops-subtab-calendar";
    btn.title = _calT("ui.operations_calendar.tile_title", "Operations-Kalender (M25)");
    btn.className =
      "ops-header-tile flex flex-col items-center justify-between min-w-[56px] sm:min-w-[62px] h-[72px] py-1 px-0.5 bg-transparent border-0 shadow-none opacity-80 hover:opacity-100 cursor-pointer select-none transition-transform hover:scale-105 duration-150";
    btn.innerHTML = `
      <div class="tile-icon-wrap w-11 h-11 sm:w-12 sm:h-12 flex items-center justify-center mb-0.5 relative">
        <img src="/static/img/cadre_icons/calendar.png?v=2026112045" alt="Kalender" class="w-full h-full object-contain drop-shadow-xs pointer-events-none">
      </div>
      <span class="ops-tab-label text-[10px] font-mono tracking-tight text-center whitespace-nowrap text-[var(--foreground)] font-medium leading-none">${_escCal(_calT("ui.operations_calendar.tile_label", "Kalender"))}</span>`;
    btn.onclick = window.openOperationsCalendar;
    anchor.parentNode.insertBefore(btn, anchor.nextSibling);
    return true;
  }

  function mountTileWithObserver() {
    if (injectCalendarTile()) return;
    let retries = 0;
    const maxRetries = 12;
    let obs = null;
    const tryMount = () => {
      if (injectCalendarTile()) {
        if (obs) obs.disconnect();
        return true;
      }
      return false;
    };
    const rootTarget = document.getElementById("view-operations") || document.body;
    if (rootTarget && typeof MutationObserver !== "undefined") {
      obs = new MutationObserver(() => { tryMount(); });
      obs.observe(rootTarget, { childList: true, subtree: true });
    }
    const tick = () => {
      if (tryMount() || ++retries >= maxRetries) {
        if (obs) obs.disconnect();
        return;
      }
      setTimeout(tick, 250);
    };
    setTimeout(tick, 250);
  }

  window.addEventListener("archon:language-changed", () => {
    updateTileLabel();
    const modal = document.getElementById(MODAL_ID);
    if (modal) {
      applyModalTranslations(modal);
      if (!modal.classList.contains("hidden")) loadEvents();
    }
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mountTileWithObserver);
  } else {
    mountTileWithObserver();
  }
})();
