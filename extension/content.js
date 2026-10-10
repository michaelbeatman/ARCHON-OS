/**
 * Archon CRM - Extension Content Script
 * Fully Automated LinkedIn Profile & Contact Info Scraper
 */

(function () {
  'use strict';

  let lastProcessedUrl = '';
  let autoSyncDebounceTimer = null;

  // Robust multi-fallback DOM Extractor for LinkedIn profiles
  function extractProfileData() {
    // 1. Name extraction
    let fullName = '';
    const nameSelectors = [
      'h1.text-heading-xlarge',
      'h1.v-card-full-name',
      'main section h1',
      'h1.inline.t-24',
      '.pv-top-card--list h1',
      '.pv-text-details__left-panel h1'
    ];
    for (const sel of nameSelectors) {
      const el = document.querySelector(sel);
      if (el && el.innerText && el.innerText.trim()) {
        fullName = el.innerText.trim();
        break;
      }
    }

    if (!fullName) return null;

    const nameParts = fullName.split(/\s+/);
    const vorname = nameParts[0] || '';
    const nachname = nameParts.length > 1 ? nameParts.slice(1).join(' ') : '';

    // 2. Position / Headline extraction
    let position = '';
    const headlineSelectors = [
      'div.text-body-medium.break-words',
      '.pv-top-card--list .text-body-medium',
      '.pv-text-details__left-panel .text-body-medium',
      'main section .text-body-medium'
    ];
    for (const sel of headlineSelectors) {
      const el = document.querySelector(sel);
      if (el && el.innerText && el.innerText.trim()) {
        position = el.innerText.trim();
        break;
      }
    }

    // 3. Location / Region extraction
    let region = '';
    const regionSelectors = [
      'span.text-body-small.inline.t-black--light.break-words',
      '.pv-text-details__left-panel .text-body-small',
      '.pv-top-card--list-bullet > li:first-child'
    ];
    for (const sel of regionSelectors) {
      const el = document.querySelector(sel);
      if (el && el.innerText && el.innerText.trim()) {
        region = el.innerText.trim();
        break;
      }
    }

    // 4. Company extraction
    let unternehmen = '';
    const companySelectors = [
      'button[aria-label*="Current company"]',
      'button[aria-label*="Derzeitiges Unternehmen"]',
      '.pv-text-details__right-panel-item span',
      '.inline-show-more-text',
      'img[alt*="logo"] + span'
    ];
    for (const sel of companySelectors) {
      const el = document.querySelector(sel);
      if (el && el.innerText && el.innerText.trim()) {
        unternehmen = el.innerText.trim();
        break;
      }
    }

    if (!unternehmen && position) {
      if (position.includes(' bei ')) unternehmen = position.split(' bei ')[1].split('|')[0].trim();
      else if (position.includes(' at ')) unternehmen = position.split(' at ')[1].split('|')[0].trim();
    }

    // 5. Profile Picture URL
    let profilbild = '';
    const imgSelectors = [
      'img.pv-top-card-profile-picture__image--show',
      'img.pv-top-card-profile-picture__image',
      '.pv-top-card__photo img',
      'img.presence-entity__image',
      'img[alt*="profile picture"]',
      'img[alt*="Profilbild"]'
    ];
    for (const sel of imgSelectors) {
      const img = document.querySelector(sel);
      if (img && img.src && !img.src.startsWith('data:image/svg')) {
        profilbild = img.src;
        break;
      }
    }

    let linkedinUrl = window.location.href.split('?')[0].split('#')[0];
    if (linkedinUrl.endsWith('/')) linkedinUrl = linkedinUrl.slice(0, -1);

    return {
      vorname,
      nachname,
      name: fullName,
      position,
      rolle: position,
      unternehmen,
      region,
      linkedin_url: linkedinUrl,
      profilbild,
      tags: ['LinkedIn Import']
    };
  }

  // Extract Modal Contact Info (Email, Phone, Websites, Address)
  function extractContactModalData() {
    const modal = document.querySelector('.artdeco-modal, .pv-contact-info');
    if (!modal) return null;

    const data = {};

    // Email
    const emailEl = modal.querySelector('a[href^="mailto:"]');
    if (emailEl) data.email = emailEl.innerText.trim() || emailEl.href.replace('mailto:', '').trim();

    // Phone
    const phoneEl = modal.querySelector('.ci-phone .t-14, .pv-contact-info__contact-type.ci-phone span');
    if (phoneEl) data.telefon_1 = phoneEl.innerText.trim();

    // Website
    const websiteEl = modal.querySelector('.ci-websites a, .pv-contact-info__contact-type.ci-websites a');
    if (websiteEl) data.webseite = websiteEl.href || websiteEl.innerText.trim();

    // Address
    const addressEl = modal.querySelector('.ci-address .t-14, .pv-contact-info__contact-type.ci-address span');
    if (addressEl) data.adresse = addressEl.innerText.trim();

    return Object.keys(data).length > 0 ? data : null;
  }

  // Toast Notification UI
  function showToast(message, isSuccess = true) {
    let toast = document.getElementById('archon-crm-toast');
    if (!toast) {
      toast = document.createElement('div');
      toast.id = 'archon-crm-toast';
      toast.style.cssText = `
        position: fixed;
        bottom: 20px;
        right: 20px;
        z-index: 10000;
        padding: 12px 18px;
        border-radius: 10px;
        font-family: system-ui, -apple-system, sans-serif;
        font-size: 13px;
        font-weight: 600;
        color: #ffffff;
        box-shadow: 0 8px 24px rgba(0,0,0,0.35);
        backdrop-filter: blur(8px);
        transition: all 0.3s ease;
      `;
      document.body.appendChild(toast);
    }

    toast.style.background = isSuccess ? 'rgba(16, 185, 129, 0.95)' : 'rgba(239, 68, 68, 0.95)';
    toast.innerText = message;
    toast.style.opacity = '1';
    toast.style.display = 'block';

    setTimeout(() => {
      toast.style.opacity = '0';
      setTimeout(() => { toast.style.display = 'none'; }, 300);
    }, 4000);
  }

  // Trigger Automatic Auto-Sync for Profile Page
  function autoSyncProfile() {
    if (!window.location.href.includes('/in/')) return;

    const currentUrl = window.location.href.split('?')[0].split('#')[0];
    const profileData = extractProfileData();

    if (!profileData || !profileData.name) return;

    // Avoid redundant posts for same URL in same view
    if (lastProcessedUrl === currentUrl + profileData.name) return;
    lastProcessedUrl = currentUrl + profileData.name;

    chrome.runtime.sendMessage({ action: 'SAVE_PROFILE', data: profileData }, (response) => {
      if (chrome.runtime.lastError) {
        console.warn('[Archon CRM] Sync error:', chrome.runtime.lastError.message);
        return;
      }
      if (response && response.success) {
        showToast(`⚡ Archon CRM: ${profileData.name} automatisch erfasst`, true);
      }
    });
  }

  // Observe DOM for Contact Info modal openings
  function setupModalObserver() {
    const observer = new MutationObserver(() => {
      const contactData = extractContactModalData();
      if (contactData) {
        const baseData = extractProfileData() || {};
        const fullPayload = { ...baseData, ...contactData };

        chrome.runtime.sendMessage({ action: 'SAVE_PROFILE', data: fullPayload }, (response) => {
          if (response && response.success) {
            showToast(`⚡ Archon CRM: Kontaktdaten (E-Mail / Tel) ergänzt!`, true);
          }
        });
      }
    });

    observer.observe(document.body, { childList: true, subtree: true });
  }

  // Initialize auto-sync logic
  function initAutoSync() {
    clearTimeout(autoSyncDebounceTimer);
    autoSyncDebounceTimer = setTimeout(autoSyncProfile, 1200);
  }

  // Handle SPA Route changes & initial load
  let lastUrl = location.href;
  new MutationObserver(() => {
    if (location.href !== lastUrl) {
      lastUrl = location.href;
      lastProcessedUrl = '';
      if (location.href.includes('/in/')) {
        initAutoSync();
      }
    }
  }).observe(document.body, { childList: true, subtree: true });

  // Initial trigger & observer setup
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      initAutoSync();
      setupModalObserver();
    });
  } else {
    initAutoSync();
    setupModalObserver();
  }

  // Also listen for manual trigger from popup
  chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === 'SCRAPE_PROFILE') {
      lastProcessedUrl = '';
      autoSyncProfile();
      sendResponse({ status: 'success' });
    }
    return true;
  });
})();
