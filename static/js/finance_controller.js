/**
 * static/js/finance_controller.js
 * Archon OS Finance & Receipt Management Controller
 */

let financeReceipts = [];
let selectedReceipt = null;
let currentFinanceTab = "receipts";

async function initFinanceView() {
  await loadFinanceReceipts();
  if (typeof lucide !== 'undefined') lucide.createIcons();
}

function setFinanceSubTab(tab) {
  currentFinanceTab = tab;
  const tabs = ["receipts", "analytics", "contracts", "dunning"];
  tabs.forEach(t => {
    const btn = document.getElementById(`finance-subtab-btn-${t}`);
    const view = document.getElementById(`finance-view-${t}`);
    const label = btn ? btn.querySelector(".finance-tab-label") : null;
    const tileWrap = btn ? btn.querySelector(".tile-icon-wrap") : null;

    if (t === tab) {
      if (view) view.classList.remove("hidden");
      if (btn) btn.className = "finance-header-tile active-cadre-tab flex flex-col items-center justify-between min-w-[56px] sm:min-w-[62px] h-[72px] py-1 px-0.5 bg-transparent border-0 shadow-none opacity-100 cursor-pointer select-none transition-transform hover:scale-105 duration-150";
      if (label) label.className = "finance-tab-label text-[10px] font-mono tracking-tight text-center whitespace-nowrap text-red-600 font-bold leading-none";
      if (tileWrap) tileWrap.classList.add("active-tile");
    } else {
      if (view) view.classList.add("hidden");
      if (btn) btn.className = "finance-header-tile flex flex-col items-center justify-between min-w-[56px] sm:min-w-[62px] h-[72px] py-1 px-0.5 bg-transparent border-0 shadow-none opacity-80 hover:opacity-100 cursor-pointer select-none transition-transform hover:scale-105 duration-150";
      if (label) label.className = "finance-tab-label text-[10px] font-mono tracking-tight text-center whitespace-nowrap text-[var(--muted-foreground)] font-medium leading-none";
      if (tileWrap) tileWrap.classList.remove("active-tile");
    }
  });

  if (tab === "contracts") {
    loadFinanceContracts();
  } else if (tab === "analytics") {
    updateAnalyticsKPIs();
  } else if (tab === "dunning") {
    loadDunningInvoices();
  }
  if (typeof lucide !== 'undefined') lucide.createIcons();
}

async function loadFinanceReceipts() {
  try {
    const res = await fetch("/api/operations/receipts?limit=100");
    if (!res.ok) throw new Error("Netzwerkfehler");
    const data = await res.json();
    financeReceipts = data.receipts || [];

    // Header Badges
    const badgeCount = document.getElementById("finance-receipt-count-badge");
    const badgeTotal = document.getElementById("finance-total-amount-badge");
    const totalSum = financeReceipts.reduce((acc, r) => acc + (parseFloat(r.amount_gross) || 0), 0);

    if (badgeCount) badgeCount.textContent = `${financeReceipts.length} Belege`;
    if (badgeTotal) badgeTotal.textContent = `${totalSum.toFixed(2)} EUR`;

    renderFinanceReceipts();
    updateAnalyticsKPIs();
  } catch (e) {
    console.error("[Finance] Fehler beim Laden der Belege:", e);
  }
}

function renderFinanceReceipts() {
  const tbody = document.getElementById("finance-receipts-tbody");
  if (!tbody) return;

  const search = (document.getElementById("finance-search-input")?.value || "").toLowerCase().trim();
  const catFilter = document.getElementById("finance-category-filter")?.value || "ALL";
  const statusFilter = document.getElementById("finance-status-filter")?.value || "ALL";

  const filtered = financeReceipts.filter(r => {
    const matchesSearch = !search || 
      (r.merchant && r.merchant.toLowerCase().includes(search)) ||
      (r.category && r.category.toLowerCase().includes(search)) ||
      (r.receipt_id && r.receipt_id.toLowerCase().includes(search));
    const matchesCat = (catFilter === "ALL") || (r.category === catFilter);
    const matchesStatus = (statusFilter === "ALL") || (r.status === statusFilter);
    return matchesSearch && matchesCat && matchesStatus;
  });

  const countEl = document.getElementById("finance-filtered-count");
  if (countEl) countEl.textContent = filtered.length;

  if (filtered.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="6" class="py-8 text-center text-xs text-[var(--muted-foreground)]">
          Keine passenden Belege gefunden.
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = filtered.map(r => {
    const isSelected = selectedReceipt && selectedReceipt.receipt_id === r.receipt_id;
    const rowClass = isSelected 
      ? "bg-sky-500/10 font-medium" 
      : "hover:bg-[var(--secondary)]/40 cursor-pointer transition";

    let statusBadge = `<span class="px-2 py-0.5 rounded-full text-[10px] font-mono font-bold bg-amber-500/10 text-amber-500 border border-amber-500/20">Offen</span>`;
    if (r.status === "approved") {
      statusBadge = `<span class="px-2 py-0.5 rounded-full text-[10px] font-mono font-bold bg-emerald-500/10 text-emerald-500 border border-emerald-500/20">Freigegeben</span>`;
    } else if (r.status === "rejected") {
      statusBadge = `<span class="px-2 py-0.5 rounded-full text-[10px] font-mono font-bold bg-rose-500/10 text-rose-500 border border-rose-500/20">Abgelehnt</span>`;
    }

    const sourceIcon = r.source === "telegram" ? "send" : "upload";

    return `
      <tr class="${rowClass}" onclick="selectFinanceReceipt('${r.receipt_id}')">
        <td class="py-2.5 px-3 font-mono text-[11px] whitespace-nowrap text-[var(--muted-foreground)]">
          ${r.receipt_date || "-"}
        </td>
        <td class="py-2.5 px-3 font-semibold text-[var(--foreground)] truncate max-w-[160px]">
          ${r.merchant || "Unbekannter Händler"}
        </td>
        <td class="py-2.5 px-3">
          <span class="px-2 py-0.5 rounded bg-[var(--secondary)] text-[10px] font-medium text-[var(--foreground)]">
            ${r.category || "Sonstiges"}
          </span>
        </td>
        <td class="py-2.5 px-3 text-right font-mono font-bold text-[var(--foreground)] whitespace-nowrap">
          ${(parseFloat(r.amount_gross) || 0).toFixed(2)} ${r.currency || "EUR"}
        </td>
        <td class="py-2.5 px-3 whitespace-nowrap">
          ${statusBadge}
        </td>
        <td class="py-2.5 px-3 text-center text-[var(--muted-foreground)]" title="Quelle: ${r.source}">
          <i data-lucide="${sourceIcon}" class="w-3.5 h-3.5 mx-auto"></i>
        </td>
      </tr>
    `;
  }).join("");

  if (typeof lucide !== 'undefined') lucide.createIcons();
}

function selectFinanceReceipt(receiptId) {
  const r = financeReceipts.find(x => x.receipt_id === receiptId);
  if (!r) return;
  selectedReceipt = r;

  const emptyEl = document.getElementById("finance-detail-empty");
  const contentEl = document.getElementById("finance-detail-content");
  if (emptyEl) emptyEl.classList.add("hidden");
  if (contentEl) contentEl.classList.remove("hidden");

  // Formularwerte befüllen
  const merchantInp = document.getElementById("finance-edit-merchant");
  const amountInp = document.getElementById("finance-edit-amount");
  const taxInp = document.getElementById("finance-edit-tax");
  const catInp = document.getElementById("finance-edit-category");
  const paymentInp = document.getElementById("finance-edit-payment");
  const dateInp = document.getElementById("finance-edit-date");

  if (merchantInp) merchantInp.value = r.merchant || "";
  if (amountInp) amountInp.value = parseFloat(r.amount_gross) || 0;
  if (taxInp) taxInp.value = parseFloat(r.tax_amount) || 0;
  if (catInp) catInp.value = r.category || "Sonstiges";
  if (paymentInp) paymentInp.value = r.payment_method || "Unbekannt";
  if (dateInp) dateInp.value = r.receipt_date || "";

  // Bildvorschau
  const imgEl = document.getElementById("finance-detail-img");
  const linkEl = document.getElementById("finance-detail-img-link");
  const imgUrl = `/api/operations/receipts/${r.receipt_id}/image`;
  if (imgEl) imgEl.src = imgUrl;
  if (linkEl) linkEl.href = imgUrl;

  // Status Badge im Detailpanel
  const statusBadge = document.getElementById("finance-detail-status-badge");
  if (statusBadge) {
    if (r.status === "approved") {
      statusBadge.textContent = "Freigegeben";
      statusBadge.className = "px-2 py-0.5 rounded-full text-[10px] font-mono font-bold bg-emerald-500/10 text-emerald-500 border border-emerald-500/20";
    } else if (r.status === "rejected") {
      statusBadge.textContent = "Abgelehnt";
      statusBadge.className = "px-2 py-0.5 rounded-full text-[10px] font-mono font-bold bg-rose-500/10 text-rose-500 border border-rose-500/20";
    } else {
      statusBadge.textContent = "Prüfung offen";
      statusBadge.className = "px-2 py-0.5 rounded-full text-[10px] font-mono font-bold bg-amber-500/10 text-amber-500 border border-amber-500/20";
    }
  }

  renderFinanceReceipts();
  if (typeof lucide !== 'undefined') lucide.createIcons();
}

async function approveCurrentReceipt() {
  if (!selectedReceipt) return;
  await saveReceiptUpdates({ status: "approved" });
}

async function rejectCurrentReceipt() {
  if (!selectedReceipt) return;
  await saveReceiptUpdates({ status: "rejected" });
}

async function saveCurrentReceiptEdits() {
  if (!selectedReceipt) return;
  const updates = {
    merchant: document.getElementById("finance-edit-merchant")?.value,
    amount_gross: parseFloat(document.getElementById("finance-edit-amount")?.value) || 0,
    tax_amount: parseFloat(document.getElementById("finance-edit-tax")?.value) || 0,
    category: document.getElementById("finance-edit-category")?.value,
    payment_method: document.getElementById("finance-edit-payment")?.value
  };
  await saveReceiptUpdates(updates);
}

async function saveReceiptUpdates(updates) {
  if (!selectedReceipt) return;
  try {
    const res = await fetch(`/api/operations/receipts/${selectedReceipt.receipt_id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: json.stringify(updates)
    });
    if (!res.ok) throw new Error("Fehler beim Speichern");
    
    // Lokales Objekt aktualisieren
    Object.assign(selectedReceipt, updates);
    await loadFinanceReceipts();
    selectFinanceReceipt(selectedReceipt.receipt_id);
  } catch (e) {
    alert("Fehler beim Aktualisieren: " + e.message);
  }
}

async function handleFinanceFileUpload(event) {
  const file = event.target.files?.[0];
  if (!file) return;

  const formData = new FormData();
  formData.append("file", file);
  formData.append("sender", "Operator");

  try {
    const res = await fetch("/api/operations/receipts/upload", {
      method: "POST",
      body: formData
    });
    if (!res.ok) throw new Error("Upload fehlgeschlagen");
    const data = await res.json();
    await loadFinanceReceipts();
    if (data.receipt?.receipt_id) {
      selectFinanceReceipt(data.receipt.receipt_id);
    }
  } catch (e) {
    alert("Fehler beim Beleg-Upload: " + e.message);
  } finally {
    event.target.value = "";
  }
}

function updateAnalyticsKPIs() {
  const kpiTotal = document.getElementById("finance-kpi-total");
  const kpiApproved = document.getElementById("finance-kpi-approved");
  const kpiPending = document.getElementById("finance-kpi-pending");

  const total = financeReceipts.reduce((acc, r) => acc + (parseFloat(r.amount_gross) || 0), 0);
  const approved = financeReceipts
    .filter(r => r.status === "approved")
    .reduce((acc, r) => acc + (parseFloat(r.amount_gross) || 0), 0);
  const pending = financeReceipts.filter(r => r.status === "pending_review").length;

  if (kpiTotal) kpiTotal.textContent = `${total.toFixed(2)} EUR`;
  if (kpiApproved) kpiApproved.textContent = `${approved.toFixed(2)} EUR`;
  if (kpiPending) kpiPending.textContent = pending;
}

async function loadFinanceContracts() {
  const tbody = document.getElementById("finance-contracts-tbody");
  const countEl = document.getElementById("finance-contracts-count");
  if (!tbody) return;

  try {
    const res = await fetch("/api/operations/esign/contracts?limit=50");
    if (!res.ok) throw new Error("Netzwerkfehler");
    const data = await res.json();
    const contracts = data.contracts || [];

    if (countEl) countEl.textContent = contracts.length;

    if (contracts.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="6" class="py-8 text-center text-xs text-[var(--muted-foreground)]">
            Noch keine Verträge angelegt.
          </td>
        </tr>
      `;
      return;
    }

    tbody.innerHTML = contracts.map(c => {
      let statusBadge = `<span class="px-2 py-0.5 rounded-full text-[10px] font-mono font-bold bg-amber-500/10 text-amber-500 border border-amber-500/20">Ausstehend</span>`;
      if (c.status === "completed") {
        statusBadge = `<span class="px-2 py-0.5 rounded-full text-[10px] font-mono font-bold bg-emerald-500/10 text-emerald-500 border border-emerald-500/20">Unterzeichnet</span>`;
      }

      return `
        <tr class="hover:bg-[var(--secondary)]/40 transition">
          <td class="py-2.5 px-3 font-semibold text-[var(--foreground)]">${c.title || "Vertrag"}</td>
          <td class="py-2.5 px-3 text-[var(--foreground)]">${c.signer_name || "-"}</td>
          <td class="py-2.5 px-3 font-mono text-[11px] text-[var(--muted-foreground)]">${c.signer_email || "-"}</td>
          <td class="py-2.5 px-3 whitespace-nowrap">${statusBadge}</td>
          <td class="py-2.5 px-3 font-mono text-[11px] text-[var(--muted-foreground)]">${c.created_at || "-"}</td>
          <td class="py-2.5 px-3 text-right">
            ${c.sign_url ? `<a href="${c.sign_url}" target="_blank" class="text-sky-500 hover:underline font-mono text-[11px]">Signieren &rarr;</a>` : "-"}
          </td>
        </tr>
      `;
    }).join("");

    if (typeof lucide !== 'undefined') lucide.createIcons();
  } catch (e) {
    console.error("[Finance] Fehler beim Laden der Verträge:", e);
  }
}

// =========================================================================
// MAHNWESEN CONTROLLER
// =========================================================================

let dunningInvoices = [];
let selectedInvoice = null;
let currentDunningDraft = null;

async function loadDunningInvoices() {
  try {
    const res = await fetch("/api/operations/dunning/invoices");
    if (!res.ok) throw new Error("Fehler beim Laden der Rechnungen");
    const data = await res.json();
    dunningInvoices = data.invoices || [];

    const countEl = document.getElementById("finance-dunning-count");
    if (countEl) countEl.textContent = dunningInvoices.length;

    renderDunningInvoices();
  } catch (e) {
    console.error("[Dunning] Error:", e);
  }
}

function renderDunningInvoices() {
  const tbody = document.getElementById("finance-dunning-tbody");
  if (!tbody) return;

  const search = (document.getElementById("finance-dunning-search")?.value || "").toLowerCase().trim();
  const filter = document.getElementById("finance-dunning-filter")?.value || "ALL";

  const filtered = dunningInvoices.filter(inv => {
    const matchesSearch = !search ||
      (inv.invoice_id && inv.invoice_id.toLowerCase().includes(search)) ||
      (inv.customer_name && inv.customer_name.toLowerCase().includes(search));
    
    if (filter === "ALL") return matchesSearch;
    if (filter === "overdue") return matchesSearch && inv.is_overdue;
    return matchesSearch && inv.status === filter;
  });

  if (filtered.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="6" class="py-8 text-center text-xs text-[var(--muted-foreground)]">
          Keine passenden Ausgangsrechnungen gefunden.
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = filtered.map(inv => {
    const isSelected = selectedInvoice && selectedInvoice.invoice_id === inv.invoice_id;
    const rowClass = isSelected ? "bg-amber-500/10 font-medium" : "hover:bg-[var(--secondary)]/40 cursor-pointer transition";

    let badge = `<span class="px-2 py-0.5 rounded-full text-[10px] font-mono font-bold bg-slate-500/10 text-[var(--muted-foreground)]">Offen</span>`;
    if (inv.status === "paid") {
      badge = `<span class="px-2 py-0.5 rounded-full text-[10px] font-mono font-bold bg-emerald-500/10 text-emerald-600 border border-emerald-500/20">Bezahlt</span>`;
    } else if (inv.status === "dunning_1") {
      badge = `<span class="px-2 py-0.5 rounded-full text-[10px] font-mono font-bold bg-amber-500/15 text-amber-500 border border-amber-500/30">Erinnerung (1)</span>`;
    } else if (inv.status === "dunning_2") {
      badge = `<span class="px-2 py-0.5 rounded-full text-[10px] font-mono font-bold bg-orange-500/15 text-orange-500 border border-orange-500/30">Mahnung (2)</span>`;
    } else if (inv.status === "dunning_3") {
      badge = `<span class="px-2 py-0.5 rounded-full text-[10px] font-mono font-bold bg-rose-500/15 text-rose-500 border border-rose-500/30">Letzte Mahnung (3)</span>`;
    } else if (inv.is_overdue) {
      badge = `<span class="px-2 py-0.5 rounded-full text-[10px] font-mono font-bold bg-amber-500/20 text-amber-600 font-bold">${inv.overdue_days}d Überfällig</span>`;
    }

    return `
      <tr class="${rowClass}" onclick="selectDunningInvoice('${inv.invoice_id}')">
        <td class="py-2.5 px-3 font-mono font-bold text-sky-500 whitespace-nowrap">${inv.invoice_id}</td>
        <td class="py-2.5 px-3 font-semibold text-[var(--foreground)] truncate max-w-[140px]">${inv.customer_name}</td>
        <td class="py-2.5 px-3 font-mono text-[11px] whitespace-nowrap text-[var(--muted-foreground)]">${inv.due_date}</td>
        <td class="py-2.5 px-3 text-right font-mono font-bold text-[var(--foreground)] whitespace-nowrap">${parseFloat(inv.amount_gross).toFixed(2)} EUR</td>
        <td class="py-2.5 px-3 whitespace-nowrap">${badge}</td>
        <td class="py-2.5 px-3 text-right">
          <button onclick="event.stopPropagation(); selectDunningInvoice('${inv.invoice_id}');" class="px-2 py-1 rounded bg-[var(--secondary)] hover:bg-[var(--border)] text-[10.5px] font-semibold text-[var(--foreground)]">
            Mahnung &rarr;
          </button>
        </td>
      </tr>
    `;
  }).join("");

  if (typeof lucide !== 'undefined') lucide.createIcons();
}

function selectDunningInvoice(invId) {
  const inv = dunningInvoices.find(x => x.invoice_id === invId);
  if (!inv) return;
  selectedInvoice = inv;
  currentDunningDraft = null;

  const emptyEl = document.getElementById("finance-dunning-empty");
  const contentEl = document.getElementById("finance-dunning-content");
  if (emptyEl) emptyEl.classList.add("hidden");
  if (contentEl) contentEl.classList.remove("hidden");

  document.getElementById("dunning-detail-invid").textContent = inv.invoice_id;
  document.getElementById("dunning-detail-cust").textContent = `${inv.customer_name} (${inv.customer_email})`;
  document.getElementById("dunning-detail-overdue").textContent = inv.is_overdue ? `${inv.overdue_days} Tage über Fälligkeit` : "In Zahlungsfrist";

  const stageBadge = document.getElementById("finance-dunning-stage-badge");
  if (stageBadge) {
    stageBadge.textContent = `Status: ${inv.status}`;
    stageBadge.className = "px-2 py-0.5 rounded-full text-[10px] font-mono font-bold bg-amber-500/10 text-amber-500 border border-amber-500/20";
  }

  // Generiere automatischen Entwurf passend zur Stufe
  const autoLevel = inv.recommended_level || 1;
  generateDraftForSelected(autoLevel);
  renderDunningInvoices();
}

async function generateDraftForSelected(level) {
  if (!selectedInvoice) return;
  const textarea = document.getElementById("dunning-draft-textarea");
  if (textarea) textarea.value = "Generiere Entwurf...";

  try {
    const res = await fetch("/api/operations/dunning/draft", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ invoice_id: selectedInvoice.invoice_id, level: level })
    });
    if (!res.ok) throw new Error("Konnte Mahnentwurf nicht generieren.");
    const data = await res.json();
    currentDunningDraft = data.draft;
    if (textarea) textarea.value = currentDunningDraft.body_text;
  } catch (e) {
    if (textarea) textarea.value = "Fehler beim Generieren: " + e.message;
  }
}

async function approveCurrentDunningDraft() {
  if (!currentDunningDraft) {
    alert("Bitte wählen Sie zuerst eine Mahnstufe aus.");
    return;
  }

  if (!confirm(`Mahnung '${currentDunningDraft.dunning_id}' über ${currentDunningDraft.total_claim.toFixed(2)} EUR verbindlich freigeben und versenden?`)) {
    return;
  }

  try {
    const res = await fetch("/api/operations/dunning/approve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dunning_id: currentDunningDraft.dunning_id })
    });
    if (!res.ok) throw new Error("Freigabe fehlgeschlagen");
    alert("Mahnung erfolgreich freigegeben und versandt!");
    await loadDunningInvoices();
    if (selectedInvoice) {
      selectDunningInvoice(selectedInvoice.invoice_id);
    }
  } catch (e) {
    alert("Fehler bei Mahnungsfreigabe: " + e.message);
  }
}

async function markCurrentInvoicePaid() {
  if (!selectedInvoice) return;
  if (!confirm(`Rechnung ${selectedInvoice.invoice_id} als vollständig bezahlt markieren?`)) return;

  try {
    const res = await fetch("/api/operations/dunning/mark-paid", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ invoice_id: selectedInvoice.invoice_id })
    });
    if (!res.ok) throw new Error("Konnte Status nicht aktualisieren");
    await loadDunningInvoices();
    selectDunningInvoice(selectedInvoice.invoice_id);
  } catch (e) {
    alert("Fehler: " + e.message);
  }
}

function openCreateInvoiceModal() {
  const modal = document.getElementById("modal-create-invoice");
  if (modal) modal.classList.remove("hidden");
}

function closeCreateInvoiceModal() {
  const modal = document.getElementById("modal-create-invoice");
  if (modal) modal.classList.add("hidden");
}

async function submitNewInvoice() {
  const customer = document.getElementById("new-inv-customer")?.value.trim();
  const email = document.getElementById("new-inv-email")?.value.trim();
  const amount = parseFloat(document.getElementById("new-inv-amount")?.value) || 0;
  const days = parseInt(document.getElementById("new-inv-days")?.value) || 14;

  if (!customer || amount <= 0) {
    alert("Bitte Kundenname und einen positiven Betrag eingeben.");
    return;
  }

  try {
    const res = await fetch("/api/operations/dunning/invoices", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        customer_name: customer,
        customer_email: email,
        amount_net: amount,
        due_days: days
      })
    });
    if (!res.ok) throw new Error("Rechnung konnte nicht erstellt werden");
    closeCreateInvoiceModal();
    await loadDunningInvoices();
  } catch (e) {
    alert("Fehler beim Erstellen: " + e.message);
  }
}

