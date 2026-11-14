/**
 * static/js/settings_search.js
 * Intelligente Volltextsuche über alle Tabs, Kategorien und Einstellungen
 * des Archon OS System Control Centers.
 */

(function () {
  'use strict';

  let searchIndex = null;
  let isIndexing = false;
  let debounceTimer = null;
  let activeQuery = '';

  const TAB_METADATA = {
    kernel: { name: 'HERMES CORE', icon: 'cpu', color: 'text-indigo-500' },
    autonomy: { name: 'AUTONOMIE & MODULE (36)', icon: 'shield', color: 'text-emerald-500' },
    services: { name: 'CONTAINER & DIENSTE', icon: 'server', color: 'text-amber-500' },
    routing: { name: 'PROVIDER & GATEWAY', icon: 'git-branch', color: 'text-purple-500' },
    keys: { name: 'API-KEYS & ACCESS', icon: 'key', color: 'text-rose-500' },
    frameworks: { name: 'METHODIKEN', icon: 'layers', color: 'text-blue-500' },
    plugins: { name: 'PLUGINS', icon: 'package', color: 'text-cyan-500' },
    comm: { name: 'KOMMUNIKATION', icon: 'message-square', color: 'text-teal-500' },
    design: { name: 'DESIGN', icon: 'palette', color: 'text-pink-500' },
    users: { name: 'BENUTZER & ROLLEN', icon: 'users', color: 'text-sky-500' },
    update: { name: 'SYSTEM-UPDATE', icon: 'refresh-cw', color: 'text-orange-500' }
  };

  // Kuratierte Quick-Treffer für häufig gesuchte Einstellungen
  const CURATED_SETTINGS = [
    {
      tab: 'kernel',
      elementId: 'hermes-cfg-language',
      title: 'Systemsprache (Language / Lokalisierung)',
      section: '3. Anzeige, Streaming & Benutzeroberfläche',
      description: 'Zentrale Oberflächen- und Dialogsprache für Archon OS (Deutsch, English, Español, Français, Português, Русский, 日本語, 한국어, 简体中文).',
      keywords: ['sprache', 'language', 'deutsch', 'englisch', 'german', 'english', 'spanisch', 'französisch', 'portugiesisch', 'russisch', 'japanisch', 'koreanisch', 'chinesisch', 'i18n', 'lokalisierung', 'übersetzung', 'systemsprache']
    },
    {
      tab: 'kernel',
      elementId: 'hermes-sec-13',
      title: 'Spracherkennung (STT) & Sprachausgabe (Voice / TTS)',
      section: '13. Spracherkennung & Sprachausgabe',
      description: 'Audio-Transkription (Groq Whisper) und automatische Sprachausgabe (Edge-TTS, ElevenLabs). Audio-Sprache und Stimmen-Modell.',
      keywords: ['voice', 'stimme', 'audio', 'tts', 'stt', 'whisper', 'vorlesen', 'mikrofon', 'sprache', 'speech']
    },
    {
      tab: 'kernel',
      elementId: 'hermes-cfg-model-default',
      title: 'Standard LLM-Modell & Provider-Routing',
      section: '1. Standard-Modell & Provider-Routing',
      description: 'Zentrales KI-Gehirn für autonome Aufgaben (z. B. z-ai/glm-5.3, Claude 3.5 Sonnet, Gemini 2.5 Flash, GPT-4o).',
      keywords: ['modell', 'model', 'llm', 'glm', 'claude', 'gemini', 'gpt', 'provider', 'openrouter', 'standardmodell', 'ki-modell']
    },
    {
      tab: 'kernel',
      elementId: 'hermes-sec-2',
      title: 'Kontextfenster, Token-Limits & Kompression',
      section: '2. Kontextfenster & Token-Limits',
      description: 'Maximale Kontextgröße in Tokens, Max Output Tokens, Reasoning-Tiefe und automatische Kontextkompression.',
      keywords: ['kontext', 'context', 'tokens', 'limits', 'kompression', 'reasoning', 'fenster', 'max_tokens']
    },
    {
      tab: 'users',
      elementId: 'auth-mode-toggle',
      title: 'Authentifizierungs-Modus (Einzelplatz vs. Multi-User)',
      section: 'Benutzer & Rollen (RBAC)',
      description: 'Schaltet zwischen barrierefreiem Einzelplatz-Modus (ohne Login-Zwang) und sicherem Multi-User-Betrieb mit RBAC um.',
      keywords: ['auth', 'login', 'passwort', 'einzelplatz', 'multi-user', 'anmeldung', 'sicherheit', 'schalter', 'modus', 'authentifizierung']
    },
    {
      tab: 'users',
      elementId: 'settings-users-table-body',
      title: 'Benutzerverwaltung & Rollen (Admin, Operator, Viewer)',
      section: 'Benutzer & Rollen (RBAC)',
      description: 'Benutzerkonten anlegen, bearbeiten oder löschen. Rechte vergeben: Admin (Vollzugriff), Operator (Tasks & CRM), Viewer (Nur-Lesen).',
      keywords: ['user', 'benutzer', 'account', 'rolle', 'admin', 'operator', 'viewer', 'rechte', 'rbac', 'mitarbeiter', 'kennwort']
    },
    {
      tab: 'keys',
      elementId: 'settings-tab-keys',
      title: 'API-Keys & Externe Provider-Zugänge',
      section: 'API-Keys & Access',
      description: 'Verwaltung von API-Keys für OpenAI, Anthropic, OpenRouter, DeepSeek, Groq, Google Gemini, Perplexity und interne Archon API-Schlüssel.',
      keywords: ['api', 'key', 'keys', 'token', 'openai', 'anthropic', 'openrouter', 'groq', 'deepseek', 'gemini', 'zugang', 'passwort', 'secret', 'schlüssel']
    },
    {
      tab: 'services',
      elementId: 'settings-tab-services',
      title: 'Container & Hintergrunddienste',
      section: 'Container & Dienste',
      description: 'Status und Steuerung aller Docker-Container (ARCHON-OS, Watchdog, Hermes Daemon, SearXNG, DB, Ports 8501, 8420).',
      keywords: ['docker', 'container', 'watchdog', 'daemon', 'dienst', 'dienste', 'port', 'status', 'restart', 'cpu', 'ram', 'neustart']
    },
    {
      tab: 'routing',
      elementId: 'settings-tab-routing',
      title: 'Provider-Routing & Fallback-Ketten',
      section: 'Provider & Gateway',
      description: 'LLM-Routing-Strategien, Ausweich-Provider bei Rate-Limits, Latenzoptimierung und Gateway-Endpunkte.',
      keywords: ['routing', 'gateway', 'fallback', 'provider', 'ausweich', 'latenz', 'rate-limit', 'openrouter', 'ausfallschutz']
    },
    {
      tab: 'autonomy',
      elementId: 'sec4-zero-egress-governance-card',
      title: 'Zero-Egress, Privacy-Router Hard-Block & SHA-256 LLM-Dispatch-Kette',
      section: 'Sicherheit & Zero-Egress (Modul 32)',
      description: 'Harter Fail-Closed Block bei Offline-Lokalmodell für Finanzen/Verträge/CRM, isoliertes Docker-Worker-Netz ohne Internet-Route (Internal=true) und SHA-256-Protokollierung jedes LLM-Calls.',
      keywords: ['zero-egress', 'zero egress', 'privacy-router', 'hard-block', 'hard block', 'dsgvo', 'lokal', 'ollama', 'sha-256', 'hashkette', 'audit-log', 'llm-dispatch', 'worker', 'internal', 'docker-netzwerk', 'crm', 'finanzen', 'verträge']
    },
    {
      tab: 'comm',
      elementId: 'settings-tab-comm',
      title: 'Kommunikation (Telegram, SMTP, Webhooks)',
      section: 'Kommunikations-Gateways',
      description: 'Telegram-Bot Anbindung, SMTP/E-Mail-Server, n8n-Workflow-Automatisierung und Webhook-Empfänger.',
      keywords: ['telegram', 'bot', 'mail', 'email', 'smtp', 'postfach', 'n8n', 'webhook', 'nachrichten', 'benachrichtigung']
    },
    {
      tab: 'update',
      elementId: 'settings-tab-update',
      title: 'System-Update & Git-Synchronisation',
      section: 'System-Update',
      description: 'Prüfen auf neue Updates aus dem GitHub Repository, automatische System-Snapshots und Rollback-Wiederherstellung.',
      keywords: ['update', 'git', 'snapshot', 'backup', 'pull', 'version', 'wiederherstellen', 'upgrade', 'sicherung', 'stand']
    },
    {
      tab: 'design',
      elementId: 'settings-tab-design',
      title: 'Design, Theme & Erscheinungsbild',
      section: 'Design System',
      description: 'Farbschemata (Dark Mode, Light Mode), Akzentfarben, Typografie, Sidebar-Layout und visuelle Dichte.',
      keywords: ['design', 'theme', 'dark mode', 'light mode', 'farbe', 'color', 'akzent', 'layout', 'ui', 'aussehen', 'schrift']
    },
    {
      tab: 'autonomy',
      elementId: 'settings-tab-autonomy',
      title: 'Autonomie-Level & Modul-Freigaben (36 Module)',
      section: 'Autonomie & Governance',
      description: 'Human-in-the-Loop (HITL) Bestätigungen, Berechtigungsgrenzen für Dateizugriffe, Shell-Befehle und Web-Recherche.',
      keywords: ['autonomie', 'freigabe', 'hitl', 'bestätigung', 'sicherheit', 'zero-trust', 'berechtigung', 'module', 'grenzen']
    },
    {
      tab: 'plugins',
      elementId: 'settings-tab-plugins',
      title: 'Plugins, MCP Server & JEV-Kostenoptimierung',
      section: 'Plugins & Erweiterungen',
      description: 'Model Context Protocol (MCP) Server, Tool-Pruning, FastPath-Cache und Token-Kostenoptimierer.',
      keywords: ['plugin', 'plugins', 'mcp', 'jev', 'kosten', 'cost', 'pruning', 'fastpath', 'erweiterung', 'tools']
    }
  ];

  /**
   * Baut den dynamischen Suchindex aus dem DOM auf.
   */
  function buildSearchIndex() {
    if (isIndexing) return;
    isIndexing = true;

    const items = [...CURATED_SETTINGS];
    const registeredIds = new Set(CURATED_SETTINGS.map(c => c.elementId));

    try {
      const tabs = Object.keys(TAB_METADATA);
      tabs.forEach(tabKey => {
        const pane = document.getElementById(`settings-tab-${tabKey}`);
        if (!pane) return;

        // Finde alle Cards / Sektionen im Tab
        const cards = pane.querySelectorAll('[id^="hermes-sec-"], .rounded-xl, .border');
        cards.forEach((card, idx) => {
          // Keine verschachtelten Cards doppelt indexieren
          if (card.closest('.rounded-xl') && card.closest('.rounded-xl') !== card) {
            return;
          }

          const headingEl = card.querySelector('h4, h5, h6, legend, [class*="font-bold"]');
          const descEl = card.querySelector('p, [class*="text-[11px]"], [class*="text-muted"]');
          const title = headingEl ? headingEl.innerText.trim() : '';
          const desc = descEl ? descEl.innerText.trim() : '';

          if (!title && !desc) return;

          // Kontrollen sammeln (Labels, Inputs)
          const labels = Array.from(card.querySelectorAll('label')).map(l => l.innerText.trim()).filter(Boolean);
          const elemId = card.id || (card.querySelector('input, select, textarea, button') || {}).id || `card-${tabKey}-${idx}`;

          if (registeredIds.has(elemId)) return;
          registeredIds.add(elemId);

          items.push({
            tab: tabKey,
            elementId: elemId,
            title: title || `${TAB_METADATA[tabKey].name} - Einstellung`,
            section: TAB_METADATA[tabKey].name,
            description: desc || labels.slice(0, 3).join(' · '),
            keywords: labels
          });
        });
      });
    } catch (e) {
      console.warn('[SettingsSearch] Error during DOM index scan:', e);
    }

    searchIndex = items;
    isIndexing = false;
  }

  /**
   * Behandelt Tastatur-Eingaben im globalen Settings-Suchfeld.
   */
  function handleSettingsGlobalSearch(query) {
    activeQuery = (query || '').trim();
    const clearBtn = document.getElementById('settings-global-search-clear-btn');
    if (clearBtn) {
      if (activeQuery) {
        clearBtn.classList.remove('hidden');
      } else {
        clearBtn.classList.add('hidden');
      }
    }

    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      performSearch(activeQuery);
    }, 120);
  }

  /**
   * Führt die Suche aus und rendert die Ergebnisse.
   */
  function performSearch(query) {
    const resultsPane = document.getElementById('settings-tab-search-results');
    const resultsList = document.getElementById('settings-search-results-list');
    const countBadge = document.getElementById('settings-search-count-badge');
    const queryText = document.getElementById('settings-search-query-text');

    if (!resultsPane || !resultsList) return;

    if (!query || query.length < 2) {
      // Wenn Suchbegriff gelöscht oder zu kurz: Trefferbereich ausblenden und vorherigen Tab wieder anzeigen
      resultsPane.classList.add('hidden');
      const activeTab = window.activeSettingsTab || 'kernel';
      const activePane = document.getElementById(`settings-tab-${activeTab}`);
      if (activePane) {
        activePane.classList.remove('hidden');
      }
      return;
    }

    // Stelle sicher, dass der Index existiert
    if (!searchIndex || searchIndex.length === 0) {
      buildSearchIndex();
    }

    // Verstecke alle normalen Tab-Panes
    const allTabs = Object.keys(TAB_METADATA);
    allTabs.forEach(t => {
      const p = document.getElementById(`settings-tab-${t}`);
      if (p) p.classList.add('hidden');
    });

    // Zeige das Suchergebnis-Pane
    resultsPane.classList.remove('hidden');
    if (queryText) queryText.textContent = query;

    const q = query.toLowerCase();
    const words = q.split(/\s+/).filter(Boolean);

    // Scoring & Filtering
    const matches = [];
    for (const item of searchIndex) {
      let score = 0;
      const titleLower = item.title.toLowerCase();
      const descLower = item.description.toLowerCase();
      const sectionLower = item.section.toLowerCase();
      const keywordsLower = (item.keywords || []).map(k => k.toLowerCase());

      for (const word of words) {
        if (titleLower.includes(word)) score += 15;
        if (keywordsLower.some(k => k.includes(word))) score += 12;
        if (sectionLower.includes(word)) score += 6;
        if (descLower.includes(word)) score += 4;
      }

      if (score > 0) {
        matches.push({ item, score });
      }
    }

    // Sortiere nach Relevanz (höchster Score zuerst)
    matches.sort((a, b) => b.score - a.score);

    if (countBadge) {
      countBadge.textContent = `${matches.length} Treffer`;
      countBadge.className = matches.length > 0 
        ? 'px-2.5 py-0.5 rounded-full text-xs font-mono font-bold bg-sky-500/15 text-sky-600 dark:text-sky-400 border border-sky-500/30'
        : 'px-2.5 py-0.5 rounded-full text-xs font-mono font-bold bg-zinc-500/15 text-zinc-500 border border-zinc-500/30';
    }

    if (matches.length === 0) {
      resultsList.innerHTML = `
        <div class="border border-[var(--border)] rounded-2xl p-8 bg-[var(--background)] text-center space-y-3">
          <div class="w-12 h-12 rounded-2xl bg-zinc-500/10 text-zinc-400 flex items-center justify-center mx-auto text-xl">
            🔍
          </div>
          <div class="space-y-1">
            <h4 class="font-bold text-sm text-[var(--foreground)]">Keine passenden Einstellungen gefunden</h4>
            <p class="text-xs text-[var(--muted-foreground)] max-w-md mx-auto">
              Für „${escapeHtml(query)}“ konnte kein Eintrag zugeordnet werden. Versuche Begriffe wie <span class="font-mono text-sky-500">Sprache</span>, <span class="font-mono text-sky-500">Auth</span>, <span class="font-mono text-sky-500">Model</span>, <span class="font-mono text-sky-500">API</span> oder <span class="font-mono text-sky-500">Docker</span>.
            </p>
          </div>
          <button type="button" onclick="window.clearSettingsGlobalSearch()" class="px-4 py-2 rounded-xl bg-[var(--secondary)] hover:bg-[var(--secondary)]/80 text-xs font-mono font-bold border border-[var(--border)] transition cursor-pointer">
            Suche zurücksetzen
          </button>
        </div>
      `;
      return;
    }

    // Treffer rendern
    resultsList.innerHTML = matches.map(({ item }) => {
      const meta = TAB_METADATA[item.tab] || { name: item.tab.toUpperCase(), icon: 'settings', color: 'text-zinc-400' };
      const highlightedTitle = highlightMatch(item.title, words);
      const highlightedDesc = highlightMatch(item.description, words);
      const highlightedSec = highlightMatch(item.section, words);

      return `
        <div onclick="window.jumpToSetting('${item.tab}', '${item.elementId || ''}')" 
             class="border border-[var(--border)] hover:border-sky-500/50 rounded-xl p-4 bg-[var(--card)] hover:bg-[var(--secondary)]/40 transition-all cursor-pointer group shadow-2xs space-y-2">
          <div class="flex items-center justify-between gap-3">
            <div class="flex items-center gap-2 flex-wrap">
              <span class="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-[var(--secondary)] border border-[var(--border)] ${meta.color} flex items-center gap-1">
                <i data-lucide="${meta.icon}" class="w-3 h-3"></i>
                ${meta.name}
              </span>
              <span class="text-[11px] font-mono text-[var(--muted-foreground)]">
                › ${highlightedSec}
              </span>
            </div>
            <button type="button" class="shrink-0 text-xs font-mono font-bold text-sky-600 dark:text-sky-400 group-hover:translate-x-0.5 transition flex items-center gap-1">
              <span>Öffnen</span>
              <span>→</span>
            </button>
          </div>
          <div>
            <h4 class="text-sm font-bold text-[var(--foreground)] group-hover:text-sky-600 dark:group-hover:text-sky-400 transition-colors">
              ${highlightedTitle}
            </h4>
            <p class="text-xs text-[var(--muted-foreground)] mt-1 line-clamp-2 leading-relaxed">
              ${highlightedDesc}
            </p>
          </div>
        </div>
      `;
    }).join('');

    if (window.lucide && typeof window.lucide.createIcons === 'function') {
      window.lucide.createIcons();
    }
  }

  /**
   * Markiert gefundene Suchwörter mit einem visuellen <mark>-Tag.
   */
  function highlightMatch(text, words) {
    if (!text) return '';
    let escaped = escapeHtml(text);
    for (const word of words) {
      if (!word) continue;
      const regex = new RegExp(`(${escapeRegex(word)})`, 'gi');
      escaped = escaped.replace(regex, '<mark class="bg-amber-400/30 text-amber-900 dark:text-amber-200 rounded px-1 font-semibold">$1</mark>');
    }
    return escaped;
  }

  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function escapeRegex(str) {
    return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  }

  /**
   * Setzt die Suche zurück und stellt den zuletzt aktiven Tab wieder her.
   */
  function clearSettingsGlobalSearch() {
    activeQuery = '';
    const input = document.getElementById('settings-global-search-input');
    if (input) input.value = '';

    const clearBtn = document.getElementById('settings-global-search-clear-btn');
    if (clearBtn) clearBtn.classList.add('hidden');

    const resultsPane = document.getElementById('settings-tab-search-results');
    if (resultsPane) resultsPane.classList.add('hidden');

    const targetTab = window.activeSettingsTab || 'kernel';
    if (typeof window.setSettingsTab === 'function') {
      window.setSettingsTab(targetTab);
    } else {
      const p = document.getElementById(`settings-tab-${targetTab}`);
      if (p) p.classList.remove('hidden');
    }
  }

  /**
   * Springt direkt zu einer Einstellung in ihrem Original-Tab und hebt sie hervor.
   */
  function jumpToSetting(tabKey, elementId) {
    // 1. Suche zurücksetzen
    const input = document.getElementById('settings-global-search-input');
    if (input) input.value = '';
    const clearBtn = document.getElementById('settings-global-search-clear-btn');
    if (clearBtn) clearBtn.classList.add('hidden');
    const resultsPane = document.getElementById('settings-tab-search-results');
    if (resultsPane) resultsPane.classList.add('hidden');

    // 2. Tab aktivieren
    if (typeof window.setSettingsTab === 'function') {
      window.setSettingsTab(tabKey);
    }

    // 3. Nach kurzer Render-Pause zum Element scrollen & hervorheben
    setTimeout(() => {
      let targetEl = elementId ? document.getElementById(elementId) : null;
      if (!targetEl && elementId) {
        targetEl = document.querySelector(`[data-setting-id="${elementId}"]`);
      }
      if (!targetEl) {
        targetEl = document.getElementById(`settings-tab-${tabKey}`);
      }

      if (targetEl) {
        targetEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
        // Aufmerksamkeits-Puls
        targetEl.classList.add('ring-2', 'ring-sky-500', 'ring-offset-4', 'ring-offset-[var(--card)]', 'duration-300');
        setTimeout(() => {
          targetEl.classList.remove('ring-2', 'ring-sky-500', 'ring-offset-4', 'ring-offset-[var(--card)]');
        }, 2500);

        if (['INPUT', 'SELECT', 'TEXTAREA'].includes(targetEl.tagName)) {
          try { targetEl.focus(); } catch (e) {}
        }
      }
    }, 120);
  }

  /**
   * Tastatur-Shortcuts im Suchfeld (Enter = Erster Treffer, Esc = Schließen).
   */
  function handleSettingsGlobalSearchKeydown(event) {
    if (event.key === 'Escape') {
      event.preventDefault();
      clearSettingsGlobalSearch();
    } else if (event.key === 'Enter') {
      event.preventDefault();
      const firstCard = document.querySelector('#settings-search-results-list > div');
      if (firstCard) {
        firstCard.click();
      }
    }
  }

  // Globaler Keyboard-Shortcut: '/' oder 'Ctrl+F' im geöffneten Settings-Modal fokussiert die Suche
  document.addEventListener('keydown', (e) => {
    const modal = document.getElementById('system-settings-modal');
    if (!modal || modal.classList.contains('hidden')) return;

    if (e.key === '/' && !['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement.tagName)) {
      e.preventDefault();
      const input = document.getElementById('settings-global-search-input');
      if (input) {
        input.focus();
        input.select();
      }
    }
  });

  // Exportiere Funktionen nach window
  window.handleSettingsGlobalSearch = handleSettingsGlobalSearch;
  window.handleSettingsGlobalSearchKeydown = handleSettingsGlobalSearchKeydown;
  window.clearSettingsGlobalSearch = clearSettingsGlobalSearch;
  window.jumpToSetting = jumpToSetting;
  window.buildSettingsSearchIndex = buildSearchIndex;

})();
