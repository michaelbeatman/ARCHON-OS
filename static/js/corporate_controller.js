// Corporate Hub Client Logic (static/js/corporate_controller.js)
let currentCorpCompany = null;
let allCorpCompanies = [];

async function initCorporateView() {
  await loadCorporateCompanies();
  await renderTemplateLivePreview();
}

async function loadCorporateCompanies() {
  try {
    const res = await fetch("/api/corporate/companies");
    if (!res.ok) return;
    const data = await res.json();
    allCorpCompanies = data.companies || [];
    
    const select = document.getElementById("corp-company-select");
    if (select) {
      select.innerHTML = "";
      allCorpCompanies.forEach(c => {
        const opt = document.createElement("option");
        opt.value = c.id;
        opt.textContent = `${c.name} ${c.is_active ? '(Aktiv)' : ''}`;
        if (c.is_active) opt.selected = true;
        select.appendChild(opt);
      });
    }

    const active = allCorpCompanies.find(c => c.is_active) || allCorpCompanies[0];
    if (active) {
      await loadCompanyDetails(active.id);
    }
  } catch (e) {
    console.error("Error loading corporate companies:", e);
  }
}

async function loadCompanyDetails(companyId) {
  try {
    const res = await fetch(`/api/corporate/companies/${companyId}`);
    if (res.ok) {
      currentCorpCompany = await res.json();
    } else if (allCorpCompanies.length > 0) {
      currentCorpCompany = allCorpCompanies.find(c => c.id === companyId) || allCorpCompanies[0];
    }
    if (currentCorpCompany) {
      populateCompanyForm(currentCorpCompany);
      await renderTemplateLivePreview();
    }
  } catch (e) {
    console.error("Error loading company details:", e);
  }
}

function populateCompanyForm(c) {
  if (!c) return;
  const setVal = (id, v) => { const el = document.getElementById(id); if (el) el.value = v || ""; };
  setVal("corp-input-name", c.name);
  setVal("corp-input-legal", c.legal_form);
  setVal("corp-input-slogan", c.slogan);
  
  const addr = c.address || {};
  setVal("corp-input-street", addr.street || c.street);
  setVal("corp-input-zip", addr.postal_code || c.zip_code);
  setVal("corp-input-city", addr.city || c.city);
  setVal("corp-input-country", addr.country || c.country || "Deutschland");

  const cont = c.contact || {};
  setVal("corp-input-phone", cont.phone || c.phone);
  setVal("corp-input-email", cont.email || c.email);
  setVal("corp-input-web", cont.website || c.website);

  const reg = c.registry || {};
  setVal("corp-input-court", reg.court || c.register_court);
  setVal("corp-input-hrb", reg.number || c.register_number);
  setVal("corp-input-directors", reg.managing_directors || c.managing_director);

  const tax = c.tax || {};
  setVal("corp-input-vatid", tax.vat_id || c.vat_id);
  setVal("corp-input-taxnum", tax.tax_number || c.tax_number);
  const sb = document.getElementById("corp-check-smallbiz");
  if (sb) sb.checked = !!(tax.small_business ?? c.small_business_regulation);

  const bank = c.bank || {};
  setVal("corp-input-bankname", bank.bank_name || c.bank_name);
  setVal("corp-input-iban", bank.iban || c.iban);
  setVal("corp-input-bic", bank.bic || c.bic);

  const des = c.design || {};
  const pCol = des.primary_color || c.primary_color || "#4f46e5";
  const sCol = des.secondary_color || c.secondary_color || "#06b6d4";
  setVal("corp-input-primary", pCol);
  setVal("corp-picker-primary", pCol);
  setVal("corp-input-secondary", sCol);
  setVal("corp-picker-secondary", sCol);
  setVal("corp-input-logo", des.logo_url || c.logo_url || "/static/archon_os_logo.png");
  if (des.font_family || c.font_family) {
    setVal("corp-select-font", des.font_family || c.font_family);
  }
}

async function onCorporateCompanySelect(companyId) {
  await loadCompanyDetails(companyId);
  await fetch(`/api/corporate/companies/${companyId}/set-active`, { method: "POST" });
}

async function saveCorporateCompany() {
  const saveBtn = document.getElementById("btn-save-corporate");
  const origHtml = saveBtn ? saveBtn.innerHTML : "Speichern";
  if (saveBtn) saveBtn.innerHTML = `<span class="animate-spin">⏳</span> Speichern...`;

  const payload = {
    id: currentCorpCompany ? currentCorpCompany.id : undefined,
    name: document.getElementById("corp-input-name")?.value.trim() || "",
    legal_form: document.getElementById("corp-input-legal")?.value.trim() || "",
    slogan: document.getElementById("corp-input-slogan")?.value.trim() || "",
    address: {
      street: document.getElementById("corp-input-street")?.value.trim() || "",
      postal_code: document.getElementById("corp-input-zip")?.value.trim() || "",
      city: document.getElementById("corp-input-city")?.value.trim() || "",
      country: document.getElementById("corp-input-country")?.value.trim() || "Deutschland"
    },
    contact: {
      phone: document.getElementById("corp-input-phone")?.value.trim() || "",
      email: document.getElementById("corp-input-email")?.value.trim() || "",
      website: document.getElementById("corp-input-web")?.value.trim() || ""
    },
    registry: {
      court: document.getElementById("corp-input-court")?.value.trim() || "",
      number: document.getElementById("corp-input-hrb")?.value.trim() || "",
      managing_directors: document.getElementById("corp-input-directors")?.value.trim() || ""
    },
    tax: {
      vat_id: document.getElementById("corp-input-vatid")?.value.trim() || "",
      tax_number: document.getElementById("corp-input-taxnum")?.value.trim() || "",
      small_business: !!document.getElementById("corp-check-smallbiz")?.checked
    },
    bank: {
      bank_name: document.getElementById("corp-input-bankname")?.value.trim() || "",
      iban: document.getElementById("corp-input-iban")?.value.trim() || "",
      bic: document.getElementById("corp-input-bic")?.value.trim() || ""
    },
    design: {
      primary_color: document.getElementById("corp-input-primary")?.value.trim() || "#4f46e5",
      secondary_color: document.getElementById("corp-input-secondary")?.value.trim() || "#06b6d4",
      logo_url: document.getElementById("corp-input-logo")?.value.trim() || "",
      font_family: document.getElementById("corp-select-font")?.value || "Inter"
    }
  };

  try {
    const res = await fetch("/api/corporate/companies", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    if (res.ok) {
      const data = await res.json();
      currentCorpCompany = data.company;
      await loadCorporateCompanies();
      await renderTemplateLivePreview();
      if (saveBtn) {
        saveBtn.innerHTML = `✓ Gespeichert!`;
        setTimeout(() => { saveBtn.innerHTML = origHtml; }, 2000);
      }
    } else if (saveBtn) {
      saveBtn.innerHTML = `Fehler!`;
      setTimeout(() => { saveBtn.innerHTML = origHtml; }, 2000);
    }
  } catch (e) {
    console.error("Error saving corporate company:", e);
    if (saveBtn) saveBtn.innerHTML = origHtml;
  }
}

function switchCorporateSubTab(tab) {
  const masterView = document.getElementById("corp-subview-master");
  const tmplView = document.getElementById("corp-subview-templates");
  const btnMaster = document.getElementById("tab-btn-corp-master");
  const btnTmpl = document.getElementById("tab-btn-corp-templates");
  if (!masterView || !tmplView) return;

  if (tab === "master") {
    masterView.classList.remove("hidden");
    tmplView.classList.add("hidden");
    if (btnMaster) {
      btnMaster.classList.add("border-indigo-500", "text-indigo-600", "dark:text-indigo-400");
      btnMaster.classList.remove("border-transparent", "text-[var(--muted-foreground)]");
    }
    if (btnTmpl) {
      btnTmpl.classList.remove("border-indigo-500", "text-indigo-600", "dark:text-indigo-400");
      btnTmpl.classList.add("border-transparent", "text-[var(--muted-foreground)]");
    }
  } else {
    masterView.classList.add("hidden");
    tmplView.classList.remove("hidden");
    if (btnTmpl) {
      btnTmpl.classList.add("border-indigo-500", "text-indigo-600", "dark:text-indigo-400");
      btnTmpl.classList.remove("border-transparent", "text-[var(--muted-foreground)]");
    }
    if (btnMaster) {
      btnMaster.classList.remove("border-indigo-500", "text-indigo-600", "dark:text-indigo-400");
      btnMaster.classList.add("border-transparent", "text-[var(--muted-foreground)]");
    }
    renderTemplateLivePreview();
  }
  if (typeof lucide !== 'undefined') lucide.createIcons();
}

function onTemplateTypeChanged(val) {
  const ctrlLetter = document.getElementById("tmpl-controls-letter");
  const ctrlInv = document.getElementById("tmpl-controls-invoice");
  if (val === "invoice") {
    if (ctrlLetter) ctrlLetter.classList.add("hidden");
    if (ctrlInv) ctrlInv.classList.remove("hidden");
  } else {
    if (ctrlLetter) ctrlLetter.classList.remove("hidden");
    if (ctrlInv) ctrlInv.classList.add("hidden");
  }
  renderTemplateLivePreview();
}

function buildFallbackTemplateHtml(type, c, custom) {
  const name = c?.name || "Archon Systems GmbH";
  const street = c?.address?.street || c?.street || "Innovationsallee 42";
  const city = `${c?.address?.postal_code || c?.zip_code || "48143"} ${c?.address?.city || c?.city || "Münster"}`;
  const vatId = c?.tax?.vat_id || c?.vat_id || "DE348192045";
  const hrb = c?.registry?.number || c?.register_number || "HRB 24680";
  const court = c?.registry?.court || c?.register_court || "Amtsgericht Münster";
  const iban = c?.bank?.iban || c?.iban || "DE89 4005 0150 0012 3456 78";
  const primary = c?.design?.primary_color || c?.primary_color || "#4f46e5";

  return `
    <div style="background:#ffffff;color:#0f172a;padding:42px 48px;border-radius:8px;box-shadow:0 10px 30px rgba(0,0,0,0.12);font-family:Inter,sans-serif;min-height:680px;display:flex;flex-direction:column;justify-content:space-between;">
      <div>
        <div style="display:flex;justify-content:space-between;align-items:flex-start;border-bottom:3px solid ${primary};padding-bottom:18px;margin-bottom:28px;">
          <div>
            <div style="font-size:20px;font-weight:800;letter-spacing:-0.02em;color:${primary};">${name}</div>
            <div style="font-size:11px;color:#64748b;margin-top:2px;">Autonomous Enterprise Operating System &amp; Consulting</div>
          </div>
          <div style="text-align:right;font-size:11px;color:#475569;line-height:1.5;">
            <div><strong>${name}</strong></div>
            <div>${street} · ${city}</div>
            <div>USt-IdNr.: ${vatId}</div>
          </div>
        </div>
        <div style="display:flex;justify-content:space-between;margin-bottom:32px;font-size:12px;">
          <div>
            <div style="font-size:9px;text-transform:uppercase;color:#94a3b8;text-decoration:underline;margin-bottom:6px;">${name} · ${street} · ${city}</div>
            <div style="font-weight:700;">${custom.recipient_name || "Mustermann Holding GmbH"}</div>
            <div>${custom.recipient_contact || "z. Hd. Geschäftsführung"}</div>
            <div>${custom.recipient_street || "Königsallee 100"}</div>
            <div>${custom.recipient_city || "40215 Düsseldorf"}</div>
          </div>
          <div style="text-align:right;font-size:11px;color:#475569;line-height:1.6;">
            <div><strong>Datum:</strong> 01.11.2026</div>
            <div><strong>Unser Zeichen:</strong> MK-2026-11</div>
            <div><strong>Ansprechpartner:</strong> Michael Keller</div>
          </div>
        </div>
        <div style="font-size:15px;font-weight:700;color:#0f172a;margin-bottom:16px;">
          ${custom.subject || "Projektvorschlag & Kooperationsrahmen Q4/2026 (DIN 5008 Vorlage)"}
        </div>
        <div style="font-size:12.5px;line-height:1.7;color:#334155;white-space:pre-line;">
${custom.body_text || "Sehr geehrte Damen und Herren,\n\nanbei übersenden wir Ihnen die abgestimmten Spezifikationen für die Einführung von Archon OS Enterprise inklusive revisionssicherer GoBD-Belegverarbeitung und Multi-Company-Mandantensteuerung.\n\nFür Rückfragen stehen wir Ihnen jederzeit gerne zur Verfügung.\n\nMit freundlichen Grüßen\n\nMichael Keller\nGeschäftsführer"}
        </div>
      </div>
      <div style="border-top:1px solid #e2e8f0;padding-top:14px;margin-top:40px;display:grid;grid-template-columns:repeat(3,1fr);gap:12px;font-size:9.5px;color:#64748b;">
        <div><strong>Gesellschaft:</strong><br>${name}<br>${street}, ${city}</div>
        <div><strong>Register &amp; Steuern:</strong><br>${court} · ${hrb}<br>USt-IdNr.: ${vatId}</div>
        <div><strong>Bankverbindung:</strong><br>IBAN: ${iban}<br>BIC: WELADED1MST</div>
      </div>
    </div>
  `;
}

async function renderTemplateLivePreview() {
  const container = document.getElementById("tmpl-preview-container");
  if (!container) return;

  const type = document.getElementById("tmpl-select-type")?.value || "letter";
  const custom = {
    recipient_name: document.getElementById("tmpl-input-rec-name")?.value || "",
    recipient_contact: document.getElementById("tmpl-input-rec-contact")?.value || "",
    recipient_street: document.getElementById("tmpl-input-rec-street")?.value || "",
    recipient_city: document.getElementById("tmpl-input-rec-city")?.value || "",
    subject: document.getElementById("tmpl-input-subject")?.value || "",
    body_text: document.getElementById("tmpl-input-body")?.value || "",
    invoice_num: document.getElementById("tmpl-input-inv-num")?.value || "RE-2026-001",
    due_date: document.getElementById("tmpl-input-inv-due")?.value || "14.11.2026"
  };

  try {
    const res = await fetch("/api/corporate/render-template", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        template_type: type,
        company_id: currentCorpCompany ? currentCorpCompany.id : undefined,
        custom: custom
      })
    });
    if (res.ok) {
      const data = await res.json();
      if (data && data.html) {
        container.innerHTML = data.html;
        return;
      }
    }
  } catch (e) {}
  container.innerHTML = buildFallbackTemplateHtml(type, currentCorpCompany, custom);
}

function printTemplatePreview() {
  const container = document.getElementById("tmpl-preview-container");
  if (!container) return;
  const printWindow = window.open("", "_blank");
  printWindow.document.write(`
    <html>
      <head>
        <title>Ausdruck - Vorlage</title>
        <style>
          @page { margin: 15mm; size: A4; }
          body { margin: 0; padding: 0; background: #fff; }
        </style>
      </head>
      <body>
        ${container.innerHTML}
        <script>
          window.onload = function() { window.print(); window.close(); }
        <\/script>
      </body>
    </html>
  `);
  printWindow.document.close();
}

function openNewCompanyModal() {
  const name = prompt("Name des neuen Unternehmens / der Tochtergesellschaft:");
  if (!name) return;
  const newComp = {
    name: name,
    legal_form: "GmbH",
    slogan: "",
    address: { street: "", postal_code: "", city: "", country: "Deutschland" },
    contact: { phone: "", email: "", website: "" },
    registry: { court: "", number: "", managing_directors: "" },
    tax: { vat_id: "", tax_number: "", small_business: false },
    bank: { bank_name: "", iban: "", bic: "" },
    design: { primary_color: "#2563eb", secondary_color: "#38bdf8", logo_url: "" }
  };
  fetch("/api/corporate/companies", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(newComp)
  }).then(r => r.json()).then(data => {
    if (data.company) {
      loadCorporateCompanies().then(() => {
        onCorporateCompanySelect(data.company.id);
      });
    }
  });
}

window.initCorporateView = initCorporateView;
window.loadCorporateCompanies = loadCorporateCompanies;
window.loadCompanyDetails = loadCompanyDetails;
window.onCorporateCompanySelect = onCorporateCompanySelect;
window.saveCorporateCompany = saveCorporateCompany;
window.switchCorporateSubTab = switchCorporateSubTab;
window.onTemplateTypeChanged = onTemplateTypeChanged;
window.renderTemplateLivePreview = renderTemplateLivePreview;
window.renderCorporateTemplatePreview = renderTemplateLivePreview;
window.printTemplatePreview = printTemplatePreview;
window.openNewCompanyModal = openNewCompanyModal;

const _origSetBoardroomTab = typeof window.setBoardroomTab === "function" ? window.setBoardroomTab : null;
window.setBoardroomTab = function(tab) {
  if (_origSetBoardroomTab && _origSetBoardroomTab !== window.setBoardroomTab) {
    try { _origSetBoardroomTab(tab); } catch (e) {}
  }
  const tabs = ["overview", "debate", "live"];
  const titles = {
    overview: ["Decision Engine · Übersicht", "Historie, frühere Debatten & strategische Konsens-Ergebnisse"],
    debate: ["Decision Engine · Debatte", "Methodik-Auswahl (55 Frameworks), Chairman & C-Suite Kader-Konfiguration"],
    live: ["Decision Engine · Live-Arena", "Echtzeit-Debatten-Streaming, Kontroverse & Synthese-Transkript"]
  };
  tabs.forEach(t => {
    const view = document.getElementById("boardroom-view-" + t);
    const btn = document.getElementById("boardroom-subtab-" + t);
    if (view) {
      if (t === tab) view.classList.remove("hidden");
      else view.classList.add("hidden");
    }
    if (btn) {
      const wrap = btn.querySelector(".tile-icon-wrap");
      const lbl = btn.querySelector(".boardroom-tab-label");
      if (t === tab) {
        btn.classList.add("active-cadre-tab", "opacity-100");
        btn.classList.remove("opacity-80");
        if (wrap) wrap.classList.add("active-tile");
        if (lbl) { lbl.classList.add("text-red-600", "font-bold"); lbl.classList.remove("text-[var(--muted-foreground)]", "font-medium"); }
      } else {
        btn.classList.remove("active-cadre-tab", "opacity-100");
        btn.classList.add("opacity-80");
        if (wrap) wrap.classList.remove("active-tile");
        if (lbl) { lbl.classList.remove("text-red-600", "font-bold"); lbl.classList.add("text-[var(--muted-foreground)]", "font-medium"); }
      }
    }
  });
  const tEl = document.getElementById("boardroom-main-title");
  const sEl = document.getElementById("boardroom-main-subtitle");
  if (tEl && titles[tab]) tEl.textContent = titles[tab][0];
  if (sEl && titles[tab]) sEl.textContent = titles[tab][1];
};

const _origSetSettingsTab = typeof window.setSettingsTab === "function" ? window.setSettingsTab : null;
window.setSettingsTab = function(tab) {
  if (_origSetSettingsTab && _origSetSettingsTab !== window.setSettingsTab) {
    try { _origSetSettingsTab(tab); } catch (e) {}
  }
  const allTabs = ["kernel", "autonomy", "services", "routing", "keys", "frameworks", "plugins", "comm", "design", "update"];
  allTabs.forEach(t => {
    const panel = document.getElementById("settings-tab-" + t);
    const btn = document.getElementById("btn-tab-" + t);
    if (panel) {
      if (t === tab) panel.classList.remove("hidden");
      else panel.classList.add("hidden");
    }
    if (btn) {
      if (t === tab) {
        btn.classList.add("font-bold", "text-[var(--foreground)]");
        btn.classList.remove("font-normal", "text-[var(--muted-foreground)]");
        btn.style.borderColor = "var(--border)";
        btn.style.backgroundColor = "var(--card)";
        btn.style.borderBottom = "1.5px solid var(--card)";
        btn.style.zIndex = "2";
      } else {
        btn.classList.remove("font-bold", "text-[var(--foreground)]");
        btn.classList.add("font-normal", "text-[var(--muted-foreground)]");
        btn.style.borderColor = "transparent";
        btn.style.backgroundColor = "transparent";
        btn.style.borderBottom = "";
        btn.style.zIndex = "1";
      }
    }
  });
};

