/**
 * static/js/approval_policies_controller.js
 * Archon OS - GoBD/ISO 27001 Revisionssichere Approval Policy Engine
 */

let currentApprovalsTab = "finance";
let activeApprovalPolicies = {};

async function initApprovalPoliciesView() {
  await Promise.all([
    loadApprovalPolicies(),
    loadApprovalDelegation(),
    loadApprovalRequests(),
    loadApprovalsAuditChain()
  ]);
  if (typeof lucide !== 'undefined') lucide.createIcons();
}

function setApprovalsSubTab(tab) {
  currentApprovalsTab = tab;
  const tabs = ["finance", "email", "system"];
  
  tabs.forEach(t => {
    const btn = document.getElementById(`approvals-subtab-btn-${t}`);
    const view = document.getElementById(`approvals-tab-${t}`);
    const label = btn ? btn.querySelector(".approvals-tab-label") : null;
    const tileWrap = btn ? btn.querySelector(".tile-icon-wrap") : null;

    if (t === tab) {
      if (view) view.classList.remove("hidden");
      if (btn) btn.className = "approvals-header-tile active-cadre-tab flex flex-col items-center justify-between min-w-[56px] sm:min-w-[62px] h-[72px] py-1 px-0.5 bg-transparent border-0 shadow-none opacity-100 cursor-pointer select-none transition-transform hover:scale-105 duration-150";
      if (label) label.className = "approvals-tab-label text-[10px] font-mono tracking-tight text-center whitespace-nowrap text-red-600 font-bold leading-none";
      if (tileWrap) tileWrap.classList.add("active-tile");
    } else {
      if (view) view.classList.add("hidden");
      if (btn) btn.className = "approvals-header-tile flex flex-col items-center justify-between min-w-[56px] sm:min-w-[62px] h-[72px] py-1 px-0.5 bg-transparent border-0 shadow-none opacity-80 hover:opacity-100 cursor-pointer select-none transition-transform hover:scale-105 duration-150";
      if (label) label.className = "approvals-tab-label text-[10px] font-mono tracking-tight text-center whitespace-nowrap text-[var(--muted-foreground)] font-medium leading-none";
      if (tileWrap) tileWrap.classList.remove("active-tile");
    }
  });

  if (typeof lucide !== 'undefined') lucide.createIcons();
}

async function loadApprovalPolicies() {
  try {
    const res = await fetch("/api/operations/approvals/policies");
    if (!res.ok) throw new Error("Fehler beim Laden der Policies");
    const data = await res.json();
    const policies = data.policies || [];

    policies.forEach(p => {
      activeApprovalPolicies[p.policy_key] = p.policy_value;
      const input = document.getElementById(`input-${p.policy_key}`);
      const valDisplay = document.getElementById(`val-${p.policy_key}`);
      if (input) input.value = p.policy_value;
      if (valDisplay) {
        if (p.policy_key.includes("max") || p.policy_key.includes("min")) {
          valDisplay.textContent = `${parseFloat(p.policy_value).toFixed(2)} €`;
        } else if (p.policy_key.includes("hours")) {
          valDisplay.textContent = `${p.policy_value} h`;
        } else {
          valDisplay.textContent = p.policy_value;
        }
      }
    });
  } catch (err) {
    console.error("[Approvals] Policies Load Error:", err);
  }
}

async function savePolicySetting(key) {
  const input = document.getElementById(`input-${key}`);
  if (!input) return;

  const newVal = input.value;
  try {
    const res = await fetch("/api/operations/approvals/policies", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ policy_key: key, new_value: newVal, user_id: "admin" })
    });

    if (!res.ok) throw new Error("Speichern fehlgeschlagen");
    const data = await res.json();

    const valDisplay = document.getElementById(`val-${key}`);
    if (valDisplay) {
      if (key.includes("max") || key.includes("min")) {
        valDisplay.textContent = `${parseFloat(newVal).toFixed(2)} €`;
      } else if (key.includes("hours")) {
        valDisplay.textContent = `${newVal} h`;
      } else {
        valDisplay.textContent = newVal;
      }
    }

    await loadApprovalsAuditChain();
    if (typeof showToast === 'function') {
      showToast(`Policy ${key} revisionssicher signiert und gespeichert.`);
    }
  } catch (err) {
    alert("Fehler beim Speichern: " + err.message);
  }
}

async function loadApprovalDelegation() {
  try {
    const res = await fetch("/api/operations/approvals/delegation?user_id=admin");
    if (!res.ok) return;
    const data = await res.json();
    const deleg = data.delegation || {};

    const toggle = document.getElementById("approvals-vacation-toggle");
    const select = document.getElementById("approvals-substitute-select");
    if (toggle) toggle.checked = Boolean(deleg.is_active);
    if (select && deleg.substitute_id) select.value = deleg.substitute_id;
  } catch (err) {
    console.error("[Approvals] Delegation Load Error:", err);
  }
}

async function toggleVacationMode(isActive) {
  const select = document.getElementById("approvals-substitute-select");
  const subId = select ? select.value : "katharina";
  const subName = select && select.options[select.selectedIndex] ? select.options[select.selectedIndex].text : "Katharina Völk (QM)";

  try {
    const res = await fetch("/api/operations/approvals/delegation", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        user_id: "admin",
        is_active: isActive,
        substitute_id: subId,
        substitute_name: subName
      })
    });
    if (res.ok) {
      await loadApprovalsAuditChain();
      if (typeof showToast === 'function') {
        showToast(isActive ? `Urlaubsmodus aktiviert: Stellvertretung durch ${subName}` : "Urlaubsmodus deaktiviert.");
      }
    }
  } catch (err) {
    console.error("[Approvals] Vacation Toggle Error:", err);
  }
}

async function updateSubstituteAgent(subId) {
  const toggle = document.getElementById("approvals-vacation-toggle");
  if (toggle && toggle.checked) {
    toggleVacationMode(true);
  }
}

async function loadApprovalRequests() {
  try {
    const res = await fetch("/api/operations/approvals/requests");
    if (!res.ok) return;
    const data = await res.json();
    const requests = data.requests || [];

    const badge = document.getElementById("approvals-pending-badge");
    const countBadge = document.getElementById("approvals-queue-count");
    const pendingList = requests.filter(r => r.status === "pending" || r.status === "first_approved" || r.status === "escalated");

    if (badge) badge.textContent = `${pendingList.length} Ausstehend`;
    if (countBadge) countBadge.textContent = pendingList.length;

    const tbody = document.getElementById("approvals-queue-tbody");
    if (!tbody) return;

    if (requests.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="5" class="py-8 text-center text-xs text-[var(--muted-foreground)]">
            <i data-lucide="check-check" class="w-8 h-8 text-emerald-500/50 mx-auto mb-2"></i>
            Keine offenen Freigabeanfragen vorhanden. Alle Schwellenwerte sind nominal.
          </td>
        </tr>
      `;
      if (typeof lucide !== 'undefined') lucide.createIcons();
      return;
    }

    tbody.innerHTML = requests.map(r => {
      let statusPill = "";
      if (r.status === "approved" || r.status === "auto_approved") {
        statusPill = `<span class="px-2 py-0.5 rounded-full text-[10px] font-mono font-bold bg-emerald-500/10 text-emerald-600 border border-emerald-500/25">${r.status === 'auto_approved' ? 'Auto-Freigegeben' : 'Freigegeben'}</span>`;
      } else if (r.status === "escalated") {
        statusPill = `<span class="px-2 py-0.5 rounded-full text-[10px] font-mono font-bold bg-rose-500/20 text-rose-600 animate-pulse border border-rose-500/30">Eskaliert (>24h)</span>`;
      } else if (r.status === "first_approved") {
        statusPill = `<span class="px-2 py-0.5 rounded-full text-[10px] font-mono font-bold bg-amber-500/15 text-amber-600 border border-amber-500/30">1. Freigabe erteilt (4-Augen)</span>`;
      } else if (r.status === "rejected") {
        statusPill = `<span class="px-2 py-0.5 rounded-full text-[10px] font-mono font-bold bg-slate-500/20 text-slate-500 border border-slate-500/30">Abgelehnt</span>`;
      } else {
        statusPill = `<span class="px-2 py-0.5 rounded-full text-[10px] font-mono font-bold bg-sky-500/10 text-sky-600 border border-sky-500/25">Ausstehend</span>`;
      }

      const isPending = (r.status === "pending" || r.status === "first_approved" || r.status === "escalated");

      return `
        <tr class="hover:bg-[var(--secondary)]/40 transition">
          <td class="py-2 px-2">
            <div class="font-bold text-[var(--foreground)] truncate max-w-[200px]" title="${r.title}">${r.title}</div>
            <div class="text-[10px] font-mono text-[var(--muted-foreground)]">${r.id} ${r.reference_id ? '• Ref: ' + r.reference_id : ''}</div>
          </td>
          <td class="py-2 px-2">
            <span class="text-[10px] font-mono uppercase px-1.5 py-0.5 rounded bg-[var(--secondary)]">${r.domain}</span>
          </td>
          <td class="py-2 px-2 text-right font-mono font-bold ${r.amount >= 500 ? 'text-amber-500' : 'text-[var(--foreground)]'}">
            ${r.amount > 0 ? r.amount.toFixed(2) + ' ' + (r.currency || 'EUR') : '-'}
          </td>
          <td class="py-2 px-2 text-center">
            ${statusPill}
          </td>
          <td class="py-2 px-2 text-right">
            ${isPending ? `
              <div class="flex items-center justify-end gap-1">
                <button type="button" onclick="approveRequest('${r.id}')" class="px-2 py-1 rounded bg-emerald-600 hover:bg-emerald-500 text-white font-mono text-[10.5px] font-bold transition cursor-pointer" title="Freigeben">
                  Freigeben
                </button>
                <button type="button" onclick="openRejectDialog('${r.id}')" class="px-2 py-1 rounded border border-rose-500/40 text-rose-500 hover:bg-rose-500/10 font-mono text-[10.5px] transition cursor-pointer" title="Ablehnen">
                  Ablehnen
                </button>
              </div>
            ` : `
              <span class="text-[10px] font-mono text-[var(--muted-foreground)]">Abgeschlossen</span>
            `}
          </td>
        </tr>
      `;
    }).join("");

    if (typeof lucide !== 'undefined') lucide.createIcons();
  } catch (err) {
    console.error("[Approvals] Requests Load Error:", err);
  }
}

async function approveRequest(reqId) {
  try {
    const res = await fetch(`/api/operations/approvals/requests/${reqId}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approver_id: "admin" })
    });
    if (!res.ok) throw new Error("Freigabe fehlgeschlagen");
    await loadApprovalRequests();
    await loadApprovalsAuditChain();
    if (typeof showToast === 'function') {
      showToast(`Freigabe ${reqId} erfolgreich erteilt.`);
    }
  } catch (err) {
    alert(err.message);
  }
}

function openRejectDialog(reqId) {
  const dialog = document.getElementById("approvals-reject-dialog");
  const targetInput = document.getElementById("reject-target-req-id");
  const reasonInput = document.getElementById("reject-reason-input");
  if (dialog && targetInput) {
    targetInput.value = reqId;
    if (reasonInput) reasonInput.value = "";
    dialog.classList.remove("hidden");
  }
}

function closeRejectDialog() {
  const dialog = document.getElementById("approvals-reject-dialog");
  if (dialog) dialog.classList.add("hidden");
}

async function confirmRejectRequest() {
  const targetInput = document.getElementById("reject-target-req-id");
  const reasonInput = document.getElementById("reject-reason-input");
  if (!targetInput || !reasonInput) return;

  const reqId = targetInput.value;
  const reason = reasonInput.value.trim();
  if (!reason) {
    alert("Bitte eine Begründung für die Ablehnung eingeben.");
    return;
  }

  try {
    const res = await fetch(`/api/operations/approvals/requests/${reqId}/reject`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rejected_by: "admin", reason: reason })
    });
    if (!res.ok) throw new Error("Ablehnung fehlgeschlagen");
    closeRejectDialog();
    await loadApprovalRequests();
    await loadApprovalsAuditChain();
    if (typeof showToast === 'function') {
      showToast(`Freigabe ${reqId} abgelehnt.`);
    }
  } catch (err) {
    alert(err.message);
  }
}

async function loadApprovalsAuditChain() {
  try {
    const res = await fetch("/api/operations/approvals/audit-chain?limit=15");
    if (!res.ok) return;
    const data = await res.json();
    const chain = data.chain || [];

    const tbody = document.getElementById("approvals-audit-tbody");
    if (!tbody) return;

    tbody.innerHTML = chain.map(c => `
      <tr class="hover:bg-[var(--secondary)]/50">
        <td class="p-1 text-[var(--muted-foreground)]">${c.timestamp ? c.timestamp.substring(11, 19) : '-'}</td>
        <td class="p-1 font-semibold text-[var(--foreground)]">${c.action}</td>
        <td class="p-1 text-sky-500">${c.user_id}</td>
        <td class="p-1 text-[var(--muted-foreground)] truncate max-w-[120px]" title="${c.current_hash}">
          ${c.current_hash ? c.current_hash.substring(0, 10) + '...' : '-'}
        </td>
      </tr>
    `).join("");
  } catch (err) {
    console.error("[Approvals] Audit Chain Error:", err);
  }
}

async function verifyApprovalsAuditChain() {
  try {
    const res = await fetch("/api/operations/approvals/audit-verify");
    if (!res.ok) throw new Error("Integritätsprüfung fehlgeschlagen");
    const data = await res.json();
    const integ = data.integrity || {};

    if (integ.valid) {
      alert(`[GoBD/ISO 27001 Revisionsprüfung BESTANDEN]\n${integ.message}\nAktueller Genesis-Head: ${integ.latest_hash}`);
    } else {
      alert(`[WARNUNG: KETTENBRUCH ERKANNT]\n${integ.message}`);
    }
  } catch (err) {
    alert("Prüfung fehlgeschlagen: " + err.message);
  }
}
