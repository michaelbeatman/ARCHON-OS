/**
 * static/js/eu_ai_act_studio.js
 * M49 — EU AI Act Compliance-Center & 1-Klick GoBD-/EU-AI-Act-Verfahrensdokumentation (PDF).
 * Eigene SVG-Icons in Markenfarben (Rot/Orange/Gelb), lesbare Tabellen, kein Emoji-Einsatz.
 */
(function () {
  "use strict";

  const MODAL_ID = "archon-eu-ai-act-modal";
  let activeTab = "inventory";
  let currentRiskFilter = "ALL";
  let cachedInventory = [];

  const SHIELD_SVG = `
    <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
      <path d="m9 12 2 2 4-4" stroke="#ef4444" stroke-width="2.1"/>
    </svg>`;

  function esc(val) {
    return String(val == null ? "" : val)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  async function api(url, opts) {
    const res = await fetch(url, opts);
    if (!res.ok) {
      const txt = await res.text();
      throw new Error(txt || `HTTP ${res.status}`);
    }
    return await res.json();
  }

  function ensureModal() {
    let modal = document.getElementById(MODAL_ID);
    if (modal) return modal;

    modal = document.createElement("div");
    modal.id = MODAL_ID;
    modal.className = "fixed inset-0 z-50 hidden items-center justify-center bg-black/70 backdrop-blur-sm p-4";
    modal.innerHTML = `
      <div class="w-full max-w-5xl rounded-2xl border theme-border bg-white dark:bg-zinc-900 p-5 shadow-2xl max-h-[90vh] flex flex-col gap-3.5 text-xs">
        <div class="flex items-center justify-between border-b theme-border pb-3">
          <div class="flex items-center gap-2.5">
            <div class="p-1.5 rounded-lg border border-amber-500/30 bg-amber-500/10">${SHIELD_SVG}</div>
            <div>
              <h2 class="text-sm font-bold tracking-wide">EU AI Act Compliance-Engine &amp; GoBD-Verfahrensdokumentation (M49)</h2>
              <p class="text-[11px] opacity-70">Verordnung (EU) 2024/1689 (Art. 4, 6, Anhang III, Art. 50) &middot; GoBD Rz. 151 ff. &middot; SHA-256 Merkle-Beweis</p>
            </div>
          </div>
          <div class="flex items-center gap-2">
            <a id="m49-quick-pdf-btn" href="/api/v1/governance/compliance/verfahrensdokumentation.pdf" target="_blank"
               class="px-3 py-1.5 rounded-lg bg-gradient-to-r from-red-600 to-amber-500 text-white font-semibold shadow hover:opacity-95 transition">
              GoBD + EU AI Act PDF herunterladen
            </a>
            <button id="m49-close-btn" type="button" class="px-2.5 py-1.5 rounded-lg border theme-border hover:opacity-80">Schließen</button>
          </div>
        </div>

        <div class="flex flex-wrap gap-2 border-b theme-border pb-2">
          <button type="button" data-m49tab="inventory" class="m49-tab-btn px-3 py-1.5 rounded-lg border theme-border font-semibold">1. KI-Risikoregister &amp; SOUL-Hashes</button>
          <button type="button" data-m49tab="literacy" class="m49-tab-btn px-3 py-1.5 rounded-lg border theme-border">2. Art. 4 KI-Kompetenznachweis</button>
          <button type="button" data-m49tab="pdf" class="m49-tab-btn px-3 py-1.5 rounded-lg border theme-border">3. Verfahrensdokumentation &amp; GoBD-Prüfung</button>
        </div>

        <div id="m49-body" class="overflow-y-auto flex-1 pr-1 space-y-3"></div>
      </div>`;
    document.body.appendChild(modal);

    modal.querySelector("#m49-close-btn").onclick = () => {
      modal.classList.add("hidden");
      modal.classList.remove("flex");
    };

    modal.querySelectorAll(".m49-tab-btn").forEach((btn) => {
      btn.onclick = () => {
        activeTab = btn.dataset.m49tab;
        renderActiveTab();
      };
    });

    return modal;
  }

  function tierBadge(tier) {
    if (tier === "HIGH_RISK") {
      return `<span class="px-2 py-0.5 rounded bg-red-500/15 text-red-500 border border-red-500/30 font-mono font-semibold text-[10px]">HIGH RISK (Anh. III)</span>`;
    }
    if (tier === "SPECIFIC_TRANSPARENCY") {
      return `<span class="px-2 py-0.5 rounded bg-amber-500/15 text-amber-500 border border-amber-500/30 font-mono font-semibold text-[10px]">TRANSPARENZ (Art. 50)</span>`;
    }
    return `<span class="px-2 py-0.5 rounded bg-emerald-500/15 text-emerald-500 border border-emerald-500/30 font-mono font-semibold text-[10px]">MINIMAL (Art. 95)</span>`;
  }

  async function renderInventoryTab(container) {
    const [invRes, statsRes, guardRes] = await Promise.all([
      api("/api/v1/governance/ai-act/inventory"),
      api("/api/v1/governance/ai-act/stats"),
      api("/api/v1/governance/ai-act/guardrails"),
    ]);
    cachedInventory = invRes.inventory || [];
    const st = statsRes.stats || {};
    const gd = guardRes.guardrails || {};

    const filtered = cachedInventory.filter((item) =>
      currentRiskFilter === "ALL" ? true : item.risk_tier === currentRiskFilter
    );

    container.innerHTML = `
      <div class="grid grid-cols-2 sm:grid-cols-5 gap-2">
        <div class="p-2.5 rounded-lg border theme-border">
          <div class="opacity-65 text-[10px] uppercase">Spezialisten gesamt</div>
          <div class="text-base font-bold font-mono">${esc(st.total_agents || 0)}</div>
        </div>
        <div class="p-2.5 rounded-lg border border-red-500/30 bg-red-500/5">
          <div class="text-red-400 text-[10px] uppercase">Anhang III High-Risk</div>
          <div class="text-base font-bold font-mono text-red-500">${esc(st.high_risk_count || 0)}</div>
        </div>
        <div class="p-2.5 rounded-lg border border-amber-500/30 bg-amber-500/5">
          <div class="text-amber-400 text-[10px] uppercase">Art. 50 Transparenz</div>
          <div class="text-base font-bold font-mono text-amber-500">${esc(st.transparency_risk_count || 0)}</div>
        </div>
        <div class="p-2.5 rounded-lg border theme-border">
          <div class="opacity-65 text-[10px] uppercase">SOUL-SHA256 gepinnt</div>
          <div class="text-base font-bold font-mono">${esc(st.soul_hashes_pinned || 0)}</div>
        </div>
        <div class="p-2.5 rounded-lg border ${gd.all_guardrails_passed ? "border-emerald-500/30 bg-emerald-500/5" : "border-amber-500/30"}">
          <div class="opacity-65 text-[10px] uppercase">Pflicht-Guardrails</div>
          <div class="text-xs font-bold font-mono ${gd.all_guardrails_passed ? "text-emerald-500" : "text-amber-500"}">
            ${gd.all_guardrails_passed ? "VERIFIZIERT" : `${(gd.violations || []).length} Hinweise`}
          </div>
        </div>
      </div>

      <div class="flex flex-wrap items-center gap-1.5">
        <span class="opacity-70 mr-1">Filter:</span>
        <button type="button" data-rfilter="ALL" class="m49-rfilter px-2.5 py-1 rounded border theme-border ${currentRiskFilter === "ALL" ? "font-bold border-amber-500" : ""}">Alle (${cachedInventory.length})</button>
        <button type="button" data-rfilter="HIGH_RISK" class="m49-rfilter px-2.5 py-1 rounded border theme-border ${currentRiskFilter === "HIGH_RISK" ? "font-bold border-red-500" : ""}">Anhang III High-Risk</button>
        <button type="button" data-rfilter="SPECIFIC_TRANSPARENCY" class="m49-rfilter px-2.5 py-1 rounded border theme-border ${currentRiskFilter === "SPECIFIC_TRANSPARENCY" ? "font-bold border-amber-500" : ""}">Art. 50 Transparenz</button>
        <button type="button" data-rfilter="MINIMAL_RISK" class="m49-rfilter px-2.5 py-1 rounded border theme-border ${currentRiskFilter === "MINIMAL_RISK" ? "font-bold border-emerald-500" : ""}">Art. 95 Minimal</button>
      </div>

      <div class="overflow-x-auto rounded-lg border theme-border">
        <table class="w-full text-left border-collapse">
          <thead>
            <tr class="border-b theme-border bg-black/5 dark:bg-white/5 text-[11px]">
              <th class="p-2 font-semibold">Spezialist</th>
              <th class="p-2 font-semibold">Domäne</th>
              <th class="p-2 font-semibold">Risikoklasse</th>
              <th class="p-2 font-semibold">Aufsichts-Gate</th>
              <th class="p-2 font-semibold">SOUL-SHA256</th>
            </tr>
          </thead>
          <tbody>
            ${filtered
              .map(
                (it) => `
              <tr class="border-b theme-border hover:bg-black/5 dark:hover:bg-white/5">
                <td class="p-2">
                  <div class="font-semibold">${esc(it.agent_name)}</div>
                  <div class="font-mono text-[10px] opacity-65">${esc(it.agent_id)}</div>
                </td>
                <td class="p-2 opacity-80">${esc(it.category)}</td>
                <td class="p-2">${tierBadge(it.risk_tier)}</td>
                <td class="p-2 text-[11px]">${esc(String(it.human_oversight_measure || "").split("(")[0])}</td>
                <td class="p-2 font-mono text-[10px] opacity-80">${esc(String(it.soul_sha256 || "").slice(0, 14))}</td>
              </tr>`
              )
              .join("")}
          </tbody>
        </table>
      </div>`;

    container.querySelectorAll(".m49-rfilter").forEach((b) => {
      b.onclick = () => {
        currentRiskFilter = b.dataset.rfilter;
        renderInventoryTab(container);
      };
    });
  }

  async function renderLiteracyTab(container) {
    const data = await api("/api/v1/governance/ai-act/literacy-register");
    const entries = data.entries || [];

    container.innerHTML = `
      <div class="p-3 rounded-lg border theme-border space-y-2">
        <div class="font-semibold">Neuen KI-Kompetenznachweis nach Art. 4 EU AI Act protokollieren (revisionssicher via GoBD-Hashkette)</div>
        <div class="grid grid-cols-1 sm:grid-cols-4 gap-2">
          <input id="m49-lit-person" class="p-1.5 rounded border theme-border bg-transparent" placeholder="Name / Funktionsträger" />
          <input id="m49-lit-role" class="p-1.5 rounded border theme-border bg-transparent" placeholder="Rolle (z. B. GF / Operator)" />
          <input id="m49-lit-module" class="p-1.5 rounded border theme-border bg-transparent" placeholder="Schulungs-/Einweisungsmodul" value="Art. 4 EU AI Act & HITL-Freigabe" />
          <button id="m49-lit-add" type="button" class="px-3 py-1.5 rounded bg-amber-600 text-white font-semibold hover:bg-amber-500">Nachweis eintragen</button>
        </div>
      </div>

      <div class="overflow-x-auto rounded-lg border theme-border">
        <table class="w-full text-left border-collapse">
          <thead>
            <tr class="border-b theme-border bg-black/5 dark:bg-white/5 text-[11px]">
              <th class="p-2 font-semibold">Person / Funktion</th>
              <th class="p-2 font-semibold">Rolle</th>
              <th class="p-2 font-semibold">Kompetenzmodul</th>
              <th class="p-2 font-semibold">Gültig bis</th>
              <th class="p-2 font-semibold">Zertifikats-SHA256</th>
              <th class="p-2 font-semibold">Aktion</th>
            </tr>
          </thead>
          <tbody>
            ${entries
              .map(
                (e) => `
              <tr class="border-b theme-border">
                <td class="p-2 font-semibold">${esc(e.person_name)}</td>
                <td class="p-2">${esc(e.role)}</td>
                <td class="p-2">${esc(e.training_module)}</td>
                <td class="p-2 font-mono">${esc(e.valid_until)}</td>
                <td class="p-2 font-mono text-[10px]">${esc(String(e.certificate_sha256 || "").slice(0, 14))}</td>
                <td class="p-2">
                  <button type="button" data-litdel="${esc(e.id)}" class="px-2 py-0.5 rounded border theme-border text-[10px] hover:border-red-500">Entfernen</button>
                </td>
              </tr>`
              )
              .join("")}
          </tbody>
        </table>
      </div>`;

    container.querySelector("#m49-lit-add").onclick = async () => {
      const person_name = document.getElementById("m49-lit-person").value.trim();
      const role = document.getElementById("m49-lit-role").value.trim() || "Operator";
      const training_module = document.getElementById("m49-lit-module").value.trim();
      if (!person_name) return;
      await api("/api/v1/governance/ai-act/literacy-register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ person_name, role, training_module }),
      });
      renderLiteracyTab(container);
    };

    container.querySelectorAll("[data-litdel]").forEach((btn) => {
      btn.onclick = async () => {
        await api(`/api/v1/governance/ai-act/literacy-register/${encodeURIComponent(btn.dataset.litdel)}`, {
          method: "DELETE",
        });
        renderLiteracyTab(container);
      };
    });
  }

  async function renderPdfTab(container) {
    const res = await api("/api/v1/governance/compliance/snapshot");
    const snap = res.snapshot || {};
    const comp = snap.company || {};
    const audit = snap.audit_chain || {};
    const dbs = (snap.db_isolation && snap.db_isolation.databases) || {};

    container.innerHTML = `
      <div class="p-3.5 rounded-xl border border-amber-500/30 bg-amber-500/5 flex flex-wrap items-center justify-between gap-3">
        <div>
          <div class="text-sm font-bold">Prüferfertige Verfahrensdokumentation (GoBD Rz. 151 ff. + EU AI Act)</div>
          <div class="opacity-75 mt-0.5">Aktiver Mandant: <strong>${esc(comp.name || snap.tenant_id)}</strong> &middot; Dokument-ID: <span class="font-mono">${esc(snap.document_id)}</span></div>
        </div>
        <a href="/api/v1/governance/compliance/verfahrensdokumentation.pdf?company_id=${encodeURIComponent(snap.tenant_id || "")}"
           target="_blank"
           class="px-4 py-2 rounded-lg bg-gradient-to-r from-red-600 to-amber-500 text-white font-bold shadow">
          1-Klick PDF-Export starten
        </a>
      </div>

      <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div class="p-3 rounded-lg border theme-border space-y-1.5">
          <div class="font-bold uppercase text-[10px] opacity-70">GoBD Merkle-Hashkette (M21)</div>
          <div>Status: <strong class="${audit.valid ? "text-emerald-500" : "text-red-500"}">${audit.valid ? "MATHEMATISCH UNVERSEHRT" : "PRÜFUNG ERFORDERLICH"}</strong></div>
          <div>Geprüfte Blöcke: <span class="font-mono">${esc(audit.checked_blocks ?? audit.total_entries ?? 0)}</span></div>
          <div class="font-mono text-[10px] break-all opacity-75">Head-Hash: ${esc(audit.head_hash || "")}</div>
        </div>
        <div class="p-3 rounded-lg border theme-border space-y-1.5">
          <div class="font-bold uppercase text-[10px] opacity-70">Physische Mandanten-DB-Isolation (M43)</div>
          <table class="w-full text-left text-[11px]">
            <tbody>
              ${Object.entries(dbs)
                .map(
                  ([k, v]) => `
                <tr class="border-b theme-border">
                  <td class="py-1 font-mono font-semibold">${esc(k)}</td>
                  <td class="py-1">${esc(v.mode)}</td>
                  <td class="py-1 font-mono text-right">${((v.size_bytes || 0) / 1024).toFixed(1)} KB</td>
                </tr>`
                )
                .join("")}
            </tbody>
          </table>
        </div>
      </div>`;
  }

  async function renderActiveTab() {
    const modal = ensureModal();
    modal.querySelectorAll(".m49-tab-btn").forEach((b) => {
      const sel = b.dataset.m49tab === activeTab;
      b.classList.toggle("border-amber-500", sel);
      b.classList.toggle("bg-amber-500/10", sel);
    });
    const body = document.getElementById("m49-body");
    if (!body) return;
    body.innerHTML = `<div class="p-4 opacity-60">Lade Live-Compliance-Daten...</div>`;
    try {
      if (activeTab === "inventory") await renderInventoryTab(body);
      else if (activeTab === "literacy") await renderLiteracyTab(body);
      else await renderPdfTab(body);
    } catch (err) {
      body.innerHTML = `<div class="p-3 rounded border border-red-500/40 text-red-400">Fehler: ${esc(err.message)}</div>`;
    }
  }

  window.openComplianceStudio = function (initialTab) {
    if (initialTab) activeTab = initialTab;
    const modal = ensureModal();
    modal.classList.remove("hidden");
    modal.classList.add("flex");
    renderActiveTab();
  };

  function injectComplianceTile() {
    if (document.getElementById("ops-subtab-compliance")) return;
    const anchor =
      document.getElementById("ops-subtab-calendar") ||
      document.getElementById("ops-subtab-playbooks") ||
      document.getElementById("ops-subtab-org") ||
      document.getElementById("ops-subtab-kanban");
    if (!anchor || !anchor.parentNode) return;

    const btn = document.createElement("button");
    btn.type = "button";
    btn.id = "ops-subtab-compliance";
    btn.title = "EU AI Act & GoBD Verfahrensdokumentation (M49)";
    btn.className =
      "ops-header-tile flex flex-col items-center justify-between min-w-[56px] sm:min-w-[66px] h-[72px] py-1 px-0.5 bg-transparent border-0 shadow-none opacity-85 hover:opacity-100 cursor-pointer select-none transition-transform hover:scale-105 duration-150";
    btn.innerHTML = `
      <div class="tile-icon-wrap w-11 h-11 sm:w-12 sm:h-12 flex items-center justify-center mb-0.5 relative">
        ${SHIELD_SVG}
      </div>
      <span class="ops-tab-label text-[10px] font-mono tracking-tight text-center whitespace-nowrap text-[var(--foreground)] font-medium leading-none">AI Act / GoBD</span>`;
    btn.onclick = () => window.openComplianceStudio("inventory");
    anchor.parentNode.insertBefore(btn, anchor.nextSibling);
  }

  window.addEventListener("archon:tenant-switched", () => {
    const modal = document.getElementById(MODAL_ID);
    if (modal && !modal.classList.contains("hidden")) {
      renderActiveTab();
    }
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", injectComplianceTile);
  } else {
    injectComplianceTile();
  }
})();
