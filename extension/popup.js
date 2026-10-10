/**
 * Archon CRM - Extension Popup Logic
 */

document.addEventListener('DOMContentLoaded', () => {
  const statusDot = document.getElementById('statusDot');
  const statusText = document.getElementById('statusText');
  const syncBtn = document.getElementById('syncBtn');

  // Health check to PocketBase API on port 8090
  fetch('http://127.0.0.1:8090/api/health')
    .then(res => {
      if (res.ok) {
        statusDot.classList.add('active');
        statusText.innerText = 'PocketBase Verbunden (8090)';
      } else {
        statusDot.classList.remove('active');
        statusText.innerText = 'PocketBase Fehler (8090)';
      }
    })
    .catch(() => {
      statusDot.classList.remove('active');
      statusText.innerText = 'PocketBase Offline (8090)';
    });

  // Event listener for manual profile sync button
  syncBtn.addEventListener('click', () => {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      if (tabs[0] && tabs[0].id) {
        syncBtn.innerText = 'Scanne Profil...';
        chrome.tabs.sendMessage(tabs[0].id, { action: 'SCRAPE_PROFILE' }, (res) => {
          setTimeout(() => {
            syncBtn.innerText = 'Profil manuell scannen';
          }, 2000);
        });
      }
    });
  });
});
