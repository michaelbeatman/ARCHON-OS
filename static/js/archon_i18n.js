/**
 * static/js/archon_i18n.js
 * Zentraler Internationalisierungs-Engine (i18n) für Archon OS 2026.
 * Unterstützt 11 Weltsprachen: de, en, es, fr, it, nl, pt, ru, ja, ko, zh.
 * Reaktive DOM-Aktualisierung, Fallback-Strategie und Settings-Synchronisation.
 */

/**
 * Build-Version der Kataloge. Ersetzt den früheren Zeitstempel-Cache-Buster:
 * der Query-Parameter ist damit stabil und die Locale-Dateien wieder
 * HTTP-cachebar. Bei jeder Katalogänderung hochzählen.
 */
const ARCHON_LOCALE_VERSION = '2026-11-11.13';

/** Einzige Attribut-Familie, die translateDOM() anfasst. */
const I18N_SELECTOR = '[data-i18n], [data-i18n-title], [data-i18n-placeholder]';

class ArchonI18n {
  constructor() {
    this.supportedLanguages = {
      de: { name: 'Deutsch', flag: '🇩🇪', native: 'Deutsch' },
      en: { name: 'English', flag: '🇺🇸', native: 'English' },
      es: { name: 'Español', flag: '🇪🇸', native: 'Español' },
      fr: { name: 'Français', flag: '🇫🇷', native: 'Français' },
      it: { name: 'Italiano', flag: '🇮🇹', native: 'Italiano' },
      nl: { name: 'Nederlands', flag: '🇳🇱', native: 'Nederlands' },
      pt: { name: 'Português', flag: '🇵🇹', native: 'Português' },
      ru: { name: 'Русский', flag: '🇷🇺', native: 'Русский' },
      ja: { name: '日本語', flag: '🇯🇵', native: '日本語' },
      ko: { name: '한국어', flag: '🇰🇷', native: '한국어' },
      zh: { name: '简体中文', flag: '🇨🇳', native: '简体中文' }
    };

    this.defaultLang = 'de';
    this.currentLang = localStorage.getItem('archon_language') || this.defaultLang;
    if (!this.supportedLanguages[this.currentLang]) {
      this.currentLang = this.defaultLang;
    }

    this.cache = {};
    this.initialized = false;
    this.observer = null;
    // Renderer-Registry: Views/Module registrieren sich hier für language-changed
    this.renderers = new Map(); // key -> { render: fn, ctx: any }
  }

  async init() {
    try {
      await this.loadLocale(this.defaultLang);
      if (this.currentLang !== this.defaultLang) {
        await this.loadLocale(this.currentLang);
      }
      this.initialized = true;
      document.documentElement.lang = this.currentLang;
      this.translateDOM();
      this.syncSettingsDropdown();
      // Observer erst nach dem ersten translateDOM() starten, sonst würde
      // der initiale Schreibvorgang als Mutation zurückgemeldet.
      this.startObserver();
      console.log(`[i18n] Archon i18n initialized. Active language: ${this.currentLang} (${this.supportedLanguages[this.currentLang].native})`);
    } catch (err) {
      console.warn('[i18n] Error initializing i18n:', err);
    }
  }

  async loadLocale(lang) {
    if (this.cache[lang]) return this.cache[lang];
    try {
      const res = await fetch(`/static/locales/${lang}.json?v=${ARCHON_LOCALE_VERSION}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      this.cache[lang] = data;
      return data;
    } catch (e) {
      console.warn(`[i18n] Could not load locale '${lang}', falling back to in-memory data:`, e);
      return this.cache[this.defaultLang] || {};
    }
  }

  t(key, fallback = '') {
    if (!key) return fallback;
    const parts = key.split('.');

    // 1. Aktive Sprache (nur Strings sind renderbar; Plural-Objekte nicht)
    let val = this.resolvePath(this.cache[this.currentLang], parts);
    if (typeof val === 'string') return val;

    // 2. Referenzsprache (de)
    val = this.resolvePath(this.cache[this.defaultLang], parts);
    if (typeof val === 'string') return val;

    // 3. Expliziter Aufruf-Fallback (z. B. vorhandener DOM-Text)
    if (fallback) return fallback;

    // 4. Kein Key-Rendering mehr: leerer String plus Warnung.
    //    Ein gerendertes Key-Segment (früher "operations") ist falscher Text.
    console.warn(`[i18n] MISSING ${this.currentLang}:${key}`);
    return '';
  }

  /**
   * Liefert die CLDR-Pluralkategorie für Sprache + Anzahl zurück.
   * Kategorien: zero, one, two, few, many, other
   */
  getPluralCategory(lang, count) {
    try {
      const pr = new Intl.PluralRules(lang, { type: 'cardinal' });
      return pr.select(count);
    } catch (e) {
      // Fallback: germanic rule (one for 1, other otherwise)
      return count === 1 ? 'one' : 'other';
    }
  }

  /**
   * Übersetzt einen Key mit Plural-Unterstützung.
   * Erwartet im Katalog entweder:
   *   - String (einfacher Fallback)
   *   - Objekt mit CLDR-Kategorien: { "one": "...", "other": "..." }
   * Platzhalter {count} werden automatisch ersetzt.
   */
  tc(key, count, params = {}) {
    if (!key) return '';
    const parts = key.split('.');

    // Lookup in aktiver Sprache
    let val = this.resolvePath(this.cache[this.currentLang], parts);
    // Fallback auf Referenzsprache
    if (val === undefined || val === null) {
      val = this.resolvePath(this.cache[this.defaultLang], parts);
    }

    let result = '';
    if (typeof val === 'string') {
      // Einfacher String → als 'other' behandeln
      result = val;
    } else if (val && typeof val === 'object') {
      // Plural-Objekt
      const cat = this.getPluralCategory(this.currentLang, count);
      // CLDR-Fallback-Kette: exact → other
      result = val[cat] || val.other || '';
    } else {
      console.warn(`[i18n] MISSING ${this.currentLang}:${key} (plural)`);
      return '';
    }

    // Platzhalter ersetzen: {count} + custom params
    const allParams = { count, ...params };
    return result.replace(/\{(\w+)\}/g, (_, k) => allParams[k] !== undefined ? String(allParams[k]) : `{${k}}`);
  }

  resolvePath(obj, parts) {
    if (!obj) return undefined;
    let curr = obj;
    for (const p of parts) {
      if (curr === undefined || curr === null || typeof curr !== 'object') return undefined;
      curr = curr[p];
    }
    return curr;
  }

  async setLanguage(lang, syncBackend = true) {
    if (!this.supportedLanguages[lang]) {
      console.warn(`[i18n] Unsupported language code: ${lang}`);
      return;
    }

    this.currentLang = lang;
    localStorage.setItem('archon_language', lang);
    document.documentElement.lang = lang;

    await this.loadLocale(lang);
    this.translateDOM();
    this.syncSettingsDropdown();

    // Notify registered renderers
    this._notifyRenderers(lang);

    // Notify components
    window.dispatchEvent(new CustomEvent('archon:language-changed', {
      detail: { language: lang, meta: this.supportedLanguages[lang] }
    }));

    if (syncBackend) {
      this.syncBackendLanguage(lang);
    }
  }

  translateDOM(root = document) {
    if (!root) return;

    // Rekursionsbremse: Während des Schreibens darf der Observer keine
    // eigenen Mutationen sehen. Disconnect + takeRecords verwirft alles,
    // was durch textContent/setAttribute in diesem Lauf entsteht.
    const observer = this.observer;
    const wasObserving = Boolean(observer);
    if (wasObserving) {
      observer.takeRecords();
      observer.disconnect();
    }

    try {
      // Text content
      const elements = root.querySelectorAll('[data-i18n]');
      elements.forEach(el => {
        const key = el.getAttribute('data-i18n');
        if (key) {
          const trans = this.t(key, el.textContent.trim());
          el.textContent = trans;
        }
      });

      // Titles / tooltips
      const titleElements = root.querySelectorAll('[data-i18n-title]');
      titleElements.forEach(el => {
        const key = el.getAttribute('data-i18n-title');
        if (key) {
          el.setAttribute('title', this.t(key, el.getAttribute('title') || ''));
        }
      });

      // Placeholders
      const placeholderElements = root.querySelectorAll('[data-i18n-placeholder]');
      placeholderElements.forEach(el => {
        const key = el.getAttribute('data-i18n-placeholder');
        if (key) {
          el.setAttribute('placeholder', this.t(key, el.getAttribute('placeholder') || ''));
        }
      });

      // Der eingefügte Knoten selbst (querySelectorAll liefert nur Nachfahren).
      if (root.nodeType === 1) {
        const key = root.getAttribute('data-i18n');
        if (key) root.textContent = this.t(key, root.textContent.trim());
        const titleKey = root.getAttribute('data-i18n-title');
        if (titleKey) root.setAttribute('title', this.t(titleKey, root.getAttribute('title') || ''));
        const phKey = root.getAttribute('data-i18n-placeholder');
        if (phKey) root.setAttribute('placeholder', this.t(phKey, root.getAttribute('placeholder') || ''));
      }
    } finally {
      if (wasObserving) {
        observer.takeRecords();
        observer.observe(document.body, { childList: true, subtree: true });
      }
    }
  }

  /**
   * Beobachtet nachgeladene DOM-Fragmente und übersetzt neue Teilbäume.
   * Nur Knoten mit data-i18n*-Attributen werden angefasst; ohne passende
   * Anker entsteht weder Arbeit noch eine neue Mutation.
   */
  startObserver() {
    if (this.observer || typeof MutationObserver === 'undefined') return;
    this.observer = new MutationObserver(mutations => {
      for (const mutation of mutations) {
        for (const node of mutation.addedNodes) {
          if (node.nodeType !== 1) continue;
          if (node.matches(I18N_SELECTOR) || node.querySelector(I18N_SELECTOR)) {
            this.translateDOM(node);
          }
        }
      }
    });
    this.observer.observe(document.body, { childList: true, subtree: true });
  }

  syncSettingsDropdown() {
    const sel = document.getElementById('hermes-cfg-language');
    if (sel && sel.value !== this.currentLang) {
      sel.value = this.currentLang;
    }
  }

  async syncBackendLanguage(lang) {
    try {
      await fetch('/api/system/language', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ language: lang })
      });
    } catch (err) {
      console.warn('[i18n] Could not sync language to backend:', err);
    }
  }

  /**
   * Registriert einen Renderer, der bei Sprachwechsel neu gerendert wird.
   * @param {string} key - Eindeutiger Key für den Renderer (z. B. 'view:finance', 'module:kanban')
   * @param {Function} renderFn - Funktion, die den View/Modul neu rendert (erhält `lang` als Argument)
   * @param {any} ctx - Optionaler Kontext, der an renderFn übergeben wird
   */
  registerRenderer(key, renderFn, ctx = null) {
    if (typeof renderFn !== 'function') {
      console.warn(`[i18n] registerRenderer: renderFn für '${key}' ist keine Funktion`);
      return;
    }
    this.renderers.set(key, { render: renderFn, ctx });
  }

  /**
   * Entfernt einen Renderer aus der Registry.
   */
  unregisterRenderer(key) {
    this.renderers.delete(key);
  }

  /**
   * Intern: Ruft alle registrierten Renderer mit der neuen Sprache auf.
   */
  _notifyRenderers(lang) {
    for (const [key, { render, ctx }] of this.renderers) {
      try {
        render(lang, ctx);
      } catch (e) {
        console.error(`[i18n] Renderer '${key}' fehlgeschlagen:`, e);
      }
    }
  }
}

// Global Singleton
window.archonI18n = new ArchonI18n();

// Auto-initialize when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => window.archonI18n.init());
} else {
  window.archonI18n.init();
}
