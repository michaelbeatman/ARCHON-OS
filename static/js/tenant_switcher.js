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
            <h3 class="text-sm font-bold">Multi-Mandanten-DB-Isolation &amp; Nummernkreise (M43)</h3>
            <p class="text-[11px] opacity-70">Aktive Gesellschaft: <strong>${esc(active.name || ctx.active_tenant_id)}</strong> (${esc(active.entity_type || "operative_gmbh")})</p>
          </div>
          <button id="m43-close-btn" type="button" class="px-2.5 py-1 rounded border theme-border">Schließen</button>
        </div>

        <div class="overflow-x-auto rounded-lg border theme-border">
          <table class="w-full text-left border-collapse">
            <thead>
              <tr class="border-b theme-border bg-black/5 dark:bg-white/5 text-[11px]">
                <th class="p-2 font-semibold">SQLite-DB</th>
                <th class="p-2 font-semibold">Modus</th>
                <th class="p-2 font-semibold">Größe</th>
                <th class="p-2 font-semibold">Aktiver Pfad</th>
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
                <th class="p-2 font-semibold">Belegtyp</th>
                <th class="p-2 font-semibold">Präfix</th>
                <th class="p-2 font-semibold">Nächste Nr.</th>
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
          <div class="font-semibold">Neue Gesellschaft anlegen (provisioniert sofort 5 isolierte SQLite-DBs + eigene Nummernkreise)</div>
          <div class="grid grid-cols-1 sm:grid-cols-4 gap-2">
            <input id="m43-new-name" class="p-1.5 rounded border theme-border bg-transparent" placeholder="z. B. Keller Holding GmbH" />
            <select id="m43-new-type" class="p-1.5 rounded border theme-border bg-transparent">
              <option value="holding">Holding</option>
              <option value="operative_gmbh" selected>Operative GmbH</option>
              <option value="spv">Projekt- / Immobilien-SPV</option>
            </select>
            <input id="m43-new-vat" class="p-1.5 rounded border theme-border bg-transparent" placeholder="USt-IdNr. (optional)" />
            <button id="m43-create-btn" type="button" class="px-3 py-1.5 rounded bg-amber-600 text-white font-semibold hover:bg-amber-500">+ Mandant anlegen</button>
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
    if (!anchor) return;

    const ctx = await fetchTenantContext();
    if (!ctx || !Array.isArray(ctx.companies)) return;

    let wrap = document.getElementById(CONTAINER_ID);
    if (!wrap) {
      wrap = document.createElement("div");
      wrap.id = CONTAINER_ID;
      wrap.className = "flex items-center gap-1 px-1.5 py-0.5 rounded border theme-border text-[11px] mb-1";
      anchor.parentNode.insertBefore(wrap, anchor);
    }

    const activeId = ctx.active_company && ctx.active_company.id;
    const options = ctx.companies
      .map((c) => {
        const label = c.entity_type ? `${c.name} (${c.entity_type})` : c.name || c.id;
        const sel = c.id === activeId ? "selected" : "";
        return `<option value="${esc(c.id)}" ${sel}>${esc(label)}</option>`;
      })
      .join("");

    wrap.innerHTML = `
      ${BADGE_SVG}
      <select id="archon-tenant-select" class="bg-transparent text-xs font-medium outline-none cursor-pointer" title="Mandant wechseln (Holding / GmbH / SPV)">${options}</select>
      <button id="archon-tenant-manage-btn" type="button" class="opacity-70 hover:opacity-100 p-0.5 cursor-pointer" title="Mandanten-DB-Isolation &amp; Nummernkreise anzeigen">${GEAR_SVG}</button>`;

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
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", renderTenantSwitcher);
  } else {
    renderTenantSwitcher();
  }
})();
