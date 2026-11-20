/**
 * static/js/playbooks_studio.js
 * M44 — Business Playbooks (Operations-Vorlagen, n8n-Katalog & Editor)
 */
(function () {
  "use strict";

  const MODAL_ID = "archon-playbooks-modal";
  let currentTab = "active";

  function _pbT(key, fallback) {
    if (window.archonI18n && typeof window.archonI18n.t === "function") {
      return window.archonI18n.t(key, fallback);
    }
    return fallback;
  }

  function _escPb(str) {
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
    const titleEl = modal.querySelector("#pb-modal-title");
    if (titleEl) titleEl.textContent = _pbT("ui.playbooks_studio.modal_title", "Operations Vorlagen & Playbooks");
    const closeBtn = modal.querySelector("#pb-close-btn");
    if (closeBtn) closeBtn.textContent = _pbT("ui.playbooks_studio.close_btn", "Schließen");
    const tabMap = {
      active: ["ui.playbooks_studio.tab_active", "Aktive Vorlagen (10+)"],
      catalog: ["ui.playbooks_studio.tab_catalog", "Katalog (Nachladen)"],
      editor: ["ui.playbooks_studio.tab_editor", "+ Neue Vorlage (Editor)"],
    };
    modal.querySelectorAll(".pb-tab").forEach((btn) => {
      const spec = tabMap[btn.dataset.pbtab];
      if (spec) btn.textContent = _pbT(spec[0], spec[1]);
    });
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
      <div class="w-full max-w-4xl rounded-xl border theme-border bg-white dark:bg-zinc-900 p-5 shadow-2xl max-h-[88vh] flex flex-col gap-3">
        <div class="flex items-center justify-between border-b theme-border pb-2">
          <h2 id="pb-modal-title" class="text-base font-bold"></h2>
          <button id="pb-close-btn" class="px-2 py-1 text-xs rounded border theme-border"></button>
        </div>
        <div class="flex gap-2">
          <button data-pbtab="active" class="pb-tab px-3 py-1.5 rounded text-xs font-semibold border theme-border"></button>
          <button data-pbtab="catalog" class="pb-tab px-3 py-1.5 rounded text-xs font-semibold border theme-border"></button>
          <button data-pbtab="editor" class="pb-tab px-3 py-1.5 rounded text-xs font-semibold border theme-border"></button>
        </div>
        <div id="pb-body" class="overflow-y-auto flex-1 space-y-2 text-xs"></div>
      </div>`;
    document.body.appendChild(modal);
    applyModalTranslations(modal);
    modal.querySelector("#pb-close-btn").onclick = () => {
      modal.classList.add("hidden");
      modal.classList.remove("flex");
    };
    modal.querySelectorAll(".pb-tab").forEach((btn) => {
      btn.onclick = () => {
        currentTab = btn.dataset.pbtab;
        renderTab();
      };
    });
    return modal;
  }

  async function renderTab() {
    const body = document.getElementById("pb-body");
    if (!body) return;

    if (currentTab === "editor") {
      body.innerHTML = `
        <div class="space-y-2 p-2 border theme-border rounded">
          <input id="pb-ed-title" class="w-full p-2 rounded border theme-border bg-transparent" placeholder="${_escPb(_pbT("ui.playbooks_studio.ph_title", "Titel der Vorlage (z. B. Quartals-Review)"))}" />
          <input id="pb-ed-cat" class="w-full p-2 rounded border theme-border bg-transparent" value="${_escPb(_pbT("ui.playbooks_studio.default_category", "Operations & Führung"))}" placeholder="${_escPb(_pbT("ui.playbooks_studio.ph_category", "Kategorie"))}" />
          <input id="pb-ed-vars" class="w-full p-2 rounded border theme-border bg-transparent" placeholder="${_escPb(_pbT("ui.playbooks_studio.ph_vars", "Variablen kommagetrennt (z. B. kunde, quartal)"))}" />
          <textarea id="pb-ed-prompt" rows="3" class="w-full p-2 rounded border theme-border bg-transparent" placeholder="${_escPb(_pbT("ui.playbooks_studio.ph_prompt", "Schritt 1 Prompt ({{kunde}} ...)"))}" ></textarea>
          <button id="pb-ed-save" class="px-3 py-1.5 rounded bg-indigo-600 text-white font-semibold">${_escPb(_pbT("ui.playbooks_studio.save_btn", "Vorlage speichern"))}</button>
        </div>`;
      body.querySelector("#pb-ed-save").onclick = async () => {
        const title = document.getElementById("pb-ed-title").value.trim();
        const category = document.getElementById("pb-ed-cat").value.trim();
        const variables = document.getElementById("pb-ed-vars").value.split(",").map((s) => s.trim()).filter(Boolean);
        const prompt_template = document.getElementById("pb-ed-prompt").value.trim();
        const res = await api("/api/v1/playbooks", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            title,
            category,
            variables,
            steps: [{ order: 1, title: _pbT("ui.playbooks_studio.step1_title", "Schritt 1"), agent_id: "executive_decision_architect", prompt_template }],
          }),
        });
        if (res.status === "success") {
          currentTab = "active";
          renderTab();
        }
      };
      return;
    }

    const activeOnly = currentTab === "active";
    const data = await api(`/api/v1/playbooks?active_only=${activeOnly}`);
    const list = data.playbooks || [];
    const runLabel = _escPb(_pbT("ui.playbooks_studio.run_btn", "Ausführen"));
    const activateLabel = _escPb(_pbT("ui.playbooks_studio.activate_btn", "Aktivieren"));
    const hideLabel = _escPb(_pbT("ui.playbooks_studio.hide_btn", "Ausblenden"));
    body.innerHTML = list
      .map(
        (pb) => `
      <div class="p-3 rounded border theme-border flex items-center justify-between gap-3">
        <div>
          <div class="font-semibold">${_escPb(pb.title)} <span class="opacity-60">[${_escPb(pb.category)}]</span></div>
          <div class="opacity-75">${_escPb(pb.description || "")}</div>
        </div>
        <div class="flex gap-1.5 shrink-0">
          ${
            activeOnly
              ? `<button data-run="${_escPb(pb.id)}" data-title="${_escPb(pb.title)}" class="px-2.5 py-1 rounded bg-emerald-600 text-white font-semibold">${runLabel}</button>`
              : `<button data-toggle="${_escPb(pb.id)}" data-next="true" class="px-2.5 py-1 rounded bg-indigo-600 text-white font-semibold">${activateLabel}</button>`
          }
          ${
            activeOnly
              ? `<button data-toggle="${_escPb(pb.id)}" data-next="false" class="px-2 py-1 rounded border theme-border">${hideLabel}</button>`
              : ""
          }
        </div>
      </div>`
      )
      .join("");

    body.querySelectorAll("[data-toggle]").forEach((b) => {
      b.onclick = async () => {
        await api(`/api/v1/playbooks/${encodeURIComponent(b.dataset.toggle)}/toggle`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ active: b.dataset.next === "true" }),
        });
        renderTab();
      };
    });
    body.querySelectorAll("[data-run]").forEach((b) => {
      b.onclick = async () => {
        const msg = _pbT("ui.playbooks_studio.confirm_run", "Playbook '{name}' jetzt mit Standardvariablen ausführen?")
          .replace("{name}", b.dataset.title || b.dataset.run);
        if (!confirm(msg)) return;
        const res = await api(`/api/v1/playbooks/${encodeURIComponent(b.dataset.run)}/run`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ variables: {} }),
        });
        if (res.status === "success") {
          b.textContent = _pbT("ui.playbooks_studio.started_label", "Gestartet");
        }
      };
    });
  }

  window.openPlaybooksStudio = function () {
    const m = ensureModal();
    m.classList.remove("hidden");
    m.classList.add("flex");
    renderTab();
  };

  function updateTileLabel() {
    const btn = document.getElementById("ops-subtab-playbooks");
    if (!btn) return;
    btn.title = _pbT("ui.playbooks_studio.tile_title", "Business Playbooks & Workflow-Vorlagen (M44)");
    const lbl = btn.querySelector(".ops-tab-label");
    if (lbl) lbl.textContent = _pbT("ui.playbooks_studio.tile_label", "Vorlagen");
  }

  function injectOperationsTile() {
    if (document.getElementById("ops-subtab-playbooks")) {
      updateTileLabel();
      return true;
    }
    const anchor =
      document.getElementById("ops-subtab-org") ||
      document.getElementById("ops-subtab-kanban");
    if (!anchor || !anchor.parentNode) return false;

    const btn = document.createElement("button");
    btn.type = "button";
    btn.id = "ops-subtab-playbooks";
    btn.title = _pbT("ui.playbooks_studio.tile_title", "Business Playbooks & Workflow-Vorlagen (M44)");
    btn.className =
      "ops-header-tile flex flex-col items-center justify-between min-w-[56px] sm:min-w-[62px] h-[72px] py-1 px-0.5 bg-transparent border-0 shadow-none opacity-80 hover:opacity-100 cursor-pointer select-none transition-transform hover:scale-105 duration-150";
    btn.innerHTML = `
      <div class="tile-icon-wrap w-11 h-11 sm:w-12 sm:h-12 flex items-center justify-center mb-0.5 relative">
        <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <rect x="3" y="3" width="7" height="7" rx="1.5"/>
          <rect x="14" y="3" width="7" height="7" rx="1.5"/>
          <rect x="14" y="14" width="7" height="7" rx="1.5"/>
          <path d="M6.5 10v4a3 3 0 0 0 3 3H14"/>
        </svg>
      </div>
      <span class="ops-tab-label text-[10px] font-mono tracking-tight text-center whitespace-nowrap text-[var(--foreground)] font-medium leading-none">${_escPb(_pbT("ui.playbooks_studio.tile_label", "Vorlagen"))}</span>`;
    btn.onclick = window.openPlaybooksStudio;
    anchor.parentNode.insertBefore(btn, anchor.nextSibling);
    return true;
  }

  function mountTileWithObserver() {
    if (injectOperationsTile()) return;
    let retries = 0;
    const maxRetries = 12;
    let obs = null;
    const tryMount = () => {
      if (injectOperationsTile()) {
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
      if (!modal.classList.contains("hidden")) renderTab();
    }
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => { /* Vorlagen jetzt direkt in 'Neue autonome Aufgabe' integriert (Option A) */ });
  }
})();
