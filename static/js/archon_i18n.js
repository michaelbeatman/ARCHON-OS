/**
 * static/js/archon_i18n.js
 * Zentraler Internationalisierungs-Engine (i18n) für Archon OS 2026.
 * Unterstützt 9 Weltsprachen: de, en, es, fr, pt, ru, ja, ko, zh.
 * Reaktive DOM-Aktualisierung, Fallback-Strategie und Settings-Synchronisation.
 */

class ArchonI18n {
  constructor() {
    this.supportedLanguages = {
      de: { name: 'Deutsch', flag: '🇩🇪', native: 'Deutsch' },
      en: { name: 'English', flag: '🇺🇸', native: 'English' },
      es: { name: 'Español', flag: '🇪🇸', native: 'Español' },
      fr: { name: 'Français', flag: '🇫🇷', native: 'Français' },
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
      console.log(`[i18n] Archon i18n initialized. Active language: ${this.currentLang} (${this.supportedLanguages[this.currentLang].native})`);
    } catch (err) {
      console.warn('[i18n] Error initializing i18n:', err);
    }
  }

  async loadLocale(lang) {
    if (this.cache[lang]) return this.cache[lang];
    try {
      const res = await fetch(`/static/locales/${lang}.json?v=${Date.now()}`);
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
    
    // 1. Try current language
    let val = this.resolvePath(this.cache[this.currentLang], parts);
    if (val !== undefined && val !== null) return val;

    // 2. Fallback to default language (de)
    val = this.resolvePath(this.cache[this.defaultLang], parts);
    if (val !== undefined && val !== null) return val;

    // 3. User fallback or last key part
    return fallback || parts[parts.length - 1];
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
}

// Global Singleton
window.archonI18n = new ArchonI18n();

// Auto-initialize when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => window.archonI18n.init());
} else {
  window.archonI18n.init();
}
