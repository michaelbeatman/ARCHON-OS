/**
 * static/erp_studio.js
 * Frontend-Controller für Säule 3: WIRTSCHAFT & ERP
 * - Adressen & CRM (`view-addresses`) mit 4 Top-Icon-Tabs (Alle, LinkedIn/Netz, Kunden, Lieferanten)
 * - Artikel & Leistungen (`view-items`) mit 4 Top-Icon-Tabs (Alle, Zeit/Service, SaaS/Abo, Produkte)
 * - Vorgänge & Verträge (`view-operations-erp`) mit 3 Top-Icon-Tabs (Angebote/AB, Pipeline, Verträge)
 * - Live-Integration mit Corporate Vorlagen-Studio (`view-corporate`) und Rechnungswesen (`view-finance`)
 */

(function () {
  let currentErpCompanyId = "archon-systems";
  let currentAddrRoleFilter = "all";
  let currentSelectedEntityId = null;
  let currentSelectedEntityDetail = null;
  let currentItemsTypeFilter = "all";
  let currentSelectedItemId = null;

  // Null-sicherer Feld-Setzer: die Legacy-IDs (erp-f-*, erp-flag-*, ...) existieren
  // in keinem aktiven View (Details am Legacy-Block unten bei createNewErpAddress).
  // Ohne ihn stirbt jeder Zugriff mit "Cannot set properties of null".
  const erpSetVal = (id, val) => {
    const el = document.getElementById(id);
    if (el) el.value = val !== undefined && val !== null ? val : "";
  };

  const INITIAL_ENTITIES = [
    {
      id: "ent-nordstern",
      entity_type: "organization",
      display_name: "Nordstern Digital AG",
      legal_form: "AG",
      is_customer: 1,
      is_supplier: 0,
      is_partner: 1,
      status: "active",
      debtor_no: "10001",
      creditor_no: "",
      vat_id: "DE298410552",
      tax_regime: "standard_19",
      payment_terms_days: 14,
      skonto_pct: 2.0,
      street: "Speicherstadt 18",
      postal_code: "20457",
      city: "Hamburg",
      country_code: "DE",
      billing_email: "rechnung@nordstern-digital.de",
      industry: "IT & Enterprise Cloud",
      rating: 5,
      dunning_block: 0,
      contacts_count: 2,
      interactions_count: 2,
      tags: ["Enterprise", "Key Account", "LinkedIn"],
      notes: "Strategischer Hauptkunde für autonome Agenten-Cluster.",
      primary_contact: {
        id: "cnt-nordstern-1",
        full_name: "Dr. Lukas Bergmann",
        role_title: "CTO & Vorstand Technik",
        email: "l.bergmann@nordstern-digital.de",
        phone_direct: "+49 40 319840-12",
        linkedin_url: "https://www.linkedin.com/in/lukas-bergmann-cto",
        connection_status: "Vernetzt",
        rating: 5,
        is_primary: 1,
        is_billing_recipient: 0
      },
      contacts: [
        {
          id: "cnt-nordstern-1",
          full_name: "Dr. Lukas Bergmann",
          role_title: "CTO & Vorstand Technik",
          email: "l.bergmann@nordstern-digital.de",
          phone_direct: "+49 40 319840-12",
          linkedin_url: "https://www.linkedin.com/in/lukas-bergmann-cto",
          connection_status: "Vernetzt",
          rating: 5,
          is_primary: 1,
          is_billing_recipient: 0
        },
        {
          id: "cnt-nordstern-2",
          full_name: "Sabine Krämer",
          role_title: "Head of Procurement & Finance",
          email: "rechnung@nordstern-digital.de",
          phone_direct: "+49 40 319840-45",
          linkedin_url: "https://www.linkedin.com/in/sabine-kraemer-fin",
          connection_status: "Vernetzt",
          rating: 4,
          is_primary: 0,
          is_billing_recipient: 1
        }
      ],
      interactions: [
        {
          channel: "email_in",
          sender_name: "Dr. Lukas Bergmann",
          subject: "Freigabe Q4 Rollout Archon Enterprise Cluster",
          body_text: "Hallo Michael, wir haben das Budget für den Q4-Ausbau freigegeben. Bitte schicke uns das aktualisierte Angebot inkl. Setup-Pauschale.",
          occurred_at: "2026-11-01 09:15:00"
        },
        {
          channel: "linkedin",
          sender_name: "Dr. Lukas Bergmann",
          subject: "LinkedIn Nachricht: Boardroom-Demo",
          body_text: "Die Live-Demo der Multi-Agenten-Debatte im Vorstand war erstklassig.",
          occurred_at: "2026-10-28 16:40:00"
        }
      ]
    },
    {
      id: "ent-weber",
      entity_type: "organization",
      display_name: "Kanzlei Dr. Weber & Partner mbB",
      legal_form: "PartG mbB",
      is_customer: 1,
      is_supplier: 0,
      is_partner: 1,
      status: "active",
      debtor_no: "10002",
      creditor_no: "",
      vat_id: "DE310492811",
      tax_regime: "standard_19",
      payment_terms_days: 14,
      skonto_pct: 0.0,
      street: "Maximilianstr. 35",
      postal_code: "80539",
      city: "München",
      country_code: "DE",
      billing_email: "buchhaltung@weber-ip-law.de",
      industry: "Wirtschaftskanzlei / IP & AI-Recht",
      rating: 5,
      dunning_block: 1,
      contacts_count: 1,
      interactions_count: 1,
      tags: ["Kunde", "LegalTech", "LinkedIn"],
      notes: "Nutzt Archon OS für EU AI Act & DSGVO-Compliance-Audits.",
      primary_contact: {
        id: "cnt-weber-1",
        full_name: "RA Dr. Henrik Weber, LL.M.",
        role_title: "Managing Partner",
        email: "h.weber@weber-ip-law.de",
        phone_direct: "+49 89 210948-0",
        linkedin_url: "https://www.linkedin.com/in/henrik-weber-llm",
        connection_status: "Vernetzt",
        rating: 5,
        is_primary: 1,
        is_billing_recipient: 1
      },
      contacts: [
        {
          id: "cnt-weber-1",
          full_name: "RA Dr. Henrik Weber, LL.M.",
          role_title: "Managing Partner",
          email: "h.weber@weber-ip-law.de",
          phone_direct: "+49 89 210948-0",
          linkedin_url: "https://www.linkedin.com/in/henrik-weber-llm",
          connection_status: "Vernetzt",
          rating: 5,
          is_primary: 1,
          is_billing_recipient: 1
        }
      ],
      interactions: [
        {
          channel: "call",
          sender_name: "RA Dr. Henrik Weber, LL.M.",
          subject: "Abstimmung Mandanten-Trennung & On-Premise Appliance",
          body_text: "Wünscht Angebot über eine dedizierte Archon Edge AI Appliance für streng vertrauliche Mandatsakten.",
          occurred_at: "2026-10-30 14:20:00"
        }
      ]
    },
    {
      id: "ent-hetzner",
      entity_type: "organization",
      display_name: "Hetzner Cloud Infrastructure GmbH",
      legal_form: "GmbH",
      is_customer: 0,
      is_supplier: 1,
      is_partner: 0,
      status: "active",
      debtor_no: "",
      creditor_no: "70001",
      vat_id: "DE812871812",
      tax_regime: "standard_19",
      payment_terms_days: 14,
      street: "Industriestr. 25",
      postal_code: "91710",
      city: "Gunzenhausen",
      country_code: "DE",
      billing_email: "billing@hetzner.com",
      iban: "DE71 7604 0061 0123 4567 00",
      bank_name: "Commerzbank Nürnberg",
      industry: "Cloud & Rechenzentrum",
      rating: 5,
      dunning_block: 0,
      contacts_count: 1,
      interactions_count: 1,
      tags: ["Lieferant", "Server", "GPU-Cluster"],
      notes: "Primärer Infrastruktur-Lieferant für Archon Dedicated Nodes.",
      primary_contact: {
        id: "cnt-hetzner-1",
        full_name: "Key Account Team Cloud",
        role_title: "Dedicated Server Support",
        email: "billing@hetzner.com",
        connection_status: "Geschäftskontakt",
        rating: 5,
        is_primary: 1
      },
      contacts: [
        {
          id: "cnt-hetzner-1",
          full_name: "Key Account Team Cloud",
          role_title: "Dedicated Server Support",
          email: "billing@hetzner.com",
          connection_status: "Geschäftskontakt",
          rating: 5,
          is_primary: 1
        }
      ],
      interactions: [
        {
          channel: "email_in",
          sender_name: "Hetzner Billing",
          subject: "Monatsabrechnung Dedicated GPU Nodes Oktober",
          body_text: "Eingangsrechnung über 145,00 EUR netto automatisch via OCR verbucht.",
          occurred_at: "2026-10-31 08:00:00"
        }
      ]
    },
    {
      id: "ent-alpencloud",
      entity_type: "organization",
      display_name: "AlpenCloud Swiss Systems AG",
      legal_form: "AG",
      is_customer: 0,
      is_supplier: 1,
      is_partner: 0,
      status: "active",
      debtor_no: "",
      creditor_no: "70002",
      vat_id: "CHE-114.829.301",
      tax_regime: "reverse_charge",
      payment_terms_days: 30,
      street: "Bahnhofstrasse 102",
      postal_code: "8001",
      city: "Zürich",
      country_code: "CH",
      billing_email: "invoices@alpencloud.ch",
      iban: "CH93 0076 2011 6238 5295 7",
      bank_name: "Zürcher Kantonalbank",
      industry: "Hardware & Edge AI Server",
      rating: 4,
      dunning_block: 0,
      contacts_count: 1,
      interactions_count: 1,
      tags: ["Lieferant", "Hardware", "Schweiz"],
      notes: "Hardware-Distributor für vorkonfigurierte Archon Edge AI Appliances.",
      primary_contact: {
        id: "cnt-alpen-1",
        full_name: "Marc Brunner",
        role_title: "Head of Enterprise Hardware",
        email: "m.brunner@alpencloud.ch",
        phone_direct: "+41 44 580 12 90",
        connection_status: "Vernetzt",
        rating: 4,
        is_primary: 1
      },
      contacts: [
        {
          id: "cnt-alpen-1",
          full_name: "Marc Brunner",
          role_title: "Head of Enterprise Hardware",
          email: "m.brunner@alpencloud.ch",
          phone_direct: "+41 44 580 12 90",
          connection_status: "Vernetzt",
          rating: 4,
          is_primary: 1
        }
      ],
      interactions: [
        {
          channel: "note",
          sender_name: "Marc Brunner",
          subject: "Lieferzeit Edge AI Appliances Q4",
          body_text: "4 Geräte ab Lager Zürich sofort verfügbar (EK 2.150 EUR netto).",
          occurred_at: "2026-10-29 11:30:00"
        }
      ]
    },
    {
      id: "ent-velox",
      entity_type: "organization",
      display_name: "Velox MedTech Solutions GmbH",
      legal_form: "GmbH",
      is_customer: 0,
      is_supplier: 0,
      is_partner: 1,
      status: "lead",
      debtor_no: "",
      creditor_no: "",
      street: "Sendlinger Str. 44",
      postal_code: "80331",
      city: "München",
      country_code: "DE",
      industry: "Medizintechnik / ISO 13485",
      rating: 4,
      dunning_block: 0,
      contacts_count: 1,
      interactions_count: 1,
      tags: ["LinkedIn Lead", "AI Act", "MedTech"],
      notes: "Interesse an Archon Compliance-Modul (ISO 13485 & EU AI Act).",
      primary_contact: {
        id: "cnt-velox-1",
        full_name: "Lena Vogel",
        role_title: "VP Regulatory & Quality",
        email: "l.vogel@velox-medtech.de",
        phone_direct: "+49 89 452190-10",
        linkedin_url: "https://www.linkedin.com/in/lena-vogel-qms",
        connection_status: "Vernetzt",
        rating: 4,
        is_primary: 1
      },
      contacts: [
        {
          id: "cnt-velox-1",
          full_name: "Lena Vogel",
          role_title: "VP Regulatory & Quality",
          email: "l.vogel@velox-medtech.de",
          phone_direct: "+49 89 452190-10",
          linkedin_url: "https://www.linkedin.com/in/lena-vogel-qms",
          connection_status: "Vernetzt",
          rating: 4,
          is_primary: 1
        }
      ],
      interactions: [
        {
          channel: "linkedin",
          sender_name: "Lena Vogel",
          subject: "LinkedIn Follow-up: Automatisierte ISO 13485 & AI Act Audits",
          body_text: "Hallo Michael, vielen Dank für die Vernetzung! Lass uns nächste Woche über das regulatorische Dossier-Modul sprechen.",
          occurred_at: "2026-11-01 10:05:00"
        }
      ]
    }
  ];

  const INITIAL_ITEMS = [
    {
      id: "itm-01",
      item_no: "ART-1001",
      item_type: "saas",
      title: "Archon OS Enterprise Node (Monatslizenz)",
      description: "Dedizierter Agentic-OS-Cluster inkl. 57 Expertenprofilen, OmniRoute-Gateway & Security-Guard.",
      category: "SaaS & Lizenzen",
      unit: "Monat",
      billing_interval: "monthly",
      sales_price_net: 890.0,
      purchase_price_net: 145.0,
      tax_rate_pct: 19.0,
      margin_eur: 745.0,
      margin_pct: 83.7,
      track_inventory: 0,
      stock_qty: 0,
      supplier_entity_id: "ent-hetzner",
      supplier_name: "Hetzner Cloud Infrastructure GmbH"
    },
    {
      id: "itm-02",
      item_no: "ART-1002",
      item_type: "flat_rate",
      title: "Onboarding & Custom RAG-Vault Integration",
      description: "Schlüsselfertige Einrichtung des Mandanten-Wissensspeichers, DSGVO-Rollenkonzept und Team-Einweisung.",
      category: "Implementierung",
      unit: "Pauschal",
      billing_interval: "one_off",
      sales_price_net: 2400.0,
      purchase_price_net: 400.0,
      tax_rate_pct: 19.0,
      margin_eur: 2000.0,
      margin_pct: 83.3,
      track_inventory: 0,
      stock_qty: 0
    },
    {
      id: "itm-03",
      item_no: "ART-1003",
      item_type: "service",
      title: "Senior AI Solution Architect (Tagessatz)",
      description: "Architekturberatung, Prompt-Engineering nach ASD-STE100 und Custom-Skill-Entwicklung.",
      category: "Consulting",
      unit: "Tag",
      billing_interval: "one_off",
      sales_price_net: 1450.0,
      purchase_price_net: 0.0,
      tax_rate_pct: 19.0,
      margin_eur: 1450.0,
      margin_pct: 100.0,
      track_inventory: 0,
      stock_qty: 0
    },
    {
      id: "itm-04",
      item_no: "ART-1004",
      item_type: "product",
      title: "Archon Edge AI Appliance (Local Inference Box)",
      description: "Vorkonfigurierter Edge-Server (64 GB Unified Memory, NVMe RAID) für 100% lokale Air-Gapped LLMs.",
      category: "IT-Hardware",
      unit: "Stk.",
      billing_interval: "one_off",
      sales_price_net: 3490.0,
      purchase_price_net: 2150.0,
      tax_rate_pct: 19.0,
      margin_eur: 1340.0,
      margin_pct: 38.4,
      track_inventory: 1,
      stock_qty: 4,
      supplier_entity_id: "ent-alpencloud",
      supplier_name: "AlpenCloud Swiss Systems AG"
    },
    {
      id: "itm-05",
      item_no: "ART-1005",
      item_type: "saas",
      title: "Archon Compliance & EU AI-Act Shield (Abo)",
      description: "Laufende regulatorische Überwachung, Audit-Trail-Zertifizierung und ISO-13485/27001 Dossier-Generator.",
      category: "SaaS & Compliance",
      unit: "Monat",
      billing_interval: "monthly",
      sales_price_net: 490.0,
      purchase_price_net: 45.0,
      tax_rate_pct: 19.0,
      margin_eur: 445.0,
      margin_pct: 90.8,
      track_inventory: 0,
      stock_qty: 0
    }
  ];

  const INITIAL_OFFERS = [
    {
      id: "doc-offer-01",
      doc_type: "offer",
      doc_number: "ANG-2026-0001",
      status: "sent",
      entity_id: "ent-nordstern",
      entity_name: "Nordstern Digital AG",
      issue_date: "2026-11-01",
      due_date: "2026-11-15",
      amount_net: 3290.0,
      tax_amount: 625.1,
      amount_gross: 3915.1,
      currency: "EUR",
      lines: [
        { item_id: "itm-01", title: "Archon OS Enterprise Node (Monatslizenz)", quantity: 1 },
        { item_id: "itm-02", title: "Onboarding & Custom RAG-Vault Integration", quantity: 1 }
      ]
    },
    {
      id: "doc-inv-01",
      doc_type: "invoice",
      doc_number: "RE-2026-0001",
      status: "booked",
      entity_id: "ent-nordstern",
      entity_name: "Nordstern Digital AG",
      issue_date: "2026-11-01",
      due_date: "2026-11-15",
      amount_net: 1450.0,
      tax_amount: 275.5,
      amount_gross: 1725.5,
      currency: "EUR",
      lines: [{ item_id: "itm-03", title: "Senior AI Solution Architect (Tagessatz)", quantity: 1 }]
    }
  ];

  // Master-Speicher im Client (wird mit Backend & LocalStorage pro Mandant synchronisiert)
  let allEntities = JSON.parse(JSON.stringify(INITIAL_ENTITIES));
  let cachedEntities = [];
  let allItems = JSON.parse(JSON.stringify(INITIAL_ITEMS));
  let cachedItems = [];
  let cachedOffers = JSON.parse(JSON.stringify(INITIAL_OFFERS));

  function getActiveCompanyId() {
    const sel = document.getElementById("corp-company-select");
    if (sel && sel.value) {
      currentErpCompanyId = sel.value;
    }
    return currentErpCompanyId || "archon-systems";
  }

  function loadTenantLocalState(cid) {
    try {
      const raw = localStorage.getItem(`archon_erp_state_v2_${cid}`);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed.entities) && parsed.entities.length) allEntities = parsed.entities;
        if (Array.isArray(parsed.items) && parsed.items.length) allItems = parsed.items;
        if (Array.isArray(parsed.offers) && parsed.offers.length) cachedOffers = parsed.offers;
        return;
      }
    } catch (e) {
      console.warn("[ERP] LocalStorage read warning:", e);
    }
    if (cid === "archon-systems") {
      allEntities = JSON.parse(JSON.stringify(INITIAL_ENTITIES));
      allItems = JSON.parse(JSON.stringify(INITIAL_ITEMS));
      cachedOffers = JSON.parse(JSON.stringify(INITIAL_OFFERS));
    } else {
      allEntities = [];
      allItems = [];
      cachedOffers = [];
    }
  }

  function saveTenantLocalState(cid) {
    try {
      localStorage.setItem(
        `archon_erp_state_v2_${cid}`,
        JSON.stringify({
          entities: allEntities,
          items: allItems,
          offers: cachedOffers
        })
      );
    } catch (e) {
      console.warn("[ERP] LocalStorage write warning:", e);
    }
  }

  function renderStars(rating) {
    const r = Math.max(0, Math.min(5, parseInt(rating || 0, 10)));
    return "★".repeat(r) + "☆".repeat(5 - r);
  }

  // Metadaten für die 4 Top-Icon-Tabs in Adressen & CRM
  const ADDRESS_TAB_META = {
    all: {
      title: "Adressen & CRM — Gesamtübersicht",
      subtitle: "Alle Geschäftspartner, LinkedIn-Kontakte (0–5★), Debitoren (10000+) & Kreditoren (70000+) in isolierter Mandanten-DB",
      bannerLabel: "Ansicht: Alle Adressen & Kontakte",
      bannerClass: "px-2.5 py-1.5 rounded-xl bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-between gap-2 text-[11px] font-mono shrink-0",
      labelColor: "font-bold text-indigo-600 dark:text-indigo-400",
      defaultDetailTab: "timeline"
    },
    network: {
      title: "Adressen & CRM — LinkedIn & Netzwerk",
      subtitle: "Persönliche Netzwerk-Kontakte, Leads, Beziehungs-Scoring (0–5★) & direkte Kommunikations-Timeline",
      bannerLabel: "Ansicht: LinkedIn & Netzwerk-Kontakte",
      bannerClass: "px-2.5 py-1.5 rounded-xl bg-sky-500/10 border border-sky-500/25 flex items-center justify-between gap-2 text-[11px] font-mono shrink-0",
      labelColor: "font-bold text-sky-600 dark:text-sky-400",
      defaultDetailTab: "timeline"
    },
    customers: {
      title: "Adressen & CRM — Kundenstamm (Debitoren 10000+)",
      subtitle: "Aktive Rechnungsempfänger im DATEV-Nummernkreis 10000+, USt-IdNr., Zahlungsziele, Skonto & Kunden-Belege",
      bannerLabel: "Ansicht: Kundenstamm (Debitoren 10000+)",
      bannerClass: "px-2.5 py-1.5 rounded-xl bg-emerald-500/10 border border-emerald-500/25 flex items-center justify-between gap-2 text-[11px] font-mono shrink-0",
      labelColor: "font-bold text-emerald-600 dark:text-emerald-400",
      defaultDetailTab: "bwl"
    },
    suppliers: {
      title: "Adressen & CRM — Lieferantenstamm (Kreditoren 70000+)",
      subtitle: "Lieferanten, Rechenzentren & Dienstleister im DATEV-Nummernkreis 70000+, IBAN/Bankdaten & Einkaufskonditionen",
      bannerLabel: "Ansicht: Lieferantenstamm (Kreditoren 70000+)",
      bannerClass: "px-2.5 py-1.5 rounded-xl bg-amber-500/10 border border-amber-500/25 flex items-center justify-between gap-2 text-[11px] font-mono shrink-0",
      labelColor: "font-bold text-amber-600 dark:text-amber-400",
      defaultDetailTab: "bwl"
    }
  };

  // Metadaten für die 4 Top-Icon-Tabs in Artikel & Leistungen
  const ITEMS_TAB_META = {
    all: {
      title: "Artikel & Leistungen — Gesamtkatalog",
      subtitle: "Dienstleistungen, Pauschalen, SaaS-Lizenzen & Produkte inkl. VK/EK-Margenkalkulation und Lieferantenzuordnung",
      bannerLabel: "Kategorie: Gesamtkatalog (Alle Typen)",
      bannerClass: "px-2.5 py-1.5 rounded-xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-between gap-2 text-[11px] font-mono shrink-0",
      labelColor: "font-bold text-emerald-700 dark:text-emerald-400",
      defaultItemType: "service"
    },
    service: {
      title: "Artikel & Leistungen — Zeit & Consulting",
      subtitle: "Stundensätze, Tagessätze & Werkvertrags-Pauschalen für Beratung, Engineering, Audits und Onboarding",
      bannerLabel: "Kategorie: Zeit / Service & Pauschalen",
      bannerClass: "px-2.5 py-1.5 rounded-xl bg-indigo-500/10 border border-indigo-500/25 flex items-center justify-between gap-2 text-[11px] font-mono shrink-0",
      labelColor: "font-bold text-indigo-600 dark:text-indigo-400",
      defaultItemType: "service"
    },
    saas: {
      title: "Artikel & Leistungen — SaaS & Abonnements",
      subtitle: "Wiederkehrende Monats- und Jahreslizenzen (MRR / ARR), Managed Agent Nodes & Compliance-Abos",
      bannerLabel: "Kategorie: SaaS-Lizenzen & Wiederkehrende Abos",
      bannerClass: "px-2.5 py-1.5 rounded-xl bg-sky-500/10 border border-sky-500/25 flex items-center justify-between gap-2 text-[11px] font-mono shrink-0",
      labelColor: "font-bold text-sky-600 dark:text-sky-400",
      defaultItemType: "saas"
    },
    product: {
      title: "Artikel & Leistungen — Produkte & Hardware",
      subtitle: "Physische Produkte, vorkonfigurierte Edge-AI-Appliances & Lizenz-Bundles inkl. Lagerbestand",
      bannerLabel: "Kategorie: Physische Produkte & Hardware",
      bannerClass: "px-2.5 py-1.5 rounded-xl bg-amber-500/10 border border-amber-500/25 flex items-center justify-between gap-2 text-[11px] font-mono shrink-0",
      labelColor: "font-bold text-amber-600 dark:text-amber-400",
      defaultItemType: "product"
    }
  };

  // ===========================================================================
  // 1. ADRESSEN & CRM (view-addresses)
  // ===========================================================================

  window.initAddressesViewLegacy = async function () {
    const cid = getActiveCompanyId();
    loadTenantLocalState(cid);
    const badge = document.getElementById("erp-addr-tenant-badge");
    if (badge) badge.textContent = `Mandant: ${cid} (erp.db)`;
    await setAddressesRoleFilter(currentAddrRoleFilter || "all");
  };

  // Delegate initAddressesView directly to crmStudio
  window.initAddressesView = function() {
    if (window.crmStudio && typeof window.crmStudio.init === 'function') {
      window.crmStudio.init();
    }
  };

  function filterEntitiesClientSide(entities, roleFilter, searchQuery) {
    const q = (searchQuery || "").toLowerCase().trim();
    return (entities || []).filter((ent) => {
      if (roleFilter === "customers" && !ent.is_customer) return false;
      if (roleFilter === "suppliers" && !ent.is_supplier) return false;
      if (roleFilter === "network" && !ent.is_partner && (ent.is_customer || ent.is_supplier)) return false;

      if (!q) return true;
      const prim = ent.primary_contact || {};
      const hay = [
        ent.display_name,
        ent.legal_form,
        ent.city,
        ent.debtor_no,
        ent.creditor_no,
        ent.industry,
        prim.full_name,
        prim.email,
        prim.role_title,
        ...(ent.tags || [])
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return hay.includes(q);
    });
  }

  window.setAddressesRoleFilter = async function (role) {
    currentAddrRoleFilter = role || "all";
    const roles = ["all", "network", "customers", "suppliers"];
    roles.forEach((r) => {
      const btn = document.getElementById(`addr-subtab-btn-${r}`);
      if (!btn) return;
      const wrap = btn.querySelector(".tile-icon-wrap");
      const lbl = btn.querySelector(".addr-tab-label");
      if (r === currentAddrRoleFilter) {
        btn.className =
          "addr-header-tile active-cadre-tab flex flex-col items-center justify-between min-w-[56px] sm:min-w-[62px] h-[72px] py-1 px-0.5 bg-transparent border-0 shadow-none opacity-100 cursor-pointer select-none transition-transform hover:scale-105 duration-150";
        if (wrap) wrap.className = "tile-icon-wrap active-tile w-11 h-11 sm:w-12 sm:h-12 flex items-center justify-center mb-0.5";
        if (lbl) lbl.className = "addr-tab-label text-[10px] font-mono tracking-tight text-center whitespace-nowrap text-red-600 font-bold leading-none";
      } else {
        btn.className =
          "addr-header-tile flex flex-col items-center justify-between min-w-[56px] sm:min-w-[62px] h-[72px] py-1 px-0.5 bg-transparent border-0 shadow-none opacity-80 hover:opacity-100 cursor-pointer select-none transition-transform hover:scale-105 duration-150";
        if (wrap) wrap.className = "tile-icon-wrap w-11 h-11 sm:w-12 sm:h-12 flex items-center justify-center mb-0.5";
        if (lbl) lbl.className = "addr-tab-label text-[10px] font-mono tracking-tight text-center whitespace-nowrap text-[var(--muted-foreground)] font-medium leading-none";
      }
    });

    const meta = ADDRESS_TAB_META[currentAddrRoleFilter] || ADDRESS_TAB_META.all;
    const titleEl = document.getElementById("addresses-main-title");
    const subEl = document.getElementById("addresses-main-subtitle");
    if (titleEl) titleEl.textContent = meta.title;
    if (subEl) subEl.textContent = meta.subtitle;

    const bannerEl = document.getElementById("erp-addr-mode-banner");
    const bannerLbl = document.getElementById("erp-addr-mode-label");
    if (bannerEl) bannerEl.className = meta.bannerClass;
    if (bannerLbl) {
      bannerLbl.className = meta.labelColor;
      bannerLbl.textContent = meta.bannerLabel;
    }

    // Wechsle auch den rechten Detail-Reiter passend zum gewählten oberen Icon-Tab
    switchErpAddressDetailTab(meta.defaultDetailTab);

    await loadErpAddresses(true);
  };

  window.loadErpAddresses = async function (forceSelectFirst) {
    const cid = getActiveCompanyId();
    const qEl = document.getElementById("erp-addr-search");
    const search = qEl ? qEl.value.trim() : "";
    const container = document.getElementById("erp-addr-list-container");

    try {
      const resp = await fetch(`/api/erp/entities?company_id=${encodeURIComponent(cid)}&role=all`);
      if (resp.ok) {
        const data = await resp.json();
        if (Array.isArray(data.items) && data.items.length > 0) {
          allEntities = data.items;
          saveTenantLocalState(cid);
        }
      }
    } catch (e) {
      // Lokaler Fallback aktiv
    }

    cachedEntities = filterEntitiesClientSide(allEntities, currentAddrRoleFilter, search);

    const countBadge = document.getElementById("erp-addr-count-badge");
    if (countBadge) countBadge.textContent = `${cachedEntities.length} von ${allEntities.length} Adressen`;

    const bannerKpi = document.getElementById("erp-addr-mode-kpi");
    if (bannerKpi) {
      if (currentAddrRoleFilter === "customers") {
        bannerKpi.textContent = `${cachedEntities.length} Debitoren (10001+)`;
      } else if (currentAddrRoleFilter === "suppliers") {
        bannerKpi.textContent = `${cachedEntities.length} Kreditoren (70001+)`;
      } else if (currentAddrRoleFilter === "network") {
        bannerKpi.textContent = `${cachedEntities.length} LinkedIn-Profile / Leads`;
      } else {
        const custCount = allEntities.filter((e) => e.is_customer).length;
        const suppCount = allEntities.filter((e) => e.is_supplier).length;
        bannerKpi.textContent = `${custCount} Kunden · ${suppCount} Lieferanten`;
      }
    }

    if (!container) return;
    if (!cachedEntities.length) {
      container.innerHTML = `<div class="text-xs text-[var(--muted-foreground)] p-6 text-center border border-dashed border-[var(--border)] rounded-xl">Keine Adressen für den Filter "${currentAddrRoleFilter.toUpperCase()}" gefunden.</div>`;
      return;
    }

    // Falls der aktuell ausgewählte Kontakt nicht im neuen Filter enthalten ist (oder forceSelectFirst aktiv ist), wähle den ersten Eintrag des neuen Filters
    const stillInList = cachedEntities.some((x) => x.id === currentSelectedEntityId);
    if ((forceSelectFirst || !currentSelectedEntityId || !stillInList) && cachedEntities.length > 0) {
      currentSelectedEntityId = cachedEntities[0].id;
      await selectErpAddress(currentSelectedEntityId, true);
      return;
    }

    renderAddressesListHtml(container);
  };

  function renderAddressesListHtml(container) {
    if (!container) container = document.getElementById("erp-addr-list-container");
    if (!container) return;

    container.innerHTML = cachedEntities
      .map((ent) => {
        const isSel = ent.id === currentSelectedEntityId;
        const prim = ent.primary_contact || (ent.contacts && ent.contacts[0]) || {};
        const debBadge = ent.debtor_no
          ? `<span class="px-1.5 py-0.5 rounded text-[9.5px] font-mono font-bold bg-sky-500/10 text-sky-600 dark:text-sky-400 border border-sky-500/20">Debitor ${ent.debtor_no}</span>`
          : "";
        const credBadge = ent.creditor_no
          ? `<span class="px-1.5 py-0.5 rounded text-[9.5px] font-mono font-bold bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/20">Kreditor ${ent.creditor_no}</span>`
          : "";
        const dunningBadge = ent.dunning_block
          ? `<span class="px-1.5 py-0.5 rounded text-[9.5px] font-mono font-bold bg-rose-500/10 text-rose-600 border border-rose-500/20">Mahnstopp</span>`
          : "";

        return `
          <div onclick="selectErpAddress('${ent.id}')" class="p-3 rounded-xl border ${
            isSel
              ? "border-indigo-500 bg-indigo-500/10 shadow-xs"
              : "border-[var(--border)] bg-[var(--secondary)]/30 hover:bg-[var(--secondary)]/60"
          } transition cursor-pointer space-y-1.5">
            <div class="flex items-start justify-between gap-2">
              <div class="min-w-0">
                <div class="text-xs font-bold text-[var(--foreground)] truncate">${ent.display_name} ${
                  ent.legal_form ? `<span class="text-[10px] font-normal text-[var(--muted-foreground)]">(${ent.legal_form})</span>` : ""
                }</div>
                <div class="text-[11px] text-[var(--muted-foreground)] truncate">
                  ${prim.full_name ? `👤 ${prim.full_name} · ${prim.role_title || "Ansprechpartner"}` : ent.industry || "Organisation"}
                </div>
              </div>
              <span class="text-xs font-mono text-amber-500 shrink-0" title="Beziehungs-Score">${renderStars(ent.rating)}</span>
            </div>
            <div class="flex items-center justify-between gap-2 pt-1 flex-wrap">
              <div class="flex items-center gap-1 flex-wrap">
                ${debBadge}
                ${credBadge}
                ${dunningBadge}
                ${
                  !debBadge && !credBadge
                    ? `<span class="px-1.5 py-0.5 rounded text-[9.5px] font-mono bg-[var(--card)] text-sky-600 dark:text-sky-400 border border-sky-500/25">LinkedIn / Lead</span>`
                    : ""
                }
              </div>
              <div class="text-[10px] font-mono text-[var(--muted-foreground)]">
                ${ent.city || "DE"} · ${(ent.contacts && ent.contacts.length) || ent.contacts_count || 1} Pers. · ${(ent.interactions && ent.interactions.length) || ent.interactions_count || 1} Msg
              </div>
            </div>
          </div>
        `;
      })
      .join("");
  }

  window.selectErpAddress = async function (entityId, skipListRedraw) {
    currentSelectedEntityId = entityId;
    const cid = getActiveCompanyId();
    let loadedFromApi = false;
    try {
      const resp = await fetch(`/api/erp/entities/${encodeURIComponent(entityId)}?company_id=${encodeURIComponent(cid)}`);
      if (resp.ok) {
        const json = await resp.json();
        if (json && json.entity && json.entity.id) {
          currentSelectedEntityDetail = json;
          renderErpAddressDetail(currentSelectedEntityDetail);
          loadedFromApi = true;
        }
      }
    } catch (e) {
      // Fallback
    }
    if (!loadedFromApi) {
      const fallbackEnt = allEntities.find((x) => x.id === entityId) || cachedEntities.find((x) => x.id === entityId);
      if (fallbackEnt) {
        currentSelectedEntityDetail = {
          entity: fallbackEnt,
          contacts: fallbackEnt.contacts || (fallbackEnt.primary_contact ? [fallbackEnt.primary_contact] : []),
          interactions: fallbackEnt.interactions || [],
          documents: cachedOffers.filter((d) => d.entity_id === entityId)
        };
        renderErpAddressDetail(currentSelectedEntityDetail);
      }
    }
    renderAddressesListHtml();
  };

  function renderErpAddressDetail(detail) {
    if (!detail || !detail.entity) return;
    const e = detail.entity;
    const contacts = detail.contacts || [];
    const interactions = detail.interactions || [];
    const docs = detail.documents || [];

    const titleEl = document.getElementById("erp-detail-title");
    if (titleEl) titleEl.textContent = e.display_name || "Adresse";

    const subEl = document.getElementById("erp-detail-subtitle");
    if (subEl) {
      subEl.textContent = `${e.industry || "Geschäftspartner"} · ${e.postal_code || ""} ${e.city || ""} · Status: ${(e.status || "active").toUpperCase()}`;
    }

    const debBadge = document.getElementById("erp-detail-debtor-badge");
    if (debBadge) {
      if (e.debtor_no) {
        debBadge.textContent = `Debitor ${e.debtor_no}`;
        debBadge.classList.remove("hidden");
      } else {
        debBadge.classList.add("hidden");
      }
    }

    const credBadge = document.getElementById("erp-detail-creditor-badge");
    if (credBadge) {
      if (e.creditor_no) {
        credBadge.textContent = `Kreditor ${e.creditor_no}`;
        credBadge.classList.remove("hidden");
      } else {
        credBadge.classList.add("hidden");
      }
    }

    const chkCust = document.getElementById("erp-flag-customer");
    if (chkCust) chkCust.checked = !!e.is_customer;
    const chkSupp = document.getElementById("erp-flag-supplier");
    if (chkSupp) chkSupp.checked = !!e.is_supplier;

    const setVal = erpSetVal;  // identische Semantik wie oben, ein Helfer statt zwei
    setVal("erp-f-id", e.id);
    setVal("erp-f-display-name", e.display_name);
    setVal("erp-f-legal-form", e.legal_form);
    setVal("erp-f-debtor-no", e.debtor_no);
    setVal("erp-f-creditor-no", e.creditor_no);
    setVal("erp-f-rating", e.rating || 0);
    setVal("erp-f-street", e.street);
    setVal("erp-f-zip", e.postal_code);
    setVal("erp-f-city", e.city);
    setVal("erp-f-billing-email", e.billing_email);
    setVal("erp-f-vat-id", e.vat_id);
    setVal("erp-f-tax-regime", e.tax_regime || "standard_19");
    setVal("erp-f-pay-days", e.payment_terms_days || 14);
    setVal("erp-f-skonto", e.skonto_pct || 0);
    setVal("erp-f-iban", e.iban);
    setVal("erp-f-bank", e.bank_name);
    setVal("erp-f-tags", Array.isArray(e.tags) ? e.tags.join(", ") : e.tags || "");
    setVal("erp-f-industry", e.industry);
    setVal("erp-f-notes", e.notes);

    const chkDunning = document.getElementById("erp-f-dunning-block");
    if (chkDunning) chkDunning.checked = !!e.dunning_block;

    // 1:n Ansprechpartner rendern
    const cntList = document.getElementById("erp-contacts-list");
    if (cntList) {
      if (!contacts.length) {
        cntList.innerHTML = `<div class="text-xs text-[var(--muted-foreground)] italic">Noch kein Ansprechpartner hinterlegt.</div>`;
      } else {
        cntList.innerHTML = contacts
          .map(
            (c) => `
            <div class="p-2.5 rounded-lg bg-[var(--card)] border border-[var(--border)] flex items-center justify-between gap-2 text-xs">
              <div class="min-w-0">
                <div class="font-bold text-[var(--foreground)] flex items-center gap-1.5 flex-wrap">
                  <span>${c.full_name}</span>
                  ${c.is_primary ? `<span class="px-1.5 py-0.2 rounded text-[9px] font-mono bg-indigo-500/10 text-indigo-600">Hauptkontakt</span>` : ""}
                  ${c.is_billing_recipient ? `<span class="px-1.5 py-0.2 rounded text-[9px] font-mono bg-emerald-500/10 text-emerald-600">Rechnungsempfänger</span>` : ""}
                  <span class="text-[10px] font-mono text-amber-500">${renderStars(c.rating)}</span>
                </div>
                <div class="text-[11px] text-[var(--muted-foreground)] truncate">
                  ${c.role_title || "Rolle n.a."} · ${c.email || "keine E-Mail"} ${c.phone_direct ? `· 📞 ${c.phone_direct}` : ""}
                </div>
              </div>
              <div class="flex items-center gap-1.5 shrink-0">
                <span class="px-1.5 py-0.5 rounded text-[9.5px] font-mono bg-[var(--secondary)] text-[var(--muted-foreground)]">${c.connection_status || "Vernetzt"}</span>
                ${c.linkedin_url ? `<a href="${c.linkedin_url}" target="_blank" class="px-2 py-0.5 rounded bg-sky-500/10 text-sky-600 font-mono text-[10px] font-bold hover:underline">LinkedIn &nearr;</a>` : ""}
              </div>
            </div>
          `
          )
          .join("");
      }
    }

    // Timeline / Interaktionen rendern
    const intList = document.getElementById("erp-interactions-list");
    if (intList) {
      if (!interactions.length) {
        intList.innerHTML = `<div class="text-xs text-[var(--muted-foreground)] italic">Noch keine Nachrichten oder Gesprächsnotizen vorhanden.</div>`;
      } else {
        intList.innerHTML = interactions
          .map(
            (i) => `
            <div class="p-2.5 rounded-lg bg-[var(--card)] border border-[var(--border)] space-y-1 text-xs">
              <div class="flex items-center justify-between text-[10px] font-mono text-[var(--muted-foreground)]">
                <span class="font-bold text-indigo-500 uppercase">${i.channel} · ${i.sender_name || "Kontakt"}</span>
                <span>${i.occurred_at || ""}</span>
              </div>
              <div class="font-semibold text-[var(--foreground)]">${i.subject || ""}</div>
              <div class="text-[11.5px] text-[var(--muted-foreground)] whitespace-pre-line">${i.body_text || ""}</div>
            </div>
          `
          )
          .join("");
      }
    }

    // Verknüpfte Belege rendern
    const docsList = document.getElementById("erp-entity-docs-list");
    if (docsList) {
      if (!docs.length) {
        docsList.innerHTML = `<div class="text-xs text-[var(--muted-foreground)] p-4 border border-dashed border-[var(--border)] rounded-xl text-center">Noch keine Angebote oder Rechnungen für diese Adresse vorhanden.</div>`;
      } else {
        docsList.innerHTML = docs
          .map(
            (d) => `
            <div class="p-3 rounded-xl bg-[var(--secondary)]/40 border border-[var(--border)] flex items-center justify-between gap-2 text-xs">
              <div>
                <div class="font-bold text-[var(--foreground)]">${d.doc_number} <span class="text-[10px] font-mono uppercase px-1.5 py-0.5 rounded bg-indigo-500/10 text-indigo-600">${d.status}</span></div>
                <div class="text-[11px] text-[var(--muted-foreground)]">Datum: ${d.issue_date} · Fällig: ${d.due_date || "-"}</div>
              </div>
              <div class="flex items-center gap-2">
                <span class="font-mono font-bold text-sm text-[var(--foreground)]">${Number(d.amount_gross || 0).toFixed(2)} ${d.currency || "EUR"}</span>
                ${
                  d.doc_type === "offer" && d.status !== "accepted"
                    ? `<button type="button" onclick="convertErpDocToInvoice('${d.id}')" class="px-2.5 py-1 rounded-lg bg-emerald-600 text-white text-[11px] font-bold cursor-pointer">In Rechnung wandeln &rarr;</button>`
                    : ""
                }
              </div>
            </div>
          `
          )
          .join("");
      }
    }
  }

  window.switchErpAddressDetailTab = function (tab) {
    ["timeline", "bwl", "docs"].forEach((t) => {
      const v = document.getElementById(`erp-detail-view-${t}`);
      const b = document.getElementById(`erp-detail-tab-btn-${t}`);
      if (v) v.classList.toggle("hidden", t !== tab);
      if (b) {
        if (t === tab) {
          b.className = "px-3 py-1.5 rounded-lg text-xs font-bold bg-indigo-600 text-white transition cursor-pointer";
        } else {
          b.className = "px-3 py-1.5 rounded-lg text-xs font-semibold bg-[var(--secondary)] text-[var(--foreground)] hover:opacity-90 transition cursor-pointer";
        }
      }
    });
  };

  // LEGACY-ADRESSFORMULAR (Stand 2026-11-07 nachgeprueft): die IDs erp-f-*,
  // erp-flag-customer/-supplier, erp-contacts-list, erp-new-contact-form,
  // erp-interactions-list, erp-detail-* und erp-addr-list-container existieren in
  // KEINEM aktiven View (static/views/view_operations_erp.html hat 20 IDs, keine
  // davon aus dieser Familie; das aktive Adress-UI ist crmStudio in
  // views/view_addresses.html). "Neue Firma" hat deshalb keinen Button und ruft
  // diese Funktion nie auf. Die Felder werden NICHT ins View ergaenzt — das waere
  // ein Formular (Produktentscheidung), kein Bugfix. Die Zugriffe laufen ueber
  // den null-sicheren Helfer erpSetVal (oben definiert).
  window.createNewErpAddress = function () {
    currentSelectedEntityId = null;
    erpSetVal("erp-f-id", "");
    erpSetVal("erp-f-display-name", "Neue Firma / Kontakt");
    erpSetVal("erp-f-legal-form", "GmbH");
    erpSetVal("erp-f-debtor-no", "");
    erpSetVal("erp-f-creditor-no", "");
    erpSetVal("erp-f-street", "");
    erpSetVal("erp-f-zip", "");
    erpSetVal("erp-f-city", "");
    erpSetVal("erp-f-vat-id", "");
    erpSetVal("erp-f-notes", "");
    const chkCust = document.getElementById("erp-flag-customer");
    const chkSupp = document.getElementById("erp-flag-supplier");
    if (chkCust) chkCust.checked = currentAddrRoleFilter === "customers";
    if (chkSupp) chkSupp.checked = currentAddrRoleFilter === "suppliers";
    switchErpAddressDetailTab("bwl");
  };

  window.saveCurrentErpAddress = async function () {
    const cid = getActiveCompanyId();
    const isCustomer = document.getElementById("erp-flag-customer")?.checked ? 1 : 0;
    const isSupplier = document.getElementById("erp-flag-supplier")?.checked ? 1 : 0;
    let debtorNo = document.getElementById("erp-f-debtor-no")?.value.trim() || "";
    let creditorNo = document.getElementById("erp-f-creditor-no")?.value.trim() || "";

    if (isCustomer && !debtorNo) {
      const maxDeb = allEntities.reduce((m, e) => Math.max(m, parseInt(e.debtor_no || "10000", 10) || 10000), 10000);
      debtorNo = String(maxDeb + 1);
    }
    if (isSupplier && !creditorNo) {
      const maxCred = allEntities.reduce((m, e) => Math.max(m, parseInt(e.creditor_no || "70000", 10) || 70000), 70000);
      creditorNo = String(maxCred + 1);
    }

    const entId = document.getElementById("erp-f-id")?.value || currentSelectedEntityId || `ent-${Date.now()}`;
    const tagsRaw = document.getElementById("erp-f-tags")?.value || "";
    const tagsArr = tagsRaw
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);

    const payload = {
      company_id: cid,
      id: entId,
      display_name: document.getElementById("erp-f-display-name")?.value || "Neuer Geschäftspartner",
      legal_form: document.getElementById("erp-f-legal-form")?.value || "",
      is_customer: isCustomer,
      is_supplier: isSupplier,
      is_partner: !isCustomer && !isSupplier ? 1 : 0,
      debtor_no: debtorNo,
      creditor_no: creditorNo,
      rating: parseInt(document.getElementById("erp-f-rating")?.value || "4", 10),
      street: document.getElementById("erp-f-street")?.value || "",
      postal_code: document.getElementById("erp-f-zip")?.value || "",
      city: document.getElementById("erp-f-city")?.value || "",
      billing_email: document.getElementById("erp-f-billing-email")?.value || "",
      vat_id: document.getElementById("erp-f-vat-id")?.value || "",
      tax_regime: document.getElementById("erp-f-tax-regime")?.value || "standard_19",
      payment_terms_days: parseInt(document.getElementById("erp-f-pay-days")?.value || "14", 10),
      skonto_pct: parseFloat(document.getElementById("erp-f-skonto")?.value || "0"),
      iban: document.getElementById("erp-f-iban")?.value || "",
      bank_name: document.getElementById("erp-f-bank")?.value || "",
      dunning_block: document.getElementById("erp-f-dunning-block")?.checked ? 1 : 0,
      tags: tagsArr,
      industry: document.getElementById("erp-f-industry")?.value || "",
      notes: document.getElementById("erp-f-notes")?.value || ""
    };

    let savedViaApi = false;
    try {
      const resp = await fetch("/api/erp/entities", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (resp.ok) {
        const res = await resp.json();
        if (res.data && res.data.entity) {
          currentSelectedEntityId = res.data.entity.id;
          renderErpAddressDetail(res.data);
          savedViaApi = true;
        }
      }
    } catch (e) {
      // Lokale Speicherung
    }

    if (!savedViaApi) {
      const idx = allEntities.findIndex((x) => x.id === entId);
      if (idx >= 0) {
        allEntities[idx] = { ...allEntities[idx], ...payload };
      } else {
        allEntities.unshift({ ...payload, contacts: [], interactions: [] });
      }
      saveTenantLocalState(cid);
      currentSelectedEntityId = entId;
    }

    await loadErpAddresses(false);
    await selectErpAddress(currentSelectedEntityId, true);
    if (typeof window.showNotification === "function") {
      window.showNotification("Adresse gespeichert", `${payload.display_name} (${debtorNo ? "Debitor " + debtorNo : creditorNo ? "Kreditor " + creditorNo : "CRM"}) aktualisiert.`, "success");
    }
  };

  window.toggleNewContactInlineForm = function () {
    const f = document.getElementById("erp-new-contact-form");
    if (f) f.classList.toggle("hidden");
  };

  window.submitNewErpContact = async function () {
    if (!currentSelectedEntityId) return;
    const cid = getActiveCompanyId();
    const fullName = document.getElementById("erp-cnt-fullname")?.value.trim();
    if (!fullName) return;

    const newContact = {
      id: `cnt-${Date.now()}`,
      company_id: cid,
      entity_id: currentSelectedEntityId,
      full_name: fullName,
      role_title: document.getElementById("erp-cnt-role")?.value || "",
      email: document.getElementById("erp-cnt-email")?.value || "",
      phone_direct: document.getElementById("erp-cnt-phone")?.value || "",
      linkedin_url: document.getElementById("erp-cnt-linkedin")?.value || "",
      connection_status: "Vernetzt",
      rating: parseInt(document.getElementById("erp-cnt-rating")?.value || "4", 10),
      is_primary: 0
    };

    try {
      await fetch("/api/erp/contacts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(newContact)
      });
    } catch (e) {}

    const ent = allEntities.find((x) => x.id === currentSelectedEntityId);
    if (ent) {
      if (!Array.isArray(ent.contacts)) ent.contacts = ent.primary_contact ? [ent.primary_contact] : [];
      ent.contacts.push(newContact);
      ent.contacts_count = ent.contacts.length;
      if (!ent.primary_contact) ent.primary_contact = newContact;
      saveTenantLocalState(cid);
    }

    document.getElementById("erp-cnt-fullname").value = "";
    document.getElementById("erp-new-contact-form")?.classList.add("hidden");
    await selectErpAddress(currentSelectedEntityId);
  };

  window.addErpInteractionNote = async function () {
    if (!currentSelectedEntityId) return;
    const cid = getActiveCompanyId();
    const textEl = document.getElementById("erp-int-text");
    const bodyText = textEl ? textEl.value.trim() : "";
    if (!bodyText) return;
    const channel = document.getElementById("erp-int-channel")?.value || "note";
    const nowStr = new Date().toISOString().slice(0, 19).replace("T", " ");

    const newInt = {
      company_id: cid,
      entity_id: currentSelectedEntityId,
      channel: channel,
      sender_name: "Archon CRM",
      subject: `CRM-Eintrag (${channel.toUpperCase()})`,
      body_text: bodyText,
      occurred_at: nowStr
    };

    try {
      await fetch("/api/erp/interactions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(newInt)
      });
    } catch (e) {}

    const ent = allEntities.find((x) => x.id === currentSelectedEntityId);
    if (ent) {
      if (!Array.isArray(ent.interactions)) ent.interactions = [];
      ent.interactions.unshift(newInt);
      ent.interactions_count = ent.interactions.length;
      saveTenantLocalState(cid);
    }

    if (textEl) textEl.value = "";
    await selectErpAddress(currentSelectedEntityId);
  };

  window.syncErpWithPocketbase = async function () {
    const btn = document.getElementById("btn-erp-pb-sync");
    if (btn) btn.innerHTML = `<span>Synchronisiere...</span>`;
    try {
      const resp = await fetch("/api/erp/sync/pocketbase", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ company_id: getActiveCompanyId() })
      });
      const res = await resp.json();
      if (btn) {
        btn.innerHTML = `<i data-lucide="check-circle" class="w-3 h-3"></i><span>${res.status === "ok" ? "Sync OK" : "Lokal Autark"}</span>`;
      }
      await loadErpAddresses(false);
    } catch (e) {
      if (btn) btn.innerHTML = `<span>Lokal Autark (erp.db)</span>`;
    }
  };

  window.openAddressInCorporateStudio = function (templateType) {
    if (!currentSelectedEntityDetail || !currentSelectedEntityDetail.entity) return;
    const ent = currentSelectedEntityDetail.entity;
    const prim = (currentSelectedEntityDetail.contacts || [])[0] || {};
    setTab("corporate");
    setTimeout(() => {
      if (typeof switchCorporateSubTab === "function") switchCorporateSubTab("templates");
      const recName = document.getElementById("tmpl-input-rec-name");
      const recCont = document.getElementById("tmpl-input-rec-contact");
      const recStreet = document.getElementById("tmpl-input-rec-street");
      const recCity = document.getElementById("tmpl-input-rec-city");
      const typeSel = document.getElementById("tmpl-select-type");
      if (recName) recName.value = `${ent.display_name} ${ent.legal_form || ""}`.trim();
      if (recCont) recCont.value = prim.full_name ? `${prim.salutation || ""} ${prim.full_name}`.trim() : "Geschäftsführung";
      if (recStreet) recStreet.value = ent.street || "";
      if (recCity) recCity.value = `${ent.postal_code || ""} ${ent.city || ""}`.trim();
      if (typeSel && templateType) {
        typeSel.value = templateType;
        if (typeof onTemplateTypeChanged === "function") onTemplateTypeChanged(templateType);
      } else if (typeof renderTemplateLivePreview === "function") {
        renderTemplateLivePreview();
      }
    }, 150);
  };

  window.onCorporateCrmEntitySelected = async function (entityId) {
    if (!entityId) return;
    const ent = allEntities.find((x) => x.id === entityId);
    if (ent) {
      const prim = ent.primary_contact || (ent.contacts && ent.contacts[0]) || {};
      const recName = document.getElementById("tmpl-input-rec-name");
      const recCont = document.getElementById("tmpl-input-rec-contact");
      const recStreet = document.getElementById("tmpl-input-rec-street");
      const recCity = document.getElementById("tmpl-input-rec-city");
      if (recName) recName.value = ent.display_name || "";
      if (recCont) recCont.value = prim.full_name ? `${prim.salutation || ""} ${prim.full_name}`.trim() : "Geschäftsführung";
      if (recStreet) recStreet.value = ent.street || "";
      if (recCity) recCity.value = `${ent.postal_code || ""} ${ent.city || ""}`.trim();
      if (typeof renderTemplateLivePreview === "function") renderTemplateLivePreview();
    }
  };

  window.createOfferForCurrentAddress = function () {
    const eid = currentSelectedEntityId;
    setTab("operations-erp");
    setTimeout(() => {
      switchErpOpsSubTab("offers");
      const sel = document.getElementById("erp-doc-entity-select");
      if (sel && eid) sel.value = eid;
    }, 150);
  };

  // ===========================================================================
  // 2. ARTIKEL & LEISTUNGEN (view-items)
  // ===========================================================================

  window.initItemsView = async function () {
    const cid = getActiveCompanyId();
    loadTenantLocalState(cid);
    populateSupplierSelect();
    await setItemsTypeFilter(currentItemsTypeFilter || "all");
  };

  function populateSupplierSelect() {
    const sel = document.getElementById("erp-itm-supplier");
    if (!sel) return;
    const suppliers = allEntities.filter((e) => e.is_supplier);
    sel.innerHTML =
      `<option value="">-- Eigenleistung / Kein Lieferant --</option>` +
      suppliers
        .map((s) => `<option value="${s.id}">${s.display_name} (${s.creditor_no || "Kreditor"})</option>`)
        .join("");
  }

  function filterItemsClientSide(items, typeFilter, searchQuery) {
    const q = (searchQuery || "").toLowerCase().trim();
    return (items || []).filter((itm) => {
      if (typeFilter === "service" && itm.item_type !== "service" && itm.item_type !== "flat_rate") return false;
      if (typeFilter === "saas" && itm.item_type !== "saas") return false;
      if (typeFilter === "product" && itm.item_type !== "product") return false;

      if (!q) return true;
      const hay = [itm.item_no, itm.title, itm.description, itm.category, itm.supplier_name]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return hay.includes(q);
    });
  }

  window.setItemsTypeFilter = async function (type) {
    currentItemsTypeFilter = type || "all";
    ["all", "service", "saas", "product"].forEach((t) => {
      const btn = document.getElementById(`items-subtab-btn-${t}`);
      if (!btn) return;
      const wrap = btn.querySelector(".tile-icon-wrap");
      const lbl = btn.querySelector(".items-tab-label");
      if (t === currentItemsTypeFilter) {
        btn.className =
          "items-header-tile active-cadre-tab flex flex-col items-center justify-between min-w-[56px] sm:min-w-[62px] h-[72px] py-1 px-0.5 bg-transparent border-0 shadow-none opacity-100 cursor-pointer select-none transition-transform hover:scale-105 duration-150";
        if (wrap) wrap.className = "tile-icon-wrap active-tile w-11 h-11 sm:w-12 sm:h-12 flex items-center justify-center mb-0.5";
        if (lbl) lbl.className = "items-tab-label text-[10px] font-mono tracking-tight text-center whitespace-nowrap text-red-600 font-bold leading-none";
      } else {
        btn.className =
          "items-header-tile flex flex-col items-center justify-between min-w-[56px] sm:min-w-[62px] h-[72px] py-1 px-0.5 bg-transparent border-0 shadow-none opacity-80 hover:opacity-100 cursor-pointer select-none transition-transform hover:scale-105 duration-150";
        if (wrap) wrap.className = "tile-icon-wrap w-11 h-11 sm:w-12 sm:h-12 flex items-center justify-center mb-0.5";
        if (lbl) lbl.className = "items-tab-label text-[10px] font-mono tracking-tight text-center whitespace-nowrap text-[var(--muted-foreground)] font-medium leading-none";
      }
    });

    const meta = ITEMS_TAB_META[currentItemsTypeFilter] || ITEMS_TAB_META.all;
    const titleEl = document.getElementById("items-main-title");
    const subEl = document.getElementById("items-main-subtitle");
    if (titleEl) titleEl.textContent = meta.title;
    if (subEl) subEl.textContent = meta.subtitle;

    const bannerEl = document.getElementById("erp-items-mode-banner");
    const bannerLbl = document.getElementById("erp-items-mode-label");
    if (bannerEl) bannerEl.className = meta.bannerClass;
    if (bannerLbl) {
      bannerLbl.className = meta.labelColor;
      bannerLbl.textContent = meta.bannerLabel;
    }

    await loadErpItems(true);
  };

  window.loadErpItems = async function (forceSelectFirst) {
    const cid = getActiveCompanyId();
    const q = document.getElementById("erp-items-search")?.value.trim() || "";
    const container = document.getElementById("erp-items-list-container");

    try {
      const resp = await fetch(`/api/erp/items?company_id=${encodeURIComponent(cid)}&item_type=all`);
      if (resp.ok) {
        const data = await resp.json();
        if (Array.isArray(data.items) && data.items.length > 0) {
          allItems = data.items;
          saveTenantLocalState(cid);
        }
      }
    } catch (e) {
      // Lokaler Fallback aktiv
    }

    cachedItems = filterItemsClientSide(allItems, currentItemsTypeFilter, q);

    const badge = document.getElementById("erp-items-count-badge");
    if (badge) badge.textContent = `${cachedItems.length} von ${allItems.length} Artikeln`;

    const bannerKpi = document.getElementById("erp-items-mode-kpi");
    if (bannerKpi) {
      if (cachedItems.length > 0) {
        const avgMargin =
          cachedItems.reduce((acc, i) => acc + Number(i.margin_pct || 0), 0) / cachedItems.length;
        const sumVk = cachedItems.reduce((acc, i) => acc + Number(i.sales_price_net || 0), 0);
        bannerKpi.textContent = `${cachedItems.length} Positionen · Ø Marge ${avgMargin.toFixed(1)}% · Volumen ${sumVk.toFixed(2)} €`;
      } else {
        bannerKpi.textContent = `0 Positionen`;
      }
    }

    if (!container) return;
    if (!cachedItems.length) {
      container.innerHTML = `<div class="text-xs text-[var(--muted-foreground)] p-6 text-center border border-dashed border-[var(--border)] rounded-xl">Keine Artikel für den Filter "${currentItemsTypeFilter.toUpperCase()}" vorhanden.</div>`;
      return;
    }

    const stillInList = cachedItems.some((x) => x.id === currentSelectedItemId);
    if ((forceSelectFirst || !currentSelectedItemId || !stillInList) && cachedItems.length > 0) {
      currentSelectedItemId = cachedItems[0].id;
      selectErpItem(currentSelectedItemId);
      return;
    }

    renderItemsListHtml(container);
  };

  function renderItemsListHtml(container) {
    if (!container) container = document.getElementById("erp-items-list-container");
    if (!container) return;

    const typeBadges = {
      service: `<span class="px-1.5 py-0.5 rounded text-[9.5px] font-mono bg-indigo-500/10 text-indigo-600 dark:text-indigo-400 border border-indigo-500/20">Zeit/Service</span>`,
      flat_rate: `<span class="px-1.5 py-0.5 rounded text-[9.5px] font-mono bg-indigo-500/10 text-indigo-600 dark:text-indigo-400 border border-indigo-500/20">Pauschale</span>`,
      saas: `<span class="px-1.5 py-0.5 rounded text-[9.5px] font-mono bg-sky-500/10 text-sky-600 dark:text-sky-400 border border-sky-500/20">SaaS/Abo</span>`,
      product: `<span class="px-1.5 py-0.5 rounded text-[9.5px] font-mono bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/20">Produkt/HW</span>`
    };

    container.innerHTML = cachedItems
      .map((itm) => {
        const isSel = itm.id === currentSelectedItemId;
        const tBadge = typeBadges[itm.item_type] || "";
        return `
        <div onclick="selectErpItem('${itm.id}'); openErpItemDrawer('${itm.id}')" class="p-3 rounded-xl border ${
          isSel
            ? "border-emerald-500 bg-emerald-500/10 shadow-xs"
            : "border-[var(--border)] bg-[var(--secondary)]/30 hover:bg-[var(--secondary)]/60"
        } transition cursor-pointer flex items-center justify-between gap-3 group">
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-2 flex-wrap">
              <span class="px-1.5 py-0.5 rounded text-[10px] font-mono font-bold bg-[var(--card)] text-[var(--foreground)] border border-[var(--border)]">${itm.item_no}</span>
              ${tBadge}
              <span class="text-xs font-bold text-[var(--foreground)] truncate">${itm.title}</span>
              <span class="text-[10px] font-mono text-[var(--muted-foreground)]">(${itm.unit})</span>
            </div>
            <div class="text-[11px] text-[var(--muted-foreground)] truncate mt-0.5">${itm.description || itm.category}</div>
            <div class="flex items-center gap-3 mt-0.5 flex-wrap">
              ${itm.supplier_name ? `<span class="text-[10px] font-mono text-amber-600 dark:text-amber-400">Lieferant: ${itm.supplier_name}</span>` : ""}
              ${itm.track_inventory ? `<span class="text-[10px] font-mono text-sky-600 dark:text-sky-400">Lagerbestand: ${itm.stock_qty || 0} ${itm.unit}</span>` : ""}
            </div>
          </div>
          <div class="text-right shrink-0 flex flex-col items-end gap-0.5">
            <div class="text-xs font-mono font-black text-[var(--foreground)]">${Number(itm.sales_price_net).toFixed(2)} EUR <span class="text-[10px] font-normal text-[var(--muted-foreground)]">netto</span></div>
            <div class="text-[10px] font-mono text-emerald-600 dark:text-emerald-400 font-bold">Marge: +${Number(itm.margin_eur).toFixed(2)} € (${itm.margin_pct}%)</div>
            <span class="text-[10.5px] font-mono text-indigo-500 group-hover:underline font-semibold mt-0.5">Öffnen (VARIO) &rarr;</span>
          </div>
        </div>
      `;
      })
      .join("");
  }

  window.selectErpItem = function (itemId) {
    currentSelectedItemId = itemId;
    const itm = allItems.find((x) => x.id === itemId) || cachedItems.find((x) => x.id === itemId);
    if (!itm) return;
    document.getElementById("erp-itm-id").value = itm.id;
    document.getElementById("erp-itm-no").value = itm.item_no || "";
    document.getElementById("erp-itm-type").value = itm.item_type || "service";
    document.getElementById("erp-itm-title").value = itm.title || "";
    document.getElementById("erp-itm-desc").value = itm.description || "";
    document.getElementById("erp-itm-category").value = itm.category || "";
    document.getElementById("erp-itm-unit").value = itm.unit || "Std.";
    document.getElementById("erp-itm-interval").value = itm.billing_interval || "one_off";
    document.getElementById("erp-itm-vk").value = itm.sales_price_net || 0;
    document.getElementById("erp-itm-ek").value = itm.purchase_price_net || 0;
    document.getElementById("erp-itm-tax").value = String(itm.tax_rate_pct || 19.0);
    document.getElementById("erp-itm-supplier").value = itm.supplier_entity_id || "";
    document.getElementById("erp-itm-track-inv").checked = !!itm.track_inventory;
    document.getElementById("erp-itm-stock").value = itm.stock_qty || 0;
    updateLiveItemMargin();
    renderItemsListHtml();
  };

  window.createNewErpItem = function () {
    currentSelectedItemId = null;
    openErpItemDrawer(null);
  };

  window.openErpItemDrawer = function (itemId) {
    const drawer = document.getElementById("erp-item-drawer");
    if (!drawer) return;

    let itm = null;
    if (itemId) {
      itm = allItems.find((x) => x.id === itemId) || cachedItems.find((x) => x.id === itemId);
      currentSelectedItemId = itemId;
    } else {
      currentSelectedItemId = null;
    }

    // Default-Werte ermitteln
    const isNew = !itm;
    const itemNo = itm?.item_no || "";
    const itemType = itm?.item_type || (currentItemsTypeFilter !== "all" ? currentItemsTypeFilter : "service");
    const title = itm?.title || "";
    const desc = itm?.description || "";
    const category = itm?.category || (itemType === "saas" ? "SaaS Lizenzen" : itemType === "product" ? "Hardware" : "Consulting");
    const unit = itm?.unit || (itemType === "product" ? "Stk." : "Std.");
    const interval = itm?.billing_interval || (itemType === "saas" ? "monthly" : "one_off");
    const vk = itm?.sales_price_net != null ? Number(itm.sales_price_net) : (itemType === "service" ? 180.0 : 950.0);
    const ek = itm?.purchase_price_net != null ? Number(itm.purchase_price_net) : (itemType === "service" ? 45.0 : 150.0);
    const tax = String(itm?.tax_rate_pct != null ? itm.tax_rate_pct : "19.0");
    const trackInv = itm?.track_inventory ? 1 : (itemType === "product" ? 1 : 0);
    const stock = itm?.stock_qty || 0;
    const suppId = itm?.supplier_entity_id || "";

    // Header aktualisieren
    const titleEl = document.getElementById("erp-item-drawer-title");
    const noEl = document.getElementById("erp-item-drawer-no");
    const badgeEl = document.getElementById("erp-item-drawer-type-badge");
    const iconEl = document.getElementById("erp-item-drawer-icon");

    if (titleEl) titleEl.textContent = title || "Neuer Artikel / Neue Leistung";
    if (noEl) noEl.textContent = itemNo ? `Art-Nr: ${itemNo}` : "Neu (Automatische Nummerierung)";
    if (badgeEl) {
      const typeLabels = { service: "Zeit/Service", flat_rate: "Pauschale", saas: "SaaS/Abo", product: "Produkt/HW" };
      badgeEl.textContent = typeLabels[itemType] || itemType;
    }
    if (iconEl) {
      const typeIcons = { service: "💼", flat_rate: "📦", saas: "☁️", product: "🏷️" };
      iconEl.textContent = typeIcons[itemType] || "📦";
    }

    // Felder befüllen
    const setVal = (id, val) => {
      const el = document.getElementById(id);
      if (el) el.value = val != null ? val : "";
    };

    setVal("drw-itm-no", itemNo);
    setVal("drw-itm-type", itemType);
    setVal("drw-itm-ean", itm?.ean || "");
    setVal("drw-itm-title", title);
    setVal("drw-itm-category", category);
    setVal("drw-itm-desc", desc);
    setVal("drw-itm-unit", unit);
    setVal("drw-itm-interval", interval);
    setVal("drw-itm-vk", vk);
    setVal("drw-itm-ek", ek);
    setVal("drw-itm-tax", tax);
    setVal("drw-itm-account", itm?.account_no || (tax === "19.0" ? "8400 (SKR03)" : "8120 (SKR03)"));
    setVal("drw-itm-stock", stock);
    setVal("drw-itm-min-stock", itm?.min_stock_qty || 5);
    setVal("drw-itm-bin", itm?.warehouse_bin || "Regal A-04");
    setVal("drw-itm-seats", itm?.seats_limit || "");
    setVal("drw-itm-cancel-months", itm?.cancel_period_months || 3);
    setVal("drw-itm-seniority", itm?.seniority_level || "senior");

    const trackInvEl = document.getElementById("drw-itm-track-inv");
    if (trackInvEl) trackInvEl.checked = !!trackInv;

    // Lieferanten-Dropdown befüllen
    const suppSelect = document.getElementById("drw-itm-supplier");
    if (suppSelect) {
      const suppliers = allEntities.filter((e) => e.is_supplier || e.is_partner);
      suppSelect.innerHTML = `<option value="">-- Eigenleistung / Kein Lieferant --</option>` +
        suppliers.map((s) => `<option value="${s.id}" ${s.id === suppId ? "selected" : ""}>${s.display_name} (${s.creditor_no || "Kreditor"})</option>`).join("");
    }

    // Verkaufshistorie befüllen
    const histTbody = document.getElementById("drw-itm-history-tbody");
    if (histTbody) {
      if (itm) {
        histTbody.innerHTML = `
          <tr>
            <td class="py-3 px-3 font-bold text-zinc-900 dark:text-zinc-100">ANG-2026-0842</td>
            <td class="py-3 px-3"><span class="px-2 py-0.5 rounded text-[10px] font-bold bg-blue-50 text-blue-700">Angebot</span></td>
            <td class="py-3 px-3">Nordstern Digital AG</td>
            <td class="py-3 px-3">10 ${unit}</td>
            <td class="py-3 px-3">${vk.toFixed(2)} €</td>
            <td class="py-3 px-3 font-bold">${(vk * 10).toFixed(2)} €</td>
            <td class="py-3 px-3 text-zinc-500">24.10.2026</td>
          </tr>
          <tr>
            <td class="py-3 px-3 font-bold text-zinc-900 dark:text-zinc-100">AB-2026-0199</td>
            <td class="py-3 px-3"><span class="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-50 text-emerald-700">Auftrag</span></td>
            <td class="py-3 px-3">Bormann Bioscience LLC</td>
            <td class="py-3 px-3">40 ${unit}</td>
            <td class="py-3 px-3">${vk.toFixed(2)} €</td>
            <td class="py-3 px-3 font-bold">${(vk * 40).toFixed(2)} €</td>
            <td class="py-3 px-3 text-zinc-500">12.09.2026</td>
          </tr>
        `;
      } else {
        histTbody.innerHTML = `<tr><td colspan="7" class="py-4 text-center text-xs text-zinc-400">Neuer Artikel: Noch keine Vorgänge vorhanden.</td></tr>`;
      }
    }

    updateDrawerItemMargin();
    switchItemDrawerTab("stammdaten");
    drawer.classList.remove("hidden");
  };

  window.closeErpItemDrawer = function () {
    const drawer = document.getElementById("erp-item-drawer");
    if (drawer) drawer.classList.add("hidden");
  };

  window.switchItemDrawerTab = function (tabId) {
    const tabs = ["stammdaten", "preise", "bestand", "historie"];
    tabs.forEach((t) => {
      const view = document.getElementById(`itm-view-${t}`);
      const btn = document.getElementById(`itm-tabbtn-${t}`);
      const isActive = t === tabId;
      if (view) view.classList.toggle("hidden", !isActive);
      if (btn) {
        if (isActive) {
          btn.className = "itm-tab-btn px-3 py-1.5 rounded-xl text-xs font-bold transition flex items-center gap-1.5 bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900 shadow-xs cursor-pointer";
        } else {
          btn.className = "itm-tab-btn px-3 py-1.5 rounded-xl text-xs font-bold transition flex items-center gap-1.5 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-200/70 dark:hover:bg-zinc-800 cursor-pointer";
        }
      }
    });
  };

  window.updateDrawerItemMargin = function () {
    const vk = parseFloat(document.getElementById("drw-itm-vk")?.value || "0");
    const ek = parseFloat(document.getElementById("drw-itm-ek")?.value || "0");
    const diff = vk - ek;
    const pct = vk > 0 ? ((diff / vk) * 100).toFixed(1) : "0.0";
    const marginText = document.getElementById("drw-itm-margin-text");
    if (marginText) marginText.textContent = `${diff.toFixed(2)} € (${pct}%)`;
    const scale1 = document.getElementById("drw-scale-1");
    if (scale1) scale1.textContent = `${vk.toFixed(2)} € (Basis 100%)`;
  };

  window.onItemTypeChange = function (val) {
    const badgeEl = document.getElementById("erp-item-drawer-type-badge");
    const iconEl = document.getElementById("erp-item-drawer-icon");
    const typeLabels = { service: "Zeit/Service", flat_rate: "Pauschale", saas: "SaaS/Abo", product: "Produkt/HW" };
    const typeIcons = { service: "💼", flat_rate: "📦", saas: "☁️", product: "🏷️" };
    if (badgeEl) badgeEl.textContent = typeLabels[val] || val;
    if (iconEl) iconEl.textContent = typeIcons[val] || "📦";
    if (val === "product") {
      const track = document.getElementById("drw-itm-track-inv");
      if (track) track.checked = true;
    }
  };

  window.saveErpItemFromDrawer = async function () {
    const cid = getActiveCompanyId();
    let itmId = currentSelectedItemId;
    if (!itmId) itmId = `itm-${Date.now()}`;

    let itemNo = document.getElementById("drw-itm-no")?.value.trim() || "";
    if (!itemNo) {
      const maxNo = allItems.reduce((m, i) => {
        const num = parseInt(String(i.item_no || "").replace(/\D+/g, ""), 10) || 1000;
        return Math.max(m, num);
      }, 1000);
      itemNo = `ART-${maxNo + 1}`;
    }

    const title = document.getElementById("drw-itm-title")?.value.trim() || "Neue Leistung";
    const vk = parseFloat(document.getElementById("drw-itm-vk")?.value || "0");
    const ek = parseFloat(document.getElementById("drw-itm-ek")?.value || "0");
    const marginEur = Number((vk - ek).toFixed(2));
    const marginPct = vk > 0 ? Number(((marginEur / vk) * 100).toFixed(1)) : 0.0;
    const suppId = document.getElementById("drw-itm-supplier")?.value || null;
    const suppEnt = allEntities.find((e) => e.id === suppId);

    const payload = {
      company_id: cid,
      id: itmId,
      item_no: itemNo,
      item_type: document.getElementById("drw-itm-type")?.value || "service",
      ean: document.getElementById("drw-itm-ean")?.value || "",
      title: title,
      description: document.getElementById("drw-itm-desc")?.value || "",
      category: document.getElementById("drw-itm-category")?.value || "Consulting",
      unit: document.getElementById("drw-itm-unit")?.value || "Std.",
      billing_interval: document.getElementById("drw-itm-interval")?.value || "one_off",
      sales_price_net: vk,
      purchase_price_net: ek,
      margin_eur: marginEur,
      margin_pct: marginPct,
      tax_rate_pct: parseFloat(document.getElementById("drw-itm-tax")?.value || "19"),
      account_no: document.getElementById("drw-itm-account")?.value || "",
      supplier_entity_id: suppId,
      supplier_name: suppEnt ? suppEnt.display_name : "",
      track_inventory: document.getElementById("drw-itm-track-inv")?.checked ? 1 : 0,
      stock_qty: parseFloat(document.getElementById("drw-itm-stock")?.value || "0"),
      min_stock_qty: parseFloat(document.getElementById("drw-itm-min-stock")?.value || "5"),
      warehouse_bin: document.getElementById("drw-itm-bin")?.value || "",
      seats_limit: document.getElementById("drw-itm-seats")?.value || "",
      cancel_period_months: parseFloat(document.getElementById("drw-itm-cancel-months")?.value || "3"),
      seniority_level: document.getElementById("drw-itm-seniority")?.value || "senior"
    };

    try {
      await fetch("/api/erp/items", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
    } catch (e) {}

    const idx = allItems.findIndex((x) => x.id === itmId);
    if (idx >= 0) {
      allItems[idx] = { ...allItems[idx], ...payload };
    } else {
      allItems.unshift(payload);
    }
    saveTenantLocalState(cid);
    currentSelectedItemId = itmId;

    closeErpItemDrawer();
    await loadErpItems(false);
    selectErpItem(itmId);
    if (typeof window.showNotification === "function") {
      window.showNotification("Artikel gespeichert", `${payload.item_no} · ${payload.title} aktualisiert.`, "success");
    }
  };

  window.deleteCurrentErpItem = async function () {
    if (!currentSelectedItemId) return;
    if (!confirm("Diesen Artikel wirklich aus dem Katalog entfernen / archivieren?")) return;

    const itmId = currentSelectedItemId;
    allItems = allItems.filter((x) => x.id !== itmId);
    saveTenantLocalState(getActiveCompanyId());
    closeErpItemDrawer();
    currentSelectedItemId = null;
    await loadErpItems(true);

    if (typeof window.showNotification === "function") {
      window.showNotification("Artikel archiviert", "Der Datensatz wurde aus dem aktiven Katalog entfernt.", "info");
    }
  };

  // Esc-Key Event Listener für Modal-Schließen
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      const itmDrawer = document.getElementById("erp-item-drawer");
      if (itmDrawer && !itmDrawer.classList.contains("hidden")) {
        closeErpItemDrawer();
      }
    }
  });

  window.updateLiveItemMargin = function () {
    const vk = parseFloat(document.getElementById("erp-itm-vk")?.value || "0");
    const ek = parseFloat(document.getElementById("erp-itm-ek")?.value || "0");
    const diff = vk - ek;
    const pct = vk > 0 ? ((diff / vk) * 100).toFixed(1) : "0.0";
    const disp = document.getElementById("erp-itm-margin-display");
    if (disp) disp.textContent = `${diff.toFixed(2)} EUR (${pct}%)`;
  };

  window.saveCurrentErpItem = async function () {
    const cid = getActiveCompanyId();
    const itmId = document.getElementById("erp-itm-id")?.value || `itm-${Date.now()}`;
    let itemNo = document.getElementById("erp-itm-no")?.value.trim() || "";
    if (!itemNo) {
      const maxNo = allItems.reduce((m, i) => {
        const num = parseInt(String(i.item_no || "").replace(/\D+/g, ""), 10) || 1000;
        return Math.max(m, num);
      }, 1000);
      itemNo = `ART-${maxNo + 1}`;
    }

    const vk = parseFloat(document.getElementById("erp-itm-vk")?.value || "0");
    const ek = parseFloat(document.getElementById("erp-itm-ek")?.value || "0");
    const marginEur = Number((vk - ek).toFixed(2));
    const marginPct = vk > 0 ? Number(((marginEur / vk) * 100).toFixed(1)) : 0.0;
    const suppId = document.getElementById("erp-itm-supplier")?.value || null;
    const suppEnt = allEntities.find((e) => e.id === suppId);

    const payload = {
      company_id: cid,
      id: itmId,
      item_no: itemNo,
      item_type: document.getElementById("erp-itm-type")?.value || "service",
      title: document.getElementById("erp-itm-title")?.value || "Neue Leistung",
      description: document.getElementById("erp-itm-desc")?.value || "",
      category: document.getElementById("erp-itm-category")?.value || "Consulting",
      unit: document.getElementById("erp-itm-unit")?.value || "Std.",
      billing_interval: document.getElementById("erp-itm-interval")?.value || "one_off",
      sales_price_net: vk,
      purchase_price_net: ek,
      margin_eur: marginEur,
      margin_pct: marginPct,
      tax_rate_pct: parseFloat(document.getElementById("erp-itm-tax")?.value || "19"),
      supplier_entity_id: suppId,
      supplier_name: suppEnt ? suppEnt.display_name : "",
      track_inventory: document.getElementById("erp-itm-track-inv")?.checked ? 1 : 0,
      stock_qty: parseFloat(document.getElementById("erp-itm-stock")?.value || "0")
    };

    try {
      await fetch("/api/erp/items", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
    } catch (e) {}

    const idx = allItems.findIndex((x) => x.id === itmId);
    if (idx >= 0) {
      allItems[idx] = { ...allItems[idx], ...payload };
    } else {
      allItems.unshift(payload);
    }
    saveTenantLocalState(cid);
    currentSelectedItemId = itmId;

    await loadErpItems(false);
    selectErpItem(itmId);
    if (typeof window.showNotification === "function") {
      window.showNotification("Artikel gespeichert", `${payload.item_no} · ${payload.title} aktualisiert.`, "success");
    }
  };

  // ===========================================================================
  // 3. VORGÄNGE & VERTRÄGE (view-operations-erp)
  // ===========================================================================

  const OPS_ERP_TAB_META = {
    offers: {
      title: "Vorgänge & Verträge — Angebote (ANG) & Aufträge (AB)",
      subtitle: "Nuclos-Belegfluss: Angebot kalkulieren -> Auftrag bestätigen -> 1-Klick-Wandlung in GoBD-Rechnung (RE)"
    },
    pipeline: {
      title: "Vorgänge & Verträge — Deal-Pipeline & Umsatz-Forecast",
      subtitle: "Qualifizierte LinkedIn-Leads, offene Angebote und realisiertes Rechnungsvolumen im Phasen-Überblick"
    },
    contracts: {
      title: "Vorgänge & Verträge — Vertrags- & Fristenradar",
      subtitle: "Aktive SLA-Rahmenverträge, Lieferanten-Kontrakte, Kündigungsfristen und Vorlagen-Studio-Anbindung"
    }
  };

  window.initOperationsErpView = async function () {
    const cid = getActiveCompanyId();
    loadTenantLocalState(cid);
    await loadErpAddresses(false);
    await loadErpItems(false);
    populateOfferBuilderSelects();
    await loadErpDocuments();
  };

  window.switchErpOpsSubTab = function (sub) {
    ["offers", "pipeline", "contracts"].forEach((s) => {
      const v = document.getElementById(`ops-erp-view-${s}`);
      const b = document.getElementById(`ops-erp-subtab-btn-${s}`);
      if (v) v.classList.toggle("hidden", s !== sub);
      if (b) {
        const wrap = b.querySelector(".tile-icon-wrap");
        const lbl = b.querySelector(".ops-erp-tab-label");
        if (s === sub) {
          b.className =
            "ops-erp-header-tile active-cadre-tab flex flex-col items-center justify-between min-w-[56px] sm:min-w-[62px] h-[72px] py-1 px-0.5 bg-transparent border-0 shadow-none opacity-100 cursor-pointer select-none transition-transform hover:scale-105 duration-150";
          if (wrap) wrap.className = "tile-icon-wrap active-tile w-11 h-11 sm:w-12 sm:h-12 flex items-center justify-center mb-0.5";
          if (lbl) lbl.className = "ops-erp-tab-label text-[10px] font-mono tracking-tight text-center whitespace-nowrap text-red-600 font-bold leading-none";
        } else {
          b.className =
            "ops-erp-header-tile flex flex-col items-center justify-between min-w-[56px] sm:min-w-[62px] h-[72px] py-1 px-0.5 bg-transparent border-0 shadow-none opacity-80 hover:opacity-100 cursor-pointer select-none transition-transform hover:scale-105 duration-150";
          if (wrap) wrap.className = "tile-icon-wrap w-11 h-11 sm:w-12 sm:h-12 flex items-center justify-center mb-0.5";
          if (lbl) lbl.className = "ops-erp-tab-label text-[10px] font-mono tracking-tight text-center whitespace-nowrap text-[var(--muted-foreground)] font-medium leading-none";
        }
      }
    });

    const meta = OPS_ERP_TAB_META[sub] || OPS_ERP_TAB_META.offers;
    const titleEl = document.getElementById("ops-erp-main-title");
    const subEl = document.getElementById("ops-erp-main-subtitle");
    if (titleEl) titleEl.textContent = meta.title;
    if (subEl) subEl.textContent = meta.subtitle;

    if (sub === "pipeline") {
      renderErpPipelineLeadsList();
    }
  };

  function renderErpPipelineLeadsList() {
    const box = document.getElementById("erp-pipeline-leads-list");
    if (!box) return;
    const rows = allEntities.map((ent) => {
      const entDocs = cachedOffers.filter((d) => d.entity_id === ent.id);
      const totalGross = entDocs.reduce((acc, d) => acc + Number(d.amount_gross || 0), 0);
      const stage = ent.is_customer
        ? "Bestandskunde / Won (100%)"
        : ent.is_supplier
        ? "Infrastruktur-Partner"
        : "LinkedIn Lead / Discovery (25%)";
      return `
        <div class="p-3 rounded-xl border border-[var(--border)] bg-[var(--secondary)]/30 flex items-center justify-between gap-3 text-xs">
          <div>
            <div class="font-bold text-[var(--foreground)]">${ent.display_name} <span class="text-[10px] font-mono text-amber-500">${renderStars(ent.rating)}</span></div>
            <div class="text-[11px] text-[var(--muted-foreground)]">${stage} · ${ent.city || "DE"} · ${entDocs.length} Beleg(e)</div>
          </div>
          <div class="flex items-center gap-2">
            <span class="font-mono font-bold text-[var(--foreground)]">${totalGross.toFixed(2)} EUR</span>
            <button type="button" onclick="setTab('addresses'); selectErpAddress('${ent.id}');" class="px-2.5 py-1 rounded-lg bg-[var(--card)] border border-[var(--border)] text-[11px] font-semibold cursor-pointer">Akte öffnen</button>
          </div>
        </div>
      `;
    });
    box.innerHTML = rows.join("");
  }

  function populateOfferBuilderSelects() {
    const entSel = document.getElementById("erp-doc-entity-select");
    if (entSel) {
      entSel.innerHTML = allEntities
        .map((e) => `<option value="${e.id}">${e.display_name} (${e.debtor_no ? `Debitor ${e.debtor_no}` : "Lead"})</option>`)
        .join("");
    }
    const linesBox = document.getElementById("erp-doc-lines-builder");
    if (linesBox && !linesBox.children.length) {
      addErpDocBuilderLine();
    }
  }

  window.addErpDocBuilderLine = function () {
    const linesBox = document.getElementById("erp-doc-lines-builder");
    if (!linesBox) return;
    const row = document.createElement("div");
    row.className = "grid grid-cols-12 gap-1.5 items-center erp-builder-line";
    const itemOptions = allItems
      .map((i) => `<option value="${i.id}" data-price="${i.sales_price_net}">${i.item_no} · ${i.title} (${i.sales_price_net} €)</option>`)
      .join("");
    row.innerHTML = `
      <select class="col-span-7 px-2 py-1 rounded-lg bg-[var(--secondary)] border border-[var(--border)] text-xs text-[var(--foreground)] erp-line-item-select">
        ${itemOptions}
      </select>
      <input type="number" step="1" value="1" class="col-span-3 px-2 py-1 rounded-lg bg-[var(--secondary)] border border-[var(--border)] text-xs font-mono text-[var(--foreground)] erp-line-qty" placeholder="Menge">
      <button type="button" onclick="this.parentElement.remove()" class="col-span-2 px-2 py-1 rounded-lg bg-rose-500/10 text-rose-600 text-xs font-bold cursor-pointer">✕</button>
    `;
    linesBox.appendChild(row);
  };

  window.resetErpOfferBuilder = function () {
    const linesBox = document.getElementById("erp-doc-lines-builder");
    if (linesBox) linesBox.innerHTML = "";
    addErpDocBuilderLine();
  };

  window.submitErpOfferDocument = async function () {
    const cid = getActiveCompanyId();
    const docType = document.getElementById("erp-doc-type")?.value || "offer";
    const entityId = document.getElementById("erp-doc-entity-select")?.value;
    if (!entityId) return;

    const lineEls = document.querySelectorAll(".erp-builder-line");
    const lines = [];
    let sumNet = 0;
    lineEls.forEach((row) => {
      const itemId = row.querySelector(".erp-line-item-select")?.value;
      const qty = parseFloat(row.querySelector(".erp-line-qty")?.value || "1");
      const itm = allItems.find((x) => x.id === itemId);
      if (itm) {
        sumNet += Number(itm.sales_price_net || 0) * qty;
        lines.push({ item_id: itemId, title: itm.title, quantity: qty });
      }
    });

    let createdViaApi = false;
    try {
      const resp = await fetch("/api/erp/documents", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          company_id: cid,
          doc_type: docType,
          status: docType === "invoice" ? "booked" : "sent",
          entity_id: entityId,
          notes: document.getElementById("erp-doc-notes")?.value || "",
          lines: lines
        })
      });
      if (resp.ok) createdViaApi = true;
    } catch (e) {}

    if (!createdViaApi) {
      const ent = allEntities.find((x) => x.id === entityId);
      const prefix = docType === "invoice" ? "RE" : docType === "order" ? "AB" : "ANG";
      const countSame = cachedOffers.filter((d) => d.doc_type === docType).length + 1;
      const today = new Date().toISOString().slice(0, 10);
      const tax = Number((sumNet * 0.19).toFixed(2));
      cachedOffers.unshift({
        id: `doc-${Date.now()}`,
        doc_type: docType,
        doc_number: `${prefix}-2026-000${countSame}`,
        status: docType === "invoice" ? "booked" : "sent",
        entity_id: entityId,
        entity_name: ent ? ent.display_name : "Kunde",
        issue_date: today,
        due_date: today,
        amount_net: Number(sumNet.toFixed(2)),
        tax_amount: tax,
        amount_gross: Number((sumNet + tax).toFixed(2)),
        currency: "EUR",
        lines: lines
      });
      saveTenantLocalState(cid);
    }

    await loadErpDocuments();
  };

  window.loadErpDocuments = async function () {
    const cid = getActiveCompanyId();
    const container = document.getElementById("erp-offers-list-container");
    try {
      const resp = await fetch(`/api/erp/documents?company_id=${encodeURIComponent(cid)}`);
      if (resp.ok) {
        const data = await resp.json();
        if (Array.isArray(data.items) && data.items.length > 0) {
          cachedOffers = data.items;
          saveTenantLocalState(cid);
        }
      }
    } catch (e) {}

    const openOffersVol = cachedOffers
      .filter((d) => d.doc_type === "offer" && d.status !== "cancelled")
      .reduce((acc, d) => acc + Number(d.amount_net || 0), 0);
    const volBadge = document.getElementById("erp-ops-volume-badge");
    if (volBadge) volBadge.textContent = `Angebotsvolumen: ${openOffersVol.toFixed(2)} EUR netto`;

    const pipeCount = document.getElementById("erp-pipe-offers-count");
    if (pipeCount) pipeCount.textContent = `${cachedOffers.filter((d) => d.doc_type === "offer").length} aktive Angebote`;

    const wonVol = cachedOffers
      .filter((d) => d.doc_type === "invoice" && d.status !== "cancelled")
      .reduce((acc, d) => acc + Number(d.amount_gross || 0), 0);
    const pipeWon = document.getElementById("erp-pipe-won-volume");
    if (pipeWon) pipeWon.textContent = `${wonVol.toFixed(2)} EUR brutto`;

    renderErpPipelineLeadsList();

    if (!container) return;
    if (!cachedOffers.length) {
      container.innerHTML = `<div class="text-xs text-[var(--muted-foreground)] p-6 text-center">Noch keine Angebote oder Aufträge vorhanden.</div>`;
      return;
    }

    container.innerHTML = cachedOffers
      .map(
        (doc) => `
        <div class="p-3 rounded-xl border border-[var(--border)] bg-[var(--secondary)]/30 flex items-center justify-between gap-3">
          <div class="min-w-0">
            <div class="flex items-center gap-2 flex-wrap">
              <span class="px-2 py-0.5 rounded text-[10px] font-mono font-bold ${
                doc.doc_type === "invoice"
                  ? "bg-emerald-500/10 text-emerald-600 border border-emerald-500/20"
                  : "bg-indigo-500/10 text-indigo-600 border border-indigo-500/20"
              }">${doc.doc_number}</span>
              <span class="text-xs font-bold text-[var(--foreground)]">${doc.entity_name || "Kunde"}</span>
              <span class="text-[10px] font-mono uppercase px-1.5 py-0.5 rounded bg-[var(--card)] border border-[var(--border)]">${doc.status}</span>
            </div>
            <div class="text-[11px] text-[var(--muted-foreground)] mt-0.5">
              Datum: ${doc.issue_date} · ${(doc.lines || []).length} Position(en) · Netto: ${Number(doc.amount_net).toFixed(2)} €
            </div>
          </div>
          <div class="flex items-center gap-2 shrink-0">
            <div class="text-right">
              <div class="text-xs font-mono font-black text-[var(--foreground)]">${Number(doc.amount_gross).toFixed(2)} EUR</div>
              <div class="text-[10px] font-mono text-[var(--muted-foreground)]">inkl. USt.</div>
            </div>
            ${
              doc.doc_type === "offer" && doc.status !== "accepted"
                ? `<button type="button" onclick="convertErpDocToInvoice('${doc.id}')" class="px-2.5 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-[11px] font-bold cursor-pointer shadow-xs">1-Klick &rarr; Rechnung</button>`
                : `<button type="button" onclick="previewErpDocumentInStudio('${doc.id}')" class="px-2.5 py-1.5 rounded-lg bg-[var(--card)] border border-[var(--border)] text-[11px] font-semibold text-[var(--foreground)] cursor-pointer">Beleg-PDF / Druck</button>`
            }
          </div>
        </div>
      `
      )
      .join("");
  };

  window.convertErpDocToInvoice = async function (docId) {
    const cid = getActiveCompanyId();
    let convertedViaApi = false;
    try {
      const resp = await fetch(`/api/erp/documents/${encodeURIComponent(docId)}/convert`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ company_id: cid, target_doc_type: "invoice" })
      });
      if (resp.ok) convertedViaApi = true;
    } catch (e) {}

    if (!convertedViaApi) {
      const src = cachedOffers.find((d) => d.id === docId);
      if (src) {
        src.status = "accepted";
        const invCount = cachedOffers.filter((d) => d.doc_type === "invoice").length + 1;
        const today = new Date().toISOString().slice(0, 10);
        cachedOffers.unshift({
          ...JSON.parse(JSON.stringify(src)),
          id: `doc-inv-${Date.now()}`,
          doc_type: "invoice",
          doc_number: `RE-2026-000${invCount}`,
          status: "booked",
          issue_date: today
        });
        saveTenantLocalState(cid);
      }
    }

    await loadErpDocuments();
    if (currentSelectedEntityId) await selectErpAddress(currentSelectedEntityId, true);
  };

  window.openErpDocumentPdf = function (docId, docType, entityName, amountNet) {
    const cid = getActiveCompanyId();
    let url = `/api/erp/documents/${encodeURIComponent(docId)}/print?company_id=${encodeURIComponent(cid)}`;
    if (docType) url += `&doc_type=${encodeURIComponent(docType)}`;
    if (entityName) url += `&entity_name=${encodeURIComponent(entityName)}`;
    if (amountNet) url += `&amount_net=${encodeURIComponent(amountNet)}`;
    window.open(url, "_blank");
  };

  window.previewErpDocumentInStudio = function (docId) {
    openErpDocumentPdf(docId);
  };
})();
