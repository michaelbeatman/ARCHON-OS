/**
 * static/js/playbooks_studio.js
 * M44 — Business Playbooks (Operations-Vorlagen, n8n-Katalog & Editor)
 */
(function () {
  "use strict";

  const MODAL_ID = "archon-playbooks-modal";
  let currentTab = "active";

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
      <div class="w-full max-w-4xl rounded-xl border theme-border bg-white dark:bg-zinc-900 p-5 shadow-2xl max-h-[88vh] flex flex-col gap-3">
        <div class="flex items-center justify-between border-b theme-border pb-2">
          <h2 class="text-base font-bold">Operations Vorlagen & Playbooks</h2>
          <button id="pb-close-btn" class="px-2 py-1 text-xs rounded border theme-border">Schließen</button>
        </div>
        <div class="flex gap-2">
          <button data-pbtab="active" class="pb-tab px-3 py-1.5 rounded text-xs font-semibold border theme-border">Aktive Vorlagen (10+)</button>
          <button data-pbtab="catalog" class="pb-tab px-3 py-1.5 rounded text-xs font-semibold border theme-border">Katalog (Nachladen)</button>
          <button data-pbtab="editor" class="pb-tab px-3 py-1.5 rounded text-xs font-semibold border theme-border">+ Neue Vorlage (Editor)</button>
        </div>
        <div id="pb-body" class="overflow-y-auto flex-1 space-y-2 text-xs"></div>
      </div>`;
    document.body.appendChild(modal);
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
          <input id="pb-ed-title" class="w-full p-2 rounded border theme-border bg-transparent" placeholder="Titel der Vorlage (z. B. Quartals-Review)" />
          <input id="pb-ed-cat" class="w-full p-2 rounded border theme-border bg-transparent" value="Operations & Führung" placeholder="Kategorie" />
          <input id="pb-ed-vars" class="w-full p-2 rounded border theme-border bg-transparent" placeholder="Variablen kommagetrennt (z. B. kunde, quartal)" />
          <textarea id="pb-ed-prompt" rows="3" class="w-full p-2 rounded border theme-border bg-transparent" placeholder="Schritt 1 Prompt ({{kunde}} ...)"></textarea>
          <button id="pb-ed-save" class="px-3 py-1.5 rounded bg-indigo-600 text-white font-semibold">Vorlage speichern</button>
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
            steps: [{ order: 1, title: "Schritt 1", agent_id: "executive_decision_architect", prompt_template }],
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
    body.innerHTML = list
      .map(
        (pb) => `
      <div class="p-3 rounded border theme-border flex items-center justify-between gap-3">
        <div>
          <div class="font-semibold">${pb.title} <span class="opacity-60">[${pb.category}]</span></div>
          <div class="opacity-75">${pb.description || ""}</div>
        </div>
        <div class="flex gap-1.5 shrink-0">
          ${
            activeOnly
              ? `<button data-run="${pb.id}" class="px-2.5 py-1 rounded bg-emerald-600 text-white font-semibold">Ausführen</button>`
              : `<button data-toggle="${pb.id}" data-next="true" class="px-2.5 py-1 rounded bg-indigo-600 text-white font-semibold">Aktivieren</button>`
          }
          ${
            activeOnly
              ? `<button data-toggle="${pb.id}" data-next="false" class="px-2 py-1 rounded border theme-border">Ausblenden</button>`
              : ""
          }
        </div>
      </div>`
      )
      .join("");

    body.querySelectorAll("[data-toggle]").forEach((b) => {
      b.onclick = async () => {
        await api(`/api/v1/playbooks/${b.dataset.toggle}/toggle`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ active: b.dataset.next === "true" }),
        });
        renderTab();
      };
    });
    body.querySelectorAll("[data-run]").forEach((b) => {
      b.onclick = async () => {
        const res = await api(`/api/v1/playbooks/${b.dataset.run}/run`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ variables: {} }),
        });
        if (res.status === "success") {
          b.textContent = "Gestartet";
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

  function injectOperationsTile() {
    if (document.getElementById("ops-subtab-playbooks")) return;
    const anchor =
      document.getElementById("ops-subtab-org") ||
      document.getElementById("ops-subtab-kanban");
    if (!anchor || !anchor.parentNode) return;

    const btn = document.createElement("button");
    btn.type = "button";
    btn.id = "ops-subtab-playbooks";
    btn.title = "Business Playbooks & Workflow-Vorlagen (M44)";
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
      <span class="ops-tab-label text-[10px] font-mono tracking-tight text-center whitespace-nowrap text-[var(--foreground)] font-medium leading-none">Vorlagen</span>`;
    btn.onclick = window.openPlaybooksStudio;
    anchor.parentNode.insertBefore(btn, anchor.nextSibling);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", injectOperationsTile);
  } else {
    injectOperationsTile();
  }
})();
