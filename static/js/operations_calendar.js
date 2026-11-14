/**
 * static/js/operations_calendar.js
 * M25 — Operations-Kalender UI (Kachel in Operations + Modal für ERP, Kanban, n8n & Termine)
 */
(function () {
  "use strict";

  const MODAL_ID = "archon-calendar-modal";
  let activeSource = "all";

  async function api(url, opts) {
    const res = await fetch(url, opts);
    return await res.json();
  }

  function ensureModal() {
    let modal = document.getElementById(MODAL_ID);
    if (modal) return modal;
    modal = document.createElement("div");
    modal.id = MODAL_ID;
    modal.className = "fixed inset-0 z-50 hidden items-center justify-center bg-black/60 p-4";
    modal.innerHTML = `
      <div class="w-full max-w-3xl rounded-xl border theme-border bg-white dark:bg-zinc-900 p-5 shadow-2xl max-h-[88vh] flex flex-col gap-3">
        <div class="flex items-center justify-between border-b theme-border pb-2">
          <h2 class="text-base font-bold">Operations-Kalender (Kanban, ERP, n8n &amp; Termine)</h2>
          <button id="cal-close-btn" class="px-2 py-1 text-xs rounded border theme-border">Schließen</button>
        </div>
        <div class="flex flex-wrap gap-1.5 text-xs">
          <button data-calsrc="all" class="cal-filter px-2.5 py-1 rounded border theme-border font-semibold">Alle</button>
          <button data-calsrc="kanban" class="cal-filter px-2.5 py-1 rounded border theme-border">Kanban</button>
          <button data-calsrc="erp" class="cal-filter px-2.5 py-1 rounded border theme-border">ERP-Fälligkeiten</button>
          <button data-calsrc="n8n" class="cal-filter px-2.5 py-1 rounded border theme-border">n8n-Crons</button>
          <button data-calsrc="custom" class="cal-filter px-2.5 py-1 rounded border theme-border">Eigene Termine</button>
        </div>
        <div class="flex flex-wrap gap-2 items-center text-xs border theme-border rounded p-2">
          <input id="cal-new-title" class="flex-1 min-w-[160px] p-1.5 rounded border theme-border bg-transparent" placeholder="Neuer Termin / Geburtstag / Frist..." />
          <input id="cal-new-date" type="date" class="p-1.5 rounded border theme-border bg-transparent" />
          <input id="cal-new-time" type="time" class="p-1.5 rounded border theme-border bg-transparent" />
          <button id="cal-add-btn" class="px-3 py-1.5 rounded bg-indigo-600 text-white font-semibold">+ Anlegen</button>
        </div>
        <div id="cal-list" class="overflow-y-auto flex-1 space-y-1.5 text-xs"></div>
      </div>`;
    document.body.appendChild(modal);

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
      listEl.innerHTML = `<div class="opacity-60 p-3">Keine Einträge für diesen Filter.</div>`;
      return;
    }
    listEl.innerHTML = events
      .map(
        (ev) => `
      <div class="p-2.5 rounded border theme-border flex items-center justify-between gap-2">
        <div>
          <span class="font-mono font-semibold">${ev.date}${ev.time ? " " + ev.time : ""}</span>
          <span class="ml-2 font-medium">${ev.title}</span>
          <span class="ml-2 opacity-60">[${ev.source}]</span>
        </div>
        ${
          ev.source === "custom"
            ? `<button data-caldel="${ev.id}" class="px-2 py-0.5 rounded border theme-border text-[11px]">Löschen</button>`
            : ""
        }
      </div>`
      )
      .join("");
    listEl.querySelectorAll("[data-caldel]").forEach((b) => {
      b.onclick = async () => {
        await api(`/api/v1/calendar/events/${b.dataset.caldel}`, { method: "DELETE" });
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

  function injectCalendarTile() {
    if (document.getElementById("ops-subtab-calendar")) return;
    const anchor =
      document.getElementById("ops-subtab-playbooks") ||
      document.getElementById("ops-subtab-org") ||
      document.getElementById("ops-subtab-kanban");
    if (!anchor || !anchor.parentNode) return;

    const btn = document.createElement("button");
    btn.type = "button";
    btn.id = "ops-subtab-calendar";
    btn.title = "Operations-Kalender (M25)";
    btn.className =
      "ops-header-tile flex flex-col items-center justify-between min-w-[56px] sm:min-w-[62px] h-[72px] py-1 px-0.5 bg-transparent border-0 shadow-none opacity-80 hover:opacity-100 cursor-pointer select-none transition-transform hover:scale-105 duration-150";
    btn.innerHTML = `
      <div class="tile-icon-wrap w-11 h-11 sm:w-12 sm:h-12 flex items-center justify-center mb-0.5 relative">
        <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <rect x="3" y="4" width="18" height="18" rx="2"/>
          <line x1="16" y1="2" x2="16" y2="6"/>
          <line x1="8" y1="2" x2="8" y2="6"/>
          <line x1="3" y1="10" x2="21" y2="10"/>
        </svg>
      </div>
      <span class="ops-tab-label text-[10px] font-mono tracking-tight text-center whitespace-nowrap text-[var(--foreground)] font-medium leading-none">Kalender</span>`;
    btn.onclick = window.openOperationsCalendar;
    anchor.parentNode.insertBefore(btn, anchor.nextSibling);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", injectCalendarTile);
  } else {
    injectCalendarTile();
  }
})();
