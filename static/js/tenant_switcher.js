/**
 * static/js/tenant_switcher.js
 * M43 — Multi-Mandanten-Umschalter (Holding / Operative GmbH / SPV) in der Topbar/Sidebar
 * inkl. Live-Refresh aktiver Fachmodule und 1-Klick Mandanten-/DB-Isolations-Dialog.
 */
(function () {
  "use strict";

  const CONTAINER_ID = "archon-tenant-switcher";
  const MODAL_ID = "archon-tenant-isolation-modal";
  const BADGE_SVG =
    '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 21h18"/><path d="M5 21V7l8-4v18"/><path d="M19 21V11l-6-4"/><path d="M9 9v.01"/><path d="M9 12v.01"/><path d="M9 15v.01"/><path d="M9 18v.01"/></svg>';
  const GEAR_SVG =
    '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9c.26.6.77 1.02 1.41 1.09H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>';

  function _tenT(key, fallback) {
    if (window.archonI18n && typeof window.archonI18n.t === "function") {
      return window.archonI18n.t(key, fallback);
    }
    return fallback;
  }

  function esc(v) {
    return String(v == null ? "" : v)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  async function fetchTenantContext() {
    try {
      const res = await fetch("/api/v1/tenants/context");
      if (!res.ok) return null;
      return await res.json();
    } catch (_) {
      return null;
    }
  }

  function reloadActiveModuleViews() {
    const hooks = [
      "loadKanbanBoard",
      "refreshKanban",
      "loadDealsPipeline",
      "loadContractsList",
      "loadCrmContacts",
      "erpReloadCurrentTab",
    ];
    for (const fnName of hooks) {
      if (typeof window[fnName] === "function") {
        try {
          window[fnName]();
        } catch (_) {}
      }
    }
  }

  async function switchTenant(companyId) {
    try {
      const res = await fetch("/api/v1/tenants/switch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ company_id: companyId }),
      });
      if (res.ok) {
        await renderTenantSwitcher();
        reloadActiveModuleViews();
        window.dispatchEvent(new CustomEvent("archon:tenant-switched", { detail: { companyId } }));
      }
    } catch (_) {}
  }

  async function openTenantIsolationModal() {
    let modal = document.getElementById(MODAL_ID);
    if (!modal) {
      modal = document.createElement("div");
      modal.id = MODAL_ID;
      modal.setAttribute("role", "dialog");
      modal.setAttribute("aria-modal", "true");
      modal.className = "fixed inset-0 z-50 hidden items-center justify-center bg-black/70 backdrop-blur-sm p-4";
      document.body.appendChild(modal);
    }

    const ctx = await fetchTenantContext();
    if (!ctx) return;
    const dbs = (ctx.isolation && ctx.isolation.databases) || {};
    const ranges = ctx.number_ranges || {};
    const active = ctx.active_company || {};

    modal.innerHTML = `
      <div class="w-full max-w-3xl rounded-2xl border theme-border bg-white dark:bg-zinc-900 p-5 shadow-2xl max-h-[88vh] overflow-y-auto space-y-4 text-xs">
        <div class="flex items-center justify-between border-b theme-border pb-2.5">
          <div>
            <h3 class="text-sm font-bold">${esc(_tenT("ui.tenant_switcher.modal_title", "Multi-Mandanten-DB-Isolation & Nummernkreise (M43)"))}</h3>
            <p class="text-[11px] opacity-70">${esc(_tenT("ui.tenant_switcher.active_company", "Aktive Gesellschaft:"))} <strong>${esc(active.name || ctx.active_tenant_id)}</strong> (${esc(active.entity_type || "operative_gmbh")})</p>
          </div>
          <button id="m43-close-btn" type="button" class="px-2.5 py-1 rounded border theme-border">${esc(_tenT("ui.tenant_switcher.close_btn", "Schließen"))}</button>
        </div>

        <div class="overflow-x-auto rounded-lg border theme-border">
          <table class="w-full text-left border-collapse">
            <thead>
              <tr class="border-b theme-border bg-black/5 dark:bg-white/5 text-[11px]">
                <th class="p-2 font-semibold">${esc(_tenT("ui.tenant_switcher.col_db", "SQLite-DB"))}</th>
                <th class="p-2 font-semibold">${esc(_tenT("ui.tenant_switcher.col_mode", "Modus"))}</th>
                <th class="p-2 font-semibold">${esc(_tenT("ui.tenant_switcher.col_size", "Größe"))}</th>
                <th class="p-2 font-semibold">${esc(_tenT("ui.tenant_switcher.col_path", "Aktiver Pfad"))}</th>
              </tr>
            </thead>
            <tbody>
              ${Object.entries(dbs)
                .map(
                  ([k, v]) => `
                <tr class="border-b theme-border">
                  <td class="p-2 font-mono font-semibold">${esc(k)}</td>
                  <td class="p-2"><span class="px-1.5 py-0.5 rounded border theme-border font-mono text-[10px]">${esc(v.mode)}</span></td>
                  <td class="p-2 font-mono">${((v.size_bytes || 0) / 1024).toFixed(1)} KB</td>
                  <td class="p-2 font-mono text-[10px] opacity-75 break-all">${esc(v.active_path || v.path)}</td>
                </tr>`
                )
                .join("")}
            </tbody>
          </table>
        </div>

        <div class="overflow-x-auto rounded-lg border theme-border">
          <table class="w-full text-left border-collapse">
            <thead>
              <tr class="border-b theme-border bg-black/5 dark:bg-white/5 text-[11px]">
                <th class="p-2 font-semibold">${esc(_tenT("ui.tenant_switcher.col_doc_type", "Belegtyp"))}</th>
                <th class="p-2 font-semibold">${esc(_tenT("ui.tenant_switcher.col_prefix", "Präfix"))}</th>
                <th class="p-2 font-semibold">${esc(_tenT("ui.tenant_switcher.col_next_seq", "Nächste Nr."))}</th>
              </tr>
            </thead>
            <tbody>
              ${Object.entries(ranges)
                .map(
                  ([dt, r]) => `
                <tr class="border-b theme-border">
                  <td class="p-2 font-mono">${esc(dt)}</td>
                  <td class="p-2 font-mono">${esc(r.prefix)}</td>
                  <td class="p-2 font-mono font-semibold">${esc(r.next_seq)}</td>
                </tr>`
                )
                .join("")}
            </tbody>
          </table>
        </div>

        <div class="p-3 rounded-lg border theme-border space-y-2">
          <div class="font-semibold">${esc(_tenT("ui.tenant_switcher.create_title", "Neue Gesellschaft anlegen (provisioniert sofort 5 isolierte SQLite-DBs + eigene Nummernkreise)"))}</div>
          <div class="grid grid-cols-1 sm:grid-cols-4 gap-2">
            <input id="m43-new-name" class="p-1.5 rounded border theme-border bg-transparent" placeholder="${esc(_tenT("ui.tenant_switcher.ph_name", "z. B. Keller Holding GmbH"))}" />
            <select id="m43-new-type" class="p-1.5 rounded border theme-border bg-transparent">
              <option value="holding">${esc(_tenT("ui.tenant_switcher.type_holding", "Holding"))}</option>
              <option value="operative_gmbh" selected>${esc(_tenT("ui.tenant_switcher.type_operative", "Operative GmbH"))}</option>
              <option value="spv">${esc(_tenT("ui.tenant_switcher.type_spv", "Projekt- / Immobilien-SPV"))}</option>
            </select>
            <input id="m43-new-vat" class="p-1.5 rounded border theme-border bg-transparent" placeholder="${esc(_tenT("ui.tenant_switcher.ph_vat", "USt-IdNr. (optional)"))}" />
            <button id="m43-create-btn" type="button" class="px-3 py-1.5 rounded bg-amber-600 text-white font-semibold hover:bg-amber-500">${esc(_tenT("ui.tenant_switcher.create_btn", "+ Mandant anlegen"))}</button>
          </div>
        </div>
      </div>`;

    modal.classList.remove("hidden");
    modal.classList.add("flex");

    modal.querySelector("#m43-close-btn").onclick = () => {
      modal.classList.add("hidden");
      modal.classList.remove("flex");
    };

    modal.querySelector("#m43-create-btn").onclick = async () => {
      const name = document.getElementById("m43-new-name").value.trim();
      const entity_type = document.getElementById("m43-new-type").value;
      const vat_id = document.getElementById("m43-new-vat").value.trim();
      if (!name) return;
      const res = await fetch("/api/v1/tenants/companies", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          entity_type,
          tax: { vat_id },
          activate: true,
        }),
      });
      if (res.ok) {
        await renderTenantSwitcher();
        reloadActiveModuleViews();
        await openTenantIsolationModal();
      }
    };
  }

  window.openTenantIsolationModal = openTenantIsolationModal;

  async function renderTenantSwitcher() {
    const anchor =
      document.getElementById("topbar-user-badge") ||
      document.getElementById("topbar-custom-content");
    if (!anchor) return false;

    const ctx = await fetchTenantContext();
    if (!ctx || !Array.isArray(ctx.companies)) return false;

    let wrap = document.getElementById(CONTAINER_ID);
    if (!wrap) {
      wrap = document.createElement("div");
      wrap.id = CONTAINER_ID;
      wrap.className = "flex items-center justify-between gap-1 px-1 py-0.5 rounded hover:bg-[var(--secondary)]/60 transition text-[11px]";
      anchor.parentNode.insertBefore(wrap, anchor);
    }

    const activeId = ctx.active_company && ctx.active_company.id;
    const activeCompany = ctx.companies.find((c) => c.id === activeId);
    const options = ctx.companies
      .map((c) => {
        const label = c.name || c.id;
        const sel = c.id === activeId ? "selected" : "";
        return `<option value="${esc(c.id)}" ${sel}>${esc(label)}</option>`;
      })
      .join("");
    const selectTitle = activeCompany && activeCompany.entity_type
      ? `${activeCompany.name || activeCompany.id} (${activeCompany.entity_type}) — ${_tenT("ui.tenant_switcher.select_title", "Mandant wechseln")}`
      : _tenT("ui.tenant_switcher.select_title", "Mandant wechseln (Holding / GmbH / SPV)");

    wrap.innerHTML = `
      <span class="flex items-center gap-1.5 min-w-0 flex-1">
        <span class="shrink-0">${BADGE_SVG}</span>
        <select id="archon-tenant-select" class="bg-transparent text-[11px] font-medium text-[var(--foreground)] outline-none cursor-pointer min-w-0 flex-1 truncate" title="${esc(selectTitle)}">${options}</select>
      </span>
      <button id="archon-tenant-manage-btn" type="button" class="opacity-50 hover:opacity-100 p-0.5 cursor-pointer shrink-0 transition" aria-label="${esc(_tenT("ui.tenant_switcher.manage_title", "Mandanten-DB-Isolation & Nummernkreise anzeigen"))}" title="${esc(_tenT("ui.tenant_switcher.manage_title", "Mandanten-DB-Isolation & Nummernkreise anzeigen"))}">${GEAR_SVG}</button>`;

    const selEl = document.getElementById("archon-tenant-select");
    if (selEl) {
      selEl.addEventListener("change", (e) => {
        if (e.target && e.target.value) {
          switchTenant(e.target.value);
        }
      });
    }
    const manageBtn = document.getElementById("archon-tenant-manage-btn");
    if (manageBtn) {
      manageBtn.onclick = openTenantIsolationModal;
    }
    return true;
  }

  function mountSwitcherWithObserver() {
    renderTenantSwitcher().then((ok) => {
      if (ok) return;
      let retries = 0;
      const maxRetries = 10;
      let obs = null;
      const rootTarget = document.getElementById("main-topbar") || document.body;
      if (rootTarget && typeof MutationObserver !== "undefined") {
        obs = new MutationObserver(() => {
          if (document.getElementById("topbar-user-badge") || document.getElementById("topbar-custom-content")) {
            if (obs) obs.disconnect();
            renderTenantSwitcher();
          }
        });
        obs.observe(rootTarget, { childList: true, subtree: true });
      }
      const tick = async () => {
        if (await renderTenantSwitcher()) {
          if (obs) obs.disconnect();
          return;
        }
        if (++retries >= maxRetries) {
          if (obs) obs.disconnect();
          return;
        }
        setTimeout(tick, 300);
      };
      setTimeout(tick, 300);
    });
  }

  window.addEventListener("archon:language-changed", () => {
    renderTenantSwitcher();
    const modal = document.getElementById(MODAL_ID);
    if (modal && !modal.classList.contains("hidden")) {
      openTenantIsolationModal();
    }
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mountSwitcherWithObserver);
  } else {
    mountSwitcherWithObserver();
  }
})();
