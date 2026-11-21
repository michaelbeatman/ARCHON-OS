/**
 * static/js/treasury_studio.js — M103: Treasury, Wallets, Bankkonten & Passkey-gesichertes Zahlungs-Cockpit
 */
(function () {
  if (window.__treasuryStudioInitialized) return;
  window.__treasuryStudioInitialized = true;

  const esc = (v) =>
    String(v == null ? "" : v)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");

  const TYPE_LABELS = {
    bank: "Bankkonto",
    paypal: "PayPal",
    stripe: "Stripe",
    crypto_treasury: "Krypto (Watch-Only)",
    crypto_agent_allowance: "Agent-Allowance (x402)",
  };

  const CUSTODY_LABELS = {
    passkey_hitl: "Handy-Passkey / HITL",
    watch_only: "Nur lesend (Watch-Only)",
    allowance_capped: "Gedeckelt (Cap + Allowlist)",
  };

  const CATEGORIES = [
    "LLM / API",
    "Ads & Marketing",
    "Lieferanten / E-Commerce",
    "Software & Abos",
    "Steuern & Gebuehren",
    "Honorar / Service",
    "Einnahme / Umsatz",
    "Sonstiges",
  ];

  let _overview = null;
  let _catFilter = "all";

  async function apiJson(url, opts = {}) {
    const res = await fetch(url, {
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
      ...opts,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    return data;
  }

  function ensureTreasuryTabButton() {
    if (document.getElementById("finance-subtab-btn-treasury")) return;
    const dunningBtn = document.getElementById("finance-subtab-btn-dunning");
    if (!dunningBtn || !dunningBtn.parentNode) return;

    const btn = document.createElement("button");
    btn.type = "button";
    btn.id = "finance-subtab-btn-treasury";
    btn.title = "Treasury, Bankkonten, PayPal, Krypto-Wallets & Zahlungsfreigaben";
    btn.className =
      "finance-header-tile flex flex-col items-center justify-between min-w-[56px] sm:min-w-[62px] h-[72px] py-1 px-0.5 bg-transparent border-0 shadow-none opacity-80 hover:opacity-100 cursor-pointer select-none transition-transform hover:scale-105 duration-150";
    btn.setAttribute("onclick", "setFinanceSubTab('treasury')");
    btn.innerHTML = `
      <div class="tile-icon-wrap w-11 h-11 sm:w-12 sm:h-12 flex items-center justify-center mb-0.5 relative">
        <img src="/static/img/cadre_icons/approvals.png?v=2026112047" alt="Treasury" class="w-full h-full object-contain drop-shadow-xs pointer-events-none">
      </div>
      <span class="finance-tab-label text-[10px] font-mono tracking-tight text-center whitespace-nowrap text-[var(--muted-foreground)] font-medium leading-none">Treasury</span>
    `;
    dunningBtn.parentNode.insertBefore(btn, dunningBtn.nextSibling);
  }

  function renderTreasury() {
    const mount = document.getElementById("finance-view-treasury");
    if (!mount || !_overview) return;

    const accounts = _overview.accounts || [];
    const pending = _overview.pending_approvals || [];
    const txs = _overview.transactions || [];
    const liqCur = _overview.liquidity_by_currency || {};
    const liqType = _overview.liquidity_by_type || {};
    const spendCat = _overview.spend_by_category || {};
    const passkeyReq = !!_overview.passkey_payments_required;

    const liqSummary = Object.keys(liqCur).length
      ? Object.entries(liqCur)
          .map(([c, v]) => `${Number(v).toFixed(2)} ${esc(c)}`)
          .join(" · ")
      : "0.00 EUR";

    const filteredTxs =
      _catFilter === "all" ? txs : txs.filter((tx) => (tx.category || "Sonstiges") === _catFilter);

    const maxCatSpend = Math.max(1, ...Object.values(spendCat).map((v) => Number(v) || 0));

    mount.innerHTML = `
      <div class="space-y-3 pb-4">
        <div class="p-3 rounded-xl border ${
          passkeyReq
            ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-200"
            : "border-amber-500/40 bg-amber-500/10 text-amber-200"
        } flex flex-wrap items-center justify-between gap-2 text-xs">
          <div>
            <b>${passkeyReq ? "Handy-Passkey & HITL-Schutz aktiv:" : "Hinweis:"}</b>
            ${
              passkeyReq
                ? "Agenten koennen keine Zahlungen oder Limit-Aenderungen selbst ausfuehren. Jede Zahlung erfordert deine Passkey-Freigabe."
                : "Passkey-Pflicht fuer Zahlungen ist aktuell in den Benutzer-Settings optional/ausgeschaltet. Aktiviere sie unter Settings -> Benutzer fuer maximalen Schutz."
            }
          </div>
          <button type="button" id="tr-open-passkey-settings" class="px-2.5 py-1 rounded-lg border border-current text-[11px] font-mono hover:opacity-80">
            Passkey-Regeln
          </button>
        </div>

        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2.5">
          <div class="p-3 rounded-xl border border-[var(--border)] bg-[var(--card)]">
            <div class="text-[10px] font-mono uppercase text-[var(--muted-foreground)]">Gesamtliquiditaet</div>
            <div class="text-base font-black text-[var(--foreground)] mt-1">${liqSummary}</div>
            <div class="text-[10px] text-[var(--muted-foreground)] mt-0.5">${accounts.length} verbundene Konten/Wallets</div>
          </div>
          <div class="p-3 rounded-xl border border-[var(--border)] bg-[var(--card)]">
            <div class="text-[10px] font-mono uppercase text-[var(--muted-foreground)]">Bank + PayPal / Stripe</div>
            <div class="text-base font-black text-[var(--foreground)] mt-1">${(
              Number(liqType.bank || 0) +
              Number(liqType.paypal || 0) +
              Number(liqType.stripe || 0)
            ).toFixed(2)}</div>
            <div class="text-[10px] text-[var(--muted-foreground)] mt-0.5">Fiat-Schienen</div>
          </div>
          <div class="p-3 rounded-xl border border-[var(--border)] bg-[var(--card)]">
            <div class="text-[10px] font-mono uppercase text-[var(--muted-foreground)]">Krypto-Wallets</div>
            <div class="text-base font-black text-[var(--foreground)] mt-1">${(
              Number(liqType.crypto_treasury || 0) + Number(liqType.crypto_agent_allowance || 0)
            ).toFixed(2)}</div>
            <div class="text-[10px] text-[var(--muted-foreground)] mt-0.5">Treasury + Agent-Allowance</div>
          </div>
          <div class="p-3 rounded-xl border ${pending.length ? "border-amber-500/50 bg-amber-500/10" : "border-[var(--border)] bg-[var(--card)]"}">
            <div class="text-[10px] font-mono uppercase text-[var(--muted-foreground)]">Offene Freigaben</div>
            <div class="text-base font-black ${pending.length ? "text-amber-300" : "text-[var(--foreground)]"} mt-1">${pending.length}</div>
            <div class="text-[10px] text-[var(--muted-foreground)] mt-0.5">Ausgaben gesamt: ${Number(_overview.total_spent || 0).toFixed(2)}</div>
          </div>
        </div>

        <div class="grid grid-cols-1 xl:grid-cols-2 gap-3">
          <section class="p-3 rounded-xl border border-[var(--border)] bg-[var(--card)] space-y-2.5">
            <div class="flex items-center justify-between">
              <h3 class="text-xs font-bold uppercase tracking-wider font-mono">Offene Zahlungsfreigaben (HITL / Passkey)</h3>
              <span class="text-[10px] font-mono text-[var(--muted-foreground)]">${pending.length} wartend</span>
            </div>
            <div class="space-y-2 max-h-[260px] overflow-y-auto">
              ${
                pending.length
                  ? pending
                      .map(
                        (tx) => `
                      <div class="p-2.5 rounded-lg border border-amber-500/35 bg-[var(--page-bg)] space-y-1.5 text-xs">
                        <div class="flex items-center justify-between gap-2">
                          <span class="font-bold text-[var(--foreground)]">${Number(tx.amount).toFixed(2)} ${esc(tx.currency)} → ${esc(tx.recipient || "Empfaenger")}</span>
                          <span class="text-[10px] font-mono px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-300">${esc(tx.category)}</span>
                        </div>
                        <div class="text-[11px] text-[var(--muted-foreground)]">${esc(tx.purpose || "Ohne Verwendungszweck")} · Angefordert von: <b>${esc(tx.requested_by)}</b></div>
                        <div class="text-[10px] font-mono text-amber-300/90">${esc(tx.policy_note)}</div>
                        <div class="flex gap-2 pt-1">
                          <button type="button" data-pay-approve="${esc(tx.id)}" class="px-3 py-1 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-[11px] font-semibold">
                            Mit Passkey freigeben
                          </button>
                          <button type="button" data-pay-reject="${esc(tx.id)}" class="px-2.5 py-1 rounded-lg border border-rose-500/40 text-rose-400 text-[11px] hover:bg-rose-500/10">
                            Ablehnen
                          </button>
                        </div>
                      </div>`
                      )
                      .join("")
                  : '<div class="text-xs text-[var(--muted-foreground)] py-4 text-center">Keine offenen Zahlungsfreigaben.</div>'
              }
            </div>
          </section>

          <section class="p-3 rounded-xl border border-[var(--border)] bg-[var(--card)] space-y-2.5">
            <h3 class="text-xs font-bold uppercase tracking-wider font-mono">Wofuer Geld ausgegeben wurde</h3>
            <div class="space-y-2">
              ${
                Object.keys(spendCat).length
                  ? Object.entries(spendCat)
                      .sort((a, b) => b[1] - a[1])
                      .map(([cat, val]) => {
                        const pct = Math.max(4, Math.round((Number(val) / maxCatSpend) * 100));
                        return `
                          <div class="space-y-0.5 text-xs">
                            <div class="flex justify-between font-mono text-[11px]">
                              <span>${esc(cat)}</span>
                              <b>${Number(val).toFixed(2)}</b>
                            </div>
                            <div class="w-full h-2 rounded-full bg-[var(--page-bg)] overflow-hidden">
                              <div class="h-full bg-indigo-500 rounded-full" style="width:${pct}%"></div>
                            </div>
                          </div>`;
                      })
                      .join("")
                  : '<div class="text-xs text-[var(--muted-foreground)] py-4 text-center">Noch keine ausgefuehrten Ausgaben erfasst.</div>'
              }
            </div>
          </section>
        </div>

        <div class="grid grid-cols-1 xl:grid-cols-2 gap-3">
          <section class="p-3 rounded-xl border border-[var(--border)] bg-[var(--card)] space-y-2.5">
            <h3 class="text-xs font-bold uppercase tracking-wider font-mono">Konten, PayPal & Krypto-Wallets</h3>
            <div class="space-y-1.5 max-h-[210px] overflow-y-auto">
              ${
                accounts.length
                  ? accounts
                      .map(
                        (a) => `
                      <div class="p-2 rounded-lg border border-[var(--border)] bg-[var(--page-bg)] flex items-center justify-between gap-2 text-xs">
                        <div class="min-w-0">
                          <div class="font-semibold truncate">${esc(a.name)} <span class="text-[10px] font-mono text-indigo-300">[${esc(TYPE_LABELS[a.account_type] || a.account_type)}]</span></div>
                          <div class="text-[10px] font-mono text-[var(--muted-foreground)] truncate">${esc(CUSTODY_LABELS[a.custody_mode] || a.custody_mode)}${a.identifier ? ` · ${esc(a.identifier)}` : ""}</div>
                        </div>
                        <div class="flex items-center gap-2 shrink-0">
                          <span class="font-mono font-bold">${Number(a.balance).toFixed(2)} ${esc(a.currency)}</span>
                          <button type="button" data-acc-del="${esc(a.id)}" class="text-rose-400 hover:text-rose-300 text-xs">✕</button>
                        </div>
                      </div>`
                      )
                      .join("")
                  : '<div class="text-xs text-[var(--muted-foreground)]">Noch keine Konten/Wallets angelegt.</div>'
              }
            </div>

            <div class="pt-2 border-t border-[var(--border)] grid grid-cols-2 md:grid-cols-3 gap-1.5 text-xs">
              <input id="tr-acc-name" placeholder="Kontoname (z. B. Geschaeftskonto)" class="px-2 py-1 rounded border border-[var(--border)] bg-[var(--page-bg)]" />
              <select id="tr-acc-type" class="px-2 py-1 rounded border border-[var(--border)] bg-[var(--page-bg)]">
                <option value="bank">Bankkonto</option>
                <option value="paypal">PayPal</option>
                <option value="stripe">Stripe</option>
                <option value="crypto_treasury">Krypto (Watch-Only)</option>
                <option value="crypto_agent_allowance">Agent-Allowance (x402)</option>
              </select>
              <input id="tr-acc-cur" value="EUR" placeholder="Waehrung (EUR/USD/USDC)" class="px-2 py-1 rounded border border-[var(--border)] bg-[var(--page-bg)] font-mono" />
              <input id="tr-acc-bal" type="number" step="0.01" placeholder="Kontostand" class="px-2 py-1 rounded border border-[var(--border)] bg-[var(--page-bg)] font-mono" />
              <input id="tr-acc-id" placeholder="IBAN / E-Mail / Wallet" class="px-2 py-1 rounded border border-[var(--border)] bg-[var(--page-bg)] font-mono" />
              <button type="button" id="tr-acc-add" class="px-2.5 py-1 rounded bg-indigo-600 hover:bg-indigo-500 text-white font-semibold">+ Konto/Wallet</button>
            </div>
          </section>

          <section class="p-3 rounded-xl border border-[var(--border)] bg-[var(--card)] space-y-2.5">
            <h3 class="text-xs font-bold uppercase tracking-wider font-mono">Zahlung / Ausgabe / Eingang erfassen</h3>
            <div class="grid grid-cols-2 md:grid-cols-3 gap-1.5 text-xs">
              <select id="tr-tx-acc" class="px-2 py-1 rounded border border-[var(--border)] bg-[var(--page-bg)]">
                ${accounts.map((a) => `<option value="${esc(a.id)}">${esc(a.name)} (${esc(a.currency)})</option>`).join("")}
              </select>
              <select id="tr-tx-dir" class="px-2 py-1 rounded border border-[var(--border)] bg-[var(--page-bg)]">
                <option value="out">Ausgabe (Zahlung)</option>
                <option value="in">Einnahme (Gutschrift)</option>
              </select>
              <input id="tr-tx-amt" type="number" step="0.01" placeholder="Betrag" class="px-2 py-1 rounded border border-[var(--border)] bg-[var(--page-bg)] font-mono" />
              <select id="tr-tx-cat" class="px-2 py-1 rounded border border-[var(--border)] bg-[var(--page-bg)]">
                ${CATEGORIES.map((c) => `<option value="${esc(c)}">${esc(c)}</option>`).join("")}
              </select>
              <input id="tr-tx-rec" placeholder="Empfaenger / Anbieter" class="px-2 py-1 rounded border border-[var(--border)] bg-[var(--page-bg)]" />
              <input id="tr-tx-pur" placeholder="Verwendungszweck" class="px-2 py-1 rounded border border-[var(--border)] bg-[var(--page-bg)]" />
            </div>
            <div class="flex flex-wrap items-center justify-between gap-2 text-xs">
              <label class="flex items-center gap-1.5 cursor-pointer">
                <input type="checkbox" id="tr-tx-agent" />
                <span class="text-[11px] text-[var(--muted-foreground)]">Als Agent-Anfrage testen (landet bei Passkey/HITL in Freigabe)</span>
              </label>
              <button type="button" id="tr-tx-submit" class="px-3 py-1.5 rounded bg-indigo-600 hover:bg-indigo-500 text-white font-semibold">Erfassen</button>
            </div>
          </section>
        </div>

        <section class="p-3 rounded-xl border border-[var(--border)] bg-[var(--card)] space-y-2">
          <div class="flex flex-wrap items-center justify-between gap-2">
            <h3 class="text-xs font-bold uppercase tracking-wider font-mono">Transaktions-Ledger (SHA-256 Audit-Chain)</h3>
            <select id="tr-ledger-cat" class="px-2 py-1 rounded border border-[var(--border)] bg-[var(--page-bg)] text-xs">
              <option value="all">Alle Kategorien</option>
              ${CATEGORIES.map((c) => `<option value="${esc(c)}" ${_catFilter === c ? "selected" : ""}>${esc(c)}</option>`).join("")}
            </select>
          </div>
          <div class="space-y-1.5 max-h-[260px] overflow-y-auto">
            ${
              filteredTxs.length
                ? filteredTxs
                    .map(
                      (tx) => `
                    <div class="p-2 rounded-lg border border-[var(--border)] bg-[var(--page-bg)] flex flex-wrap items-center justify-between gap-2 text-xs">
                      <div class="min-w-0">
                        <div class="flex items-center gap-2">
                          <span class="font-mono font-bold ${tx.direction === "in" ? "text-emerald-400" : "text-rose-400"}">${tx.direction === "in" ? "+" : "-"}${Number(tx.amount).toFixed(2)} ${esc(tx.currency)}</span>
                          <span class="font-semibold truncate">${esc(tx.recipient || "—")}</span>
                          <span class="text-[10px] font-mono px-1.5 py-0.5 rounded border border-[var(--border)]">${esc(tx.category)}</span>
                          ${tx.passkey_verified ? '<span class="text-[10px] font-mono px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-300">Passkey</span>' : ""}
                        </div>
                        <div class="text-[10px] font-mono text-[var(--muted-foreground)] truncate">${esc(tx.purpose || "")} · Status: ${esc(tx.status)} · Hash: ${esc((tx.entry_hash || "").slice(0, 12))}</div>
                      </div>
                      <span class="text-[10px] font-mono text-[var(--muted-foreground)]">${esc((tx.created_at || "").replace("T", " ").slice(0, 19))}</span>
                    </div>`
                    )
                    .join("")
                : '<div class="text-xs text-[var(--muted-foreground)] py-3 text-center">Keine Transaktionen in dieser Kategorie.</div>'
            }
          </div>
        </section>
      </div>`;

    bindTreasuryEvents(mount);
  }

  function bindTreasuryEvents(mount) {
    const openSet = mount.querySelector("#tr-open-passkey-settings");
    if (openSet) {
      openSet.onclick = () => {
        if (typeof window.openSettingsModal === "function") window.openSettingsModal("users");
      };
    }

    const addAcc = mount.querySelector("#tr-acc-add");
    if (addAcc) {
      addAcc.onclick = async () => {
        const name = (mount.querySelector("#tr-acc-name")?.value || "").trim();
        if (!name) return alert("Bitte Kontoname eingeben.");
        try {
          await apiJson("/api/v2/treasury/accounts", {
            method: "POST",
            body: JSON.stringify({
              name,
              account_type: mount.querySelector("#tr-acc-type")?.value || "bank",
              currency: mount.querySelector("#tr-acc-cur")?.value || "EUR",
              balance: Number(mount.querySelector("#tr-acc-bal")?.value || 0),
              identifier: mount.querySelector("#tr-acc-id")?.value || "",
            }),
          });
          await window.loadTreasuryStudio();
        } catch (err) {
          alert(err.message);
        }
      };
    }

    mount.querySelectorAll("[data-acc-del]").forEach((b) => {
      b.onclick = async () => {
        if (!confirm("Konto/Wallet wirklich entfernen?")) return;
        try {
          await apiJson(`/api/v2/treasury/accounts/${encodeURIComponent(b.getAttribute("data-acc-del"))}`, { method: "DELETE" });
          await window.loadTreasuryStudio();
        } catch (err) {
          alert(err.message);
        }
      };
    });

    const txSub = mount.querySelector("#tr-tx-submit");
    if (txSub) {
      txSub.onclick = async () => {
        const account_id = mount.querySelector("#tr-tx-acc")?.value;
        const amount = Number(mount.querySelector("#tr-tx-amt")?.value || 0);
        if (!account_id || amount <= 0) return alert("Bitte Konto und gueltigen Betrag waehlen.");
        try {
          await apiJson("/api/v2/treasury/payments/request", {
            method: "POST",
            body: JSON.stringify({
              account_id,
              direction: mount.querySelector("#tr-tx-dir")?.value || "out",
              amount,
              category: mount.querySelector("#tr-tx-cat")?.value || "Sonstiges",
              recipient: mount.querySelector("#tr-tx-rec")?.value || "",
              purpose: mount.querySelector("#tr-tx-pur")?.value || "",
              is_agent_request: !!mount.querySelector("#tr-tx-agent")?.checked,
              requested_by: mount.querySelector("#tr-tx-agent")?.checked ? "agent:treasury_bot" : "user",
            }),
          });
          await window.loadTreasuryStudio();
        } catch (err) {
          alert(err.message);
        }
      };
    }

    mount.querySelectorAll("[data-pay-approve]").forEach((b) => {
      b.onclick = async () => {
        const txId = b.getAttribute("data-pay-approve");
        try {
          let passkeyProofToken = null;
          if (_overview?.passkey_payments_required && typeof window.requirePasskeyForHitl === "function") {
            const pkRes = await window.requirePasskeyForHitl("payments", "Zahlung freigeben");
            if (!pkRes || !pkRes.verified) return;
            passkeyProofToken = pkRes.proof_token || pkRes.proof?.proof_token || null;
          }
          await apiJson(`/api/v2/treasury/payments/${encodeURIComponent(txId)}/approve`, {
            method: "POST",
            body: JSON.stringify({ passkey_proof_token: passkeyProofToken }),
          });
          await window.loadTreasuryStudio();
        } catch (err) {
          alert(`Freigabe fehlgeschlagen: ${err.message}`);
        }
      };
    });

    mount.querySelectorAll("[data-pay-reject]").forEach((b) => {
      b.onclick = async () => {
        const txId = b.getAttribute("data-pay-reject");
        const reason = prompt("Begruendung fuer Ablehnung (optional):") || "Abgelehnt";
        try {
          await apiJson(`/api/v2/treasury/payments/${encodeURIComponent(txId)}/reject`, {
            method: "POST",
            body: JSON.stringify({ reason }),
          });
          await window.loadTreasuryStudio();
        } catch (err) {
          alert(err.message);
        }
      };
    });

    const catSel = mount.querySelector("#tr-ledger-cat");
    if (catSel) {
      catSel.onchange = () => {
        _catFilter = catSel.value;
        renderTreasury();
      };
    }
  }

  window.loadTreasuryStudio = async function () {
    ensureTreasuryTabButton();
    const mount = document.getElementById("finance-view-treasury");
    if (!mount) return;
    try {
      const data = await apiJson("/api/v2/treasury/overview");
      _overview = data;
      renderTreasury();
    } catch (err) {
      mount.innerHTML = `<div class="p-4 text-xs text-rose-400">Treasury konnte nicht geladen werden: ${esc(err.message)}</div>`;
    }
  };

  const _finObs = new MutationObserver(() => {
    if (document.getElementById("finance-subtab-btn-dunning") && !document.getElementById("finance-subtab-btn-treasury")) {
      ensureTreasuryTabButton();
    }
  });
  if (document.body) _finObs.observe(document.body, { childList: true, subtree: true });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", ensureTreasuryTabButton);
  } else {
    ensureTreasuryTabButton();
  }
})();
