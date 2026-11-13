/**
 * static/js/onboarding_wizard.js
 * Milestone 30: Interactive First-Run Web Setup Wizard & Onboarding Assistant
 *
 * Self-contained, theme-aware (var(--card), var(--foreground), var(--border))
 * 4-step modal wizard in pure vanilla JS with built-in EN / DE i18n dictionary,
 * live SSRF-safe AI provider connectivity probes + latency badges, Zero-Egress
 * privacy toggle, channel configuration, and 8-domain / 70-specialist activation.
 *
 * Public helper: window.openArchonSetupWizard()
 */
(function () {
  'use strict';

  const MODAL_ID = 'archon-onboarding-wizard-overlay';
  const STYLE_ID = 'archon-onboarding-wizard-styles';

  const I18N = {
    en: {
      badge: 'First-Run Setup',
      title: 'Welcome to Archon Agentic OS',
      subtitle: 'Configure your tenant, AI engines, communication channels, and specialist cadre in 4 quick steps.',
      steps: [
        '1. Company & Tenant',
        '2. AI Providers & Zero-Egress',
        '3. Channels & Vault',
        '4. Specialist Domains'
      ],
      step1Title: 'Company & Primary Tenant Profile',
      step1Desc: 'Used for corporate letterheads, invoices, contracts, and executive syntheses. Stored locally on your instance.',
      companyName: 'Company / Organization Name *',
      companyNamePlaceholder: 'e.g. Horizon Ventures LLC',
      legalForm: 'Legal Form',
      legalFormPlaceholder: 'e.g. LLC, Inc., Ltd., GmbH',
      address: 'Business Address',
      addressPlaceholder: 'Street, Postal Code, City, Country',
      taxId: 'Tax ID / EIN',
      taxIdPlaceholder: 'Optional tax number',
      vatId: 'VAT / Sales Tax ID',
      vatIdPlaceholder: 'e.g. EU123456789',
      iban: 'IBAN / Account',
      ibanPlaceholder: 'Optional IBAN (e.g. DE89...)',
      bic: 'BIC / SWIFT',
      bicPlaceholder: 'Optional BIC (8 or 11 chars)',
      currency: 'Base Currency',
      language: 'Workspace & Guardrail Language',
      langEn: 'English (Global)',
      langDe: 'Deutsch (DACH)',
      errCompanyRequired: 'Please enter a Company / Organization Name to continue.',

      step2Title: 'AI Providers & Zero-Egress Privacy Routing',
      step2Desc: 'Connect cloud APIs, local engines (Ollama / LM Studio), or OmniRoute. Secret keys are saved with strict 0600 permissions.',
      zeroEgressTitle: 'Enforce Zero-Egress Privacy Routing (GDPR / Strict Local)',
      zeroEgressDesc: 'Sensitive finance, legal, HR, and CRM payloads stay strictly on local LLMs (Ollama / LM Studio) and never leave your machine.',
      configuredBadge: 'Configured',
      localBadge: 'Local / Self-Hosted',
      cloudBadge: 'HTTPS Cloud',
      apiKeyPlaceholder: 'Enter API key...',
      apiKeyKeepPlaceholder: '•••••••• (saved — leave blank to keep)',
      baseUrlLabel: 'Endpoint URL',
      testBtn: 'Test Connection',
      testingBtn: 'Probing...',
      modelsUnit: 'models',

      step3Title: 'Communication Channels & Second Brain Vault',
      step3Desc: 'Optional integrations for email inbox/dispatch, Telegram mobile command, and Obsidian Markdown sync.',
      vaultSection: 'Obsidian Second Brain Vault',
      vaultPath: 'Vault Directory Path',
      vaultPlaceholder: './obsidian_vault',
      emailSection: 'Email Integration (IMAP & SMTP)',
      imapHost: 'IMAP Host',
      imapPort: 'IMAP Port',
      smtpHost: 'SMTP Host',
      smtpPort: 'SMTP Port',
      emailUser: 'Email Username / Address',
      emailPass: 'Email App Password',
      telegramSection: 'Telegram Executive Bridge',
      tgToken: 'Telegram Bot Token (@BotFather)',
      tgChatId: 'Authorized Chat ID',
      tgVerify: 'Verify Telegram Bot via getMe upon completion',

      step4Title: 'Activate Specialist Domains (70 Specialists)',
      step4Desc: 'Select which specialist departments should be active in Mission Control and the AI Boardroom. Compact SOUL directives will be synchronized automatically.',
      selectAll: 'Select All (8)',
      selectCore: 'Core Business Only',
      selectedSummary: '{domains} of {totalDomains} domains active · {specialists} of {totalSpecialists} specialists ready',
      specialistsCount: '{count} Specialists',
      errDomainRequired: 'Please keep at least one specialist domain enabled.',

      skipBtn: 'Skip Setup',
      skippingBtn: 'Skipping...',
      backBtn: 'Back',
      nextBtn: 'Continue',
      finishBtn: 'Complete Setup',
      savingBtn: 'Saving Configuration...',
      completedToast: 'Archon OS setup completed!',
      closeLabel: 'Close wizard'
    },
    de: {
      badge: 'Ersteinrichtung',
      title: 'Willkommen bei Archon Agentic OS',
      subtitle: 'Richten Sie Mandantenprofil, KI-Provider, Kommunikationskanäle und Spezialisten-Domänen in 4 kurzen Schritten ein.',
      steps: [
        '1. Unternehmen & Mandant',
        '2. KI-Provider & Zero-Egress',
        '3. Kanäle & Vault',
        '4. Spezialisten-Domänen'
      ],
      step1Title: 'Unternehmens- & Mandanten-Stammdaten',
      step1Desc: 'Basis für Briefbögen, Angebote, Rechnungen, Verträge und Boardroom-Dossiers. Wird ausschließlich lokal gespeichert.',
      companyName: 'Firmenname / Organisation *',
      companyNamePlaceholder: 'z. B. Muster Holding GmbH',
      legalForm: 'Rechtsform',
      legalFormPlaceholder: 'z. B. GmbH, UG, AG, e.K., Einzelunternehmen',
      address: 'Geschäftsadresse',
      addressPlaceholder: 'Straße, PLZ, Ort, Land',
      taxId: 'Steuernummer',
      taxIdPlaceholder: 'Optionale Steuernummer',
      vatId: 'USt-IdNr.',
      vatIdPlaceholder: 'z. B. DE123456789',
      iban: 'IBAN',
      ibanPlaceholder: 'Optionale IBAN (z. B. DE89...)',
      bic: 'BIC / SWIFT',
      bicPlaceholder: 'Optionaler BIC (8 oder 11 Zeichen)',
      currency: 'Basiswährung',
      language: 'System- & Direktiven-Sprache',
      langEn: 'English (International)',
      langDe: 'Deutsch (DACH)',
      errCompanyRequired: 'Bitte geben Sie einen Firmen- bzw. Organisationsnamen ein.',

      step2Title: 'KI-Provider & Zero-Egress Datenschutz-Routing',
      step2Desc: 'Verbinden Sie Cloud-APIs, lokale Modelle (Ollama / LM Studio) oder OmniRoute. API-Keys werden gehärtet (chmod 0600) abgelegt.',
      zeroEgressTitle: 'Zero-Egress Datenschutz-Routing erzwingen (DSGVO / Lokal)',
      zeroEgressDesc: 'Sensible Finanz-, Vertrags-, Personal- und CRM-Daten verbleiben strikt auf lokalen LLMs (Ollama / LM Studio) und verlassen Ihr System nie.',
      configuredBadge: 'Hinterlegt',
      localBadge: 'Lokal / Self-Hosted',
      cloudBadge: 'HTTPS Cloud',
      apiKeyPlaceholder: 'API-Key eingeben...',
      apiKeyKeepPlaceholder: '•••••••• (gespeichert — leer lassen zum Behalten)',
      baseUrlLabel: 'Endpunkt-URL',
      testBtn: 'Verbindung testen',
      testingBtn: 'Prüfe...',
      modelsUnit: 'Modelle',

      step3Title: 'Kommunikationskanäle & Obsidian Second Brain',
      step3Desc: 'Optionale Anbindungen für E-Mail-Postfach, Telegram-Steuerung und Ihren lokalen Obsidian-Wissensspeicher.',
      vaultSection: 'Obsidian Second Brain Vault',
      vaultPath: 'Pfad zum Obsidian-Vault',
      vaultPlaceholder: './obsidian_vault',
      emailSection: 'E-Mail-Anbindung (IMAP & SMTP)',
      imapHost: 'IMAP-Server',
      imapPort: 'IMAP-Port',
      smtpHost: 'SMTP-Server',
      smtpPort: 'SMTP-Port',
      emailUser: 'E-Mail-Benutzer / Adresse',
      emailPass: 'E-Mail-App-Passwort',
      telegramSection: 'Telegram Executive Bridge',
      tgToken: 'Telegram Bot-Token (@BotFather)',
      tgChatId: 'Autorisierte Chat-ID',
      tgVerify: 'Telegram-Bot beim Abschließen live via getMe prüfen',

      step4Title: 'Spezialisten-Domänen aktivieren (70 Spezialisten)',
      step4Desc: 'Wählen Sie die aktiven Fachbereiche für Mission Control und den AI Boardroom. Die kompakten SOUL-Direktiven werden automatisch synchronisiert.',
      selectAll: 'Alle auswählen (8)',
      selectCore: 'Nur Kern-Domänen',
      selectedSummary: '{domains} von {totalDomains} Domänen aktiv · {specialists} von {totalSpecialists} Spezialisten bereit',
      specialistsCount: '{count} Spezialisten',
      errDomainRequired: 'Bitte lassen Sie mindestens eine Spezialisten-Domäne aktiviert.',

      skipBtn: 'Einrichtung überspringen',
      skippingBtn: 'Wird übersprungen...',
      backBtn: 'Zurück',
      nextBtn: 'Weiter',
      finishBtn: 'Einrichtung abschließen',
      savingBtn: 'Speichere Konfiguration...',
      completedToast: 'Archon OS Einrichtung abgeschlossen!',
      closeLabel: 'Assistent schließen'
    }
  };

  function detectInitialLanguage(serverLang) {
    const stored =
      localStorage.getItem('archon_lang') ||
      localStorage.getItem('archon_language') ||
      serverLang ||
      (typeof navigator !== 'undefined' ? navigator.language : 'en') ||
      'en';
    return String(stored).toLowerCase().startsWith('de') ? 'de' : 'en';
  }

  function esc(val) {
    return String(val == null ? '' : val)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function formatAddressForInput(addr) {
    if (!addr) return '';
    if (typeof addr === 'string') return addr;
    if (typeof addr === 'object') {
      return [addr.street, [addr.postal_code, addr.city].filter(Boolean).join(' '), addr.country]
        .filter(Boolean)
        .join(', ');
    }
    return String(addr);
  }

  const state = {
    step: 0,
    lang: detectInitialLanguage(),
    statusData: null,
    errorMsg: '',
    busy: false,
    probeResults: {},
    probingMap: {},
    form: {
      company_name: '',
      legal_form: '',
      address: '',
      tax_id: '',
      vat_id: '',
      iban: '',
      bic: '',
      currency: 'EUR',
      language: 'en',
      zero_egress: false,
      providerKeys: {},
      providerUrls: {},
      obsidian_vault_path: './obsidian_vault',
      imap_host: '',
      imap_port: 993,
      smtp_host: '',
      smtp_port: 587,
      email_user: '',
      email_password: '',
      bot_token: '',
      chat_id: '',
      verify_telegram: false,
      active_domains: []
    }
  };

  function t(key) {
    const dict = I18N[state.lang] || I18N.en;
    return dict[key] != null ? dict[key] : (I18N.en[key] || key);
  }

  function injectStyles() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = `
      #${MODAL_ID} {
        position: fixed;
        inset: 0;
        z-index: 99990;
        display: none;
        align-items: center;
        justify-content: center;
        padding: 16px;
        background: rgba(2, 6, 23, 0.72);
        backdrop-filter: blur(6px);
        font-family: Outfit, Inter, system-ui, -apple-system, sans-serif;
      }
      #${MODAL_ID}.is-open {
        display: flex;
      }
      .aow-dialog {
        width: 100%;
        max-width: 860px;
        max-height: 92vh;
        display: flex;
        flex-direction: column;
        background: var(--card, #ffffff);
        color: var(--foreground, #0f172a);
        border: 1px solid var(--border, #e2e8f0);
        border-radius: 16px;
        box-shadow: 0 24px 70px rgba(0, 0, 0, 0.38);
        overflow: hidden;
      }
      .aow-header {
        padding: 20px 24px 16px;
        border-bottom: 1px solid var(--border, #e2e8f0);
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 16px;
      }
      .aow-badge {
        display: inline-block;
        font-family: 'JetBrains Mono', monospace;
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        padding: 3px 8px;
        border-radius: 999px;
        background: rgba(2, 132, 199, 0.12);
        color: #0284c7;
        margin-bottom: 6px;
      }
      .aow-title {
        font-size: 20px;
        font-weight: 800;
        line-height: 1.25;
        margin: 0;
      }
      .aow-subtitle {
        font-size: 13px;
        color: var(--muted-foreground, #64748b);
        margin: 4px 0 0;
      }
      .aow-lang-switch {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        border: 1px solid var(--border, #e2e8f0);
        border-radius: 8px;
        padding: 2px;
        flex-shrink: 0;
      }
      .aow-lang-btn {
        border: 0;
        background: transparent;
        color: var(--muted-foreground, #64748b);
        font-family: 'JetBrains Mono', monospace;
        font-size: 11px;
        font-weight: 700;
        padding: 4px 8px;
        border-radius: 6px;
        cursor: pointer;
      }
      .aow-lang-btn.is-active {
        background: #0284c7;
        color: #ffffff;
      }
      .aow-stepper {
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 8px;
        padding: 12px 24px;
        background: var(--muted, rgba(148, 163, 184, 0.08));
        border-bottom: 1px solid var(--border, #e2e8f0);
      }
      .aow-step-pill {
        font-size: 12px;
        font-weight: 600;
        padding: 7px 10px;
        border-radius: 8px;
        border: 1px solid var(--border, #e2e8f0);
        background: var(--card, #ffffff);
        color: var(--muted-foreground, #64748b);
        text-align: center;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        cursor: pointer;
        transition: all 0.15s ease;
      }
      .aow-step-pill.is-active {
        border-color: #0284c7;
        background: rgba(2, 132, 199, 0.1);
        color: var(--foreground, #0f172a);
        font-weight: 700;
      }
      .aow-step-pill.is-done {
        border-color: rgba(16, 185, 129, 0.45);
        color: #10b981;
      }
      .aow-body {
        padding: 20px 24px;
        overflow-y: auto;
        flex: 1;
      }
      .aow-section-title {
        font-size: 15px;
        font-weight: 700;
        margin: 0 0 4px;
      }
      .aow-section-desc {
        font-size: 12.5px;
        color: var(--muted-foreground, #64748b);
        margin: 0 0 16px;
      }
      .aow-grid-2 {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 12px;
      }
      .aow-grid-3 {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 12px;
      }
      @media (max-width: 680px) {
        .aow-stepper { grid-template-columns: repeat(2, 1fr); }
        .aow-grid-2, .aow-grid-3 { grid-template-columns: 1fr; }
      }
      .aow-field {
        display: flex;
        flex-direction: column;
        gap: 5px;
      }
      .aow-field.span-2 {
        grid-column: 1 / -1;
      }
      .aow-label {
        font-size: 11.5px;
        font-weight: 600;
        color: var(--foreground, #0f172a);
      }
      .aow-input, .aow-select {
        width: 100%;
        box-sizing: border-box;
        background: var(--background, #f8fafc);
        color: var(--foreground, #0f172a);
        border: 1px solid var(--border, #cbd5e1);
        border-radius: 8px;
        padding: 8px 11px;
        font-size: 12.5px;
        font-family: inherit;
        outline: none;
      }
      .aow-input:focus, .aow-select:focus {
        border-color: #0284c7;
        box-shadow: 0 0 0 2px rgba(2, 132, 199, 0.18);
      }
      .aow-mono {
        font-family: 'JetBrains Mono', monospace;
        font-size: 12px;
      }
      .aow-zero-egress-card {
        display: flex;
        align-items: flex-start;
        gap: 12px;
        padding: 12px 14px;
        border-radius: 10px;
        border: 1px solid rgba(16, 185, 129, 0.4);
        background: rgba(16, 185, 129, 0.07);
        margin-bottom: 14px;
      }
      .aow-provider-list {
        display: flex;
        flex-direction: column;
        gap: 10px;
      }
      .aow-provider-row {
        border: 1px solid var(--border, #e2e8f0);
        border-radius: 10px;
        padding: 11px 13px;
        background: var(--background, rgba(148, 163, 184, 0.04));
        display: flex;
        flex-direction: column;
        gap: 8px;
      }
      .aow-provider-top {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
        flex-wrap: wrap;
      }
      .aow-pill {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        font-family: 'JetBrains Mono', monospace;
        font-size: 10.5px;
        font-weight: 600;
        padding: 2px 8px;
        border-radius: 999px;
        border: 1px solid var(--border, #cbd5e1);
      }
      .aow-pill.ok {
        border-color: rgba(16, 185, 129, 0.45);
        background: rgba(16, 185, 129, 0.12);
        color: #10b981;
      }
      .aow-pill.err {
        border-color: rgba(239, 68, 68, 0.45);
        background: rgba(239, 68, 68, 0.12);
        color: #ef4444;
      }
      .aow-provider-controls {
        display: flex;
        gap: 8px;
        align-items: center;
        flex-wrap: wrap;
      }
      .aow-provider-controls .aow-input {
        flex: 1;
        min-width: 180px;
      }
      .aow-btn {
        border: 1px solid var(--border, #cbd5e1);
        background: var(--card, #ffffff);
        color: var(--foreground, #0f172a);
        border-radius: 8px;
        padding: 8px 14px;
        font-size: 12px;
        font-weight: 700;
        cursor: pointer;
        transition: all 0.15s ease;
      }
      .aow-btn:hover:not(:disabled) {
        border-color: #0284c7;
      }
      .aow-btn:disabled {
        opacity: 0.55;
        cursor: not-allowed;
      }
      .aow-btn-primary {
        background: #0284c7;
        border-color: #0284c7;
        color: #ffffff;
      }
      .aow-btn-primary:hover:not(:disabled) {
        background: #0369a1;
      }
      .aow-btn-ghost {
        border-color: transparent;
        background: transparent;
        color: var(--muted-foreground, #64748b);
      }
      .aow-btn-ghost:hover:not(:disabled) {
        color: var(--foreground, #0f172a);
        border-color: var(--border, #cbd5e1);
      }
      .aow-domain-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 10px;
      }
      @media (max-width: 680px) {
        .aow-domain-grid { grid-template-columns: 1fr; }
      }
      .aow-domain-card {
        border: 1px solid var(--border, #e2e8f0);
        border-radius: 10px;
        padding: 11px 13px;
        display: flex;
        align-items: flex-start;
        gap: 10px;
        cursor: pointer;
        background: var(--background, rgba(148, 163, 184, 0.04));
      }
      .aow-domain-card.is-checked {
        border-color: #0284c7;
        background: rgba(2, 132, 199, 0.07);
      }
      .aow-subbox {
        border: 1px solid var(--border, #e2e8f0);
        border-radius: 10px;
        padding: 13px;
        margin-bottom: 12px;
      }
      .aow-subbox-title {
        font-size: 12.5px;
        font-weight: 700;
        margin: 0 0 10px;
      }
      .aow-error {
        margin: 0 24px 10px;
        padding: 9px 12px;
        border-radius: 8px;
        background: rgba(239, 68, 68, 0.12);
        border: 1px solid rgba(239, 68, 68, 0.4);
        color: #ef4444;
        font-size: 12px;
        font-weight: 600;
      }
      .aow-footer {
        padding: 14px 24px;
        border-top: 1px solid var(--border, #e2e8f0);
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
      }
    `;
    document.head.appendChild(style);
  }

  function hydrateStateFromServer(data) {
    state.statusData = data || {};
    state.lang = detectInitialLanguage(data && data.language);
    const cp = (data && data.company_profile) || {};
    const ch = (data && data.channels) || {};
    state.form.company_name = cp.company_name || cp.name || '';
    state.form.legal_form = cp.legal_form || '';
    state.form.address = formatAddressForInput(cp.address);
    state.form.tax_id = cp.tax_id || '';
    state.form.vat_id = cp.vat_id || '';
    state.form.iban = cp.iban || '';
    state.form.bic = cp.bic || '';
    state.form.currency = cp.currency || 'EUR';
    state.form.language = cp.language || data.language || state.lang || 'en';
    state.form.zero_egress = Boolean(data && data.zero_egress);

    const catalog = (data && data.providers_catalog) || [];
    catalog.forEach(function (p) {
      if (p.url_env_key && !state.form.providerUrls[p.id]) {
        state.form.providerUrls[p.id] = p.default_base_url || '';
      }
    });

    state.form.obsidian_vault_path = ch.obsidian_vault_path || './obsidian_vault';
    state.form.imap_host = ch.imap_host || '';
    state.form.imap_port = ch.imap_port || 993;
    state.form.smtp_host = ch.smtp_host || '';
    state.form.smtp_port = ch.smtp_port || 587;
    state.form.email_user = ch.email_user || '';
    state.form.chat_id = ch.telegram_chat_id || '';

    const doms = (data && data.specialist_domains) || [];
    const activeIds = (data && data.active_domains && data.active_domains.length)
      ? data.active_domains.slice()
      : doms.map(function (d) { return d.id; });
    state.form.active_domains = activeIds;
  }

  function renderStep1() {
    const f = state.form;
    const currencies = ['EUR', 'USD', 'GBP', 'CHF'];
    return `
      <h3 class="aow-section-title">${esc(t('step1Title'))}</h3>
      <p class="aow-section-desc">${esc(t('step1Desc'))}</p>
      <div class="aow-grid-2">
        <div class="aow-field">
          <label class="aow-label" for="aow-company-name">${esc(t('companyName'))}</label>
          <input id="aow-company-name" class="aow-input" type="text" value="${esc(f.company_name)}" placeholder="${esc(t('companyNamePlaceholder'))}" />
        </div>
        <div class="aow-field">
          <label class="aow-label" for="aow-legal-form">${esc(t('legalForm'))}</label>
          <input id="aow-legal-form" class="aow-input" type="text" value="${esc(f.legal_form)}" placeholder="${esc(t('legalFormPlaceholder'))}" />
        </div>
        <div class="aow-field span-2">
          <label class="aow-label" for="aow-address">${esc(t('address'))}</label>
          <input id="aow-address" class="aow-input" type="text" value="${esc(f.address)}" placeholder="${esc(t('addressPlaceholder'))}" />
        </div>
        <div class="aow-field">
          <label class="aow-label" for="aow-tax-id">${esc(t('taxId'))}</label>
          <input id="aow-tax-id" class="aow-input aow-mono" type="text" value="${esc(f.tax_id)}" placeholder="${esc(t('taxIdPlaceholder'))}" />
        </div>
        <div class="aow-field">
          <label class="aow-label" for="aow-vat-id">${esc(t('vatId'))}</label>
          <input id="aow-vat-id" class="aow-input aow-mono" type="text" value="${esc(f.vat_id)}" placeholder="${esc(t('vatIdPlaceholder'))}" />
        </div>
        <div class="aow-field">
          <label class="aow-label" for="aow-iban">${esc(t('iban'))}</label>
          <input id="aow-iban" class="aow-input aow-mono" type="text" value="${esc(f.iban)}" placeholder="${esc(t('ibanPlaceholder'))}" />
        </div>
        <div class="aow-field">
          <label class="aow-label" for="aow-bic">${esc(t('bic'))}</label>
          <input id="aow-bic" class="aow-input aow-mono" type="text" value="${esc(f.bic)}" placeholder="${esc(t('bicPlaceholder'))}" />
        </div>
        <div class="aow-field">
          <label class="aow-label" for="aow-currency">${esc(t('currency'))}</label>
          <select id="aow-currency" class="aow-select aow-mono">
            ${currencies.map(function (c) {
              return `<option value="${c}" ${f.currency === c ? 'selected' : ''}>${c}</option>`;
            }).join('')}
          </select>
        </div>
        <div class="aow-field">
          <label class="aow-label" for="aow-language">${esc(t('language'))}</label>
          <select id="aow-language" class="aow-select">
            <option value="en" ${f.language === 'en' ? 'selected' : ''}>${esc(t('langEn'))}</option>
            <option value="de" ${f.language === 'de' ? 'selected' : ''}>${esc(t('langDe'))}</option>
          </select>
        </div>
      </div>
    `;
  }

  function renderStep2() {
    const f = state.form;
    const catalog = (state.statusData && state.statusData.providers_catalog) || [
      { id: 'openrouter', name: 'OpenRouter', env_key: 'OPENROUTER_API_KEY', is_local: false, requires_key: true, configured: false, default_base_url: 'https://openrouter.ai/api/v1' },
      { id: 'openai', name: 'OpenAI', env_key: 'OPENAI_API_KEY', is_local: false, requires_key: true, configured: false, default_base_url: 'https://api.openai.com/v1' },
      { id: 'anthropic', name: 'Anthropic', env_key: 'ANTHROPIC_API_KEY', is_local: false, requires_key: true, configured: false, default_base_url: 'https://api.anthropic.com/v1' },
      { id: 'gemini', name: 'Google Gemini', env_key: 'GEMINI_API_KEY', is_local: false, requires_key: true, configured: false, default_base_url: 'https://generativelanguage.googleapis.com/v1beta' },
      { id: 'groq', name: 'Groq', env_key: 'GROQ_API_KEY', is_local: false, requires_key: true, configured: false, default_base_url: 'https://api.groq.com/openai/v1' },
      { id: 'ollama', name: 'Ollama (Local)', env_key: null, url_env_key: 'OLLAMA_BASE_URL', is_local: true, requires_key: false, configured: false, default_base_url: 'http://localhost:11434' },
      { id: 'lm_studio', name: 'LM Studio (Local)', env_key: null, url_env_key: 'LM_STUDIO_URL', is_local: true, requires_key: false, configured: false, default_base_url: 'http://localhost:1234/v1' },
      { id: 'omniroute', name: 'OmniRoute Hub', env_key: 'OMNIROUTE_API_KEY', url_env_key: 'OMNIROUTE_URL', is_local: true, requires_key: false, configured: false, default_base_url: 'http://localhost:20128/v1' }
    ];

    const rowsHtml = catalog.map(function (p) {
      const probe = state.probeResults[p.id];
      const isProbing = Boolean(state.probingMap[p.id]);
      const keyVal = f.providerKeys[p.id] || '';
      const urlVal = f.providerUrls[p.id] != null ? f.providerUrls[p.id] : (p.default_base_url || '');
      const keyPlaceholder = p.configured ? t('apiKeyKeepPlaceholder') : t('apiKeyPlaceholder');

      let statusBadge = '';
      if (probe) {
        if (probe.ok) {
          statusBadge = `<span class="aow-pill ok">&#10003; ${esc(probe.latency_ms)} ms &middot; ${esc(probe.models_detected)} ${esc(t('modelsUnit'))}</span>`;
        } else {
          statusBadge = `<span class="aow-pill err" title="${esc(probe.detail)}">&#10005; ${esc(probe.detail)}</span>`;
        }
      } else if (p.configured) {
        statusBadge = `<span class="aow-pill ok">&#10003; ${esc(t('configuredBadge'))}</span>`;
      }

      return `
        <div class="aow-provider-row" data-provider-row="${esc(p.id)}">
          <div class="aow-provider-top">
            <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
              <strong style="font-size:13px">${esc(p.name)}</strong>
              <span class="aow-pill">${esc(p.is_local ? t('localBadge') : t('cloudBadge'))}</span>
              ${p.env_key ? `<span style="font-size:11px;color:var(--muted-foreground,#64748b)" class="aow-mono">${esc(p.env_key)}</span>` : ''}
            </div>
            <div>${statusBadge}</div>
          </div>
          <div class="aow-provider-controls">
            ${p.env_key ? `
              <input
                type="password"
                autocomplete="off"
                class="aow-input aow-mono"
                data-prov-key="${esc(p.id)}"
                value="${esc(keyVal)}"
                placeholder="${esc(keyPlaceholder)}"
              />
            ` : ''}
            ${p.is_local ? `
              <input
                type="text"
                class="aow-input aow-mono"
                data-prov-url="${esc(p.id)}"
                value="${esc(urlVal)}"
                placeholder="${esc(p.default_base_url || '')}"
                aria-label="${esc(t('baseUrlLabel'))}"
              />
            ` : ''}
            <button type="button" class="aow-btn" data-test-provider="${esc(p.id)}" ${isProbing ? 'disabled' : ''}>
              ${esc(isProbing ? t('testingBtn') : t('testBtn'))}
            </button>
          </div>
        </div>
      `;
    }).join('');

    return `
      <h3 class="aow-section-title">${esc(t('step2Title'))}</h3>
      <p class="aow-section-desc">${esc(t('step2Desc'))}</p>
      <label class="aow-zero-egress-card" for="aow-zero-egress">
        <input id="aow-zero-egress" type="checkbox" ${f.zero_egress ? 'checked' : ''} style="margin-top:3px" />
        <div>
          <div style="font-size:13px;font-weight:700">${esc(t('zeroEgressTitle'))}</div>
          <div style="font-size:11.5px;color:var(--muted-foreground,#64748b);margin-top:2px">${esc(t('zeroEgressDesc'))}</div>
        </div>
      </label>
      <div class="aow-provider-list">${rowsHtml}</div>
    `;
  }

  function renderStep3() {
    const f = state.form;
    const ch = (state.statusData && state.statusData.channels) || {};
    const emailPassPlaceholder = ch.email_password_configured ? t('apiKeyKeepPlaceholder') : '••••••••';
    const tgPlaceholder = ch.telegram_bot_configured ? t('apiKeyKeepPlaceholder') : '123456789:ABCdef...';

    return `
      <h3 class="aow-section-title">${esc(t('step3Title'))}</h3>
      <p class="aow-section-desc">${esc(t('step3Desc'))}</p>

      <div class="aow-subbox">
        <div class="aow-subbox-title">${esc(t('vaultSection'))}</div>
        <div class="aow-field">
          <label class="aow-label" for="aow-vault-path">${esc(t('vaultPath'))}</label>
          <input id="aow-vault-path" class="aow-input aow-mono" type="text" value="${esc(f.obsidian_vault_path)}" placeholder="${esc(t('vaultPlaceholder'))}" />
        </div>
      </div>

      <div class="aow-subbox">
        <div class="aow-subbox-title">${esc(t('emailSection'))}</div>
        <div class="aow-grid-2">
          <div class="aow-field">
            <label class="aow-label" for="aow-imap-host">${esc(t('imapHost'))}</label>
            <input id="aow-imap-host" class="aow-input aow-mono" type="text" value="${esc(f.imap_host)}" placeholder="imap.example.com" />
          </div>
          <div class="aow-field">
            <label class="aow-label" for="aow-imap-port">${esc(t('imapPort'))}</label>
            <input id="aow-imap-port" class="aow-input aow-mono" type="number" min="1" max="65535" value="${esc(f.imap_port)}" />
          </div>
          <div class="aow-field">
            <label class="aow-label" for="aow-smtp-host">${esc(t('smtpHost'))}</label>
            <input id="aow-smtp-host" class="aow-input aow-mono" type="text" value="${esc(f.smtp_host)}" placeholder="smtp.example.com" />
          </div>
          <div class="aow-field">
            <label class="aow-label" for="aow-smtp-port">${esc(t('smtpPort'))}</label>
            <input id="aow-smtp-port" class="aow-input aow-mono" type="number" min="1" max="65535" value="${esc(f.smtp_port)}" />
          </div>
          <div class="aow-field">
            <label class="aow-label" for="aow-email-user">${esc(t('emailUser'))}</label>
            <input id="aow-email-user" class="aow-input aow-mono" type="text" value="${esc(f.email_user)}" placeholder="ops@example.com" />
          </div>
          <div class="aow-field">
            <label class="aow-label" for="aow-email-pass">${esc(t('emailPass'))}</label>
            <input id="aow-email-pass" class="aow-input aow-mono" type="password" autocomplete="off" value="${esc(f.email_password)}" placeholder="${esc(emailPassPlaceholder)}" />
          </div>
        </div>
      </div>

      <div class="aow-subbox" style="margin-bottom:0">
        <div class="aow-subbox-title">${esc(t('telegramSection'))}</div>
        <div class="aow-grid-2">
          <div class="aow-field">
            <label class="aow-label" for="aow-tg-token">${esc(t('tgToken'))}</label>
            <input id="aow-tg-token" class="aow-input aow-mono" type="password" autocomplete="off" value="${esc(f.bot_token)}" placeholder="${esc(tgPlaceholder)}" />
          </div>
          <div class="aow-field">
            <label class="aow-label" for="aow-tg-chat">${esc(t('tgChatId'))}</label>
            <input id="aow-tg-chat" class="aow-input aow-mono" type="text" value="${esc(f.chat_id)}" placeholder="e.g. 123456789" />
          </div>
          <label class="aow-field span-2" style="flex-direction:row;align-items:center;gap:8px;cursor:pointer;margin-top:4px">
            <input id="aow-tg-verify" type="checkbox" ${f.verify_telegram ? 'checked' : ''} />
            <span style="font-size:12px">${esc(t('tgVerify'))}</span>
          </label>
        </div>
      </div>
    `;
  }

  function renderStep4() {
    const domains = (state.statusData && state.statusData.specialist_domains) || [];
    const activeSet = new Set(state.form.active_domains);
    let activeSpecCount = 0;
    let totalSpecCount = 0;

    domains.forEach(function (d) {
      const cnt = Number(d.specialist_count || 0);
      totalSpecCount += cnt;
      if (activeSet.has(d.id)) activeSpecCount += cnt;
    });

    const summaryText = t('selectedSummary')
      .replace('{domains}', String(activeSet.size))
      .replace('{totalDomains}', String(domains.length || 8))
      .replace('{specialists}', String(activeSpecCount))
      .replace('{totalSpecialists}', String(totalSpecCount || 70));

    const cardsHtml = domains.map(function (d) {
      const checked = activeSet.has(d.id);
      const title = state.lang === 'de' ? d.category_de : d.category_en;
      const desc = state.lang === 'de' ? d.description_de : d.description_en;
      const countLabel = t('specialistsCount').replace('{count}', String(d.specialist_count));
      return `
        <label class="aow-domain-card ${checked ? 'is-checked' : ''}">
          <input type="checkbox" data-domain-id="${esc(d.id)}" ${checked ? 'checked' : ''} style="margin-top:3px" />
          <div style="flex:1;min-width:0">
            <div style="display:flex;align-items:center;justify-content:space-between;gap:8px">
              <strong style="font-size:12.5px">${esc(title)}</strong>
              <span class="aow-pill">${esc(countLabel)}</span>
            </div>
            <div style="font-size:11.5px;color:var(--muted-foreground,#64748b);margin-top:4px">${esc(desc)}</div>
          </div>
        </label>
      `;
    }).join('');

    return `
      <h3 class="aow-section-title">${esc(t('step4Title'))}</h3>
      <p class="aow-section-desc">${esc(t('step4Desc'))}</p>
      <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:12px;flex-wrap:wrap">
        <span class="aow-mono" style="font-size:12px;font-weight:700;color:#0284c7">${esc(summaryText)}</span>
        <div style="display:flex;gap:8px">
          <button type="button" class="aow-btn" id="aow-select-all-domains">${esc(t('selectAll'))}</button>
          <button type="button" class="aow-btn" id="aow-select-core-domains">${esc(t('selectCore'))}</button>
        </div>
      </div>
      <div class="aow-domain-grid">${cardsHtml}</div>
    `;
  }

  function captureCurrentStepInputs(root) {
    if (!root) return;
    const f = state.form;
    if (state.step === 0) {
      const cn = root.querySelector('#aow-company-name');
      if (cn) f.company_name = cn.value.trim();
      const lf = root.querySelector('#aow-legal-form');
      if (lf) f.legal_form = lf.value.trim();
      const ad = root.querySelector('#aow-address');
      if (ad) f.address = ad.value.trim();
      const ti = root.querySelector('#aow-tax-id');
      if (ti) f.tax_id = ti.value.trim();
      const vi = root.querySelector('#aow-vat-id');
      if (vi) f.vat_id = vi.value.trim();
      const ib = root.querySelector('#aow-iban');
      if (ib) f.iban = ib.value.trim();
      const bc = root.querySelector('#aow-bic');
      if (bc) f.bic = bc.value.trim();
      const cu = root.querySelector('#aow-currency');
      if (cu) f.currency = cu.value;
      const lg = root.querySelector('#aow-language');
      if (lg) f.language = lg.value;
    } else if (state.step === 1) {
      const ze = root.querySelector('#aow-zero-egress');
      if (ze) f.zero_egress = ze.checked;
      root.querySelectorAll('[data-prov-key]').forEach(function (inp) {
        f.providerKeys[inp.getAttribute('data-prov-key')] = inp.value;
      });
      root.querySelectorAll('[data-prov-url]').forEach(function (inp) {
        f.providerUrls[inp.getAttribute('data-prov-url')] = inp.value.trim();
      });
    } else if (state.step === 2) {
      const vp = root.querySelector('#aow-vault-path');
      if (vp) f.obsidian_vault_path = vp.value.trim();
      const ih = root.querySelector('#aow-imap-host');
      if (ih) f.imap_host = ih.value.trim();
      const ip = root.querySelector('#aow-imap-port');
      if (ip) f.imap_port = Number(ip.value || 993);
      const sh = root.querySelector('#aow-smtp-host');
      if (sh) f.smtp_host = sh.value.trim();
      const sp = root.querySelector('#aow-smtp-port');
      if (sp) f.smtp_port = Number(sp.value || 587);
      const eu = root.querySelector('#aow-email-user');
      if (eu) f.email_user = eu.value.trim();
      const ep = root.querySelector('#aow-email-pass');
      if (ep) f.email_password = ep.value;
      const tt = root.querySelector('#aow-tg-token');
      if (tt) f.bot_token = tt.value;
      const tc = root.querySelector('#aow-tg-chat');
      if (tc) f.chat_id = tc.value.trim();
      const tv = root.querySelector('#aow-tg-verify');
      if (tv) f.verify_telegram = tv.checked;
    } else if (state.step === 3) {
      const selected = [];
      root.querySelectorAll('[data-domain-id]').forEach(function (cb) {
        if (cb.checked) selected.push(cb.getAttribute('data-domain-id'));
      });
      f.active_domains = selected;
    }
  }

  function validateStep(stepIndex) {
    if (stepIndex === 0 && !state.form.company_name.trim()) {
      state.errorMsg = t('errCompanyRequired');
      return false;
    }
    if (stepIndex === 3 && state.form.active_domains.length === 0) {
      state.errorMsg = t('errDomainRequired');
      return false;
    }
    state.errorMsg = '';
    return true;
  }

  function applyUiLanguage(newLang) {
    const normalized = newLang === 'de' ? 'de' : 'en';
    state.lang = normalized;
    state.form.language = normalized;
    try {
      localStorage.setItem('archon_lang', normalized);
      localStorage.setItem('archon_language', normalized);
      if (window.archonI18n && typeof window.archonI18n.setLanguage === 'function') {
        window.archonI18n.setLanguage(normalized);
      }
    } catch (_) { /* ignore storage errors */ }
    renderModal();
  }

  async function handleTestProvider(providerId) {
    const overlay = document.getElementById(MODAL_ID);
    captureCurrentStepInputs(overlay);
    state.probingMap[providerId] = true;
    state.errorMsg = '';
    renderModal();

    try {
      const res = await fetch('/api/onboarding/test-provider', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          provider: providerId,
          api_key: state.form.providerKeys[providerId] || '',
          base_url: state.form.providerUrls[providerId] || null
        })
      });
      const data = await res.json().catch(function () { return {}; });
      if (!res.ok) {
        state.probeResults[providerId] = {
          ok: false,
          latency_ms: 0,
          models_detected: 0,
          detail: data.detail || ('HTTP ' + res.status)
        };
      } else {
        state.probeResults[providerId] = data;
      }
    } catch (err) {
      state.probeResults[providerId] = {
        ok: false,
        latency_ms: 0,
        models_detected: 0,
        detail: err && err.message ? err.message : 'Network error'
      };
    } finally {
      state.probingMap[providerId] = false;
      renderModal();
    }
  }

  async function handleSkip() {
    if (state.busy) return;
    state.busy = true;
    state.errorMsg = '';
    renderModal();
    try {
      const res = await fetch('/api/onboarding/skip', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({})
      });
      if (!res.ok) {
        const d = await res.json().catch(function () { return {}; });
        state.errorMsg = d.detail || ('HTTP ' + res.status);
        state.busy = false;
        renderModal();
        return;
      }
      state.busy = false;
      closeWizard();
    } catch (err) {
      state.busy = false;
      state.errorMsg = err && err.message ? err.message : 'Failed to skip setup.';
      renderModal();
    }
  }

  async function handleComplete() {
    const overlay = document.getElementById(MODAL_ID);
    captureCurrentStepInputs(overlay);
    if (!validateStep(0)) {
      state.step = 0;
      renderModal();
      return;
    }
    if (!validateStep(3)) {
      renderModal();
      return;
    }

    state.busy = true;
    state.errorMsg = '';
    renderModal();

    const f = state.form;
    const payload = {
      company_profile: {
        company_name: f.company_name,
        legal_form: f.legal_form,
        address: f.address,
        tax_id: f.tax_id,
        vat_id: f.vat_id,
        iban: f.iban,
        bic: f.bic,
        currency: f.currency,
        language: f.language
      },
      zero_egress: Boolean(f.zero_egress),
      providers: {
        api_keys: Object.assign({}, f.providerKeys),
        base_urls: Object.assign({}, f.providerUrls),
        zero_egress: Boolean(f.zero_egress)
      },
      channels: {
        obsidian_vault_path: f.obsidian_vault_path || './obsidian_vault',
        imap_host: f.imap_host,
        imap_port: Number(f.imap_port || 993),
        smtp_host: f.smtp_host,
        smtp_port: Number(f.smtp_port || 587),
        email_user: f.email_user,
        email_password: f.email_password || null,
        bot_token: f.bot_token || null,
        chat_id: f.chat_id,
        verify_telegram: Boolean(f.verify_telegram)
      },
      active_domains: f.active_domains.slice(),
      sync_souls: true
    };

    try {
      const res = await fetch('/api/onboarding/complete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await res.json().catch(function () { return {}; });
      if (!res.ok) {
        state.errorMsg = data.detail || ('HTTP ' + res.status);
        state.busy = false;
        renderModal();
        return;
      }
      applyUiLanguage(f.language);
      state.busy = false;
      closeWizard();
      showCompletionBanner(t('completedToast'));
    } catch (err) {
      state.busy = false;
      state.errorMsg = err && err.message ? err.message : 'Network error saving configuration.';
      renderModal();
    }
  }

  function showCompletionBanner(message) {
    const toast = document.createElement('div');
    toast.style.cssText = 'position:fixed;bottom:22px;right:22px;z-index:99995;background:#10b981;color:#fff;padding:11px 18px;border-radius:10px;font-family:Outfit,sans-serif;font-size:13px;font-weight:700;box-shadow:0 12px 30px rgba(0,0,0,.25)';
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(function () {
      if (toast.parentNode) toast.parentNode.removeChild(toast);
    }, 3600);
  }

  function ensureOverlay() {
    injectStyles();
    let el = document.getElementById(MODAL_ID);
    if (!el) {
      el = document.createElement('div');
      el.id = MODAL_ID;
      el.setAttribute('role', 'dialog');
      el.setAttribute('aria-modal', 'true');
      document.body.appendChild(el);
    }
    return el;
  }

  function renderModal() {
    const overlay = ensureOverlay();
    const stepsLabels = t('steps');
    let bodyContent = '';
    if (state.step === 0) bodyContent = renderStep1();
    else if (state.step === 1) bodyContent = renderStep2();
    else if (state.step === 2) bodyContent = renderStep3();
    else bodyContent = renderStep4();

    const isLast = state.step === 3;

    overlay.innerHTML = `
      <div class="aow-dialog">
        <div class="aow-header">
          <div>
            <span class="aow-badge">${esc(t('badge'))}</span>
            <h2 class="aow-title">${esc(t('title'))}</h2>
            <p class="aow-subtitle">${esc(t('subtitle'))}</p>
          </div>
          <div style="display:flex;align-items:center;gap:8px">
            <div class="aow-lang-switch" role="group" aria-label="Language">
              <button type="button" class="aow-lang-btn ${state.lang === 'en' ? 'is-active' : ''}" data-set-lang="en">EN</button>
              <button type="button" class="aow-lang-btn ${state.lang === 'de' ? 'is-active' : ''}" data-set-lang="de">DE</button>
            </div>
            <button type="button" class="aow-btn aow-btn-ghost" id="aow-close-x" aria-label="${esc(t('closeLabel'))}" style="padding:5px 9px;font-size:15px">&times;</button>
          </div>
        </div>

        <div class="aow-stepper">
          ${stepsLabels.map(function (lbl, idx) {
            const cls = idx === state.step ? 'is-active' : (idx < state.step ? 'is-done' : '');
            return `<button type="button" class="aow-step-pill ${cls}" data-goto-step="${idx}">${esc(lbl)}</button>`;
          }).join('')}
        </div>

        <div class="aow-body">${bodyContent}</div>

        ${state.errorMsg ? `<div class="aow-error">${esc(state.errorMsg)}</div>` : ''}

        <div class="aow-footer">
          <button type="button" class="aow-btn aow-btn-ghost" id="aow-skip-btn" ${state.busy ? 'disabled' : ''}>
            ${esc(t('skipBtn'))}
          </button>
          <div style="display:flex;gap:8px;align-items:center">
            ${state.step > 0 ? `<button type="button" class="aow-btn" id="aow-back-btn" ${state.busy ? 'disabled' : ''}>${esc(t('backBtn'))}</button>` : ''}
            ${!isLast
              ? `<button type="button" class="aow-btn aow-btn-primary" id="aow-next-btn" ${state.busy ? 'disabled' : ''}>${esc(t('nextBtn'))}</button>`
              : `<button type="button" class="aow-btn aow-btn-primary" id="aow-finish-btn" ${state.busy ? 'disabled' : ''}>${esc(state.busy ? t('savingBtn') : t('finishBtn'))}</button>`
            }
          </div>
        </div>
      </div>
    `;

    bindModalEvents(overlay);
  }

  function bindModalEvents(overlay) {
    overlay.querySelectorAll('[data-set-lang]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        captureCurrentStepInputs(overlay);
        applyUiLanguage(btn.getAttribute('data-set-lang'));
      });
    });

    const langSelect = overlay.querySelector('#aow-language');
    if (langSelect) {
      langSelect.addEventListener('change', function () {
        captureCurrentStepInputs(overlay);
        applyUiLanguage(langSelect.value);
      });
    }

    const closeX = overlay.querySelector('#aow-close-x');
    if (closeX) {
      closeX.addEventListener('click', function () {
        closeWizard();
      });
    }

    overlay.querySelectorAll('[data-goto-step]').forEach(function (pill) {
      pill.addEventListener('click', function () {
        const target = Number(pill.getAttribute('data-goto-step'));
        captureCurrentStepInputs(overlay);
        if (target > 0 && state.step === 0 && !validateStep(0)) {
          renderModal();
          return;
        }
        state.errorMsg = '';
        state.step = target;
        renderModal();
      });
    });

    overlay.querySelectorAll('[data-test-provider]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        handleTestProvider(btn.getAttribute('data-test-provider'));
      });
    });

    overlay.querySelectorAll('[data-domain-id]').forEach(function (cb) {
      cb.addEventListener('change', function () {
        captureCurrentStepInputs(overlay);
        state.errorMsg = '';
        renderModal();
      });
    });

    const selAll = overlay.querySelector('#aow-select-all-domains');
    if (selAll) {
      selAll.addEventListener('click', function () {
        const doms = (state.statusData && state.statusData.specialist_domains) || [];
        state.form.active_domains = doms.map(function (d) { return d.id; });
        state.errorMsg = '';
        renderModal();
      });
    }

    const selCore = overlay.querySelector('#aow-select-core-domains');
    if (selCore) {
      selCore.addEventListener('click', function () {
        state.form.active_domains = [
          'strategy_leadership',
          'legal_tax_compliance',
          'sales_crm_growth',
          'tech_software_data'
        ];
        state.errorMsg = '';
        renderModal();
      });
    }

    const skipBtn = overlay.querySelector('#aow-skip-btn');
    if (skipBtn) skipBtn.addEventListener('click', handleSkip);

    const backBtn = overlay.querySelector('#aow-back-btn');
    if (backBtn) {
      backBtn.addEventListener('click', function () {
        captureCurrentStepInputs(overlay);
        state.errorMsg = '';
        state.step = Math.max(0, state.step - 1);
        renderModal();
      });
    }

    const nextBtn = overlay.querySelector('#aow-next-btn');
    if (nextBtn) {
      nextBtn.addEventListener('click', function () {
        captureCurrentStepInputs(overlay);
        if (!validateStep(state.step)) {
          renderModal();
          return;
        }
        state.step = Math.min(3, state.step + 1);
        renderModal();
      });
    }

    const finishBtn = overlay.querySelector('#aow-finish-btn');
    if (finishBtn) finishBtn.addEventListener('click', handleComplete);
  }

  function closeWizard() {
    const el = document.getElementById(MODAL_ID);
    if (el) el.classList.remove('is-open');
  }

  async function openWizard(options) {
    const opts = options || {};
    try {
      const res = await fetch('/api/onboarding/status');
      if (res.ok) {
        const data = await res.json();
        if (data.demo_mode && !opts.force) {
          return data;
        }
        hydrateStateFromServer(data);
      }
    } catch (_) { /* render with local defaults if offline */ }

    state.step = typeof opts.step === 'number' ? Math.max(0, Math.min(3, opts.step)) : 0;
    state.errorMsg = '';
    renderModal();
    const overlay = ensureOverlay();
    overlay.classList.add('is-open');
    return state.statusData;
  }

  async function bootCheck() {
    try {
      const authGate = document.getElementById('archon-auth-gate');
      if (authGate && authGate.style.display === 'flex') {
        return;
      }
      const res = await fetch('/api/onboarding/status');
      if (!res.ok) return;
      const data = await res.json();
      if (!data || data.demo_mode || !data.auto_open) {
        return;
      }
      hydrateStateFromServer(data);
      state.step = 0;
      state.errorMsg = '';
      renderModal();
      ensureOverlay().classList.add('is-open');
    } catch (_) { /* silent when router not mounted or unauthenticated */ }
  }

  window.openArchonSetupWizard = function (options) {
    return openWizard(Object.assign({ force: false }, options || {}));
  };

  window.ArchonOnboardingWizard = {
    open: window.openArchonSetupWizard,
    close: closeWizard,
    bootCheck: bootCheck
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bootCheck);
  } else {
    bootCheck();
  }
})();
