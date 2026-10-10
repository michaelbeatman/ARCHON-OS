/**
 * Archon CRM - LinkedIn Companion Popup Logic
 */

document.addEventListener('DOMContentLoaded', async () => {
  const statusIndicator = document.getElementById('status-indicator');
  const statusText = document.getElementById('status-text');
  const tabBtns = document.querySelectorAll('.tab-btn');
  const tabContents = document.querySelectorAll('.tab-content');

  const currentProfileCard = document.getElementById('current-profile-card');
  const searchInput = document.getElementById('search-input');
  const searchBtn = document.getElementById('search-btn');
  const searchResults = document.getElementById('search-results');

  const pbUrlInput = document.getElementById('pb-url-input');
  const saveSettingsBtn = document.getElementById('save-settings-btn');
  const settingsFeedback = document.getElementById('settings-feedback');

  // Load configured PocketBase URL
  const storage = await chrome.storage.local.get(['pbUrl']);
  if (storage.pbUrl) {
    pbUrlInput.value = storage.pbUrl;
  }

  // 1. Health Check Connection to PocketBase
  function checkHealth() {
    chrome.runtime.sendMessage({ type: 'HEALTH_CHECK' }, (res) => {
      if (res && res.success) {
        statusIndicator.className = 'status-indicator online';
        statusText.innerText = `Online (${res.totalRecords} Kontakte)`;
      } else {
        statusIndicator.className = 'status-indicator offline';
        statusText.innerText = 'Offline';
      }
    });
  }

  checkHealth();

  // 2. Tab Navigation
  tabBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      tabBtns.forEach(b => b.classList.remove('active'));
      tabContents.forEach(c => c.classList.remove('active'));

      btn.classList.add('active');
      const targetTab = document.getElementById(btn.dataset.tab);
      if (targetTab) targetTab.classList.add('active');
    });
  });

  // 3. Inspect Current Active Tab (LinkedIn Profile)
  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    const activeTab = tabs[0];
    if (activeTab && activeTab.url && activeTab.url.includes('linkedin.com/in/')) {
      chrome.tabs.sendMessage(activeTab.id, { action: 'GET_DOM_PROFILE' }, (res) => {
        // Pass BOTH url and name to the service worker so the name-first,
        // umlaut-safe lookup can find existing contacts reliably.
        let profileName = null;
        if (res && res.profile && res.profile.name) {
          profileName = res.profile.name;
        }
        chrome.runtime.sendMessage({ type: 'CHECK_CONTACT', linkedinUrl: activeTab.url, name: profileName }, (checkRes) => {
          if (checkRes && checkRes.success && checkRes.record) {
            const rec = checkRes.record;
            currentProfileCard.innerHTML = `
              <div style="display: flex; gap: 12px; align-items: center;">
                <div style="flex: 1;">
                  <div class="profile-title">${rec.name}</div>
                  <div class="profile-subtitle">${rec.rolle || 'Keine Rolle'}</div>
                  <div class="profile-company">${rec.unternehmen || 'Kein Unternehmen'}</div>
                </div>
              </div>
              <div style="margin-top: 12px; padding-top: 10px; border-top: 1px solid rgba(255,255,255,0.08); display: flex; justify-content: space-between; align-items: center;">
                <span class="badge" style="background: rgba(34, 197, 94, 0.2); color: #4ade80;">In CRM: ${rec.status}</span>
                <a href="http://localhost:8090/_/#/collections/kontakte/records/${rec.id}" target="_blank" style="color: #38bdf8; font-size: 11px; text-decoration: none;">
                  ↗ In CRM öffnen
                </a>
              </div>
            `;
          } else {
            currentProfileCard.innerHTML = `
              <div class="profile-title">LinkedIn Profil erkannt</div>
              <div class="profile-subtitle">${activeTab.url}</div>
              <p style="margin-top: 10px; font-size: 12px; color: #94a3b8;">
                Dieses Profil ist noch nicht in deiner Archon CRM Datenbank. Nutze den Button auf der Seite zum Speichern!
              </p>
            `;
          }
        });
      });
    } else {
      currentProfileCard.innerHTML = `
        <div style="text-align: center; padding: 12px 0; color: #94a3b8;">
          ℹ️ Kein aktives LinkedIn Profil geöffnet.<br>
          <span style="font-size: 11px;">Navigiere auf <code>linkedin.com/in/...</code> um Kontakte zu importieren.</span>
        </div>
      `;
    }
  });

  // 4. CRM Contact Search
  async function performSearch() {
    const q = searchInput.value.trim();
    if (!q) return;

    searchResults.innerHTML = '<p class="hint">Suche läuft...</p>';

    chrome.runtime.sendMessage({ type: 'SEARCH_CONTACTS', query: q }, (res) => {
      if (res && res.success && res.items.length > 0) {
        searchResults.innerHTML = res.items.map(item => `
          <div class="result-item">
            <div>
              <div class="result-name">${item.name}</div>
              <div class="result-detail">${item.rolle || ''} ${item.unternehmen ? '@ ' + item.unternehmen : ''}</div>
            </div>
            <span class="badge">${item.status}</span>
          </div>
        `).join('');
      } else {
        searchResults.innerHTML = '<p class="hint">Keine Kontakte gefunden.</p>';
      }
    });
  }

  searchBtn.addEventListener('click', performSearch);
  searchInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') performSearch();
  });

  // 5. Save Settings
  saveSettingsBtn.addEventListener('click', async () => {
    const newUrl = pbUrlInput.value.trim();
    if (!newUrl) return;

    await chrome.storage.local.set({ pbUrl: newUrl });
    settingsFeedback.className = 'feedback success';
    settingsFeedback.innerText = '✓ Einstellungen gespeichert!';
    checkHealth();
    setTimeout(() => { settingsFeedback.innerText = ''; }, 2500);
  });
});
